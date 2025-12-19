# Current Location Integration Guide

This guide outlines different approaches to pass the user's current location from the mobile app to the assistant, enabling automatic pickup location detection when only dropoff is provided.

## Overview

When a user provides only a dropoff location (e.g., "Take me to F-6 Markaz"), the assistant should automatically use the user's current location as the pickup location.

---

## Approach 1: Add `current_location` to ChatRequest (Recommended)

**Pros:**
- Clean separation of concerns
- Easy to access in the endpoint
- Can be stored per session
- Doesn't pollute message history

**Cons:**
- Requires updating the API contract

### Implementation Steps:

#### 1. Update Backend API (`server.py`)

```python
from pydantic import BaseModel
from typing import Optional

class LocationData(BaseModel):
    lat: float
    lng: float
    address: Optional[str] = None  # Optional: reverse geocoded address

class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    user_message: Optional[str] = None
    messages: Optional[List[ChatMessage]] = None
    current_location: Optional[LocationData] = None  # NEW FIELD
```

#### 2. Store Location in Session Memory (`server.py`)

```python
@app.post("/chat")
async def chat_endpoint(
    request: Request,
    body: ChatRequest,
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
):
    # ... existing code ...
    
    memory = get_memory(body.session_id)
    
    # Store current location in memory if provided
    if body.current_location:
        # Store in a custom attribute or use memory's metadata
        memory.current_location = {
            "lat": body.current_location.lat,
            "lng": body.current_location.lng,
            "address": body.current_location.address,
        }
        logger.info(f"[{request_id}] Current location: {body.current_location.lat}, {body.current_location.lng}")
```

#### 3. Update Memory Store (`memory_store.py`)

```python
from langchain.memory import ConversationBufferMemory
from typing import Dict, Optional

class EnhancedMemory(ConversationBufferMemory):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_location: Optional[Dict] = None

_MEMORIES: Dict[str, EnhancedMemory] = {}

def get_memory(session_id: str) -> EnhancedMemory:
    memory = _MEMORIES.get(session_id)
    if not memory:
        memory = EnhancedMemory(return_messages=True)
        _MEMORIES[session_id] = memory
    return memory
```

#### 4. Inject Location Context into System Prompt (`server.py`)

```python
# In chat_endpoint, before calling OpenAI:
memory = get_memory(body.session_id)

# Build system prompt with location context
system_prompt = SYSTEM
if memory.current_location:
    loc = memory.current_location
    system_prompt += f"\n\nUSER'S CURRENT LOCATION: {loc.get('address', 'Unknown')} ({loc['lat']}, {loc['lng']}). If the user provides only a dropoff location, use this as the pickup location automatically."
```

#### 5. Update Assistant System Prompt (`assistant.py`)

Add to the SYSTEM prompt:

```python
SYSTEM = """...
- **CURRENT LOCATION**: If the user's current location is available, it will be provided in the context. When a user provides only a dropoff location (e.g., "Take me to F-6 Markaz"), automatically use their current location as the pickup location. You don't need to ask for pickup - just use the current location and proceed with booking.
...
"""
```

#### 6. Frontend Implementation (React Native/TypeScript)

