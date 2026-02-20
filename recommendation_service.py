"""
Phase 6: Intelligent Recommendation Service

This service builds intelligent user context from:
1. User preferences (most visited places, preferred ride types, common locations)
2. Recent chat summaries (booking patterns, preferences)
3. Historical patterns (frequency, recency)

The context is injected into the system prompt to enable proactive recommendations
without changing the booking workflow.
"""
import logging
from typing import Optional, Dict, List
from datetime import datetime, timedelta

from preference_extraction import (
    get_most_visited_places,
    get_preferred_ride_types,
    get_common_pickup_locations,
    get_common_dropoff_locations,
    get_preferred_payment_methods,
    get_user_preferences,
    PREF_TYPE_TIME,
)
from summary_service import get_user_summaries

logger = logging.getLogger(__name__)


def build_user_recommendation_context(user_id: str) -> str:
    """
    Build intelligent user context from preferences and summaries.
    Returns a formatted string that can be injected into the system prompt.
    
    Args:
        user_id: User UUID
        
    Returns:
        Formatted context string, or empty string if no data available
    """
    if not user_id:
        return ""
    
    try:
        context_parts = []
        
        # 1. Most Visited Places (Top 3)
        most_visited = get_most_visited_places(user_id, limit=3)
        if most_visited:
            places = [f"{p['preference_value']} ({p['frequency']}x)" for p in most_visited]
            context_parts.append(f"MOST VISITED PLACES: {', '.join(places)}")
        
        # 2. Preferred Ride Types (Top 2)
        ride_types = get_preferred_ride_types(user_id, limit=2)
        if ride_types:
            types = [f"{r['preference_value']} ({r['frequency']}x)" for r in ride_types]
            context_parts.append(f"PREFERRED RIDE TYPES: {', '.join(types)}")
        
        # 3. Common Pickup Locations (Top 3)
        pickups = get_common_pickup_locations(user_id, limit=3)
        if pickups:
            pickup_list = [f"{p['preference_value']} ({p['frequency']}x)" for p in pickups]
            context_parts.append(f"COMMON PICKUP LOCATIONS: {', '.join(pickup_list)}")
        
        # 4. Common Dropoff Locations (Top 3)
        dropoffs = get_common_dropoff_locations(user_id, limit=3)
        if dropoffs:
            dropoff_list = [f"{d['preference_value']} ({d['frequency']}x)" for d in dropoffs]
            context_parts.append(f"COMMON DROPOFF LOCATIONS: {', '.join(dropoff_list)}")
        
        # 5. Preferred Payment Methods (Top 2)
        payments = get_preferred_payment_methods(user_id, limit=2)
        if payments:
            payment_list = [f"{p['preference_value']} ({p['frequency']}x)" for p in payments]
            context_parts.append(f"PREFERRED PAYMENT METHODS: {', '.join(payment_list)}")
        
        # 6. Time Preferences (if available)
        time_prefs = get_user_preferences(user_id, PREF_TYPE_TIME)
        if time_prefs:
            time_list = [f"{t['preference_value']} ({t['frequency']}x)" for t in time_prefs[:3]]
            context_parts.append(f"PREFERRED TIMES: {', '.join(time_list)}")
        
        # 7. Recent Summaries (Last 3) - Extract key patterns
        summaries = get_user_summaries(user_id, limit=3)
        if summaries:
            summary_insights = []
            for summary in summaries:
                summary_text = summary.get("summary_text", "")
                if summary_text:
                    # Extract key locations and patterns from summary
                    summary_insights.append(summary_text[:200] + "..." if len(summary_text) > 200 else summary_text)
            
            if summary_insights:
                context_parts.append(f"RECENT BOOKING PATTERNS: {' | '.join(summary_insights)}")
        
        # Build final context string
        if context_parts:
            context = "\n\n=== USER PREFERENCES & PATTERNS (Use for intelligent recommendations) ===\n"
            context += "\n".join(context_parts)
            context += "\n\nRECOMMENDATION GUIDELINES:"
            context += "\n- When user mentions a destination, proactively suggest their usual pickup location if it's a common one"
            context += "\n- When user asks for ride type suggestions, prioritize their preferred types"
            context += "\n- When user doesn't specify payment method, suggest their preferred method"
            context += "\n- Reference their most visited places naturally: 'I see you often go to [place]'"
            context += "\n- Use patterns from recent summaries to anticipate needs"
            context += "\n- Be proactive but not pushy - offer suggestions, don't assume"
            context += "\n- If user's request matches a pattern, acknowledge it naturally"
            context += "\n- Example: User says 'Take me to F7 Markaz' → You can say 'I see you often go to F7 Markaz! Would you like me to use your usual pickup at F6 Markaz?'"
            context += "\n- Example: User asks 'What ride type should I choose?' → Suggest their preferred types first"
            context += "\n- Example: User doesn't mention payment → 'Would you like to pay via [preferred method] as usual?'"
            context += "\n\n=== END USER CONTEXT ===\n"
            return context
        
        return ""
    
    except Exception as e:
        logger.error(f"Failed to build recommendation context for user {user_id}: {e}")
        return ""


