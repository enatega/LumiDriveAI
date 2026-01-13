import os
import logging
from contextlib import contextmanager
from typing import List, Dict, Optional

import psycopg2
from psycopg2 import pool, extras

logger = logging.getLogger(__name__)

# Environment-driven configuration
DB_TYPE = os.getenv("DB_TYPE", "postgres").lower()
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_USERNAME = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

_POOL: Optional[pool.SimpleConnectionPool] = None


def _build_dsn() -> str:
    return (
        f"dbname={DB_NAME} "
        f"user={DB_USERNAME} "
        f"password={DB_PASSWORD} "
        f"host={DB_HOST} "
        f"port={DB_PORT}"
    )


def init_database():
    """Initialize connection pool and ensure schema exists."""
    global _POOL

    if DB_TYPE != "postgres":
        raise RuntimeError(f"Unsupported DB_TYPE: {DB_TYPE}. Only 'postgres' is supported for now.")

    missing = [name for name, val in [
        ("DB_HOST", DB_HOST),
        ("DB_PORT", DB_PORT),
        ("DB_USERNAME", DB_USERNAME),
        ("DB_PASSWORD", DB_PASSWORD),
        ("DB_NAME", DB_NAME),
    ] if not val]
    if missing:
        raise RuntimeError(f"Database configuration missing: {', '.join(missing)}")

    if _POOL is None:
        dsn = _build_dsn()
        _POOL = pool.SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=dsn,
            connect_timeout=10,
            cursor_factory=extras.RealDictCursor,
        )
        logger.info("PostgreSQL connection pool initialized.")

    _ensure_schema()


def close_pool():
    global _POOL
    if _POOL:
        _POOL.closeall()
        _POOL = None
        logger.info("Database connection pool closed.")


def _ensure_schema():
    """
    Create assistant chat tables if they do not exist.
    Uses existing 'users' table (id uuid) - does NOT create or modify it.
    """
    schema_sql = """
    -- Assistant chat sessions table (separate from existing chatboxes/messages)
    CREATE TABLE IF NOT EXISTS assistant_chat_sessions (
        session_id TEXT PRIMARY KEY,
        user_id UUID NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        last_message_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        message_count INTEGER DEFAULT 0 NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    
    CREATE INDEX IF NOT EXISTS idx_assistant_chat_sessions_user_id ON assistant_chat_sessions(user_id);
    CREATE INDEX IF NOT EXISTS idx_assistant_chat_sessions_updated_at ON assistant_chat_sessions(updated_at DESC);

    -- Assistant chat messages table (separate from existing messages table)
    CREATE TABLE IF NOT EXISTS assistant_chat_messages (
        id BIGSERIAL PRIMARY KEY,
        session_id TEXT NOT NULL,
        user_id UUID NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
        content TEXT NOT NULL,
        tool_call_id TEXT,
        tool_name TEXT,
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        FOREIGN KEY (session_id) REFERENCES assistant_chat_sessions(session_id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    
    CREATE INDEX IF NOT EXISTS idx_assistant_chat_messages_session_id ON assistant_chat_messages(session_id);
    CREATE INDEX IF NOT EXISTS idx_assistant_chat_messages_user_id ON assistant_chat_messages(user_id);
    CREATE INDEX IF NOT EXISTS idx_assistant_chat_messages_created_at ON assistant_chat_messages(created_at DESC);
    """

    with get_cursor(commit=True) as cur:
        cur.execute(schema_sql)
    logger.info("Assistant chat database schema ensured (using existing users table).")


@contextmanager
def get_cursor(commit: bool = False):
    """Context manager yielding a cursor from the pool."""
    if _POOL is None:
        init_database()

    conn = _POOL.getconn()
    try:
        cur = conn.cursor()
        yield cur
        if commit:
            conn.commit()
    except Exception as exc:
        conn.rollback()
        raise
    finally:
        _POOL.putconn(conn)


def ensure_user(user_id: str):
    """
    Verify user exists in existing users table.
    Does NOT create or modify the users table - only checks existence.
    """
    with get_cursor(commit=True) as cur:
        # Just verify the user exists - don't try to insert
        cur.execute(
            "SELECT id FROM users WHERE id = %s",
            (user_id,),
        )
        if not cur.fetchone():
            logger.warning(f"User {user_id} not found in users table - chat storage may fail")


def get_or_create_session(session_id: str, user_id: str) -> Optional[Dict]:
    """
    Get or create an assistant chat session.
    Uses existing users table - does NOT modify it.
    Returns None if user doesn't exist or operation fails.
    """
    try:
        ensure_user(user_id)

        with get_cursor(commit=True) as cur:
            cur.execute(
                "SELECT * FROM assistant_chat_sessions WHERE session_id = %s",
                (session_id,),
            )
            row = cur.fetchone()
            if row:
                return dict(row)

            cur.execute(
                """
                INSERT INTO assistant_chat_sessions (session_id, user_id, last_message_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                RETURNING *
                """,
                (session_id, user_id),
            )
            return dict(cur.fetchone())
    except psycopg2.IntegrityError as e:
        # Foreign key constraint violation - user doesn't exist
        logger.error(f"User {user_id} not found in users table: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to get/create session {session_id}: {e}")
        return None


def save_message(
    session_id: str,
    user_id: str,
    role: str,
    content: str,
    tool_call_id: Optional[str] = None,
    tool_name: Optional[str] = None,
) -> Optional[int]:
    """
    Save an assistant chat message.
    Returns the message ID (BIGINT) or None if operation fails.
    """
    try:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO assistant_chat_messages
                (session_id, user_id, role, content, tool_call_id, tool_name)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (session_id, user_id, role, content, tool_call_id, tool_name),
            )
            message_id = cur.fetchone()["id"]

            # Update session metadata
            cur.execute(
                """
                UPDATE assistant_chat_sessions
                SET updated_at = CURRENT_TIMESTAMP,
                    last_message_at = CURRENT_TIMESTAMP,
                    message_count = message_count + 1
                WHERE session_id = %s
                """,
                (session_id,),
            )

            return int(message_id)
    except psycopg2.IntegrityError as e:
        # Foreign key constraint violation - user or session doesn't exist
        logger.error(f"Failed to save message: foreign key constraint violation: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to save message for session {session_id}: {e}")
        return None


def get_session_messages(session_id: str, limit: Optional[int] = None) -> List[Dict]:
    """
    Get assistant chat messages for a session.
    """
    query = """
        SELECT id, role, content, tool_call_id, tool_name, created_at
        FROM assistant_chat_messages
        WHERE session_id = %s
        ORDER BY created_at ASC
    """
    params: List = [session_id]

    if limit:
        query += " LIMIT %s"
        params.append(limit)

    with get_cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall() or []
        return [dict(r) for r in rows]


def get_user_recent_sessions(user_id: str, limit: int = 10) -> List[Dict]:
    """
    Get recent assistant chat sessions for a user.
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM assistant_chat_sessions
            WHERE user_id = %s
            ORDER BY last_message_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        rows = cur.fetchall() or []
        return [dict(r) for r in rows]
