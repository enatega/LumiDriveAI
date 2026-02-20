"""
Chat Summary Generation Service (Phase 4)

Generates summaries of chat conversations using LLM to provide context
for future conversations and enable intelligent recommendations.
"""

import logging
import os
from typing import List, Dict, Optional
from dotenv import load_dotenv
from openai import OpenAI

from database import get_cursor

load_dotenv()
logger = logging.getLogger(__name__)

# Initialize OpenAI client
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY not set - summary generation will be disabled")
    client = None
else:
    client = OpenAI(api_key=OPENAI_API_KEY)

MODEL = os.getenv("MODEL", "gpt-4o-mini")
SUMMARY_GENERATION_THRESHOLD = int(os.getenv("SUMMARY_GENERATION_THRESHOLD", "20"))


def generate_chat_summary(session_id: str, user_id: str, message_ids: List[int]) -> Optional[str]:
    """
    Generate a summary of chat messages using LLM.
    
    Args:
        session_id: Chat session ID
        user_id: User ID
        message_ids: List of message IDs to summarize
    
    Returns:
        Summary text or None if generation fails
    """
    if not client:
        logger.warning("OpenAI client not initialized - skipping summary generation")
        return None
    
    if not message_ids:
        return None
    
    # Get messages from database
    try:
        with get_cursor() as cur:
            placeholders = ','.join(['%s'] * len(message_ids))
            cur.execute(
                f"""
                SELECT role, content 
                FROM assistant_chat_messages 
                WHERE id IN ({placeholders}) 
                ORDER BY created_at ASC
                """,
                message_ids
            )
            rows = cur.fetchall()
            messages = [dict(row) for row in rows] if rows else []
    except Exception as e:
        logger.error(f"Failed to fetch messages for summary: {e}")
        return None
    
    if not messages:
        return None
    
    # Build conversation context
    conversation_text = "\n".join([
        f"{msg['role'].upper()}: {msg['content']}"
        for msg in messages
    ])
    
    # Limit conversation length to avoid token limits
    max_chars = 8000  # Leave room for prompt and response
    if len(conversation_text) > max_chars:
        conversation_text = conversation_text[-max_chars:] + "\n[... conversation truncated ...]"
    
    # Generate summary using LLM
    prompt = f"""Summarize the following conversation between a user and a ride-booking assistant. 
Focus on:
1. Pickup and dropoff locations mentioned
2. Ride types requested (LUMI_GO, LUMI_PLUS, LUMI_XL, Courier, etc.)
3. User preferences (time preferences, ride type preferences, etc.)
4. Any recurring patterns or frequently mentioned places
5. Booking outcomes (successful rides, cancellations, etc.)

Keep the summary concise (2-3 sentences) and focus on actionable insights that would help personalize future interactions.

Conversation:
{conversation_text}

Summary:"""
    
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that summarizes conversations concisely, focusing on user preferences and booking patterns."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_completion_tokens=300
        )
        
        summary = response.choices[0].message.content.strip()
        logger.info(f"Generated summary for session {session_id[:20]}...: {summary[:100]}...")
        return summary
    except Exception as e:
        logger.error(f"Failed to generate summary for session {session_id}: {e}")
        return None


def save_summary(
    session_id: str,
    user_id: str,
    summary_text: str,
    message_count: int,
    start_message_id: int,
    end_message_id: int
) -> Optional[int]:
    """
    Save a chat summary to database.
    
    Returns:
        Summary ID if successful, None otherwise
    """
    try:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO assistant_chat_summaries 
                (session_id, user_id, summary_text, message_count, 
                 start_message_id, end_message_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (session_id, user_id, summary_text, message_count,
                 start_message_id, end_message_id)
            )
            result = cur.fetchone()
            if result:
                summary_id = result["id"]
                logger.info(f"Saved summary {summary_id} for session {session_id[:20]}...")
                return summary_id
            return None
    except Exception as e:
        logger.error(f"Failed to save summary for session {session_id}: {e}")
        return None


