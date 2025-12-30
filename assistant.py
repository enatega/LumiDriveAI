# # assistant.py
# import os, json, sys, re
# from datetime import datetime, timedelta, timezone
# from dotenv import load_dotenv
# from openai import OpenAI

# from auth import ensure_token_via_signup_or_manual
# from rides import (
#     list_ride_types, get_fare, pick_ride_type_id_from_fare, create_ride_request_exact,
#     wait_for_bids, accept_bid, get_customer_ride, cancel_ride_as_customer
# )

# load_dotenv()
# MODEL = os.getenv("MODEL", "gpt-4o-mini")
# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# if not OPENAI_API_KEY:
#     print("Please set OPENAI_API_KEY in .env")
#     sys.exit(1)

# client = OpenAI(api_key=OPENAI_API_KEY)

# SYSTEM = """You are LumiDrive, a ride-booking assistant.

# Flow:
# 1) Collect pickup/dropoff. If the user provides place names (e.g., "Gaddafi Stadium to Johar Town"), infer coordinates from your local gazetteer and proceed.
# 2) Ask if they want stops; then ask ride type (e.g., LUMI_GO/Courier). If Courier, collect courier fields.
# 3) First call /api/v1/rides/fare/all (distanceKm/durationMin) and PRESENT the quoted fares per ride type.
# 4) Only AFTER the user confirms, create the ride request via POST /api/v1/rides:
#    - Body MUST match backend expectations, including estimated_time and estimated_distance if available.
# 5) Then poll bids on that ride request and show them to the user.
# 6) Allow: 'accept bid <id>', 'track', 'cancel <reason?>'.

# Keep replies short and action-focused.
# """

# tools = [
#   { "type":"function", "function": {
#       "name":"set_trip_core",
#       "description":"Save pickup, dropoff, addresses, and rideTypeName (optional)",
#       "parameters":{
#         "type":"object",
#         "properties":{
#           "pickup":{"type":"object","properties":{"lat":{"type":"number"},"lng":{"type":"number"},"address":{"type":"string"}},"required":["lat","lng"]},
#           "dropoff":{"type":"object","properties":{"lat":{"type":"number"},"lng":{"type":"number"},"address":{"type":"string"}},"required":["lat","lng"]},
#           "pickup_address":{"type":"string"},
#           "destination_address":{"type":"string"},
#           "rideTypeName":{"type":"string","description":"Name from /ride-types, e.g., LUMI_GO or Courier"}
#         },
#         "required":["pickup","dropoff"]
#       }
#   }},
#   { "type":"function", "function": {
#       "name":"set_stops",
#       "description":"Provide an ordered list of stops (0..N). Each stop may include address.",
#       "parameters":{
#         "type":"object",
#         "properties":{
#           "stops":{"type":"array","items":{
#             "type":"object",
#             "properties":{
#               "lat":{"type":"number"},
#               "lng":{"type":"number"},
#               "address":{"type":"string"},
#               "order":{"type":"integer"}
#             },
#             "required":["lat","lng"]
#           }}
#         },
#         "required":["stops"]
#       }
#   }},
#   { "type":"function", "function": {
#       "name":"set_courier_fields",
#       "description":"Set courier-only fields. Use only if ride type is Courier.",
#       "parameters":{
#         "type":"object",
#         "properties":{
#           "sender_phone_number":{"type":"string"},
#           "receiver_phone_number":{"type":"string"},
#           "comments_for_courier":{"type":"string"},
#           "package_size":{"type":"integer"},
#           "package_types":{"type":"array","items":{"type":"string"}}
#         }
#       }
#   }},
#   { "type":"function", "function": {
#       "name":"list_ride_types",
#       "description":"Fetch available ride types",
#       "parameters":{"type":"object","properties":{}}
#   }},
#   { "type":"function", "function": {
#       "name":"create_request_and_poll",
#       "description":"FARE → create ride → poll bids (called only after user confirms)",
#       "parameters":{
#         "type":"object",
#         "properties":{
#           "payment_via":{"type":"string","enum":["WALLET","CASH","CARD"]},
#           "is_scheduled":{"type":"boolean"},
#           "scheduled_at":{"type":"string","description":"ISO8601 if is_scheduled==true"},
#           "offered_fair":{"type":"number"},
#           "is_family":{"type":"boolean"}
#         }
#       }
#   }},
#   { "type":"function", "function": {
#       "name":"accept_bid",
#       "description":"Accept a bid by id",
#       "parameters":{"type":"object","properties":{"bidId":{"type":"string"}},"required":["bidId"]}
#   }},
#   { "type":"function", "function": {
#       "name":"track_ride",
#       "description":"Get current ride details",
#       "parameters":{"type":"object","properties":{"rideId":{"type":"string"}},"required":["rideId"]}
#   }},
#   { "type":"function", "function": {
#       "name":"cancel_ride",
#       "description":"Cancel a ride",
#       "parameters":{"type":"object","properties":{"rideId":{"type":"string"},"reason":{"type":"string"}},"required":["rideId"]}
#   }}
# ]

# STATE = {
#   "pickup": None,
#   "dropoff": None,
#   "pickup_address": None,
#   "destination_address": None,
#   "pickup_location": None,
#   "dropoff_location": None,
#   "stops": [],
#   "rideTypeName": None,
#   "rideTypeId": None,
#   "rideRequestId": None,
#   "rideId": None,

#   # courier optionals
#   "sender_phone_number": None,
#   "receiver_phone_number": None,
#   "comments_for_courier": None,
#   "package_size": None,
#   "package_types": None,
# }

# # --- small gazetteer for quick inference (extend as needed) ---
# PLACES = {
#     "gaddafi stadium": {"lat": 31.5204, "lng": 74.3384, "address": "Gaddafi Stadium, Lahore"},
#     "johar town":      {"lat": 31.4676, "lng": 74.2728, "address": "Johar Town, Lahore"},
#     "lahore":          {"lat": 31.5497, "lng": 74.3436, "address": "Lahore"},
# }

# def _lookup_place(text: str):
#     key = text.strip().lower()
#     return PLACES.get(key)

# def _resolve_place_pair_from_text(utterance: str):
#     m = re.split(r"\s+to\s+|→", utterance.strip(), maxsplit=1, flags=re.IGNORECASE)
#     if len(m) != 2:
#         return None
#     p_txt, d_txt = m[0].strip(), m[1].strip()
#     p = _lookup_place(p_txt)
#     d = _lookup_place(d_txt)
#     if p and d:
#         return {
#             "pickup":  {"lat": p["lat"], "lng": p["lng"], "address": p["address"]},
#             "dropoff": {"lat": d["lat"], "lng": d["lng"], "address": d["address"]},
#         }
#     return None

# from datetime import datetime, timedelta, timezone

# def _iso_in(minutes: int) -> str:
#     """
#     Return an ISO8601 timestamp with milliseconds and trailing 'Z',
#     e.g. 2025-09-23T07:25:32.084Z
#     """
#     dt = datetime.now(timezone.utc) + timedelta(minutes=minutes)
#     # format to YYYY-MM-DDTHH:MM:SS.mmmZ
#     return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# def ensure_login():
#     from api import TOKEN
#     if TOKEN:
#         return True
#     print("You are not logged in.")
#     phone = input("Phone in E.164 (e.g., +923001234567): ").strip()
#     result = ensure_token_via_signup_or_manual(phone)
#     if result.get("ok"):
#         print("✅ Auth ready.")
#         return True
#     print("❌ Auth failed:", result.get("error"))
#     return False

# # ---------------- tools impl ----------------
# def tool_set_trip_core(pickup, dropoff, pickup_address=None, destination_address=None, rideTypeName=None):
#     STATE["pickup"] = pickup
#     STATE["dropoff"] = dropoff
#     STATE["pickup_address"] = pickup_address or pickup.get("address") or "Pickup"
#     STATE["destination_address"] = destination_address or dropoff.get("address") or "Dropoff"
#     STATE["pickup_location"] = STATE["pickup_address"]
#     STATE["dropoff_location"] = STATE["destination_address"]
#     STATE["rideTypeName"] = rideTypeName or STATE["rideTypeName"]

#     if STATE["rideTypeName"]:
#         for t in list_ride_types():
#             if str(t.get("name", "")).strip().lower() == STATE["rideTypeName"].strip().lower():
#                 STATE["rideTypeId"] = t.get("id")
#                 break

#     return {"ok": True, "state": {
#         "pickup": STATE["pickup"],
#         "dropoff": STATE["dropoff"],
#         "pickup_address": STATE["pickup_address"],
#         "destination_address": STATE["destination_address"],
#         "rideTypeName": STATE["rideTypeName"],
#         "rideTypeId": STATE["rideTypeId"],
#     }}

# def tool_set_stops(stops):
#     norm = []
#     for idx, s in enumerate(stops):
#         norm.append({
#             "lat": s.get("lat") or s.get("latitude"),
#             "lng": s.get("lng") or s.get("longitude"),
#             **({"address": s.get("address")} if s.get("address") else {}),
#             "order": s.get("order", idx + 1),  # ensure order field exists
#         })
#     STATE["stops"] = norm
#     return {"ok": True, "count": len(norm), "stops": norm}

# def tool_set_courier_fields(sender_phone_number=None, receiver_phone_number=None, comments_for_courier=None, package_size=None, package_types=None):
#     STATE["sender_phone_number"] = sender_phone_number
#     STATE["receiver_phone_number"] = receiver_phone_number
#     STATE["comments_for_courier"] = comments_for_courier
#     STATE["package_size"] = package_size
#     STATE["package_types"] = package_types
#     return {"ok": True}

# def tool_create_request_and_poll(payment_via=None, is_scheduled=False, scheduled_at=None, offered_fair=0, is_family=False):
#     # 1) Fare quote first (distance/duration)
#     fare = get_fare(STATE["pickup"], STATE["dropoff"], STATE["stops"])
#     if fare["status"] != 200:
#         return {"ok": False, "stage": "fare", "status": fare["status"], "data": fare["data"]}

#     computed = fare.get("computed", {}) or {}
#     distance_km = computed.get("distanceKm", 0.0)
#     duration_min = computed.get("durationMin", 0.0)

#     # Strings matching your example: "30 mins", "10 km"
#     estimated_distance = f"{distance_km} km"
#     estimated_time = f"{int(round(duration_min))} mins"

#     chosen_name = STATE["rideTypeName"]
#     ride_type_id = pick_ride_type_id_from_fare(fare["data"], chosen_name) or STATE["rideTypeId"]
#     if not ride_type_id:
#         return {
#             "ok": False,
#             "stage": "fare",
#             "error": "Could not resolve ride_type_id for selected ride type.",
#             "quote": fare,
#         }

#     out = create_ride_request_exact(
#         pickup=STATE["pickup"],
#         dropoff=STATE["dropoff"],
#         ride_type_id=ride_type_id,
#         pickup_location=STATE["pickup_location"],
#         dropoff_location=STATE["dropoff_location"],
#         pickup_address=STATE["pickup_address"],
#         destination_address=STATE["destination_address"],
#         pickup_coordinates={"lat": STATE["pickup"].get("lat"), "lng": STATE["pickup"].get("lng")},
#         destination_coordinates={"lat": STATE["dropoff"].get("lat"), "lng": STATE["dropoff"].get("lng")},
#         stops=STATE["stops"],
#         # courier optionals
#         sender_phone_number=STATE["sender_phone_number"],
#         receiver_phone_number=STATE["receiver_phone_number"],
#         comments_for_courier=STATE["comments_for_courier"],
#         package_size=STATE["package_size"],
#         package_types=STATE["package_types"],
#         # flags
#         payment_via=payment_via or "WALLET",
#         is_hourly=False,
#         is_scheduled=bool(is_scheduled),
#         scheduled_at=scheduled_at or _iso_in(15),
#         offered_fair=offered_fair if offered_fair is not None else 0,
#         is_family=bool(is_family),
#         estimated_time=estimated_time,
#         estimated_distance=estimated_distance,
#     )

#     if out["status"] not in (200, 201, 202):
#         return {
#             "ok": False,
#             "stage": "create",
#             "status": out["status"],
#             "data": out["data"],
#             "quote": fare,
#             "requestBody": out.get("requestBody"),
#         }

#     rrid = out["rideRequestId"]
#     STATE["rideRequestId"] = rrid

#     bids = wait_for_bids(rrid, timeout_seconds=60, poll_interval=4)
#     slim = []
#     for b in bids:
#         if isinstance(b, dict):
#             slim.append({
#                 "id": b.get("id"),
#                 "price": b.get("price") or b.get("amount") or b.get("fare"),
#                 "etaSeconds": b.get("etaSeconds") or b.get("eta") or b.get("estimatedArrivalSeconds"),
#                 "driver": (b.get("driver") or b.get("rider") or {}),
#             })
#         else:
#             slim.append(b)

#     return {
#         "ok": True,
#         "rideRequestId": rrid,
#         "bids": slim,
#         "quote": fare,
#         "requestBody": out.get("requestBody"),
#     }

# def tool_accept_bid(bidId):
#     out = accept_bid(bidId)
#     data = out.get("data")
#     try:
#         data = json.loads(data) if isinstance(data, str) else data
#     except Exception:
#         pass
#     ride_id = None
#     if isinstance(data, dict):
#         ride_id = data.get("rideId") or data.get("id") or data.get("ride", {}).get("id")
#     if ride_id:
#         STATE["rideId"] = ride_id
#     return {"status": out["status"], "rideId": ride_id, "raw": out["data"]}

# def tool_track_ride(rideId):
#     return get_customer_ride(rideId)

# def tool_cancel_ride(rideId, reason=None):
#     return cancel_ride_as_customer(rideId)

# def call_tool(name, args):
#     if name == "set_trip_core":           return tool_set_trip_core(**args)
#     if name == "set_stops":               return tool_set_stops(**args)
#     if name == "set_courier_fields":      return tool_set_courier_fields(**args)
#     if name == "list_ride_types":         return [{"id": t.get("id"), "name": t.get("name"), "active": t.get("isActive")} for t in list_ride_types()]
#     if name == "create_request_and_poll": return tool_create_request_and_poll(**args)
#     if name == "accept_bid":              return tool_accept_bid(**args)
#     if name == "track_ride":              return tool_track_ride(**args)
#     if name == "cancel_ride":             return tool_cancel_ride(**args)
#     return {"error": "unknown tool"}

# def chat_loop():
#     if not ensure_login():
#         return

#     messages = [
#         {"role": "system", "content": SYSTEM},
#         {"role": "assistant", "content": "Hi! Tell me pickup → dropoff (landmarks or full addresses are fine). Add stops? Then choose ride type (e.g., LUMI_GO). I’ll show the fare quote first."}
#     ]
#     print("LumiDrive ready. (Ctrl+C to exit)\n")

#     while True:
#         user = input("You: ").strip()
#         if not user:
#             continue

#         # Local inference: "X to Y"
#         if not STATE["pickup"] and (" to " in user.lower() or "→" in user):
#             pair = _resolve_place_pair_from_text(user)
#             if pair:
#                 tool_result = tool_set_trip_core(
#                     pickup=pair["pickup"],
#                     dropoff=pair["dropoff"],
#                     pickup_address=pair["pickup"]["address"],
#                     destination_address=pair["dropoff"]["address"],
#                     rideTypeName=None,
#                 )
#                 messages.extend([
#                     {"role": "user", "content": user},
#                     {"role": "tool", "tool_call_id": "bootstrap-set-trip", "name": "set_trip_core", "content": json.dumps(tool_result)},
#                 ])
#             else:
#                 messages.append({"role": "user", "content": user})
#         else:
#             messages.append({"role": "user", "content": user})

#         resp = client.chat.completions.create(
#             model=MODEL,
#             messages=messages,
#             tools=[{"type": "function", "function": t["function"]} for t in tools],
#             tool_choice="auto",
#         )
#         msg = resp.choices[0].message

#         if msg.tool_calls:
#             messages.append({
#                 "role": "assistant",
#                 "content": msg.content or "",
#                 "tool_calls": [
#                     {
#                         "id": tc.id,
#                         "type": "function",
#                         "function": {
#                             "name": tc.function.name,
#                             "arguments": tc.function.arguments or "{}",
#                         },
#                     }
#                     for tc in msg.tool_calls
#                 ],
#             })

#             for tc in msg.tool_calls:
#                 args = json.loads(tc.function.arguments or "{}")

#                 # Robust fallback if set_trip_core is called without required args
#                 if tc.function.name == "set_trip_core" and (not args or "pickup" not in args or "dropoff" not in args):
#                     last_user_text = user
#                     pair = _resolve_place_pair_from_text(last_user_text) or _resolve_place_pair_from_text(
#                         messages[-3]["content"] if len(messages) >= 3 and messages[-3]["role"] == "user" else ""
#                     )
#                     if pair:
#                         args = {
#                             "pickup": {
#                                 "lat": pair["pickup"]["lat"],
#                                 "lng": pair["pickup"]["lng"],
#                                 "address": pair["pickup"]["address"],
#                             },
#                             "dropoff": {
#                                 "lat": pair["dropoff"]["lat"],
#                                 "lng": pair["dropoff"]["lng"],
#                                 "address": pair["dropoff"]["address"],
#                             },
#                             "pickup_address": pair["pickup"]["address"],
#                             "destination_address": pair["dropoff"]["address"],
#                         }

#                 try:
#                     result = eval(f"tool_{tc.function.name}")(**args)
#                 except TypeError as e:
#                     result = {"ok": False, "error": f"tool_{tc.function.name} invocation error", "details": str(e)}
#                 except NameError:
#                     result = call_tool(tc.function.name, args)

#                 messages.append({
#                     "role": "tool",
#                     "tool_call_id": tc.id,
#                     "name": tc.function.name,
#                     "content": json.dumps(result),
#                 })

