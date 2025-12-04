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

load_dotenv()
MODEL = os.getenv("MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("Please set OPENAI_API_KEY in .env")
    sys.exit(1)

client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM = """You are LumiDrive, an intelligent ride-booking assistant. Your job is to help users book rides by collecting all necessary information and then automatically processing the booking.

SMART BOOKING WORKFLOW:
1. COLLECT INFORMATION: When a user wants to book a ride, intelligently extract from their messages:
   - Pickup location (place name, address, or coordinates)
   - Dropoff location (place name, address, or coordinates)
   - Ride type (e.g., "LUMI_GO", "Lumi GO", "Courier", "Bike", etc.)

2. RESOLVE LOCATIONS (FOR BOOKING, LET TOOLS HANDLE IT): 
   - For normal booking flows, DO NOT call resolve_place_to_coordinates or set_trip_core directly once you have all details.
   - Instead, call book_ride_with_details and let the internal workflow resolve coordinates and set the trip.
   - Only call resolve_place_to_coordinates directly if the user explicitly asks for coordinates/address information (not for booking).

3. ASK FOR MISSING INFO: If any detail is missing (pickup, dropoff, or ride type), politely ask the user for it.

4. AUTOMATIC BOOKING (IMMEDIATE - NO CONFIRMATION NEEDED): Once you have ALL three pieces of information (pickup, dropoff, ride_type), IMMEDIATELY call book_ride_with_details without asking for confirmation. Call it with:
   - pickup_place: The pickup location (place name or coordinates)
   - dropoff_place: The dropoff location (place name, address, or coordinates)
   - ride_type: The selected ride type name
   
   This tool will automatically:
   - Resolve locations to coordinates if needed
   - Set trip core
   - Get fare quote
   - Create ride request
   - Wait for bids
   - Accept the best (lowest fare) bid
   - Return success message

5. CONFIRM BOOKING: Inform the user that their ride has been booked successfully, in a single concise message.

CRITICAL RULES:
- Be intelligent and natural in conversation - extract information from user messages without being robotic.
- If user provides complete information in one message (e.g., "I want to go from X to Y on Lumi GO"), extract all details and IMMEDIATELY call book_ride_with_details - DO NOT wait for user confirmation.
- If information is missing, ask for it naturally (e.g., "Which ride type would you like?" or "Where would you like to go?").
- AFTER you have all three details and have called book_ride_with_details, DO NOT ask the user for anything else; wait for the tool result and then reply with a single final confirmation.
- NEVER ask "should I book?", "proceed?", or similar questions - just book automatically when you have all info.
- NEVER say "please hold on", "I'll proceed to", "I'll go ahead and", or other filler status messages. Minimize intermediate updates.
- NEVER use regex patterns or hardcoded logic - use your intelligence to understand user intent.
- NEVER guess coordinates - use tools (through book_ride_with_details or resolve_place_to_coordinates) to get them.
- NEVER hallucinate ride types, fares, or driver names - use actual API data.
- **CRITICAL ERROR HANDLING**: When a tool returns {"ok": False, "error": "..."}, ALWAYS report the exact error message to the user in plain language. NEVER say the booking was successful if there's an error. NEVER make up success messages when tools fail. If there's an error, tell the user what went wrong clearly and concisely.
- Keep responses friendly, concise, and helpful, ideally confirming the booking in one message once it's done.
- The book_ride_with_details tool handles everything automatically - you just need to collect the info and call it IMMEDIATELY.
"""

tools = [
  { "type":"function", "function": {
      "name":"request_map_selection",
      "description":"Request the user to select pickup and dropoff locations on a map. Use this when the user wants to book a ride but hasn't provided specific coordinates or addresses. The frontend will display a map interface for location selection. Call this when user says they want to book a ride but locations are not yet set.",
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
          "place_name":{"type":"string","description":"Place name or address to resolve, e.g. 'F-6 Markaz, Islamabad' or 'Gaddafi Stadium, Lahore'"},
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
      "description":"Provide an ordered list of stops (0..N). Each stop may include address.",
      "parameters":{
        "type":"object",
        "properties":{
          "stops":{"type":"array","items":{
            "type":"object",
            "properties":{
              "lat":{"type":"number"},
              "lng":{"type":"number"},
              "address":{"type":"string"},
              "order":{"type":"integer"}
            },
            "required":["lat","lng"]
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
      "description":"Fetch available ride types from the API. Call this AUTOMATICALLY after set_trip_core is successfully called. Returns ALL ride types with their 'active' status. You MUST present ALL active ride types (where active=true) to the user - never filter or omit any. NEVER make up or guess ride types - always call this function to get the actual list from the API.",
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
      "description":"AUTONOMOUS BOOKING: When you have collected ALL required booking details (pickup location, dropoff location, and ride type), call this tool to automatically book the ride. This tool will: 1) Resolve locations to coordinates if needed, 2) Set trip core, 3) Get fare quote, 4) Create ride request, 5) Wait for bids, 6) Automatically accept the best (lowest fare) bid, 7) Return success message. ONLY call this when you have ALL three: pickup_place (or coordinates), dropoff_place (or coordinates), and ride_type. If any detail is missing, ask the user for it first.",
      "parameters":{
        "type":"object",
        "properties":{
          "pickup_place":{"type":"string","description":"Pickup location as place name (e.g., 'F-6 Markaz, Islamabad') or coordinates (e.g., '33.6956,73.2205'). If coordinates are provided, they should be in 'lat,lng' format."},
          "dropoff_place":{"type":"string","description":"Dropoff location as place name (e.g., 'E-11, Islamabad') or coordinates (e.g., '33.6992,72.9744'). If coordinates are provided, they should be in 'lat,lng' format."},
          "ride_type":{"type":"string","description":"Ride type name (e.g., 'LUMI_GO', 'Lumi GO', 'Courier', 'Bike', etc.)"},
          "payment_via":{"type":"string","enum":["WALLET","CASH","CARD"],"description":"Payment method (optional, defaults to CASH)"},
          "is_scheduled":{"type":"boolean","description":"Whether this is a scheduled ride (optional)"},
          "scheduled_at":{"type":"string","description":"ISO8601 timestamp if is_scheduled is true (optional)"},
          "is_family":{"type":"boolean","description":"Whether this is a family ride (optional)"}
        },
        "required":["pickup_place","dropoff_place","ride_type"]
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
      "description":"Cancel a ride",
      "parameters":{"type":"object","properties":{"rideId":{"type":"string"},"reason":{"type":"string"}},"required":["rideId"]}
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
    Extract a user-friendly error message from API response.
    Handles various error response formats and status codes.
    """
    if not api_response:
        if status_code == 409:
            return "You already have an active ride request. Please wait for it to complete or cancel it before booking a new ride."
        elif status_code == 400:
            return "Invalid request. Please check your booking details and try again."
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
        return "You already have an active ride request. Please wait for it to complete or cancel it before booking a new ride."
    elif status_code == 400:
        return "Invalid request. Please check your booking details and try again."
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
    if not place_name or len(place_name.strip()) < 3:
        return {
            "ok": False,
            "error": "Place name must be at least 3 characters long.",
        }
    
    try:
        from google_maps import get_google_maps_service
        service = get_google_maps_service()
        
        if not service.googleApiKey:
            return {
                "ok": False,
                "error": "Google Maps API key not configured. Cannot resolve place names.",
            }
        
        # First, try to get place suggestions
        predictions = await service.fetchPlaces(place_name)
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
    Parse pickup and dropoff locations from user message.
    Handles formats like:
    - "Pickup: Address (lat, lng), Dropoff: Address (lat, lng)"
    - "Selected locations: Pickup: ... (lat, lng), Dropoff: ... (lat, lng)"
    """
    import re
    # Pattern to match coordinates in parentheses: (lat, lng)
    coord_pattern = r'\(([+-]?\d+\.?\d*),\s*([+-]?\d+\.?\d*)\)'
    
    # Try to find pickup and dropoff patterns
    pickup_match = re.search(r'pickup[:\s]+([^(]+?)(?:\(([+-]?\d+\.?\d*),\s*([+-]?\d+\.?\d*)\))?', message, re.IGNORECASE)
    dropoff_match = re.search(r'dropoff[:\s]+([^(]+?)(?:\(([+-]?\d+\.?\d*),\s*([+-]?\d+\.?\d*)\))?', message, re.IGNORECASE)
    
    # Alternative: find all coordinate pairs and assume first is pickup, second is dropoff
    all_coords = re.findall(coord_pattern, message)
    
    result = {}
    
    if pickup_match and dropoff_match:
        pickup_addr = pickup_match.group(1).strip()
        dropoff_addr = dropoff_match.group(1).strip()
        
        # Try to get coordinates from the match groups or from all_coords
        if pickup_match.group(2) and pickup_match.group(3):
            pickup_lat = float(pickup_match.group(2))
            pickup_lng = float(pickup_match.group(3))
        elif len(all_coords) >= 1:
            pickup_lat = float(all_coords[0][0])
            pickup_lng = float(all_coords[0][1])
        else:
            return None
            
        if dropoff_match.group(2) and dropoff_match.group(3):
            dropoff_lat = float(dropoff_match.group(2))
            dropoff_lng = float(dropoff_match.group(3))
        elif len(all_coords) >= 2:
            dropoff_lat = float(all_coords[1][0])
            dropoff_lng = float(all_coords[1][1])
        else:
            return None
        
        result = {
            "pickup": {"lat": pickup_lat, "lng": pickup_lng, "address": pickup_addr},
            "dropoff": {"lat": dropoff_lat, "lng": dropoff_lng, "address": dropoff_addr},
            "pickup_address": pickup_addr,
            "destination_address": dropoff_addr,
        }
    elif len(all_coords) >= 2:
        # Fallback: if we have at least 2 coordinate pairs, use them
        pickup_lat = float(all_coords[0][0])
        pickup_lng = float(all_coords[0][1])
        dropoff_lat = float(all_coords[1][0])
        dropoff_lng = float(all_coords[1][1])
        
        # Try to extract addresses
        parts = re.split(r'pickup|dropoff', message, flags=re.IGNORECASE)
        pickup_addr = parts[1].split('(')[0].strip() if len(parts) > 1 else "Pickup"
        dropoff_addr = parts[2].split('(')[0].strip() if len(parts) > 2 else "Dropoff"
        
        result = {
            "pickup": {"lat": pickup_lat, "lng": pickup_lng, "address": pickup_addr},
            "dropoff": {"lat": dropoff_lat, "lng": dropoff_lng, "address": dropoff_addr},
            "pickup_address": pickup_addr,
            "destination_address": dropoff_addr,
        }
    
    return result if result else None

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

def tool_set_stops(stops):
    norm = []
    for idx, s in enumerate(stops):
        norm.append({
            "lat": s.get("lat") or s.get("latitude"),
            "lng": s.get("lng") or s.get("longitude"),
            **({"address": s.get("address")} if s.get("address") else {}),
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
        return {
            "ok": False,
            "error": f"Ride type '{ride_type_name}' not found. Available ride types: {', '.join(available_names)}",
            "available_ride_types": available_names,
        }
    
    # Set the ride type in STATE
    STATE["rideTypeName"] = matched_ride_type.get("name")
    STATE["rideTypeId"] = matched_ride_type.get("id")
    
    # Automatically call get_fare_quote
    fare_result = await tool_get_fare_quote()
    
    if not fare_result.get("ok"):
        return {
            "ok": False,
            "error": f"Failed to get fare quote: {fare_result.get('error')}",
            "ride_type_set": True,
            "ride_type_name": STATE["rideTypeName"],
            "ride_type_id": STATE["rideTypeId"],
        }
    
    # AUTOMATICALLY book the ride - no user confirmation needed
    booking_result = await tool_auto_book_ride()
    
    if not booking_result.get("ok"):
        return {
            "ok": False,
            "error": f"Failed to book ride: {booking_result.get('error')}",
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
        scheduled_at=scheduled_at or _iso_in(15),
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
    driver = (best_bid.get("rider") or best_bid.get("driver") or {})
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
        "message": f"<p>I found a bid from <b>{driver_name}</b> at {amount_str}.</p>",
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

    # Format best bid
    driver = (best_bid.get("rider") or best_bid.get("driver") or {})
    user_profile = driver.get("userProfile", {})
    user = user_profile.get("user", {})
    driver_name = user.get("name") or "Unknown driver"
    price = best_bid.get("price") or best_bid.get("amount") or best_bid.get("fare")

    # Ensure price is a number, not None
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
        "message": f"<p>Current best bid: <b>{driver_name}</b> at {amount_str}.</p>",
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
        msg = f"<p>Your ride has been created with <b>{driver_name_final}</b> at {amount_str}. Your driver is on the way.</p>"
    else:
        msg = f"<p>Failed to accept the bid from <b>{driver_name_final}</b>. Status: {base.get('status')}.</p>"

    return {
        "ok": ok,
        "message": msg,
        "bidId": bid_id,
        "driverName": driver_name_final,
        "price": price,
        "result": base,
    }

async def tool_book_ride_with_details(
    pickup_place: str,
    dropoff_place: str,
    ride_type: str,
    payment_via=None,
    is_scheduled=False,
    scheduled_at=None,
    is_family=False,
):
    """
    AUTONOMOUS BOOKING: When all booking details are collected, this tool automatically books the ride.
    It uses the LangGraph workflow to process everything end-to-end.
    """
    try:
        from booking_workflow import process_booking_with_details
        result = await process_booking_with_details(
            pickup_place=pickup_place,
            dropoff_place=dropoff_place,
            ride_type=ride_type,
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
    create_result = await tool_create_ride_and_wait_for_bids(
        payment_via=payment_via,
        is_scheduled=is_scheduled,
        scheduled_at=scheduled_at,
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
        "message": f"<p>Your ride has been booked with <b>{driver_name}</b> at {amount_str}. Your driver is on the way.</p>",
        "rideId": ride_id,
        "driverName": driver_name,
        "price": price,
        "bidId": bid_id,
    }

def tool_track_ride(rideId=None):
    """
    Get current ride details. Uses STATE['rideId'] if rideId is not provided or is invalid.
    """
    import re
    
    # Validate rideId format (UUID)
    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)
    
    # If rideId is not provided, invalid, or is a placeholder, use STATE
    if not rideId or not uuid_pattern.match(str(rideId)) or '<' in str(rideId) or '>' in str(rideId):
        rideId = STATE.get("rideId")
        if not rideId:
            return {
                "ok": False,
                "error": "No ride ID available. Please provide a valid ride ID or ensure a ride has been created and accepted.",
            }
    
    return get_customer_ride(rideId)

def tool_cancel_ride(rideId, reason=None):
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
    if name == "set_stops":               return tool_set_stops(**args)
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
        {"role": "assistant", "content": "<p>Hi! I am <b>LumiDrive</b>, your autonomous ride-booking assistant. Tell me where you want to go and which ride type you prefer, and I will book your ride.</p>"}
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

                # If set_trip_core is called without coordinates, try to parse from message
                if tc.function.name == "set_trip_core" and (not args or "pickup" not in args or "dropoff" not in args):
                    # Try to parse coordinates from user message
                    parsed = _parse_locations_from_message(user)
                    if parsed and parsed.get("pickup") and parsed.get("dropoff"):
                        args = {
                            "pickup": parsed["pickup"],
                            "dropoff": parsed["dropoff"],
                            "pickup_address": parsed.get("pickup_address"),
                            "destination_address": parsed.get("destination_address"),
                        }
                    else:
                        # If no coordinates found, return error - don't guess
                        result = {
                            "ok": False,
                            "error": "Coordinates (lat, lng) are required. Please provide coordinates or use the map to select locations.",
                        }
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tc.function.name,
                            "content": json.dumps(result),
                        })
                        continue

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
            print("LumiDrive:", final_msg.content, "\n")
            messages.append({"role": "assistant", "content": final_msg.content})
        else:
            print("LumiDrive:", msg.content, "\n")
            messages.append({"role": "assistant", "content": msg.content})

if __name__ == "__main__":
    try:
        chat_loop()
    except KeyboardInterrupt:
        print("\nBye!")
