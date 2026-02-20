"""
Phase 5: Dynamic User Preference Extraction Service

This service extracts user preferences from multiple sources:
1. Tool call results (structured data - most reliable)
2. User messages (LLM + regex extraction)
3. Assistant responses (booking confirmations, etc.)

Uses both pattern matching and LLM for dynamic, flexible extraction.
"""
import logging
import re
import json
from typing import List, Dict, Optional, Any
from datetime import datetime
from openai import OpenAI
import os
from dotenv import load_dotenv

from database import get_cursor

load_dotenv()
logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("MODEL", "gpt-4o-mini")

# Preference types
PREF_TYPE_MOST_VISITED = "most_visited_place"
PREF_TYPE_RIDE_TYPE = "preferred_ride_type"
PREF_TYPE_PICKUP = "common_pickup"
PREF_TYPE_DROPOFF = "common_dropoff"
PREF_TYPE_TIME = "preferred_time"
PREF_TYPE_PAYMENT = "preferred_payment"
PREF_TYPE_STOP = "common_stop"
PREF_TYPE_OTHER = "other"

# Ride type normalization
RIDE_TYPE_MAPPING = {
    "lumi go": "LUMI_GO",
    "lumi_go": "LUMI_GO",
    "lumi-go": "LUMI_GO",
    "lumi plus": "LUMI_PLUS",
    "lumi_plus": "LUMI_PLUS",
    "lumi-plus": "LUMI_PLUS",
    "lumi xl": "LUMI_XL",
    "lumi_xl": "LUMI_XL",
    "lumi-xl": "LUMI_XL",
    "courier": "Courier",
    "courier service": "Courier",
}

# Payment method normalization
PAYMENT_MAPPING = {
    "wallet": "WALLET",
    "cash": "CASH",
    "card": "CARD",
    "credit card": "CARD",
    "debit card": "CARD",
}


def normalize_ride_type(ride_type: str) -> str:
    """Normalize ride type to standard format"""
    if not ride_type:
        return ""
    ride_lower = ride_type.strip().lower()
    return RIDE_TYPE_MAPPING.get(ride_lower, ride_type.upper())


def normalize_payment_method(payment: str) -> str:
    """Normalize payment method to standard format"""
    if not payment:
        return ""
    payment_lower = payment.strip().lower()
    return PAYMENT_MAPPING.get(payment_lower, payment.upper())


