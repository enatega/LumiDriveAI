/**
 * Example Frontend Chat Storage Implementation
 * 
 * This file demonstrates how to persist chat messages on the frontend
 * so they survive session expiration on the backend.
 * 
 * Choose the appropriate storage method based on your platform:
 * - Web: localStorage
 * - React Native: AsyncStorage or MMKV
 */

// ============================================================================
// OPTION 1: localStorage (Web Browser)
// ============================================================================

class LocalStorageChatStorage {
  constructor(prefix = 'lumidrive_chat') {
    this.prefix = prefix;
  }

  /**
   * Save chat messages for a session
   * @param {string} sessionId - Unique session identifier
   * @param {Array} messages - Array of chat messages
   */
  save(sessionId, messages) {
    try {
      const key = `${this.prefix}_${sessionId}`;
      const data = {
        messages: messages,
        lastUpdated: Date.now(),
        sessionId: sessionId
      };
      localStorage.setItem(key, JSON.stringify(data));
      return true;
    } catch (error) {
      console.error('Error saving chat to localStorage:', error);
      return false;
    }
  }

  /**
   * Load chat messages for a session
   * @param {string} sessionId - Unique session identifier
   * @returns {Array} Array of chat messages
   */
  load(sessionId) {
    try {
      const key = `${this.prefix}_${sessionId}`;
      const data = localStorage.getItem(key);
      if (data) {
        const parsed = JSON.parse(data);
        return parsed.messages || [];
      }
      return [];
    } catch (error) {
      console.error('Error loading chat from localStorage:', error);
      return [];
    }
  }

  /**
   * Clear chat messages for a session
   * @param {string} sessionId - Unique session identifier
   */
  clear(sessionId) {
    try {
      const key = `${this.prefix}_${sessionId}`;
      localStorage.removeItem(key);
      return true;
    } catch (error) {
      console.error('Error clearing chat from localStorage:', error);
      return false;
    }
  }

  /**
   * Get all stored chat sessions
   * @returns {Array} Array of session metadata
   */
  getAllSessions() {
    const sessions = [];
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && key.startsWith(this.prefix + '_')) {
          const data = JSON.parse(localStorage.getItem(key));
          sessions.push({
            sessionId: data.sessionId,
            messageCount: data.messages?.length || 0,
            lastUpdated: data.lastUpdated
          });
        }
      }
    } catch (error) {
      console.error('Error getting all sessions:', error);
    }
    return sessions;
  }
}

// ============================================================================
// OPTION 2: AsyncStorage (React Native)
// ============================================================================

class AsyncStorageChatStorage {
  constructor(storage, prefix = 'lumidrive_chat') {
    this.storage = storage; // AsyncStorage instance
    this.prefix = prefix;
  }

  /**
   * Save chat messages for a session
   */
  async save(sessionId, messages) {
    try {
      const key = `${this.prefix}_${sessionId}`;
      const data = {
        messages: messages,
        lastUpdated: Date.now(),
        sessionId: sessionId
      };
      await this.storage.setItem(key, JSON.stringify(data));
      return true;
    } catch (error) {
      console.error('Error saving chat to AsyncStorage:', error);
      return false;
    }
  }

  /**
   * Load chat messages for a session
   */
  async load(sessionId) {
    try {
      const key = `${this.prefix}_${sessionId}`;
      const data = await this.storage.getItem(key);
      if (data) {
        const parsed = JSON.parse(data);
        return parsed.messages || [];
      }
      return [];
    } catch (error) {
      console.error('Error loading chat from AsyncStorage:', error);
      return [];
    }
  }

  /**
   * Clear chat messages for a session
   */
  async clear(sessionId) {
    try {
      const key = `${this.prefix}_${sessionId}`;
      await this.storage.removeItem(key);
      return true;
    } catch (error) {
      console.error('Error clearing chat from AsyncStorage:', error);
      return false;
    }
  }
}

// ============================================================================
// USAGE EXAMPLE: React Hook
// ============================================================================

/**
 * React Hook for managing chat storage
 * 
 * Usage:
 * ```jsx
 * function ChatComponent() {
 *   const { messages, addMessage, clearChat, loading } = useChatStorage('user123');
 *   
 *   const handleSend = async (text) => {
 *     addMessage({ role: 'user', content: text });
 *     // Send to backend...
 *   };
 *   
 *   return <ChatView messages={messages} onSend={handleSend} />;
 * }
 * ```
 */
