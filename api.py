import os, uuid, json
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("BASE_URL", "").rstrip("/")

# NOTE:
# - In the CLI flow, we still use this module-level TOKEN.
# - In server/production, prefer set_token(...) per request so each user
#   has their own Authorization header.
TOKEN = os.getenv("TOKEN") or ""

session = requests.Session()
session.headers.update({"Content-Type": "application/json"})

def _auth_header():
    """
    Build auth header from the current TOKEN.
    In production, TOKEN should be set per-request (e.g. from FastAPI dependency).
    """
    headers = {}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return headers

def set_token(new_token: str):
    """
    Set the module-level TOKEN.
    In FastAPI, call this at the start of each request using the user's JWT.
    """
    global TOKEN
    TOKEN = new_token or ""

def _idemp_headers():
    return {
        "X-Request-Id": str(uuid.uuid4()),
        "Idempotency-Key": str(uuid.uuid4())
    }

def post(path: str, body: dict, timeout: int = 25):
    url = f"{BASE_URL}{path}"
    headers = {**_auth_header(), **_idemp_headers()}
    print(f"\n🌍 POST {url}\n📦 Payload:", json.dumps(body, indent=2))
    resp = session.post(url, json=body, headers=headers, timeout=timeout)
    print("📥 Response:", resp.status_code)
    try:
        print(json.dumps(resp.json(), indent=2))
    except Exception:
        print(resp.text[:1000])
    return resp

def patch(path: str, body: dict | None = None, timeout: int = 25):
    url = f"{BASE_URL}{path}"
    headers = {**_auth_header(), **_idemp_headers()}
    print(f"\n🩹 PATCH {url}")
    if body is not None:
        print("📦 Payload:", json.dumps(body, indent=2))
    resp = session.patch(url, json=body, headers=headers, timeout=timeout)
    print("📥 Response:", resp.status_code)
    try:
        print(json.dumps(resp.json(), indent=2))
    except Exception:
        print(resp.text[:1000])
    return resp

def get(path: str, params: dict | None = None, timeout: int = 25):
    url = f"{BASE_URL}{path}"
    headers = _auth_header()
    print(f"\n🔎 GET {url}\n🔍 Params:", params)
    resp = session.get(url, params=params, headers=headers, timeout=timeout)
    print("📥 Response:", resp.status_code)
    try:
        print(json.dumps(resp.json(), indent=2))
    except Exception:
        print(resp.text[:1000])
    return resp


def get_user_id_from_jwt(token: str, timeout: int = 10) -> dict:
    """
    Fetch user_id from JWT token using the rides backend API.

    Args:
        token: JWT bearer token (raw, without the Bearer prefix)
        timeout: Request timeout in seconds

    Returns:
        {
            "ok": bool,
            "user_id": str | None,
            "error": str | None
        }
    """
    if not token:
        return {"ok": False, "user_id": None, "error": "Missing token"}

    url = f"{BASE_URL}/api/v1/users/get-user-id"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    try:
        resp = session.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            user_id = data.get("user_id")
            if user_id:
                return {"ok": True, "user_id": user_id, "error": None}
            return {"ok": False, "user_id": None, "error": "user_id not found in response"}

        if resp.status_code == 401:
            return {"ok": False, "user_id": None, "error": "Invalid or expired JWT token"}

        return {
            "ok": False,
            "user_id": None,
            "error": f"Failed to fetch user_id: HTTP {resp.status_code}",
        }
    except Exception as exc:
        return {"ok": False, "user_id": None, "error": f"Error fetching user_id: {exc}"}

def get_user_current_location(timeout: int = 10) -> dict:
    """
    Fetch user's current location from rides backend API.
    Uses the current TOKEN (set via set_token) for authentication.
    
    Returns:
        {
            "ok": bool,
            "location": {"lat": float, "lng": float} | None,
            "error": str | None
        }
    """
    url = f"{BASE_URL}/api/v1/users/current-location"
    headers = _auth_header()
    
    try:
        resp = session.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            location = data.get("location")
            if location and "lat" in location and "lng" in location:
                return {
                    "ok": True,
                    "location": {
                        "lat": location["lat"],
                        "lng": location["lng"],
                    },
                }
            else:
                return {
                    "ok": False,
                    "location": None,
                    "error": "Invalid location data in response",
                }
        elif resp.status_code == 404:
            return {
                "ok": False,
                "location": None,
                "error": "Location not available",
            }
        else:
            return {
                "ok": False,
                "location": None,
                "error": f"Failed to fetch location: HTTP {resp.status_code}",
            }
    except Exception as e:
        return {
            "ok": False,
            "location": None,
            "error": f"Error fetching location: {str(e)}",
        }
