#!/usr/bin/env python3
"""
Chat Storage Verification Script

This script verifies that chat messages are being stored correctly in the database.
It checks:
- Sessions are created properly
- Messages are saved with correct user_id and session_id
- Message counts are accurate
- Data integrity (foreign keys, timestamps, etc.)

Usage:
    python verify_chat_storage.py [--user-id USER_ID] [--session-id SESSION_ID] [--limit N]
"""

import os
import sys
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import argparse

# Load environment variables
load_dotenv()

# Database configuration
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_USERNAME = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")


def get_connection():
    """Create a database connection"""
    if not all([DB_HOST, DB_PORT, DB_USERNAME, DB_PASSWORD, DB_NAME]):
        missing = [name for name, val in [
            ("DB_HOST", DB_HOST),
            ("DB_PORT", DB_PORT),
            ("DB_USERNAME", DB_USERNAME),
            ("DB_PASSWORD", DB_PASSWORD),
            ("DB_NAME", DB_NAME),
        ] if not val]
        raise ValueError(f"Missing database configuration: {', '.join(missing)}")
    
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USERNAME,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        return conn
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
        sys.exit(1)


def check_tables_exist(conn):
    """Verify that assistant chat tables exist"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('assistant_chat_sessions', 'assistant_chat_messages', 'assistant_chat_summaries')
            ORDER BY table_name;
        """)
        tables = [row[0] for row in cur.fetchall()]
        
        expected_tables = ['assistant_chat_sessions', 'assistant_chat_messages', 'assistant_chat_summaries']
        missing = [t for t in expected_tables if t not in tables]
        
        if missing:
            print(f"⚠️  Missing tables: {', '.join(missing)}")
            print(f"   Found: {', '.join(tables) if tables else 'none'}")
            if 'assistant_chat_summaries' in missing:
                print("   Note: assistant_chat_summaries is from Phase 4 - may not exist yet")
        
        if len(tables) >= 2:
            print(f"✅ Tables exist: {', '.join(tables)}")
            return True
        else:
            print("❌ Missing core tables!")
            return False


