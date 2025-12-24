# Frontend Chat Storage Guide

This document outlines various approaches to persist chat messages on the frontend so that chat history remains available even when the backend session expires.

## Current Architecture

- **Backend**: Uses `session_id` to manage chat sessions
- **Backend Storage**: In-memory only (`_MEMORIES` dictionary) - lost on server restart or session expiration
- **Frontend**: Can send full `messages` array in `/chat` request
- **Bootstrap**: Backend can restore chat history from `body.messages` using `bootstrap_memory_from_messages()`

## Storage Options

### 1. **localStorage** (Recommended for Simple Cases)

**Pros:**
- Simple to implement
- Persists across browser sessions
- No size limits (typically 5-10MB)
- Synchronous API
- Works offline

**Cons:**
- Only available in browser (not native mobile apps)
- Shared across all tabs
- Can be cleared by user
- Synchronous operations can block UI

**Implementation:**

```javascript
// Save chat messages
function saveChatToLocalStorage(sessionId, messages) {
  const key = `lumidrive_chat_${sessionId}`;
  localStorage.setItem(key, JSON.stringify({
    messages: messages,
    lastUpdated: Date.now()
  }));
}

// Load chat messages
function loadChatFromLocalStorage(sessionId) {
  const key = `lumidrive_chat_${sessionId}`;
  const data = localStorage.getItem(key);
  if (data) {
    return JSON.parse(data).messages;
  }
  return [];
}

// Clear chat for a session
function clearChatFromLocalStorage(sessionId) {
  const key = `lumidrive_chat_${sessionId}`;
  localStorage.removeItem(key);
}

// Usage in React/React Native
useEffect(() => {
  // Load chat history on mount
  const savedMessages = loadChatFromLocalStorage(sessionId);
  if (savedMessages.length > 0) {
    setMessages(savedMessages);
  }
}, [sessionId]);

useEffect(() => {
  // Save chat history whenever messages change
  if (messages.length > 0) {
    saveChatToLocalStorage(sessionId, messages);
  }
}, [messages, sessionId]);
```

**Storage Structure:**
```json
{
  "lumidrive_chat_user123": {
    "messages": [
      {"role": "user", "content": "Book a lumi go ride"},
      {"role": "assistant", "content": "I'll book a LUMI_GO ride..."}
    ],
    "lastUpdated": 1704067200000
  }
}
```

---

### 2. **AsyncStorage** (React Native / Mobile Apps)

**Pros:**
- Native mobile storage solution
- Asynchronous API (non-blocking)
- Persists across app restarts
- Works on iOS and Android

**Cons:**
- React Native specific (not for web)
- Size limits (~6MB on iOS, ~10MB on Android)
- Can be cleared by OS under storage pressure

**Implementation:**

```javascript
import AsyncStorage from '@react-native-async-storage/async-storage';

// Save chat messages
async function saveChatToAsyncStorage(sessionId, messages) {
  const key = `lumidrive_chat_${sessionId}`;
  try {
    await AsyncStorage.setItem(key, JSON.stringify({
      messages: messages,
      lastUpdated: Date.now()
    }));
  } catch (error) {
    console.error('Error saving chat:', error);
  }
}

// Load chat messages
async function loadChatFromAsyncStorage(sessionId) {
  const key = `lumidrive_chat_${sessionId}`;
  try {
    const data = await AsyncStorage.getItem(key);
    if (data) {
      return JSON.parse(data).messages;
    }
  } catch (error) {
    console.error('Error loading chat:', error);
  }
  return [];
}

// Clear chat for a session
async function clearChatFromAsyncStorage(sessionId) {
  const key = `lumidrive_chat_${sessionId}`;
  try {
    await AsyncStorage.removeItem(key);
  } catch (error) {
    console.error('Error clearing chat:', error);
  }
}

// Usage in React Native
useEffect(() => {
  const loadChat = async () => {
    const savedMessages = await loadChatFromAsyncStorage(sessionId);
    if (savedMessages.length > 0) {
      setMessages(savedMessages);
    }
  };
  loadChat();
}, [sessionId]);

useEffect(() => {
  if (messages.length > 0) {
    saveChatToAsyncStorage(sessionId, messages);
  }
}, [messages, sessionId]);
```

---

### 3. **IndexedDB** (Web - Advanced)

**Pros:**
- Large storage capacity (typically 50% of disk space)
- Asynchronous API
- Structured data storage
- Can store complex objects
- Better performance for large datasets

**Cons:**
- More complex API
- Browser support (not available in React Native)
- Requires more setup

**Implementation:**