def extract_preferences_from_tool_result(
    user_id: str, tool_name: str, tool_result: Dict[str, Any]
) -> None:
    """
    Extract preferences from tool call results (structured data).
    This is the most reliable source of preference data.
    """
    if not tool_result or not isinstance(tool_result, dict):
        return

    try:
        # Extract from book_ride_with_details tool
        if tool_name == "book_ride_with_details":
            pickup_place = tool_result.get("pickup_place") or tool_result.get("pickup_address")
            dropoff_place = tool_result.get("dropoff_place") or tool_result.get("destination_address")
            ride_type = tool_result.get("ride_type")
            payment_via = tool_result.get("payment_via")
            stops = tool_result.get("stops", [])

            if pickup_place:
                update_preference(
                    user_id, PREF_TYPE_PICKUP, pickup_place, pickup_place
                )

            if dropoff_place:
                update_preference(
                    user_id, PREF_TYPE_DROPOFF, dropoff_place, dropoff_place
                )
                # Also track as most visited place
                update_preference(
                    user_id, PREF_TYPE_MOST_VISITED, dropoff_place, dropoff_place
                )

            if ride_type:
                normalized = normalize_ride_type(ride_type)
                if normalized:
                    update_preference(
                        user_id, PREF_TYPE_RIDE_TYPE, normalized, normalized
                    )

            if payment_via:
                normalized = normalize_payment_method(payment_via)
                if normalized:
                    update_preference(
                        user_id, PREF_TYPE_PAYMENT, normalized, normalized
                    )

            # Extract stops
            if stops and isinstance(stops, list):
                for stop in stops:
                    stop_place = stop if isinstance(stop, str) else stop.get("place") or stop.get("address")
                    if stop_place:
                        update_preference(
                            user_id, PREF_TYPE_STOP, stop_place, stop_place
                        )

        # Extract from set_trip_core tool
        elif tool_name == "set_trip_core":
            pickup = tool_result.get("pickup")
            dropoff = tool_result.get("dropoff")
            pickup_address = tool_result.get("pickup_address")
            destination_address = tool_result.get("destination_address")
            ride_type = tool_result.get("rideTypeName") or tool_result.get("ride_type")

            if pickup_address:
                update_preference(
                    user_id, PREF_TYPE_PICKUP, pickup_address, pickup_address
                )
            elif pickup and isinstance(pickup, dict):
                address = pickup.get("address")
                if address:
                    update_preference(
                        user_id, PREF_TYPE_PICKUP, address, address
                    )

            if destination_address:
                update_preference(
                    user_id, PREF_TYPE_DROPOFF, destination_address, destination_address
                )
                update_preference(
                    user_id, PREF_TYPE_MOST_VISITED, destination_address, destination_address
                )
            elif dropoff and isinstance(dropoff, dict):
                address = dropoff.get("address")
                if address:
                    update_preference(
                        user_id, PREF_TYPE_DROPOFF, address, address
                    )
                    update_preference(
                        user_id, PREF_TYPE_MOST_VISITED, address, address
                    )

            if ride_type:
                normalized = normalize_ride_type(ride_type)
                if normalized:
                    update_preference(
                        user_id, PREF_TYPE_RIDE_TYPE, normalized, normalized
                    )

        # Extract from set_ride_type tool
        elif tool_name == "set_ride_type":
            ride_type = tool_result.get("ride_type") or tool_result.get("rideTypeName")
            if ride_type:
                normalized = normalize_ride_type(ride_type)
                if normalized:
                    update_preference(
                        user_id, PREF_TYPE_RIDE_TYPE, normalized, normalized
                    )

        # Extract from create_request_and_poll tool
        elif tool_name == "create_request_and_poll":
            payment_via = tool_result.get("payment_via")
            if payment_via:
                normalized = normalize_payment_method(payment_via)
                if normalized:
                    update_preference(
                        user_id, PREF_TYPE_PAYMENT, normalized, normalized
                    )

    except Exception as e:
        logger.error(f"Error extracting preferences from tool result: {e}")