def get_statistics(conn):
    """Get overall statistics"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Session stats
        cur.execute("""
            SELECT 
                COUNT(*) as total_sessions,
                COUNT(DISTINCT user_id) as unique_users,
                SUM(message_count) as total_messages_stored,
                MAX(last_message_at) as most_recent_activity
            FROM assistant_chat_sessions
        """)
        session_stats = cur.fetchone()
        
        # Message stats
        cur.execute("""
            SELECT 
                COUNT(*) as total_messages,
                COUNT(DISTINCT session_id) as sessions_with_messages,
                COUNT(DISTINCT user_id) as users_with_messages,
                COUNT(CASE WHEN role = 'user' THEN 1 END) as user_messages,
                COUNT(CASE WHEN role = 'assistant' THEN 1 END) as assistant_messages,
                COUNT(CASE WHEN role = 'system' THEN 1 END) as system_messages,
                COUNT(CASE WHEN role = 'tool' THEN 1 END) as tool_messages,
                MIN(created_at) as oldest_message,
                MAX(created_at) as newest_message
            FROM assistant_chat_messages
        """)
        message_stats = cur.fetchone()
        
        # Summary stats (Phase 4) - check if table exists first
        summary_stats = {}
        try:
            cur.execute("""
                SELECT 
                    COUNT(*) as total_summaries,
                    COUNT(DISTINCT session_id) as sessions_with_summaries,
                    COUNT(DISTINCT user_id) as users_with_summaries,
                    SUM(message_count) as total_messages_summarized,
                    MIN(created_at) as oldest_summary,
                    MAX(created_at) as newest_summary
                FROM assistant_chat_summaries
            """)
            summary_stats = dict(cur.fetchone())
        except Exception:
            # Table doesn't exist yet
            summary_stats = None
        
        return dict(session_stats), dict(message_stats), summary_stats


def verify_data_integrity(conn):
    """Verify data integrity (foreign keys, message counts, etc.)"""
    issues = []
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check sessions with mismatched message counts
        cur.execute("""
            SELECT 
                s.session_id,
                s.user_id,
                s.message_count as stored_count,
                COUNT(m.id) as actual_count
            FROM assistant_chat_sessions s
            LEFT JOIN assistant_chat_messages m ON s.session_id = m.session_id
            GROUP BY s.session_id, s.user_id, s.message_count
            HAVING s.message_count != COUNT(m.id)
        """)
        mismatched = cur.fetchall()
        if mismatched:
            issues.append(f"⚠️  {len(mismatched)} session(s) with mismatched message counts")
            for row in mismatched[:5]:  # Show first 5
                issues.append(f"   Session {row['session_id'][:20]}...: stored={row['stored_count']}, actual={row['actual_count']}")
        
        # Check messages with invalid session_id
        cur.execute("""
            SELECT COUNT(*) as count
            FROM assistant_chat_messages m
            LEFT JOIN assistant_chat_sessions s ON m.session_id = s.session_id
            WHERE s.session_id IS NULL
        """)
        orphaned = cur.fetchone()['count']
        if orphaned > 0:
            issues.append(f"❌ {orphaned} message(s) with invalid session_id (orphaned)")
        
        # Check messages with invalid user_id
        cur.execute("""
            SELECT COUNT(*) as count
            FROM assistant_chat_messages m
            LEFT JOIN users u ON m.user_id = u.id
            WHERE u.id IS NULL
        """)
        invalid_user = cur.fetchone()['count']
        if invalid_user > 0:
            issues.append(f"❌ {invalid_user} message(s) with invalid user_id")
        
        # Check sessions with invalid user_id
        cur.execute("""
            SELECT COUNT(*) as count
            FROM assistant_chat_sessions s
            LEFT JOIN users u ON s.user_id = u.id
            WHERE u.id IS NULL
        """)
        invalid_session_user = cur.fetchone()['count']
        if invalid_session_user > 0:
            issues.append(f"❌ {invalid_session_user} session(s) with invalid user_id")
    
    if not issues:
        print("✅ Data integrity check passed")
        return True
    else:
        print("\n".join(issues))
        return False


def show_recent_sessions(conn, limit=10):
    """Show recent chat sessions"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT 
                session_id,
                user_id,
                message_count,
                created_at,
                last_message_at,
                updated_at
            FROM assistant_chat_sessions
            ORDER BY last_message_at DESC
            LIMIT %s
        """, (limit,))
        sessions = cur.fetchall()
        
        if not sessions:
            print("ℹ️  No chat sessions found")
            return
        
        print(f"\n📋 Recent Sessions (last {limit}):")
        print("=" * 100)
        for i, session in enumerate(sessions, 1):
            print(f"\n{i}. Session: {session['session_id'][:50]}...")
            print(f"   User ID: {session['user_id']}")
            print(f"   Messages: {session['message_count']}")
            print(f"   Created: {session['created_at']}")
            print(f"   Last Activity: {session['last_message_at']}")


def show_session_messages(conn, session_id, limit=20):
    """Show messages for a specific session"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT 
                id,
                role,
                LEFT(content, 100) as content_preview,
                tool_name,
                created_at
            FROM assistant_chat_messages
            WHERE session_id = %s
            ORDER BY created_at ASC
            LIMIT %s
        """, (session_id, limit))
        messages = cur.fetchall()
        
        if not messages:
            print(f"ℹ️  No messages found for session: {session_id}")
            return
        
        print(f"\n💬 Messages for Session: {session_id[:50]}...")
        print("=" * 100)
        for i, msg in enumerate(messages, 1):
            role_icon = {
                'user': '👤',
                'assistant': '🤖',
                'system': '⚙️',
                'tool': '🔧'
            }.get(msg['role'], '❓')
            
            content = msg['content_preview']
            if len(content) == 100:
                content += "..."
            
            print(f"\n{i}. {role_icon} {msg['role'].upper()}")
            print(f"   Content: {content}")
            if msg['tool_name']:
                print(f"   Tool: {msg['tool_name']}")
            print(f"   Time: {msg['created_at']}")


def show_summaries(conn, session_id=None, user_id=None, limit=10):
    """Show summaries for a session or user"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if session_id:
            cur.execute("""
                SELECT 
                    id,
                    session_id,
                    summary_text,
                    message_count,
                    start_message_id,
                    end_message_id,
                    created_at
                FROM assistant_chat_summaries
                WHERE session_id = %s
                ORDER BY created_at ASC
            """, (session_id,))
            title = f"Summaries for Session: {session_id[:50]}..."
        elif user_id:
            cur.execute("""
                SELECT 
                    id,
                    session_id,
                    summary_text,
                    message_count,
                    start_message_id,
                    end_message_id,
                    created_at
                FROM assistant_chat_summaries
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (user_id, limit))
            title = f"Summaries for User: {user_id}"
        else:
            cur.execute("""
                SELECT 
                    id,
                    session_id,
                    summary_text,
                    message_count,
                    start_message_id,
                    end_message_id,
                    created_at
                FROM assistant_chat_summaries
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))
            title = f"Recent Summaries (last {limit})"
        
        summaries = cur.fetchall()
        
        if not summaries:
            print(f"ℹ️  No summaries found")
            return
        
        print(f"\n📝 {title}")
        print("=" * 100)
        for i, summary in enumerate(summaries, 1):
            print(f"\n{i}. Summary ID: {summary['id']}")
            print(f"   Session: {summary['session_id'][:50]}...")
            print(f"   Messages Covered: {summary['message_count']} (IDs: {summary['start_message_id']} - {summary['end_message_id']})")
            print(f"   Created: {summary['created_at']}")
            summary_text = summary['summary_text']
            if len(summary_text) > 200:
                summary_text = summary_text[:200] + "..."
            print(f"   Summary: {summary_text}")