function useChatStorage(sessionId, storageAdapter) {
  const [messages, setMessages] = React.useState([]);
  const [loading, setLoading] = React.useState(true);

  // Load chat history on mount
  React.useEffect(() => {
    const loadChat = async () => {
      try {
        const savedMessages = await storageAdapter.load(sessionId);
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
  }, [sessionId, storageAdapter]);

  // Auto-save messages whenever they change
  React.useEffect(() => {
    if (messages.length > 0 && sessionId) {
      storageAdapter.save(sessionId, messages).catch(error => {
        console.error('Error auto-saving chat:', error);
      });
    }
  }, [messages, sessionId, storageAdapter]);

  const addMessage = React.useCallback((message) => {
    setMessages(prev => [...prev, message]);
  }, []);

  const clearChat = React.useCallback(async () => {
    setMessages([]);
    if (sessionId) {
      await storageAdapter.clear(sessionId);
    }
  }, [sessionId, storageAdapter]);

  return {
    messages,
    addMessage,
    clearChat,
    loading
  };
}

// ============================================================================
// USAGE EXAMPLE: Integration with Backend API
// ============================================================================

/**
 * Send chat message to backend with full history
 * 
 * The backend supports restoring chat history via bootstrap_memory_from_messages()
 * so we send the full message history with each request.
 */
async function sendChatMessage(userMessage, sessionId, authToken, storageAdapter) {
  // 1. Load saved messages from local storage
  const savedMessages = await storageAdapter.load(sessionId);

  // 2. Add new user message
  const updatedMessages = [
    ...savedMessages,
    { role: 'user', content: userMessage }
  ];

  // 3. Save updated messages immediately (optimistic update)
  await storageAdapter.save(sessionId, updatedMessages);

  try {
    // 4. Send to backend with full message history
    const response = await fetch('/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${authToken}`
      },
      body: JSON.stringify({
        session_id: sessionId,
        user_message: userMessage,
        messages: updatedMessages // Send full history for backend restoration
      })
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    // 5. Handle streaming response (if backend streams)
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let assistantMessage = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value);
      assistantMessage += chunk;
      
      // Update UI with streaming chunks (optional)
      // onStreamChunk(chunk);
    }

    // 6. Save final messages including assistant response
    const finalMessages = [
      ...updatedMessages,
      { role: 'assistant', content: assistantMessage }
    ];
    await storageAdapter.save(sessionId, finalMessages);

    return {
      success: true,
      message: assistantMessage,
      messages: finalMessages
    };
  } catch (error) {
    console.error('Error sending chat message:', error);
    
    // Revert optimistic update on error
    await storageAdapter.save(sessionId, savedMessages);
    
    throw error;
  }
}

// ============================================================================
// USAGE EXAMPLE: Complete Chat Service
// ============================================================================

class ChatService {
  constructor(storageAdapter, apiBaseUrl, getAuthToken) {
    this.storage = storageAdapter;
    this.apiBaseUrl = apiBaseUrl;
    this.getAuthToken = getAuthToken; // Function that returns current auth token
  }

  /**
   * Initialize chat session - loads saved messages
   */
  async initializeSession(sessionId) {
    return await this.storage.load(sessionId);
  }

  /**
   * Send a message and get response
   */
  async sendMessage(sessionId, userMessage) {
    const token = await this.getAuthToken();
    return await sendChatMessage(
      userMessage,
      sessionId,
      token,
      this.storage
    );
  }

  /**
   * Clear chat history for a session
   */
  async clearSession(sessionId) {
    return await this.storage.clear(sessionId);
  }

  /**
   * Get all chat sessions
   */
  async getAllSessions() {
    if (this.storage.getAllSessions) {
      return await this.storage.getAllSessions();
    }
    return [];
  }
}

// ============================================================================
// INITIALIZATION EXAMPLES
// ============================================================================

// For Web (localStorage):
// const chatStorage = new LocalStorageChatStorage();
// const chatService = new ChatService(
//   chatStorage,
//   'https://api.lumidrive.com',
//   () => localStorage.getItem('auth_token')
// );

// For React Native (AsyncStorage):
// import AsyncStorage from '@react-native-async-storage/async-storage';
// const chatStorage = new AsyncStorageChatStorage(AsyncStorage);
// const chatService = new ChatService(
//   chatStorage,
//   'https://api.lumidrive.com',
//   async () => await AsyncStorage.getItem('auth_token')
// );

// Export for use
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    LocalStorageChatStorage,
    AsyncStorageChatStorage,
    useChatStorage,
    sendChatMessage,
    ChatService
  };
}

