from typing import List, Literal, Optional, Dict, Any
import logging
import time

from fastapi import FastAPI, Header, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api import set_token
from assistant import (
    SYSTEM,
    MODEL,
    client,
    tools,
    call_tool,
)
from memory_store import (
    get_memory,
    bootstrap_memory_from_messages,
    memory_to_openai_messages,
)
from speech import transcribe_audio, synthesize_speech
import json
import os
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    user_message: Optional[str] = None
    messages: Optional[List[ChatMessage]] = None


class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    audio_format: Optional[str] = None


app = FastAPI(title="LumiDrive Assistant API")

# Add CORS middleware to allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific frontend URL
    allow_credentials=False,  # We use Bearer tokens, not cookies
    allow_methods=["*"],
    allow_headers=["*"],
)


def _set_backend_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty bearer token.")
    set_token(token)
    return token


def _last_user_message(messages: List[ChatMessage]) -> Optional[str]:
    for msg in reversed(messages):
        if msg.role == "user" and msg.content:
            return msg.content
    return None


async def _run_tools_for_message(msg, messages: List[Dict[str, Any]], user_location: Optional[Dict[str, float]] = None) -> None:
    """
    Execute any tool calls in msg and append their outputs to messages.
    This mirrors the logic in assistant.chat_loop but without CLI I/O.
    Handles both sync and async tools.
    """
    if not msg.tool_calls:
        return

    # Mirror the structure we keep in the interactive assistant
    messages.append({
        "role": "assistant",
        "content": msg.content or "",
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or "{}",
                },
            }
            for tc in msg.tool_calls
        ],
    })

    for tc in msg.tool_calls:
        args = json.loads(tc.function.arguments or "{}")
        
        try:
            from assistant import tool_create_request_and_poll, call_tool
            import inspect
            
            # For async tools, call them directly and await
            if tc.function.name == "set_trip_core":
                from assistant import tool_set_trip_core
                result = await tool_set_trip_core(**args)
            elif tc.function.name == "resolve_place_to_coordinates":
                from assistant import tool_resolve_place_to_coordinates
                result = await tool_resolve_place_to_coordinates(**args)
            elif tc.function.name == "set_ride_type":
                from assistant import tool_set_ride_type
                result = await tool_set_ride_type(**args)
            elif tc.function.name == "get_fare_quote":
                from assistant import tool_get_fare_quote
                result = await tool_get_fare_quote()
            elif tc.function.name == "get_fare_for_locations":
                from assistant import tool_get_fare_for_locations
                result = await tool_get_fare_for_locations(**args)
            elif tc.function.name == "check_active_ride":
                from assistant import tool_check_active_ride
                result = tool_check_active_ride()
            elif tc.function.name == "book_ride_with_details":
                from assistant import tool_book_ride_with_details
                result = await tool_book_ride_with_details(**args)
            elif tc.function.name == "auto_book_ride":
                from assistant import tool_auto_book_ride
                result = await tool_auto_book_ride(**args)
            elif tc.function.name == "create_ride_and_wait_for_bids":
                from assistant import tool_create_ride_and_wait_for_bids
                result = await tool_create_ride_and_wait_for_bids(**args)
            elif tc.function.name == "create_request_and_poll":
                from assistant import tool_create_request_and_poll
                result = await tool_create_request_and_poll(**args)
            else:
                # For sync tools, use call_tool
                tool_result = call_tool(tc.function.name, args)
                # Check if result is a coroutine (shouldn't happen for sync tools, but just in case)
                if inspect.iscoroutine(tool_result):
                    result = await tool_result
                else:
                    result = tool_result
                
        except TypeError as e:
            result = {"ok": False, "error": f"tool_{tc.function.name} invocation error", "details": str(e)}
        except Exception as exc:
            result = {"ok": False, "error": f"tool_{tc.function.name} crashed", "details": str(exc)}

        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "name": tc.function.name,
            "content": json.dumps(result),
        })


