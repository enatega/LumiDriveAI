"""
LangGraph-based autonomous booking workflow.
When user provides complete information (pickup, dropoff, ride type) in one message,
this workflow automatically processes everything and books the ride.
"""
import asyncio
from typing import TypedDict, Annotated, Literal
try:
    from langgraph.graph import StateGraph, END
    from langgraph.graph.message import add_messages
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    # Fallback for when langgraph is not installed
    def add_messages(left, right):
        return left + right if isinstance(right, list) else left + [right]

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from assistant import (
    STATE,
    tool_resolve_place_to_coordinates,
    tool_set_trip_core,
    tool_set_ride_type,
    list_ride_types,
    _normalize_ride_type_name,
)
import json
import re


class BookingState(TypedDict):
    """State for the booking workflow"""
    messages: Annotated[list, add_messages]
    pickup_place: str | None
    dropoff_place: str | None
    ride_type: str | None
    pickup_coords: dict | None  # {"lat": float, "lng": float, "address": str}
    dropoff_coords: dict | None
    ride_type_set: bool
    booking_complete: bool
    error: str | None


def parse_booking_intent(state: BookingState) -> BookingState:
    """
    Parse user message to extract pickup, dropoff, and ride type.
    Handles patterns like:
    - "from X to Y on Z"
    - "X to Y, Z"
    - "I want to book a ride from X to Y on Z"
    - "I want to travel from X to Y on Z"
    """
    messages = state.get("messages", [])
    if not messages:
        return state
    
    # Get the last user message
    last_message = None
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_message = msg.content
            break
    
    if not last_message:
        return state
    
    # Normalize the message
    normalized = last_message.strip()
    
    # Patterns to match (order matters - most specific first)
    patterns = [
        # "I want to book/travel from X to Y on Z"
        r"(?:want to|wanna|need to)\s+(?:book|travel|go)\s+(?:a\s+)?(?:ride|trip)?\s*(?:from)?\s+([^,]+?)\s+(?:to|→)\s+([^,]+?)(?:\s+on\s+|\s*,\s*)([A-Z_\s]+)",
        # "from X to Y on Z" or "from X to Y, Z"
        r"(?:from|pickup|pick up)\s+([^,]+?)\s+(?:to|dropoff|drop off)\s+([^,]+?)(?:\s+on\s+|\s*,\s*)([A-Z_\s]+)",
        # "X to Y on Z"
        r"^([^,]+?)\s+to\s+([^,]+?)(?:\s+on\s+|\s*,\s*)([A-Z_\s]+)",
    ]
    
    pickup = None
    dropoff = None
    ride_type = None
    
    for pattern in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            pickup = match.group(1).strip()
            dropoff = match.group(2).strip()
            ride_type = match.group(3).strip()
            # Normalize ride type (remove extra spaces)
            ride_type = re.sub(r'\s+', ' ', ride_type).strip()
            break
    
    # If no pattern matched, try simpler extraction
    if not pickup:
        # Try "X to Y" pattern
        simple_match = re.search(r"([^,]+?)\s+to\s+([^,]+)", normalized, re.IGNORECASE)
        if simple_match:
            pickup = simple_match.group(1).strip()
            dropoff = simple_match.group(2).strip()
            # Try to find ride type elsewhere in message
            ride_type_patterns = [
                r"(?:on|using|with|ride type|type)\s+([A-Z_]+(?:\s+[A-Z_]+)?)",
                r"(Lumi\s+GO|LUMI\s+GO|LUMI_GO)",
            ]
            for rt_pattern in ride_type_patterns:
                ride_type_match = re.search(rt_pattern, normalized, re.IGNORECASE)
                if ride_type_match:
                    ride_type = ride_type_match.group(1).strip()
                    break
    
    return {
        **state,
        "pickup_place": pickup,
        "dropoff_place": dropoff,
        "ride_type": ride_type,
    }


