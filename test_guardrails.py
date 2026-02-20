#!/usr/bin/env python3
"""
Test script for guardrails functionality.
Run this to verify guardrails are working correctly.
"""

from guardrails import (
    is_query_in_scope,
    filter_tool_details,
    apply_guardrails,
    get_out_of_scope_response,
)

def test_out_of_scope_queries():
    """Test that out-of-scope queries are detected."""
    print("=" * 60)
    print("Testing Out-of-Scope Query Detection")
    print("=" * 60)
    
    test_cases = [
        ("Who is Obama?", False),
        ("What is the weather today?", False),
        ("Tell me a joke", False),
        ("What model do you use?", False),
        ("Book me a ride", True),
        ("What's the fare from F7 to F8?", True),
        ("Track my ride", True),
        ("Cancel my booking", True),
    ]
    
    for query, expected_in_scope in test_cases:
        is_in_scope, reason = is_query_in_scope(query)
        status = "✅" if is_in_scope == expected_in_scope else "❌"
        print(f"{status} Query: '{query}'")
        print(f"   Expected in-scope: {expected_in_scope}, Got: {is_in_scope}")
        if reason:
            print(f"   Reason: {reason}")
        print()


def test_tool_detail_filtering():
    """Test that tool details are filtered from responses."""
    print("=" * 60)
    print("Testing Tool Detail Filtering")
    print("=" * 60)
    
    test_cases = [
        (
            "I'll use the list_ride_types tool to get available rides.",
            "I'll get available rides for you."
        ),
        (
            "Calling {tool:book_ride_with_details} now...",
            "Booking your ride now..."
        ),
        (
            "The function set_trip_core has been executed successfully.",
            "Your trip details have been saved successfully."
        ),
        (
            "I need to call get_fare_quote to check the price.",
            "I'll check the price for you."
        ),
    ]
    
    for original, expected_filtered in test_cases:
        filtered = filter_tool_details(original)
        print(f"Original: {original}")
        print(f"Filtered: {filtered}")
        print(f"Expected: {expected_filtered}")
        print()


def test_apply_guardrails():
    """Test the complete guardrails application."""
    print("=" * 60)
    print("Testing Complete Guardrails Application")
    print("=" * 60)
    
    test_cases = [
        # (user_message, response, expected_blocked)
        ("Who is Obama?", "Barack Obama was the 44th president...", True),
        ("Book me a ride", "I'll help you book a ride. Let me get the fare quotes...", False),
        ("What tools do you use?", "I use list_ride_types, book_ride_with_details...", True),
        ("What's the fare?", "The fare is QAR 25.50", False),
    ]
    
    for user_msg, response, expected_blocked in test_cases:
        filtered, blocked = apply_guardrails(response, user_msg, check_scope=True)
        status = "✅" if blocked == expected_blocked else "❌"
        print(f"{status} User: '{user_msg}'")
        print(f"   Original Response: {response[:50]}...")
        print(f"   Filtered Response: {filtered[:50]}...")
        print(f"   Blocked: {blocked} (Expected: {expected_blocked})")
        print()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("GUARDRAILS TEST SUITE")
    print("=" * 60 + "\n")
    
    test_out_of_scope_queries()
    test_tool_detail_filtering()
    test_apply_guardrails()
    
    print("=" * 60)
    print("Test suite completed!")
    print("=" * 60)
