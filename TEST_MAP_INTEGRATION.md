# Testing Map Selection Integration

## Quick Start

1. **Open the test frontend**:
   ```bash
   # Serve the HTML file
   python3 -m http.server 8080
   # Then open: http://localhost:8080/test_frontend.html
   ```

2. **Enter your Google Maps API Key**:
   - In the "Google Maps API Key" input field
   - Get a key from [Google Cloud Console](https://console.cloud.google.com/)
   - Enable "Maps JavaScript API" and "Geocoding API" in your project

3. **Enter your JWT Token** and API URL

4. **Test the integration**:

## Testing Methods

### Method 1: Manual Test Button
- Click the **"🗺️ Test Map Selection"** button
- This will open the map modal directly
- Select pickup and dropoff locations
- Click "Done"
- Locations will be sent to the assistant

### Method 2: Through Chat
1. Type: **"I want to book a ride"** or **"Book a ride for me"**
2. The assistant should call `request_map_selection` tool
3. The map modal should automatically appear
4. Select locations and click "Done"
5. The assistant will proceed with booking

### Method 3: Direct Location Selection
1. Click "Test Map Selection" button
2. Select locations on map
3. Click "Done"
4. The locations will be sent as a message to the assistant
5. Assistant will process them and continue with booking

## Features

✅ **Interactive Map**: Click to select pickup and dropoff locations  
✅ **Visual Markers**: Green marker for pickup, red for dropoff  
✅ **Address Lookup**: Automatically gets addresses for selected coordinates  
✅ **Geolocation**: Tries to center map on your current location  
✅ **Validation**: Requires both locations before allowing "Done"  
✅ **Auto-detection**: Detects when assistant requests map selection  

## How It Works

1. **Map Detection**: The frontend checks assistant messages for map-related keywords
2. **Map Display**: When detected, shows a modal with Google Maps
3. **Location Selection**: User clicks on map to select pickup, then dropoff
4. **Address Resolution**: Uses Google Geocoding API to get addresses
5. **Submission**: Sends locations to assistant via chat message
6. **Processing**: Assistant receives locations and calls `set_trip_core` tool
7. **Booking**: Assistant proceeds with fare calculation and booking

## Troubleshooting

### Map doesn't appear
- Check that Google Maps API key is entered correctly
- Verify API key has "Maps JavaScript API" enabled
- Check browser console for errors
- Try reloading the page after entering API key

### "Please enter your Google Maps API key" error
- Enter your API key in the input field
- The key is saved to localStorage for convenience
- Reload page if needed

### Locations not being sent
- Check that both pickup and dropoff are selected
- Verify JWT token is valid
- Check browser console for API errors
- Ensure backend server is running

### Assistant doesn't detect map request
- The detection uses keyword matching
- Try saying: "I need to select locations on a map"
- Or use the manual "Test Map Selection" button

## Next Steps

For production frontend:
1. Replace keyword detection with actual tool call parsing
2. Store full conversation history with tool calls
3. Parse tool call results from server responses
4. Add place search/autocomplete to map
5. Add route preview between locations
6. Add ability to drag markers to adjust locations

---

**Last Updated**: November 2024

