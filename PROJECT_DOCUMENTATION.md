# LumiDrive Assistant - Project Documentation

## Overview
LumiDrive Assistant is a voice-enabled AI-powered ride booking assistant that allows customers to book rides through natural language conversations. The system integrates with the LumiDrive backend API to handle ride requests, fare quotes, bid management, and ride tracking.

---

## Technical Approach

### Architecture
The project follows a **client-server architecture** with:
- **Backend**: FastAPI-based REST API that handles AI chat, speech-to-text, and text-to-speech
- **Frontend**: React Native/Expo mobile application with Redux state management
- **AI Integration**: OpenAI GPT models with function calling for structured tool execution
- **Memory Management**: LangChain-based conversation memory for session persistence

### Core Design Principles
1. **Function Calling**: Uses OpenAI's function calling feature to execute structured operations (ride booking, fare queries, bid acceptance)
2. **Session-based Memory**: Each conversation session maintains context using LangChain's ConversationBufferMemory
3. **Streaming Responses**: Real-time token streaming for better user experience
4. **Multi-modal Support**: Text and voice input/output capabilities
5. **State Management**: Server-side state tracking for ride booking workflow

---

## Technical Libraries and Their Uses

### Backend Libraries (Python)

#### Core Framework
- **FastAPI (0.115.0)**: Modern, fast web framework for building REST APIs
  - Used for: HTTP endpoints (`/chat`, `/stt`, `/tts`), request/response handling, CORS middleware
  - Key Features: Automatic API documentation, async support, type validation

- **Uvicorn (0.30.6)**: ASGI server for running FastAPI applications
  - Used for: Production server deployment, handling concurrent requests

#### AI & Machine Learning
- **openai (1.51.0)**: Official OpenAI Python SDK
  - Used for: 
    - Chat completions with GPT-4o-mini model
    - Speech-to-text transcription (gpt-4o-mini-transcribe)
    - Text-to-speech synthesis (gpt-4o-mini-tts)
    - Function calling/tool execution

- **langchain (0.3.1)**: Framework for building LLM applications
  - Used for: Conversation memory management (ConversationBufferMemory)
  - Purpose: Maintains chat history per session, converts between LangChain and OpenAI message formats

#### HTTP & Networking
- **requests (2.32.3)**: HTTP library for making API calls
  - Used for: Communicating with LumiDrive backend API (ride booking, fare queries, bid management)

- **httpx (0.27.2)**: Modern HTTP client with async support
  - Used for: Alternative HTTP client (backup/async operations)

- **httpcore (1.0.5)**: Low-level HTTP transport library
  - Used for: HTTP connection pooling and transport layer

#### Data Validation & Configuration
- **pydantic (2.9.2)**: Data validation using Python type annotations
  - Used for: Request/response models (ChatMessage, ChatRequest, TTSRequest), automatic validation

- **python-dotenv (1.0.1)**: Environment variable management
  - Used for: Loading configuration from `.env` files (API keys, backend URLs, model settings)

#### Database (Optional)
- **psycopg2-binary (2.9.9)**: PostgreSQL database adapter
  - Used for: Database connectivity (if persistent storage is needed)

#### File Handling
- **python-multipart**: Multipart form data handling
  - Used for: Processing audio file uploads in `/stt` endpoint

### Frontend Libraries (React Native/TypeScript)

#### Core Framework
- **React Native (0.79.3)**: Mobile app framework
- **Expo (~53.0.11)**: React Native toolchain and services
- **TypeScript (5.3.3)**: Type-safe JavaScript

#### State Management
- **@reduxjs/toolkit (2.7.0)**: Modern Redux with simplified API
  - Used for: Global state management (auth tokens, user data)
- **react-redux (9.2.0)**: React bindings for Redux
- **redux-persist (6.0.0)**: Persist Redux state to storage

#### Networking
- **axios (1.12.0)**: HTTP client for API calls
- **@tanstack/react-query (5.89.0)**: Data fetching and caching