```typescript
// In your chat API service file
import * as Location from 'expo-location';

interface LocationData {
  lat: number;
  lng: number;
  address?: string;
}

interface ChatRequest {
  session_id: string;
  user_message?: string;
  messages?: Array<ChatMessage>;
  current_location?: LocationData;  // NEW FIELD
}

async function sendChatMessage(
  sessionId: string,
  message: string,
  messages: ChatMessage[]
): Promise<Response> {
  // Get current location
  let currentLocation: LocationData | undefined;
  
  try {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status === 'granted') {
      const location = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });
      
      // Optional: Reverse geocode to get address
      const reverseGeocode = await Location.reverseGeocodeAsync({
        latitude: location.coords.latitude,
        longitude: location.coords.longitude,
      });
      
      currentLocation = {
        lat: location.coords.latitude,
        lng: location.coords.longitude,
        address: reverseGeocode[0]?.formattedAddress,
      };
    }
  } catch (error) {
    console.warn('Failed to get location:', error);
    // Continue without location
  }
  
  // Send request with location
  return fetch(`${ASSISTANT_API_URL}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify({
      session_id: sessionId,
      user_message: message,
      messages: messages,
      current_location: currentLocation,  // Include location
    }),
  });
}
```

---

## Approach 2: Pass Location via Custom Headers

**Pros:**
- No API contract changes
- Simple to implement
- Can be added incrementally

**Cons:**
- Less semantic (headers are for HTTP metadata)
- Harder to track in logs
- Not part of request body

### Implementation:

#### Backend (`server.py`)

```python
@app.post("/chat")
async def chat_endpoint(
    request: Request,
    body: ChatRequest,
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
    x_current_lat: Optional[str] = Header(default=None),
    x_current_lng: Optional[str] = Header(default=None),
):
    # Parse location from headers
    current_location = None
    if x_current_lat and x_current_lng:
        try:
            current_location = {
                "lat": float(x_current_lat),
                "lng": float(x_current_lng),
            }
            memory = get_memory(body.session_id)
            memory.current_location = current_location
        except ValueError:
            logger.warning("Invalid location headers")
