# Run Commands Guide

## 🐍 Backend (FastAPI Server)

### Step 1: Navigate to Project Root
```bash
cd /Users/macbookpro/lumidrive-assistant
```

### Step 2: Create Virtual Environment (if not exists)
```bash
# Create virtual environment
python3 -m venv venv

# Or if you prefer a different name
python3 -m venv .venv
```

### Step 3: Activate Virtual Environment

**On macOS/Linux:**
```bash
source venv/bin/activate
```

**On Windows:**
```bash
venv\Scripts\activate
```

### Step 4: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 5: Set Up Environment Variables
Create a `.env` file in the project root (if not exists):
```bash
# .env file
OPENAI_API_KEY=your_openai_api_key_here
API_BASE_URL=your_api_base_url_here
CUSTOMER_ID=your_customer_id_here
```

### Step 6: Run the Server
```bash
# Using uvicorn directly
uvicorn server:app --host 0.0.0.0 --port 8000 --reload

# Or with Python
python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

**Server will be available at:**
- Local: `http://localhost:8000`
- Network: `http://0.0.0.0:8000`

**API Documentation:**
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## 🌐 Test Frontend (HTML/JavaScript)

### Quick Start (Simple Method)
```bash
# Navigate to project root
cd /Users/macbookpro/lumidrive-assistant

# Open directly in browser (macOS)
open test_frontend.html

# Or on Linux
xdg-open test_frontend.html

# Or on Windows
start test_frontend.html
```

### Recommended Method (HTTP Server)
For better CORS handling and testing, serve it via HTTP:

**Option 1: Python HTTP Server**
```bash
cd /Users/macbookpro/lumidrive-assistant

# Python 3
python3 -m http.server 8080

# Or Python 2
python -m SimpleHTTPServer 8080
```

Then open in browser: `http://localhost:8080/test_frontend.html`

**Option 2: Node.js HTTP Server**
```bash
cd /Users/macbookpro/lumidrive-assistant

# Install http-server globally (first time only)
npm install -g http-server

# Run server
http-server -p 8080
```

Then open in browser: `http://localhost:8080/test_frontend.html`

**Option 3: VS Code Live Server**
- Install "Live Server" extension in VS Code
- Right-click on `test_frontend.html`
- Select "Open with Live Server"

### Configuration
1. **JWT Token**: Enter your authentication token in the input field
2. **API URL**: 
   - Local: `http://localhost:8000`
   - Production: `https://lumidriveai-production.up.railway.app`

### Features
- ✅ Text chat with streaming responses
- ✅ Voice recording (STT → Chat → TTS)
- ✅ Real-time message streaming
- ✅ Session management
- ✅ Chat history

### Troubleshooting

**CORS Errors:**
- Make sure backend is running with CORS enabled
- Use HTTP server method instead of opening file directly

**Microphone Not Working:**
- Grant microphone permissions in browser
- Use HTTPS or localhost (some browsers require secure context)

**API Connection Failed:**
- Verify backend is running on the specified port
- Check API URL is correct
- Ensure JWT token is valid

---

## 📱 Frontend (Expo/React Native App)

### Step 1: Navigate to Frontend Directory
```bash
cd /Users/macbookpro/lumidrive-assistant/Lumi-Customer-App-main
```

### Step 2: Install Dependencies (First Time Only)
```bash
npm install
# or
yarn install
```

### Step 3: Run the Frontend

**Start Expo Development Server:**
```bash
npm start
# or
yarn start
# or
npx expo start
```

**Run on Specific Platform:**
```bash
# Web
npm run web
# or
npx expo start --web

# iOS Simulator (requires Xcode)
npm run ios
# or
npx expo start --ios

# Android Emulator (requires Android Studio)
npm run android
# or
npx expo start --android
```

**Quick Options:**
- Press `w` to open in web browser
- Press `i` to open iOS simulator
- Press `a` to open Android emulator
- Press `r` to reload the app
- Press `m` to toggle menu

---

## 🚀 Quick Start (All-in-One)

### Option 1: Test Frontend (HTML) - Easiest

