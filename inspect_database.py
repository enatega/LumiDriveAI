#!/usr/bin/env python3
"""
Database Inspection Script

This script connects to the staging database and displays:
- All tables in the database
- Schema details for each table (columns, types, constraints)
- Indexes
- Row counts
- Sample data (optional)

Usage:
    python inspect_database.py
"""

import os
import sys
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

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


def get_all_tables(conn):
    """Get list of all tables in the database"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
            ORDER BY table_name;
        """)
        return [row[0] for row in cur.fetchall()]


def get_table_columns(conn, table_name):
    """Get column information for a table"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT 
                column_name,
                data_type,
                character_maximum_length,
                is_nullable,
                column_default,
                ordinal_position
            FROM information_schema.columns
            WHERE table_schema = 'public' 
            AND table_name = %s
            ORDER BY ordinal_position;
        """, (table_name,))
        return cur.fetchall()


def get_table_constraints(conn, table_name):
    """Get constraints (primary keys, foreign keys, unique, check) for a table"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Primary keys
        cur.execute("""
            SELECT 
                kcu.column_name,
                tc.constraint_name,
                tc.constraint_type
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu 
                ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_schema = 'public' 
            AND tc.table_name = %s
            AND tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY', 'UNIQUE', 'CHECK')
            ORDER BY tc.constraint_type, kcu.ordinal_position;
        """, (table_name,))
        return cur.fetchall()


def get_table_indexes(conn, table_name):
    """Get indexes for a table"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT 
                indexname,
                indexdef
            FROM pg_indexes
            WHERE schemaname = 'public' 
            AND tablename = %s
            ORDER BY indexname;
        """, (table_name,))
        return cur.fetchall()


def get_row_count(conn, table_name):
    """Get row count for a table"""
    with conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{table_name}";')
        return cur.fetchone()[0]


def get_sample_data(conn, table_name, limit=3):
    """Get sample data from a table"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f'SELECT * FROM "{table_name}" LIMIT %s;', (limit,))
        return cur.fetchall()


def format_column_type(col):
    """Format column type information"""
    data_type = col['data_type']
    if col['character_maximum_length']:
        data_type += f"({col['character_maximum_length']})"
    
    nullable = "NULL" if col['is_nullable'] == 'YES' else "NOT NULL"
    default = f" DEFAULT {col['column_default']}" if col['column_default'] else ""
    
    return f"{col['column_name']:<30} {data_type:<20} {nullable}{default}"


def print_table_info(conn, table_name):
    """Print detailed information about a table"""
    print(f"\n{'='*80}")
    print(f"📊 TABLE: {table_name}")
    print(f"{'='*80}")
    
    # Row count
    row_count = get_row_count(conn, table_name)
    print(f"\n📈 Row Count: {row_count:,}")
    
    # Columns
    columns = get_table_columns(conn, table_name)
    if columns:
        print(f"\n📋 Columns ({len(columns)}):")
        print("-" * 80)
        for col in columns:
            print(f"  {format_column_type(col)}")
    
    # Constraints
    constraints = get_table_constraints(conn, table_name)
    if constraints:
        print(f"\n🔒 Constraints:")
        print("-" * 80)
        current_type = None
        for constraint in constraints:
            if constraint['constraint_type'] != current_type:
                current_type = constraint['constraint_type']
                print(f"\n  {current_type}:")
            print(f"    - {constraint['constraint_name']} ({constraint['column_name']})")
    
    # Indexes
    indexes = get_table_indexes(conn, table_name)
    if indexes:
        print(f"\n🔍 Indexes ({len(indexes)}):")
        print("-" * 80)
        for idx in indexes:
            print(f"  - {idx['indexname']}")
            # Truncate long index definitions
            idx_def = idx['indexdef']
            if len(idx_def) > 100:
                idx_def = idx_def[:100] + "..."
            print(f"    {idx_def}")
    
    # Sample data (if table has data)
    if row_count > 0:
        print(f"\n📝 Sample Data (first {min(3, row_count)} rows):")
        print("-" * 80)
        samples = get_sample_data(conn, table_name, limit=3)
        for i, row in enumerate(samples, 1):
            print(f"\n  Row {i}:")
            for key, value in row.items():
                # Truncate long values
                if isinstance(value, str) and len(value) > 100:
                    value = value[:100] + "..."
                print(f"    {key}: {value}")


def main():
    """Main function"""
    print("🔍 Database Inspection Tool")
    print("=" * 80)
    print(f"\n📡 Connecting to database...")
    print(f"   Host: {DB_HOST}")
    print(f"   Port: {DB_PORT}")
    print(f"   Database: {DB_NAME}")
    print(f"   User: {DB_USERNAME}")
    
    conn = get_connection()
    print("✅ Connected successfully!\n")
    
    try:
        # Get all tables
        tables = get_all_tables(conn)
        
        if not tables:
            print("⚠️  No tables found in the database.")
            return
        
        print(f"📚 Found {len(tables)} table(s): {', '.join(tables)}\n")
        
        # Print information for each table
        for table_name in tables:
            print_table_info(conn, table_name)
        
        print(f"\n{'='*80}")
        print("✅ Inspection complete!")
        print(f"{'='*80}\n")
        
    except Exception as e:
        print(f"\n❌ Error during inspection: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()
        print("🔌 Connection closed.")


if __name__ == "__main__":
    main()
