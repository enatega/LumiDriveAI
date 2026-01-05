# Status Messages Implementation Guide

## Overview
This guide explains how to implement user-friendly status messages during the booking process. Instead of just showing loading dots, the frontend will display informative messages like "Please wait, your ride is being booked" or "Searching for available drivers...".

## Architecture

### Current Flow
1. User sends message → `/chat` endpoint
2. Backend processes (may call `book_ride_with_details`)
3. Booking workflow executes:
   - Resolve locations
   - Set trip core
   - Get fare quote
   - Create ride request
   - Wait for bids (can take 30-60 seconds)
   - Accept best bid
4. Final response streamed back

### Proposed Solution
Add status messages to the streaming response during long-running operations.

## Backend Implementation

### Option 1: JSON Status Messages in Stream (Recommended)

Modify the streaming response to include JSON status messages alongside text content.

**Format:**
```json
{"type": "status", "message": "Please wait, your ride is being booked..."}
{"type": "content", "text": "Your ride has been booked successfully!"}
```

**Implementation Steps:**

1. **Create a status callback mechanism** in `assistant.py`:
```python
# Global status callback (can be set per request)
_status_callback = None

def set_status_callback(callback):
    """Set a callback function to send status updates"""
    global _status_callback
    _status_callback = callback

def send_status(message: str):
    """Send a status message via callback"""
    global _status_callback
    if _status_callback:
        _status_callback(message)
```

2. **Modify `book_ride_with_details`** to send status updates:
```python
async def tool_book_ride_with_details(...):
    from assistant import send_status
    
    send_status("Resolving pickup and dropoff locations...")
    # ... resolve locations ...
    
    send_status("Calculating fare...")
    # ... get fare ...
    
    send_status("Creating your ride request...")
    # ... create ride request ...
    
    send_status("Searching for available drivers...")
    # ... wait for bids ...
    
    send_status("Accepting the best offer...")
    # ... accept bid ...
    
    send_status("Ride booked successfully!")
    # ... return success ...
```

3. **Modify streaming response** in `server.py`:
```python
def token_stream():
    status_queue = []  # Queue for status messages
    
    # Set up status callback
    from assistant import set_status_callback
    def status_handler(message: str):
        status_queue.append(json.dumps({"type": "status", "message": message}) + "\n")
    set_status_callback(status_handler)
    
    try:
        # Yield status messages from queue
        while status_queue:
            yield status_queue.pop(0)
        
        # Stream normal content
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                cleaned_content = strip_asterisks(delta.content)
                # Yield as content type
                yield json.dumps({"type": "content", "text": cleaned_content}) + "\n"
    finally:
        set_status_callback(None)  # Clear callback
```

### Option 2: Separate SSE Endpoint (Alternative)

Create a separate Server-Sent Events (SSE) endpoint for status updates.

**Endpoint:** `GET /chat/status?session_id=xxx`

**Implementation:**
```python
@app.get("/chat/status")
async def status_stream(session_id: str):
    async def event_stream():
        # Subscribe to status updates for this session
        # Yield status messages as they come
        while True:
            status = await get_status_for_session(session_id)
            if status:
                yield f"data: {json.dumps(status)}\n\n"
            await asyncio.sleep(0.5)
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

## Frontend Implementation

### Option 1: Parse JSON Messages from Stream

**React/JavaScript Example:**
```javascript
async function sendMessage(message) {
  const response = await fetch('/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body: JSON.stringify({
      session_id: sessionId,
      user_message: message
    })
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || ''; // Keep incomplete line in buffer

    for (const line of lines) {
      if (!line.trim()) continue;
      
      try {
        const data = JSON.parse(line);
        
        if (data.type === 'status') {
          // Show status message badge
          showStatusMessage(data.message);
        } else if (data.type === 'content') {
          // Append to chat content
          appendToChat(data.text);
        }
      } catch (e) {
        // Handle non-JSON content (backward compatibility)
        appendToChat(line);
      }
    }
  }
}

function showStatusMessage(message) {
  // Create or update status badge
  const statusBadge = document.getElementById('status-badge') || 
    createStatusBadge();
  statusBadge.textContent = message;
  statusBadge.style.display = 'block';
}