def show_user_sessions(conn, user_id, limit=10, show_messages=True):
    """Show sessions for a specific user"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT 
                session_id,
                message_count,
                created_at,
                last_message_at
            FROM assistant_chat_sessions
            WHERE user_id = %s
            ORDER BY last_message_at DESC
            LIMIT %s
        """, (user_id, limit))
        sessions = cur.fetchall()
        
        if not sessions:
            print(f"ℹ️  No sessions found for user: {user_id}")
            return
        
        print(f"\n👤 Sessions for User: {user_id}")
        print("=" * 100)
        for i, session in enumerate(sessions, 1):
            print(f"\n{i}. Session: {session['session_id'][:50]}...")
            print(f"   Messages: {session['message_count']}")
            print(f"   Created: {session['created_at']}")
            print(f"   Last Activity: {session['last_message_at']}")
            
            # Show messages for this session
            if show_messages:
                cur.execute("""
                    SELECT 
                        id,
                        role,
                        content,
                        tool_name,
                        created_at
                    FROM assistant_chat_messages
                    WHERE session_id = %s
                    ORDER BY created_at ASC
                """, (session['session_id'],))
                messages = cur.fetchall()
                
                if messages:
                    print(f"\n   💬 Messages ({len(messages)}):")
                    for j, msg in enumerate(messages, 1):
                        role_icon = {
                            'user': '👤',
                            'assistant': '🤖',
                            'system': '⚙️',
                            'tool': '🔧'
                        }.get(msg['role'], '❓')
                        
                        content = msg['content']
                        # Truncate long messages
                        if len(content) > 150:
                            content_preview = content[:150] + "..."
                        else:
                            content_preview = content
                        
                        print(f"      {j}. {role_icon} {msg['role'].upper()}: {content_preview}")
                        if msg['tool_name']:
                            print(f"         Tool: {msg['tool_name']}")
                        print(f"         Time: {msg['created_at']}")
                else:
                    print(f"   ℹ️  No messages found for this session")