#### UI Components
- **@react-navigation/native (7.0.14)**: Navigation library
- **react-native-maps (1.20.1)**: Map integration for location selection
- **react-native-google-places-autocomplete (2.5.7)**: Location autocomplete

#### Voice & Audio
- **@twilio/voice-react-native-sdk (1.6.1)**: Voice calling capabilities
- **expo-av (15.1.7)**: Audio playback and recording

---

## Models Used

### OpenAI Models

1. **GPT-4o-mini (Default Chat Model)**
   - **Purpose**: Main conversational AI model
   - **Configuration**: Set via `MODEL` environment variable (default: "gpt-4o-mini")
   - **Usage**: 
     - Processes user messages and generates responses
     - Executes function calls (tools) for ride booking operations
     - Maintains conversation context and flow

2. **gpt-4o-mini-transcribe (STT Model)**
   - **Purpose**: Speech-to-text transcription
   - **Configuration**: Set via `STT_MODEL` environment variable
   - **Usage**: Converts audio recordings to text for voice input

3. **gpt-4o-mini-tts (TTS Model)**
   - **Purpose**: Text-to-speech synthesis
   - **Configuration**: Set via `TTS_MODEL` environment variable
   - **Voice Options**: Configurable via `TTS_VOICE` (default: "alloy")
   - **Audio Format**: Configurable via `TTS_FORMAT` (default: "mp3")
   - **Usage**: Converts assistant responses to audio for voice output

### Model Configuration
All models are configured via environment variables in `.env`:
- `OPENAI_API_KEY`: Required API key for OpenAI services
- `MODEL`: Chat completion model (default: "gpt-4o-mini")
- `STT_MODEL`: Speech-to-text model (default: "gpt-4o-mini-transcribe")
- `TTS_MODEL`: Text-to-speech model (default: "gpt-4o-mini-tts")
- `TTS_VOICE`: Voice selection (default: "alloy")
- `TTS_FORMAT`: Audio format (default: "mp3")

---

## Workflow

### Customer Ride Booking Workflow

#### 1. **Session Initialization**
- User starts a conversation session
- Frontend generates a unique `session_id`
- Backend creates a new LangChain memory instance for the session
- System prompt is injected: "You are LumiDrive, a ride-booking assistant."

#### 2. **Location Collection**
- User provides pickup and dropoff locations (text or voice)
- Assistant uses `set_trip_core` tool to store:
  - Pickup coordinates (lat/lng) and address
  - Dropoff coordinates (lat/lng) and address
  - Optional: Ride type name (e.g., "LUMI_GO", "Courier")
- Local gazetteer lookup for common place names (e.g., "Gaddafi Stadium", "Johar Town")

#### 3. **Additional Information Gathering**
- **Stops**: User can add intermediate stops via `set_stops` tool
- **Ride Type**: If not provided, assistant asks and uses `list_ride_types` tool
- **Courier Fields** (if Courier ride type):
  - Sender/receiver phone numbers
  - Package size and types
  - Comments for courier
  - Collected via `set_courier_fields` tool

#### 4. **Fare Quote & Ride Request Creation**
- Assistant calls `create_request_and_poll` tool which:
  - **Step 1**: Calculates distance/duration using Haversine formula
  - **Step 2**: Calls `/api/v1/rides/fare/all` with:
    - `distanceKm`: Calculated route distance
    - `durationMin`: Estimated travel time
    - `isNightRide`, `waitingMinutes`, `isHourly` flags
  - **Step 3**: Presents fare quotes per ride type to user
  - **Step 4**: After user confirmation, creates ride request via `POST /api/v1/rides` with:
    - Pickup/dropoff coordinates and addresses
    - Ride type ID
    - Payment method (WALLET/CASH/CARD)
    - Scheduled ride options
    - Estimated time and distance
    - Courier fields (if applicable)
  - **Step 5**: Polls for bids on the created ride request

#### 5. **Bid Management**
- Assistant receives list of bids from drivers
- Bids include: driver name, price, ETA, bid ID
- User can:
  - Accept a bid by index: "accept bid 1"
  - Accept a bid by driver name: "accept bid from hasnat"
  - Wait for more bids: "wait for more bids" (triggers `wait_for_bids` tool)
  - Accept bid by UUID: Uses `accept_bid` tool directly

