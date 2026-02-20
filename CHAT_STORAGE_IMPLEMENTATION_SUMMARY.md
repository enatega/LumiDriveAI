# Chat Storage Implementation Summary (Phase 1-4)

## Overview
Implemented chat storage for the assistant using the existing database schema. The implementation:
- **Does NOT modify** existing tables (`users`, `messages`, `chatboxes`, etc.)
- **Creates new tables** with distinct names to avoid conflicts
- **Uses existing `users` table** for foreign key relationships
- **Handles errors gracefully** - chat works even if database operations fail

## Database Schema

### New Tables Created

#### 1. `assistant_chat_sessions`
Stores chat sessions for the assistant:
- `session_id` (TEXT PRIMARY KEY) - Unique session identifier
- `user_id` (UUID) - References `users.id` (existing table)
- `created_at`, `updated_at`, `last_message_at` (TIMESTAMP)
- `message_count` (INTEGER)

#### 2. `assistant_chat_messages`
Stores individual chat messages:
- `id` (BIGSERIAL PRIMARY KEY) - Auto-incrementing message ID
- `session_id` (TEXT) - References `assistant_chat_sessions.session_id`
- `user_id` (UUID) - References `users.id` (existing table)
- `role` (TEXT) - 'user', 'assistant', 'system', or 'tool'
- `content` (TEXT) - Message content
- `tool_call_id` (TEXT, nullable) - For tool call tracking
- `tool_name` (TEXT, nullable) - Tool name if applicable
- `created_at` (TIMESTAMP)

#### 3. `assistant_chat_summaries` (Phase 4)
Stores LLM-generated summaries of chat conversations:
- `id` (BIGSERIAL PRIMARY KEY) - Auto-incrementing summary ID
- `session_id` (TEXT) - References `assistant_chat_sessions.session_id`
- `user_id` (UUID) - References `users.id` (existing table)
- `summary_text` (TEXT) - LLM-generated summary
- `message_count` (INTEGER) - Number of messages summarized
- `start_message_id` (BIGINT, nullable) - First message ID in summary range
- `end_message_id` (BIGINT, nullable) - Last message ID in summary range
- `created_at` (TIMESTAMP)

### Indexes Created
- `idx_assistant_chat_sessions_user_id` - Fast user lookup
- `idx_assistant_chat_sessions_updated_at` - Fast recent sessions
- `idx_assistant_chat_messages_session_id` - Fast session message lookup
- `idx_assistant_chat_messages_user_id` - Fast user message lookup
- `idx_assistant_chat_messages_created_at` - Fast chronological ordering
- `idx_assistant_chat_summaries_session_id` - Fast session summary lookup
- `idx_assistant_chat_summaries_user_id` - Fast user summary lookup
- `idx_assistant_chat_summaries_created_at` - Fast chronological ordering

## Key Features

### 1. No Conflicts with Existing Tables
- Uses `assistant_chat_sessions` instead of `chat_sessions` (avoids conflict with existing `chatboxes`)
- Uses `assistant_chat_messages` instead of `chat_messages` (avoids conflict with existing `messages`)
- Does NOT create or modify the `users` table - uses existing one

### 2. User ID Resolution
- Gets `user_id` from JWT token via `/api/v1/users/get-user-id` endpoint
- Verifies user exists in `users` table before creating sessions
- Handles cases where user might not exist gracefully

### 3. Error Handling
- All database operations wrapped in try-catch
- Foreign key violations logged but don't crash the system
- Chat continues to work even if database operations fail
- Returns `None` for failed operations instead of raising exceptions

### 4. Data Persistence
- Messages saved to database automatically
- Sessions created on first message
- Message history loaded from database when session resumes
- Session metadata (message count, last message time) updated automatically

### 5. Chat Summary Generation (Phase 4)
- Automatically generates summaries after threshold number of messages (default: 20)
- Uses OpenAI LLM to create concise summaries focusing on:
  - Pickup and dropoff locations
  - Ride types requested
  - User preferences
  - Recurring patterns
  - Booking outcomes
- Summaries stored in `assistant_chat_summaries` table
- Tracks which messages have been summarized to avoid duplicates
- Configurable via `SUMMARY_GENERATION_THRESHOLD` environment variable

## Files Modified