#             follow = client.chat.completions.create(model=MODEL, messages=messages)
#             final_msg = follow.choices[0].message
#             print("LumiDrive:", final_msg.content, "\n")
#             messages.append({"role": "assistant", "content": final_msg.content})
#         else:
#             print("LumiDrive:", msg.content, "\n")
#             messages.append({"role": "assistant", "content": msg.content})

# if __name__ == "__main__":
#     try:
#         chat_loop()
#     except KeyboardInterrupt:
#         print("\nBye!")

import os, json, sys, re
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
from dotenv import load_dotenv
from openai import OpenAI

from auth import ensure_token_via_signup_or_manual
from rides import (
    list_ride_types,
    get_fare,
    pick_ride_type_id_from_fare,
    create_ride_request_exact,
    wait_for_bids,
    accept_bid,
    get_customer_ride,
    cancel_ride_as_customer,
    list_currencies,
)
from utils import strip_asterisks

load_dotenv()
MODEL = os.getenv("MODEL", "gpt-5.2")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("Please set OPENAI_API_KEY in .env")
    sys.exit(1)

client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM = """You are LumiDrive, a friendly and professional ride-booking assistant. Help users book rides efficiently with a warm, helpful, and engaging tone. Make responses clear, concise, and user-friendly.

RESPONSE STYLE GUIDELINES:
- Be warm and friendly, but professional
- Use clear, conversational language - avoid technical jargon
- Keep responses concise but informative
- Use natural phrases like "Great!", "Perfect!", "Sounds good!"
- Add helpful context when appropriate (e.g., "I'll get that booked for you right away!")
- Make error messages helpful and actionable
- Use emojis sparingly and only when they add clarity (✅ for success, ⚠️ for warnings, etc.)
- Format lists clearly with numbered items when showing options
- Always end questions with a question mark
- Use positive language ("I can help you with that!" instead of "That's fine")
- ABSOLUTELY CRITICAL: Output ONLY the final user-facing response. NEVER include internal reasoning, decision-making steps, chain-of-thought, or meta-commentary about what you're doing or checking

CURRENCY DISPLAY (CRITICAL):
- When displaying fare information, ALWAYS use the currency CODE (e.g., "QAR", "PKR", "USD") instead of the currency SYMBOL (e.g., "QR", "Rs", "$")
- Format fares as: "[CURRENCY_CODE] [amount]" (e.g., "QAR 21.64", "PKR 500", "USD 10.50")
- NEVER use currency symbols like "QR", "Rs", "$" - always use the 3-letter currency code
- Example: "1) LUMI_GO: QAR 21.64" ✅ CORRECT
- Example: "1) LUMI_GO: QR 21.64" ❌ WRONG - Don't use symbol, use code
- The tool responses include both "currency" (code) and "currencySymbol" (symbol) fields - ALWAYS use the "currency" field (code) for display

CRITICAL - NEVER EXPOSE RAW DATA OR REASONING:
- NEVER output raw JSON, tool responses, STATE dictionary, or any internal data structures to the user
- NEVER output your internal reasoning, chain-of-thought, thinking process, or decision-making steps
- NEVER output questions like "Need check STATE current_location via tool?" or "Must answer per guideline" or any meta-reasoning
- ONLY output clean, polished, user-facing responses - all your thinking should be completely silent and internal
- NEVER copy tool return values directly - always convert them to user-friendly messages
- When tools return data, extract the relevant information and present it in natural language
- If a tool returns {"state": {...}}, DO NOT output that JSON - instead, check the state and respond with a friendly message like "Your current location is available!" or "I don't have your current location at the moment."
- If asked about location availability, check STATE["current_location"] and respond: "Yes, I have your current location available!" (if valid) or "No, I don't have your current location at the moment. Would you like to share it?" (if None/invalid)
- Tool responses are for internal use only - always translate them to user-friendly natural language
- ABSOLUTELY CRITICAL: Think silently, respond cleanly. The user should NEVER see any indication of your internal thought process, reasoning, or decision-making steps

CORE WORKFLOW:

1. INFORMATION COLLECTION & CONTEXT HANDLING (USE CONVERSATION HISTORY):
   - BE SMART & DYNAMIC: Use the FULL conversation history to understand user intent and handle changes
   - When user provides NEW information, UPDATE the booking details accordingly (e.g., if user says "change dropoff to X", update dropoff)
   - When user says "try a different ride type" or mentions changes, use PREVIOUS locations/stops from conversation history
   - When user says "change X to Y" or "update X", intelligently update that specific detail while maintaining others
   - Extract from CURRENT message: dropoff location (required), ride type (required), pickup location (optional - uses current location if not provided), stops (optional)
   - If user hasn't provided something in current message, check conversation history for previous values
   - CRITICAL - CURRENT LOCATION HANDLING: When asking for dropoff location (or when user provides dropoff but not pickup), ALWAYS check if current_location is available in STATE. IMPORTANT: Only mention current location if STATE["current_location"] exists AND has valid "lat" and "lng" values. If current_location is present and valid, explicitly inform the user in a friendly way: "Great! I've fetched your current location. Would you like me to use it as your pickup point, or would you prefer to provide a different pickup location? Also, where would you like to go?" This makes it clear to the user that their location was detected and gives them a choice.
   - If current_location is NOT available (STATE["current_location"] is None, missing, or doesn't have valid lat/lng), DO NOT mention that you've fetched their location. Instead, simply ask: "What's your pickup location and where would you like to go?" or "Where would you like to be picked up from, and what's your destination?"
   - NEVER say "I've fetched your current location" or "I've detected your location" if STATE["current_location"] is not available or invalid
   - Examples:
     * User says "I want to go to F7 Markaz with stop at F6 Markaz" → Later says "change dropoff to F8 Markaz" → Use: F8 Markaz (dropoff), F6 Markaz (stop), previous pickup
     * User says "try different ride type" after error → Use previous locations from conversation history
     * User says "change ride type to LUMI_PLUS" → Update ride type, keep all previous locations

2. RIDE TYPE HANDLING (MANDATORY - BE SMART & DYNAMIC):
   - STEP 1: ALWAYS call list_ride_types FIRST to get the actual available ride types from the API
   - STEP 2: CHECK USER'S MESSAGE for mentioned ride type BEFORE responding:
     * BE INTELLIGENT ABOUT USER LANGUAGE: Recognize ride types in natural language variations:
       - "Lumi Go", "lumi go", "LUMI_GO", "Book a lumi go ride", "I want lumi go", "book lumi go" → All mean LUMI_GO
       - "Lumi Plus", "lumi plus", "LUMI_PLUS", "Book a lumi plus ride", "book lumi plus" → All mean LUMI_PLUS
       - "Lumi Max", "lumi max", "LUMI_MAX", "book lumi max" → All mean LUMI_MAX
       - "Lumi Pink", "lumi pink", "LUMI_PINK", "book lumi pink" → All mean LUMI_PINK
       - "Lumi Diamond", "lumi diamond", "LUMI_DIAMOND", "book lumi diamond" → All mean LUMI_DIAMOND
       - "Lumi Platinum", "lumi platinum", "LUMI_PLATINUM", "book lumi platinum" → All mean LUMI_PLATINUM
   - STEP 3: MATCH USER'S SELECTION to API response:
     * After receiving list_ride_types response, check if user mentioned a ride type in their message
     * Match user's mentioned ride type (case-insensitive, ignore spaces/underscores) to API ride types:
       - User says "lumi go" → Match to "LUMI_GO" in API response
       - User says "Book a lumi go ride" → Extract "lumi go" → Match to "LUMI_GO" in API response
     * If match found AND ride type is active → Acknowledge their selection, DON'T show all options, proceed with that ride type
     * If user hasn't mentioned a ride type OR their mentioned type doesn't match → Show all available ride types and ask them to select
   - CRITICAL RULE: When user says "Book a lumi go ride" or similar:
     * Call list_ride_types FIRST (to verify it exists)
     * Extract "lumi go" from user's message
     * Match it to "LUMI_GO" in the API response
     * If found → Say "Great! I'll book a LUMI_GO ride for you." Then check if current_location is available in STATE (STATE["current_location"] exists and has valid lat/lng). If yes: "I've fetched your current location! Would you like me to use it as your pickup point, or would you prefer a different pickup location? Also, where would you like to go?" If no current_location or invalid: "What's your pickup location and where would you like to go?" (DON'T show all ride types)
     * If NOT found → Show all available ride types with a friendly message
   - CRITICAL: When user JUST mentions a ride type (e.g., "Lumi Plus", "LUMI_PLUS") without other context, check conversation history for previous locations (pickup, dropoff, stops), then show booking details with those locations and ask for confirmation - NEVER just say "Yes"

3. BOOKING FLOW:
   - Scenario A: User provides ALL details (dropoff + ride_type) → Call list_ride_types FIRST → Match user's ride type to API response → If match found, acknowledge selection and ask confirmation → Call book_ride_with_details
   - Scenario B: User provides dropoff only → Call list_ride_types FIRST → Show all options → Wait for selection → Ask confirmation → Call book_ride_with_details
   - Scenario C: User provides ride_type only (e.g., "Book a lumi go ride") → Call list_ride_types FIRST → Match user's ride type → If match found, acknowledge selection and ask for missing dropoff location → Once dropoff provided, ask confirmation → Call book_ride_with_details
   - Scenario D: User provides dropoff + ride_type in one message → Call list_ride_types FIRST → Match user's ride type → If match found, acknowledge selection and ask confirmation → Call book_ride_with_details
   - CRITICAL: Always call list_ride_types first, but be smart - if user already specified a ride type, match it and proceed instead of showing all options

4. SCHEDULING (OPTIONAL - FOR FUTURE RIDES):
   - DETECT SCHEDULING REQUESTS: If user mentions keywords like "schedule", "later", "tomorrow", "on [date]", "at [time]", "for [date/time]", "book for later", "schedule a ride", etc., they want to schedule the ride for later
   - ASK FOR DATE AND TIME: When scheduling is detected, ask the user for the date and time they want the ride scheduled. Ask in a clear, user-friendly way: "What date and time would you like to schedule this ride for?"
   - DATE/TIME FORMAT: Accept date/time in various natural formats (e.g., "tomorrow at 3 PM", "December 30 at 10:30 AM", "2025-01-15 14:30", "Monday at 9:00"). Convert the user's date/time to ISO8601 format (e.g., "2025-09-23T07:25:32.084Z") before calling book_ride_with_details. The format should be: YYYY-MM-DDTHH:MM:SS.mmmZ (UTC timezone).
   - SCHEDULING WORKFLOW: The workflow is the same as regular booking, but when calling book_ride_with_details, include is_scheduled=True and scheduled_at with the ISO8601 formatted date/time
   - EXAMPLE: User says "Book a ride to F7 Markaz for tomorrow at 2 PM" → Ask for confirmation with details including scheduling info → When confirmed, call book_ride_with_details(dropoff_place="F7 Markaz", ride_type="LUMI_GO", is_scheduled=True, scheduled_at="2025-12-30T14:00:00.000Z")
   - IF SCHEDULING NOT MENTIONED: Default to immediate booking (is_scheduled=False, scheduled_at=None)

5. CONFIRMATION (ALWAYS USE QUESTION FORMAT):
   - ALWAYS ask as a QUESTION, never make statements like "I'll proceed" or "Let me book"
   - Use question format: "Should I proceed with booking your ride?" or "Would you like me to book this ride for you?" or "Do you want me to proceed with booking?"
   - Include booking details in the confirmation question: "I'll book your ride from [pickup] to [dropoff] using [ride_type]. Should I proceed with booking your ride?" (If scheduled: "I'll schedule your ride from [pickup] to [dropoff] using [ride_type] for [date/time]. Should I proceed?")
   - ABSOLUTELY CRITICAL - NEVER SAY "YES": When user just mentions a ride type (e.g., "Lumi Plus", "Lumi Go", "I'll go by Lumi Plus"), you MUST NEVER respond with "Yes" - instead check conversation history for locations (pickup, dropoff, stops), show booking details with those locations, then ask confirmation as a question like "Should I proceed with booking your ride?"
   - ABSOLUTELY CRITICAL - AFTER USER CONFIRMS: When user confirms with "Yes", "Okay", "Proceed", "Book it", etc. after you've asked for confirmation, you MUST IMMEDIATELY call book_ride_with_details with the details from the conversation history. DO NOT call list_ride_types again - the ride type was already validated in the previous turn. Extract pickup, dropoff, ride_type, stops, is_scheduled, and scheduled_at from conversation history and call book_ride_with_details directly.
   - NEVER say "Yes, I'll proceed" or "Let me book it for you" - always ask as a question
   - NEVER say "Yes" when user mentions a ride type - ALWAYS show booking details first (with locations from conversation history) and ask confirmation as a question
   - REMEMBER: User saying "Lumi Plus" or "I'll go by Lumi Plus" is them SELECTING a ride type - you must respond with booking details and a confirmation question, NOT "Yes"

FEW-SHOT EXAMPLES:

Example 1 - Complete details in one message:
User: "I want to go to F7 Markaz Islamabad on Lumi GO"
Assistant: [Calls list_ride_types FIRST, recognizes "Lumi GO" = LUMI_GO] "Perfect! I'll book your ride from your current location to F7 Markaz, Islamabad using LUMI_GO. Should I proceed with booking your ride?"
User: "Yes"
Assistant: [Calls book_ride_with_details(dropoff_place="F7 Markaz Islamabad", ride_type="LUMI_GO")] "Your ride has been booked successfully..."

Example 2 - Missing ride type:
User: "Take me to F7 Markaz Islamabad"
Assistant: [Calls list_ride_types immediately] [Checks if current_location exists in STATE and has valid lat/lng] If current_location available: "Great! I've fetched your current location and I'll use it as your pickup point. Here are our available ride types:
1) LUMI_GO
2) LUMI_PLUS
3) LUMI_MAX
Which ride type would you like for your trip to F7 Markaz, Islamabad?"
If current_location NOT available: "Here are our available ride types:
1) LUMI_GO
2) LUMI_PLUS
3) LUMI_MAX
Which ride type would you like for your trip to F7 Markaz, Islamabad? Also, where would you like to be picked up from?"
User: "Lumi GO"
Assistant: "Perfect! I'll book your ride from your current location to F7 Markaz, Islamabad using LUMI_GO. Should I proceed with booking your ride?"
User: "Yes"
Assistant: [Calls book_ride_with_details(dropoff_place="F7 Markaz Islamabad", ride_type="LUMI_GO") IMMEDIATELY - does NOT call list_ride_types again] "Your ride has been booked successfully..."

Example 3 - User provides both locations with ride type:
User: "Book a ride from Gaddafi Stadium to Johar Town on Lumi Pink"
Assistant: [Calls list_ride_types FIRST, recognizes "Lumi Pink" = LUMI_PINK] "I'll book your ride from Gaddafi Stadium to Johar Town using LUMI_PINK. Should I proceed with booking your ride?"
User: "Yes"
Assistant: [Calls book_ride_with_details(pickup_place="Gaddafi Stadium", dropoff_place="Johar Town", ride_type="LUMI_PINK")] "Your ride has been booked successfully..."

Example 3B - User mentions ride type but missing dropoff (SMART RECOGNITION - CRITICAL):
User: "Book a lumi go ride"
Assistant: [Calls list_ride_types FIRST] [Receives response with LUMI_GO, LUMI_PLUS, etc.] [Extracts "lumi go" from user message] [Matches "lumi go" to "LUMI_GO" in API response] [Checks if current_location exists in STATE and has valid lat/lng] If current_location available: "Great! I'll book a LUMI_GO ride for you. I've fetched your current location! Would you like me to use it as your pickup point, or would you prefer a different pickup location? Also, where would you like to go?" If current_location NOT available: "Great! I'll book a LUMI_GO ride for you. What's your pickup location and where would you like to go?"
❌ WRONG: "Here are the available ride types... Which ride type would you like?" - User already said "lumi go", don't ask again!
❌ WRONG: "I've fetched your current location" when STATE["current_location"] is None or invalid - NEVER mention location if it's not actually available!
User: "F7 Markaz Islamabad"
Assistant: "Perfect! I'll book your ride from your current location to F7 Markaz, Islamabad using LUMI_GO. Should I proceed with booking your ride?"
User: "Yes"
Assistant: [Calls book_ride_with_details(dropoff_place="F7 Markaz Islamabad", ride_type="LUMI_GO")] "Your ride has been booked successfully..."

Example 4 - Retry with different ride type after error (CONTEXT HANDLING):
User: "I want to travel to F7 Markaz Islamabad after stopping at F6 Markaz Islamabad"
Assistant: [Calls list_ride_types FIRST] "Here are the available ride types:
1) LUMI_GO
2) LUMI_PLUS
3) LUMI_MAX
Which ride type would you like?"
User: "Lumi Go"
Assistant: "Perfect! I'll book your ride from your current location to F7 Markaz, Islamabad with a stop at F6 Markaz, Islamabad using LUMI_GO. Should I proceed with booking your ride?"
User: "Yes"
Assistant: [Calls book_ride_with_details] → Error: "Failed to get fare quote."
Assistant: "Failed to get fare quote. Is there anything else I can help you with? Would you like to try a different location or ride type?"
User: "Lets try a different ride type"
Assistant: [Calls list_ride_types FIRST] "Here are the available ride types:
1) LUMI_GO
2) LUMI_PLUS
3) LUMI_MAX
4) LUMI_DIAMOND
Which ride type would you like for your trip from your current location, stopping at F6 Markaz Islamabad, and then to F7 Markaz Islamabad?"
User: "LUMI_DIAMOND"
Assistant: "Perfect! I'll book your ride from your current location to F7 Markaz, Islamabad with a stop at F6 Markaz, Islamabad using LUMI_DIAMOND. Should I proceed with booking your ride?"
User: "Yes"
Assistant: [Calls book_ride_with_details(dropoff_place="F7 Markaz Islamabad", stops=["F6 Markaz Islamabad"], ride_type="LUMI_DIAMOND")] "Your ride has been booked successfully..."

Example 7 - User just says ride type name (must still follow full workflow):
User: "LUMI_DIAMOND" (after error occurred)
Assistant: "LUMI_DIAMOND" ❌ WRONG - Don't just repeat the name
Assistant: "Yes" ❌ WRONG - Don't say "Yes", show booking details and ask THEM
CORRECT: [Calls list_ride_types FIRST] "Here are the available ride types... Which ride type would you like for your trip [with previous locations]?" → User selects → Show booking details → Ask confirmation as a QUESTION ✅

Example 8 - User just says ride type without context (CRITICAL):
User: "Lumi Plus" (after locations were provided earlier in conversation)
Assistant: "Yes" ❌ WRONG - You said "Yes" but should check conversation history for locations and show booking details
CORRECT: [Check conversation history for previous locations] "Perfect! I'll book your ride from [previous pickup] to [previous dropoff] with [previous stops] using LUMI_PLUS. Should I proceed with booking your ride?" ✅

Example 9 - Scheduling a ride for later:
User: "Book a ride to F7 Markaz Islamabad for tomorrow at 3 PM"
Assistant: [Calls list_ride_types FIRST] [Recognizes "tomorrow at 3 PM" as scheduling request] "I'll schedule a ride to F7 Markaz, Islamabad for tomorrow at 3 PM. Which ride type would you like?"
User: "Lumi Go"
Assistant: "Perfect! I'll schedule your ride from your current location to F7 Markaz, Islamabad using LUMI_GO for tomorrow at 3 PM. Should I proceed with scheduling your ride?"
User: "Yes"
Assistant: [Calls book_ride_with_details(dropoff_place="F7 Markaz Islamabad", ride_type="LUMI_GO", is_scheduled=True, scheduled_at="2025-12-30T15:00:00.000Z")] "Your ride has been scheduled successfully..."

Example 10 - User asks to schedule after providing details:
User: "Book a lumi go ride to F7 Markaz"
Assistant: [Calls list_ride_types FIRST] [Matches "lumi go" to LUMI_GO] "I'll book a LUMI_GO ride for you to F7 Markaz, Islamabad. Should I proceed with booking your ride?"
User: "Can I schedule it for later?"
Assistant: "Of course! What date and time would you like to schedule this ride for?"
User: "Tomorrow at 2 PM"
Assistant: "Perfect! I'll schedule your ride from your current location to F7 Markaz, Islamabad using LUMI_GO for tomorrow at 2 PM. Should I proceed with scheduling your ride?"
User: "Yes"
Assistant: [Calls book_ride_with_details(dropoff_place="F7 Markaz Islamabad", ride_type="LUMI_GO", is_scheduled=True, scheduled_at="2025-12-30T14:00:00.000Z")] "Your ride has been scheduled successfully..."

**WRONG WORKFLOWS - NEVER DO THESE:**

WRONG Example 1 - Not calling list_ride_types first when user mentions a ride type:
User: "I want to travel to F7 Markaz Islamabad after stopping at F6 Markaz Islamabad"
Assistant: "Please specify the ride type... Here are the available ride types: 1) LUMI_GO, 2) LUMI_PLUS..." ❌ WRONG - You showed ride types without calling list_ride_types API first
CORRECT: [Calls list_ride_types FIRST] "Here are the available ride types: 1) LUMI_GO, 2) LUMI_PLUS..." ✅

WRONG Example 1B - Not recognizing ride type when user explicitly mentions it (CRITICAL - THIS IS THE EXACT MISTAKE TO AVOID):
User: "Book a lumi go ride"
Assistant: [Calls list_ride_types] "Here are the available ride types: 1) LUMI_GO, 2) LUMI_PLUS... Which ride type would you like?" ❌ ABSOLUTELY WRONG - User already said "lumi go" in their message, you MUST extract it, match it to LUMI_GO in the API response, acknowledge their selection, and ask for dropoff location instead of showing all options
CORRECT WORKFLOW: 
1. User says "Book a lumi go ride"
2. Call list_ride_types FIRST (to verify it exists)
3. Extract "lumi go" from user's message
4. Match "lumi go" (case-insensitive) to "LUMI_GO" in API response
5. If match found → Say "I'll book a LUMI_GO ride for you. What's your dropoff location?" ✅
6. If NOT found → Show all available ride types

WRONG Example 2 - Saying "Yes" when user mentions ride type:
User: "Lumi Plus"
Assistant: "Yes" ❌ ABSOLUTELY WRONG - Never say "Yes" when user mentions a ride type. You must check conversation history, show booking details, and ask confirmation
User: "I'll go by Lumi Plus"
Assistant: "Yes" ❌ ABSOLUTELY WRONG - Never say "Yes". User is selecting ride type, you must show booking details and ask confirmation
CORRECT: [Check conversation history for previous locations] "Perfect! I'll book your ride from [previous pickup] to [previous dropoff] with [previous stops] using LUMI_PLUS. Should I proceed with booking your ride?" ✅

WRONG Example 3 - Confirmation loop (asking multiple times):
User: "Yes"
Assistant: "Are you sure you want to proceed?" ❌ WRONG - User already confirmed, just book it
User: "Yes"
Assistant: "Would you like me to confirm the details again?" ❌ WRONG - This creates a loop
CORRECT: User says "Yes" → Immediately call book_ride_with_details ✅

WRONG Example 4 - Hallucinating booking success without calling tool:
User: "Yes"
Assistant: "Your ride has been booked successfully." ❌ WRONG - You didn't call book_ride_with_details, this is hallucination
CORRECT: [Calls book_ride_with_details] → Wait for tool response → If {"ok": true}, say success; if {"ok": false}, report the error ✅

WRONG Example 5 - Not using exact error message:
Tool returns: {"ok": false, "error": "Start Location is outside the valid service zone."}
Assistant: "There was an issue with the booking. Please check your locations." ❌ WRONG - You're paraphrasing instead of using the exact error
CORRECT: "Start Location is outside the valid service zone." ✅

WRONG Example 6 - Not asking for help after error:
Tool returns: {"ok": false, "error": "Failed to get fare quote."}
Assistant: "Failed to get fare quote." ❌ WRONG - You reported the error but didn't offer help
CORRECT: "Failed to get fare quote. Is there anything else I can help you with? Would you like to try a different location or ride type?" ✅

WRONG Example 7 - Losing context when user wants to retry:
User: "Lets try a different ride type"
Assistant: "LUMI_DIAMOND" ❌ WRONG - You just said a ride type name, didn't show options or ask for confirmation
Assistant: "Yes" ❌ WRONG - You said "Yes" but should ask THEM for confirmation with booking details
CORRECT: [Calls list_ride_types FIRST] "Here are the available ride types... Which ride type would you like for your trip [with previous locations]?" → User selects → Show booking details → Ask confirmation ✅

WRONG Example 8 - Not showing booking details before confirmation:
User: "LUMI_DIAMOND"
Assistant: "Yes" ❌ WRONG - You said "Yes" but should show booking details and ask THEM for confirmation
CORRECT: "Perfect! I'll book your ride from [pickup] to [dropoff] with stops [stops] using LUMI_DIAMOND. Should I proceed with booking your ride?" ✅

WRONG Example 9 - Not using conversation history for dynamic changes:
User: "Change dropoff to F8 Markaz"
Assistant: [Asks for all details again] ❌ WRONG - You should use conversation history to maintain pickup, stops, ride type and only update dropoff
CORRECT: [Uses conversation history] "Perfect! I'll book your ride from [previous pickup] to F8 Markaz with [previous stops] using [previous ride_type]. Should I proceed with booking your ride?" ✅

WRONG Example 10 - Confirmation not as a question:
User: "Yes"
Assistant: "I'll proceed with booking." ❌ WRONG - Confirmation should be asked as a question, not a statement
Assistant: "Let me book it for you." ❌ WRONG - This is a statement, not a question
CORRECT: "Perfect! I'll book your ride from [pickup] to [dropoff] using [ride_type]. Should I proceed with booking your ride?" ✅

WRONG Example 11 - Just saying "Yes" when user mentions ride type:
User: "Lumi Plus" (user just mentions a ride type)
Assistant: "Yes" ❌ WRONG - Never just say "Yes" when user mentions a ride type. You must check conversation history for locations, show booking details, and ask confirmation
CORRECT: [Use conversation history] "Perfect! I'll book your ride from [previous pickup] to [previous dropoff] using LUMI_PLUS. Should I proceed with booking your ride?" ✅

ANTI-HALLUCINATION RULES:
- ALWAYS call list_ride_types FIRST before showing ride types - NEVER infer, guess, or decide ride types on your own
- NEVER say "Your ride has been booked successfully" without calling book_ride_with_details first
- NEVER say "Yes" or "Go ahead" when user selects a ride type - YOU ask THEM for confirmation
- NEVER say "Yes" when user just mentions a ride type (e.g., "Lumi Plus") - check conversation history for locations, show booking details, then ask confirmation
- NEVER just say a ride type name when user wants to try different - ALWAYS call list_ride_types, show options, wait for selection, show booking details, then ask confirmation
- NEVER create confirmation loops - if user confirms, book immediately
- NEVER paraphrase error messages - use the EXACT error from tool responses
- ALWAYS ask for help after reporting an error - offer to try different locations or ride types
- MAINTAIN CONTEXT when user wants to retry - use previous locations (pickup, dropoff, stops) with new ride type from conversation history
- ALWAYS show booking details (locations + ride type) before asking for confirmation - use conversation history if user just mentions ride type
- ONLY report success if book_ride_with_details returns {"ok": true}
- ONLY report errors if tools return {"ok": false, "error": "..."}
- If you're unsure, call the appropriate tool - don't guess or make up responses

CRITICAL RULES:
- NEVER send status messages like "Let me check", "Please hold on", "I'll check" - just call tools directly
- ALWAYS call list_ride_types FIRST before showing ride types - NEVER infer or decide ride types on your own
- Use EXACT location strings from user's message (e.g., "F7 Markaz Islamabad" NOT "F7 Markaz")
- Current location is auto-available - don't ask for pickup if user provides only dropoff
- After confirmation, call book_ride_with_details IMMEDIATELY - no delays
- USE CONVERSATION HISTORY: Be smart and dynamic - use full conversation history to understand user intent and handle changes
- When user changes something (e.g., "change dropoff to X", "update ride type", "try different ride type"), intelligently update that detail while maintaining others from conversation history
- CONTEXT HANDLING: Maintain location context (pickup, dropoff, stops) when user wants to retry with different ride type after an error or makes changes
- When user says "try a different ride type" or "let's try X", call list_ride_types FIRST, show options, and use PREVIOUS locations from the conversation history
- ALWAYS show booking details (pickup, dropoff, stops, ride type) before asking for confirmation - never just say "Yes"
- CONFIRMATION MUST BE A QUESTION: Always ask "Should I proceed?" or "Would you like me to book?" - never make statements
- Formatting: Plain text only, no markdown/HTML/asterisks

SPECIAL QUERIES:
- Fare queries → Call get_fare_for_locations immediately
- Ride status → Call check_active_ride immediately
- Goodbye → Respond warmly, don't redirect

ADDRESS FORMATTING (when presenting ride status):
- When check_active_ride returns addresses, format them in a concise, user-friendly way
- Extract meaningful location names: neighborhood/area name and city
- Remove: Plus Codes (e.g., "QPGJ+X59"), country names ("Pakistan"), street details ("Main Road"), numbers with "near"
- Examples:
  * "QPGJ+X59, Officer Colony Main Road, Officers Colony Wah, Pakistan" → "Officers Colony Wah"
  * "49, near UET, F block Taxila Gardens housing society, Taxila, Pakistan" → "Taxila Gardens, Taxila"
  * "F-6 Markaz, Islamabad, Pakistan" → "F-6 Markaz, Islamabad"
- Always present addresses in natural, readable format - just the location name and city if available

CONVERSATION GUIDELINES:
- Greet professionally when user greets you
- Handle ride status, fare queries directly - don't redirect
- Redirect irrelevant questions politely to ride booking
- Maintain professional, friendly tone
- ACCURACY IS CRITICAL: If you don't know something or don't have information, say so accurately. NEVER guess, assume, or make up information. Check STATE, check conversation history, check tool responses - if information is not available, clearly state that you don't have it rather than guessing

CURRENT LOCATION QUERIES (BE ACCURATE - CHECK STATE, DON'T GUESS OR HALLUCINATE):
- ALWAYS check STATE["current_location"] to determine if location is available - NEVER guess, assume, or hallucinate coordinates
- CRITICAL ANTI-HALLUCINATION RULE: If STATE["current_location"] is None, missing, or doesn't have valid "lat" and "lng" values, you MUST respond that you don't have the location. NEVER call get_address_from_coordinates with guessed, assumed, or hallucinated coordinates. NEVER use coordinates from previous sessions, memory, or any source other than STATE["current_location"].
- When user asks "Do you have my location?" or "Is my current location available?":
  * If STATE["current_location"] exists and has valid lat/lng: Respond "Yes, I have your current location available! I can use it as your pickup point when booking a ride."
  * If STATE["current_location"] is None or invalid: Respond "No, I don't have your current location at the moment. You can share it when booking a ride, or I can use it automatically if location services are enabled."
- When user asks "What's my current location?" or "What is my location?" or "Show me my location":
  * FIRST: Check STATE["current_location"] - it MUST exist AND have valid "lat" and "lng" values
  * If STATE["current_location"] exists and has valid lat/lng: Call the get_address_from_coordinates tool with lat=STATE["current_location"]["lat"] and lng=STATE["current_location"]["lng"]. After the tool returns the address, display it to the user in a friendly format, e.g., "Your current location is at [address]" or "You're currently at [address]".
  * If STATE["current_location"] is None, missing, or invalid: Respond "I don't have your current location at the moment. You can share it when booking a ride, or I can use it automatically if location services are enabled." DO NOT call get_address_from_coordinates. DO NOT guess or hallucinate coordinates.
- ABSOLUTELY CRITICAL ANTI-HALLUCINATION: NEVER call get_address_from_coordinates if STATE["current_location"] is None or invalid. NEVER use coordinates from memory, previous sessions, or any other source. If you don't have valid coordinates in STATE["current_location"], you MUST say you don't have the location - do NOT guess or hallucinate.
- CRITICAL: Always check STATE["current_location"] - if it's None or missing, say so. If it exists and has valid lat/lng, use the get_address_from_coordinates tool to get a readable address. NEVER guess or assume location availability.
- NEVER output raw STATE data, JSON, tool responses, or your internal reasoning/checking process - only output the final clean response

ERROR HANDLING (CRITICAL - NO HALLUCINATION):
- When tools return errors ({"ok": false, "error": "..."}), use the EXACT error message from the tool response
- DO NOT paraphrase, rewrite, or summarize the error - present it to the user EXACTLY as provided by the tool
- DO NOT say generic messages like "Failed to get fare quote" when the tool provides a specific error
- The error message from tools is already user-friendly and formatted - just pass it through verbatim
- NEVER claim success when tools fail
- NEVER make up error messages - only use what tools return
- Example: If tool returns {"ok": false, "error": "Start Location is outside the valid service zone."}, tell the user exactly: "Start Location is outside the valid service zone." (NOT "There was an issue with your location" or "Failed to get fare quote")
- If tool returns {"ok": false, "error": "Failed to get fare quote."}, tell the user exactly that - don't add extra context
- AFTER reporting an error, ALWAYS ask the user if they need any other help, e.g., "Is there anything else I can help you with?" or "Would you like to try a different location or ride type?"
"""

