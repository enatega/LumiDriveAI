# Testing Guide: Phase 4 - Chat Summary Generation

This guide explains how to test the Phase 4 chat summary generation implementation.

## Prerequisites

1. **Environment Variables** - Ensure these are set in your `.env` file:
   ```bash
   # Database (required)
   DB_TYPE=postgres
   DB_HOST=your-db-host
   DB_PORT=5432
   DB_USERNAME=your-username
   DB_PASSWORD=your-password
   DB_NAME=your-database

   # OpenAI (required for summary generation)
   OPENAI_API_KEY=your-openai-api-key
   MODEL=gpt-4o-mini  # or your preferred model

   # Summary threshold (optional, default: 20)
   SUMMARY_GENERATION_THRESHOLD=20
   ```

2. **Server Running** - The FastAPI server should be running:
   ```bash
   python server.py
   # or
   uvicorn server:app --reload
   ```

## Testing Steps

### Step 1: Verify Database Schema

First, verify that the `assistant_chat_summaries` table was created:

```bash
python verify_chat_storage.py
```

You should see:
- ✅ Tables exist: assistant_chat_sessions, assistant_chat_messages, assistant_chat_summaries
- If the summaries table is missing, the server will create it on startup

### Step 2: Check Current State

Check if you already have summaries:

```bash
# Show all summaries
python verify_chat_storage.py --summaries

# Show summaries for a specific user
python verify_chat_storage.py --summaries --user-id "your-user-id"

# Show summaries for a specific session
python verify_chat_storage.py --summaries --session-id "your-session-id"
```

### Step 3: Generate Test Messages

To trigger summary generation, you need to have at least **20 messages** (or your configured threshold) in a session that haven't been summarized yet.

**Option A: Use the Chat API**

Send messages via the `/chat` endpoint with a valid JWT token:

```bash
# Example using curl
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{
    "session_id": "test-session-123",
    "user_message": "I need a ride from Gaddafi Stadium to Johar Town"
  }'
```

Send at least 20 messages (10 user + 10 assistant responses) in the same session.

**Option B: Check Existing Sessions**

If you already have sessions with many messages:

```bash
# Check how many messages a session has
python verify_chat_storage.py --session-id "your-session-id"

# Check if summaries exist for that session
python verify_chat_storage.py --summaries --session-id "your-session-id"
```

### Step 4: Monitor Summary Generation

After sending messages, check the server logs. You should see:

```
INFO: Generated summary for session test-session-123...: User frequently requests rides from Gaddafi Stadium to Johar Town...
INFO: Saved summary 1 for session test-session-123...
```

### Step 5: Verify Summaries Were Created

```bash
# Check all summaries
python verify_chat_storage.py --summaries

# Check summaries for your test session
python verify_chat_storage.py --summaries --session-id "test-session-123"

# Check full statistics
python verify_chat_storage.py
```

You should see:
- Total Summaries count > 0
- Summary text showing pickup/dropoff locations, ride types, preferences
- Message count showing how many messages were summarized

### Step 6: Test Summary Content

Verify the summary quality:

```bash
python verify_chat_storage.py --summaries --session-id "your-session-id"
```

The summary should include:
- ✅ Pickup and dropoff locations mentioned
- ✅ Ride types requested (LUMI_GO, LUMI_PLUS, etc.)
- ✅ User preferences or patterns
- ✅ Booking outcomes

## Troubleshooting

### Issue: Summaries Not Being Generated

**Check 1: Message Count**
```bash
python verify_chat_storage.py --session-id "your-session-id"
```
Ensure the session has at least 20 messages (or your configured threshold).

**Check 2: OpenAI API Key**
```bash
# Check if OPENAI_API_KEY is set
echo $OPENAI_API_KEY
```
The summary service will log a warning if the API key is missing.

**Check 3: Server Logs**
Look for errors in the server logs:
- `Failed to generate summary: ...`
- `OpenAI client not initialized - skipping summary generation`

**Check 4: Database Connection**
```bash
python verify_chat_storage.py
```
Ensure database connection is working.

### Issue: Summary Generation Fails Silently

Check server logs for:
- `Failed to generate summary for session ...`
- `Failed to save summary for session ...`

These errors are logged but don't crash the chat functionality.

### Issue: Wrong Summary Content

The summary prompt focuses on:
- Pickup/dropoff locations
- Ride types
- User preferences
- Booking patterns

If summaries are too generic, you can adjust the prompt in `summary_service.py` in the `generate_chat_summary()` function.

## Testing with Lower Threshold

For faster testing, you can temporarily lower the threshold:

```bash
# In .env file
SUMMARY_GENERATION_THRESHOLD=5  # Generate summary after 5 messages
```

Then restart the server and send 5 messages to trigger summary generation.

## Expected Behavior

1. **First 19 messages**: No summary generated
2. **20th message**: Summary generated automatically after assistant response
3. **Next 20 messages**: Another summary generated (covering messages 21-40)
4. **Summary storage**: Each summary tracks which message IDs it covers

## Verification Checklist

- [ ] `assistant_chat_summaries` table exists
- [ ] At least one session has 20+ messages
- [ ] Summary was generated (check logs)
- [ ] Summary appears in database (verify script)
- [ ] Summary content includes relevant information
- [ ] No errors in server logs
- [ ] Chat functionality still works normally

## Next Steps

Once summaries are working:
- Phase 5: User preference extraction (uses summaries)
- Phase 6: Intelligent recommendations (uses summaries and preferences)

## Quick Test Script

You can create a simple test script to send multiple messages:

```python
# test_summary_generation.py
import requests
import time

BASE_URL = "http://localhost:8000"
JWT_TOKEN = "your-jwt-token"
SESSION_ID = "test-summary-session"

headers = {
    "Authorization": f"Bearer {JWT_TOKEN}",
    "Content-Type": "application/json"
}

messages = [
    "I need a ride from Gaddafi Stadium to Johar Town",
    "What ride types are available?",
    "I prefer LUMI_GO",
    "How much will it cost?",
    # ... add more messages to reach threshold
]

for i, msg in enumerate(messages, 1):
    response = requests.post(
        f"{BASE_URL}/chat",
        headers=headers,
        json={
            "session_id": SESSION_ID,
            "user_message": msg
        }
    )
    print(f"Message {i}: {response.status_code}")
    time.sleep(1)  # Small delay between messages

print(f"\nCheck summaries with:")
print(f"python verify_chat_storage.py --summaries --session-id {SESSION_ID}")
```

Run it:
```bash
python test_summary_generation.py
```