@app.post("/chat")
async def chat_endpoint(
    request: Request,
    body: ChatRequest,
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
):
    """
    Chat endpoint for the LumiDrive assistant.

    - Expects full conversation array in `body.messages`.
    - Uses the Bearer token from the Authorization header to talk to the rides backend.
    - Streams the final assistant reply back to the caller.
    """
    start_time = time.time()
    request_id = f"{int(time.time() * 1000)}-{id(request)}"
    
    # Log request received
    logger.info(f"[{request_id}] ========== POST /chat REQUEST ==========")
    logger.info(f"[{request_id}] Session ID: {body.session_id}")
    logger.info(f"[{request_id}] User Message: {body.user_message[:200] if body.user_message else 'None'}...")
    logger.info(f"[{request_id}] Messages Count: {len(body.messages) if body.messages else 0}")
    logger.info(f"[{request_id}] Auth Token Present: {bool(authorization)}")
    if authorization:
        token_preview = authorization[:20] + "..." if len(authorization) > 20 else authorization
        logger.info(f"[{request_id}] Auth Token Preview: {token_preview}")
    
    try:
        _set_backend_token(authorization)

        if not body.session_id:
            logger.error(f"[{request_id}] ERROR: session_id is required")
            raise HTTPException(status_code=400, detail="session_id is required.")

        memory = get_memory(body.session_id)
        logger.info(f"[{request_id}] Memory retrieved for session: {body.session_id}")

        if body.messages:
            bootstrap_memory_from_messages(memory, [m.dict() for m in body.messages])
            logger.info(f"[{request_id}] Bootstrapped memory with {len(body.messages)} messages")

        user_message = (body.user_message or "").strip()
        if not user_message and body.messages:
            user_message = (_last_user_message(body.messages) or "").strip()

        if not user_message:
            logger.error(f"[{request_id}] ERROR: user_message is required")
            raise HTTPException(status_code=400, detail="user_message is required.")

        logger.info(f"[{request_id}] Processing user message: {user_message[:100]}...")
        memory.chat_memory.add_user_message(user_message)

        messages = memory_to_openai_messages(memory, SYSTEM)
        logger.info(f"[{request_id}] Total messages for OpenAI: {len(messages)}")

        try:
            logger.info(f"[{request_id}] Calling OpenAI API (first call with tools)...")
            first = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=[{"type": "function", "function": t["function"]} for t in tools],
                tool_choice="auto",
            )
            logger.info(f"[{request_id}] OpenAI first call completed")
        except Exception as exc:
            logger.error(f"[{request_id}] ERROR: Failed to reach OpenAI: {exc}")
            raise HTTPException(status_code=502, detail=f"Failed to reach OpenAI: {exc}") from exc

        first_msg = first.choices[0].message
        if first_msg.tool_calls:
            logger.info(f"[{request_id}] Executing {len(first_msg.tool_calls)} tool calls...")
            for tc in first_msg.tool_calls:
                logger.info(f"[{request_id}] Tool Call: {tc.function.name}")
        await _run_tools_for_message(first_msg, messages)

        try:
            logger.info(f"[{request_id}] Calling OpenAI API (streaming response)...")
            stream = client.chat.completions.create(
                model=MODEL,
                messages=messages + [{"role": "assistant", "content": first_msg.content or ""}],
                stream=True,
            )
            logger.info(f"[{request_id}] OpenAI streaming started")
        except Exception as exc:
            logger.error(f"[{request_id}] ERROR: Failed to stream OpenAI response: {exc}")
            raise HTTPException(status_code=502, detail=f"Failed to stream OpenAI response: {exc}") from exc

        def token_stream():
            final_chunks: List[str] = []
            chunk_count = 0
            try:
                for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        final_chunks.append(delta.content)
                        chunk_count += 1
                        yield delta.content
            finally:
                final_text = "".join(final_chunks).strip()
                elapsed_time = time.time() - start_time
                if final_text:
                    memory.chat_memory.add_ai_message(final_text)
                    logger.info(f"[{request_id}] ========== POST /chat RESPONSE ==========")
                    logger.info(f"[{request_id}] Status: 200 OK")
                    logger.info(f"[{request_id}] Response Length: {len(final_text)} characters")
                    logger.info(f"[{request_id}] Response Preview: {final_text[:200]}...")
                    logger.info(f"[{request_id}] Chunks Streamed: {chunk_count}")
                    logger.info(f"[{request_id}] Total Time: {elapsed_time:.2f}s")
                    logger.info(f"[{request_id}] ==========================================")
                else:
                    logger.warning(f"[{request_id}] WARNING: Empty response streamed")

        return StreamingResponse(token_stream(), media_type="text/plain")
    
    except HTTPException as e:
        elapsed_time = time.time() - start_time
        logger.error(f"[{request_id}] ========== POST /chat ERROR ==========")
        logger.error(f"[{request_id}] Status: {e.status_code}")
        logger.error(f"[{request_id}] Error Detail: {e.detail}")
        logger.error(f"[{request_id}] Total Time: {elapsed_time:.2f}s")
        logger.error(f"[{request_id}] =======================================")
        raise
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error(f"[{request_id}] ========== POST /chat UNEXPECTED ERROR ==========")
        logger.error(f"[{request_id}] Error Type: {type(e).__name__}")
        logger.error(f"[{request_id}] Error Message: {str(e)}")
        logger.error(f"[{request_id}] Total Time: {elapsed_time:.2f}s")
        logger.error(f"[{request_id}] =================================================")
        raise