tools = [
  { "type":"function", "function": {
      "name":"request_map_selection",
      "description":"Request the user to select pickup and dropoff locations on a map. ONLY use this as a LAST RESORT when: 1) User explicitly asks to use a map, 2) Location resolution has failed multiple times and user hasn't provided city names, 3) User provides NO location information at all. DO NOT call this if user provides location names (even if ambiguous like 'E11' or 'H13') - instead, proceed with book_ride_with_details and let the system try to resolve them. The frontend will display a map interface for location selection.",
      "parameters":{
        "type":"object",
        "properties":{
          "message":{"type":"string","description":"Optional message to display to the user, e.g. 'Please select your pickup and dropoff locations on the map'"}
        }
      }
  }},
  { "type":"function", "function": {
      "name":"resolve_place_to_coordinates",
      "description":"Resolve a place name or address to coordinates (lat, lng) using Google Maps Places API. Use this if user provides only a place name without coordinates. Returns coordinates and formatted address. NEVER guess coordinates - always call this function to resolve place names.",
      "parameters":{
        "type":"object",
        "properties":{
          "place_name":{"type":"string","description":"Place name or address to resolve, e.g. 'F-6 Markaz, Islamabad' or 'E11' or 'Gaddafi Stadium, Lahore'."},
        },
        "required":["place_name"]
      }
  }},
  { "type":"function", "function": {
      "name":"set_trip_core",
      "description":"Save pickup, dropoff, addresses, and rideTypeName. REQUIRES actual coordinates (lat, lng) - never use place names without coordinates. If user provides place names only (no coordinates), you must first resolve them using Google Maps Places API to get coordinates. The frontend map should send coordinates directly. After successfully saving locations, you should automatically call list_ride_types next.",
      "parameters":{
        "type":"object",
        "properties":{
          "pickup":{"type":"object","properties":{"lat":{"type":"number"},"lng":{"type":"number"},"address":{"type":"string"}},"required":["lat","lng"],"description":"MUST have lat and lng coordinates. If only address is provided, resolve it via Google Maps API first."},
          "dropoff":{"type":"object","properties":{"lat":{"type":"number"},"lng":{"type":"number"},"address":{"type":"string"}},"required":["lat","lng"],"description":"MUST have lat and lng coordinates. If only address is provided, resolve it via Google Maps API first."},
          "pickup_address":{"type":"string"},
          "destination_address":{"type":"string"},
          "rideTypeName":{"type":"string","description":"Name from /ride-types, e.g., LUMI_GO or Courier"}
        },
        "required":["pickup","dropoff"]
      }
  }},
  { "type":"function", "function": {
      "name":"set_stops",
      "description":"Set stops for the ride. Accepts place names (which will be resolved to coordinates) or coordinates directly. Provide an ordered list of stops (0..N). Each stop can be a place name (string) or an object with lat/lng coordinates.",
      "parameters":{
        "type":"object",
        "properties":{
          "stops":{"type":"array","items":{
            "oneOf": [
              {
                "type":"string",
                "description":"Place name or address to resolve (e.g., 'F-6 Markaz, Islamabad')"
              },
              {
            "type":"object",
            "properties":{
              "lat":{"type":"number"},
              "lng":{"type":"number"},
              "address":{"type":"string"},
                  "order":{"type":"integer"},
                  "place_name":{"type":"string","description":"Place name if coordinates are provided"}
            },
            "required":["lat","lng"]
              }
            ]
          }}
        },
        "required":["stops"]
      }
  }},
  { "type":"function", "function": {
      "name":"set_courier_fields",
      "description":"Set courier-only fields. Use only if ride type is Courier.",
      "parameters":{
        "type":"object",
        "properties":{
          "sender_phone_number":{"type":"string"},
          "receiver_phone_number":{"type":"string"},
          "comments_for_courier":{"type":"string"},
          "package_size":{"type":"integer"},
          "package_types":{"type":"array","items":{"type":"string"}}
        }
      }
  }},
  { "type":"function", "function": {
      "name":"list_ride_types",
      "description":"Fetch available ride types from the API. CRITICAL: Call this IMMEDIATELY when: 1) User mentions a ride type (to validate it exists), 2) User asks for ride type options, 3) You need to show available ride types to the user. Returns ALL ride types with their 'active' status. IMPORTANT MATCHING RULE: After calling this function, check if the user already mentioned a ride type in their message (e.g., 'Book a lumi go ride'). If they did, extract it from their message, match it to the API response (case-insensitive, e.g., 'lumi go' matches 'LUMI_GO'), and if found, acknowledge their selection and proceed - DON'T show all options. Only show all options if user hasn't mentioned a ride type or their mentioned type doesn't match. NEVER make up or guess ride types - always call this function to get the actual list from the API.",
      "parameters":{"type":"object","properties":{}}
  }},
  { "type":"function", "function": {
      "name":"set_ride_type",
      "description":"Set the selected ride type, get fare quote, and AUTOMATICALLY book the ride. Call this IMMEDIATELY when user selects a ride type (e.g., 'Lumi GO', 'LUMI_GO', 'Courier', etc.). This tool will: 1) Parse and match the ride type name to the API ride types, 2) Set it in state, 3) Automatically call get_fare_quote, 4) AUTOMATICALLY call auto_book_ride to complete the booking. NO USER CONFIRMATION REQUIRED - fully automatic.",
      "parameters":{
        "type":"object",
        "properties":{
          "ride_type_name":{"type":"string","description":"The ride type name the user selected, e.g., 'Lumi GO', 'LUMI_GO', 'Courier', 'Bike', etc. This will be matched to the actual API ride type names."}
        },
        "required":["ride_type_name"]
      }
  }},
  { "type":"function", "function": {
      "name":"book_ride_with_details",
      "description":"AUTONOMOUS BOOKING: When you have collected ALL required booking details (dropoff location and ride type), call this tool to automatically book the ride. CRITICAL: You MUST have dropoff_place and ride_type before calling this tool. pickup_place is OPTIONAL - if not provided, the system will automatically use the user's current location (fetched from backend API). CRITICAL - WHEN USER CONFIRMS: If the user has confirmed after you asked for confirmation (said 'Yes', 'Okay', 'Proceed', 'Book it', etc.), call this tool IMMEDIATELY using the details from conversation history. DO NOT call list_ride_types again - if the ride_type was already mentioned/selected in the conversation (e.g., user selected 'LUMI_GO' and you already called list_ride_types to validate it), use it directly. IMPORTANT: Only call list_ride_types FIRST if this is a NEW ride_type that hasn't been validated yet. But once validated in the conversation, when user confirms, call this tool directly. SCHEDULING: If the user wants to schedule the ride for later (mentioned keywords like 'schedule', 'later', 'tomorrow', 'on [date]', 'at [time]'), set is_scheduled=True and provide scheduled_at in ISO8601 format (e.g., '2025-09-23T07:25:32.084Z'). Convert user's date/time to UTC ISO8601 format before passing. If scheduling not mentioned, default to immediate booking (is_scheduled=False, scheduled_at=None). CRITICAL: Always use the COMPLETE location names from the conversation (e.g., 'Jamil Sweets, E-11' NOT just 'E-11', 'NSTP, H-12' NOT just 'NSTP'). Preserve the full location strings as mentioned by the user. This tool will: 1) Resolve locations to coordinates if needed, 2) Set trip core, 3) Get fare quote, 4) Create ride request with scheduling if specified, 5) Wait for bids, 6) Automatically accept the best (lowest fare) bid, 7) Return success message. ONLY call this when you have dropoff_place and ride_type. If pickup_place is not provided, current location will be used automatically. ANTI-HALLUCINATION: NEVER say 'Your ride has been booked successfully' without calling this tool first. Wait for tool response - if {'ok': True}, report success; if {'ok': False}, report the EXACT error message from the tool. NEVER make up success or error messages.",
      "parameters":{
        "type":"object",
        "properties":{
          "pickup_place":{"type":"string","description":"Pickup location as place name (e.g., 'F-6 Markaz, Islamabad') or coordinates in 'lat,lng' format (e.g., '33.6956,73.2205'). CRITICAL: If using coordinates, use ONLY 'lat,lng' format with no spaces or descriptive text like 'Coordinates (lat, lng)'. OPTIONAL: If not provided, user's current location will be used automatically."},
          "dropoff_place":{"type":"string","description":"Dropoff location as place name (e.g., 'E-11, Islamabad') or coordinates (e.g., '33.6992,72.9744'). If coordinates are provided, they should be in 'lat,lng' format."},
          "ride_type":{"type":"string","description":"Ride type name (e.g., 'LUMI_GO', 'Lumi GO', 'Courier', 'Bike', etc.)"},
          "stops":{"type":"array","items":{"type":"string"},"description":"Optional list of stop place names (e.g., ['F-6 Markaz, Islamabad', 'E-11, Islamabad']). Stops will be resolved to coordinates automatically."},
          "payment_via":{"type":"string","enum":["WALLET","CASH","CARD"],"description":"Payment method (optional, defaults to CASH)"},
          "is_scheduled":{"type":"boolean","description":"Whether this is a scheduled ride (optional). Set to true if user wants to schedule the ride for later. Must be true if scheduled_at is provided."},
          "scheduled_at":{"type":"string","description":"ISO8601 timestamp in UTC format (e.g., '2025-09-23T07:25:32.084Z') for when the ride should be scheduled. Required if is_scheduled is true. Format: YYYY-MM-DDTHH:MM:SS.mmmZ. Convert user-provided date/time to UTC ISO8601 format before passing."},
          "is_family":{"type":"boolean","description":"Whether this is a family ride (optional)"}
        },
        "required":["dropoff_place","ride_type"]
      }
  }},
  { "type":"function", "function": {
      "name":"auto_book_ride",
      "description":"AUTONOMOUS AGENT: Automatically books a ride end-to-end without user confirmation. This tool: 1) Creates the ride request, 2) Waits for bids, 3) Automatically accepts the best (lowest fare) bid, 4) Returns success message. Called automatically by set_ride_type - you usually don't need to call this directly.",
      "parameters":{
        "type":"object",
        "properties":{
          "payment_via":{"type":"string","enum":["WALLET","CASH","CARD"]},
          "is_scheduled":{"type":"boolean"},
          "scheduled_at":{"type":"string","description":"ISO8601 if is_scheduled==true"},
          "is_family":{"type":"boolean"}
        }
      }
  }},
  { "type":"function", "function": {
      "name":"get_fare_quote",
      "description":"Get fare estimate WITHOUT creating a ride. Returns 'selected_ride_type_fare' field with the exact fare amount for the selected ride type. NOTE: set_ride_type automatically calls this, so you usually don't need to call this directly unless set_ride_type fails.",
      "parameters":{
        "type":"object",
        "properties":{}
      }
  }},
  { "type":"function", "function": {
      "name":"get_fare_for_locations",
      "description":"CRITICAL: Get fare quote for specific pickup and dropoff locations. Use this IMMEDIATELY when user asks about fare in ANY format (e.g., 'what is the fare from X to Y', 'fare for going from X to Y', 'fare for going to X to Y', 'what is the fare for going to X to Y', 'cheapest fare from X to Y', 'what's the fare for all the rides'). Extract pickup and dropoff locations from the user's message and call this tool DIRECTLY. DO NOT ask for confirmation. DO NOT try to set locations first. DO NOT say 'I'll check' or 'Let me get' - just call the tool immediately. IMPORTANT: If user doesn't provide pickup location (e.g., 'fare to F6 Markaz' or 'what's the fare for all the rides'), leave pickup_place empty or don't provide it - the tool will automatically use current_location from STATE (converts coordinates to address first). If user provides only dropoff, use current_location as pickup. This tool automatically handles both place names and coordinate strings, resolves locations using Google Maps API, calculates distance/duration, and returns fare quotes for all ride types. This is a standalone API query that works independently without setting trip core.",
      "parameters":{
        "type":"object",
        "properties":{
          "pickup_place":{"type":"string","description":"Pickup location extracted from user's message (e.g., 'F7 Markaz Islamabad', 'Jameel Sweets, E-11, Islamabad'). If user doesn't provide pickup, leave this empty or don't provide it - the tool will use current_location automatically. Use the exact location name the user provided."},
          "dropoff_place":{"type":"string","description":"Dropoff location extracted from user's message (e.g., 'F6 Markaz Islamabad', 'NSTP, H-12, Islamabad'). Use the exact location name the user provided."}
        },
        "required":["dropoff_place"]
      }
  }},
  { "type":"function", "function": {
      "name":"get_address_from_coordinates",
      "description":"CRITICAL: Convert coordinates (latitude, longitude) to a human-readable address using Google Maps reverse geocoding. ONLY call this tool when STATE['current_location'] exists AND has valid 'lat' and 'lng' values. NEVER call this tool if STATE['current_location'] is None, missing, or invalid. NEVER hallucinate or guess coordinates - if you don't have valid coordinates in STATE['current_location'], respond that you don't have the location instead of calling this tool. The tool takes latitude and longitude coordinates and returns a formatted address string that you should display to the user.",
      "parameters":{
        "type":"object",
        "properties":{
          "lat":{"type":"number","description":"Latitude coordinate from STATE['current_location']['lat'] - ONLY use if STATE['current_location'] exists and has valid lat"},
          "lng":{"type":"number","description":"Longitude coordinate from STATE['current_location']['lng'] - ONLY use if STATE['current_location'] exists and has valid lng"}
        },
        "required":["lat","lng"]
      }
  }},
  { "type":"function", "function": {
      "name":"check_active_ride",
      "description":"Check if the user has an active or ongoing ride. Use this when user asks 'is my ride booked', 'do I have an active ride', 'check my ride status', or similar questions. Returns the active ride details if one exists, or indicates no active ride. IMPORTANT: The tool returns full addresses from Google Maps. When presenting addresses to the user, format them in a concise, user-friendly way by extracting the meaningful neighborhood/area name and city. For example, 'QPGJ+X59, Officer Colony Main Road, Officers Colony Wah, Pakistan' should be presented as 'Officers Colony Wah', and '49, near UET, F block Taxila Gardens housing society, Taxila, Pakistan' should be presented as 'Taxila Gardens, Taxila'. Remove Plus Codes, country names, street details, and keep only the meaningful location identifiers.",
      "parameters":{"type":"object","properties":{}}
  }},
  { "type":"function", "function": {
      "name":"create_ride_and_wait_for_bids",
      "description":"Create ride and wait for first bid. Call AUTOMATICALLY immediately after user confirms fare (says 'yes', 'okay', 'proceed', 'create'). This creates the ride, waits for first bid to arrive, then returns the best (lowest fare) bid IMMEDIATELY - no delays. Returns a 'best_bid' object with 'driverName' and 'price' fields - ALWAYS use these exact values when presenting the bid to the user. NEVER make up bid prices or driver names. If user says 'wait for more bids', call wait_for_bids tool instead.",
      "parameters":{
        "type":"object",
        "properties":{
          "payment_via":{"type":"string","enum":["WALLET","CASH","CARD"]},
          "is_scheduled":{"type":"boolean"},
          "scheduled_at":{"type":"string","description":"ISO8601 if is_scheduled==true"},
          "offered_fair":{"type":"number"},
          "is_family":{"type":"boolean"}
        }
      }
  }},
  { "type":"function", "function": {
      "name":"create_request_and_poll",
      "description":"[DEPRECATED - Use get_fare_quote + create_ride_and_wait_for_bids instead] FARE → create ride → poll bids (called only after user confirms)",
      "parameters":{
        "type":"object",
        "properties":{
          "payment_via":{"type":"string","enum":["WALLET","CASH","CARD"]},
          "is_scheduled":{"type":"boolean"},
          "scheduled_at":{"type":"string","description":"ISO8601 if is_scheduled==true"},
          "offered_fair":{"type":"number"},
          "is_family":{"type":"boolean"}
        }
      }
  }},
  { "type":"function", "function": {
      "name":"wait_for_bids",
      "description":"Re-poll bids for the current rideRequestId. Use when the user says 'wait for more bids' or 'show bids again'.",
      "parameters":{
        "type":"object",
        "properties":{
          "timeout_seconds":{"type":"integer","description":"Max seconds to wait for bids.","default":30},
          "poll_interval":{"type":"integer","description":"Polling interval in seconds.","default":4}
        }
      }
  }},
  { "type":"function", "function": {
      "name":"accept_bid_choice",
      "description":"Accept a bid using its index in the last listed bids or by driver name.",
      "parameters":{
        "type":"object",
        "properties":{
          "choice_index":{"type":"integer","description":"1-based index of the bid from the last bids list."},
          "driver_name":{"type":"string","description":"Case-insensitive driver name match, e.g. 'hasnat'."}
        },
        "description":"Provide either choice_index or driver_name to pick which bid to accept."
      }
  }},
  { "type":"function", "function": {
      "name":"accept_bid",
      "description":"Accept a bid by id (UUID). Prefer accept_bid_choice when user gives an index or name.",
      "parameters":{"type":"object","properties":{"bidId":{"type":"string"}},"required":["bidId"]}
  }},
  { "type":"function", "function": {
      "name":"track_ride",
      "description":"Get current ride details. REQUIRES a valid ride ID (UUID format). Use STATE['rideId'] if available, or ask the user for the ride ID. NEVER use placeholder values like '<ride_id>' - always use the actual ride ID from STATE or user input.",
      "parameters":{"type":"object","properties":{"rideId":{"type":"string","description":"The actual ride ID (UUID) from STATE['rideId'] or user input. Must be a valid UUID, not a placeholder."}},"required":["rideId"]}
  }},
  { "type":"function", "function": {
      "name":"cancel_ride",
      "description":"Cancel a ride. IMPORTANT: This tool automatically checks for active ride first and uses that ride ID. If user says 'cancel this ride' or 'cancel my ride', just call this tool - it will automatically get the correct ride ID from the active ride. The rideId parameter is required but the tool will override it with the active ride ID if one exists. Only if there's no active ride will it use the provided rideId (for canceling a specific ride by ID).",
      "parameters":{"type":"object","properties":{"rideId":{"type":"string","description":"Ride ID parameter (required but will be overridden by active ride ID if available). If user says 'cancel this ride', you can use any placeholder value - the tool will automatically fetch the correct ride ID from the active ride."},"reason":{"type":"string","description":"Optional cancellation reason"}},"required":["rideId"]}
  }}
]

