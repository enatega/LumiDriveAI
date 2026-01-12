from typing import List, Literal, Optional, Dict, Any
import logging
import time
import asyncio
from collections import deque

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
from utils import strip_asterisks
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
            elif tc.function.name == "get_address_from_coordinates":
                from assistant import tool_get_address_from_coordinates
                result = await tool_get_address_from_coordinates(**args)
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
                result = await tool_check_active_ride()
            elif tc.function.name == "book_ride_with_details":
                from assistant import tool_book_ride_with_details, _status_callback
                logger.info(f"DEBUG book_ride_with_details args:")
                logger.info(f"  pickup_place: '{args.get('pickup_place', 'NOT PROVIDED')}'")
                logger.info(f"  dropoff_place: '{args.get('dropoff_place', 'NOT PROVIDED')}'")
                logger.info(f"  ride_type: '{args.get('ride_type', 'NOT PROVIDED')}'")
                logger.info(f"  stops: {args.get('stops', [])}")
                logger.info(f"  Status callback set when calling book_ride_with_details: {_status_callback is not None}")
                print(f"[DEBUG] Status callback set when calling book_ride_with_details: {_status_callback is not None}")
                result = await tool_book_ride_with_details(**args)
                logger.info(f"  book_ride_with_details completed, result ok: {result.get('ok', False)}")
            elif tc.function.name == "auto_book_ride":
                from assistant import tool_auto_book_ride
                result = await tool_auto_book_ride(**args)
            elif tc.function.name == "create_ride_and_wait_for_bids":
                from assistant import tool_create_ride_and_wait_for_bids
                result = await tool_create_ride_and_wait_for_bids(**args)
            elif tc.function.name == "create_request_and_poll":
                from assistant import tool_create_request_and_poll
                result = await tool_create_request_and_poll(**args)
            elif tc.function.name == "set_stops":
                from assistant import tool_set_stops
                result = await tool_set_stops(**args)
            elif tc.function.name == "cancel_ride":
                from assistant import tool_cancel_ride
                result = await tool_cancel_ride(**args)
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

        # Fetch current location from backend API
        from api import get_user_current_location
        from memory_store import set_current_location, get_current_location
        
        location_result = get_user_current_location(timeout=10)
        
        if location_result.get("ok") and location_result.get("location"):
            location_data = location_result["location"]
            current_location = {
                "lat": location_data["lat"],
                "lng": location_data["lng"],
            }
            set_current_location(body.session_id, current_location)
            logger.info(f"[{request_id}] Current location fetched: {location_data['lat']}, {location_data['lng']}")
        else:
            set_current_location(body.session_id, None)
            logger.info(f"[{request_id}] Current location not available: {location_result.get('error', 'Unknown error')}")

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

        # Build system prompt with location context if available
        from memory_store import get_current_location
        
        system_prompt = SYSTEM
        current_location = get_current_location(body.session_id)
        # Only add location context if it's valid (exists, has lat and lng)
        if current_location and isinstance(current_location, dict) and current_location.get("lat") and current_location.get("lng"):
            loc = current_location
            system_prompt += f"\n\nUSER'S CURRENT LOCATION: Coordinates ({loc['lat']}, {loc['lng']}). If the user asks 'What's my current location?' or 'What is my location?', you MUST call get_address_from_coordinates with lat={loc['lat']} and lng={loc['lng']} to convert to a readable address. If the user provides only a dropoff location (e.g., 'Take me to F-6 Markaz'), automatically use this current location as the pickup location. You don't need to ask for pickup - just proceed with booking using the current location. IMPORTANT: When calling book_ride_with_details with current location, DO NOT pass pickup_place parameter at all, or if you must pass it, use the format '{loc['lat']},{loc['lng']}' (lat,lng without spaces or formatting). DO NOT format it as 'Coordinates (lat, lng)' or any other descriptive text."
            
            # Also store in STATE for tool access
            from assistant import STATE
            # Clear any stale STATE data first to prevent cross-session contamination
            STATE["pickup"] = None
            STATE["dropoff"] = None
            STATE["pickup_address"] = None
            STATE["destination_address"] = None
            STATE["pickup_location"] = None
            STATE["dropoff_location"] = None
            STATE["stops"] = []
            STATE["rideTypeName"] = None
            STATE["rideTypeId"] = None
            STATE["customerId"] = None
            STATE["rideRequestId"] = None
            STATE["rideId"] = None
            STATE["sender_phone_number"] = None
            STATE["receiver_phone_number"] = None
            STATE["comments_for_courier"] = None
            STATE["package_size"] = None
            STATE["package_types"] = None
            STATE["current_location"] = current_location
        else:
            # Explicitly set to None if not available - IMPORTANT: Clear any stale location data
            from assistant import STATE
            STATE["current_location"] = None
            # Also clear other STATE fields that might persist from previous sessions
            # Reset STATE to initial values to prevent cross-session contamination
            STATE["pickup"] = None
            STATE["dropoff"] = None
            STATE["pickup_address"] = None
            STATE["destination_address"] = None
            STATE["pickup_location"] = None
            STATE["dropoff_location"] = None
            STATE["stops"] = []
            STATE["rideTypeName"] = None
            STATE["rideTypeId"] = None
            STATE["customerId"] = None
            STATE["rideRequestId"] = None
            STATE["rideId"] = None
            STATE["sender_phone_number"] = None
            STATE["receiver_phone_number"] = None
            STATE["comments_for_courier"] = None
            STATE["package_size"] = None
            STATE["package_types"] = None

        messages = memory_to_openai_messages(memory, system_prompt)
        logger.info(f"[{request_id}] Total messages for OpenAI: {len(messages)}")

        # Set up status callback BEFORE tool execution so we can capture status messages
        import json
        from assistant import set_status_callback, send_status
        status_queue = []  # Simple list for status messages
        
        def status_handler(message: str):
            """Handle status messages by adding them to the queue"""
            status_json = json.dumps({"type": "status", "message": message}) + "\n"
            status_queue.append(status_json)
            logger.info(f"[{request_id}] Status message queued: {message} (queue length: {len(status_queue)})")
            print(f"[DEBUG] Status message queued: {message} (queue length: {len(status_queue)})")
        
        # Set the status callback before any tools are executed
        set_status_callback(status_handler)
        
        # Verify callback was set
        from assistant import _status_callback as check_callback
        logger.info(f"[{request_id}] Status callback verified after setting: {check_callback is not None}")
        print(f"[DEBUG] Status callback verified after setting: {check_callback is not None}, callback id: {id(check_callback)}")

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
            set_status_callback(None)  # Clear callback on error
            raise HTTPException(status_code=502, detail=f"Failed to reach OpenAI: {exc}") from exc

        first_msg = first.choices[0].message
        had_tool_calls = bool(first_msg.tool_calls)
        if had_tool_calls:
            logger.info(f"[{request_id}] Executing {len(first_msg.tool_calls)} tool calls...")
            for tc in first_msg.tool_calls:
                logger.info(f"[{request_id}] Tool Call: {tc.function.name}")
            
            # Verify callback is set before tool execution
            from assistant import _status_callback
            logger.info(f"[{request_id}] Status callback set before tool execution: {_status_callback is not None}")
            print(f"[DEBUG] Status callback set before tool execution: {_status_callback is not None}")
            print(f"[DEBUG] Status queue length before tool execution: {len(status_queue)}")
        
        # Start streaming immediately to yield status messages during tool execution
        # We'll yield status messages as they're generated, then yield content
        
        async def async_token_stream():
            """Async generator that yields status messages immediately during tool execution"""
            seen_messages = set()
            tool_execution_done = False
            tool_execution_error = None
            
            async def run_tools_async():
                """Run tools in background"""
                nonlocal tool_execution_done, tool_execution_error
                try:
                    await _run_tools_for_message(first_msg, messages)
                    tool_execution_done = True
                except Exception as e:
                    tool_execution_error = e
                    tool_execution_done = True
            
            # Start tool execution in background
            tool_task = asyncio.create_task(run_tools_async())
            
            # Yield status messages immediately as they're generated during tool execution
            # Run tool execution and status message yielding concurrently
            # Keep checking until tool is done AND we've waited long enough for any late messages
            last_message_time = time.time()
            max_idle_time = 3.0  # Wait up to 3 seconds after last message before giving up
            
            while not tool_execution_done or status_queue or (time.time() - last_message_time < max_idle_time):
                # Yield any new status messages one at a time with small delay
                if status_queue:
                    status_msg = status_queue.pop(0)
                    try:
                        msg_data = json.loads(status_msg.strip())
                        msg_text = msg_data.get('message', '')
                        if msg_text and msg_text not in seen_messages:
                            seen_messages.add(msg_text)
                            logger.info(f"[{request_id}] Yielding status message immediately: {msg_text}")
                            print(f"[DEBUG] Yielding status message immediately: {msg_text}")
                            yield status_msg
                            last_message_time = time.time()  # Reset timer when we get a message
                            # Delay to allow frontend to display the message before next one
                            await asyncio.sleep(0.3)
                        else:
                            print(f"[DEBUG] Status message already sent, skipping: {msg_text}")
                    except json.JSONDecodeError:
                        yield status_msg
                        last_message_time = time.time()
                        await asyncio.sleep(0.3)
                else:
                    # If queue is empty but tool is still running, check more frequently
                    if not tool_execution_done:
                        await asyncio.sleep(0.05)
                    else:
                        # Tool is done, but continue checking for messages queued during synchronous operations
                        # Check if we've waited long enough without new messages
                        if time.time() - last_message_time >= max_idle_time:
                            logger.info(f"[{request_id}] No new status messages for {max_idle_time}s, exiting status loop")
                            break
                        await asyncio.sleep(0.1)
            
            # Wait for tool execution to complete (in case it hasn't already)
            if not tool_execution_done:
                await tool_task
            if tool_execution_error:
                raise tool_execution_error
            
            # Final check: yield any remaining status messages that might have been queued
            # right as tool execution was completing (race condition handling)
            while status_queue:
                status_msg = status_queue.pop(0)
                try:
                    msg_data = json.loads(status_msg.strip())
                    msg_text = msg_data.get('message', '')
                    if msg_text and msg_text not in seen_messages:
                        seen_messages.add(msg_text)
                        logger.info(f"[{request_id}] Yielding final status message: {msg_text}")
                        print(f"[DEBUG] Yielding final status message: {msg_text}")
                        yield status_msg
                        # Delay to allow frontend to display the message
                        await asyncio.sleep(0.3)
                except json.JSONDecodeError:
                    yield status_msg
                    await asyncio.sleep(0.3)
            
            # Check callback and queue after waiting for status messages
            from assistant import _status_callback
            logger.info(f"[{request_id}] Status callback set after tool execution: {_status_callback is not None}")
            logger.info(f"[{request_id}] Status queue length after waiting: {len(status_queue)}")
            print(f"[DEBUG] Status callback set after tool execution: {_status_callback is not None}")
            print(f"[DEBUG] Status queue length after waiting: {len(status_queue)}")
            if status_queue:
                print(f"[DEBUG] Remaining status queue contents: {[json.loads(msg.strip()).get('message', '') for msg in status_queue]}")
            
            try:
                logger.info(f"[{request_id}] Calling OpenAI API (streaming response)...")
                # If there were tool calls, _run_tools_for_message already added the assistant message
                # with tool_calls and tool responses to messages. Only add assistant message if there
                # were no tool calls.
                if had_tool_calls:
                    stream_messages = messages
                else:
                    # No tool calls, so add the assistant message with its content
                    stream_messages = messages + [{"role": "assistant", "content": first_msg.content or ""}]
                stream = client.chat.completions.create(
                    model=MODEL,
                    messages=stream_messages,
                    stream=True,
                )
                logger.info(f"[{request_id}] OpenAI streaming started")
            except Exception as exc:
                logger.error(f"[{request_id}] ERROR: Failed to stream OpenAI response: {exc}")
                set_status_callback(None)  # Clear callback on error
                raise HTTPException(status_code=502, detail=f"Failed to stream OpenAI response: {exc}") from exc
            
            # Then stream the normal content
            final_chunks: List[str] = []
            chunk_count = 0
            
            try:
                for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        # Strip asterisks from each chunk as it's streamed
                        cleaned_content = strip_asterisks(delta.content)
                        final_chunks.append(cleaned_content)
                        chunk_count += 1
                        # Only yield content if it's not empty
                        if cleaned_content:
                            # Yield as content type JSON
                            yield json.dumps({"type": "content", "text": cleaned_content}) + "\n"
                    
                    # Check for new status messages while streaming (interleave them)
                    while status_queue:
                        status_msg = status_queue.pop(0)
                        try:
                            msg_data = json.loads(status_msg.strip())
                            msg_text = msg_data.get('message', '')
                            if msg_text and msg_text not in seen_messages:
                                seen_messages.add(msg_text)
                                logger.info(f"[{request_id}] Yielding status message during stream: {msg_text}")
                                print(f"[DEBUG] Yielding status message during stream: {msg_text}")
                                yield status_msg
                            else:
                                print(f"[DEBUG] Status message already sent during stream, skipping: {msg_text}")
                        except json.JSONDecodeError:
                            yield status_msg
            finally:
                # Clear status callback
                set_status_callback(None)
                
                final_text = "".join(final_chunks).strip()
                # Strip asterisks from final text before saving to memory
                final_text = strip_asterisks(final_text)
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
        
        return StreamingResponse(async_token_stream(), media_type="text/plain")
    
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


