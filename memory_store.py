from typing import Dict, List, Optional

from langchain.memory import ConversationBufferMemory
from langchain.schema import AIMessage, HumanMessage, SystemMessage, BaseMessage


from database import (
    get_or_create_session,
    get_session_messages,
    save_message,
)
import logging

logger = logging.getLogger(__name__)

# Store current location separately since ConversationBufferMemory is a Pydantic model
_MEMORY_LOCATIONS: Dict[str, Optional[Dict]] = {}

# In-memory caches for active sessions
_MEMORIES: Dict[str, ConversationBufferMemory] = {}
_USER_IDS: Dict[str, str] = {}  # session_id -> user_id mapping


def get_memory(session_id: str, user_id: Optional[str] = None) -> ConversationBufferMemory:
    """
    Get memory for a session, optionally tying it to a user_id and
    hydrating from the database if available.
    """
    # Track user_id mapping
    if user_id:
        _USER_IDS[session_id] = user_id
        try:
            session_data = get_or_create_session(session_id, user_id)
            if not session_data:
                logger.warning(f"Could not create/get session {session_id} for user {user_id} - chat will work but won't be persisted")
        except Exception as exc:
            logger.error(f"Failed to ensure session {session_id} for user {user_id}: {exc}")

    memory = _MEMORIES.get(session_id)
    if not memory:
        memory = ConversationBufferMemory(return_messages=True)
        _MEMORIES[session_id] = memory
        _MEMORY_LOCATIONS[session_id] = None

        # Load existing history from DB
        if user_id:
            try:
                db_messages = get_session_messages(session_id)
                for msg in db_messages:
                    role = msg.get("role")
                    content = msg.get("content", "")
                    if not content:
                        continue
                    if role == "user":
                        memory.chat_memory.add_user_message(content)
                    elif role == "assistant":
                        memory.chat_memory.add_ai_message(content)
                    elif role == "system":
                        memory.chat_memory.add_message(SystemMessage(content=content))
            except Exception as exc:
                logger.error(f"Failed to hydrate session {session_id} from DB: {exc}")

    return memory


def get_current_location(session_id: str) -> Optional[Dict]:
    """Get current location for a session"""
    return _MEMORY_LOCATIONS.get(session_id)


def set_current_location(session_id: str, location: Optional[Dict]):
    """Set current location for a session"""
    _MEMORY_LOCATIONS[session_id] = location


def bootstrap_memory_from_messages(memory: ConversationBufferMemory, messages: List[dict]):
    """
    Initialize a memory with existing chat history coming from the client.
    Only called when the memory is empty to avoid duplications.
    """
    if not messages:
        return
    if memory.chat_memory.messages:
        return
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if not content:
            continue
        if role == "user":
            memory.chat_memory.add_user_message(content)
        elif role == "assistant":
            memory.chat_memory.add_ai_message(content)
        elif role == "system":
            memory.chat_memory.add_message(SystemMessage(content=content))


def memory_to_openai_messages(memory: ConversationBufferMemory, system_prompt: str) -> List[dict]:
    """
    Convert the LangChain memory contents into OpenAI chat-completion format.
    """
    out = [{"role": "system", "content": system_prompt}]
    for msg in memory.chat_memory.messages:
        role = None
        if isinstance(msg, HumanMessage):
            role = "user"
        elif isinstance(msg, AIMessage):
            role = "assistant"
        elif isinstance(msg, SystemMessage):
            role = "system"
        elif isinstance(msg, BaseMessage):
            role = msg.type
        if role and msg.content:
            out.append({"role": role, "content": msg.content})
    return out


def save_chat_to_database(
    session_id: str,
    role: str,
    content: str,
    tool_call_id: Optional[str] = None,
    tool_name: Optional[str] = None,
):
    """
    Persist a chat message to the database, if a user_id mapping is available.
    Also extracts user preferences from the message (Phase 5).
    """
    user_id = _USER_IDS.get(session_id)
    if not user_id:
        return
    try:
        save_message(session_id, user_id, role, content, tool_call_id, tool_name)
        
        # Phase 5: Extract preferences from messages
        try:
            from preference_extraction import extract_preferences_from_message
            import json
            
            # If this is a tool result, parse it and extract preferences
            tool_result = None
            if role == "tool" and tool_name and content:
                try:
                    tool_result = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    pass
            
            # Extract preferences from message
            extract_preferences_from_message(
                user_id=user_id,
                role=role,
                content=content,
                tool_name=tool_name,
                tool_result=tool_result,
            )
        except Exception as exc:
            logger.error(f"Failed to extract preferences for session {session_id}: {exc}")
    except Exception as exc:
        logger.error(f"Failed to save message for session {session_id}: {exc}")