STATE = {
  "pickup": None,
  "dropoff": None,
  "pickup_address": None,
  "destination_address": None,
  "pickup_location": None,
  "dropoff_location": None,
  "stops": [],
  "current_location": None,  # User's current location from backend API
  "rideTypeName": None,
  "rideTypeId": None,
  "customerId": None,
  "rideRequestId": None,
  "rideId": None,

  # courier optionals
  "sender_phone_number": None,
  "receiver_phone_number": None,
  "comments_for_courier": None,
  "package_size": None,
  "package_types": None,

  # bidding
  "last_bids": [],
  "last_quote": None,
  "computed_distance_km": None,

  # scheduling
  "is_scheduled": False,  # Whether the ride is scheduled for later
  "scheduled_at": None,  # ISO8601 timestamp for scheduled rides
  "computed_duration_min": None,
}

def _extract_customer_id_from_bid(bid: dict | None):
    if not isinstance(bid, dict):
        return None
    ride_request = bid.get("rideRequest") or bid.get("ride_request") or {}
    passenger = (
        bid.get("passenger")
        or bid.get("customer")
        or ride_request.get("passenger")
        or ride_request.get("customer")
        or {}
    )
    return (
        bid.get("passenger_id")
        or bid.get("passengerId")
        or bid.get("customer_id")
        or bid.get("customerId")
        or ride_request.get("passenger_id")
        or ride_request.get("passengerId")
        or ride_request.get("customer_id")
        or ride_request.get("customerId")
        or passenger.get("id")
    )

def _remember_customer_id_from_bid(bid: dict | None):
    cid = _extract_customer_id_from_bid(bid)
    if cid:
        STATE["customerId"] = cid
    return cid