def extract_preferences_from_message_llm(
    user_id: str, role: str, content: str
) -> None:
    """
    Use LLM to extract preferences from user/assistant messages.
    This handles natural language and unstructured text.
    """
    if not content or len(content.strip()) < 10:
        return  # Skip very short messages

    # Only process user messages and assistant messages that might contain booking info
    if role not in ["user", "assistant"]:
        return

    try:
        # Use LLM to extract structured preferences
        prompt = f"""Extract user preferences from this message. Return a JSON object with any preferences found.

Message: "{content}"

Extract:
- pickup_location: If user mentions a pickup location
- dropoff_location: If user mentions a destination/dropoff location
- ride_type: If user mentions a ride type (LUMI_GO, LUMI_PLUS, LUMI_XL, Courier)
- payment_method: If user mentions payment method (WALLET, CASH, CARD)
- time_preference: If user mentions time preference (morning, afternoon, evening, night)
- stops: List of any stop locations mentioned

Return ONLY a JSON object with the keys above (omit keys if not found). Example:
{{"dropoff_location": "Johar Town", "ride_type": "LUMI_GO"}}

JSON:"""

        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a preference extraction assistant. Extract only concrete preferences from messages. Return valid JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_completion_tokens=200,
        )

        extracted_text = response.choices[0].message.content.strip()
        # Remove markdown code blocks if present
        if extracted_text.startswith("```"):
            extracted_text = re.sub(r"^```(?:json)?\n", "", extracted_text)
            extracted_text = re.sub(r"\n```$", "", extracted_text)

        try:
            preferences = json.loads(extracted_text)
        except json.JSONDecodeError:
            # Try to extract JSON from text
            json_match = re.search(r"\{[^}]+\}", extracted_text)
            if json_match:
                preferences = json.loads(json_match.group())
            else:
                return

        # Process extracted preferences
        if preferences.get("pickup_location"):
            place = preferences["pickup_location"]
            update_preference(user_id, PREF_TYPE_PICKUP, place, place)

        if preferences.get("dropoff_location"):
            place = preferences["dropoff_location"]
            update_preference(user_id, PREF_TYPE_DROPOFF, place, place)
            update_preference(user_id, PREF_TYPE_MOST_VISITED, place, place)

        if preferences.get("ride_type"):
            normalized = normalize_ride_type(preferences["ride_type"])
            if normalized:
                update_preference(
                    user_id, PREF_TYPE_RIDE_TYPE, normalized, normalized
                )

        if preferences.get("payment_method"):
            normalized = normalize_payment_method(preferences["payment_method"])
            if normalized:
                update_preference(
                    user_id, PREF_TYPE_PAYMENT, normalized, normalized
                )

        if preferences.get("time_preference"):
            time_pref = preferences["time_preference"].lower()
            update_preference(user_id, PREF_TYPE_TIME, time_pref, time_pref)

        if preferences.get("stops") and isinstance(preferences["stops"], list):
            for stop in preferences["stops"]:
                if stop:
                    update_preference(user_id, PREF_TYPE_STOP, stop, stop)

    except Exception as e:
        logger.error(f"Error in LLM preference extraction: {e}")
        # Fallback to regex extraction
        extract_preferences_from_message_regex(user_id, role, content)


def extract_preferences_from_message_regex(
    user_id: str, role: str, content: str
) -> None:
    """
    Fallback regex-based extraction for when LLM fails or is unavailable.
    """
    if not content or role not in ["user", "assistant"]:
        return

    content_lower = content.lower()

    # Extract pickup locations
    pickup_patterns = [
        r"pickup.*?from\s+([^,\.\n]+)",
        r"pick\s+me\s+up\s+from\s+([^,\.\n]+)",
        r"from\s+([^,\.\n]+)\s+to",
        r"starting\s+from\s+([^,\.\n]+)",
    ]
    for pattern in pickup_patterns:
        matches = re.findall(pattern, content_lower, re.IGNORECASE)
        for match in matches:
            place = match.strip()
            if len(place) > 3:
                update_preference(user_id, PREF_TYPE_PICKUP, place, place)

    # Extract dropoff locations
    dropoff_patterns = [
        r"to\s+([^,\.\n]+)",
        r"dropoff.*?at\s+([^,\.\n]+)",
        r"destination.*?is\s+([^,\.\n]+)",
        r"going\s+to\s+([^,\.\n]+)",
        r"headed\s+to\s+([^,\.\n]+)",
    ]
    for pattern in dropoff_patterns:
        matches = re.findall(pattern, content_lower, re.IGNORECASE)
        for match in matches:
            place = match.strip()
            if len(place) > 3:
                update_preference(user_id, PREF_TYPE_DROPOFF, place, place)
                update_preference(user_id, PREF_TYPE_MOST_VISITED, place, place)

    # Extract ride types
    for ride_type_key, normalized in RIDE_TYPE_MAPPING.items():
        if ride_type_key in content_lower:
            update_preference(user_id, PREF_TYPE_RIDE_TYPE, normalized, normalized)

    # Extract payment methods
    for payment_key, normalized in PAYMENT_MAPPING.items():
        if payment_key in content_lower:
            update_preference(user_id, PREF_TYPE_PAYMENT, normalized, normalized)

    # Extract time preferences
    time_keywords = {
        "morning": "morning",
        "afternoon": "afternoon",
        "evening": "evening",
        "night": "night",
        "late night": "night",
    }
    for keyword, time_pref in time_keywords.items():
        if keyword in content_lower:
            update_preference(user_id, PREF_TYPE_TIME, time_pref, content)