**Terminal 1: Backend**
```bash
cd /Users/macbookpro/lumidrive-assistant
source venv/bin/activate
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2: Test Frontend Server**
```bash
cd /Users/macbookpro/lumidrive-assistant
python3 -m http.server 8080
```

Then open: `http://localhost:8080/test_frontend.html`

### Option 2: Full Frontend (Expo App)

**Terminal 1: Backend**
```bash
cd /Users/macbookpro/lumidrive-assistant
source venv/bin/activate
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2: Frontend**
```bash
cd /Users/macbookpro/lumidrive-assistant/Lumi-Customer-App-main
npm start
# Then press 'w' for web or 'i' for iOS
```

---

## 🔧 Troubleshooting

### Backend Issues

**Port Already in Use:**
```bash
# Kill process on port 8000
lsof -ti:8000 | xargs kill -9

# Or use a different port
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

**Module Not Found:**
```bash
# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

**Virtual Environment Not Activating:**
```bash
# Recreate virtual environment
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Frontend Issues

**Node Modules Issues:**
```bash
# Clear cache and reinstall
rm -rf node_modules
npm install
# or
yarn install
```

**Metro Bundler Issues:**
```bash
# Clear Metro cache
npx expo start --clear
```

**Port Already in Use (Metro):**
```bash
# Kill process on port 8081
lsof -ti:8081 | xargs kill -9
```

**Expo CLI Not Found:**
```bash
# Install Expo CLI globally
npm install -g expo-cli
# or use npx (recommended)
npx expo start
```

---

## 📝 Environment Variables

### Backend (.env file)
```env
OPENAI_API_KEY=sk-...
API_BASE_URL=https://api.example.com
CUSTOMER_ID=your-customer-id
```

### Frontend
Update `ASSISTANT_API_BASE` in:
```
Lumi-Customer-App-main/src/services/api/assistantChatApi.ts
```

For local development, change line 4 to:
```typescript
const ASSISTANT_API_BASE = 'http://localhost:8000';
```

For production:
```typescript
const ASSISTANT_API_BASE = 'https://lumidriveai-production.up.railway.app';
```

---

## 🔍 Verify Everything is Running

### Check Backend
```bash
# Test the health endpoint (if exists)
curl http://localhost:8000/docs

# Or test chat endpoint
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"session_id":"test-123","user_message":"Hello"}'
```

### Check Frontend
- Open browser to `http://localhost:19006` (Expo DevTools)
- Or scan QR code with Expo Go app on your phone
- Or open in web browser at `http://localhost:8081`

---

## 📚 Additional Commands

### Backend
```bash
# Run with specific log level
uvicorn server:app --host 0.0.0.0 --port 8000 --log-level debug

# Run without auto-reload (production-like)
uvicorn server:app --host 0.0.0.0 --port 8000

# Run with workers (production)
uvicorn server:app --host 0.0.0.0 --port 8000 --workers 4
```

### Frontend
```bash
# Clear all caches
npm start -- --clear

# Run in tunnel mode (for testing on physical device)
npx expo start --tunnel

# Run in production mode
NODE_ENV=production npm start
```

---

## 🎯 Development Workflow

1. **Start Backend First:**
   ```bash
   cd /Users/macbookpro/lumidrive-assistant
   source venv/bin/activate
   uvicorn server:app --host 0.0.0.0 --port 8000 --reload
   ```

2. **Start Frontend Second:**
   ```bash
   cd /Users/macbookpro/lumidrive-assistant/Lumi-Customer-App-main
   npm start
   ```

3. **Open Frontend:**
   - Press `w` for web browser
   - Or scan QR code with Expo Go app

4. **Test Integration:**
   - Navigate to chat screen in the app
   - Send a test message
   - Check backend logs for request/response
   - Verify frontend receives streaming response

---

## 📞 Need Help?

- **Backend Logs**: Check terminal running `uvicorn`
- **Frontend Logs**: Check terminal running `npm start` or browser console
- **Network Issues**: Verify CORS is enabled and API URL is correct
- **Authentication**: Ensure token is properly set in Redux store

---

**Last Updated**: November 2024