def _ensure_currency():
    """
    Ensure STATE contains the active currency information from /api/v1/currency.
    Stores a dict like {"code": "...", "symbol": "..."} in STATE["currency"].
    """
    if STATE.get("currency"):
        return STATE["currency"]
    try:
        currencies = list_currencies() or []
        active = next((c for c in currencies if c.get("isActive")), None)
        if not active and currencies:
            active = currencies[0]
        if active:
            STATE["currency"] = {
                "code": active.get("code"),
                "symbol": active.get("symbol"),
            }
    except Exception as e:
        print(f"⚠️ Failed to fetch currencies: {e}")
    return STATE.get("currency")


def _format_price(amount: float) -> str:
    """
    Format a numeric amount using the active currency from state.
    Uses currency symbol if available, otherwise falls back to currency code.
    """
    cur = STATE.get("currency") or {}
    symbol = cur.get("symbol") or cur.get("code") or ""
    if symbol:
        return f"{amount:.0f} {symbol}"
    return f"{amount:.0f}"

def _normalize_ride_type_name(name: str) -> str:
    """
    Normalize ride type name for matching.
    Converts to lowercase, removes spaces and underscores, and strips.
    This allows "Lumi GO", "LUMI_GO", "lumi go", etc. to all match.
    """
    if not name:
        return ""
    return name.strip().lower().replace(" ", "").replace("_", "")

def _extract_user_friendly_error(api_response: dict, status_code: int = None) -> str:
    """
    Extract a concise, one-line user-friendly error message from API response.
    Handles various error response formats and status codes.
    """
    if not api_response:
        if status_code == 409:
            return "You already have an active ride request. Cancel it first or wait for it to complete."
        elif status_code == 400:
            return "Invalid request. Please check your booking details."
        elif status_code == 401:
            return "Authentication failed. Please log in again."
        elif status_code == 403:
            return "Permission denied."
        elif status_code == 404:
            return "Resource not found."
        elif status_code == 500:
            return "Server error. Please try again later."
        else:
            return "An error occurred. Please try again."
    
    # Try to extract message from various response formats
    message = None
    
    # Format 1: {"message": ["error text"]} or {"message": "error text"}
    if "message" in api_response:
        msg = api_response["message"]
        if isinstance(msg, list) and len(msg) > 0:
            message = msg[0]
        elif isinstance(msg, str):
            message = msg
    
    # Format 2: {"error": "error text"}
    if not message and "error" in api_response:
        error = api_response["error"]
        if isinstance(error, str):
            message = error
    
    # Format 3: {"errors": [...]}
    if not message and "errors" in api_response:
        errors = api_response["errors"]
        if isinstance(errors, list) and len(errors) > 0:
            message = str(errors[0])
    
    # Format 4: {"detail": "error text"}
    if not message and "detail" in api_response:
        message = api_response["detail"]
    
    # If we found a message, return it
    if message:
        return str(message)
    
    # Fallback to status code based messages
    if status_code == 409:
        return "You already have an active ride request. Cancel it first or wait for it to complete."
    elif status_code == 400:
        return "Invalid request. Please check your booking details."
    elif status_code == 401:
        return "Authentication failed. Please log in again."
    elif status_code == 403:
        return "You don't have permission to perform this action."
    elif status_code == 404:
        return "The requested resource was not found."
    elif status_code == 500:
        return "Server error. Please try again later."
    else:
        return "An error occurred. Please try again."

async def tool_resolve_place_to_coordinates(place_name: str):
    """
    Resolve a place name to coordinates using Google Maps Places API.
    Returns coordinates and formatted address.
    """
    if not place_name or len(place_name.strip()) < 2:
        return {
            "ok": False,
            "error": "Place name must be at least 2 characters long.",
        }
    
    try:
        from google_maps import get_google_maps_service
        service = get_google_maps_service()
        
        if not service.googleApiKey:
            return {
                "ok": False,
                "error": "Google Maps API key not configured. Cannot resolve place names.",
            }
        
        place_clean = place_name.strip()
        
        # Get place suggestions
        predictions = await service.fetchPlaces(place_clean)
        
        if not predictions or len(predictions) == 0:
            return {
                "ok": False,
                "error": f"Could not find place '{place_name}'. Please provide coordinates or use the map to select a location.",
            }
        
        # Use the first prediction (most relevant)
        place_id = predictions[0].get("place_id")
        if not place_id:
            return {
                "ok": False,
                "error": f"Could not get place ID for '{place_name}'.",
            }
        
        # Get place details with coordinates
        coords = await service.getPlaceDetails(place_id)
        if not coords or "lat" not in coords or "lng" not in coords:
            return {
                "ok": False,
                "error": f"Could not get coordinates for '{place_name}'.",
            }
        
        # Get address from coordinates
        address_result = await service.fetchAddressFromCoordinates(coords["lat"], coords["lng"])
        address = address_result.get("address", place_name)
        
        return {
            "ok": True,
            "lat": coords["lat"],
            "lng": coords["lng"],
            "address": address,
            "place_name": place_name,
        }
    except Exception as e:
        print(f"⚠️ Error resolving place '{place_name}': {e}")
        import traceback
        traceback.print_exc()
        return {
            "ok": False,
            "error": f"Failed to resolve place '{place_name}': {str(e)}",
        }

async def tool_get_address_from_coordinates(lat: float, lng: float):
    """
    Convert coordinates to a human-readable address using Google Maps reverse geocoding.
    Returns the formatted address string.
    
    CRITICAL: This tool should ONLY be called when STATE["current_location"] exists and has valid lat/lng.
    The tool validates that the provided coordinates match STATE["current_location"] to prevent hallucination.
    """
    # CRITICAL ANTI-HALLUCINATION CHECK: Verify coordinates match STATE["current_location"]
    current_loc = STATE.get("current_location")
    if not current_loc or not isinstance(current_loc, dict):
        return {
            "ok": False,
            "error": "Current location is not available. STATE['current_location'] is None or invalid. Do not call this tool when location is unavailable.",
        }
    
    if "lat" not in current_loc or "lng" not in current_loc:
        return {
            "ok": False,
            "error": "Current location is not available. STATE['current_location'] does not have valid lat/lng values. Do not call this tool when location is unavailable.",
        }
    
    # Verify the provided coordinates match STATE (with small tolerance for floating point)
    state_lat = current_loc["lat"]
    state_lng = current_loc["lng"]
    tolerance = 0.0001  # Small tolerance for floating point comparison
    
    if abs(lat - state_lat) > tolerance or abs(lng - state_lng) > tolerance:
        return {
            "ok": False,
            "error": f"Provided coordinates ({lat}, {lng}) do not match STATE['current_location'] ({state_lat}, {state_lng}). Do not use guessed or hallucinated coordinates. Only use coordinates from STATE['current_location'].",
        }
    
    try:
        from google_maps import get_google_maps_service
        service = get_google_maps_service()
        
        if not service.googleApiKey:
            return {
                "ok": False,
                "error": "Google Maps API key not configured. Cannot convert coordinates to address.",
            }
        
        # Get address from coordinates
        address_result = await service.fetchAddressFromCoordinates(lat, lng)
        address = address_result.get("address", "Address not found")
        
        if address == "Address not found":
            return {
                "ok": False,
                "error": "Could not find address for the given coordinates.",
            }
        
        return {
            "ok": True,
            "address": address,
            "lat": lat,
            "lng": lng,
        }
    except Exception as e:
        print(f"⚠️ Error converting coordinates to address: {e}")
        import traceback
        traceback.print_exc()
        return {
            "ok": False,
            "error": f"Error converting coordinates to address: {str(e)}",
        }

def _iso_in(minutes: int) -> str:
    """
    Return an ISO8601 timestamp with milliseconds and trailing 'Z',
    e.g. 2025-09-23T07:25:32.084Z
    """
    dt = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    # format to YYYY-MM-DDTHH:MM:SS.mmmZ
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ensure_login():
    from api import TOKEN
    if TOKEN:
        return True
    print("You are not logged in.")
    phone = input("Phone in E.164 (e.g., +923001234567): ").strip()
    result = ensure_token_via_signup_or_manual(phone)
    if result.get("ok"):
        print("✅ Auth ready.")
        return True
    print("❌ Auth failed:", result.get("error"))
    return False

# ---------------- tools impl ----------------
def tool_request_map_selection(message: str = None):
    """
    Request map selection from the frontend.
    This tool signals to the frontend that it should display a map for location selection.
    The frontend will handle the map UI and send back selected locations via set_trip_core.
    """
    return {
        "ok": True,
        "action": "show_map",
        "message": message or "Please select your pickup and dropoff locations on the map, then press Done.",
        "requires_user_input": True,
    }

def _parse_locations_from_message(message: str):
    """
    DEPRECATED: This function used regex-based parsing which is not scalable.
    The assistant now handles location extraction dynamically using natural language understanding.
    This function is kept for backward compatibility but returns None.
    The assistant should extract coordinates intelligently before calling tools.
    """
    # Return None - let the assistant handle extraction dynamically
    return None

async def tool_set_trip_core(pickup, dropoff, pickup_address=None, destination_address=None, rideTypeName=None):
    """
    Save pickup, dropoff, addresses, and rideTypeName.
    REQUIRES actual coordinates (lat, lng). If only place names are provided, they must be resolved via Google Maps API first.
    """
    # Validate that coordinates are provided
    if not pickup or not isinstance(pickup, dict) or pickup.get("lat") is None or pickup.get("lng") is None:
        return {
            "ok": False,
            "error": "pickup must have 'lat' and 'lng' coordinates. If only address is provided, resolve it via Google Maps Places API first.",
        }
    
    if not dropoff or not isinstance(dropoff, dict) or dropoff.get("lat") is None or dropoff.get("lng") is None:
        return {
            "ok": False,
            "error": "dropoff must have 'lat' and 'lng' coordinates. If only address is provided, resolve it via Google Maps Places API first.",
        }
    
    # If addresses are not provided, try to get them from coordinates
    if not pickup_address:
        try:
            from google_maps import get_google_maps_service
            service = get_google_maps_service()
            address_result = await service.fetchAddressFromCoordinates(pickup["lat"], pickup["lng"])
            pickup_address = address_result.get("address", "Pickup")
        except Exception as e:
            print(f"⚠️ Could not fetch address for pickup: {e}")
            pickup_address = pickup.get("address") or "Pickup"
    
    if not destination_address:
        try:
            from google_maps import get_google_maps_service
            service = get_google_maps_service()
            address_result = await service.fetchAddressFromCoordinates(dropoff["lat"], dropoff["lng"])
            destination_address = address_result.get("address", "Dropoff")
        except Exception as e:
            print(f"⚠️ Could not fetch address for dropoff: {e}")
            destination_address = dropoff.get("address") or "Dropoff"
    
    STATE["pickup"] = pickup
    STATE["dropoff"] = dropoff
    STATE["pickup_address"] = pickup_address
    STATE["destination_address"] = destination_address
    STATE["pickup_location"] = STATE["pickup_address"]
    STATE["dropoff_location"] = STATE["destination_address"]
    STATE["rideTypeName"] = rideTypeName or STATE["rideTypeName"]

    if STATE["rideTypeName"]:
        # Normalize the user's ride type name for matching (handle spaces, underscores, case)
        user_ride_type_normalized = _normalize_ride_type_name(STATE["rideTypeName"])
        for t in list_ride_types():
            api_ride_type_normalized = _normalize_ride_type_name(str(t.get("name", "")))
            if api_ride_type_normalized == user_ride_type_normalized:
                STATE["rideTypeId"] = t.get("id")
                # Update STATE["rideTypeName"] to the exact API name for consistency
                STATE["rideTypeName"] = t.get("name")
                break

    return {
        "ok": True,
        "message": "Locations saved successfully.",
        "next_step": "Call list_ride_types automatically now.",
        "state": {
        "pickup": STATE["pickup"],
        "dropoff": STATE["dropoff"],
        "pickup_address": STATE["pickup_address"],
        "destination_address": STATE["destination_address"],
        "rideTypeName": STATE["rideTypeName"],
        "rideTypeId": STATE["rideTypeId"],
        }
    }

async def tool_set_stops(stops):
    """
    Set stops for the ride. Accepts place names (strings) or coordinate objects.
    If place names are provided, resolves them to coordinates using Google Maps API.
    """
    norm = []
    for idx, s in enumerate(stops):
        # If stop is a string (place name), resolve it to coordinates
        if isinstance(s, str):
            place_name = s.strip()
            if not place_name:
                continue
            
            # Resolve place name to coordinates
            resolved = await tool_resolve_place_to_coordinates(place_name)
            if not resolved.get("ok"):
                return {
                    "ok": False,
                    "error": f"Failed to resolve stop '{place_name}': {resolved.get('error', 'Unknown error')}",
                }
            
            norm.append({
                "lat": resolved["lat"],
                "lng": resolved["lng"],
                "address": resolved.get("address", place_name),
                "order": idx + 1,
            })
        else:
            # Stop is already an object with coordinates
            norm.append({
                "lat": s.get("lat") or s.get("latitude"),
                "lng": s.get("lng") or s.get("longitude"),
                "address": s.get("address") or s.get("place_name", ""),
                "order": s.get("order", idx + 1),  # ensure order field exists
            })
    
    STATE["stops"] = norm
    return {"ok": True, "count": len(norm), "stops": norm}

def tool_set_courier_fields(sender_phone_number=None, receiver_phone_number=None, comments_for_courier=None, package_size=None, package_types=None):
    STATE["sender_phone_number"] = sender_phone_number
    STATE["receiver_phone_number"] = receiver_phone_number
    STATE["comments_for_courier"] = comments_for_courier
    STATE["package_size"] = package_size
    STATE["package_types"] = package_types
    return {"ok": True}

async def tool_set_ride_type(ride_type_name: str):
    """
    Set the selected ride type, get fare quote, and AUTOMATICALLY book the ride.
    This tool:
    1. Parses and matches the ride type name to API ride types
    2. Sets it in STATE
    3. Automatically calls get_fare_quote
    4. AUTOMATICALLY calls auto_book_ride to complete the booking
    """
    if not ride_type_name:
        return {
            "ok": False,
            "error": "ride_type_name is required.",
        }
    
    # Validate that pickup and dropoff are set
    if not STATE.get("pickup") or not STATE.get("dropoff"):
        return {
            "ok": False,
            "error": "Pickup and dropoff locations must be set before selecting a ride type. Please set locations first.",
        }
    
    # Get available ride types and match the user's selection
    available_ride_types = list_ride_types()
    matched_ride_type = None
    user_ride_type_normalized = _normalize_ride_type_name(ride_type_name)
    
    for rt in available_ride_types:
        api_ride_type_normalized = _normalize_ride_type_name(str(rt.get("name", "")))
        if api_ride_type_normalized == user_ride_type_normalized:
            matched_ride_type = rt
            break
    
    if not matched_ride_type:
        # Return available ride types so the assistant can inform the user
        available_names = [rt.get("name") for rt in available_ride_types if rt.get("name")]
        active_names = [rt.get("name") for rt in available_ride_types if rt.get("name") and rt.get("isActive", True)]
        
        # Try to find similar ride types (fuzzy matching)
        similar_suggestions = []
        user_lower = ride_type_name.lower()
        for rt in available_ride_types:
            rt_name = rt.get("name", "")
            rt_lower = rt_name.lower()
            # Check for partial matches or similar names
            if user_lower in rt_lower or rt_lower in user_lower or any(word in rt_lower for word in user_lower.split() if len(word) > 2):
                similar_suggestions.append(rt_name)
        
        error_msg = f"Ride type '{ride_type_name}' not found."
        if similar_suggestions:
            error_msg += f" Did you mean: {', '.join(similar_suggestions[:3])}?"
        else:
            error_msg += f" Available ride types: {', '.join(active_names) if active_names else ', '.join(available_names)}"
        
        return {
            "ok": False,
            "error": error_msg,
            "available_ride_types": available_names,
            "active_ride_types": active_names,
            "similar_suggestions": similar_suggestions[:3] if similar_suggestions else [],
        }
    
    # Set the ride type in STATE
    STATE["rideTypeName"] = matched_ride_type.get("name")
    STATE["rideTypeId"] = matched_ride_type.get("id")
    
    # Automatically call get_fare_quote
    fare_result = await tool_get_fare_quote()
    
    if not fare_result.get("ok"):
        # Pass through the actual error message from fare_result
        error_msg = fare_result.get('error', 'Failed to get fare quote')
        return {
            "ok": False,
            "error": error_msg,  # Use the actual error message directly, don't wrap it
            "ride_type_set": True,
            "ride_type_name": STATE["rideTypeName"],
            "ride_type_id": STATE["rideTypeId"],
        }
    
    # AUTOMATICALLY book the ride - no user confirmation needed
    # Use scheduling parameters from STATE if available
    is_scheduled = STATE.get("is_scheduled", False)
    scheduled_at = STATE.get("scheduled_at")
    booking_result = await tool_auto_book_ride(
        is_scheduled=is_scheduled,
        scheduled_at=scheduled_at
    )
    
    if not booking_result.get("ok"):
        # Pass through the actual error message from booking_result
        error_msg = booking_result.get('error', 'Failed to book ride')
        return {
            "ok": False,
            "error": error_msg,  # Use the actual error message directly, don't wrap it
            "ride_type_set": True,
            "fare_quote_ok": True,
            "ride_type_name": STATE["rideTypeName"],
            "selected_ride_type_fare": fare_result.get("selected_ride_type_fare"),
        }
    
    # Success! Return the booking result
    return {
        "ok": True,
        "ride_type_name": STATE["rideTypeName"],
        "ride_type_id": STATE["rideTypeId"],
        "selected_ride_type_fare": fare_result.get("selected_ride_type_fare"),
        "distance_km": fare_result.get("distance_km"),
        "duration_min": fare_result.get("duration_min"),
        "message": booking_result.get("message"),  # "Perfect! Your ride has been booked..."
        "rideId": booking_result.get("rideId"),
        "driverName": booking_result.get("driverName"),
        "price": booking_result.get("price"),
    }

