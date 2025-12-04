# Google Maps Integration Guide

## Overview

The assistant now integrates Google Maps APIs for accurate distance/duration calculation and provides a map selection interface for users to pick pickup and dropoff locations visually.

## What Was Implemented

### 1. Google Maps Service Module (`google_maps.py`)

Created a comprehensive Google Maps service that wraps all the provided APIs:
- `fetchGoogleRoute()` - Get route path with waypoints
- `snapToRoad()` - Snap coordinates to nearest road
- `getDistanceMatrix()` - Calculate distance and duration
- `fetchPlaces()` - Place autocomplete
- `getPlaceDetails()` - Get coordinates from place ID
- `fetchAddressFromCoordinates()` - Reverse geocoding

**Key Function**: `calculate_distance_duration_google()` - Calculates accurate distance/duration using Google Distance Matrix API before fare API calls.

### 2. New Tool: `request_map_selection`

Added a new tool that the assistant can call to trigger map UI on the frontend:

```python
{
  "name": "request_map_selection",
  "description": "Request the user to select pickup and dropoff locations on a map...",
  "parameters": {
    "message": "Optional message to display to the user"
  }
}
```

**Tool Response**:
```json
{
  "ok": true,
  "action": "show_map",
  "message": "Please select your pickup and dropoff locations on the map, then press Done.",
  "requires_user_input": true
}
```

### 3. Updated Fare Calculation Flow

The `tool_create_request_and_poll` function now:
1. **First** calculates distance/duration using Google Maps Distance Matrix API (more accurate)
2. **Then** calls the fare API with the calculated values
3. Falls back to haversine calculation if Google Maps API fails or is not configured

### 4. Backend Changes

- `assistant.py`: Added `request_map_selection` tool and updated `create_request_and_poll` to use Google Maps
- `server.py`: Updated to handle async tool calls properly
- `requirements.txt`: Added `polyline==2.0.1` for route decoding

## Frontend Integration

### How It Works

1. **User says**: "I want to book a ride" or "Book a ride for me"
2. **Assistant calls**: `request_map_selection` tool
3. **Frontend detects**: Tool call with `action: "show_map"`
4. **Frontend shows**: Google Map interface for location selection
5. **User selects**: Pickup and dropoff on map, presses "Done"
6. **Frontend sends**: Selected locations to assistant via `set_trip_core` tool
7. **Assistant proceeds**: With booking flow using Google Maps calculated distance/duration

### Frontend Implementation Steps

#### Step 1: Detect Map Selection Tool Call

In your chat component, when processing tool calls from the assistant:

```typescript
// In assistantChatApi.ts or chat component
const processToolCalls = (toolCalls: any[]) => {
  for (const toolCall of toolCalls) {
    if (toolCall.function.name === 'request_map_selection') {
      const args = JSON.parse(toolCall.function.arguments || '{}');
      // Show map UI
      showMapSelection(args.message || 'Please select locations on the map');
      return { action: 'show_map', message: args.message };
    }
  }
};
```

#### Step 2: Show Map UI

When `request_map_selection` is detected, show a Google Map component:

```typescript
// Example React Native component
import MapView, { Marker } from 'react-native-maps';

const MapSelectionScreen = ({ onLocationsSelected }) => {
  const [pickup, setPickup] = useState(null);
  const [dropoff, setDropoff] = useState(null);
  const [mode, setMode] = useState<'pickup' | 'dropoff'>('pickup');

  const handleMapPress = (event) => {
    const { latitude, longitude } = event.nativeEvent.coordinate;
    if (mode === 'pickup') {
      setPickup({ lat: latitude, lng: longitude });
      setMode('dropoff');
    } else {
      setDropoff({ lat: latitude, lng: longitude });
    }
  };

  const handleDone = async () => {
    if (pickup && dropoff) {
      // Get addresses using reverse geocoding (optional)
      const pickupAddress = await getAddressFromCoordinates(pickup.lat, pickup.lng);
      const dropoffAddress = await getAddressFromCoordinates(dropoff.lat, dropoff.lng);
      
      // Send to assistant via set_trip_core
      await sendLocationToAssistant(pickup, dropoff, pickupAddress, dropoffAddress);
      onLocationsSelected();
    }
  };

  return (
    <View>
      <MapView onPress={handleMapPress}>
        {pickup && <Marker coordinate={pickup} title="Pickup" />}
        {dropoff && <Marker coordinate={dropoff} title="Dropoff" />}
      </MapView>
      <Button title="Done" onPress={handleDone} disabled={!pickup || !dropoff} />
    </View>
  );
};
```

#### Step 3: Send Locations to Assistant

After user selects locations and presses "Done", send them to the assistant:

```typescript
const sendLocationToAssistant = async (
  pickup: { lat: number; lng: number },
  dropoff: { lat: number; lng: number },
  pickupAddress: string,
  dropoffAddress: string
) => {
  // Option 1: Send as a user message that triggers set_trip_core
  const message = JSON.stringify({
    action: 'set_trip_core',
    pickup: { lat: pickup.lat, lng: pickup.lng, address: pickupAddress },
    dropoff: { lat: dropoff.lat, lng: dropoff.lng, address: dropoffAddress },
    pickup_address: pickupAddress,
    destination_address: dropoffAddress,
  });
  
  await assistantChatApi.sendChatMessage({
    session_id: sessionId,
    user_message: `I've selected locations: ${message}`,
  });

  // Option 2: Directly call set_trip_core tool (if you have direct tool calling)
  // This requires modifying the chat API to support tool calls
};
```

**Recommended Approach**: Send locations as a structured user message that the assistant will parse and use to call `set_trip_core`.

#### Step 4: Handle Tool Calls in Chat Stream

Update your chat component to detect and handle tool calls:

```typescript
// In your chat component
const handleChatResponse = async (response: Response) => {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    
    // Check for tool calls in the response
    // Note: Tool calls come in the first OpenAI response, not the stream
    // You'll need to check the initial response for tool_calls
  }
};

// When you get the initial OpenAI response (before streaming)
const initialResponse = await fetch('/chat', {...});
const data = await initialResponse.json(); // If not streaming

if (data.tool_calls) {
  for (const toolCall of data.tool_calls) {
    if (toolCall.function.name === 'request_map_selection') {
      // Show map UI
      setShowMap(true);
    }
  }
}
```

## Environment Setup

### Required Environment Variables

Add to your `.env` file:

```env
GOOGLE_API_KEY=your_google_maps_api_key_here
```

### Required Dependencies

```bash
pip install polyline==2.0.1
```

Already added to `requirements.txt`.

## API Flow Diagram

```
User: "Book a ride"
  ↓
Assistant calls: request_map_selection
  ↓
Frontend: Shows Google Map
  ↓
User: Selects pickup & dropoff, presses "Done"
  ↓
Frontend: Sends locations to assistant
  ↓
Assistant calls: set_trip_core (with locations)
  ↓
Assistant calls: create_request_and_poll
  ↓
Backend: calculate_distance_duration_google() → Google Distance Matrix API
  ↓
Backend: get_fare() → Fare API (with Google-calculated distance/duration)
  ↓
Backend: create_ride_request_exact() → Create ride
  ↓
Backend: wait_for_bids() → Poll for bids
  ↓
Assistant: Shows bids to user
```

## Testing

### Test Google Maps Integration

1. **Set API Key**: Add `GOOGLE_API_KEY` to `.env`
2. **Test Distance Calculation**:
   ```python
   from google_maps import calculate_distance_duration_google
   
   result = await calculate_distance_duration_google(
       {"lat": 31.5204, "lng": 74.3384},  # Gaddafi Stadium
       {"lat": 31.4676, "lng": 74.2728}   # Johar Town
   )
   print(result)  # Should show distanceKm and durationMin
   ```

3. **Test Map Selection Tool**:
   - Send message: "I want to book a ride"
   - Assistant should call `request_map_selection`
   - Frontend should show map
   - Select locations and verify they're sent to assistant

## Frontend Requirements

### For React Native (Expo)

1. **Install Maps Package**:
   ```bash
   npx expo install react-native-maps
   ```

2. **Add Google Maps API Key** (for native):
   - iOS: Add to `Info.plist`
   - Android: Add to `AndroidManifest.xml`

3. **For Web**: Use `@react-google-maps/api` or Google Maps JavaScript API

### For Web (HTML/JavaScript)

Use Google Maps JavaScript API:

```html
<script src="https://maps.googleapis.com/maps/api/js?key=YOUR_API_KEY&libraries=places"></script>
```

## Error Handling

- If `GOOGLE_API_KEY` is not set, the system falls back to haversine distance calculation
- If Google Maps API fails, it falls back to haversine
- All errors are logged and don't break the booking flow

## Next Steps

1. **Frontend Team**: Implement map selection UI that:
   - Detects `request_map_selection` tool calls
   - Shows Google Map for location selection
   - Sends selected locations back to assistant

2. **Testing**: Test the complete flow:
   - Map selection → Location sending → Fare calculation → Ride booking

3. **Enhancement**: Add place autocomplete/search to map UI using `fetchPlaces()` API

## Support

For issues:
- Check `GOOGLE_API_KEY` is set correctly
- Verify Google Maps API is enabled in Google Cloud Console
- Check backend logs for Google Maps API errors
- Ensure polyline package is installed

---

**Last Updated**: November 2024