### `database.py`
- `_ensure_schema()` - Creates new assistant chat tables
- `ensure_user()` - Verifies user exists (doesn't create)
- `get_or_create_session()` - Gets or creates session with error handling
- `save_message()` - Saves messages with error handling
- `get_session_messages()` - Retrieves message history
- `get_user_recent_sessions()` - Gets user's recent sessions

### `memory_store.py`
- `get_memory()` - Now accepts `user_id` parameter
- Loads message history from database on session creation
- Tracks `user_id` mapping for database operations
- `save_chat_to_database()` - Saves messages to database and extracts preferences (Phase 5)

### `server.py`
- Resolves `user_id` from JWT token
- Passes `user_id` to `get_memory()`
- Saves user and assistant messages to database
- Calls `generate_summary_if_needed()` after assistant message is saved
- Saves tool results to database for preference extraction (Phase 5)
- Passes `session_id` to `_run_tools_for_message()` for preference extraction
- Initializes database on startup

### `api.py`
- `get_user_id_from_jwt()` - New function to get user_id from JWT

### `summary_service.py` (Phase 4 - New File)
- `generate_chat_summary()` - Generates summary using OpenAI LLM
- `save_summary()` - Saves summary to database
- `should_generate_summary()` - Checks if summary threshold is reached
- `get_unsummarized_message_ids()` - Gets messages that need summarizing
- `generate_summary_if_needed()` - Main function called after message saving
- `get_session_summaries()` - Retrieves summaries for a session
- `get_user_summaries()` - Retrieves summaries for a user

### `preference_extraction.py` (Phase 5 - New File)
- `extract_preferences_from_tool_result()` - Extracts from structured tool results
- `extract_preferences_from_message_llm()` - Uses LLM for natural language extraction
- `extract_preferences_from_message_regex()` - Fallback regex-based extraction
- `extract_preferences_from_message()` - Main entry point for all extraction
- `update_preference()` - Updates or creates preferences in database
- `get_user_preferences()` - Query preferences with optional filtering
- `get_most_visited_places()` - Get top visited destinations
- `get_preferred_ride_types()` - Get preferred ride types
- `get_common_pickup_locations()` - Get common pickup spots
- `get_common_dropoff_locations()` - Get common destinations
- `get_preferred_payment_methods()` - Get payment preferences

### `database.py` (Phase 5 Updates)
- Added `assistant_user_preferences` table to schema
- Indexes for fast preference queries

## Usage Flow

1. **User sends message** with JWT token
2. **Server resolves user_id** from JWT via API
3. **Server gets/creates session** in database
4. **Server loads message history** from database (if exists)
5. **Assistant processes message** and generates response
6. **Both messages saved** to database:
   - User message saved immediately
   - Assistant response saved after generation
7. **Session metadata updated** (message count, timestamps)
8. **Summary generation checked** (Phase 4):
   - If unsummarized messages >= threshold (default: 20), generate summary
   - Summary includes pickup/dropoff locations, ride types, preferences, patterns
   - Summary saved to `assistant_chat_summaries` table

## Error Scenarios Handled

1. **User doesn't exist in users table**
   - Warning logged, chat continues
   - Database operations return None
   - Chat works but messages not persisted

2. **Database connection failure**
   - Error logged, chat continues
   - In-memory storage still works
   - Messages not persisted until connection restored

3. **Foreign key constraint violation**
   - Caught and logged
   - Chat continues normally
   - No data corruption

## Testing Checklist

- [x] Tables created with correct schema
- [x] Foreign keys reference existing `users` table
- [x] No conflicts with existing tables
- [x] User ID resolution works
- [x] Messages saved to database
- [x] Message history loaded from database
- [x] Error handling prevents crashes
- [x] Chat works even if database fails
- [x] Summary generation triggers after threshold messages (Phase 4)
- [x] Summaries stored correctly in database (Phase 4)
- [x] Summary generation handles errors gracefully (Phase 4)
- [x] Preferences extracted from tool results (Phase 5)
- [x] Preferences extracted from user messages (Phase 5)
- [x] Preferences extracted from assistant responses (Phase 5)
- [x] Preference frequency tracking works (Phase 5)
- [x] Preference queries return correct results (Phase 5)

## Phase 4: Chat Summary Generation (✅ Implemented)

### Features
- **Automatic Summary Generation**: After every 20 messages (configurable), a summary is generated
- **LLM-Powered**: Uses OpenAI GPT models to create concise, actionable summaries
- **Smart Tracking**: Tracks which messages have been summarized to avoid duplicates
- **Focus Areas**: Summaries focus on:
  - Pickup and dropoff locations
  - Ride types requested (LUMI_GO, LUMI_PLUS, LUMI_XL, Courier)
  - User preferences and patterns
  - Booking outcomes

### Configuration
- `SUMMARY_GENERATION_THRESHOLD`: Number of messages before generating summary (default: 20)
- `MODEL`: OpenAI model to use (default: gpt-4o-mini)
- `OPENAI_API_KEY`: Required for summary generation

### Database Schema
- New table: `assistant_chat_summaries`
- Tracks message ranges (`start_message_id` to `end_message_id`)
- Foreign keys to sessions, users, and messages

### Error Handling
- Summary generation failures don't affect chat functionality
- Errors logged but chat continues normally
- Graceful degradation if OpenAI API is unavailable

## Phase 5: User Preference Extraction (✅ Implemented)

### Features
- **Dynamic Extraction**: Uses both LLM and regex patterns for flexible preference extraction
- **Multiple Sources**: Extracts preferences from:
  - Tool call results (structured data - most reliable)
  - User messages (LLM + regex extraction)
  - Assistant responses (booking confirmations, etc.)
- **Preference Types Tracked**:
  - Most visited places (dropoff locations)
  - Preferred ride types (LUMI_GO, LUMI_PLUS, LUMI_XL, Courier)
  - Common pickup locations
  - Common dropoff locations
  - Preferred payment methods (WALLET, CASH, CARD)
  - Time preferences (morning, afternoon, evening, night)
  - Common stops
- **Frequency Tracking**: Tracks how often each preference is used
- **Last Used Timestamp**: Maintains when preferences were last used

### Database Schema
- New table: `assistant_user_preferences`
- Tracks preferences with frequency and timestamps
- Unique constraint on (user_id, preference_type, preference_key)
- Indexed for fast queries by user, type, and frequency

### Integration
- Automatically extracts preferences when messages are saved
- Extracts from tool results immediately after tool execution
- Falls back to regex if LLM extraction fails
- Non-blocking - preference extraction failures don't affect chat functionality

### Helper Functions
- `get_user_preferences()` - Get all preferences or filter by type
- `get_most_visited_places()` - Get top visited destinations
- `get_preferred_ride_types()` - Get preferred ride types
- `get_common_pickup_locations()` - Get common pickup spots
- `get_common_dropoff_locations()` - Get common destinations
- `get_preferred_payment_methods()` - Get payment preferences

## Phase 6: Intelligent Recommendations (✅ Implemented)

### Features
- **Proactive Suggestions**: Assistant uses user preferences and patterns to make intelligent recommendations
- **Context-Aware**: Recommendations are based on:
  - Most visited places (frequency-based)
  - Preferred ride types
  - Common pickup/dropoff locations
  - Preferred payment methods
  - Time preferences
  - Recent booking patterns from summaries
- **Non-Intrusive**: Suggestions are offered, not forced - booking workflow remains unchanged
- **Dynamic**: Recommendations adapt as user preferences evolve

### How It Works
1. **Context Building**: On each request, the system builds a user context from:
   - Top 3 most visited places
   - Top 2 preferred ride types
   - Top 3 common pickup locations
   - Top 3 common dropoff locations
   - Top 2 preferred payment methods
   - Time preferences (if available)
   - Recent booking patterns from summaries (last 3)

2. **System Prompt Injection**: The context is injected into the system prompt, giving the assistant:
   - Knowledge of user's preferences
   - Patterns from past bookings
   - Guidelines for making proactive suggestions

3. **Intelligent Recommendations**: The assistant can now:
   - Suggest usual pickup when user mentions dropoff
   - Recommend preferred ride types when asked
   - Suggest preferred payment methods
   - Reference most visited places naturally
   - Anticipate needs based on patterns

### Example Behaviors
- **User says**: "Take me to F7 Markaz"
  - **Assistant can say**: "I see you often go to F7 Markaz! Would you like me to use your usual pickup at F6 Markaz?"

- **User asks**: "What ride type should I choose?"
  - **Assistant suggests**: Their preferred ride types first (e.g., "Based on your history, you usually prefer LUMI_GO")

- **User doesn't mention payment**: 
  - **Assistant can suggest**: "Would you like to pay via WALLET as usual?"

### Integration
- **No Workflow Changes**: All booking functionality remains exactly the same
- **Non-Blocking**: Recommendation context building failures don't affect chat
- **Automatic**: Works seamlessly in the background
- **Privacy-Aware**: Only uses data from the current user's history

### Files Modified
- **`recommendation_service.py`** (New File):
  - `build_user_recommendation_context()` - Main function to build context from preferences and summaries
  - `get_smart_suggestions()` - Generate suggestions based on user message
  - `should_suggest_pickup()` - Determine if pickup should be suggested
  - `get_recommended_pickup()` - Get most common pickup
  - `get_recommended_dropoff()` - Get most common dropoff
  - `get_recommended_ride_type()` - Get most preferred ride type
  - `get_recommended_payment_method()` - Get most preferred payment method

- **`server.py`**:
  - Integrated `build_user_recommendation_context()` into system prompt building
  - Injects user context before location context
  - Logs recommendation context injection for debugging

### Error Handling
- Recommendation context building failures are logged but don't affect chat
- If no preferences exist, system works normally without recommendations
- Graceful degradation ensures booking workflow always works

## Notes

- All timestamps use `TIMESTAMP WITHOUT TIME ZONE` to match existing schema style
- UUIDs are handled as strings (PostgreSQL auto-converts)
- BIGSERIAL used for message IDs (auto-incrementing, no extension needed)
- All operations are transaction-safe with proper rollback on errors
- Summary generation is asynchronous and non-blocking (Phase 4)
- Summaries are generated in batches of threshold size to optimize LLM usage
- Conversation text is truncated to 8000 characters to stay within token limits