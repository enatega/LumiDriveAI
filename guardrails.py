"""
Output Guardrails for AI Assistant
Prevents exposure of tool details and ensures responses stay within context.
"""

import re
import logging
from typing import Optional, Tuple, List
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # If .env file is not accessible, use defaults
    pass

logger = logging.getLogger(__name__)

# Configuration from environment variables
GUARDRAILS_ENABLED = os.getenv("GUARDRAILS_ENABLED", "true").lower() == "true"
STRICT_MODE = os.getenv("GUARDRAILS_STRICT_MODE", "true").lower() == "true"
OUT_OF_SCOPE_RESPONSE = os.getenv(
    "OUT_OF_SCOPE_RESPONSE",
    "I'm a ride-booking assistant and can help you with booking rides, checking fares, tracking rides, and managing your bookings. How can I assist you with your ride today?"
)

# Tool name patterns to detect and filter
TOOL_PATTERNS = [
    r'\{[^}]*tool[^}]*\}',  # {tool:...} patterns
    r'tool[_\s]*[:=]\s*\w+',  # tool: name or tool=name
    r'function[_\s]*[:=]\s*["\']?\w+["\']?',  # function: name
    r'call[_\s]*[:=]\s*["\']?\w+["\']?',  # call: name
    r'list_ride_types',  # Specific tool names
    r'set_trip_core',
    r'book_ride_with_details',
    r'get_fare_quote',
    r'resolve_place_to_coordinates',
    r'get_address_from_coordinates',
    r'create_ride_and_wait_for_bids',
    r'accept_bid',
    r'track_ride',
    r'cancel_ride',
    r'check_active_ride',
    r'request_map_selection',
    r'set_stops',
    r'set_courier_fields',
    r'set_ride_type',
    r'get_fare_for_locations',
    r'create_request_and_poll',
    r'wait_for_bids',
    r'auto_book_ride',
]

# Compile regex patterns for performance
TOOL_REGEX_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in TOOL_PATTERNS]

# Out-of-scope keywords and patterns
OUT_OF_SCOPE_KEYWORDS = [
    # General knowledge questions
    r'\bwho is\b',
    r'\bwhat is\b.*\b(obama|trump|biden|president|prime minister|history|biography)\b',
    r'\bwhen was\b.*\b(born|died|founded|created)\b',
    r'\bwhere is\b.*\b(country|capital|located)\b',
    # Non-ride related topics
    r'\bweather\b',
    r'\bnews\b',
    r'\bsports\b',
    r'\bentertainment\b',
    r'\brecipe\b',
    r'\bcooking\b',
    r'\bjoke\b',
    r'\btell.*joke\b',
    # Technical/system questions
    r'\bhow does.*work\b.*\b(ai|model|system|algorithm)\b',
    r'\bwhat.*model.*you.*use\b',
    r'\bwhat.*api.*you.*use\b',
    r'\bwhat.*framework\b',
    # Personal questions about the assistant
    r'\bwhat.*your.*name\b',
    r'\bwho.*created.*you\b',
    r'\bwhat.*you.*made.*of\b',
    r'\bwhat.*your.*purpose\b',
]

OUT_OF_SCOPE_REGEX = [re.compile(pattern, re.IGNORECASE) for pattern in OUT_OF_SCOPE_KEYWORDS]

# Ride booking related keywords (to determine if query is in scope)
RIDE_RELATED_KEYWORDS = [
    r'\b(ride|book|booking|trip|journey|destination|pickup|dropoff|drop-off|pick-up)\b',
    r'\b(fare|price|cost|quote|estimate)\b',
    r'\b(driver|vehicle|car|taxi|cab)\b',
    r'\b(location|address|place|where|coordinates)\b',
    r'\b(schedule|scheduled|time|when|eta|arrival)\b',
    r'\b(payment|pay|wallet|cash|card)\b',
    r'\b(bid|bids|accept|track|cancel|active)\b',
    r'\b(stop|stops|waypoint|route)\b',
    r'\b(ride type|LUMI|courier|package)\b',
    r'\b(current location|my location|where am i)\b',
]

RIDE_RELATED_REGEX = [re.compile(pattern, re.IGNORECASE) for pattern in RIDE_RELATED_KEYWORDS]


def filter_tool_details(text: str) -> str:
    """
    Remove tool-related details from response text.
    
    Args:
        text: The response text to filter
        
    Returns:
        Filtered text with tool details removed
    """
    if not GUARDRAILS_ENABLED:
        return text
    
    if not text:
        return text
    
    filtered_text = text
    
    # Remove tool patterns
    for pattern in TOOL_REGEX_PATTERNS:
        filtered_text = pattern.sub('', filtered_text)
    
    # Remove JSON-like structures that might contain tool info
    # Match {key: value} or {key=value} patterns
    filtered_text = re.sub(r'\{[^}]*[:=][^}]*\}', '', filtered_text, flags=re.IGNORECASE)
    
    # Remove function call patterns
    filtered_text = re.sub(r'\w+\([^)]*\)', lambda m: '' if any(tool in m.group(0).lower() for tool in ['tool_', 'call_', 'function_']) else m.group(0), filtered_text)
    
    # Clean up extra whitespace
    filtered_text = re.sub(r'\s+', ' ', filtered_text)
    filtered_text = filtered_text.strip()
    
    # If filtering removed everything, return a safe fallback
    if not filtered_text and text:
        logger.warning(f"Guardrail filtered entire response. Original length: {len(text)}")
        if STRICT_MODE:
            return "I apologize, but I can't provide that information. How can I help you with your ride booking?"
        return text  # Fallback to original if not in strict mode
    
    return filtered_text


