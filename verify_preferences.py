#!/usr/bin/env python3
"""
Script to verify Phase 5: User Preference Extraction

Usage:
    python verify_preferences.py --user-id USER_ID
    python verify_preferences.py --user-id USER_ID --type most_visited_place
    python verify_preferences.py --all-users
"""

import argparse
import sys
import os
from dotenv import load_dotenv

load_dotenv()

from database import init_database, get_cursor
from preference_extraction import (
    get_user_preferences,
    get_most_visited_places,
    get_preferred_ride_types,
    get_common_pickup_locations,
    get_common_dropoff_locations,
    get_preferred_payment_methods,
)

# Initialize database
init_database()


def print_preferences_table(preferences, title):
    """Print preferences in a formatted table"""
    if not preferences:
        print(f"\n{title}: No preferences found")
        return
    
    print(f"\n{title}:")
    print("-" * 80)
    print(f"{'Preference':<40} {'Frequency':<15} {'Last Used':<25}")
    print("-" * 80)
    
    for pref in preferences:
        pref_key = pref.get('preference_key', 'N/A')
        frequency = pref.get('frequency', 0)
        last_used = pref.get('last_used_at', 'N/A')
        
        # Truncate long preference keys
        if len(pref_key) > 38:
            pref_key = pref_key[:35] + "..."
        
        print(f"{pref_key:<40} {frequency:<15} {str(last_used):<25}")
    
    print("-" * 80)


def verify_user_preferences(user_id: str, preference_type: str = None):
    """Verify preferences for a specific user"""
    print(f"\n{'='*80}")
    print(f"VERIFYING PREFERENCES FOR USER: {user_id}")
    print(f"{'='*80}")
    
    # Get all preferences or filtered by type
    if preference_type:
        preferences = get_user_preferences(user_id, preference_type)
        print_preferences_table(preferences, f"Preferences (Type: {preference_type})")
    else:
        # Show all preference types
        all_preferences = get_user_preferences(user_id)
        
        if not all_preferences:
            print("\n❌ No preferences found for this user.")
            print("   Make sure you've had some conversations with the assistant.")
            return
        
        print(f"\n✅ Found {len(all_preferences)} total preferences")
        
        # Group by type
        by_type = {}
        for pref in all_preferences:
            pref_type = pref.get('preference_type', 'unknown')
            if pref_type not in by_type:
                by_type[pref_type] = []
            by_type[pref_type].append(pref)
        
        # Show each type
        print("\n" + "="*80)
        print("BREAKDOWN BY PREFERENCE TYPE")
        print("="*80)
        
        for pref_type, prefs in sorted(by_type.items()):
            print_preferences_table(prefs, pref_type.replace('_', ' ').title())
        
        # Show summary using helper functions
        print("\n" + "="*80)
        print("SUMMARY (Using Helper Functions)")
        print("="*80)
        
        most_visited = get_most_visited_places(user_id, limit=5)
        print_preferences_table(most_visited, "Most Visited Places (Top 5)")
        
        ride_types = get_preferred_ride_types(user_id, limit=3)
        print_preferences_table(ride_types, "Preferred Ride Types (Top 3)")
        
        pickups = get_common_pickup_locations(user_id, limit=5)
        print_preferences_table(pickups, "Common Pickup Locations (Top 5)")
        
        dropoffs = get_common_dropoff_locations(user_id, limit=5)
        print_preferences_table(dropoffs, "Common Dropoff Locations (Top 5)")
        
        payments = get_preferred_payment_methods(user_id, limit=3)
        print_preferences_table(payments, "Preferred Payment Methods (Top 3)")


def list_all_users():
    """List all users who have preferences"""
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT DISTINCT user_id, COUNT(*) as pref_count
                FROM assistant_user_preferences
                GROUP BY user_id
                ORDER BY pref_count DESC
            """)
            users = cur.fetchall()
            
            if not users:
                print("\n❌ No users with preferences found.")
                return
            
            print("\n" + "="*80)
            print("USERS WITH PREFERENCES")
            print("="*80)
            print(f"{'User ID':<40} {'Preference Count':<20}")
            print("-" * 80)
            
            for user in users:
                user_id = user['user_id']
                count = user['pref_count']
                print(f"{str(user_id):<40} {count:<20}")
            
            print("-" * 80)
            print(f"\nTotal users: {len(users)}")
            
    except Exception as e:
        print(f"\n❌ Error listing users: {e}")


def main():
    parser = argparse.ArgumentParser(description='Verify user preference extraction')
    parser.add_argument('--user-id', type=str, help='User ID to verify preferences for')
    parser.add_argument('--type', type=str, help='Filter by preference type', 
                       choices=['most_visited_place', 'preferred_ride_type', 
                               'common_pickup', 'common_dropoff', 
                               'preferred_payment', 'preferred_time', 'common_stop', 'other'])
    parser.add_argument('--all-users', action='store_true', help='List all users with preferences')
    
    args = parser.parse_args()
    
    if args.all_users:
        list_all_users()
    elif args.user_id:
        verify_user_preferences(args.user_id, args.type)
    else:
        parser.print_help()
        print("\n❌ Please provide --user-id or --all-users")
        sys.exit(1)


if __name__ == "__main__":
    main()