def should_generate_summary(session_id: str) -> bool:
    """
    Check if summary should be generated for a session.
    Returns True if there are enough unsummarized messages.
    """
    try:
        with get_cursor() as cur:
            # Get the highest message ID that has been summarized
            cur.execute(
                """
                SELECT COALESCE(MAX(end_message_id), 0) as last_summarized_id
                FROM assistant_chat_summaries
                WHERE session_id = %s
                """,
                (session_id,)
            )
            result = cur.fetchone()
            last_summarized_id = result["last_summarized_id"] if result else 0
            
            # Count messages after the last summarized message
            cur.execute(
                """
                SELECT COUNT(*) as count 
                FROM assistant_chat_messages 
                WHERE session_id = %s 
                AND id > %s
                """,
                (session_id, last_summarized_id)
            )
            result = cur.fetchone()
            count = result["count"] if result else 0
            return count >= SUMMARY_GENERATION_THRESHOLD
    except Exception as e:
        logger.error(f"Failed to check if summary needed for session {session_id}: {e}")
        return False


def get_unsummarized_message_ids(session_id: str, limit: int = None) -> List[int]:
    """
    Get message IDs that haven't been summarized yet.
    
    Args:
        session_id: Chat session ID
        limit: Maximum number of message IDs to return (defaults to threshold)
    
    Returns:
        List of message IDs ordered by creation time
    """
    if limit is None:
        limit = SUMMARY_GENERATION_THRESHOLD
    
    try:
        with get_cursor() as cur:
            # Get the highest message ID that has been summarized
            cur.execute(
                """
                SELECT COALESCE(MAX(end_message_id), 0) as last_summarized_id
                FROM assistant_chat_summaries
                WHERE session_id = %s
                """,
                (session_id,)
            )
            result = cur.fetchone()
            last_summarized_id = result["last_summarized_id"] if result else 0
            
            # Get messages after the last summarized message
            cur.execute(
                """
                SELECT id 
                FROM assistant_chat_messages 
                WHERE session_id = %s 
                AND id > %s
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (session_id, last_summarized_id, limit)
            )
            rows = cur.fetchall()
            return [row["id"] for row in rows] if rows else []
    except Exception as e:
        logger.error(f"Failed to get unsummarized messages for session {session_id}: {e}")
        return []


def generate_summary_if_needed(session_id: str, user_id: str) -> Optional[int]:
    """
    Generate and save summary if threshold is reached.
    
    Args:
        session_id: Chat session ID
        user_id: User ID
    
    Returns:
        Summary ID if generated, None otherwise
    """
    if not should_generate_summary(session_id):
        return None
    
    message_ids = get_unsummarized_message_ids(session_id, SUMMARY_GENERATION_THRESHOLD)
    
    if len(message_ids) < SUMMARY_GENERATION_THRESHOLD:
        return None
    
    summary_text = generate_chat_summary(session_id, user_id, message_ids)
    if not summary_text:
        return None
    
    summary_id = save_summary(
        session_id,
        user_id,
        summary_text,
        len(message_ids),
        min(message_ids),
        max(message_ids)
    )
    
    return summary_id


def get_session_summaries(session_id: str) -> List[Dict]:
    """
    Get all summaries for a session.
    
    Returns:
        List of summary dictionaries
    """
    try:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM assistant_chat_summaries
                WHERE session_id = %s
                ORDER BY created_at ASC
                """,
                (session_id,)
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows] if rows else []
    except Exception as e:
        logger.error(f"Failed to get summaries for session {session_id}: {e}")
        return []


def get_user_summaries(user_id: str, limit: int = 10) -> List[Dict]:
    """
    Get recent summaries for a user across all sessions.
    
    Returns:
        List of summary dictionaries
    """
    try:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM assistant_chat_summaries
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_id, limit)
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows] if rows else []
    except Exception as e:
        logger.error(f"Failed to get summaries for user {user_id}: {e}")
        return []