#### 6. **Ride Tracking & Management**
- **Track Ride**: `track_ride` tool fetches current ride status
- **Cancel Ride**: `cancel_ride` tool cancels an active ride
- State is maintained in server-side memory for the session

### API Endpoints

#### `/chat` (POST)
- **Purpose**: Main chat endpoint for conversational interaction
- **Request**: 
  - `session_id`: Unique session identifier
  - `user_message`: User's text input
  - `messages`: Optional full conversation history
- **Response**: Streaming text response (text/plain)
- **Flow**:
  1. Validates Bearer token from Authorization header
  2. Retrieves/creates session memory
  3. Adds user message to memory
  4. Converts memory to OpenAI message format
  5. Calls OpenAI with tools (function calling)
  6. Executes tool calls (ride booking operations)
  7. Streams final assistant response

#### `/stt` (POST)
- **Purpose**: Speech-to-text conversion
- **Request**: Multipart form data with audio file
- **Response**: JSON with transcribed text, language, duration, segments
- **Flow**:
  1. Receives audio file (Blob/File)
  2. Sends to OpenAI transcription API
  3. Returns transcript with metadata

#### `/tts` (POST)
- **Purpose**: Text-to-speech conversion
- **Request**: JSON with text, voice, audio_format
- **Response**: Audio file (mp3/wav/etc.)
- **Flow**:
  1. Receives text to synthesize
  2. Calls OpenAI TTS API
  3. Returns audio bytes for playback

### Tool Functions (Function Calling)

The assistant uses the following tools (functions) that can be called by the AI:

1. **`set_trip_core`**: Store pickup/dropoff locations and addresses
2. **`set_stops`**: Add intermediate stops to the route
3. **`set_courier_fields`**: Set courier-specific information
4. **`list_ride_types`**: Fetch available ride types from backend
5. **`create_request_and_poll`**: Get fare quote, create ride request, poll for bids
6. **`wait_for_bids`**: Re-poll for bids on existing ride request
7. **`accept_bid_choice`**: Accept bid by index or driver name
8. **`accept_bid`**: Accept bid by UUID
9. **`track_ride`**: Get current ride status
10. **`cancel_ride`**: Cancel an active ride

---

## Phase 1: Completion Status

### ✅ Completed Features

1. **Ride Booking Workflow**
   - ✅ Location collection (pickup/dropoff)
   - ✅ Stops support
   - ✅ Ride type selection
   - ✅ Courier field collection
   - ✅ Fare quote calculation and presentation
   - ✅ Ride request creation
   - ✅ Bid polling and display
   - ✅ Bid acceptance (by index, name, or UUID)
   - ✅ Ride tracking
   - ✅ Ride cancellation

2. **Backend Infrastructure**
   - ✅ FastAPI server with CORS support
   - ✅ OpenAI integration (chat, STT, TTS)
   - ✅ LangChain memory management
   - ✅ Session-based conversation persistence
   - ✅ Function calling/tool execution
   - ✅ Streaming responses
   - ✅ Authentication via Bearer tokens

3. **Frontend Integration**
   - ✅ React Native chat interface
   - ✅ API client for assistant endpoints
   - ✅ Redux token management
   - ✅ Streaming response handling
   - ✅ Voice input/output support (STT/TTS)

4. **Backend API Integration**
   - ✅ Ride types listing
   - ✅ Fare calculation
   - ✅ Ride request creation
   - ✅ Bid management
   - ✅ Ride tracking
   - ✅ Ride cancellation

### Current State
The **ride booking workflow is fully functional** and has been tested. Customers can:
- Book rides through natural language conversation
- Get fare quotes
- Create ride requests
- View and accept driver bids
- Track and cancel rides

---

## Phase 2: Planned Work

### 1. Admin Side Assistant
- **Objective**: Build an AI assistant for admin/operator use cases
- **Features**:
  - Driver management queries
  - Ride analytics and reporting
  - Customer support automation
  - Dispute resolution assistance
  - Fleet management operations