```javascript
// Initialize IndexedDB
function initChatDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('LumiDriveChatDB', 1);
    
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
    
    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains('chats')) {
        const store = db.createObjectStore('chats', { keyPath: 'sessionId' });
        store.createIndex('lastUpdated', 'lastUpdated', { unique: false });
      }
    };
  });
}

// Save chat messages
async function saveChatToIndexedDB(sessionId, messages) {
  const db = await initChatDB();
  const transaction = db.transaction(['chats'], 'readwrite');
  const store = transaction.objectStore('chats');
  
  await store.put({
    sessionId: sessionId,
    messages: messages,
    lastUpdated: Date.now()
  });
}

// Load chat messages
async function loadChatFromIndexedDB(sessionId) {
  const db = await initChatDB();
  const transaction = db.transaction(['chats'], 'readonly');
  const store = transaction.objectStore('chats');
  
  const request = store.get(sessionId);
  return new Promise((resolve, reject) => {
    request.onsuccess = () => {
      const data = request.result;
      resolve(data ? data.messages : []);
    };
    request.onerror = () => reject(request.error);
  });
}

// Get all chat sessions
async function getAllChatSessions() {
  const db = await initChatDB();
  const transaction = db.transaction(['chats'], 'readonly');
  const store = transaction.objectStore('chats');
  const index = store.index('lastUpdated');
  
  return new Promise((resolve, reject) => {
    const request = index.getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
```

---

### 4. **SQLite** (React Native - Advanced)

**Pros:**
- Full SQL database on device
- Excellent for complex queries
- Reliable and performant
- Can store relationships between data

**Cons:**
- Requires additional library (`react-native-sqlite-storage` or `expo-sqlite`)
- More setup complexity
- Overkill for simple chat storage

**Implementation:**

```javascript
import * as SQLite from 'expo-sqlite';

const db = SQLite.openDatabase('lumidrive_chat.db');

// Initialize database
function initChatDB() {
  db.transaction(tx => {
    tx.executeSql(
      `CREATE TABLE IF NOT EXISTS chats (
        session_id TEXT PRIMARY KEY,
        messages TEXT NOT NULL,
        last_updated INTEGER NOT NULL
      );`
    );
  });
}

// Save chat messages
function saveChatToSQLite(sessionId, messages) {
  db.transaction(tx => {
    tx.executeSql(
      'INSERT OR REPLACE INTO chats (session_id, messages, last_updated) VALUES (?, ?, ?)',
      [sessionId, JSON.stringify(messages), Date.now()]
    );
  });
}

// Load chat messages
function loadChatFromSQLite(sessionId) {
  return new Promise((resolve, reject) => {
    db.transaction(tx => {
      tx.executeSql(
        'SELECT messages FROM chats WHERE session_id = ?',
        [sessionId],
        (_, { rows }) => {
          if (rows.length > 0) {
            resolve(JSON.parse(rows.item(0).messages));
          } else {
            resolve([]);
          }
        },
        (_, error) => reject(error)
      );
    });
  });
}
```

---

### 5. **Redux Persist** (State Management)

**Pros:**
- Integrates with Redux/Zustand state management
- Automatic persistence
- Can combine multiple storage backends
- Handles rehydration automatically

**Cons:**
- Requires Redux/Zustand setup
- Additional dependency
- May persist unnecessary state

**Implementation:**

```javascript
// Using Redux Persist
import { persistStore, persistReducer } from 'redux-persist';
import AsyncStorage from '@react-native-async-storage/async-storage'; // or localStorage

const persistConfig = {
  key: 'root',
  storage: AsyncStorage, // or localStorage
  whitelist: ['chat'], // only persist chat slice
};

const rootReducer = combineReducers({
  chat: chatReducer,
  // other reducers...
});

const persistedReducer = persistReducer(persistConfig, rootReducer);

// Using Zustand with persist
import create from 'zustand';
import { persist } from 'zustand/middleware';

const useChatStore = create(
  persist(
    (set) => ({
      messages: [],
      sessionId: null,
      addMessage: (message) => set((state) => ({
        messages: [...state.messages, message]
      })),
      setSessionId: (id) => set({ sessionId: id }),
      clearChat: () => set({ messages: [] }),
    }),
    {
      name: 'lumidrive-chat-storage',
      storage: AsyncStorage, // or localStorage
    }
  )
);
```

---

### 6. **MMKV** (React Native - High Performance)

**Pros:**
- Extremely fast (C++ implementation)
- Synchronous API
- Small bundle size
- Thread-safe
- Better performance than AsyncStorage

**Cons:**
- React Native only
- Requires native module
- Less common than AsyncStorage

**Implementation:**

```javascript
import { MMKV } from 'react-native-mmkv';

const storage = new MMKV({ id: 'lumidrive-chat' });

// Save chat messages
function saveChatToMMKV(sessionId, messages) {
  const key = `chat_${sessionId}`;
  storage.set(key, JSON.stringify({
    messages: messages,
    lastUpdated: Date.now()
  }));
}

// Load chat messages
function loadChatFromMMKV(sessionId) {
  const key = `chat_${sessionId}`;
  const data = storage.getString(key);
  if (data) {
    return JSON.parse(data).messages;
  }
  return [];
}
```

---

## Recommended Implementation Strategy

### For Web Applications:
1. **Primary**: Use `localStorage` for simplicity
2. **Advanced**: Use `IndexedDB` if you need to store large amounts of data or multiple chat sessions

### For Mobile Applications (React Native):
1. **Primary**: Use `AsyncStorage` (standard React Native solution)
2. **High Performance**: Use `MMKV` if performance is critical
3. **Complex Queries**: Use `SQLite` if you need advanced querying