@app.post("/stt")
async def stt_endpoint(
    request: Request,
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
    file: UploadFile = File(...),
    language: Optional[str] = Form(default=None),
    session_id: Optional[str] = Form(default=None),
):
    """
    Speech-to-text helper.

    Frontend uploads audio via multipart/form-data. We call OpenAI STT and return the transcript.
    """
    start_time = time.time()
    request_id = f"{int(time.time() * 1000)}-{id(request)}"
    
    # Log request received
    logger.info(f"[{request_id}] ========== POST /stt REQUEST ==========")
    logger.info(f"[{request_id}] Filename: {file.filename}")
    logger.info(f"[{request_id}] Content Type: {file.content_type}")
    logger.info(f"[{request_id}] Language: {language or 'auto-detect'}")
    logger.info(f"[{request_id}] Session ID: {session_id}")
    logger.info(f"[{request_id}] Auth Token Present: {bool(authorization)}")
    
    try:
        _set_backend_token(authorization)

        try:
            audio_bytes = await file.read()
            audio_size = len(audio_bytes)
            logger.info(f"[{request_id}] Audio file size: {audio_size} bytes ({audio_size / 1024:.2f} KB)")
            logger.info(f"[{request_id}] Calling OpenAI Whisper API...")
            
            result = transcribe_audio(audio_bytes, filename=file.filename or "audio.wav", language=language)
            
            elapsed_time = time.time() - start_time
            transcript = result.get("text", "")
            
            logger.info(f"[{request_id}] ========== POST /stt RESPONSE ==========")
            logger.info(f"[{request_id}] Status: 200 OK")
            logger.info(f"[{request_id}] Transcript: {transcript[:200]}...")
            logger.info(f"[{request_id}] Transcript Length: {len(transcript)} characters")
            logger.info(f"[{request_id}] Detected Language: {result.get('language') or language}")
            logger.info(f"[{request_id}] Duration: {result.get('duration', 'N/A')}s")
            logger.info(f"[{request_id}] Total Time: {elapsed_time:.2f}s")
            logger.info(f"[{request_id}] =======================================")
            
            return {
                "ok": True,
                "text": transcript,
                "language": result.get("language") or language,
                "duration": result.get("duration"),
                "segments": result.get("segments"),
                "session_id": session_id,
            }
        except HTTPException:
            raise
        except Exception as exc:
            elapsed_time = time.time() - start_time
            logger.error(f"[{request_id}] ========== POST /stt ERROR ==========")
            logger.error(f"[{request_id}] Error: {str(exc)}")
            logger.error(f"[{request_id}] Total Time: {elapsed_time:.2f}s")
            logger.error(f"[{request_id}] =====================================")
            raise HTTPException(status_code=500, detail=f"Speech-to-text failed: {exc}") from exc
    
    except HTTPException as e:
        elapsed_time = time.time() - start_time
        logger.error(f"[{request_id}] ========== POST /stt ERROR ==========")
        logger.error(f"[{request_id}] Status: {e.status_code}")
        logger.error(f"[{request_id}] Error Detail: {e.detail}")
        logger.error(f"[{request_id}] Total Time: {elapsed_time:.2f}s")
        logger.error(f"[{request_id}] =====================================")
        raise