async def tool_get_fare_quote():
    """
    Get fare quote WITHOUT creating a ride. Returns fare for all ride types.
    """
    # Validate that pickup and dropoff are set
    if not STATE.get("pickup") or not STATE.get("dropoff"):
        return {
            "ok": False,
            "error": "Pickup and dropoff locations must be set before getting fare quote. Please set locations first.",
        }
    
    # Calculate distance/duration using ONLY Google Maps API (no fallback)
    try:
        from google_maps import calculate_distance_duration_google
        google_result = await calculate_distance_duration_google(
            STATE["pickup"],
            STATE["dropoff"],
            STATE["stops"]
        )
        if not google_result.get("success", False):
            return {
                "ok": False,
                "error": "Failed to calculate distance using Google Maps. Please ensure GOOGLE_API_KEY is set.",
            }
        distance_km = google_result.get("distanceKm", 0.0)
        duration_min = google_result.get("durationMin", 0.0)
    except ValueError as e:
        # Check if it's a ZERO_RESULTS error (route not found)
        error_str = str(e)
        if "ZERO_RESULTS" in error_str or "Invalid route status" in error_str:
            pickup_addr = STATE.get("pickup_address", "pickup location")
            dropoff_addr = STATE.get("destination_address", "dropoff location")
            return {
                "ok": False,
                "error": f"Route not found. Please provide city names for both locations.",
                "error_type": "ROUTE_NOT_FOUND",
            }
        # Other ValueError
        print(f"⚠️ Google Maps calculation failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            "ok": False,
            "error": f"Failed to calculate distance using Google Maps: {str(e)}",
        }
    except Exception as e:
        print(f"⚠️ Google Maps calculation failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            "ok": False,
            "error": f"Failed to calculate distance using Google Maps: {str(e)}",
        }
    
    # Fare quote with calculated distance/duration from Google Maps
    fare = get_fare(
        STATE["pickup"],
        STATE["dropoff"],
        STATE["stops"],
        distance_km=distance_km,  # Pass Google Maps distance
        duration_min=duration_min,  # Pass Google Maps duration
    )
    if fare["status"] != 200:
        return {"ok": False, "stage": "fare", "status": fare["status"], "data": fare["data"]}

    # Ensure we know the active currency from backend
    currency = _ensure_currency()

    # Store for later use
    STATE["last_quote"] = fare
    STATE["computed_distance_km"] = distance_km
    STATE["computed_duration_min"] = duration_min

    # Format fare information
    fare_data = fare.get("data", {})
    ride_type_fares_raw = fare_data.get("rideTypeFares", [])
    
    # Deduplicate ride types by ride_type_id to avoid duplicates from API
    seen_ids = set()
    ride_type_fares = []
    for rt_fare in ride_type_fares_raw:
        ride_type_id = rt_fare.get("ride_type_id")
        if ride_type_id and ride_type_id not in seen_ids:
            seen_ids.add(ride_type_id)
            ride_type_fares.append(rt_fare)

    fare_list = []
    for rt_fare in ride_type_fares:
        fare_value = rt_fare.get("fare")
        # Ensure fare is a number, not None
        if fare_value is None:
            fare_value = 0.0
        # Determine currency from fare data or active currency
        currency_code = None
        currency_symbol = None
        if isinstance(rt_fare.get("currency"), str) and rt_fare.get("currency"):
            currency_code = rt_fare.get("currency")
        if currency:
            currency_code = currency.get("code") or currency_code
            # some backends may use different keys for symbol
            currency_symbol = (
                currency.get("symbol")
                or currency.get("symmetricSymbol")
                or None
            )
        fare_list.append({
            "ride_type_name": rt_fare.get("name"),
            "ride_type_id": rt_fare.get("ride_type_id"),
            "fare": float(fare_value),  # Ensure it's a float
            "currency": currency_code or "PKR",
            "currencySymbol": currency_symbol,
        })

    # Also include the selected ride type's fare & currency if available
    selected_ride_type_name = STATE.get("rideTypeName")
    selected_ride_type_fare = None
    selected_currency = None
    if selected_ride_type_name:
        selected_name = _normalize_ride_type_name(selected_ride_type_name)
        for item in fare_list:
            if _normalize_ride_type_name(item["ride_type_name"]) == selected_name:
                selected_ride_type_fare = item["fare"]
                selected_currency = {
                    "code": item.get("currency"),
                    "symbol": item.get("currencySymbol"),
                }
                break

    if selected_currency:
        STATE["currency"] = {
            "code": selected_currency.get("code"),
            "symbol": selected_currency.get("symbol"),
        }

    return {
        "ok": True,
        "distance_km": distance_km,
        "duration_min": duration_min,
        "ride_type_fares": fare_list,
        "selected_ride_type_fare": float(selected_ride_type_fare or 0.0),
        "selected_ride_type_name": selected_ride_type_name,
        "selected_currency": STATE.get("currency"),
    }

async def tool_get_fare_for_locations(pickup_place: str = None, dropoff_place: str = None):
    """
    Get fare quote for specific locations WITHOUT setting trip core.
    This is a standalone API query for when user asks "what is the fare from X to Y".
    
    Handles both place names and coordinate strings (lat,lng format).
    If current_location is used, converts coordinates to address first.
    """
    import re
    
    # Helper function to parse coordinates from string
    def _parse_coordinates(place_str: str | None) -> dict | None:
        """Parse coordinates from string formats like 'lat,lng' or 'Coordinates (lat, lng)'"""
        if not place_str or not isinstance(place_str, str):
            return None
        # Try to extract lat,lng from various formats
        patterns = [
            r"^([+-]?\d+\.?\d*)\s*,\s*([+-]?\d+\.?\d*)$",  # lat,lng
            r"\(?\s*([+-]?\d+\.?\d*)\s*,\s*([+-]?\d+\.?\d*)\s*\)?",  # (lat, lng)
        ]
        try:
            place_str_clean = place_str.strip()
        except AttributeError:
            return None
        for pattern in patterns:
            match = re.search(pattern, place_str_clean)
            if match:
                try:
                    lat = float(match.group(1))
                    lng = float(match.group(2))
                    # Validate reasonable coordinate ranges
                    if -90 <= lat <= 90 and -180 <= lng <= 180:
                        return {"lat": lat, "lng": lng}
                except (ValueError, IndexError):
                    continue
        return None
    
    try:
        # Handle pickup location
        pickup_coords = None
        pickup_address = None
        
        # Check if pickup_place is already coordinates (only if it's provided)
        parsed_coords = _parse_coordinates(pickup_place) if pickup_place else None
        if parsed_coords:
            # It's coordinates - use them directly
            pickup_coords = parsed_coords
            # Try to get address for better display
            try:
                from google_maps import get_google_maps_service
                service = get_google_maps_service()
                if service.googleApiKey:
                    address_result = await service.fetchAddressFromCoordinates(parsed_coords["lat"], parsed_coords["lng"])
                    pickup_address = address_result.get("address", pickup_place)
            except Exception:
                pickup_address = pickup_place
        else:
            # Check if pickup_place is missing and we should use current_location
            if not pickup_place or pickup_place.strip() == "":
                current_loc = STATE.get("current_location")
                if current_loc and current_loc.get("lat") and current_loc.get("lng"):
                    # Convert current location to address first
                    try:
                        from google_maps import get_google_maps_service
                        service = get_google_maps_service()
                        if service.googleApiKey:
                            address_result = await service.fetchAddressFromCoordinates(
                                current_loc['lat'], 
                                current_loc['lng']
                            )
                            pickup_address = address_result.get("address")
                            if pickup_address and pickup_address != "Address not found":
                                pickup_place = pickup_address
                                # Use original coordinates directly (don't re-resolve to avoid coordinate drift)
                                pickup_coords = {"lat": current_loc['lat'], "lng": current_loc['lng']}
                                pickup_address = pickup_address
                                print(f"[DEBUG] Using current location address: {pickup_address}, coordinates: {pickup_coords}")
                            else:
                                # Fallback: use current location coordinates directly
                                pickup_coords = {"lat": current_loc['lat'], "lng": current_loc['lng']}
                                pickup_address = f"{current_loc['lat']},{current_loc['lng']}"
                        else:
                            # No API key, use coordinates directly
                            pickup_coords = {"lat": current_loc['lat'], "lng": current_loc['lng']}
                            pickup_address = f"{current_loc['lat']},{current_loc['lng']}"
                    except Exception as e:
                        print(f"[DEBUG] Error converting current location to address: {e}")
                        # Fallback: use current location coordinates directly
                        pickup_coords = {"lat": current_loc['lat'], "lng": current_loc['lng']}
                        pickup_address = f"{current_loc['lat']},{current_loc['lng']}"
                else:
                    return {
                        "ok": False,
                        "error": "Pickup location is required. Please provide pickup location or ensure location services are enabled.",
                    }
            else:
                # Resolve place name to coordinates
                pickup_result = await tool_resolve_place_to_coordinates(pickup_place)
                if not pickup_result.get("ok"):
                    return {
                        "ok": False,
                        "error": pickup_result.get("error", "Failed to resolve pickup location."),
                    }
                pickup_coords = {"lat": pickup_result["lat"], "lng": pickup_result["lng"]}
                pickup_address = pickup_result.get("address", pickup_place)
        
        # Handle dropoff location
        if not dropoff_place or (isinstance(dropoff_place, str) and dropoff_place.strip() == ""):
            return {
                "ok": False,
                "error": "Dropoff location is required.",
            }
        
        dropoff_coords = None
        dropoff_address = None
        
        # Check if dropoff_place is already coordinates
        parsed_coords = _parse_coordinates(dropoff_place)
        if parsed_coords:
            # It's coordinates - use them directly
            dropoff_coords = parsed_coords
            # Try to get address for better display
            try:
                from google_maps import get_google_maps_service
                service = get_google_maps_service()
                if service.googleApiKey:
                    address_result = await service.fetchAddressFromCoordinates(parsed_coords["lat"], parsed_coords["lng"])
                    dropoff_address = address_result.get("address", dropoff_place)
            except Exception:
                dropoff_address = dropoff_place
        else:
            # Resolve place name to coordinates
            dropoff_result = await tool_resolve_place_to_coordinates(dropoff_place)
            if not dropoff_result.get("ok"):
                return {
                    "ok": False,
                    "error": dropoff_result.get("error", "Failed to resolve dropoff location."),
                }
            dropoff_coords = {"lat": dropoff_result["lat"], "lng": dropoff_result["lng"]}
            dropoff_address = dropoff_result.get("address", dropoff_place)
        
        # Calculate distance/duration using Google Maps API
        try:
            from google_maps import calculate_distance_duration_google
            google_result = await calculate_distance_duration_google(
                pickup_coords,
                dropoff_coords,
                None
            )
            if not google_result.get("success", False):
                return {
                    "ok": False,
                    "error": "Failed to calculate route distance.",
                }
            distance_km = google_result.get("distanceKm", 0.0)
            duration_min = google_result.get("durationMin", 0.0)
        except ValueError as e:
            error_str = str(e)
            if "ZERO_RESULTS" in error_str or "Invalid route status" in error_str:
                return {
                    "ok": False,
                    "error": "Route not found. Please provide city names for both locations.",
                    "error_type": "ROUTE_NOT_FOUND",
                }
            return {
                "ok": False,
                "error": "Failed to calculate route distance.",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": "Failed to calculate route distance.",
            }
        
        # Get fare quote
        fare = get_fare(
            pickup_coords,
            dropoff_coords,
            None,
            distance_km=distance_km,
            duration_min=duration_min,
        )
        if fare["status"] != 200:
            # Handle 502 Bad Gateway and other server errors
            if fare["status"] == 502:
                return {
                    "ok": False,
                    "error": "Fare service temporarily unavailable. Please try again in a moment.",
                    "error_type": "SERVICE_UNAVAILABLE",
                }
            # Extract error message from API response
            fare_data = fare.get("data", {})
            error_msg = _extract_user_friendly_error(fare_data, fare.get("status"))
            
            # Debug: Print what we're extracting
            if not error_msg or error_msg == "Invalid request. Please check your booking details.":
                print(f"[DEBUG] Fare error extraction - status: {fare.get('status')}, data: {fare_data}")
            
            # If extraction failed, try to get message directly
            if not error_msg or error_msg == "Invalid request. Please check your booking details.":
                if isinstance(fare_data, dict):
                    if "message" in fare_data:
                        msg = fare_data["message"]
                        if isinstance(msg, list) and len(msg) > 0:
                            error_msg = msg[0]
                        elif isinstance(msg, str):
                            error_msg = msg
            
            return {
                "ok": False,
                "error": error_msg or "Failed to get fare quote.",
            }
        
        # Format fare information
        currency = _ensure_currency()
        fare_data = fare.get("data", {})
        ride_type_fares_raw = fare_data.get("rideTypeFares", [])
        
        # Deduplicate ride types
        seen_ids = set()
        ride_type_fares = []
        for rt_fare in ride_type_fares_raw:
            ride_type_id = rt_fare.get("ride_type_id")
            if ride_type_id and ride_type_id not in seen_ids:
                seen_ids.add(ride_type_id)
                ride_type_fares.append(rt_fare)
        
        fare_list = []
        for rt_fare in ride_type_fares:
            fare_value = rt_fare.get("fare") or 0.0
            fare_list.append({
                "ride_type_name": rt_fare.get("name"),
                "ride_type_id": rt_fare.get("ride_type_id"),
                "fare": float(fare_value),
                "currency": currency.get("code", "PKR"),
                "currencySymbol": currency.get("symbol", "PKR"),
            })
        
        # Find cheapest fare
        cheapest = None
        cheapest_fare = float('inf')
        for item in fare_list:
            if item["fare"] < cheapest_fare:
                cheapest_fare = item["fare"]
                cheapest = item
        
        return {
            "ok": True,
            "distance_km": distance_km,
            "duration_min": duration_min,
            "ride_type_fares": fare_list,
            "cheapest_fare": cheapest_fare if cheapest else None,
            "cheapest_ride_type": cheapest["ride_type_name"] if cheapest else None,
            "currency": currency.get("code", "PKR"),
            "currencySymbol": currency.get("symbol", "PKR"),
        }
    except Exception as e:
        print(f"⚠️ Error getting fare for locations: {e}")
        import traceback
        traceback.print_exc()
        return {
            "ok": False,
            "error": "Failed to get fare quote.",
        }

async def tool_check_active_ride():
    """
    Check if user has an active/ongoing ride.
    Returns ride details if active ride exists, or indicates no active ride.
    Converts coordinates to addresses using Google Maps reverse geocoding.
    """
    try:
        from rides import active_ride_for_customer
        from google_maps import GoogleMapsService
        
        result = active_ride_for_customer()
        
        if result["status"] == 200 and result.get("data"):
            ride_data = result["data"]
            # Check for ride_id (API returns ride_id, not id)
            ride_id = ride_data.get("ride_id") or ride_data.get("id")
            # Also check if ride_status exists (indicates active ride)
            ride_status = ride_data.get("ride_status")
            
            if isinstance(ride_data, dict) and (ride_id or ride_status):
                # Format the response message
                driver_name = "a driver"
                pickup_location_raw = ride_data.get("pickup_location") or ride_data.get("pickup_address")
                dropoff_location_raw = ride_data.get("dropoff_location") or ride_data.get("dropoff_address")
                ride_type_name = "your ride type"
                fare = ride_data.get("agreed_price")
                
                # Helper function to extract lat/lng from various formats
                def extract_coordinates(loc):
                    """Extract lat/lng from string coordinates or dict with lat/lng keys"""
                    if isinstance(loc, dict):
                        lat = loc.get("lat") or loc.get("latitude")
                        lng = loc.get("lng") or loc.get("longitude")
                        if lat is not None and lng is not None:
                            return float(lat), float(lng)
                    elif isinstance(loc, str):
                        # Check for lat,lng format (e.g., "33.6844,73.0479")
                        import re
                        coord_pattern = r'^-?\d+\.?\d*,-?\d+\.?\d*$'
                        if re.match(coord_pattern, loc.strip()):
                            try:
                                parts = loc.split(',')
                                if len(parts) == 2:
                                    return float(parts[0].strip()), float(parts[1].strip())
                            except:
                                pass
                    return None, None
                
                # Helper function to check if location is coordinates (not an address string)
                def is_coordinates(loc):
                    """Check if location is coordinates (not an address string)"""
                    lat, lng = extract_coordinates(loc)
                    return lat is not None and lng is not None
                
                # Resolve pickup address
                pickup_address = "your pickup location"
                if pickup_location_raw:
                    lat, lng = extract_coordinates(pickup_location_raw)
                    if lat is not None and lng is not None:
                        # Reverse geocode coordinates to address
                        try:
                            maps_service = GoogleMapsService()
                            geocode_result = await maps_service.fetchAddressFromCoordinates(lat, lng)
                            pickup_address = geocode_result.get("address", pickup_location_raw)
                        except Exception as e:
                            print(f"⚠️ Error reverse geocoding pickup: {e}")
                            pickup_address = pickup_location_raw
                    else:
                        # Already an address string
                        pickup_address = pickup_location_raw
                
                # Resolve dropoff address
                dropoff_address = "your destination"
                if dropoff_location_raw:
                    lat, lng = extract_coordinates(dropoff_location_raw)
                    if lat is not None and lng is not None:
                        # Reverse geocode coordinates to address
                        try:
                            maps_service = GoogleMapsService()
                            geocode_result = await maps_service.fetchAddressFromCoordinates(lat, lng)
                            dropoff_address = geocode_result.get("address", dropoff_location_raw)
                        except Exception as e:
                            print(f"⚠️ Error reverse geocoding dropoff: {e}")
                            dropoff_address = dropoff_location_raw
                    else:
                        # Already an address string
                        dropoff_address = dropoff_location_raw
                
                # Extract driver name
                driver = ride_data.get("driver", {})
                if driver:
                    user = driver.get("user", {})
                    if user:
                        driver_name = user.get("name", "a driver")
                
                # Extract ride type name
                ride_type = ride_data.get("ride_type", {})
                if ride_type:
                    ride_type_name = ride_type.get("name", "your ride type")
                
                # Format fare
                currency = _ensure_currency()
                fare_str = _format_price(float(fare)) if fare else "an unknown amount"
                
                # Build message based on ride status
                # Only say "driver is on the way" for ASSIGNED status, not for IN_PROGRESS or other statuses
                status_message = ""
                if ride_status == "ASSIGNED":
                    status_message = " Your driver is on the way."
                elif ride_status in ["IN_PROGRESS", "STARTED", "PICKED_UP"]:
                    status_message = ""  # Don't say "on the way" for rides already in progress
                
                return {
                    "ok": True,
                    "has_active_ride": True,
                    "active_ride": True,
                    "message": f"Yes, you have an active {ride_type_name} ride.",
                    "pickup_address": pickup_address,  # Full address for LLM to format dynamically
                    "dropoff_address": dropoff_address,  # Full address for LLM to format dynamically
                    "driver_name": driver_name,
                    "fare": fare_str,
                    "status_message": status_message,
                    "ride_details": ride_data,
                    "rideId": ride_id,
                    "ride_status": ride_status,
                }
        
        return {
            "ok": True,
            "has_active_ride": False,
            "message": "No active ride found.",
        }
    except Exception as e:
        print(f"⚠️ Error checking active ride: {e}")
        import traceback
        traceback.print_exc()
        return {
            "ok": False,
            "error": "Failed to check ride status.",
        }