def main():
    parser = argparse.ArgumentParser(description="Verify chat storage in database")
    parser.add_argument("--user-id", help="Filter by user ID")
    parser.add_argument("--session-id", help="Show messages for specific session")
    parser.add_argument("--summaries", action="store_true", help="Show summaries")
    parser.add_argument("--limit", type=int, default=10, help="Limit results (default: 10)")
    args = parser.parse_args()
    
    print("🔍 Chat Storage Verification")
    print("=" * 100)
    
    conn = get_connection()
    print("✅ Connected to database\n")
    
    try:
        # Check tables exist
        if not check_tables_exist(conn):
            print("\n❌ Tables missing - chat storage may not be initialized")
            return
        
        # Get statistics
        print("\n📊 Statistics:")
        print("-" * 100)
        session_stats, message_stats, summary_stats = get_statistics(conn)
        
        print(f"\nSessions:")
        print(f"  Total Sessions: {session_stats['total_sessions']}")
        print(f"  Unique Users: {session_stats['unique_users']}")
        print(f"  Total Messages (stored count): {session_stats['total_messages_stored']}")
        if session_stats['most_recent_activity']:
            print(f"  Most Recent Activity: {session_stats['most_recent_activity']}")
        
        print(f"\nMessages:")
        print(f"  Total Messages: {message_stats['total_messages']}")
        print(f"  Sessions with Messages: {message_stats['sessions_with_messages']}")
        print(f"  Users with Messages: {message_stats['users_with_messages']}")
        print(f"  User Messages: {message_stats['user_messages']}")
        print(f"  Assistant Messages: {message_stats['assistant_messages']}")
        print(f"  System Messages: {message_stats['system_messages']}")
        print(f"  Tool Messages: {message_stats['tool_messages']}")
        if message_stats['oldest_message']:
            print(f"  Oldest Message: {message_stats['oldest_message']}")
        if message_stats['newest_message']:
            print(f"  Newest Message: {message_stats['newest_message']}")
        
        # Summary stats (Phase 4)
        if summary_stats:
            print(f"\nSummaries (Phase 4):")
            print(f"  Total Summaries: {summary_stats['total_summaries']}")
            print(f"  Sessions with Summaries: {summary_stats['sessions_with_summaries']}")
            print(f"  Users with Summaries: {summary_stats['users_with_summaries']}")
            print(f"  Total Messages Summarized: {summary_stats['total_messages_summarized']}")
            if summary_stats['oldest_summary']:
                print(f"  Oldest Summary: {summary_stats['oldest_summary']}")
            if summary_stats['newest_summary']:
                print(f"  Newest Summary: {summary_stats['newest_summary']}")
        else:
            print(f"\nSummaries (Phase 4):")
            print(f"  ⚠️  assistant_chat_summaries table not found (Phase 4 may not be initialized)")
        
        # Verify data integrity
        print("\n🔒 Data Integrity Check:")
        print("-" * 100)
        verify_data_integrity(conn)
        
        # Show specific data
        if args.summaries:
            show_summaries(conn, session_id=args.session_id, user_id=args.user_id, limit=args.limit)
        elif args.session_id:
            show_session_messages(conn, args.session_id, args.limit)
            # Also show summaries for this session if available
            try:
                show_summaries(conn, session_id=args.session_id)
            except Exception:
                pass
        elif args.user_id:
            show_user_sessions(conn, args.user_id, args.limit, show_messages=True)
            # Also show summaries for this user if available
            try:
                show_summaries(conn, user_id=args.user_id, limit=args.limit)
            except Exception:
                pass
        else:
            show_recent_sessions(conn, args.limit)
        
        print("\n" + "=" * 100)
        print("✅ Verification complete!")
        
    except Exception as e:
        print(f"\n❌ Error during verification: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()
        print("\n🔌 Connection closed.")


if __name__ == "__main__":
    main()