### Hybrid Approach (Web + Mobile):
Create a storage abstraction layer:

```javascript
// storage.js
class ChatStorage {
  constructor() {
    // Detect platform and use appropriate storage
    if (typeof window !== 'undefined' && window.localStorage) {
      this.storage = new LocalStorageAdapter();
    } else if (typeof require !== 'undefined') {
      // React Native
      this.storage = new AsyncStorageAdapter();
    }
  }

  async save(sessionId, messages) {
    return this.storage.save(sessionId, messages);
  }

  async load(sessionId) {
    return this.storage.load(sessionId);
  }

  async clear(sessionId) {
    return this.storage.clear(sessionId);
  }
}

class LocalStorageAdapter {
  save(sessionId, messages) {
    localStorage.setItem(`chat_${sessionId}`, JSON.stringify(messages));
  }

  load(sessionId) {
    const data = localStorage.getItem(`chat_${sessionId}`);
    return data ? JSON.parse(data) : [];
  }

  clear(sessionId) {
    localStorage.removeItem(`chat_${sessionId}`);
  }
}

class AsyncStorageAdapter {
  async save(sessionId, messages) {
    await AsyncStorage.setItem(`chat_${sessionId}`, JSON.stringify(messages));
  }

  async load(sessionId) {
    const data = await AsyncStorage.getItem(`chat_${sessionId}`);
    return data ? JSON.parse(data) : [];
  }

  async clear(sessionId) {
    await AsyncStorage.removeItem(`chat_${sessionId}`);
  }
}

export const chatStorage = new ChatStorage();
```

---

## Integration with Backend

The backend already supports restoring chat history via `bootstrap_memory_from_messages()`. Here's how to use it:

```javascript
// When sending chat request, include full message history
async function sendChatMessage(userMessage, sessionId) {
  // Load saved messages from local storage
  const savedMessages = await chatStorage.load(sessionId);
  
  // Add new user message
  const updatedMessages = [
    ...savedMessages,
    { role: 'user', content: userMessage }
  ];
  
  // Send to backend with full message history
  const response = await fetch('/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body: JSON.stringify({
      session_id: sessionId,
      user_message: userMessage,
      messages: updatedMessages // Send full history
    })
  });
  
  const result = await response.json();
  
  // Save updated messages including assistant response
  const finalMessages = [
    ...updatedMessages,
    { role: 'assistant', content: result.message }
  ];
  await chatStorage.save(sessionId, finalMessages);
  
  return result;
}
```

---

## Best Practices

1. **Session Management**: Use a consistent `session_id` (e.g., user ID or device ID)
2. **Data Format**: Store messages in the same format as backend expects:
   ```javascript
   {
     role: 'user' | 'assistant' | 'system',
     content: string,
     name?: string,
     tool_call_id?: string
   }
   ```
3. **Error Handling**: Always wrap storage operations in try-catch
4. **Cleanup**: Implement cleanup for old chat sessions (e.g., older than 30 days)
5. **Encryption**: Consider encrypting sensitive chat data before storage
6. **Compression**: For large chat histories, consider compressing before storage
7. **Sync**: Optionally sync with backend when connection is restored

---

## Example: Complete React Hook

```javascript
import { useState, useEffect, useCallback } from 'react';
import { chatStorage } from './storage';

export function useChatStorage(sessionId) {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);

  // Load chat history on mount
  useEffect(() => {
    const loadChat = async () => {
      try {
        const savedMessages = await chatStorage.load(sessionId);
        if (savedMessages.length > 0) {
          setMessages(savedMessages);
        }
      } catch (error) {
        console.error('Error loading chat:', error);
      } finally {
        setLoading(false);
      }
    };
    
    if (sessionId) {
      loadChat();
    }
  }, [sessionId]);

  // Save messages whenever they change
  useEffect(() => {
    if (messages.length > 0 && sessionId) {
      chatStorage.save(sessionId, messages).catch(error => {
        console.error('Error saving chat:', error);
      });
    }
  }, [messages, sessionId]);

  const addMessage = useCallback((message) => {
    setMessages(prev => [...prev, message]);
  }, []);

  const clearChat = useCallback(async () => {
    setMessages([]);
    if (sessionId) {
      await chatStorage.clear(sessionId);
    }
  }, [sessionId]);

  return {
    messages,
    addMessage,
    clearChat,
    loading
  };
}
```

---

## Summary

| Storage Method | Platform | Complexity | Performance | Size Limit |
|---------------|----------|------------|-------------|------------|
| localStorage | Web | Low | Good | 5-10MB |
| AsyncStorage | React Native | Low | Good | 6-10MB |
| IndexedDB | Web | Medium | Excellent | ~50% disk |
| SQLite | React Native | High | Excellent | Large |
| MMKV | React Native | Low | Excellent | Large |
| Redux Persist | Both | Medium | Good | Depends on backend |

**Recommendation**: Start with `localStorage` (web) or `AsyncStorage` (React Native) for simplicity, then upgrade to more advanced solutions if needed.

