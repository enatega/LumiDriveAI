# # rides.py
# import os, json, time, math
# from dotenv import load_dotenv
# from api import get, post, patch

# load_dotenv()

# RIDE_TYPES_PATH           = os.getenv("RIDE_TYPES_PATH")
# CREATE_REQUEST_PATH       = os.getenv("CREATE_REQUEST_PATH")
# BIDS_FOR_REQUEST_PATH     = os.getenv("BIDS_FOR_REQUEST_PATH")
# BID_ACCEPT_PATH           = os.getenv("BID_ACCEPT_PATH")
# CUSTOMER_RIDE_PATH        = os.getenv("CUSTOMER_RIDE_PATH")
# CANCEL_AS_CUSTOMER_PATH   = os.getenv("CANCEL_AS_CUSTOMER_PATH")
# FARE_PATH                 = os.getenv("FARE_PATH", "/api/v1/rides/fare/all")

# # Optional helpers/endpoints
# OFFER_FARE_PATH                 = "/api/v1/rides/{id}/offer-fare"
# RAISE_FARE_PATH                 = "/api/v1/rides/ride-request/raise-fare"
# START_RIDE_PATH                 = "/api/v1/rides/{rideId}/start-ride/{riderId}"
# COMPLETE_RIDE_PATH              = "/api/v1/rides/{rideId}/complete-ride"
# RIDE_DETAILS_PATH               = "/api/v1/rides/ride-details/{rideId}"
# ONGOING_ACTIVE_CUSTOMER_PATH    = "/api/v1/rides/ongoing/active/customer"

# DEFAULT_PAYMENT_VIA       = os.getenv("DEFAULT_PAYMENT_VIA", "WALLET")
# DEFAULT_IS_HOURLY         = os.getenv("DEFAULT_IS_HOURLY", "false").lower() == "true"
# DEFAULT_IS_SCHEDULED      = os.getenv("DEFAULT_IS_SCHEDULED", "false").lower() == "true"
# CUSTOMER_ID               = os.getenv("CUSTOMER_ID")  # optional

# # Fare tuning (used for distance/duration estimation)
# FARE_AVG_SPEED_KMH        = float(os.getenv("FARE_AVG_SPEED_KMH", "22"))  # city-ish avg
# FARE_WAITING_MINUTES      = float(os.getenv("FARE_WAITING_MINUTES", "0"))
# FARE_IS_NIGHT             = os.getenv("FARE_IS_NIGHT", "false").lower() == "true"


# def _fill(path: str, **params):
#     out = path
#     for k, v in params.items():
#         out = out.replace("{"+k+"}", str(v))
#     return out


# def _patch_json(path: str, body: dict | None):
#     resp = patch(path, body)
#     try:
#         return {"status": resp.status_code, "data": resp.json()}
#     except Exception:
#         return {"status": resp.status_code, "data": resp.text}


# def list_ride_types():
#     resp = get(RIDE_TYPES_PATH)
#     try:
#         return resp.json() if resp.ok else []
#     except Exception:
#         return []


# # ---------------------------
# # Distance helpers
# # ---------------------------
# def _haversine_km(a: dict, b: dict) -> float:
#     lat1, lon1 = float(a["lat"]), float(a["lng"])
#     lat2, lon2 = float(b["lat"]), float(b["lng"])
#     R = 6371.0
#     dlat = math.radians(lat2 - lat1)
#     dlon = math.radians(lon2 - lon1)
#     s1 = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
#     return 2 * R * math.asin(math.sqrt(s1))


# def _route_distance_km(pickup: dict, dropoff: dict, stops: list | None) -> float:
#     points = [pickup] + (stops or []) + [dropoff]
#     dist = 0.0
#     for i in range(len(points) - 1):
#         if points[i].get("lat") is None or points[i+1].get("lat") is None:
#             continue
#         dist += _haversine_km(points[i], points[i+1])
#     return max(dist, 0.0)


# # ---------------------------
# # Fare (use documented query params)
# # ---------------------------
# def get_fare(pickup: dict, dropoff: dict, stops: list | None = None):
#     """
#     Calls /api/v1/rides/fare/all with the official parameters:
#     - isNightRide, waitingMinutes, isHourly, durationMin, distanceKm

