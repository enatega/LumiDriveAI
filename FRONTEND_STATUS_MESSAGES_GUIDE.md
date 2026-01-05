# Frontend Team: Status Messages Implementation Guide

## Quick Summary

During booking operations (which can take 30-60 seconds), the backend will now send status messages in the stream. Instead of just showing loading dots, you can display user-friendly messages like:

- "Resolving pickup and dropoff locations..."
- "Calculating fare..."
- "Creating your ride request..."
- "Searching for available drivers..." (this is the longest step)
- "Accepting the best offer..."
- "Ride booked successfully!"

## What Changed?

### Before
- Stream only contained text content
- Frontend showed generic loading dots
- No indication of what's happening

### After
- Stream contains JSON messages with `type` and content
- Frontend can parse and display specific status messages
- Users see what's happening in real-time

## Response Format

The stream now contains JSON objects, one per line:

```json
{"type": "status", "message": "Searching for available drivers..."}
{"type": "content", "text": "Your ride has been booked successfully!"}
```

### Message Types

1. **`status`**: Status update message (show in badge/notification)
   ```json
   {"type": "status", "message": "Please wait, your ride is being booked..."}
   ```

2. **`content`**: Normal chat content (append to chat)
   ```json
   {"type": "content", "text": "Your ride has been booked successfully!"}
   ```

## Implementation Example

### JavaScript/TypeScript

```typescript
interface StreamMessage {
  type: 'status' | 'content';
  message?: string;  // For status type
  text?: string;     // For content type
}

async function handleChatStream(response: Response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let currentStatus: string | null = null;
  let currentContent = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || ''; // Keep incomplete line

    for (const line of lines) {
      if (!line.trim()) continue;

      try {
        const data: StreamMessage = JSON.parse(line);

        if (data.type === 'status') {
          // Update status badge
          currentStatus = data.message || null;
          updateStatusBadge(currentStatus);
        } else if (data.type === 'content') {
          // Append to chat, clear status
          currentContent += data.text || '';
          currentStatus = null;
          updateStatusBadge(null);
          appendToChat(data.text || '');
        }
      } catch (e) {
        // Fallback: treat as plain text (backward compatibility)
        currentContent += line;
        appendToChat(line);
      }
    }
  }

  // Final update
  if (currentStatus) {
    updateStatusBadge(null);
  }
}

function updateStatusBadge(message: string | null) {
  const badge = document.getElementById('status-badge');
  if (badge) {
    if (message) {
      badge.textContent = message;
      badge.style.display = 'block';
    } else {
      badge.style.display = 'none';
    }
  }
}

function appendToChat(text: string) {
  const chatContainer = document.getElementById('chat-messages');
  if (chatContainer) {
    chatContainer.textContent += text;
  }
}
```

### React Hook

```typescript
import { useState, useCallback } from 'react';

interface ChatStreamState {
  status: string | null;
  content: string;
  isStreaming: boolean;
}

export function useChatStream() {
  const [state, setState] = useState<ChatStreamState>({
    status: null,
    content: '',
    isStreaming: false,
  });

  const sendMessage = useCallback(async (message: string, sessionId: string) => {
    setState({ status: null, content: '', isStreaming: true });

    const response = await fetch('/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({
        session_id: sessionId,
        user_message: message,
      }),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        setState(prev => ({ ...prev, isStreaming: false }));
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
            setState(prev => ({
              ...prev,
              status: data.message || null,
            }));
          } else if (data.type === 'content') {
            setState(prev => ({
              ...prev,
              content: prev.content + (data.text || ''),
              status: null, // Clear status when content arrives
            }));
          }
        } catch (e) {
          // Fallback for non-JSON
          setState(prev => ({
            ...prev,
            content: prev.content + line,
          }));
        }
      }
    }
  }, []);

  return { ...state, sendMessage };
}
```

### React Component Example

```tsx
function ChatComponent() {
  const { status, content, isStreaming, sendMessage } = useChatStream();

  return (
    <div className="chat-container">
      <div className="chat-messages">
        {content && (
          <div className="message bot-message">{content}</div>
        )}
      </div>

      {/* Status Badge */}
      {status && (
        <div className="status-badge" role="status" aria-live="polite">
          <span className="spinner"></span>
          {status}
        </div>
      )}

      {/* Fallback loading */}
      {isStreaming && !status && (
        <div className="loading-dots">Processing...</div>
      )}
    </div>
  );
}
```

### React Native Example

```typescript
import { useState } from 'react';
import { View, Text, ActivityIndicator } from 'react-native';

function ChatScreen() {
  const [status, setStatus] = useState<string | null>(null);
  const [content, setContent] = useState('');

  const handleStream = async (response: Response) => {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

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

          if (data.type === 'status') {
            setStatus(data.message || null);
          } else if (data.type === 'content') {
            setContent(prev => prev + (data.text || ''));
            setStatus(null);
          }
        } catch (e) {
          setContent(prev => prev + line);
        }
      }
    }
  };

  return (
    <View>
      <Text>{content}</Text>
      {status && (
        <View style={styles.statusContainer}>
          <ActivityIndicator />
          <Text>{status}</Text>
        </View>
      )}
    </View>
  );
}
```

## UI/UX Recommendations

### Status Badge Design

1. **Position**: Bottom of chat area, non-intrusive
2. **Style**: Small badge with spinner/loading indicator
3. **Animation**: Subtle fade in/out
4. **Auto-dismiss**: When content arrives, status clears
5. **Manual dismiss**: Optional close button

### Example CSS

```css
.status-badge {
  position: fixed;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.8);
  color: white;
  padding: 12px 20px;
  border-radius: 24px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  z-index: 1000;
  animation: fadeIn 0.3s ease-in;
}

.status-badge .spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateX(-50%) translateY(10px); }
  to { opacity: 1; transform: translateX(-50%) translateY(0); }
}
```

## Status Messages List

Here are all possible status messages you might receive:

1. `"Resolving pickup and dropoff locations..."`
2. `"Calculating fare..."`
3. `"Creating your ride request..."`
4. `"Searching for available drivers..."` (can take 30-60 seconds)
5. `"Accepting the best offer..."`
6. `"Ride booked successfully!"`

## Backward Compatibility

The implementation is backward compatible:
- If a line is not valid JSON, treat it as plain text content
- Old responses (without status messages) will still work
- Status messages are optional - if none are sent, show default loading

## Testing Checklist

- [ ] Status messages appear during booking
- [ ] Status clears when content arrives
- [ ] Works with non-JSON responses (backward compatibility)
- [ ] Handles network errors gracefully
- [ ] Status updates smoothly (no flickering)
- [ ] Works on mobile and desktop
- [ ] Accessibility (screen readers announce status)

## Questions?

If you have questions about:
- Implementation details
- UI/UX design
- Error handling
- Performance concerns

Please reach out to the backend team.

## Timeline

**Backend Team:**
- Week 1: Implement status callback mechanism
- Week 2: Add status messages to booking flow
- Week 3: Testing and refinement

**Frontend Team:**
- Week 2: Start implementing parser
- Week 3: UI components and styling
- Week 4: Testing and integration