async def tool_create_ride_and_wait_for_bids(payment_via=None, is_scheduled=False, scheduled_at=None, offered_fair=0, is_family=False):
    """
    Create ride and wait for first bid. Returns the best (lowest fare) bid IMMEDIATELY when first bid arrives.
    Do NOT wait 5 seconds - present the bid as soon as it's available.
    """
    # Use stored quote data
    distance_km = STATE.get("computed_distance_km", 0.0)
    duration_min = STATE.get("computed_duration_min", 0.0)
    
    # If not stored, recalculate using ONLY Google Maps
    if not distance_km or not duration_min:
        try:
            from google_maps import calculate_distance_duration_google
            google_result = await calculate_distance_duration_google(
                STATE["pickup"],
                STATE["dropoff"],
                STATE["stops"]
            )
            if not google_result.get("success", False):
                return {
                    "ok": False,
                    "error": "Failed to calculate distance using Google Maps. Please ensure GOOGLE_API_KEY is set.",
                }
            distance_km = google_result.get("distanceKm", 0.0)
            duration_min = google_result.get("durationMin", 0.0)
        except Exception as e:
            print(f"⚠️ Google Maps calculation failed: {e}")
            return {
                "ok": False,
                "error": f"Failed to calculate distance using Google Maps: {str(e)}",
            }

    # Strings matching your example: "30 mins", "10 km"
    estimated_distance = f"{distance_km} km"
    estimated_time = f"{int(round(duration_min))} mins"

    chosen_name = STATE["rideTypeName"]
    ride_type_id = None
    
    # Get ride_type_id from stored quote or fare API
    if STATE.get("last_quote"):
        ride_type_id = pick_ride_type_id_from_fare(STATE["last_quote"].get("data", {}), chosen_name)
    
    if not ride_type_id:
        # Fallback: get from fare API (use stored Google Maps values if available)
        stored_distance = STATE.get("computed_distance_km")
        stored_duration = STATE.get("computed_duration_min")
        fare = get_fare(
            STATE["pickup"], 
            STATE["dropoff"], 
            STATE["stops"],
            distance_km=stored_distance if stored_distance else None,
            duration_min=stored_duration if stored_duration else None
        )
        ride_type_id = pick_ride_type_id_from_fare(fare.get("data", {}), chosen_name) or STATE["rideTypeId"]
    
    if not ride_type_id:
        return {
            "ok": False,
            "stage": "create",
            "error": "Could not resolve ride_type_id for selected ride type.",
        }

    # Get recommended fare from the last quote (selected_ride_type_fare)
    recommended_fare = 0
    if STATE.get("last_quote"):
        fare_data = STATE["last_quote"].get("data", {})
        ride_type_fares = fare_data.get("rideTypeFares", [])
        chosen_name = STATE["rideTypeName"]
        user_ride_type_normalized = _normalize_ride_type_name(chosen_name)
        for rt_fare in ride_type_fares:
            api_ride_type_normalized = _normalize_ride_type_name(rt_fare.get("name", ""))
            if api_ride_type_normalized == user_ride_type_normalized:
                recommended_fare = rt_fare.get("fare", 0)
                break
    
    # Use provided offered_fair if given, otherwise use recommended fare from quote
    final_offered_fair = offered_fair if offered_fair is not None and offered_fair > 0 else recommended_fare

    out = create_ride_request_exact(
        pickup=STATE["pickup"],
        dropoff=STATE["dropoff"],
        ride_type_id=ride_type_id,
        pickup_location=STATE["pickup_location"],
        dropoff_location=STATE["dropoff_location"],
        pickup_address=STATE["pickup_address"],
        destination_address=STATE["destination_address"],
        pickup_coordinates={"lat": STATE["pickup"].get("lat"), "lng": STATE["pickup"].get("lng")},
        destination_coordinates={"lat": STATE["dropoff"].get("lat"), "lng": STATE["dropoff"].get("lng")},
        stops=STATE["stops"],
        # courier optionals
        sender_phone_number=STATE["sender_phone_number"],
        receiver_phone_number=STATE["receiver_phone_number"],
        comments_for_courier=STATE["comments_for_courier"],
        package_size=STATE["package_size"],
        package_types=STATE["package_types"],
        # flags
        payment_via=payment_via or "CASH",
        is_hourly=False,
        is_scheduled=bool(is_scheduled),
        scheduled_at=scheduled_at if scheduled_at else (None if not is_scheduled else _iso_in(15)),
        offered_fair=final_offered_fair,  # Use recommended fare from quote
        is_family=bool(is_family),
        estimated_time=estimated_time,
        estimated_distance=estimated_distance,
    )

    if out["status"] not in (200, 201, 202):
        error_msg = _extract_user_friendly_error(out.get("data", {}), out.get("status"))
        return {
            "ok": False,
            "stage": "create",
            "status": out["status"],
            "error": error_msg,
            "data": out["data"],
        }

    rrid = out["rideRequestId"]
    STATE["rideRequestId"] = rrid
    STATE["customerId"] = None

    # Wait for first bid to arrive - present it IMMEDIATELY when it arrives
    bids = wait_for_bids(rrid, timeout_seconds=60, poll_interval=2)
    
    STATE["last_bids"] = bids or []

    if not STATE["last_bids"]:
        return {
            "ok": True,
            "rideRequestId": rrid,
            "bids": [],
            "best_bid": None,
            "message": "Ride created! Waiting for bids to arrive. I'll notify you when a bid arrives.",
        }

    # Find the bid with the lowest fare (best bid)
    best_bid = None
    best_price = float('inf')
    
    for b in STATE["last_bids"]:
        if isinstance(b, dict):
            _remember_customer_id_from_bid(b)  # Remember customer ID from each bid
            price = b.get("price") or b.get("amount") or b.get("fare")
            if price is not None and price < best_price:
                best_price = price
                best_bid = b
    
    if not best_bid:
        best_bid = STATE["last_bids"][0]
        _remember_customer_id_from_bid(best_bid)
    
    # Format best bid
    driver = best_bid.get("rider") or best_bid.get("driver") or {}
    user_profile = driver.get("userProfile", {})
    user = user_profile.get("user", {})
    driver_name = user.get("name") or "Unknown driver"
    price = best_bid.get("price") or best_bid.get("amount") or best_bid.get("fare")

    # Ensure price is a number, not None
    if price is None:
        price = 0.0
    amount_str = _format_price(float(price))
    
    return {
        "ok": True,
        "rideRequestId": rrid,
        "best_bid": {
            "id": best_bid.get("id"),
            "price": float(price),  # Ensure it's a float
            "driverName": driver_name or "Unknown driver",
            "etaSeconds": best_bid.get("etaSeconds") or best_bid.get("eta") or best_bid.get("estimatedArrivalSeconds"),
        },
        "all_bids_count": len(STATE["last_bids"]),
        "message": f"I found a bid from {driver_name} at {amount_str}.",
        "instruction": "Use best_bid.price and best_bid.driverName from this response when presenting the bid to the user. Do NOT make up values.",
    }

async def tool_create_request_and_poll(payment_via=None, is_scheduled=False, scheduled_at=None, offered_fair=0, is_family=False):
    # Calculate distance/duration using ONLY Google Maps API
    try:
        from google_maps import calculate_distance_duration_google
        google_result = await calculate_distance_duration_google(
            STATE["pickup"],
            STATE["dropoff"],
            STATE["stops"]
        )
        if not google_result.get("success", False):
            return {
                "ok": False,
                "error": "Failed to calculate distance using Google Maps. Please ensure GOOGLE_API_KEY is set.",
            }
        distance_km = google_result.get("distanceKm", 0.0)
        duration_min = google_result.get("durationMin", 0.0)
    except Exception as e:
        print(f"⚠️ Google Maps calculation failed: {e}")
        return {
            "ok": False,
            "error": f"Failed to calculate distance using Google Maps: {str(e)}",
        }
    
    # Fare quote with calculated distance/duration from Google Maps
    fare = get_fare(
        STATE["pickup"], 
        STATE["dropoff"], 
        STATE["stops"],
        distance_km=distance_km,  # Pass Google Maps distance
        duration_min=duration_min  # Pass Google Maps duration
    )
    if fare["status"] != 200:
        return {"ok": False, "stage": "fare", "status": fare["status"], "data": fare["data"]}

    # Strings matching your example: "30 mins", "10 km"
    estimated_distance = f"{distance_km} km"
    estimated_time = f"{int(round(duration_min))} mins"

    chosen_name = STATE["rideTypeName"]
    ride_type_id = pick_ride_type_id_from_fare(fare["data"], chosen_name) or STATE["rideTypeId"]
    if not ride_type_id:
        return {
            "ok": False,
            "stage": "fare",
            "error": "Could not resolve ride_type_id for selected ride type.",
            "quote": fare,
        }

    out = create_ride_request_exact(
        pickup=STATE["pickup"],
        dropoff=STATE["dropoff"],
        ride_type_id=ride_type_id,
        pickup_location=STATE["pickup_location"],
        dropoff_location=STATE["dropoff_location"],
        pickup_address=STATE["pickup_address"],
        destination_address=STATE["destination_address"],
        pickup_coordinates={"lat": STATE["pickup"].get("lat"), "lng": STATE["pickup"].get("lng")},
        destination_coordinates={"lat": STATE["dropoff"].get("lat"), "lng": STATE["dropoff"].get("lng")},
        stops=STATE["stops"],
        # courier optionals
        sender_phone_number=STATE["sender_phone_number"],
        receiver_phone_number=STATE["receiver_phone_number"],
        comments_for_courier=STATE["comments_for_courier"],
        package_size=STATE["package_size"],
        package_types=STATE["package_types"],
        # flags
        payment_via=payment_via or "CASH",
        is_hourly=False,
        is_scheduled=bool(is_scheduled),
        scheduled_at=scheduled_at or _iso_in(15),
        offered_fair=offered_fair if offered_fair is not None else 0,
        is_family=bool(is_family),
        estimated_time=estimated_time,
        estimated_distance=estimated_distance,
    )

    if out["status"] not in (200, 201, 202):
        error_msg = _extract_user_friendly_error(out.get("data", {}), out.get("status"))
        return {
            "ok": False,
            "stage": "create",
            "status": out["status"],
            "error": error_msg,
            "data": out["data"],
            "quote": fare,
            "requestBody": out.get("requestBody"),
        }

    rrid = out["rideRequestId"]
    STATE["rideRequestId"] = rrid
    STATE["customerId"] = None
    STATE["last_quote"] = fare

    bids = wait_for_bids(rrid, timeout_seconds=60, poll_interval=4)
    STATE["last_bids"] = bids or []

    slim = []
    for idx, b in enumerate(STATE["last_bids"], start=1):
        if isinstance(b, dict):
            _remember_customer_id_from_bid(b)
            driver = (
                b.get("rider") or b.get("driver") or {}
            )
            user_profile = driver.get("userProfile", {})
            user = user_profile.get("user", {})
            driver_name = user.get("name") or "Unknown driver"

            slim.append({
                "index": idx,
                "id": b.get("id"),
                "price": b.get("price") or b.get("amount") or b.get("fare"),
                "etaSeconds": b.get("etaSeconds") or b.get("eta") or b.get("estimatedArrivalSeconds"),
                "driverName": driver_name,
                "driverProfile": user.get("profile"),
            })
        else:
            slim.append({"index": idx, "raw": b})

    return {
        "ok": True,
        "rideRequestId": rrid,
        "bids": slim,
        "quote": fare,
        "requestBody": out.get("requestBody"),
    }

def tool_wait_for_bids(timeout_seconds: int = 30, poll_interval: int = 4):
    """
    Re-poll bids for the current rideRequestId. Wait 5 seconds, then return the best (lowest fare) bid.
    Use when user says "wait for more bids" or "wait".
    """
    import time
    rrid = STATE.get("rideRequestId")
    if not rrid:
        return {"ok": False, "error": "No active rideRequestId in state."}

    # Wait 5 seconds to allow more bids to arrive
    time.sleep(5)
    
    # Re-poll for latest bids
    bids = wait_for_bids(rrid, timeout_seconds=timeout_seconds, poll_interval=poll_interval)
    STATE["last_bids"] = bids or []

    if not STATE["last_bids"]:
        return {"ok": True, "rideRequestId": rrid, "bids": [], "message": "No new bids yet for this ride request."}

    # Find the bid with the lowest fare (best bid)
    best_bid = None
    best_price = float('inf')
    
    for b in STATE["last_bids"]:
        if isinstance(b, dict):
            _remember_customer_id_from_bid(b)  # Remember customer ID from each bid
            price = b.get("price") or b.get("amount") or b.get("fare")
            if price is not None and price < best_price:
                best_price = price
                best_bid = b
    
    if not best_bid:
        best_bid = STATE["last_bids"][0]
        _remember_customer_id_from_bid(best_bid)
    driver = best_bid.get("rider") or best_bid.get("driver") or {}
    user_profile = driver.get("userProfile", {})
    user = user_profile.get("user", {})
    driver_name = user.get("name") or "Unknown driver"
    if price is None:
        price = 0.0
    amount_str = _format_price(float(price))

    # Also format all bids for reference
    slim = []
    for idx, b in enumerate(STATE["last_bids"], start=1):
        if isinstance(b, dict):
            driver_obj = (b.get("rider") or b.get("driver") or {})
            user_profile_obj = driver_obj.get("userProfile", {})
            user_obj = user_profile_obj.get("user", {})
            driver_name_obj = user_obj.get("name") or "Unknown driver"
            price_obj = b.get("price") or b.get("amount") or b.get("fare")
            if price_obj is None:
                price_obj = 0.0
            slim.append({
                "index": idx,
                "id": b.get("id"),
                "price": price_obj,
                "driverName": driver_name_obj,
            })

    return {
        "ok": True,
        "rideRequestId": rrid,
        "best_bid": {
            "id": best_bid.get("id"),
            "price": float(price),
            "driverName": driver_name,
        },
        "all_bids": slim,
        "all_bids_count": len(STATE["last_bids"]),
        "message": f"Current best bid: {driver_name} at {amount_str}.",
        "instruction": "Use best_bid.price and best_bid.driverName from this response when presenting the bid to the user. Do NOT make up values.",
    }

def tool_accept_bid(bidId, customer_id=None):
    customer_id = customer_id or STATE.get("customerId")
    if not customer_id:
        return {"status": 400, "error": "Missing customerId from last bids. Please refresh bids and try again."}
    out = accept_bid(bidId, customer_id=customer_id)
    data = out.get("data")
    try:
        data = json.loads(data) if isinstance(data, str) else data
    except Exception:
        pass
    ride_id = None
    if isinstance(data, dict):
        ride_id = data.get("rideId") or data.get("id") or data.get("ride", {}).get("id")
    if ride_id:
        STATE["rideId"] = ride_id
    return {"status": out["status"], "rideId": ride_id, "raw": out["data"]}

def tool_accept_bid_choice(choice_index: int = None, driver_name: str = None):
    """
    Accept a bid by its index in STATE['last_bids'] or by driver_name.
    """
    bids = STATE.get("last_bids") or []
    if not bids:
        return {"ok": False, "error": "No bids cached. Call create_request_and_poll or wait_for_bids first."}

    selected = None

    if choice_index is not None:
        idx0 = choice_index - 1
        if idx0 < 0 or idx0 >= len(bids):
            return {"ok": False, "error": f"Invalid bid index {choice_index}. Only {len(bids)} bids available."}
        selected = bids[idx0]

    elif driver_name:
        dn = driver_name.strip().lower()
        for b in bids:
            if not isinstance(b, dict):
                continue
            driver = (b.get("rider") or b.get("driver") or {})
            user_profile = driver.get("userProfile", {})
            user = user_profile.get("user", {})
            name = (user.get("name") or "").lower()
            if dn == name or dn in name:
                selected = b
                break
        if not selected:
            return {"ok": False, "error": f"No bid found for driver '{driver_name}'."}
    else:
        return {"ok": False, "error": "Must provide either choice_index or driver_name."}

    bid_id = selected.get("id")
    if not bid_id:
        return {"ok": False, "error": "Selected bid has no id."}

    price = selected.get("price")
    driver = (selected.get("rider") or selected.get("driver") or {})
    user_profile = driver.get("userProfile", {})
    user = user_profile.get("user", {})
    driver_name_final = user.get("name") or "the selected driver"

    customer_id = _remember_customer_id_from_bid(selected)

    # Reuse low-level accept tool
    base = tool_accept_bid(bidId=bid_id, customer_id=customer_id)
    ok = base.get("status") in (200, 201, 202)

    if ok:
        amount_str = _format_price(price if isinstance(price, (int, float)) else 0.0)
        msg = f"Your ride has been created with {driver_name_final} at {amount_str}. Your driver is on the way."
    else:
        msg = f"Failed to accept the bid from {driver_name_final}. Status: {base.get('status')}."

    return {
        "ok": ok,
        "message": msg,
        "bidId": bid_id,
        "driverName": driver_name_final,
        "price": price,
        "result": base,
    }