@app.get("/config")
async def config_endpoint():
    """
    Returns frontend configuration including Google Maps API key if available.
    This endpoint is public (no auth required) as it only returns public config.
    """
    google_maps_key = os.getenv("GOOGLE_API_KEY", "")
    has_key = bool(google_maps_key)
    
    logger.info(f"GET /config - Google Maps API key present: {has_key}")
    
    return {
        "google_maps_api_key": google_maps_key if google_maps_key else None,
        "has_google_maps": has_key,
    }


@app.post("/tts")
async def tts_endpoint(
    request: Request,
    body: TTSRequest,
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
):
    """
    Text-to-speech helper.

    Accepts assistant text and returns audio bytes for playback.
    """
    start_time = time.time()
    request_id = f"{int(time.time() * 1000)}-{id(request)}"
    
    # Log request received
    logger.info(f"[{request_id}] ========== POST /tts REQUEST ==========")
    logger.info(f"[{request_id}] Text Length: {len(body.text)} characters")
    logger.info(f"[{request_id}] Text Preview: {body.text[:200]}...")
    logger.info(f"[{request_id}] Voice: {body.voice or 'alloy (default)'}")
    logger.info(f"[{request_id}] Audio Format: {body.audio_format or 'mp3 (default)'}")
    logger.info(f"[{request_id}] Auth Token Present: {bool(authorization)}")
    
    try:
        _set_backend_token(authorization)

        if not body.text:
            logger.error(f"[{request_id}] ERROR: text is required for TTS")
            raise HTTPException(status_code=400, detail="text is required for TTS.")

        try:
            logger.info(f"[{request_id}] Calling OpenAI TTS API...")
            audio_bytes, content_type = synthesize_speech(
                text=body.text,
                voice=body.voice,
                audio_format=body.audio_format,
            )
            
            audio_size = len(audio_bytes)
            elapsed_time = time.time() - start_time
            
            logger.info(f"[{request_id}] ========== POST /tts RESPONSE ==========")
            logger.info(f"[{request_id}] Status: 200 OK")
            logger.info(f"[{request_id}] Audio Size: {audio_size} bytes ({audio_size / 1024:.2f} KB)")
            logger.info(f"[{request_id}] Content Type: {content_type}")
            logger.info(f"[{request_id}] Total Time: {elapsed_time:.2f}s")
            logger.info(f"[{request_id}] =======================================")
            
            headers = {
                "Content-Disposition": 'inline; filename="speech.{}"'.format((body.audio_format or "mp3").lower())
            }

            return Response(content=audio_bytes, media_type=content_type, headers=headers)
        except HTTPException:
            raise
        except Exception as exc:
            elapsed_time = time.time() - start_time
            logger.error(f"[{request_id}] ========== POST /tts ERROR ==========")
            logger.error(f"[{request_id}] Error: {str(exc)}")
            logger.error(f"[{request_id}] Total Time: {elapsed_time:.2f}s")
            logger.error(f"[{request_id}] =====================================")
            raise HTTPException(status_code=500, detail=f"Text-to-speech failed: {exc}") from exc
    
    except HTTPException as e:
        elapsed_time = time.time() - start_time
        logger.error(f"[{request_id}] ========== POST /tts ERROR ==========")
        logger.error(f"[{request_id}] Status: {e.status_code}")
        logger.error(f"[{request_id}] Error Detail: {e.detail}")
        logger.error(f"[{request_id}] Total Time: {elapsed_time:.2f}s")
        logger.error(f"[{request_id}] =====================================")
        raise


