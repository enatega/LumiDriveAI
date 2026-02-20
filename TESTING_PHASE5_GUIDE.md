# Phase 5: User Preference Extraction - Testing Guide

## Overview
This guide provides test messages and verification steps to ensure preference extraction is working correctly.

## Test Session Flow

### Step 1: Basic Location Preferences
Test pickup and dropoff location extraction:

```
User: "I need a ride from Gaddafi Stadium to Johar Town"
```

**Expected Preferences Extracted:**
- `common_pickup`: "Gaddafi Stadium"
- `common_dropoff`: "Johar Town"
- `most_visited_place`: "Johar Town"

---

### Step 2: Ride Type Preference
Test ride type extraction:

```
User: "Book me a LUMI_GO ride"
```

**Expected Preferences Extracted:**
- `preferred_ride_type`: "LUMI_GO"

---

### Step 3: Complete Booking (Tool Result Extraction)
Test structured data extraction from tool results:

```
User: "Book a ride from Model Town to F-6 Markaz using LUMI_PLUS, pay with wallet"
```

**Expected Preferences Extracted (from tool result):**
- `common_pickup`: "Model Town"
- `common_dropoff`: "F-6 Markaz"
- `most_visited_place`: "F-6 Markaz"
- `preferred_ride_type`: "LUMI_PLUS"
- `preferred_payment`: "WALLET"

---

### Step 4: Payment Method Preference
Test payment method extraction:

```
User: "I'll pay with cash"
```

**Expected Preferences Extracted:**
- `preferred_payment`: "CASH"

---

### Step 5: Time Preference
Test time preference extraction:

```
User: "I need a ride tomorrow morning"
```

**Expected Preferences Extracted:**
- `preferred_time`: "morning"

---

### Step 6: Multiple Locations (Frequency Tracking)
Test frequency incrementing:

```
User: "Take me to Johar Town again"
```

**Expected Result:**
- `common_dropoff`: "Johar Town" (frequency should be 2)
- `most_visited_place`: "Johar Town" (frequency should be 2)

---

### Step 7: Stops Extraction
Test stops extraction:

```
User: "I need to go from DHA Phase 5 to Airport, with a stop at Mall Road"
```

**Expected Preferences Extracted:**
- `common_pickup`: "DHA Phase 5"
- `common_dropoff`: "Airport"
- `common_stop`: "Mall Road"
- `most_visited_place`: "Airport"

---

### Step 8: Natural Language Extraction (LLM)
Test LLM-based extraction from natural language:

```
User: "I usually go to Liberty Market in the evening, prefer LUMI_XL rides"
```

**Expected Preferences Extracted:**
- `common_dropoff`: "Liberty Market"
- `most_visited_place`: "Liberty Market"
- `preferred_ride_type`: "LUMI_XL"
- `preferred_time`: "evening"

---

### Step 9: Assistant Response Extraction
Test extraction from assistant booking confirmations:

After booking, assistant might say:
```
Assistant: "Your ride from Model Town to F-6 Markaz has been booked successfully!"
```

**Expected Preferences Extracted:**
- `common_pickup`: "Model Town"
- `common_dropoff`: "F-6 Markaz"
- `most_visited_place`: "F-6 Markaz"

---

### Step 10: Multiple Ride Types
Test different ride types:

```
User: "Book a Courier service from my location to Gulberg"
```

**Expected Preferences Extracted:**
- `preferred_ride_type`: "Courier"
- `common_dropoff`: "Gulberg"
- `most_visited_place`: "Gulberg"

---

## Complete Test Sequence

Here's a complete conversation flow to test all features:

```
1. User: "I need a ride from Gaddafi Stadium to Johar Town"
   → Assistant processes and books ride

2. User: "Book me a LUMI_GO ride from Model Town to F-6 Markaz"
   → Assistant processes and books ride

3. User: "I'll pay with wallet this time"
   → Assistant acknowledges

4. User: "Take me to Johar Town again, use LUMI_PLUS"
   → Assistant processes and books ride

5. User: "I need a ride tomorrow morning to Airport"
   → Assistant processes and books ride

6. User: "Book Courier service from DHA to Gulberg"
   → Assistant processes and books ride
```

---

## Verification Methods

### Method 1: Using the Verification Script

Run the provided script to check extracted preferences:

```bash
python verify_preferences.py --user-id YOUR_USER_ID
```

### Method 2: Direct Database Query

Connect to your PostgreSQL database and run:

