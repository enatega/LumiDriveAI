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
from utils import strip_asterisks
import json


class BookingState(TypedDict):
    """State for the booking workflow"""
    messages: Annotated[list, add_messages]
    pickup_place: str | None
    dropoff_place: str | None
    ride_type: str | None
    stops: list[str] | None  # List of stop place names
    pickup_coords: dict | None  # {"lat": float, "lng": float, "address": str}
    dropoff_coords: dict | None
    stops_coords: list[dict] | None  # List of {"lat": float, "lng": float, "address": str, "order": int}
    ride_type_set: bool
    booking_complete: bool
    error: str | None


def parse_booking_intent(state: BookingState) -> BookingState:
    """
    Parse booking intent from state.
    Since the assistant already extracts all information intelligently,
    we simply pass through the state if locations are already set.
    Otherwise, we rely on the assistant to extract information before calling this workflow.
    """
    # If pickup_place and dropoff_place are already set (from process_booking_with_details),
    # use the existing values - no parsing needed
    if state.get("pickup_place") and state.get("dropoff_place"):
        return state
    
    # If locations are not set, this workflow expects the assistant to have extracted
    # the information before calling process_booking_with_details.
    # Return state as-is - the workflow will ask user for missing info if needed.
    return state


def _parse_coordinates(place_str: str) -> dict | None:
    """
    Parse coordinates from string formats like:
    - "31.5204,74.3587" (lat,lng)
    - "Coordinates (31.5204, 74.3587)"
    - "(31.5204, 74.3587)"
    Returns {"lat": float, "lng": float} or None if not coordinates
    """
    import re
    
    # Try to extract lat,lng from various formats
    # Pattern: (lat, lng) or lat,lng
    patterns = [
        r"\(?\s*([+-]?\d+\.?\d*)\s*,\s*([+-]?\d+\.?\d*)\s*\)?",  # (lat, lng) or lat,lng
        r"([+-]?\d+\.?\d*)\s*,\s*([+-]?\d+\.?\d*)",  # lat, lng
    ]
    
    for pattern in patterns:
        match = re.search(pattern, place_str)
        if match:
            try:
                lat = float(match.group(1))
                lng = float(match.group(2))
                # Validate reasonable coordinate ranges
                if -90 <= lat <= 90 and -180 <= lng <= 180:
                    return {"lat": lat, "lng": lng}
            except (ValueError, IndexError):
                continue
    
    return None


async def resolve_locations(state: BookingState) -> BookingState:
    """Resolve place names to coordinates using Google Maps API"""
    pickup_place = state.get("pickup_place")
    dropoff_place = state.get("dropoff_place")
    stops = state.get("stops") or []
    
    pickup_coords = None
    dropoff_coords = None
    stops_coords = []
    error = None
    
    if pickup_place:
        # CRITICAL: Check if we have original coordinates stored in STATE (from coordinate-to-address conversion)
        # This ensures we use the exact original coordinates instead of re-resolving, which can change coordinates
        original_pickup_coords = STATE.get("original_pickup_coords")
        if original_pickup_coords and isinstance(original_pickup_coords, dict) and "lat" in original_pickup_coords and "lng" in original_pickup_coords:
            pickup_coords = {
                "lat": original_pickup_coords["lat"],
                "lng": original_pickup_coords["lng"],
                "address": pickup_place,  # Use the address string for display
            }
            print(f"[DEBUG] Using original pickup coordinates from STATE: {pickup_coords}")
            # Clear the stored coordinates after use to prevent reuse
            STATE["original_pickup_coords"] = None
        # Check if pickup_place is already coordinates
        elif _parse_coordinates(pickup_place):
            coords = _parse_coordinates(pickup_place)
            # Already coordinates, use them directly
            pickup_coords = {
                "lat": coords["lat"],
                "lng": coords["lng"],
                "address": pickup_place,  # Use original string as address
            }
        else:
            # Try to resolve as place name
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
        # Check if dropoff_place is already coordinates
        coords = _parse_coordinates(dropoff_place)
        if coords:
            # Already coordinates, use them directly
            dropoff_coords = {
                "lat": coords["lat"],
                "lng": coords["lng"],
                "address": dropoff_place,  # Use original string as address
            }
        else:
            # Try to resolve as place name
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
    
    # Resolve stops if no error so far
    if stops and not error:
        for idx, stop_place in enumerate(stops):
            if not stop_place or not isinstance(stop_place, str):
                continue
            
            # Check if stop_place is already coordinates
            coords = _parse_coordinates(stop_place)
            if coords:
                # Already coordinates, use them directly
                stops_coords.append({
                    "lat": coords["lat"],
                    "lng": coords["lng"],
                    "address": stop_place,
                    "order": idx + 1,
                })
            else:
                # Try to resolve as place name
                try:
                    result = await tool_resolve_place_to_coordinates(stop_place)
                    if result.get("ok"):
                        stops_coords.append({
                            "lat": result["lat"],
                            "lng": result["lng"],
                            "address": result.get("address", stop_place),
                            "order": idx + 1,
                        })
                    else:
                        error = f"Could not resolve stop '{stop_place}': {result.get('error')}"
                        break
                except Exception as e:
                    error = f"Error resolving stop '{stop_place}': {str(e)}"
                    break
    
    return {
        **state,
        "pickup_coords": pickup_coords,
        "dropoff_coords": dropoff_coords,
        "stops_coords": stops_coords if stops_coords else None,
        "error": error,
    }


async def set_trip_and_ride_type(state: BookingState) -> BookingState:
    """Set trip core and ride type, then auto-book"""
    pickup_coords = state.get("pickup_coords")
    dropoff_coords = state.get("dropoff_coords")
    stops_coords = state.get("stops_coords") or []
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
    
    # Set stops if any
    if stops_coords:
        try:
            from assistant import tool_set_stops
            stops_result = await tool_set_stops(stops_coords)
            if not stops_result.get("ok"):
                return {
                    **state,
                    "error": f"Failed to set stops: {stops_result.get('error')}",
                }
        except Exception as e:
            return {
                **state,
                "error": f"Error setting stops: {str(e)}",
            }
    
    # If ride type is provided, set it (which will auto-book)
    if ride_type:
        try:
            ride_result = await tool_set_ride_type(ride_type)
            
            if ride_result.get("ok"):
                # Strip asterisks from assistant output
                message_content = strip_asterisks(ride_result.get("message", "Ride booked successfully!"))
                return {
                    **state,
                    "ride_type_set": True,
                    "booking_complete": True,
                    "messages": state.get("messages", []) + [
                        AIMessage(content=message_content)
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
    
    # Strip asterisks from assistant output
    cleaned_response = strip_asterisks(response)
    return {
        **state,
        "messages": messages + [AIMessage(content=cleaned_response)],
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
            # Strip asterisks from assistant output
            response = strip_asterisks(msg.content or "")
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
    stops: list[str] | None = None,
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
    stops_str = f" with stops at {', '.join(stops)}" if stops else ""
    synthetic_message = f"Book ride from {pickup_place} to {dropoff_place} on {ride_type}{stops_str}"
    
    initial_state: BookingState = {
        "messages": [HumanMessage(content=synthetic_message)],
        "pickup_place": pickup_place,
        "dropoff_place": dropoff_place,
        "ride_type": ride_type,
        "stops": stops or [],
        "pickup_coords": None,
        "dropoff_coords": None,
        "stops_coords": None,
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
            # Strip asterisks from assistant output
            response = strip_asterisks(msg.content or "")
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

