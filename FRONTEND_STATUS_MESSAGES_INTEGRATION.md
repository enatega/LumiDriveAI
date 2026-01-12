# Frontend Status Messages Integration Guide

## Overview

The chat API now streams status messages during long-running operations (like booking a ride). These messages appear as temporary, disappearing chat bubbles that provide real-time feedback to users.

## Message Format

The API streams JSON objects with two types:

### Status Messages
```json
{"type": "status", "message": "Resolving pickup and dropoff locations..."}
```

### Content Messages
```json
{"type": "content", "text": "Perfect! I can book your ride..."}
```

## Expected Status Messages

During ride booking, you'll receive these status messages in sequence:

1. `"Resolving pickup and dropoff locations..."`
2. `"Calculating fare..."`
3. `"Creating your ride request..."`
4. `"Searching for available drivers..."` (this can take 30-60 seconds)

## Implementation Requirements

### 1. Parse JSON Stream

Parse each line of the stream as JSON:

```javascript
const reader = chatResponse.body.getReader();
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
            
            if (data.type === 'status' && data.message) {
                // Handle status message
                showStatusInChat(data.message);
            } else if (data.type === 'content' && data.text) {
                // Handle content message
                removeStatusFromChat(); // Remove status when content arrives
                appendContent(data.text);
            }
        } catch (e) {
            // Fallback: treat as plain text (backward compatibility)
            appendContent(line);
        }
    }
}
```

### 2. Display Status Messages

Status messages should:
- **Appear as temporary chat bubbles** (not in a separate badge/overlay)
- **Replace each other** - each new status message replaces the previous one
- **Show a spinner** - include a loading spinner animation
- **Disappear when content arrives** - remove status messages when the first content chunk arrives

#### Example Implementation:

```javascript
function showStatusInChat(message) {
    // Remove any existing status message
    const existingStatus = chatHistory.querySelector('.chat-message.assistant.status-temp');
    if (existingStatus) {
        existingStatus.remove();
    }
    
    // Create new status message
    const statusMsg = document.createElement('div');
    statusMsg.className = 'chat-message assistant status-temp';
    statusMsg.innerHTML = `
        <div class="role">Assistant</div>
        <div class="content">
            <span class="status-spinner"></span>
            ${escapeHtml(message)}
        </div>
    `;
    chatHistory.appendChild(statusMsg);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function removeStatusFromChat() {
    const statusMsg = chatHistory.querySelector('.chat-message.assistant.status-temp');
    if (statusMsg) {
        statusMsg.remove();
    }
}
```

### 3. CSS Styling

```css
/* Status message styling */
.chat-message.status-temp {
    opacity: 0.8;
    animation: fadeInOut 0.3s ease-in;
}

.chat-message.status-temp .status-spinner {
    display: inline-block;
    width: 12px;
    height: 12px;
    border: 2px solid rgba(102, 126, 234, 0.3);
    border-top-color: #667eea;
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin-right: 8px;
    vertical-align: middle;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

@keyframes fadeInOut {
    from { opacity: 0; transform: translateY(-5px); }
    to { opacity: 0.8; transform: translateY(0); }
}
```

## Behavior Flow

1. **User sends message** (e.g., "Book a ride")
2. **Status messages appear** sequentially:
   - "Resolving pickup and dropoff locations..." (replaces previous if any)
   - "Calculating fare..." (replaces previous)
   - "Creating your ride request..." (replaces previous)
   - "Searching for available drivers..." (replaces previous, can stay for 30-60 seconds)
3. **Content arrives** - status message disappears, actual response appears
4. **User sees final response** - normal chat message

## Important Notes

### ✅ DO:
- Parse each line as JSON
- Show status messages as temporary chat bubbles
- Replace status messages (don't stack them)
- Remove status messages when content arrives
- Include a spinner animation
- Handle both `status` and `content` message types

### ❌ DON'T:
- Show status messages in a separate badge/overlay outside the chat
- Keep status messages after content arrives
- Stack multiple status messages
- Show raw coordinates or internal data
- Block the UI while waiting for responses

## Edge Cases

1. **Empty or malformed JSON**: Fall back to treating as plain text
2. **Status message without content**: Remove status message when streaming completes
3. **Multiple rapid status messages**: Each new one replaces the previous
4. **Content arrives before status**: Remove status immediately when first content chunk arrives

## Example Complete Implementation

```javascript
async function sendMessage(text) {
    // Add user message to chat
    addUserMessage(text);
    
    // Start streaming response
    const response = await fetch('/chat', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
            session_id: sessionId,
            user_message: text
        })
    });
    
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let assistantText = '';
    let streamingMessage = null;
    
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        
        for (const line of lines) {
            if (!line.trim()) continue;
            
            try {
                const data = JSON.parse(line);
                
                if (data.type === 'status' && data.message) {
                    // Show status as temporary chat message
                    showStatusInChat(data.message);
                } else if (data.type === 'content' && data.text) {
                    // Remove status when content arrives
                    removeStatusFromChat();
                    
                    // Append content to streaming message
                    assistantText += data.text;
                    if (!streamingMessage) {
                        streamingMessage = createStreamingMessage();
                    }
                    updateStreamingMessage(assistantText);
                }
            } catch (e) {
                // Fallback: plain text
                assistantText += line;
                if (!streamingMessage) {
                    streamingMessage = createStreamingMessage();
                }
                updateStreamingMessage(assistantText);
            }
        }
    }
    
    // Finalize message
    if (streamingMessage) {
        finalizeStreamingMessage(streamingMessage);
    }
    removeStatusFromChat(); // Clean up any remaining status
}
```

## Testing

Test the integration by:
1. Booking a ride and verifying all status messages appear sequentially
2. Ensuring status messages disappear when content arrives
3. Checking that status messages replace each other (not stack)
4. Verifying the spinner animation works
5. Testing with slow network to see message transitions

## Questions?

If you have any questions about the integration, please refer to the working example in `test_frontend.html` or contact the backend team.