#     We estimate distance/duration from coordinates so backend can compute a fare.
#     Even if fare is null, computed distance & duration are returned for use in
#     the create-ride payload as estimated_distance / estimated_time.
#     """
#     p = {
#         "lat": pickup.get("lat") or pickup.get("latitude"),
#         "lng": pickup.get("lng") or pickup.get("longitude"),
#     }
#     d = {
#         "lat": dropoff.get("lat") or dropoff.get("latitude"),
#         "lng": dropoff.get("lng") or dropoff.get("longitude"),
#     }
#     s_clean = []
#     for s in (stops or []):
#         if s.get("lat") is not None and s.get("lng") is not None:
#             s_clean.append({"lat": s.get("lat"), "lng": s.get("lng")})

#     distance_km = _route_distance_km(p, d, s_clean)
#     duration_min = (distance_km / max(FARE_AVG_SPEED_KMH, 1e-6)) * 60.0

#     params = {
#         "isNightRide": str(FARE_IS_NIGHT).lower(),
#         "waitingMinutes": FARE_WAITING_MINUTES,
#         "isHourly": "false",
#         "durationMin": round(duration_min, 2),
#         "distanceKm": round(distance_km, 3),
#     }

#     resp = get(FARE_PATH, params=params)
#     try:
#         data = resp.json()
#     except Exception:
#         data = {"raw": resp.text}

#     return {
#         "status": resp.status_code,
#         "data": data,
#         "computed": {
#             "distanceKm": params["distanceKm"],
#             "durationMin": params["durationMin"],
#         },
#     }


# def pick_ride_type_id_from_fare(fare_json: dict, desired_name: str | None) -> str | None:
#     if not desired_name:
#         return None
#     try:
#         for it in (fare_json.get("rideTypeFares") or []):
#             name = (it.get("name") or "").strip().lower()
#             if name == desired_name.strip().lower():
#                 return it.get("ride_type_id")
#     except Exception:
#         pass
#     return None


# # -------------------------------------------------
# # Create ride request with EXACT body (your spec)
# # -------------------------------------------------
# def create_ride_request_exact(
#     pickup: dict,
#     dropoff: dict,
#     ride_type_id: str,
#     pickup_location: str,
#     dropoff_location: str,
#     pickup_address: str,
#     destination_address: str,
#     pickup_coordinates: dict,
#     destination_coordinates: dict,
#     stops: list | None = None,
#     # Courier-optional fields
#     sender_phone_number: str | None = None,
#     receiver_phone_number: str | None = None,
#     comments_for_courier: str | None = None,
#     package_size: int | None = None,
#     package_types: list | None = None,
#     # Payment/schedule flags
#     payment_via: str = None,
#     is_hourly: bool = False,
#     is_scheduled: bool = False,
#     scheduled_at: str | None = None,
#     offered_fair: float | int | None = 0,
#     is_family: bool = False,
#     # NEW: estimated fields to match your JSON
#     estimated_time: str | None = None,        # e.g. "30 mins"
#     estimated_distance: str | None = None,    # e.g. "10 km"
# ):
#     body = {
#         "pickup": {
#             "lat": pickup.get("lat") or pickup.get("latitude"),
#             "lng": pickup.get("lng") or pickup.get("longitude"),
#         },
#         "dropoff": {
#             "lat": dropoff.get("lat") or dropoff.get("latitude"),
#             "lng": dropoff.get("lng") or dropoff.get("longitude"),
#         },
#         "pickup_location": pickup_location,
#         "dropoff_location": dropoff_location,

#         # Optional courier fields
#         **({"sender_phone_number": sender_phone_number} if sender_phone_number else {}),
#         **({"receiver_phone_number": receiver_phone_number} if receiver_phone_number else {}),
#         **({"comments_for_courier": comments_for_courier} if comments_for_courier else {}),
#         **({"package_size": package_size} if package_size is not None else {}),
#         **({"package_types": package_types} if package_types else {}),

#         "ride_type_id": ride_type_id,
#         "payment_via": payment_via or DEFAULT_PAYMENT_VIA,
#         "is_hourly": bool(is_hourly),

#         "pickup_address": pickup_address,
#         "destination_address": destination_address,

#         "pickup_coordinates": {
#             "lat": pickup_coordinates.get("lat"),
#             "lng": pickup_coordinates.get("lng"),
#         },
#         "destination_coordinates": {
#             "lat": destination_coordinates.get("lat"),
#             "lng": destination_coordinates.get("lng"),
#         },

#         "stops": stops or [],

#         "offered_fair": offered_fair if offered_fair is not None else 0,
#         "is_scheduled": bool(is_scheduled),
#         **({"scheduled_at": scheduled_at} if scheduled_at else {}),
#         "is_family": bool(is_family),