async def resolve_locations(state: BookingState) -> BookingState:
    """Resolve place names to coordinates using Google Maps API"""
    pickup_place = state.get("pickup_place")
    dropoff_place = state.get("dropoff_place")
    
    pickup_coords = None
    dropoff_coords = None
    error = None
    
    if pickup_place:
        try:
            result = await tool_resolve_place_to_coordinates(pickup_place)
            if result.get("ok"):
                pickup_coords = {
                    "lat": result["lat"],
                    "lng": result["lng"],
                    "address": result["address"],
                }
            else:
                error = f"Could not resolve pickup location: {result.get('error')}"
        except Exception as e:
            error = f"Error resolving pickup: {str(e)}"
    
    if dropoff_place and not error:
        try:
            result = await tool_resolve_place_to_coordinates(dropoff_place)
            if result.get("ok"):
                dropoff_coords = {
                    "lat": result["lat"],
                    "lng": result["lng"],
                    "address": result["address"],
                }
            else:
                error = f"Could not resolve dropoff location: {result.get('error')}"
        except Exception as e:
            error = f"Error resolving dropoff: {str(e)}"
    
    return {
        **state,
        "pickup_coords": pickup_coords,
        "dropoff_coords": dropoff_coords,
        "error": error,
    }


async def set_trip_and_ride_type(state: BookingState) -> BookingState:
    """Set trip core and ride type, then auto-book"""
    pickup_coords = state.get("pickup_coords")
    dropoff_coords = state.get("dropoff_coords")
    ride_type = state.get("ride_type")
    
    if not pickup_coords or not dropoff_coords:
        return {
            **state,
            "error": "Missing pickup or dropoff coordinates",
        }
    
    # Set trip core
    try:
        trip_result = await tool_set_trip_core(
            pickup=pickup_coords,
            dropoff=dropoff_coords,
            pickup_address=pickup_coords.get("address"),
            destination_address=dropoff_coords.get("address"),
        )
        
        if not trip_result.get("ok"):
            return {
                **state,
                "error": f"Failed to set trip: {trip_result.get('error')}",
            }
    except Exception as e:
        return {
            **state,
            "error": f"Error setting trip: {str(e)}",
        }
    
    # If ride type is provided, set it (which will auto-book)
    if ride_type:
        try:
            ride_result = await tool_set_ride_type(ride_type)
            
            if ride_result.get("ok"):
                return {
                    **state,
                    "ride_type_set": True,
                    "booking_complete": True,
                    "messages": state.get("messages", []) + [
                        AIMessage(content=ride_result.get("message", "Ride booked successfully!"))
                    ],
                }
            else:
                return {
                    **state,
                    "error": f"Failed to set ride type: {ride_result.get('error')}",
                }
        except Exception as e:
            return {
                **state,
                "error": f"Error setting ride type: {str(e)}",
            }
    else:
        # No ride type provided - need to ask user
        return {
            **state,
            "ride_type_set": False,
        }


def should_continue(state: BookingState) -> Literal["resolve_locations", "set_trip", "ask_user", "end"]:
    """Determine next step based on state"""
    if state.get("error"):
        return "end"
    
    if state.get("booking_complete"):
        return "end"
    
    # If we have pickup/dropoff places but no coordinates, resolve them
    if state.get("pickup_place") and state.get("dropoff_place") and not state.get("pickup_coords"):
        return "resolve_locations"
    
    # If we have coordinates but haven't set trip, set it
    if state.get("pickup_coords") and state.get("dropoff_coords") and not state.get("ride_type_set"):
        return "set_trip"
    
    # Otherwise, ask user for missing info
    return "ask_user"


def ask_user_for_info(state: BookingState) -> BookingState:
    """Ask user for missing information"""
    messages = state.get("messages", [])
    missing = []
    
    if not state.get("pickup_place"):
        missing.append("pickup location")
    if not state.get("dropoff_place"):
        missing.append("dropoff location")
    if not state.get("ride_type"):
        missing.append("ride type")
    
    if missing:
        response = f"I need a few more details to book your ride. Please provide: {', '.join(missing)}."
    else:
        response = "I'm processing your booking request..."
    
    return {
        **state,
        "messages": messages + [AIMessage(content=response)],
    }