def is_query_in_scope(user_message: str) -> Tuple[bool, Optional[str]]:
    """
    Check if user query is within the assistant's scope (ride booking related).
    
    Args:
        user_message: The user's message
        
    Returns:
        Tuple of (is_in_scope, reason_if_out_of_scope)
    """
    if not GUARDRAILS_ENABLED:
        return True, None
    
    if not user_message:
        return True, None
    
    user_lower = user_message.lower()
    
    # Check for out-of-scope patterns
    for pattern in OUT_OF_SCOPE_REGEX:
        if pattern.search(user_message):
            logger.info(f"Query detected as out-of-scope: {user_message[:100]}")
            return False, "Query contains out-of-scope keywords"
    
    # Check if query is ride-related
    is_ride_related = any(pattern.search(user_message) for pattern in RIDE_RELATED_REGEX)
    
    # If query doesn't contain ride-related keywords and is a question, it might be out of scope
    if not is_ride_related:
        # Check if it's a question (contains question words)
        question_words = ['who', 'what', 'when', 'where', 'why', 'how', 'which', 'whose']
        is_question = any(user_lower.startswith(word) or f' {word} ' in user_lower for word in question_words)
        
        if is_question:
            logger.info(f"Query detected as potentially out-of-scope (non-ride question): {user_message[:100]}")
            return False, "Query is a general question not related to ride booking"
    
    return True, None


def validate_response(response: str, user_message: Optional[str] = None) -> Tuple[str, bool]:
    """
    Validate and filter response text.
    
    Args:
        response: The assistant's response text
        user_message: Optional user message for context
        
    Returns:
        Tuple of (filtered_response, is_valid)
    """
    if not GUARDRAILS_ENABLED:
        return response, True
    
    if not response:
        return response, True
    
    # Filter tool details
    filtered = filter_tool_details(response)
    
    # Check if response contains tool details (should be filtered out)
    contains_tool_details = any(pattern.search(response) for pattern in TOOL_REGEX_PATTERNS)
    
    if contains_tool_details and filtered != response:
        logger.warning(f"Response contained tool details and was filtered. Original: {response[:200]}")
    
    # If in strict mode and response was heavily filtered, mark as potentially invalid
    is_valid = True
    if STRICT_MODE:
        # If more than 50% of response was filtered, it's suspicious
        if len(filtered) < len(response) * 0.5 and len(response) > 20:
            logger.warning(f"Response heavily filtered (removed {len(response) - len(filtered)} chars). May contain tool details.")
            is_valid = False
    
    return filtered, is_valid


def get_out_of_scope_response(user_message: Optional[str] = None) -> str:
    """
    Get a standardized response for out-of-scope queries.
    
    Args:
        user_message: Optional user message for context
        
    Returns:
        Standardized out-of-scope response
    """
    return OUT_OF_SCOPE_RESPONSE


def apply_guardrails(
    response: str,
    user_message: Optional[str] = None,
    check_scope: bool = True
) -> Tuple[str, bool]:
    """
    Apply all guardrails to a response.
    
    Args:
        response: The assistant's response text
        user_message: Optional user message for context
        check_scope: Whether to check if user message is in scope
        
    Returns:
        Tuple of (filtered_response, should_block)
    """
    if not GUARDRAILS_ENABLED:
        return response, False
    
    # Check if user query is in scope (if user_message provided)
    if check_scope and user_message:
        is_in_scope, reason = is_query_in_scope(user_message)
        if not is_in_scope:
            logger.info(f"Blocking out-of-scope query: {reason}")
            return get_out_of_scope_response(user_message), True
    
    # Validate and filter response
    filtered, is_valid = validate_response(response, user_message)
    
    # If response is invalid in strict mode, block it
    should_block = STRICT_MODE and not is_valid
    
    if should_block:
        logger.warning(f"Blocking response due to guardrail violation")
        return get_out_of_scope_response(user_message), True
    
    return filtered, False


def filter_streaming_chunk(chunk: str, accumulated_text: str = "") -> str:
    """
    Filter a single streaming chunk for tool details.
    This is optimized for streaming where we only see chunks, not full response.
    
    Args:
        chunk: The current chunk being streamed
        accumulated_text: Previously accumulated text (for context)
        
    Returns:
        Filtered chunk
    """
    if not GUARDRAILS_ENABLED:
        return chunk
    
    if not chunk:
        return chunk
    
    # Filter tool patterns from chunk
    filtered_chunk = chunk
    for pattern in TOOL_REGEX_PATTERNS:
        filtered_chunk = pattern.sub('', filtered_chunk)
    
    # Remove JSON-like structures
    filtered_chunk = re.sub(r'\{[^}]*[:=][^}]*\}', '', filtered_chunk, flags=re.IGNORECASE)
    
    return filtered_chunk
