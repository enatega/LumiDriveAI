# LumiDrive Assistant - Frontend Integration Guide

## 📋 Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [API Endpoints](#api-endpoints)
4. [Authentication](#authentication)
5. [Complete Workflows](#complete-workflows)
6. [Routing Structure](#routing-structure)
7. [Implementation Examples](#implementation-examples)
8. [Error Handling](#error-handling)
9. [State Management](#state-management)
10. [Testing](#testing)

---

## 🎯 Overview

The LumiDrive Assistant is an AI-powered chat interface that helps users book rides through natural language conversations. It supports:
- **Text Chat**: Type messages and receive streaming responses
- **Voice Chat**: Record audio, convert to text, get assistant response, and play audio
- **Session Management**: Maintains conversation context per session
- **Streaming Responses**: Real-time text streaming for better UX

**Backend URL**: `https://lumidriveai-production.up.railway.app`  
**Local Development**: `http://localhost:8000`

---

## 🏗️ Architecture

```
Frontend (React Native/Expo)
    ↓
API Service Layer (assistantChatApi.ts)
    ↓
Backend API (FastAPI)
    ↓
OpenAI API (Chat, STT, TTS)
    ↓
LumiDrive Backend (Ride Booking)
```

### Key Components:
1. **API Service** (`assistantChatApi.ts`): Handles all API calls
2. **Chat Screen**: UI component for chat interface
3. **Backend Server** (`server.py`): FastAPI server with 3 endpoints
4. **Memory Store**: LangChain-based conversation memory (backend)

---

## 🔌 API Endpoints

### 1. POST `/chat` - Chat Endpoint

**Purpose**: Send text messages and receive streaming responses

**Headers**:
```
Content-Type: application/json
Authorization: Bearer <JWT_TOKEN>
```

**Request Body**:
```typescript
{
  session_id: string;        // Required: Unique session identifier
  user_message?: string;     // Optional: New user message
  messages?: ChatMessage[];  // Optional: Full conversation history (for bootstrap)
}
```

**Response**: Streaming text chunks (text/plain)

**Example Request**:
```typescript
POST https://lumidriveai-production.up.railway.app/chat
Headers: {
  "Content-Type": "application/json",
  "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
Body: {
  "session_id": "session-1234567890-abc123",
  "user_message": "I want to book a ride from Islamabad to Rawalpindi"
}
```

**Response Handling**:
- Response is streamed as text chunks
- Each chunk should be appended to display progressively
- Full response is accumulated on the frontend

---

### 2. POST `/stt` - Speech-to-Text Endpoint

**Purpose**: Convert audio recording to text transcript

**Headers**:
```
Authorization: Bearer <JWT_TOKEN>
Content-Type: multipart/form-data
```

**Request Body** (FormData):
```
file: <Audio Blob/File>
language: "en" (optional, default: "en")
session_id: "session-123..." (optional)
```

**Response**:
```typescript
{
  ok: boolean;
  text: string;              // Transcribed text
  language: string;          // Detected language
  duration?: number;         // Audio duration in seconds
  segments?: any[];          // Detailed segments
  session_id?: string;       // Echoed session_id
}
```

**Example Request**:
```typescript
const formData = new FormData();
formData.append('file', audioBlob, 'recording.webm');
formData.append('language', 'en');
formData.append('session_id', sessionId);

fetch('https://lumidriveai-production.up.railway.app/stt', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`
  },
  body: formData
});
```

---

### 3. POST `/tts` - Text-to-Speech Endpoint

**Purpose**: Convert text to speech audio

**Headers**:
```
Content-Type: application/json
Authorization: Bearer <JWT_TOKEN>
```

**Request Body**:
```typescript
{
  text: string;              // Required: Text to convert
  voice?: string;            // Optional: "alloy" | "echo" | "fable" | "onyx" | "nova" | "shimmer" (default: "alloy")
  audio_format?: string;     // Optional: "mp3" | "opus" | "aac" | "flac" (default: "mp3")
}
```

**Response**: Audio file blob (audio/mp3, audio/opus, etc.)

**Example Request**:
```typescript
fetch('https://lumidriveai-production.up.railway.app/tts', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`
  },
  body: JSON.stringify({
    text: "I'll help you book a ride.",
    voice: "alloy",
    audio_format: "mp3"
  })
});
```

---

## 🔐 Authentication

### Token Requirements
- All endpoints require a **JWT Bearer token** in the Authorization header
- Token is obtained from your app's authentication system (Redux store, AsyncStorage, etc.)
- Token is used by the backend to make authenticated requests to the LumiDrive ride booking API

### Token Format
```
Authorization: Bearer <JWT_TOKEN>
```

### Getting the Token

**Option 1: From Redux Store** (Recommended)
```typescript
import { useSelector } from 'react-redux';

const authToken = useSelector((state: any) => state?.authSuperApp?.token);
```

**Option 2: From AsyncStorage**
```typescript
import AsyncStorage from '@react-native-async-storage/async-storage';

const authToken = await AsyncStorage.getItem('authToken');
```

**Option 3: From API Instance** (If using axios interceptors)
```typescript
const token = apiInstance.defaults.headers.common['Authorization']?.replace('Bearer ', '');
```

### Error Handling
- **401 Unauthorized**: Token is missing or invalid
- **403 Forbidden**: Token is valid but lacks permissions
- Always check for token before making API calls

---

## 🔄 Complete Workflows

### Workflow 1: Text Chat Flow

```
1. User types message → Input field
2. User clicks Send → sendTextMessage()
3. Check authentication token
4. Add user message to UI
5. Call POST /chat with:
   - session_id (persistent per conversation)
   - user_message (the typed text)
6. Receive streaming response chunks
7. Display chunks progressively in UI
8. Accumulate full response
9. Add assistant message to conversation
10. (Optional) Call POST /tts to play audio
11. Update UI state
```

**Code Flow**:
```typescript
// 1. User sends message
const sendTextMessage = async () => {
  if (!authToken) {
    // Show login prompt
    return;
  }

  // 2. Add user message to UI
  addMessage('user', userMessage);
  setIsLoading(true);

  // 3. Call chat API
  let fullResponse = '';
  await assistantChatApi.sendChatMessage(
    {
      session_id: sessionId,
      user_message: userMessage,
    },
    (chunk) => {
      // 4. Stream chunks to UI
      fullResponse += chunk;
      setCurrentStreamingText(fullResponse);
    }
  );

  // 5. Finalize message
  addMessage('assistant', fullResponse);
  setIsLoading(false);

  // 6. Optional: Play TTS
  const audioBlob = await assistantChatApi.textToSpeech(fullResponse);
  playAudio(audioBlob);
};
```

---

### Workflow 2: Voice Chat Flow

```
1. User presses/holds microphone button → startRecording()
2. Request microphone permissions
3. Start audio recording (expo-av, MediaRecorder, etc.)
4. User releases button → stopRecording()
5. Stop recording and get audio blob
6. Call POST /stt with audio blob
7. Receive transcript text
8. Update UI: Replace "Recording..." with transcript
9. Call POST /chat with transcript as user_message
10. Receive streaming response
11. Display response in UI
12. Call POST /tts with assistant response
13. Play audio response
```

**Code Flow**:
```typescript
// 1. Start recording
const startRecording = async () => {
  const { status } = await Audio.requestPermissionsAsync();
  if (status !== 'granted') return;

  const { recording } = await Audio.Recording.createAsync(
    Audio.RecordingOptionsPresets.HIGH_QUALITY
  );
  setRecording(recording);
  setIsRecording(true);
  addMessage('user', 'Recording...');
};

// 2. Stop recording and process
const stopRecording = async () => {
  await recording.stopAndUnloadAsync();
  const uri = recording.getURI();
  const audioBlob = await (await fetch(uri)).blob();

  // 3. Convert speech to text
  const sttResponse = await assistantChatApi.speechToText(
    audioBlob,
    'en',
    sessionId
  );

  // 4. Update UI with transcript
  updateLastUserMessage(sttResponse.text);

  // 5. Send to chat
  let fullResponse = '';
  await assistantChatApi.sendChatMessage(
    {
      session_id: sessionId,
      user_message: sttResponse.text,
    },
    (chunk) => {
      fullResponse += chunk;
      setCurrentStreamingText(fullResponse);
    }
  );

  // 6. Play TTS
  const audioBlob = await assistantChatApi.textToSpeech(fullResponse);
  playAudio(audioBlob);
};
```

---

### Workflow 3: Session Management

```
1. User opens chat → Generate unique session_id
2. Store session_id in component state (or global state)
3. Use same session_id for all messages in conversation
4. Backend maintains conversation history per session_id
5. New conversation → Generate new session_id
6. Session persists until user clears chat or app closes
```

**Session ID Generation**:
```typescript
const generateSessionId = () => {
  return `session-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
};

// In component
const [sessionId] = useState(generateSessionId());
```

**Session Persistence** (Optional):
```typescript
// Save session_id
await AsyncStorage.setItem('chatSessionId', sessionId);

// Restore session_id
const savedSessionId = await AsyncStorage.getItem('chatSessionId');
const [sessionId] = useState(savedSessionId || generateSessionId());
```

---

## 🗺️ Routing Structure

### Recommended Route Structure

```
/app/
  /(ai-chat)/
    _layout.tsx          // Layout wrapper for chat routes
    index.tsx            // Chat screen entry point
    chatScreen.tsx       // Main chat component (optional alias)
```

### Expo Router Example

**File: `app/(ai-chat)/_layout.tsx`**
```typescript
import { Stack } from 'expo-router';

export default function ChatLayout() {
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="index" />
      <Stack.Screen name="chatScreen" />
    </Stack>
  );
}
```

**File: `app/(ai-chat)/index.tsx`**
```typescript
import ChatScreen from '@/screens/ai-chat/screens/chat';

export default ChatScreen;
```

### Navigation

**Navigate to Chat**:
```typescript
import { useRouter } from 'expo-router';

const router = useRouter();
router.push('/(ai-chat)');
// or
router.push('/ai-chat');
```

**Navigate from Chat**:
```typescript
const router = useRouter();
router.push('/home');  // Go back to home
router.back();         // Go back to previous screen
```

---

## 💻 Implementation Examples

### Example 1: Complete API Service

**File: `src/services/api/assistantChatApi.ts`**

```typescript
const ASSISTANT_API_BASE = 'https://lumidriveai-production.up.railway.app';

class AssistantChatApi {
  private getAuthToken(): string | null {
    // Implement token retrieval from your auth system
    // Return null if not authenticated
  }

  async sendChatMessage(
    request: { session_id: string; user_message: string },
    onChunk?: (chunk: string) => void
  ): Promise<string> {
    const token = this.getAuthToken();
    if (!token) throw new Error('Not authenticated');

    const response = await fetch(`${ASSISTANT_API_BASE}/chat`, {
      method: 'POST',
      mode: 'cors',
      credentials: 'omit',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Chat failed: ${response.status} - ${error}`);
    }

    // Stream response
    const reader = response.body?.getReader();
    const decoder = new TextDecoder();
    let fullText = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      fullText += chunk;
      onChunk?.(chunk);
    }

    return fullText;
  }

  async speechToText(
    audioBlob: Blob,
    language: string = 'en',
    sessionId?: string
  ): Promise<{ text: string; language: string }> {
    const token = this.getAuthToken();
    if (!token) throw new Error('Not authenticated');

    const formData = new FormData();
    formData.append('file', audioBlob, 'recording.webm');
    formData.append('language', language);
    if (sessionId) formData.append('session_id', sessionId);

    const response = await fetch(`${ASSISTANT_API_BASE}/stt`, {
      method: 'POST',
      mode: 'cors',
      credentials: 'omit',
      headers: { 'Authorization': `Bearer ${token}` },
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`STT failed: ${response.status}`);
    }

    return response.json();
  }

  async textToSpeech(
    text: string,
    voice: string = 'alloy',
    audioFormat: string = 'mp3'
  ): Promise<Blob> {
    const token = this.getAuthToken();
    if (!token) throw new Error('Not authenticated');

    const response = await fetch(`${ASSISTANT_API_BASE}/tts`, {
      method: 'POST',
      mode: 'cors',
      credentials: 'omit',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({ text, voice, audio_format: audioFormat }),
    });

    if (!response.ok) {
      throw new Error(`TTS failed: ${response.status}`);
    }

    return response.blob();
  }
}

export const assistantChatApi = new AssistantChatApi();
```

---

### Example 2: Complete Chat Component

**File: `src/screens/ai-chat/screens/chat/index.tsx`**

```typescript
import React, { useState, useRef, useEffect } from 'react';
import { View, Text, TextInput, TouchableOpacity, ScrollView, Alert } from 'react-native';
import { Audio } from 'expo-av';
import { assistantChatApi } from '@/services/api/assistantChatApi';
import { useSelector } from 'react-redux';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

const ChatScreen = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: 'assistant', content: "Hi! I'm LumiDrive. How can I help you?" }
  ]);
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [recording, setRecording] = useState<any>(null);
  const [currentStreamingText, setCurrentStreamingText] = useState('');
  const [sessionId] = useState(`session-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`);
  
  const authToken = useSelector((state: any) => state?.authSuperApp?.token);

  // Text message handler
  const sendTextMessage = async () => {
    if (!inputText.trim() || isLoading || !authToken) return;

    const userMessage = inputText.trim();
    setInputText('');
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setIsLoading(true);
    setCurrentStreamingText('');

    try {
      let fullResponse = '';
      await assistantChatApi.sendChatMessage(
        { session_id: sessionId, user_message: userMessage },
        (chunk) => {
          fullResponse += chunk;
          setCurrentStreamingText(fullResponse);
        }
      );

      setMessages(prev => [...prev, { role: 'assistant', content: fullResponse }]);
      setCurrentStreamingText('');

      // Optional: Play TTS
      try {
        const audioBlob = await assistantChatApi.textToSpeech(fullResponse);
        const { sound } = await Audio.Sound.createAsync({ 
          uri: URL.createObjectURL(audioBlob) 
        });
        await sound.playAsync();
      } catch (ttsError) {
        console.log('TTS error (non-critical):', ttsError);
      }
    } catch (error: any) {
      Alert.alert('Error', error.message || 'Failed to send message');
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: 'Sorry, I encountered an error. Please try again.' 
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  // Voice recording handlers
  const startRecording = async () => {
    if (!authToken) {
      Alert.alert('Login Required', 'Please login to use voice chat');
      return;
    }

    try {
      const { status } = await Audio.requestPermissionsAsync();
      if (status !== 'granted') {
        Alert.alert('Permission Required', 'Microphone permission needed');
        return;
      }

      const { recording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY
      );
      setRecording(recording);
      setIsRecording(true);
      setMessages(prev => [...prev, { role: 'user', content: 'Recording...' }]);
    } catch (error: any) {
      Alert.alert('Error', 'Failed to start recording: ' + error.message);
    }
  };

  const stopRecording = async () => {
    if (!recording) return;

    setIsRecording(false);
    try {
      await recording.stopAndUnloadAsync();
      const uri = recording.getURI();
      const audioBlob = await (await fetch(uri)).blob();

      // STT
      const sttResponse = await assistantChatApi.speechToText(audioBlob, 'en', sessionId);

      // Update UI with transcript
      setMessages(prev => {
        const newMessages = [...prev];
        const lastMsg = newMessages[newMessages.length - 1];
        if (lastMsg.content === 'Recording...') {
          newMessages[newMessages.length - 1] = { 
            role: 'user', 
            content: sttResponse.text 
          };
        }
        return newMessages;
      });

      // Send to chat
      setIsLoading(true);
      let fullResponse = '';
      await assistantChatApi.sendChatMessage(
        { session_id: sessionId, user_message: sttResponse.text },
        (chunk) => {
          fullResponse += chunk;
          setCurrentStreamingText(fullResponse);
        }
      );

      setMessages(prev => [...prev, { role: 'assistant', content: fullResponse }]);
      setCurrentStreamingText('');

      // Play TTS
      const audioBlob = await assistantChatApi.textToSpeech(fullResponse);
      const { sound } = await Audio.Sound.createAsync({ 
        uri: URL.createObjectURL(audioBlob) 
      });
      await sound.playAsync();
    } catch (error: any) {
      Alert.alert('Error', error.message || 'Failed to process voice');
    } finally {
      setIsLoading(false);
      setRecording(undefined);
    }
  };

  return (
    <View style={{ flex: 1 }}>
      <ScrollView style={{ flex: 1, padding: 16 }}>
        {messages.map((msg, idx) => (
          <View key={idx} style={{ 
            marginBottom: 12,
            alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start'
          }}>
            <Text style={{ 
              padding: 12, 
              backgroundColor: msg.role === 'user' ? '#007AFF' : '#E5E5EA',
              borderRadius: 16,
              color: msg.role === 'user' ? 'white' : 'black'
            }}>
              {msg.content}
            </Text>
          </View>
        ))}
        {isLoading && currentStreamingText && (
          <View style={{ alignSelf: 'flex-start', marginBottom: 12 }}>
            <Text style={{ 
              padding: 12, 
              backgroundColor: '#E5E5EA',
              borderRadius: 16
            }}>
              {currentStreamingText}
            </Text>
          </View>
        )}
      </ScrollView>

      <View style={{ flexDirection: 'row', padding: 16, borderTopWidth: 1 }}>
        <TextInput
          style={{ flex: 1, borderWidth: 1, borderRadius: 20, padding: 12, marginRight: 8 }}
          value={inputText}
          onChangeText={setInputText}
          placeholder="Type a message..."
          editable={!isLoading}
        />
        <TouchableOpacity
          onPress={isRecording ? stopRecording : startRecording}
          onLongPress={startRecording}
          style={{ 
            width: 50, 
            height: 50, 
            borderRadius: 25, 
            backgroundColor: isRecording ? 'red' : '#007AFF',
            justifyContent: 'center',
            alignItems: 'center',
            marginRight: 8
          }}
        >
          <Text style={{ color: 'white' }}>🎤</Text>
        </TouchableOpacity>
        <TouchableOpacity
          onPress={sendTextMessage}
          disabled={isLoading || !inputText.trim()}
          style={{ 
            width: 50, 
            height: 50, 
            borderRadius: 25, 
            backgroundColor: isLoading ? '#ccc' : '#007AFF',
            justifyContent: 'center',
            alignItems: 'center'
          }}
        >
          <Text style={{ color: 'white' }}>➤</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
};

export default ChatScreen;
```

---

## ⚠️ Error Handling

### Common Errors and Solutions

**1. "No authentication token available"**
- **Cause**: User not logged in or token not in store
- **Solution**: Check authentication state, redirect to login

**2. "Failed to fetch" / Network Error**
- **Cause**: CORS issue, server down, or network problem
- **Solution**: 
  - Check server is running
  - Verify API URL is correct
  - Check network connectivity
  - Ensure CORS is configured on backend

**3. "401 Unauthorized"**
- **Cause**: Invalid or expired token
- **Solution**: Refresh token or re-authenticate user

**4. "500 Internal Server Error"**
- **Cause**: Backend error (OpenAI API issue, etc.)
- **Solution**: Check backend logs, retry request

**5. "Failed to start recording"**
- **Cause**: Microphone permission denied
- **Solution**: Request permissions, check device settings

### Error Handling Pattern

```typescript
try {
  const response = await assistantChatApi.sendChatMessage(...);
} catch (error: any) {
  if (error.message.includes('authentication')) {
    // Redirect to login
    router.push('/login');
  } else if (error.message.includes('Network')) {
    // Show network error message
    Alert.alert('Connection Error', 'Please check your internet connection');
  } else {
    // Show generic error
    Alert.alert('Error', error.message || 'Something went wrong');
  }
}
```

---

## 📦 State Management

### Recommended State Structure

```typescript
interface ChatState {
  messages: ChatMessage[];
  sessionId: string;
  isLoading: boolean;
  isRecording: boolean;
  currentStreamingText: string;
  error: string | null;
}
```

### State Management Options

**Option 1: Component State** (Simple)
```typescript
const [messages, setMessages] = useState<ChatMessage[]>([]);
const [sessionId] = useState(generateSessionId());
```

**Option 2: Context API** (Medium complexity)
```typescript
const ChatContext = createContext<ChatState | null>(null);
```

**Option 3: Redux/ Zustand** (Complex apps)
```typescript
// Redux slice for chat state
const chatSlice = createSlice({
  name: 'chat',
  initialState: { messages: [], sessionId: null },
  reducers: { ... }
});
```

---

## 🧪 Testing

### Manual Testing Checklist

**Text Chat**:
- [ ] Send text message
- [ ] Verify streaming response appears
- [ ] Check message history persists
- [ ] Test with empty input (should not send)
- [ ] Test without authentication (should prompt login)

**Voice Chat**:
- [ ] Record audio
- [ ] Verify transcript appears
- [ ] Check assistant response
- [ ] Verify TTS plays
- [ ] Test permission denial handling

**Session Management**:
- [ ] Verify same session_id used across messages
- [ ] Check conversation context maintained
- [ ] Test new session creation

**Error Handling**:
- [ ] Test with invalid token
- [ ] Test with network offline
- [ ] Test with server error

### Test Scenarios

**Scenario 1: Complete Ride Booking**
```
1. User: "I want to book a ride from Islamabad F7 to F6"
2. Assistant: [Streams response about ride types]
3. User: "Book a standard ride"
4. Assistant: [Creates ride request, shows bids]
5. User: "Accept the first bid"
6. Assistant: [Confirms ride booking]
```

**Scenario 2: Voice Booking**
```
1. User: [Records] "Book me a ride"
2. STT: "Book me a ride"
3. Assistant: [Streams response]
4. TTS: [Plays audio response]
```

---

## 📝 Quick Reference

### API Base URL
```
Production: https://lumidriveai-production.up.railway.app
Local: http://localhost:8000
```

### Required Headers
```
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json (for /chat and /tts)
Content-Type: multipart/form-data (for /stt)
```

### Session ID Format
```
session-<timestamp>-<random>
Example: session-1701234567890-abc123xyz
```

### Audio Formats
- **Recording**: WebM, WAV, M4A (depends on platform)
- **TTS Output**: MP3, Opus, AAC, FLAC
- **Recommended**: MP3 for compatibility

---

## 🚀 Deployment Checklist

Before deploying to production:

- [ ] Update `ASSISTANT_API_BASE` to production URL
- [ ] Verify authentication token flow
- [ ] Test all three endpoints (chat, STT, TTS)
- [ ] Test on iOS and Android devices
- [ ] Verify microphone permissions
- [ ] Test error handling scenarios
- [ ] Monitor API response times
- [ ] Set up error logging/monitoring
- [ ] Test with real user authentication tokens

---

## 📞 Support

For issues or questions:
- **Backend Logs**: Railway dashboard
- **Frontend Logs**: Expo dev tools / React Native debugger
- **Network Debugging**: Chrome DevTools Network tab
- **API Testing**: Use Postman or curl for endpoint testing

---

## 📚 Additional Resources

- **Expo Audio**: https://docs.expo.dev/versions/latest/sdk/audio/
- **React Native Fetch**: https://reactnative.dev/docs/network
- **FastAPI CORS**: https://fastapi.tiangolo.com/tutorial/cors/
- **OpenAI API**: https://platform.openai.com/docs

---

**Last Updated**: November 2024  
**Version**: 1.0.0