#         # Your new fields
#         **({"estimated_time": estimated_time} if estimated_time else {}),
#         **({"estimated_distance": estimated_distance} if estimated_distance else {}),
#     }

#     resp = post(CREATE_REQUEST_PATH, body)
#     try:
#         data = resp.json()
#     except Exception:
#         data = {"raw": resp.text}

#     ride_request_id = None
#     if isinstance(data, dict):
#         ride_request_id = (
#             data.get("rideReq", {}).get("id")
#             or data.get("rideRequestId")
#             or data.get("id")
#         )

#     return {
#         "status": resp.status_code,
#         "data": data,
#         "rideRequestId": ride_request_id,
#         "requestBody": body,
#     }


# def list_bids_for_request(ride_request_id: str):
#     path = _fill(BIDS_FOR_REQUEST_PATH, id=ride_request_id)
#     resp = get(path)
#     try:
#         return {"status": resp.status_code, "data": resp.json()}
#     except Exception:
#         return {"status": resp.status_code, "data": resp.text}


# def accept_bid(bid_id: str, payment_via: str = "WALLET",
#                is_schedule: bool = False, scheduled_at: str | None = None):
#     path = _fill(BID_ACCEPT_PATH, id=bid_id)
#     body = {
#         **({"customerId": CUSTOMER_ID} if CUSTOMER_ID else {}),
#         "bidId": bid_id,
#         "isSchedule": bool(is_schedule),
#         "payment_via": payment_via,
#         **({"scheduledAt": scheduled_at} if is_schedule and scheduled_at else {}),
#     }
#     resp = patch(path, body=body)
#     try:
#         return {"status": resp.status_code, "data": resp.json()}
#     except Exception:
#         return {"status": resp.status_code, "data": resp.text}


# def get_customer_ride(ride_id: str):
#     path = _fill(CUSTOMER_RIDE_PATH, rideId=ride_id)
#     resp = get(path)
#     try:
#         return {"status": resp.status_code, "data": resp.json()}
#     except Exception:
#         return {"status": resp.status_code, "data": resp.text}


# def cancel_ride_as_customer(ride_id: str, reason: str | None = None):
#     path = _fill(CANCEL_AS_CUSTOMER_PATH, id=ride_id)
#     resp = patch(path, None)  # no body per spec
#     try:
#         return {"status": resp.status_code, "data": resp.json()}
#     except Exception:
#         return {"status": resp.status_code, "data": resp.text}


# def wait_for_bids(ride_request_id: str, timeout_seconds: int = 60, poll_interval: int = 4):
#     deadline = time.time() + timeout_seconds
#     while time.time() < deadline:
#         out = list_bids_for_request(ride_request_id)
#         if out["status"] == 200:
#             bids = out["data"]
#             if isinstance(bids, list) and bids:
#                 return bids
#         time.sleep(poll_interval)
#     return []


# # ------- Optional helpers -------
# def offer_fare(ride_id: str, ride_request_id: str, offered_fare: float):
#     body = {"ride_request_id": ride_request_id, "offeredFare": offered_fare}
#     return _patch_json(_fill(OFFER_FARE_PATH, id=ride_id), body)


# def raise_fare(ride_request_id: str, new_fare: float):
#     body = {"rideRequestId": ride_request_id, "newFare": new_fare}
#     return _patch_json(RAISE_FARE_PATH, body)


# def start_ride(ride_id: str, rider_id: str):
#     return _patch_json(_fill(START_RIDE_PATH, rideId=ride_id, riderId=rider_id), {})


# def complete_ride(ride_id: str):
#     return _patch_json(_fill(COMPLETE_RIDE_PATH, rideId=ride_id), {})


# def ride_details(ride_id: str):
#     resp = get(_fill(RIDE_DETAILS_PATH, rideId=ride_id))
#     try:
#         return {"status": resp.status_code, "data": resp.json()}
#     except Exception:
#         return {"status": resp.status_code, "data": resp.text}


# def active_ride_for_customer():
#     resp = get(ONGOING_ACTIVE_CUSTOMER_PATH)
#     try:
#         return {"status": resp.status_code, "data": resp.json()}
#     except Exception:
#         return {"status": resp.status_code, "data": resp.text}


import os, json, time, math
from dotenv import load_dotenv
from api import get, post, patch

load_dotenv()