function appendToChat(text) {
  // Hide status badge when content arrives
  const statusBadge = document.getElementById('status-badge');
  if (statusBadge) statusBadge.style.display = 'none';
  
  // Append text to chat
  const chatContent = document.getElementById('chat-content');
  chatContent.textContent += text;
}
```

**React Hook Example:**
```javascript
import { useState, useEffect } from 'react';

function useChatStream(sessionId) {
  const [status, setStatus] = useState(null);
  const [content, setContent] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);

  const sendMessage = async (message) => {
    setIsStreaming(true);
    setStatus(null);
    setContent('');

    const response = await fetch('/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        session_id: sessionId,
        user_message: message
      })
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        setIsStreaming(false);
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.trim()) continue;
        
        try {
          const data = JSON.parse(line);
          
          if (data.type === 'status') {
            setStatus(data.message);
          } else if (data.type === 'content') {
            setContent(prev => prev + data.text);
            setStatus(null); // Clear status when content arrives
          }
        } catch (e) {
          // Fallback for non-JSON
          setContent(prev => prev + line);
        }
      }
    }
  };

  return { sendMessage, status, content, isStreaming };
}

// Usage in component
function ChatComponent() {
  const { sendMessage, status, content, isStreaming } = useChatStream(sessionId);

  return (
    <div>
      <div className="chat-messages">
        {content && <div>{content}</div>}
      </div>
      {status && (
        <div className="status-badge">
          <span className="loading-dots"></span>
          {status}
        </div>
      )}
      {isStreaming && !status && (
        <div className="loading-dots">Processing...</div>
      )}
    </div>
  );
}
```

### Option 2: SSE Status Stream (Alternative)

```javascript
function subscribeToStatus(sessionId) {
  const eventSource = new EventSource(`/chat/status?session_id=${sessionId}`);
  
  eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    showStatusMessage(data.message);
  };
  
  eventSource.onerror = () => {
    eventSource.close();
  };
  
  return () => eventSource.close();
}
```

## Status Messages List

Here are the recommended status messages for each stage:

1. **Location Resolution**: "Resolving pickup and dropoff locations..."
2. **Fare Calculation**: "Calculating fare..."
3. **Ride Creation**: "Creating your ride request..."
4. **Bid Search**: "Searching for available drivers..." (this can take 30-60 seconds)
5. **Bid Acceptance**: "Accepting the best offer..."
6. **Success**: "Ride booked successfully!" (then show final message)

## UI/UX Recommendations

1. **Status Badge Design:**
   - Small, non-intrusive badge at the bottom of chat
   - Animated loading dots or spinner
   - Auto-dismisses when content arrives
   - Can be manually dismissed by user

2. **Visual Design:**
   ```
   ┌─────────────────────────────┐
   │ Chat Messages               │
   │                             │
   │ User: Book a ride           │
   │ Bot: [streaming response]   │
   │                             │
   └─────────────────────────────┘
   ┌─────────────────────────────┐
   │ 🔄 Searching for available  │
   │    drivers...                │
   └─────────────────────────────┘
   ```

3. **Accessibility:**
   - Announce status changes to screen readers
   - Use ARIA live regions
   - Provide clear visual feedback

## Testing

1. **Test status messages appear during booking**
2. **Test status clears when content arrives**
3. **Test backward compatibility (non-JSON responses)**
4. **Test error handling (network errors, etc.)**

## Migration Plan

1. **Phase 1**: Backend adds status messages (backward compatible)
2. **Phase 2**: Frontend updates to parse and display status
3. **Phase 3**: Remove old loading dots, use status messages only

## Questions for Frontend Team

1. Do you prefer JSON in stream or separate SSE endpoint?
2. What UI component library are you using? (React Native, React, Vue, etc.)
3. Do you need i18n support for status messages?
4. Should status messages be dismissible by user?
5. What's your preferred animation style for loading indicators?

## Backend Team Tasks

- [ ] Implement status callback mechanism
- [ ] Add status messages to `book_ride_with_details`
- [ ] Modify streaming response to include status JSON
- [ ] Test status messages appear correctly
- [ ] Document status message format
- [ ] Ensure backward compatibility

## Frontend Team Tasks

- [ ] Update stream parser to handle JSON messages
- [ ] Create status badge component
- [ ] Implement status message display logic
- [ ] Add loading animations
- [ ] Test with real booking flow
- [ ] Handle edge cases (errors, timeouts, etc.)