```sql
-- Get all preferences for a user
SELECT * FROM assistant_user_preferences 
WHERE user_id = 'YOUR_USER_ID' 
ORDER BY frequency DESC, last_used_at DESC;

-- Get most visited places
SELECT preference_key, frequency, last_used_at 
FROM assistant_user_preferences 
WHERE user_id = 'YOUR_USER_ID' 
  AND preference_type = 'most_visited_place'
ORDER BY frequency DESC;

-- Get preferred ride types
SELECT preference_key, frequency 
FROM assistant_user_preferences 
WHERE user_id = 'YOUR_USER_ID' 
  AND preference_type = 'preferred_ride_type'
ORDER BY frequency DESC;

-- Get common pickup locations
SELECT preference_key, frequency 
FROM assistant_user_preferences 
WHERE user_id = 'YOUR_USER_ID' 
  AND preference_type = 'common_pickup'
ORDER BY frequency DESC;

-- Get common dropoff locations
SELECT preference_key, frequency 
FROM assistant_user_preferences 
WHERE user_id = 'YOUR_USER_ID' 
  AND preference_type = 'common_dropoff'
ORDER BY frequency DESC;

-- Get payment preferences
SELECT preference_key, frequency 
FROM assistant_user_preferences 
WHERE user_id = 'YOUR_USER_ID' 
  AND preference_type = 'preferred_payment'
ORDER BY frequency DESC;
```

### Method 3: Using Python Helper Functions

Create a test script:

```python
from preference_extraction import (
    get_user_preferences,
    get_most_visited_places,
    get_preferred_ride_types,
    get_common_pickup_locations,
    get_common_dropoff_locations,
    get_preferred_payment_methods
)

user_id = "YOUR_USER_ID"

print("=== All Preferences ===")
all_prefs = get_user_preferences(user_id)
for pref in all_prefs:
    print(f"{pref['preference_type']}: {pref['preference_key']} (frequency: {pref['frequency']})")

print("\n=== Most Visited Places ===")
places = get_most_visited_places(user_id, limit=5)
for place in places:
    print(f"{place['preference_key']}: {place['frequency']} times")

print("\n=== Preferred Ride Types ===")
ride_types = get_preferred_ride_types(user_id)
for rt in ride_types:
    print(f"{rt['preference_key']}: {rt['frequency']} times")

print("\n=== Common Pickup Locations ===")
pickups = get_common_pickup_locations(user_id)
for pickup in pickups:
    print(f"{pickup['preference_key']}: {pickup['frequency']} times")

print("\n=== Common Dropoff Locations ===")
dropoffs = get_common_dropoff_locations(user_id)
for dropoff in dropoffs:
    print(f"{dropoff['preference_key']}: {dropoff['frequency']} times")

print("\n=== Preferred Payment Methods ===")
payments = get_preferred_payment_methods(user_id)
for payment in payments:
    print(f"{payment['preference_key']}: {payment['frequency']} times")
```

---

## Expected Results After Complete Test Sequence

After running the complete test sequence, you should see:

### Most Visited Places:
- Johar Town: 2 times
- F-6 Markaz: 1 time
- Airport: 1 time
- Gulberg: 1 time

### Preferred Ride Types:
- LUMI_GO: 1 time
- LUMI_PLUS: 1 time
- Courier: 1 time

### Common Pickup Locations:
- Gaddafi Stadium: 1 time
- Model Town: 1 time
- DHA: 1 time

### Common Dropoff Locations:
- Johar Town: 2 times
- F-6 Markaz: 1 time
- Airport: 1 time
- Gulberg: 1 time

### Preferred Payment Methods:
- WALLET: 1 time

---

## Troubleshooting

### Preferences Not Being Extracted

1. **Check Database Connection**: Ensure database is initialized
   ```python
   from database import init_database
   init_database()
   ```

2. **Check User ID**: Ensure user_id is being resolved correctly
   - Check server logs for user_id resolution
   - Verify JWT token is valid

3. **Check Tool Results**: Ensure tool results are being saved
   - Check `assistant_chat_messages` table for tool messages
   - Verify `tool_name` and `content` are populated

4. **Check LLM API**: If LLM extraction fails, regex fallback should work
   - Check OpenAI API key is set
   - Check logs for LLM extraction errors

5. **Check Logs**: Look for preference extraction errors
   ```bash
   # Check server logs for errors
   grep -i "preference" server.log
   grep -i "extract" server.log
   ```

### Frequency Not Incrementing

- Ensure same `preference_key` is used (case-sensitive matching)
- Check database for duplicate entries with different casing
- Verify `UNIQUE` constraint is working correctly

### Preferences Extracted But Not Queryable

- Verify user_id format matches (UUID format)
- Check database indexes are created
- Verify foreign key constraints are satisfied

---

## Quick Test Checklist

- [ ] Preferences extracted from tool results (structured data)
- [ ] Preferences extracted from user messages (LLM + regex)
- [ ] Preferences extracted from assistant responses
- [ ] Frequency increments correctly for repeated preferences
- [ ] Last used timestamp updates correctly
- [ ] All preference types are tracked (pickup, dropoff, ride_type, payment, time, stops)
- [ ] Most visited places tracked correctly
- [ ] Helper functions return correct results
- [ ] Database queries work correctly
- [ ] Error handling works (extraction failures don't crash chat)

---

## Notes

- Preferences are extracted asynchronously and non-blocking
- Extraction failures are logged but don't affect chat functionality
- LLM extraction may take a few seconds, regex fallback is instant
- Tool result extraction is most reliable (structured data)
- Natural language extraction (LLM) handles variations better than regex
- Frequency tracking helps identify user patterns over time
