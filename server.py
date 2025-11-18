import os
from typing import List, Literal, Optional, Dict, Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api import set_token
from assistant import (
    SYSTEM,
    MODEL,
    client,
    tools,
    call_tool,
)
import json


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    messages: List[ChatMessage]


app = FastAPI(title="LumiDrive Assistant API")


def _openai_messages_from_request(req: ChatRequest) -> List[Dict[str, Any]]:
    """
    Convert incoming ChatRequest into OpenAI chat format.
    We always inject our own SYSTEM message at the start, then replay the rest.
    """
    msgs: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM}]
    for m in req.messages:
        base = {"role": m.role, "content": m.content}
        if m.role == "tool":
            # OpenAI expects name + tool_call_id for tool messages
            if m.name:
                base["name"] = m.name
            if m.tool_call_id:
                base["tool_call_id"] = m.tool_call_id
        msgs.append(base)
    return msgs


def _run_tools_for_message(msg, messages: List[Dict[str, Any]]) -> None:
    """
    Execute any tool calls in msg and append their outputs to messages.
    This mirrors the logic in assistant.chat_loop but without CLI I/O.
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
            # all tool_* functions are defined in assistant.py
            result = eval(f"tool_{tc.function.name}")(**args)
        except TypeError as e:
            result = {"ok": False, "error": f"tool_{tc.function.name} invocation error", "details": str(e)}
        except NameError:
            result = call_tool(tc.function.name, args)

        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "name": tc.function.name,
            "content": json.dumps(result),
        })


@app.post("/chat")
async def chat_endpoint(
    body: ChatRequest,
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
):
    """
    Chat endpoint for the LumiDrive assistant.

    - Expects full conversation array in `body.messages`.
    - Uses the Bearer token from the Authorization header to talk to the rides backend.
    - Streams the final assistant reply back to the caller.
    """
    # 1) Extract and set backend token (per-request, dynamic)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty bearer token.")
    set_token(token)

    # 2) Prepare messages for OpenAI (inject our system prompt)
    messages = _openai_messages_from_request(body)

    # 3) First turn: allow tools (non-streaming)
    first = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=[{"type": "function", "function": t["function"]} for t in tools],
        tool_choice="auto",
    )
    first_msg = first.choices[0].message

    # 4) Run tools (if any), append tool outputs
    _run_tools_for_message(first_msg, messages)

    # 5) Second turn: ask model to respond with all context; stream tokens
    stream = client.chat.completions.create(
        model=MODEL,
        messages=messages + [{"role": "assistant", "content": first_msg.content or ""}],
        stream=True,
    )

    async def token_stream():
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    return StreamingResponse(token_stream(), media_type="text/plain")