RIDE_TYPES_PATH           = os.getenv("RIDE_TYPES_PATH")
CREATE_REQUEST_PATH       = os.getenv("CREATE_REQUEST_PATH")
BIDS_FOR_REQUEST_PATH     = os.getenv("BIDS_FOR_REQUEST_PATH")
BID_ACCEPT_PATH           = os.getenv("BID_ACCEPT_PATH")
CUSTOMER_RIDE_PATH        = os.getenv("CUSTOMER_RIDE_PATH")
CANCEL_AS_CUSTOMER_PATH   = os.getenv("CANCEL_AS_CUSTOMER_PATH")
FARE_PATH                 = os.getenv("FARE_PATH", "/api/v1/rides/fare/all")
# Currency endpoint
CURRENCY_PATH             = os.getenv("CURRENCY_PATH", "/api/v1/currency")

# Optional helpers/endpoints
OFFER_FARE_PATH                 = "/api/v1/rides/{id}/offer-fare"
RAISE_FARE_PATH                 = "/api/v1/rides/ride-request/raise-fare"
START_RIDE_PATH                 = "/api/v1/rides/{rideId}/start-ride/{riderId}"
COMPLETE_RIDE_PATH              = "/api/v1/rides/{rideId}/complete-ride"
RIDE_DETAILS_PATH               = "/api/v1/rides/ride-details/{rideId}"
ONGOING_ACTIVE_CUSTOMER_PATH    = "/api/v1/rides/ongoing/active/customer"

DEFAULT_PAYMENT_VIA       = os.getenv("DEFAULT_PAYMENT_VIA", "CASH")
DEFAULT_IS_HOURLY         = os.getenv("DEFAULT_IS_HOURLY", "false").lower() == "true"
DEFAULT_IS_SCHEDULED      = os.getenv("DEFAULT_IS_SCHEDULED", "false").lower() == "true"
CUSTOMER_ID               = os.getenv("CUSTOMER_ID")  # optional

# Fare tuning (used for distance/duration estimation)
FARE_AVG_SPEED_KMH        = float(os.getenv("FARE_AVG_SPEED_KMH", "22"))  # city-ish avg
FARE_WAITING_MINUTES      = float(os.getenv("FARE_WAITING_MINUTES", "0"))
FARE_IS_NIGHT             = os.getenv("FARE_IS_NIGHT", "false").lower() == "true"


def _fill(path: str, **params):
    out = path
    for k, v in params.items():
        out = out.replace("{"+k+"}", str(v))
    return out


def _patch_json(path: str, body: dict | None):
    resp = patch(path, body)
    try:
        return {"status": resp.status_code, "data": resp.json()}
    except Exception:
        return {"status": resp.status_code, "data": resp.text}


def list_ride_types():
    resp = get(RIDE_TYPES_PATH)
    try:
        return resp.json() if resp.ok else []
    except Exception:
        return []


def list_currencies():
    """
    Fetch list of currencies from the backend.
    Returns a list (may be empty) of currency objects.
    """
    resp = get(CURRENCY_PATH)
    try:
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


# ---------------------------
# Distance helpers
# ---------------------------
def _haversine_km(a: dict, b: dict) -> float:
    lat1, lon1 = float(a["lat"]), float(a["lng"])
    lat2, lon2 = float(b["lat"]), float(b["lng"])
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    s1 = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(s1))


def _route_distance_km(pickup: dict, dropoff: dict, stops: list | None) -> float:
    points = [pickup] + (stops or []) + [dropoff]
    dist = 0.0
    for i in range(len(points) - 1):
        if points[i].get("lat") is None or points[i+1].get("lat") is None:
            continue
        dist += _haversine_km(points[i], points[i+1])
    return max(dist, 0.0)