def update_preference(
    user_id: str,
    preference_type: str,
    preference_key: str,
    preference_value: str,
) -> None:
    """
    Update or create a user preference in the database.
    Increments frequency if preference already exists.
    """
    if not user_id or not preference_key or not preference_value:
        return

    try:
        with get_cursor(commit=True) as cur:
            # Check if preference exists
            cur.execute(
                """
                SELECT id, frequency FROM assistant_user_preferences
                WHERE user_id = %s AND preference_type = %s AND preference_key = %s
                """,
                (user_id, preference_type, preference_key),
            )
            row = cur.fetchone()

            if row:
                # Update existing preference
                cur.execute(
                    """
                    UPDATE assistant_user_preferences
                    SET frequency = frequency + 1,
                        preference_value = %s,
                        last_used_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (preference_value, row["id"]),
                )
            else:
                # Create new preference
                cur.execute(
                    """
                    INSERT INTO assistant_user_preferences
                    (user_id, preference_type, preference_key, preference_value, frequency)
                    VALUES (%s, %s, %s, %s, 1)
                    """,
                    (user_id, preference_type, preference_key, preference_value),
                )
    except Exception as e:
        logger.error(f"Error updating preference: {e}")


def extract_preferences_from_message(
    user_id: str,
    role: str,
    content: str,
    tool_name: Optional[str] = None,
    tool_result: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Main entry point for preference extraction.
    Handles all sources: tool results, user messages, assistant responses.
    """
    if not user_id:
        return

    # Priority 1: Extract from tool results (most reliable)
    if tool_name and tool_result:
        extract_preferences_from_tool_result(user_id, tool_name, tool_result)

    # Priority 2: Extract from messages using LLM (for natural language)
    if content and role in ["user", "assistant"]:
        # Use LLM extraction first, falls back to regex if it fails
        extract_preferences_from_message_llm(user_id, role, content)


def get_user_preferences(
    user_id: str, preference_type: Optional[str] = None
) -> List[Dict]:
    """Get user preferences, optionally filtered by type"""
    try:
        with get_cursor() as cur:
            if preference_type:
                cur.execute(
                    """
                    SELECT * FROM assistant_user_preferences
                    WHERE user_id = %s AND preference_type = %s
                    ORDER BY frequency DESC, last_used_at DESC
                    """,
                    (user_id, preference_type),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM assistant_user_preferences
                    WHERE user_id = %s
                    ORDER BY frequency DESC, last_used_at DESC
                    """,
                    (user_id,),
                )
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error getting user preferences: {e}")
        return []


def get_most_visited_places(user_id: str, limit: int = 5) -> List[Dict]:
    """Get user's most visited places"""
    preferences = get_user_preferences(user_id, PREF_TYPE_MOST_VISITED)
    return preferences[:limit]


def get_preferred_ride_types(user_id: str, limit: int = 3) -> List[Dict]:
    """Get user's preferred ride types"""
    preferences = get_user_preferences(user_id, PREF_TYPE_RIDE_TYPE)
    return preferences[:limit]


def get_common_pickup_locations(user_id: str, limit: int = 5) -> List[Dict]:
    """Get user's common pickup locations"""
    preferences = get_user_preferences(user_id, PREF_TYPE_PICKUP)
    return preferences[:limit]


def get_common_dropoff_locations(user_id: str, limit: int = 5) -> List[Dict]:
    """Get user's common dropoff locations"""
    preferences = get_user_preferences(user_id, PREF_TYPE_DROPOFF)
    return preferences[:limit]


def get_preferred_payment_methods(user_id: str, limit: int = 3) -> List[Dict]:
    """Get user's preferred payment methods"""
    preferences = get_user_preferences(user_id, PREF_TYPE_PAYMENT)
    return preferences[:limit]