def get_smart_suggestions(user_id: str, user_message: str) -> Dict[str, List[str]]:
    """
    Generate smart suggestions based on user message and preferences.
    Returns a dictionary with suggestion categories.
    
    Args:
        user_id: User UUID
        user_message: Current user message
        
    Returns:
        Dictionary with suggestion categories (pickup, dropoff, ride_type, payment)
    """
    if not user_id:
        return {}
    
    suggestions = {
        "pickup": [],
        "dropoff": [],
        "ride_type": [],
        "payment": [],
    }
    
    try:
        user_lower = user_message.lower()
        
        # If user mentions a dropoff but not pickup, suggest common pickups
        if any(word in user_lower for word in ["to", "go to", "dropoff", "destination"]):
            pickups = get_common_pickup_locations(user_id, limit=2)
            if pickups:
                suggestions["pickup"] = [p["preference_value"] for p in pickups]
        
        # If user mentions a pickup but not dropoff, suggest common dropoffs
        if any(word in user_lower for word in ["from", "pickup", "pick up"]):
            dropoffs = get_common_dropoff_locations(user_id, limit=2)
            if dropoffs:
                suggestions["dropoff"] = [d["preference_value"] for d in dropoffs]
        
        # If user asks about ride types, suggest preferred ones
        if any(word in user_lower for word in ["ride type", "which ride", "what ride", "suggest"]):
            ride_types = get_preferred_ride_types(user_id, limit=3)
            if ride_types:
                suggestions["ride_type"] = [r["preference_value"] for r in ride_types]
        
        # If user is booking but hasn't mentioned payment, suggest preferred method
        if any(word in user_lower for word in ["book", "ride", "go"]) and "payment" not in user_lower:
            payments = get_preferred_payment_methods(user_id, limit=1)
            if payments:
                suggestions["payment"] = [p["preference_value"] for p in payments]
        
    except Exception as e:
        logger.error(f"Failed to generate smart suggestions for user {user_id}: {e}")
    
    return suggestions


def should_suggest_pickup(user_id: str, user_message: str) -> bool:
    """
    Determine if we should suggest a pickup location based on user message.
    
    Returns:
        True if user mentioned dropoff but not pickup
    """
    if not user_id:
        return False
    
    user_lower = user_message.lower()
    has_dropoff = any(word in user_lower for word in ["to", "go to", "dropoff", "destination"])
    has_pickup = any(word in user_lower for word in ["from", "pickup", "pick up", "current location"])
    
    return has_dropoff and not has_pickup


def get_recommended_pickup(user_id: str) -> Optional[str]:
    """
    Get the most common pickup location for the user.
    
    Returns:
        Most common pickup location address, or None
    """
    if not user_id:
        return None
    
    try:
        pickups = get_common_pickup_locations(user_id, limit=1)
        if pickups:
            return pickups[0]["preference_value"]
    except Exception as e:
        logger.error(f"Failed to get recommended pickup for user {user_id}: {e}")
    
    return None


def get_recommended_dropoff(user_id: str) -> Optional[str]:
    """
    Get the most common dropoff location for the user.
    
    Returns:
        Most common dropoff location address, or None
    """
    if not user_id:
        return None
    
    try:
        dropoffs = get_common_dropoff_locations(user_id, limit=1)
        if dropoffs:
            return dropoffs[0]["preference_value"]
    except Exception as e:
        logger.error(f"Failed to get recommended dropoff for user {user_id}: {e}")
    
    return None


def get_recommended_ride_type(user_id: str) -> Optional[str]:
    """
    Get the most preferred ride type for the user.
    
    Returns:
        Most preferred ride type, or None
    """
    if not user_id:
        return None
    
    try:
        ride_types = get_preferred_ride_types(user_id, limit=1)
        if ride_types:
            return ride_types[0]["preference_value"]
    except Exception as e:
        logger.error(f"Failed to get recommended ride type for user {user_id}: {e}")
    
    return None


def get_recommended_payment_method(user_id: str) -> Optional[str]:
    """
    Get the most preferred payment method for the user.
    
    Returns:
        Most preferred payment method, or None
    """
    if not user_id:
        return None
    
    try:
        payments = get_preferred_payment_methods(user_id, limit=1)
        if payments:
            return payments[0]["preference_value"]
    except Exception as e:
        logger.error(f"Failed to get recommended payment method for user {user_id}: {e}")
    
    return None
