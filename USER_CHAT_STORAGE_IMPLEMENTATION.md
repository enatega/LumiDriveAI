# User Chat Storage & Intelligence Implementation Guide

## Overview

This document outlines the implementation plan for storing user chats against `user_id` (retrieved from JWT), generating chat summaries, and building an intelligent recommendation system based on user preferences and chat history.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Phase 1: User ID Resolution](#phase-1-user-id-resolution)
3. [Phase 2: Database Schema](#phase-2-database-schema)
4. [Phase 3: Chat Storage Implementation](#phase-3-chat-storage-implementation)
5. [Phase 4: Chat Summary Generation](#phase-4-chat-summary-generation)
6. [Phase 5: User Preference Extraction](#phase-5-user-preference-extraction)
7. [Phase 6: Intelligent Recommendations](#phase-6-intelligent-recommendations)
8. [API Changes](#api-changes)
9. [Migration Strategy](#migration-strategy)

---

## Architecture Overview

### Current State
- Chat sessions stored in-memory by `session_id`
- No persistent storage
- No user association
- No chat history persistence

### Target State
- Chats stored in database by `user_id`
- Persistent chat history
- Chat summaries for context
- User preference extraction (most visited places, ride types, etc.)
- Intelligent recommendations based on history

### Key Components

```
┌─────────────────┐
│   Frontend      │
│   (JWT Token)   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│   FastAPI Server                    │
│   ┌───────────────────────────────┐ │
│   │  User ID Resolution Service  │ │
│   │  (JWT → user_id)             │ │
│   └───────────────────────────────┘ │
│   ┌───────────────────────────────┐ │
│   │  Chat Storage Service         │ │
│   │  (user_id + session_id)       │ │
│   └───────────────────────────────┘ │
│   ┌───────────────────────────────┐ │
│   │  Summary Generation Service   │ │
│   │  (LLM-based summaries)       │ │
│   └───────────────────────────────┘ │
│   ┌───────────────────────────────┐ │
│   │  Preference Extraction        │ │
│   │  (Places, ride types, etc.)  │ │
│   └───────────────────────────────┘ │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│   Database (PostgreSQL/SQLite)       │
│   - users                            │
│   - chat_sessions                    │
│   - chat_messages                    │
│   - chat_summaries                   │
│   - user_preferences                 │
└─────────────────────────────────────┘
```

---

## Phase 1: User ID Resolution

### 1.1 API Integration

**Endpoint**: `GET https://ride-server.lumi.qa/api/v1/users/get-user-id`

**Implementation**: Add function to `api.py`

```python
# api.py

def get_user_id_from_jwt(token: str, timeout: int = 10) -> dict:
    """
    Fetch user_id from JWT token using the rides backend API.
    
    Args:
        token: JWT bearer token
        timeout: Request timeout in seconds
    
    Returns:
        {
            "ok": bool,
            "user_id": str | None,
            "error": str | None
        }
    """
    url = f"{BASE_URL}/api/v1/users/get-user-id"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    
    try:
        resp = session.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            user_id = data.get("user_id")
            if user_id:
                return {
                    "ok": True,
                    "user_id": user_id,
                }
            else:
                return {
                    "ok": False,
                    "user_id": None,
                    "error": "user_id not found in response",
                }
        elif resp.status_code == 401:
            return {
                "ok": False,
                "user_id": None,
                "error": "Invalid or expired JWT token",
            }
        else:
            return {
                "ok": False,
                "user_id": None,
                "error": f"Failed to fetch user_id: HTTP {resp.status_code}",
            }
    except Exception as e:
        return {
            "ok": False,
            "user_id": None,
            "error": f"Error fetching user_id: {str(e)}",
        }
```

### 1.2 Server Integration

**Update `server.py`** to resolve user_id at the start of each request:

```python
# server.py

@app.post("/chat")
async def chat_endpoint(
    request: Request,
    body: ChatRequest,
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
):
    # ... existing code ...
    
    try:
        # Set backend token
        token = _set_backend_token(authorization)
        
        # Resolve user_id from JWT
        from api import get_user_id_from_jwt
        user_id_result = get_user_id_from_jwt(token)
        
        if not user_id_result.get("ok"):
            logger.error(f"[{request_id}] Failed to resolve user_id: {user_id_result.get('error')}")
            raise HTTPException(
                status_code=401 if "Invalid" in user_id_result.get("error", "") else 500,
                detail=f"Failed to resolve user_id: {user_id_result.get('error')}"
            )
        
        user_id = user_id_result["user_id"]
        logger.info(f"[{request_id}] Resolved user_id: {user_id}")
        
        # Use user_id for chat storage
        # ... rest of implementation ...
```

---

## Phase 2: Database Schema

### 2.1 Database Choice

**Recommendation**: Start with **SQLite** for development, migrate to **PostgreSQL** for production.

### 2.2 Schema Design

```sql
-- users table (optional - can be managed by main backend)
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- chat_sessions table
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    message_count INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX idx_chat_sessions_user_id ON chat_sessions(user_id);
CREATE INDEX idx_chat_sessions_updated_at ON chat_sessions(updated_at DESC);

-- chat_messages table
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
    content TEXT NOT NULL,
    tool_call_id TEXT,
    tool_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX idx_chat_messages_session_id ON chat_messages(session_id);
CREATE INDEX idx_chat_messages_user_id ON chat_messages(user_id);
CREATE INDEX idx_chat_messages_created_at ON chat_messages(created_at DESC);

-- chat_summaries table
CREATE TABLE IF NOT EXISTS chat_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    message_count INTEGER NOT NULL,
    start_message_id INTEGER,
    end_message_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (start_message_id) REFERENCES chat_messages(id),
    FOREIGN KEY (end_message_id) REFERENCES chat_messages(id)
);

CREATE INDEX idx_chat_summaries_session_id ON chat_summaries(session_id);
CREATE INDEX idx_chat_summaries_user_id ON chat_summaries(user_id);

-- user_preferences table
CREATE TABLE IF NOT EXISTS user_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    preference_type TEXT NOT NULL CHECK(preference_type IN ('most_visited_place', 'preferred_ride_type', 'common_pickup', 'common_dropoff', 'preferred_time', 'other')),
    preference_key TEXT NOT NULL,
    preference_value TEXT NOT NULL,
    frequency INTEGER DEFAULT 1,
    last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE(user_id, preference_type, preference_key)
);

CREATE INDEX idx_user_preferences_user_id ON user_preferences(user_id);
CREATE INDEX idx_user_preferences_type ON user_preferences(preference_type);
CREATE INDEX idx_user_preferences_frequency ON user_preferences(frequency DESC);
```

### 2.3 Database Module

Create `database.py`:

```python
# database.py

import sqlite3
import os
from typing import List, Dict, Optional
from datetime import datetime
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DATABASE_PATH", "lumidrive_assistant.db")

@contextmanager
def get_db_connection():
    """Context manager for database connections"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        conn.close()

def init_database():
    """Initialize database schema"""
    schema_sql = """
    -- users table
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- chat_sessions table
    CREATE TABLE IF NOT EXISTS chat_sessions (
        session_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        message_count INTEGER DEFAULT 0
    );

    CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions(user_id);
    CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated_at ON chat_sessions(updated_at DESC);

    -- chat_messages table
    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
        content TEXT NOT NULL,
        tool_call_id TEXT,
        tool_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON chat_messages(session_id);
    CREATE INDEX IF NOT EXISTS idx_chat_messages_user_id ON chat_messages(user_id);
    CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at ON chat_messages(created_at DESC);

    -- chat_summaries table
    CREATE TABLE IF NOT EXISTS chat_summaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        summary_text TEXT NOT NULL,
        message_count INTEGER NOT NULL,
        start_message_id INTEGER,
        end_message_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_chat_summaries_session_id ON chat_summaries(session_id);
    CREATE INDEX IF NOT EXISTS idx_chat_summaries_user_id ON chat_summaries(user_id);

    -- user_preferences table
    CREATE TABLE IF NOT EXISTS user_preferences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        preference_type TEXT NOT NULL CHECK(preference_type IN ('most_visited_place', 'preferred_ride_type', 'common_pickup', 'common_dropoff', 'preferred_time', 'other')),
        preference_key TEXT NOT NULL,
        preference_value TEXT NOT NULL,
        frequency INTEGER DEFAULT 1,
        last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, preference_type, preference_key)
    );

    CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id ON user_preferences(user_id);
    CREATE INDEX IF NOT EXISTS idx_user_preferences_type ON user_preferences(preference_type);
    CREATE INDEX IF NOT EXISTS idx_user_preferences_frequency ON user_preferences(frequency DESC);
    """
    
    with get_db_connection() as conn:
        conn.executescript(schema_sql)
    logger.info("Database initialized successfully")

def ensure_user(user_id: str):
    """Ensure user exists in database"""
    with get_db_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,)
        )

def get_or_create_session(session_id: str, user_id: str) -> Dict:
    """Get or create a chat session"""
    ensure_user(user_id)
    
    with get_db_connection() as conn:
        # Try to get existing session
        cursor = conn.execute(
            "SELECT * FROM chat_sessions WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        
        # Create new session
        conn.execute(
            """INSERT INTO chat_sessions (session_id, user_id, last_message_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)""",
            (session_id, user_id)
        )
        
        cursor = conn.execute(
            "SELECT * FROM chat_sessions WHERE session_id = ?",
            (session_id,)
        )
        return dict(cursor.fetchone())

def save_message(session_id: str, user_id: str, role: str, content: str, 
                 tool_call_id: Optional[str] = None, tool_name: Optional[str] = None) -> int:
    """Save a chat message and return message ID"""
    with get_db_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO chat_messages 
               (session_id, user_id, role, content, tool_call_id, tool_name)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, user_id, role, content, tool_call_id, tool_name)
        )
        message_id = cursor.lastrowid
        
        # Update session
        conn.execute(
            """UPDATE chat_sessions 
               SET updated_at = CURRENT_TIMESTAMP,
                   last_message_at = CURRENT_TIMESTAMP,
                   message_count = message_count + 1
               WHERE session_id = ?""",
            (session_id,)
        )
        
        return message_id

def get_session_messages(session_id: str, limit: Optional[int] = None) -> List[Dict]:
    """Get messages for a session"""
    with get_db_connection() as conn:
        query = """
            SELECT * FROM chat_messages 
            WHERE session_id = ? 
            ORDER BY created_at ASC
        """
        if limit:
            query += f" LIMIT {limit}"
        
        cursor = conn.execute(query, (session_id,))
        return [dict(row) for row in cursor.fetchall()]

def get_user_recent_sessions(user_id: str, limit: int = 10) -> List[Dict]:
    """Get recent chat sessions for a user"""
    with get_db_connection() as conn:
        cursor = conn.execute(
            """SELECT * FROM chat_sessions 
               WHERE user_id = ? 
               ORDER BY last_message_at DESC 
               LIMIT ?""",
            (user_id, limit)
        )
        return [dict(row) for row in cursor.fetchall()]
```

---

## Phase 3: Chat Storage Implementation

### 3.1 Update Memory Store

Modify `memory_store.py` to integrate with database:

```python
# memory_store.py (updated)

from typing import Dict, List, Optional
from langchain.memory import ConversationBufferMemory
from langchain.schema import AIMessage, HumanMessage, SystemMessage, BaseMessage
from database import (
    get_or_create_session,
    save_message,
    get_session_messages,
    get_user_recent_sessions
)

# Keep in-memory cache for active sessions
_MEMORIES: Dict[str, ConversationBufferMemory] = {}
_MEMORY_LOCATIONS: Dict[str, Optional[Dict]] = {}
_USER_IDS: Dict[str, str] = {}  # session_id -> user_id mapping

def get_memory(session_id: str, user_id: Optional[str] = None) -> ConversationBufferMemory:
    """Get memory for a session, loading from database if needed"""
    # Store user_id mapping
    if user_id:
        _USER_IDS[session_id] = user_id
    
    # Get or create session in database
    if user_id:
        get_or_create_session(session_id, user_id)
    
    # Get from cache or create new
    memory = _MEMORIES.get(session_id)
    if not memory:
        memory = ConversationBufferMemory(return_messages=True)
        _MEMORIES[session_id] = memory
        
        # Load from database if session exists
        if user_id:
            db_messages = get_session_messages(session_id)
            for msg in db_messages:
                role = msg["role"]
                content = msg["content"]
                if role == "user":
                    memory.chat_memory.add_user_message(content)
                elif role == "assistant":
                    memory.chat_memory.add_ai_message(content)
                elif role == "system":
                    memory.chat_memory.add_message(SystemMessage(content=content))
    
    return memory

def save_chat_to_database(session_id: str, role: str, content: str, 
                          tool_call_id: Optional[str] = None, 
                          tool_name: Optional[str] = None):
    """Save a chat message to database"""
    user_id = _USER_IDS.get(session_id)
    if not user_id:
        return  # Skip if user_id not available
    
    try:
        save_message(session_id, user_id, role, content, tool_call_id, tool_name)
    except Exception as e:
        logger.error(f"Failed to save message to database: {e}")

# ... rest of existing code ...
```

### 3.2 Update Server

Modify `server.py` to save messages:

```python
# server.py (updates)

@app.post("/chat")
async def chat_endpoint(...):
    # ... existing code ...
    
    # Resolve user_id
    user_id_result = get_user_id_from_jwt(token)
    user_id = user_id_result["user_id"]
    
    # Get memory with user_id
    memory = get_memory(body.session_id, user_id)
    
    # ... existing code ...
    
    # Save user message
    user_message = (body.user_message or "").strip()
    memory.chat_memory.add_user_message(user_message)
    save_chat_to_database(body.session_id, "user", user_message)
    
    # ... tool execution ...
    
    # Save assistant response
    final_text = "".join(final_chunks).strip()
    if final_text:
        memory.chat_memory.add_ai_message(final_text)
        save_chat_to_database(body.session_id, "assistant", final_text)
    
    # ... rest of code ...
```

---

## Phase 4: Chat Summary Generation

### 4.1 Summary Generation Service

Create `summary_service.py`:

```python
# summary_service.py

import logging
from typing import List, Dict, Optional
from openai import OpenAI
import os
from dotenv import load_dotenv
from database import (
    get_session_messages,
    get_db_connection,
    save_message
)

load_dotenv()
logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("MODEL", "gpt-4o-mini")

SUMMARY_GENERATION_THRESHOLD = 20  # Generate summary after N messages

def generate_chat_summary(session_id: str, user_id: str, 
                         message_ids: List[int]) -> Optional[str]:
    """
    Generate a summary of chat messages using LLM.
    
    Args:
        session_id: Chat session ID
        user_id: User ID
        message_ids: List of message IDs to summarize
    
    Returns:
        Summary text or None if generation fails
    """
    if not message_ids:
        return None
    
    # Get messages from database
    with get_db_connection() as conn:
        placeholders = ','.join(['?'] * len(message_ids))
        cursor = conn.execute(
            f"""SELECT role, content FROM chat_messages 
                WHERE id IN ({placeholders}) 
                ORDER BY created_at ASC""",
            message_ids
        )
        messages = [dict(row) for row in cursor.fetchall()]
    
    if not messages:
        return None
    
    # Build conversation context
    conversation_text = "\n".join([
        f"{msg['role'].upper()}: {msg['content']}"
        for msg in messages
    ])
    
    # Generate summary using LLM
    prompt = f"""Summarize the following conversation between a user and a ride-booking assistant. 
Focus on:
1. Pickup and dropoff locations mentioned
2. Ride types requested
3. User preferences (time preferences, ride type preferences, etc.)
4. Any recurring patterns or frequently mentioned places
5. Booking outcomes (successful rides, cancellations, etc.)

Keep the summary concise (2-3 sentences) and focus on actionable insights.

Conversation:
{conversation_text}

Summary:"""
    
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that summarizes conversations concisely."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=300
        )
        
        summary = response.choices[0].message.content.strip()
        logger.info(f"Generated summary for session {session_id}: {summary[:100]}...")
        return summary
    except Exception as e:
        logger.error(f"Failed to generate summary: {e}")
        return None

def save_summary(session_id: str, user_id: str, summary_text: str,
                message_count: int, start_message_id: int, end_message_id: int):
    """Save a chat summary to database"""
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO chat_summaries 
               (session_id, user_id, summary_text, message_count, 
                start_message_id, end_message_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, user_id, summary_text, message_count,
             start_message_id, end_message_id)
        )

def should_generate_summary(session_id: str) -> bool:
    """Check if summary should be generated for a session"""
    with get_db_connection() as conn:
        cursor = conn.execute(
            """SELECT COUNT(*) as count FROM chat_messages 
               WHERE session_id = ? AND id NOT IN (
                   SELECT DISTINCT start_message_id FROM chat_summaries 
                   WHERE session_id = ? AND start_message_id IS NOT NULL
               )""",
            (session_id, session_id)
        )
        count = cursor.fetchone()["count"]
        return count >= SUMMARY_GENERATION_THRESHOLD

def generate_summary_if_needed(session_id: str, user_id: str):
    """Generate and save summary if threshold is reached"""
    if not should_generate_summary(session_id):
        return
    
    # Get unsummarized messages
    with get_db_connection() as conn:
        cursor = conn.execute(
            """SELECT id FROM chat_messages 
               WHERE session_id = ? AND id NOT IN (
                   SELECT DISTINCT start_message_id FROM chat_summaries 
                   WHERE session_id = ? AND start_message_id IS NOT NULL
               )
               ORDER BY created_at ASC
               LIMIT ?""",
            (session_id, session_id, SUMMARY_GENERATION_THRESHOLD)
        )
        message_ids = [row["id"] for row in cursor.fetchall()]
    
    if len(message_ids) >= SUMMARY_GENERATION_THRESHOLD:
        summary = generate_chat_summary(session_id, user_id, message_ids)
        if summary:
            save_summary(
                session_id, user_id, summary,
                len(message_ids),
                min(message_ids),
                max(message_ids)
            )
```

### 4.2 Integration

Add summary generation to `server.py`:

```python
# After saving assistant message
if final_text:
    memory.chat_memory.add_ai_message(final_text)
    save_chat_to_database(body.session_id, "assistant", final_text)
    
    # Generate summary if needed
    from summary_service import generate_summary_if_needed
    generate_summary_if_needed(body.session_id, user_id)
```

---

## Phase 5: User Preference Extraction

### 5.1 Preference Extraction Service

Create `preference_extraction.py`:

```python
# preference_extraction.py

import logging
import re
from typing import List, Dict, Optional
from database import get_db_connection
from datetime import datetime

logger = logging.getLogger(__name__)

def extract_preferences_from_message(user_id: str, role: str, content: str):
    """Extract user preferences from a single message"""
    if role != "user" and role != "assistant":
        return
    
    content_lower = content.lower()
    
    # Extract pickup locations
    pickup_patterns = [
        r"pickup.*?from\s+([^,\.]+)",
        r"pick\s+me\s+up\s+from\s+([^,\.]+)",
        r"from\s+([^,\.]+)\s+to",
    ]
    for pattern in pickup_patterns:
        matches = re.findall(pattern, content_lower, re.IGNORECASE)
        for match in matches:
            place = match.strip()
            if len(place) > 3:  # Filter out very short matches
                update_preference(user_id, "common_pickup", place, content)
    
    # Extract dropoff locations
    dropoff_patterns = [
        r"to\s+([^,\.]+)",
        r"dropoff.*?at\s+([^,\.]+)",
        r"destination.*?is\s+([^,\.]+)",
    ]
    for pattern in dropoff_patterns:
        matches = re.findall(pattern, content_lower, re.IGNORECASE)
        for match in matches:
            place = match.strip()
            if len(place) > 3:
                update_preference(user_id, "common_dropoff", place, content)
    
    # Extract ride types
    ride_types = ["lumi go", "lumi plus", "lumi xl", "courier", "lumi_go", "lumi_plus", "lumi_xl"]
    for ride_type in ride_types:
        if ride_type in content_lower:
            update_preference(user_id, "preferred_ride_type", ride_type, content)
    
    # Extract time preferences (morning, afternoon, evening, night)
    time_keywords = {
        "morning": "morning",
        "afternoon": "afternoon",
        "evening": "evening",
        "night": "night",
        "late night": "night"
    }
    for keyword, time_pref in time_keywords.items():
        if keyword in content_lower:
            update_preference(user_id, "preferred_time", time_pref, content)

def update_preference(user_id: str, preference_type: str, preference_key: str, 
                     preference_value: str):
    """Update or create a user preference"""
    with get_db_connection() as conn:
        # Check if preference exists
        cursor = conn.execute(
            """SELECT id, frequency FROM user_preferences 
               WHERE user_id = ? AND preference_type = ? AND preference_key = ?""",
            (user_id, preference_type, preference_key)
        )
        row = cursor.fetchone()
        
        if row:
            # Update existing preference
            conn.execute(
                """UPDATE user_preferences 
                   SET frequency = frequency + 1,
                       preference_value = ?,
                       last_used_at = CURRENT_TIMESTAMP,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (preference_value, row["id"])
            )
        else:
            # Create new preference
            conn.execute(
                """INSERT INTO user_preferences 
                   (user_id, preference_type, preference_key, preference_value, frequency)
                   VALUES (?, ?, ?, ?, 1)""",
                (user_id, preference_type, preference_key, preference_value)
            )

def get_user_preferences(user_id: str, preference_type: Optional[str] = None) -> List[Dict]:
    """Get user preferences, optionally filtered by type"""
    with get_db_connection() as conn:
        if preference_type:
            cursor = conn.execute(
                """SELECT * FROM user_preferences 
                   WHERE user_id = ? AND preference_type = ?
                   ORDER BY frequency DESC, last_used_at DESC""",
                (user_id, preference_type)
            )
        else:
            cursor = conn.execute(
                """SELECT * FROM user_preferences 
                   WHERE user_id = ?
                   ORDER BY frequency DESC, last_used_at DESC""",
                (user_id,)
            )
        return [dict(row) for row in cursor.fetchall()]

def get_most_visited_places(user_id: str, limit: int = 5) -> List[Dict]:
    """Get user's most visited places"""
    preferences = get_user_preferences(user_id, "common_dropoff")
    return preferences[:limit]
```

### 5.2 Integration

Add preference extraction to `server.py`:

```python
# After saving user message
save_chat_to_database(body.session_id, "user", user_message)
from preference_extraction import extract_preferences_from_message
extract_preferences_from_message(user_id, "user", user_message)
```

---

## Phase 6: Intelligent Recommendations

### 6.1 Context Building Service

Create `context_service.py`:

```python
# context_service.py

from typing import List, Dict, Optional
from database import (
    get_user_recent_sessions,
    get_session_messages,
    get_db_connection
)
from preference_extraction import get_user_preferences, get_most_visited_places

def build_user_context(user_id: str) -> str:
    """Build context string for user based on chat history and preferences"""
    context_parts = []
    
    # Get recent summaries
    with get_db_connection() as conn:
        cursor = conn.execute(
            """SELECT summary_text FROM chat_summaries 
               WHERE user_id = ? 
               ORDER BY created_at DESC 
               LIMIT 3""",
            (user_id,)
        )
        summaries = [row["summary_text"] for row in cursor.fetchall()]
    
    if summaries:
        context_parts.append("RECENT CHAT SUMMARIES:")
        for i, summary in enumerate(summaries, 1):
            context_parts.append(f"{i}. {summary}")
    
    # Get most visited places
    most_visited = get_most_visited_places(user_id, limit=3)
    if most_visited:
        context_parts.append("\nMOST VISITED PLACES:")
        for place in most_visited:
            context_parts.append(f"- {place['preference_key']} (visited {place['frequency']} times)")
    
    # Get preferred ride types
    ride_prefs = get_user_preferences(user_id, "preferred_ride_type")
    if ride_prefs:
        context_parts.append("\nPREFERRED RIDE TYPES:")
        for pref in ride_prefs[:3]:
            context_parts.append(f"- {pref['preference_key']} (used {pref['frequency']} times)")
    
    # Get common pickup locations
    pickup_prefs = get_user_preferences(user_id, "common_pickup")
    if pickup_prefs:
        context_parts.append("\nCOMMON PICKUP LOCATIONS:")
        for pref in pickup_prefs[:3]:
            context_parts.append(f"- {pref['preference_key']} (used {pref['frequency']} times)")
    
    return "\n".join(context_parts) if context_parts else ""

def enhance_system_prompt_with_context(system_prompt: str, user_id: str) -> str:
    """Enhance system prompt with user context"""
    context = build_user_context(user_id)
    if context:
        enhanced = f"""{system_prompt}

USER CONTEXT AND PREFERENCES:
{context}

Use this context to provide personalized recommendations. For example:
- If the user frequently visits a place, suggest it when relevant
- If they prefer a specific ride type, mention it as an option
- Reference their common pickup locations when asking for pickup
- Be proactive based on their history"""
        return enhanced
    return system_prompt
```

### 6.2 Integration

Update `server.py` to use context:

```python
# Build system prompt with user context
from context_service import enhance_system_prompt_with_context
system_prompt = SYSTEM
system_prompt = enhance_system_prompt_with_context(system_prompt, user_id)

# Add location context if available
current_location = get_current_location(body.session_id)
if current_location and isinstance(current_location, dict) and current_location.get("lat") and current_location.get("lng"):
    # ... existing location code ...
```

---

## API Changes

### New Endpoints

Add to `server.py`:

```python
@app.get("/chat/history")
async def get_chat_history(
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
    limit: int = 50,
):
    """Get user's chat history"""
    token = _set_backend_token(authorization)
    user_id_result = get_user_id_from_jwt(token)
    user_id = user_id_result["user_id"]
    
    from database import get_user_recent_sessions
    sessions = get_user_recent_sessions(user_id, limit=limit)
    
    return {"ok": True, "sessions": sessions}

@app.get("/chat/preferences")
async def get_user_preferences_endpoint(
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
):
    """Get user preferences"""
    token = _set_backend_token(authorization)
    user_id_result = get_user_id_from_jwt(token)
    user_id = user_id_result["user_id"]
    
    from preference_extraction import get_user_preferences
    preferences = get_user_preferences(user_id)
    
    return {"ok": True, "preferences": preferences}
```

---

## Migration Strategy

### Step 1: Database Setup
1. Run `init_database()` on server startup
2. Test database connection

### Step 2: User ID Resolution
1. Add `get_user_id_from_jwt()` to `api.py`
2. Integrate into `/chat` endpoint
3. Test with valid JWT tokens

### Step 3: Chat Storage
1. Update `memory_store.py` to use database
2. Update `server.py` to save messages
3. Test message persistence

### Step 4: Summary Generation
1. Implement `summary_service.py`
2. Integrate summary generation
3. Test summary creation

### Step 5: Preference Extraction
1. Implement `preference_extraction.py`
2. Integrate extraction into message saving
3. Test preference tracking

### Step 6: Context Enhancement
1. Implement `context_service.py`
2. Integrate into system prompt
3. Test personalized recommendations

### Step 7: Migration of Existing Data
- If you have existing in-memory sessions, create a migration script to save them to database
- Run migration script once before switching to database-only storage

---

## Testing Checklist

- [ ] User ID resolution works with valid JWT
- [ ] User ID resolution fails gracefully with invalid JWT
- [ ] Chat messages are saved to database
- [ ] Chat messages are loaded from database on session resume
- [ ] Summaries are generated after threshold messages
- [ ] Preferences are extracted from messages
- [ ] Most visited places are tracked correctly
- [ ] System prompt includes user context
- [ ] Recommendations appear in assistant responses
- [ ] Database queries are performant
- [ ] Error handling works correctly

---

## Future Enhancements

1. **Advanced NLP**: Use more sophisticated NLP models for preference extraction
2. **Real-time Recommendations**: Provide suggestions as user types
3. **Analytics Dashboard**: Show user preferences and chat statistics
4. **Multi-language Support**: Extract preferences in multiple languages
5. **Time-based Patterns**: Detect patterns based on time of day/week
6. **Location Clustering**: Group nearby locations together
7. **Sentiment Analysis**: Track user satisfaction from chat history

---

## Dependencies

Add to `requirements.txt`:

```
# Database (SQLite is built-in, but for PostgreSQL):
# psycopg2-binary==2.9.9  # Uncomment for PostgreSQL

# Already have:
# openai
# langchain
# python-dotenv
# fastapi
# requests
```

---

## Environment Variables

Add to `.env`:

```bash
# Database
DATABASE_PATH=lumidrive_assistant.db  # SQLite path, or PostgreSQL connection string

# Summary generation threshold
SUMMARY_GENERATION_THRESHOLD=20
```

---

## Notes

- Start with SQLite for simplicity, migrate to PostgreSQL for production
- Summary generation can be expensive (LLM calls), so batch it or run async
- Preference extraction uses regex patterns - consider more sophisticated NLP later
- Database indexes are crucial for performance with large chat histories
- Consider implementing caching for frequently accessed user preferences