async def tool_book_ride_with_details(
    dropoff_place: str,
    ride_type: str,
    pickup_place: str | None = None,
    stops=None,
    payment_via=None,
    is_scheduled=False,
    scheduled_at=None,
    is_family=False,
):
    """
    AUTONOMOUS BOOKING: When all booking details are collected, this tool automatically books the ride.
    It uses the LangGraph workflow to process everything end-to-end.
    
    If pickup_place is not provided, uses current_location from STATE (fetched from backend API).
    """
    # Store original pickup coordinates if we convert from current location
    original_pickup_coords = None
    
    # If pickup_place is not provided, try to use current location
    if not pickup_place:
        current_loc = STATE.get("current_location")
        if current_loc and current_loc.get("lat") and current_loc.get("lng"):
            # Store original coordinates BEFORE converting to address
            original_pickup_coords = {
                "lat": current_loc['lat'],
                "lng": current_loc['lng']
            }
            # Convert current location coordinates to address string for better driver experience
            try:
                from google_maps import get_google_maps_service
                service = get_google_maps_service()
                if service.googleApiKey:
                    address_result = await service.fetchAddressFromCoordinates(
                        current_loc['lat'], 
                        current_loc['lng']
                    )
                    address = address_result.get("address")
                    if address and address != "Address not found":
                        pickup_place = address
                        print(f"[DEBUG] Using current location address as pickup: {pickup_place}")
                        print(f"[DEBUG] Original coordinates preserved: {original_pickup_coords}")
                    else:
                        # Fallback to coordinates if address lookup fails
                        pickup_place = f"{current_loc['lat']},{current_loc['lng']}"
                        original_pickup_coords = None  # No need to preserve if using coordinates directly
                        print(f"[DEBUG] Address lookup failed, using coordinates: {pickup_place}")
                else:
                    # No API key, fallback to coordinates
                    pickup_place = f"{current_loc['lat']},{current_loc['lng']}"
                    original_pickup_coords = None  # No need to preserve if using coordinates directly
                    print(f"[DEBUG] No API key, using coordinates: {pickup_place}")
            except Exception as e:
                print(f"[DEBUG] Error converting coordinates to address: {e}, falling back to coordinates")
                pickup_place = f"{current_loc['lat']},{current_loc['lng']}"
                original_pickup_coords = None  # No need to preserve if using coordinates directly
        else:
            return {
                "ok": False,
                "error": "Pickup location is required. Please provide pickup location or ensure location services are enabled.",
            }
    
    # If pickup_place looks like formatted coordinates (lat,lng format), try to convert to address
    import re
    coord_match = re.search(r"^([+-]?\d+\.?\d*)\s*,\s*([+-]?\d+\.?\d*)$", pickup_place.strip())
    if coord_match and not original_pickup_coords:  # Only convert if we haven't already stored original coords
        # It's in lat,lng format - convert to address for better driver experience
        try:
            lat = float(coord_match.group(1))
            lng = float(coord_match.group(2))
            # Store original coordinates before converting
            original_pickup_coords = {"lat": lat, "lng": lng}
            from google_maps import get_google_maps_service
            service = get_google_maps_service()
            if service.googleApiKey:
                address_result = await service.fetchAddressFromCoordinates(lat, lng)
                address = address_result.get("address")
                if address and address != "Address not found":
                    pickup_place = address
                    print(f"[DEBUG] Converted coordinates to address: {pickup_place}")
                    print(f"[DEBUG] Original coordinates preserved: {original_pickup_coords}")
                else:
                    original_pickup_coords = None  # No need to preserve if conversion failed
                    print(f"[DEBUG] Address lookup failed for coordinates, keeping coordinates format")
        except Exception as e:
            original_pickup_coords = None  # No need to preserve if error occurred
            print(f"[DEBUG] Error converting coordinates to address: {e}, keeping coordinates format")
    
    # Handle formatted coordinate strings like "Coordinates (lat, lng)" or "(lat, lng)"
    coord_match_formatted = re.search(r"\(?\s*([+-]?\d+\.?\d*)\s*,\s*([+-]?\d+\.?\d*)\s*\)?", pickup_place)
    if coord_match_formatted and ("Coordinates" in pickup_place or "coordinates" in pickup_place.lower()) and not original_pickup_coords:
        # Extract coordinates and convert to address
        try:
            lat = float(coord_match_formatted.group(1))
            lng = float(coord_match_formatted.group(2))
            # Store original coordinates before converting
            original_pickup_coords = {"lat": lat, "lng": lng}
            from google_maps import get_google_maps_service
            service = get_google_maps_service()
            if service.googleApiKey:
                address_result = await service.fetchAddressFromCoordinates(lat, lng)
                address = address_result.get("address")
                if address and address != "Address not found":
                    pickup_place = address
                    print(f"[DEBUG] Converted formatted coordinates to address: {pickup_place}")
                    print(f"[DEBUG] Original coordinates preserved: {original_pickup_coords}")
                else:
                    # Extract clean lat,lng format as fallback
                    pickup_place = f"{lat},{lng}"
                    original_pickup_coords = None  # No need to preserve if conversion failed
                    print(f"[DEBUG] Address lookup failed, using clean coordinates: {pickup_place}")
            else:
                # Extract clean lat,lng format as fallback
                pickup_place = f"{coord_match_formatted.group(1)},{coord_match_formatted.group(2)}"
                original_pickup_coords = None  # No need to preserve if no API key
                print(f"[DEBUG] No API key, using clean coordinates: {pickup_place}")
        except Exception as e:
            original_pickup_coords = None  # No need to preserve if error occurred
            print(f"[DEBUG] Error converting formatted coordinates: {e}, using clean format")
            pickup_place = f"{coord_match_formatted.group(1)},{coord_match_formatted.group(2)}"
    
    # Store scheduling parameters in STATE for use by the workflow
    STATE["is_scheduled"] = is_scheduled
    STATE["scheduled_at"] = scheduled_at
    
    # Store original pickup coordinates in STATE if we converted from coordinates to address
    # This allows the workflow to use exact coordinates instead of re-resolving the address
    if original_pickup_coords:
        STATE["original_pickup_coords"] = original_pickup_coords
        print(f"[DEBUG] Stored original pickup coordinates in STATE: {original_pickup_coords}")
    else:
        STATE["original_pickup_coords"] = None
    
    # Log the parameters being passed for debugging
    print(f"[DEBUG] book_ride_with_details called with:")
    print(f"  pickup_place: '{pickup_place}'")
    print(f"  dropoff_place: '{dropoff_place}'")
    print(f"  ride_type: '{ride_type}'")
    print(f"  stops: {stops}")
    print(f"  is_scheduled: {is_scheduled}")
    print(f"  scheduled_at: {scheduled_at}")
    if original_pickup_coords:
        print(f"  original_pickup_coords: {original_pickup_coords}")
    
    try:
        from booking_workflow import process_booking_with_details
        result = await process_booking_with_details(
            pickup_place=pickup_place,
            dropoff_place=dropoff_place,
            ride_type=ride_type,
            stops=stops or [],
        )
        return result
    except ImportError:
        return {
            "ok": False,
            "error": "LangGraph booking workflow is not available. Please install langgraph: pip install langgraph",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"Failed to process booking: {str(e)}",
        }

async def tool_auto_book_ride(payment_via=None, is_scheduled=False, scheduled_at=None, is_family=False):
    """
    AUTONOMOUS AGENT: Automatically books a ride end-to-end.
    This tool:
    1. Creates the ride request
    2. Waits for bids to arrive
    3. Automatically accepts the best (lowest fare) bid
    4. Returns success message
    
    NO USER CONFIRMATION REQUIRED - fully automatic.
    """
    # Validate that all required state is set
    if not STATE.get("pickup") or not STATE.get("dropoff"):
        return {
            "ok": False,
            "error": "Pickup and dropoff locations must be set before auto-booking. Please set locations first.",
        }
    
    if not STATE.get("rideTypeName") or not STATE.get("rideTypeId"):
        return {
            "ok": False,
            "error": "Ride type must be selected before auto-booking. Please select a ride type first.",
        }
    
    # Step 1: Create ride and wait for bids (this already gets fare quote internally)
    # Use scheduling parameters from STATE if not provided as function arguments
    final_is_scheduled = is_scheduled if is_scheduled else STATE.get("is_scheduled", False)
    final_scheduled_at = scheduled_at if scheduled_at else STATE.get("scheduled_at")
    create_result = await tool_create_ride_and_wait_for_bids(
        payment_via=payment_via,
        is_scheduled=final_is_scheduled,
        scheduled_at=final_scheduled_at,
        is_family=is_family
    )
    
    if not create_result.get("ok"):
        # Extract user-friendly error message
        error_msg = create_result.get("error")
        if not error_msg:
            error_msg = _extract_user_friendly_error(create_result.get("data", {}), create_result.get("status"))
        return {
            "ok": False,
            "error": error_msg or "Failed to create ride request. Please try again.",
            "stage": "create",
        }
    
    # Step 2: Wait for bids if none arrived yet
    if not create_result.get("best_bid"):
        # Wait a bit more for bids
        import time
        time.sleep(5)
        wait_result = tool_wait_for_bids(timeout_seconds=30, poll_interval=2)
        
        if not wait_result.get("ok") or not wait_result.get("best_bid"):
            return {
                "ok": False,
                "error": "No bids received yet. Please try again in a moment.",
                "rideRequestId": create_result.get("rideRequestId"),
            }
        
        best_bid = wait_result.get("best_bid")
    else:
        best_bid = create_result.get("best_bid")
    
    # Step 3: Automatically accept the best bid (lowest fare)
    bid_id = best_bid.get("id")
    if not bid_id:
        return {
            "ok": False,
            "error": "Best bid has no ID. Cannot accept bid.",
        }
    
    # Accept the bid automatically
    accept_result = tool_accept_bid(bidId=bid_id, customer_id=STATE.get("customerId"))
    
    if accept_result.get("status") not in (200, 201, 202):
        error_msg = _extract_user_friendly_error(accept_result.get("raw", {}), accept_result.get("status"))
        return {
            "ok": False,
            "error": error_msg or f"Failed to accept bid. Status: {accept_result.get('status')}",
            "status": accept_result.get("status"),
        }
    
    # Success!
    driver_name = best_bid.get("driverName", "your driver")
    price = best_bid.get("price", 0.0)
    if price is None:
        price = 0.0
    ride_id = accept_result.get("rideId")
    
    if ride_id:
        STATE["rideId"] = ride_id
    
    amount_str = _format_price(price)
    return {
        "ok": True,
        "message": f"Your ride has been booked with {driver_name} at {amount_str}. Your driver is on the way.",
        "rideId": ride_id,
        "driverName": driver_name,
        "price": price,
        "bidId": bid_id,
    }

def tool_track_ride(rideId=None):
    """
    Get current ride details. Uses STATE['rideId'] if rideId is not provided or is invalid.
    """
    # Simple validation: check if rideId looks like a UUID (basic check without regex)
    ride_id_str = str(rideId) if rideId else ""
    is_valid_uuid = ride_id_str and len(ride_id_str) == 36 and ride_id_str.count('-') == 4
    
    # If rideId is not provided, invalid, or is a placeholder, use STATE
    if not rideId or not is_valid_uuid or '<' in ride_id_str or '>' in ride_id_str:
        rideId = STATE.get("rideId")
        if not rideId:
            return {
                "ok": False,
                "error": "No ride ID available. Please provide a valid ride ID or ensure a ride has been created and accepted.",
            }
    
    return get_customer_ride(rideId)

async def tool_cancel_ride(rideId, reason=None):
    """
    Cancel a ride. Always checks for active ride first and uses that ride ID.
    This ensures we always cancel the correct/current ride, not an old one.
    """
    import re
    
    # Validate rideId is a UUID format (basic check)
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    
    # First, always check for active ride to get the correct ride ID
    try:
        active_ride_result = await tool_check_active_ride()
        if active_ride_result.get("ok") and active_ride_result.get("has_active_ride"):
            active_ride_id = active_ride_result.get("rideId")
            if active_ride_id:
                # Always use the active ride ID (most common case: user says "cancel this ride")
                print(f"✅ Found active ride ID: {active_ride_id}. Using it to cancel ride.")
                rideId = active_ride_id
            else:
                return {
                    "ok": False,
                    "error": "Could not find active ride ID. No active ride to cancel.",
                }
        else:
            # No active ride found - use provided rideId if it's valid
            if not rideId or not isinstance(rideId, str):
                return {
                    "ok": False,
                    "error": "No active ride found and no valid ride ID provided. Please provide a valid ride ID.",
                }
            
            # Validate provided rideId is a UUID
            if not re.match(uuid_pattern, rideId.lower().strip()):
                return {
                    "ok": False,
                    "error": f"Invalid ride ID format: '{rideId}' is not a valid UUID. No active ride found to cancel.",
                }
            
            # Use provided rideId (user wants to cancel a specific ride, not active one)
            print(f"⚠️ No active ride found. Using provided ride ID: {rideId}")
    except Exception as e:
        print(f"⚠️ Error checking active ride: {e}")
        # Fallback: use provided rideId if it's valid
        if not rideId or not isinstance(rideId, str):
            return {
                "ok": False,
                "error": f"Error checking active ride and no valid ride ID provided: {str(e)}",
            }
        
        if not re.match(uuid_pattern, rideId.lower().strip()):
            return {
                "ok": False,
                "error": f"Error checking active ride and invalid ride ID format: '{rideId}' is not a valid UUID.",
            }
        
        print(f"⚠️ Using provided ride ID as fallback: {rideId}")
    
    # Final validation
    if not re.match(uuid_pattern, rideId.lower().strip()):
        return {
            "ok": False,
            "error": f"Invalid ride ID: '{rideId}' is not a valid UUID format.",
        }
    
    # Cancel the ride
    return cancel_ride_as_customer(rideId)

def call_tool(name, args):
    if name == "request_map_selection":   return tool_request_map_selection(**args)
    if name == "resolve_place_to_coordinates":
        # Handle async function
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(tool_resolve_place_to_coordinates(**args))
    if name == "set_trip_core":
        # Handle async function
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(tool_set_trip_core(**args))
    if name == "set_stops":
        # Handle async function
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(tool_set_stops(**args))
    if name == "set_courier_fields":      return tool_set_courier_fields(**args)
    if name == "list_ride_types":         return [{"id": t.get("id"), "name": t.get("name"), "active": t.get("isActive")} for t in list_ride_types()]
    if name == "set_ride_type":
        # Handle async function
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(tool_set_ride_type(**args))
    if name == "book_ride_with_details":
        # Handle async function
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(tool_book_ride_with_details(**args))
    if name == "auto_book_ride":
        # Handle async function
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(tool_auto_book_ride(**args))
    if name == "get_fare_quote":
        # Handle async function
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(tool_get_fare_quote())
    if name == "get_fare_for_locations":
        # Handle async function
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(tool_get_fare_for_locations(**args))
    if name == "check_active_ride":
        return tool_check_active_ride()
    if name == "create_ride_and_wait_for_bids":
        # Handle async function
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(tool_create_ride_and_wait_for_bids(**args))
    if name == "create_request_and_poll": 
        # Handle async function
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(tool_create_request_and_poll(**args))
    if name == "wait_for_bids":           return tool_wait_for_bids(**args)
    if name == "accept_bid_choice":       return tool_accept_bid_choice(**args)
    if name == "accept_bid":              return tool_accept_bid(**args)
    if name == "track_ride":              return tool_track_ride(**args)
    if name == "cancel_ride":             return tool_cancel_ride(**args)
    return {"error": "unknown tool"}

def chat_loop():
    if not ensure_login():
        return

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "assistant", "content": "Hi! I am LumiDrive, your autonomous ride-booking assistant. Tell me where you want to go and which ride type you prefer, and I will book your ride."}
    ]
    print("LumiDrive ready. (Ctrl+C to exit)\n")

    while True:
        user = input("You: ").strip()
        if not user:
            continue

        # No local inference - let the assistant handle it via tools
            messages.append({"role": "user", "content": user})

        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=[{"type": "function", "function": t["function"]} for t in tools],
            tool_choice="auto",
        )
        msg = resp.choices[0].message

        if msg.tool_calls:
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

                # If set_trip_core is called without coordinates, the assistant should have extracted
                # the information intelligently. If coordinates are missing, let the tool handle the error.
                # No regex parsing - assistant handles extraction dynamically.

                try:
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

            follow = client.chat.completions.create(model=MODEL, messages=messages)
            final_msg = follow.choices[0].message
            # Strip asterisks from assistant output
            cleaned_content = strip_asterisks(final_msg.content or "")
            print("LumiDrive:", cleaned_content, "\n")
            messages.append({"role": "assistant", "content": cleaned_content})
        else:
            # Strip asterisks from assistant output
            cleaned_content = strip_asterisks(msg.content or "")
            print("LumiDrive:", cleaned_content, "\n")
            messages.append({"role": "assistant", "content": cleaned_content})

if __name__ == "__main__":
    try:
        chat_loop()
    except KeyboardInterrupt:
        print("\nBye!")