def create_booking_graph():
    """Create the LangGraph workflow for autonomous booking"""
    if not LANGGRAPH_AVAILABLE:
        raise ImportError("langgraph is not installed. Please install it: pip install langgraph")
    
    workflow = StateGraph(BookingState)
    
    # Add nodes (async nodes are automatically handled by LangGraph)
    workflow.add_node("parse_intent", parse_booking_intent)
    workflow.add_node("resolve_locations", resolve_locations)  # async
    workflow.add_node("set_trip", set_trip_and_ride_type)  # async
    workflow.add_node("ask_user", ask_user_for_info)
    
    # Set entry point
    workflow.set_entry_point("parse_intent")
    
    # Add conditional edges
    workflow.add_conditional_edges(
        "parse_intent",
        should_continue,
        {
            "resolve_locations": "resolve_locations",
            "set_trip": "set_trip",
            "ask_user": "ask_user",
            "end": END,
        }
    )
    
    workflow.add_conditional_edges(
        "resolve_locations",
        should_continue,
        {
            "set_trip": "set_trip",
            "ask_user": "ask_user",
            "end": END,
        }
    )
    
    workflow.add_conditional_edges(
        "set_trip",
        should_continue,
        {
            "ask_user": "ask_user",
            "end": END,
        }
    )
    
    workflow.add_edge("ask_user", END)
    
    return workflow.compile()


# Global graph instance
_booking_graph = None


def get_booking_graph():
    """Get or create the booking graph instance"""
    global _booking_graph
    if _booking_graph is None:
        _booking_graph = create_booking_graph()
    return _booking_graph


async def process_booking_request(user_message: str) -> dict:
    """
    Process a complete booking request in one go.
    Returns the final state with booking result.
    """
    graph = get_booking_graph()
    
    initial_state: BookingState = {
        "messages": [HumanMessage(content=user_message)],
        "pickup_place": None,
        "dropoff_place": None,
        "ride_type": None,
        "pickup_coords": None,
        "dropoff_coords": None,
        "ride_type_set": False,
        "booking_complete": False,
        "error": None,
    }
    
    # Run the graph
    final_state = await graph.ainvoke(initial_state)
    
    # Extract the response message
    messages = final_state.get("messages", [])
    response = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            response = msg.content
            break
    
    return {
        "ok": final_state.get("booking_complete", False) and not final_state.get("error"),
        "message": response or final_state.get("error") or "Processing...",
        "error": final_state.get("error"),
        "state": {
            "pickup": final_state.get("pickup_coords"),
            "dropoff": final_state.get("dropoff_coords"),
            "ride_type": final_state.get("ride_type"),
        }
    }


async def process_booking_with_details(
    pickup_place: str,
    dropoff_place: str,
    ride_type: str,
) -> dict:
    """
    Process booking with pre-collected details from the assistant.
    This is called when the assistant has already extracted all required information.
    """
    if not LANGGRAPH_AVAILABLE:
        return {
            "ok": False,
            "error": "LangGraph is not installed. Please install it: pip install langgraph",
        }
    
    graph = get_booking_graph()
    
    # Create a synthetic message for the workflow
    synthetic_message = f"Book ride from {pickup_place} to {dropoff_place} on {ride_type}"
    
    initial_state: BookingState = {
        "messages": [HumanMessage(content=synthetic_message)],
        "pickup_place": pickup_place,
        "dropoff_place": dropoff_place,
        "ride_type": ride_type,
        "pickup_coords": None,
        "dropoff_coords": None,
        "ride_type_set": False,
        "booking_complete": False,
        "error": None,
    }
    
    # Run the graph
    final_state = await graph.ainvoke(initial_state)
    
    # Extract the response message
    messages = final_state.get("messages", [])
    response = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            response = msg.content
            break
    
    return {
        "ok": final_state.get("booking_complete", False) and not final_state.get("error"),
        "message": response or final_state.get("error") or "Processing...",
        "error": final_state.get("error"),
        "state": {
            "pickup": final_state.get("pickup_coords"),
            "dropoff": final_state.get("dropoff_coords"),
            "ride_type": final_state.get("ride_type"),
        }
    }