# ---------------------------
# Fare (use documented query params)
# ---------------------------
def get_fare(pickup: dict, dropoff: dict, stops: list | None = None, distance_km: float | None = None, duration_min: float | None = None):
    """
    Calls /api/v1/rides/fare/all with the official parameters:
    - isNightRide, waitingMinutes, isHourly, durationMin, distanceKm

    If distance_km and duration_min are provided (e.g., from Google Maps), use them.
    Otherwise, estimate distance/duration from coordinates using haversine.
    Even if fare is null, computed distance & duration are returned for use in
    the create-ride payload as estimated_distance / estimated_time.
    """
    p = {
        "lat": pickup.get("lat") or pickup.get("latitude"),
        "lng": pickup.get("lng") or pickup.get("longitude"),
    }
    d = {
        "lat": dropoff.get("lat") or dropoff.get("latitude"),
        "lng": dropoff.get("lng") or dropoff.get("longitude"),
    }
    s_clean = []
    for s in (stops or []):
        if s.get("lat") is not None and s.get("lng") is not None:
            s_clean.append({"lat": s.get("lat"), "lng": s.get("lng")})

    # Use provided Google Maps values if available, otherwise calculate using haversine
    if distance_km is None or duration_min is None:
        distance_km = _route_distance_km(p, d, s_clean)
        duration_min = (distance_km / max(FARE_AVG_SPEED_KMH, 1e-6)) * 60.0

    params = {
        "pickup_lat": p.get("lat"),
        "pickup_lng": p.get("lng"),
        "dropoff_lat": d.get("lat"),
        "dropoff_lng": d.get("lng"),
        "isNightRide": str(FARE_IS_NIGHT).lower(),
        "waitingMinutes": FARE_WAITING_MINUTES,
        "isHourly": "false",
        "durationMin": round(duration_min, 2),
        "distanceKm": round(distance_km, 3),
    }

    resp = get(FARE_PATH, params=params)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}

    return {
        "status": resp.status_code,
        "data": data,
        "computed": {
            "distanceKm": params["distanceKm"],
            "durationMin": params["durationMin"],
        },
    }


def pick_ride_type_id_from_fare(fare_json: dict, desired_name: str | None) -> str | None:
    if not desired_name:
        return None
    
    def _normalize_ride_type_name(name: str) -> str:
        """Normalize ride type name for matching (handles spaces, underscores, case)"""
        if not name:
            return ""
        return name.strip().lower().replace(" ", "").replace("_", "")
    
    try:
        desired_normalized = _normalize_ride_type_name(desired_name)
        for it in (fare_json.get("rideTypeFares") or []):
            api_name = (it.get("name") or "").strip()
            api_name_normalized = _normalize_ride_type_name(api_name)
            if api_name_normalized == desired_normalized:
                return it.get("ride_type_id")
    except Exception:
        pass
    return None


# -------------------------------------------------
# Create ride request with EXACT body (your spec)
# -------------------------------------------------
def create_ride_request_exact(
    pickup: dict,
    dropoff: dict,
    ride_type_id: str,
    pickup_location: str,
    dropoff_location: str,
    pickup_address: str,
    destination_address: str,
    pickup_coordinates: dict,
    destination_coordinates: dict,
    stops: list | None = None,
    # Courier-optional fields
    sender_phone_number: str | None = None,
    receiver_phone_number: str | None = None,
    comments_for_courier: str | None = None,
    package_size: int | None = None,
    package_types: list | None = None,
    # Payment/schedule flags
    payment_via: str = None,
    is_hourly: bool = False,
    is_scheduled: bool = False,
    scheduled_at: str | None = None,
    offered_fair: float | int | None = 0,
    is_family: bool = False,
    # NEW: estimated fields to match your JSON
    estimated_time: str | None = None,        # e.g. "30 mins"
    estimated_distance: str | None = None,    # e.g. "10 km"
):
    body = {
        "pickup": {
            "lat": pickup.get("lat") or pickup.get("latitude"),
            "lng": pickup.get("lng") or pickup.get("longitude"),
        },
        "dropoff": {
            "lat": dropoff.get("lat") or dropoff.get("latitude"),
            "lng": dropoff.get("lng") or dropoff.get("longitude"),
        },
        "pickup_location": pickup_location,
        "dropoff_location": dropoff_location,

        # Optional courier fields
        **({"sender_phone_number": sender_phone_number} if sender_phone_number else {}),
        **({"receiver_phone_number": receiver_phone_number} if receiver_phone_number else {}),
        **({"comments_for_courier": comments_for_courier} if comments_for_courier else {}),
        **({"package_size": package_size} if package_size is not None else {}),
        **({"package_types": package_types} if package_types else {}),

        "ride_type_id": ride_type_id,
        "payment_via": payment_via or DEFAULT_PAYMENT_VIA,
        "is_hourly": bool(is_hourly),

        "pickup_address": pickup_address,
        "destination_address": destination_address,

        "pickup_coordinates": {
            "lat": pickup_coordinates.get("lat"),
            "lng": pickup_coordinates.get("lng"),
        },
        "destination_coordinates": {
            "lat": destination_coordinates.get("lat"),
            "lng": destination_coordinates.get("lng"),
        },

        "stops": stops or [],

        "offered_fair": offered_fair if offered_fair is not None else 0,
        "is_scheduled": bool(is_scheduled),
        **({"scheduled_at": scheduled_at} if scheduled_at else {}),
        "is_family": bool(is_family),

        # Your new fields
        **({"estimated_time": estimated_time} if estimated_time else {}),
        **({"estimated_distance": estimated_distance} if estimated_distance else {}),
    }

    resp = post(CREATE_REQUEST_PATH, body)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}

    ride_request_id = None
    if isinstance(data, dict):
        ride_request_id = (
            data.get("rideReq", {}).get("id")
            or data.get("rideRequestId")
            or data.get("id")
        )

    return {
        "status": resp.status_code,
        "data": data,
        "rideRequestId": ride_request_id,
        "requestBody": body,
    }