```

#### Frontend

```typescript
fetch(`${ASSISTANT_API_URL}/chat`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`,
    'X-Current-Lat': location?.lat?.toString(),
    'X-Current-Lng': location?.lng?.toString(),
  },
  body: JSON.stringify({ session_id, user_message, messages }),
});
```

---

## Approach 3: Inject Location into User Message Metadata

**Pros:**
- Location travels with the message
- Can be tracked per message
- Natural fit for message-based systems

**Cons:**
- Pollutes message history
- Requires updating ChatMessage model

### Implementation:

#### Backend (`server.py`)

```python
class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    location: Optional[LocationData] = None  # NEW FIELD
```

Then extract location from the last user message:

```python
def _extract_location_from_messages(messages: List[ChatMessage]) -> Optional[Dict]:
    for msg in reversed(messages):
        if msg.role == "user" and msg.location:
            return {
                "lat": msg.location.lat,
                "lng": msg.location.lng,
                "address": msg.location.address,
            }
    return None
```

---

## Approach 4: Use System Message Injection

**Pros:**
- No API changes needed
- Location is part of conversation context
- AI can naturally understand it

**Cons:**
- Location appears in every message
- Can clutter conversation history

### Implementation:

#### Backend (`server.py`)

```python
# In chat_endpoint, before calling OpenAI:
messages = memory_to_openai_messages(memory, SYSTEM)

# Inject location as system message if available
if body.current_location:
    location_msg = {
        "role": "system",
        "content": f"User's current location: {body.current_location.address or 'Unknown'} ({body.current_location.lat}, {body.current_location.lng}). Use this as pickup when only dropoff is provided."
    }
    messages.insert(1, location_msg)  # Insert after main system prompt
```

---

## Approach 5: Fetch Location from Backend API (Recommended for Production)

**Pros:**
- ✅ Single source of truth (backend manages location)
- ✅ More secure (location stored server-side, not sent in requests)
- ✅ Can track location history and updates
- ✅ Frontend doesn't need location permissions for every request
- ✅ Better for privacy/security compliance (GDPR, etc.)
- ✅ Can have background location updates
- ✅ Location can be updated independently of chat requests
- ✅ Reduces payload size of chat requests

**Cons:**
- ❌ Requires backend API changes
- ❌ Additional API call overhead
- ❌ Need to handle location refresh/update mechanisms
- ❌ May have stale location if not updated frequently
- ❌ Need to handle cases where location is unavailable

### Implementation Steps:

#### 1. Backend API Endpoint (Rides Backend)

The rides backend should expose an endpoint to get/update user's current location:

```python
# Example backend API endpoints:
GET  /api/v1/users/me/location          # Get current location
POST /api/v1/users/me/location          # Update current location
PUT  /api/v1/users/me/location          # Update current location
```

**Request (Update Location):**
```json
POST /api/v1/users/me/location
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "lat": 33.6844,
  "lng": 73.0479,
  "address": "F-6 Markaz, Islamabad",
  "accuracy": 10.5,  // Optional: GPS accuracy in meters
  "timestamp": "2025-01-17T10:30:00Z"  // Optional
}
```

**Response:**
```json
{
  "ok": true,
  "location": {
    "lat": 33.6844,
    "lng": 73.0479,
    "address": "F-6 Markaz, Islamabad",
    "updated_at": "2025-01-17T10:30:00Z"
  }
}
```

#### 2. Add Location Fetching to Assistant Backend (`api.py`)

```python
# Add to api.py

def get_user_current_location() -> dict:
    """
    Fetch user's current location from rides backend API.
    Uses the current TOKEN (set via set_token) for authentication.
    """
    url = f"{BASE_URL}/api/v1/users/me/location"
    headers = _auth_header()
    
    try:
        resp = session.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "ok": True,
                "location": data.get("location"),
            }
        elif resp.status_code == 404:
            return {
                "ok": False,
                "error": "Location not available",
            }
        else:
            return {
                "ok": False,
                "error": f"Failed to fetch location: {resp.status_code}",
            }
    except Exception as e:
        return {
            "ok": False,
            "error": f"Error fetching location: {str(e)}",
        }
```

#### 3. Fetch Location in Chat Endpoint (`server.py`)

```python
@app.post("/chat")
async def chat_endpoint(
    request: Request,
    body: ChatRequest,
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
):
    # ... existing code ...
    
    _set_backend_token(authorization)
    memory = get_memory(body.session_id)
    
    # Fetch current location from backend API
    from api import get_user_current_location
    location_result = get_user_current_location()
    
    if location_result.get("ok") and location_result.get("location"):
        location_data = location_result["location"]
        memory.current_location = {
            "lat": location_data.get("lat"),
            "lng": location_data.get("lng"),
            "address": location_data.get("address"),
            "updated_at": location_data.get("updated_at"),
        }
        logger.info(f"[{request_id}] Fetched current location: {location_data.get('address')}")
    else:
        logger.info(f"[{request_id}] Current location not available: {location_result.get('error')}")
        memory.current_location = None
    
    # Continue with chat processing...
```

#### 4. Update System Prompt with Location Context (`server.py`)

```python
# Build system prompt with location context
system_prompt = SYSTEM
if memory.current_location:
    loc = memory.current_location
    address = loc.get('address') or f"{loc['lat']}, {loc['lng']}"
    system_prompt += f"\n\nUSER'S CURRENT LOCATION: {address} (coordinates: {loc['lat']}, {loc['lng']}). If the user provides only a dropoff location, automatically use this current location as the pickup location. You don't need to ask for pickup - just proceed with booking using the current location."
```

#### 5. Frontend Implementation (React Native)

The frontend needs to update location periodically, not on every chat request:

```typescript
// Location service (separate from chat)
import * as Location from 'expo-location';
import { apiClient } from './api'; // Your API client

class LocationService {
  private updateInterval: NodeJS.Timeout | null = null;
  
  async startLocationUpdates(intervalMinutes: number = 5) {
    // Request permission
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== 'granted') {
      console.warn('Location permission denied');
      return;
    }
    
    // Update immediately
    await this.updateLocation();
    
    // Set up periodic updates
    this.updateInterval = setInterval(
      () => this.updateLocation(),
      intervalMinutes * 60 * 1000
    );
  }
  
  async updateLocation() {
    try {
      const location = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });
      
      // Reverse geocode for address
      const reverseGeocode = await Location.reverseGeocodeAsync({
        latitude: location.coords.latitude,
        longitude: location.coords.longitude,
      });
      
      // Send to backend API
      await apiClient.post('/api/v1/users/me/location', {
        lat: location.coords.latitude,
        lng: location.coords.longitude,
        address: reverseGeocode[0]?.formattedAddress,
        accuracy: location.coords.accuracy,
      });
      
      console.log('Location updated successfully');
    } catch (error) {
      console.error('Failed to update location:', error);
    }
  }
  
  stopLocationUpdates() {
    if (this.updateInterval) {
      clearInterval(this.updateInterval);
      this.updateInterval = null;
    }
  }
}

export const locationService = new LocationService();

// In your app initialization (e.g., App.tsx or main screen):
useEffect(() => {
  locationService.startLocationUpdates(5); // Update every 5 minutes
  
  return () => {
    locationService.stopLocationUpdates();
  };
}, []);
```

#### 6. Update Assistant Logic (`assistant.py`)

```python
async def tool_book_ride_with_details(
    pickup_place: str | None = None,  # Make optional
    dropoff_place: str,
    ride_type: str,
    stops=None,
    ...
):
    """
    If pickup_place is None, check if current_location is available in STATE.
    """
    # Check if pickup is missing and we have current location
    if not pickup_place:
        # Try to get from STATE (set by chat endpoint)
        current_loc = STATE.get("current_location")
        if current_loc:
            pickup_coords = current_loc
            pickup_place = pickup_coords.get("address") or f"{pickup_coords['lat']},{pickup_coords['lng']}"
            logger.info(f"Using current location as pickup: {pickup_place}")
        else:
            return {
                "ok": False,
                "error": "Pickup location is required. Please provide pickup location or ensure location services are enabled.",
            }
    
    # Continue with booking...
```

#### 7. Store Location in STATE (`assistant.py`)

Update the chat endpoint to store location in STATE:

```python
# In server.py chat_endpoint, after fetching location:
if memory.current_location:
    # Also store in STATE for tool access
    from assistant import STATE
    STATE["current_location"] = memory.current_location
```

### Architecture Flow:

```
┌─────────────┐
│  Mobile App │
│             │
│  1. Updates │
│  location   │
│  every 5min │
└──────┬──────┘
       │ POST /api/v1/users/me/location
       │ { lat, lng, address }
       ▼
┌─────────────────┐
│  Rides Backend  │
│                 │
│  Stores user    │
│  location       │
└──────┬──────────┘
       │
       │ GET /api/v1/users/me/location
       │ (with JWT token)
       ▼
┌─────────────────┐
│Assistant Backend│
│                 │
│  Fetches        │
│  location on    │
│  each chat      │
│  request        │
└─────────────────┘
```

### Comparison: Approach 1 vs Approach 5

| Aspect | Approach 1 (Send in Request) | Approach 5 (Backend API) |
|--------|------------------------------|--------------------------|
| **Security** | Location sent in every request | Location stored server-side |
| **Privacy** | Location in request logs | Better privacy compliance |
| **Payload Size** | Larger requests | Smaller requests |
| **Frontend Permissions** | Needed for every request | Needed only for updates |
| **Location Freshness** | Always current | May be stale (needs refresh) |
| **Backend Changes** | Minimal | Requires new endpoint |
| **Scalability** | Good | Better (centralized) |
| **Use Case** | MVP/Prototype | Production |

### Hybrid Approach (Best of Both Worlds)

You can combine both approaches:

1. **Frontend sends location** in chat request (Approach 1) as fallback
2. **Backend API** is primary source (Approach 5)
3. **Assistant backend** tries backend API first, falls back to request data

```python
# In server.py chat_endpoint:
# Try backend API first
location_result = get_user_current_location()

# Fallback to request data if API fails
if not location_result.get("ok") and body.current_location:
    memory.current_location = {
        "lat": body.current_location.lat,
        "lng": body.current_location.lng,
        "address": body.current_location.address,
    }
```

---

## Recommended Implementation Flow

### Step-by-Step:

1. **Choose Approach 1** (Add to ChatRequest) - It's the cleanest
2. **Update Backend Models** - Add `current_location` to `ChatRequest`
3. **Update Memory Store** - Store location per session
4. **Update System Prompt** - Tell AI to use current location automatically
5. **Update Frontend** - Get location and send with each request
6. **Handle Edge Cases**:
   - Location permission denied
   - Location unavailable
   - Stale location (older than X minutes)
   - Location accuracy issues

### Example: Complete Flow

```python
# In assistant.py, update book_ride_with_details logic:

async def tool_book_ride_with_details(
    pickup_place: str | None = None,  # Make optional
    dropoff_place: str,
    ride_type: str,
    stops=None,
    ...
):
    """
    If pickup_place is None, check if current_location is available in STATE.
    """
    # Check if pickup is missing and we have current location
    if not pickup_place and STATE.get("current_location"):
        pickup_coords = STATE["current_location"]
        pickup_place = pickup_coords.get("address") or f"{pickup_coords['lat']},{pickup_coords['lng']}"
        logger.info(f"Using current location as pickup: {pickup_place}")
    
    if not pickup_place:
        return {
            "ok": False,
            "error": "Pickup location is required. Please provide pickup location or enable location services.",
        }
    
    # Continue with booking...
```

---

## Frontend Location Best Practices

### 1. Request Permissions Gracefully

```typescript
async function requestLocationPermission(): Promise<boolean> {
  const { status: existingStatus } = await Location.getForegroundPermissionsAsync();
  if (existingStatus === 'granted') {
    return true;
  }
  
  const { status } = await Location.requestForegroundPermissionsAsync();
  return status === 'granted';
}
```

### 2. Cache Location (Optional)

```typescript
// Cache location for 5 minutes to avoid excessive requests
let cachedLocation: { data: LocationData; timestamp: number } | null = null;
const LOCATION_CACHE_TTL = 5 * 60 * 1000; // 5 minutes

async function getCurrentLocation(): Promise<LocationData | null> {
  // Check cache
  if (cachedLocation && Date.now() - cachedLocation.timestamp < LOCATION_CACHE_TTL) {
    return cachedLocation.data;
  }
  
  // Get fresh location
  const location = await Location.getCurrentPositionAsync({...});
  cachedLocation = {
    data: { lat: location.coords.latitude, lng: location.coords.longitude },
    timestamp: Date.now(),
  };
  
  return cachedLocation.data;
}
```

### 3. Handle Errors Gracefully

```typescript
try {
  const location = await getCurrentLocation();
  // Send with request
} catch (error) {
  // Continue without location - assistant will ask for pickup
  console.warn('Location unavailable:', error);
}
```

---

## Testing Checklist

- [ ] Location permission granted → Location sent
- [ ] Location permission denied → Request continues without location
- [ ] User provides only dropoff → Assistant uses current location as pickup
- [ ] User provides both pickup and dropoff → Current location ignored
- [ ] Location unavailable → Assistant asks for pickup location
- [ ] Stale location → Consider refreshing or asking user

---

## Next Steps

### For MVP/Prototype:
1. ✅ Implement **Approach 1** (Send in Request) - Quick to implement, no backend changes needed
2. Update the assistant system prompt to handle current location
3. Test with various scenarios

### For Production:
1. ✅ Implement **Approach 5** (Backend API) - **Recommended for production** - More secure, scalable, and privacy-compliant
2. Coordinate with backend team to build `/api/v1/users/me/location` endpoint
3. Set up location update service in frontend (periodic updates every 5-10 minutes)
4. Add location refresh mechanism
5. Add location accuracy indicators
6. Consider **Hybrid Approach** (combine Approach 1 + 5) for maximum reliability

### Recommendation:
- **Short-term/MVP**: Use Approach 1 for quick implementation
- **Long-term/Production**: Use Approach 5 (Backend API) - **This is the correct approach for production systems**
- **Best Practice**: Use Hybrid Approach (try backend API first, fallback to request data) for maximum reliability