- **Status**: Not started

### 2. Customer Side Assistant - State Management Improvements
- **Objective**: Enhance state management and session handling
- **Planned Improvements**:
  - Persistent state across app restarts
  - Better error handling and recovery
  - State synchronization between frontend and backend
  - Improved session management (timeout, cleanup)
  - State persistence in database (optional)
- **Status**: Not started

### 3. Integration with Manual Workflow
- **Objective**: Seamlessly integrate AI assistant with existing manual booking workflow
- **Planned Features**:
  - Allow users to switch between AI and manual booking
  - Sync state between AI and manual flows
  - Unified ride history and tracking
  - Consistent UI/UX across both workflows
  - Fallback mechanisms when AI is unavailable
- **Status**: Not started

### 4. Phase 1 Workflow Testing
- **Objective**: Comprehensive testing of the completed ride booking workflow
- **Testing Areas**:
  - Unit tests for tool functions
  - Integration tests for API endpoints
  - End-to-end tests for complete booking flow
  - Voice input/output testing
  - Error handling and edge cases
  - Performance testing (concurrent sessions)
  - Load testing
  - Security testing (authentication, input validation)
- **Status**: Not started

### Phase 2 Timeline
- **Admin Side Assistant**: TBD
- **State Management**: TBD
- **Manual Workflow Integration**: TBD
- **Testing**: TBD

---

## Environment Configuration

### Required Environment Variables

#### Backend (.env)
```bash
# OpenAI Configuration
OPENAI_API_KEY=your_openai_api_key
MODEL=gpt-4o-mini
STT_MODEL=gpt-4o-mini-transcribe
TTS_MODEL=gpt-4o-mini-tts
TTS_VOICE=alloy
TTS_FORMAT=mp3

# Backend API Configuration
BASE_URL=https://your-backend-api.com
TOKEN=optional_default_token

# API Endpoints
RIDE_TYPES_PATH=/api/v1/rides/ride-types
CREATE_REQUEST_PATH=/api/v1/rides
BIDS_FOR_REQUEST_PATH=/api/v1/rides/ride-request/{id}/bids
BID_ACCEPT_PATH=/api/v1/rides/bid/{id}/accept
CUSTOMER_RIDE_PATH=/api/v1/rides/ride-details/{rideId}
CANCEL_AS_CUSTOMER_PATH=/api/v1/rides/{id}/cancel
FARE_PATH=/api/v1/rides/fare/all

# Auth Endpoints
PHONE_CHECK_PATH=/api/v1/auth/phone/check/{phone}
SIGNUP_FIRST_PATH=/api/v1/auth/signup/first-step
SIGNUP_FINAL_PATH=/api/v1/auth/signup/final-step

# Default Settings
DEFAULT_PAYMENT_VIA=WALLET
DEFAULT_IS_HOURLY=false
FARE_AVG_SPEED_KMH=22
FARE_WAITING_MINUTES=0
FARE_IS_NIGHT=false
```

#### Frontend
- Assistant API base URL configured in `assistantChatApi.ts`
- Production: `https://lumidriveai-production.up.railway.app`
- Development: `http://localhost:8000`

---

## Deployment

### Backend
- **Platform**: Railway (production)
- **Server**: Uvicorn ASGI server
- **URL**: `https://lumidriveai-production.up.railway.app`

### Frontend
- **Platform**: React Native/Expo
- **Build**: EAS Build for iOS/Android
- **Distribution**: App stores (via EAS Submit)

---

## Notes

- The assistant uses a local gazetteer for quick place name resolution (Gaddafi Stadium, Johar Town, Lahore)
- State is maintained in-memory per session (not persisted to database)
- Authentication is handled via Bearer tokens from the frontend Redux store
- The system supports both text and voice interactions
- Streaming responses provide real-time feedback to users
- Function calling allows the AI to execute structured operations safely

---

## Future Considerations

- Database persistence for conversation history
- Multi-language support
- Advanced analytics and reporting
- Integration with payment systems
- Push notifications for ride updates
- Real-time location tracking
- Driver-side assistant features