def list_bids_for_request(ride_request_id: str):
    path = _fill(BIDS_FOR_REQUEST_PATH, id=ride_request_id)
    resp = get(path)
    try:
        return {"status": resp.status_code, "data": resp.json()}
    except Exception:
        return {"status": resp.status_code, "data": resp.text}


def accept_bid(bid_id: str,
               payment_via: str = "CASH",
               is_schedule: bool = False,
               scheduled_at: str | None = None,
               customer_id: str | None = None):
    path = _fill(BID_ACCEPT_PATH, id=bid_id)
    effective_customer_id = customer_id or CUSTOMER_ID
    body = {
        **({"customerId": effective_customer_id} if effective_customer_id else {}),
        "bidId": bid_id,
        "isSchedule": bool(is_schedule),
        "payment_via": payment_via,
        **({"scheduledAt": scheduled_at} if is_schedule and scheduled_at else {}),
    }
    resp = patch(path, body=body)
    try:
        return {"status": resp.status_code, "data": resp.json()}
    except Exception:
        return {"status": resp.status_code, "data": resp.text}


def get_customer_ride(ride_id: str):
    path = _fill(CUSTOMER_RIDE_PATH, rideId=ride_id)
    resp = get(path)
    try:
        return {"status": resp.status_code, "data": resp.json()}
    except Exception:
        return {"status": resp.status_code, "data": resp.text}


def cancel_ride_as_customer(ride_id: str, reason: str | None = None):
    path = _fill(CANCEL_AS_CUSTOMER_PATH, id=ride_id)
    resp = patch(path, None)  # no body per spec
    try:
        return {"status": resp.status_code, "data": resp.json()}
    except Exception:
        return {"status": resp.status_code, "data": resp.text}


def wait_for_bids(ride_request_id: str, timeout_seconds: int = 60, poll_interval: int = 4):
    """
    Polls /bids for the given ride_request_id until at least one bid is present
    or the timeout is reached. Returns the list of bids (as returned by the API),
    or [] if none found.
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        out = list_bids_for_request(ride_request_id)
        if out["status"] == 200:
            data = out["data"]
            # API currently returns: { "bids": [ ... ] }
            if isinstance(data, dict):
                bids = data.get("bids") or []
            elif isinstance(data, list):
                bids = data
            else:
                bids = []
            if bids:
                return bids
        time.sleep(poll_interval)
    return []


# ------- Optional helpers -------
def offer_fare(ride_id: str, ride_request_id: str, offered_fare: float):
    body = {"ride_request_id": ride_request_id, "offeredFare": offered_fare}
    return _patch_json(_fill(OFFER_FARE_PATH, id=ride_id), body)


def raise_fare(ride_request_id: str, new_fare: float):
    body = {"rideRequestId": ride_request_id, "newFare": new_fare}
    return _patch_json(RAISE_FARE_PATH, body)


def start_ride(ride_id: str, rider_id: str):
    return _patch_json(_fill(START_RIDE_PATH, rideId=ride_id, riderId=rider_id), {})


def complete_ride(ride_id: str):
    return _patch_json(_fill(COMPLETE_RIDE_PATH, rideId=ride_id), {})


def ride_details(ride_id: str):
    resp = get(_fill(RIDE_DETAILS_PATH, rideId=ride_id))
    try:
        return {"status": resp.status_code, "data": resp.json()}
    except Exception:
        return {"status": resp.status_code, "data": resp.text}


def active_ride_for_customer():
    resp = get(ONGOING_ACTIVE_CUSTOMER_PATH)
    try:
        return {"status": resp.status_code, "data": resp.json()}
    except Exception:
        return {"status": resp.status_code, "data": resp.text}
