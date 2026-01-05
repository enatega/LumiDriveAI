"""
Google Maps API integration for distance calculation, route planning, and location services.
Uses the provided Google Maps APIs to calculate accurate distances and durations before fare API calls.
"""
import os
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# Try to import polyline, but don't fail if it's not available
try:
    from polyline import decode
    POLYLINE_AVAILABLE = True
except ImportError:
    POLYLINE_AVAILABLE = False
    decode = None
    print("⚠️ Warning: polyline module not available. Route path decoding will be disabled.")

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    print("⚠️ Warning: GOOGLE_API_KEY not set in .env. Google Maps features will not work.")

# HTTP client timeout for Google Maps API calls (30 seconds)
HTTP_TIMEOUT = 30.0


class GoogleMapsService:
    """Service for interacting with Google Maps APIs"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.googleApiKey = api_key or GOOGLE_API_KEY
    
    async def fetchGoogleRoute(
        self,
        origin: Dict[str, float],
        destination: Dict[str, float],
        stops: List[Dict[str, float]] = [],
    ) -> Dict[str, Any]:
        """
        Fetch route from Google Maps Directions API.
        
        Args:
            origin: {"lat": float, "lng": float}
            destination: {"lat": float, "lng": float}
            stops: List of {"lat": float, "lng": float}
        
        Returns:
            {"path": [[lat, lng], ...]} - Decoded polyline path
        """
        if not self.googleApiKey:
            raise ValueError("Google API key not configured")
        
        try:
            originStr = f"{origin['lat']},{origin['lng']}"
            destinationStr = f"{destination['lat']},{destination['lng']}"
            waypoints = ""
            
            if stops:
                waypoints = "&waypoints=" + "|".join([f"{s['lat']},{s['lng']}" for s in stops])
            
            url = f"https://maps.googleapis.com/maps/api/directions/json?origin={originStr}&destination={destinationStr}{waypoints}&key={self.googleApiKey}"
            
            import httpx
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                res = await client.get(url)
                res.raise_for_status()
                data = res.json()
            
            if not data.get("routes") or len(data["routes"]) == 0:
                raise ValueError("No routes found from Google Maps")
            
            encodedPolyline = data["routes"][0].get("overview_polyline", {}).get("points")
            if not encodedPolyline:
                raise ValueError("Polyline data not found")
            
            if not POLYLINE_AVAILABLE or decode is None:
                # Return empty path if polyline is not available
                # The route is still valid, we just can't decode the path
                return {"path": []}
            
            decodedPath = decode(encodedPolyline)
            return {"path": decodedPath}
        
        except Exception as error:
            print(f"Error fetching Google route: {error}")
            raise
    
    async def snapToRoad(
        self,
        lat: float,
        lng: float,
    ) -> Dict[str, float]:
        """
        Snap coordinates to nearest road using Google Roads API.
        
        Args:
            lat: Latitude
            lng: Longitude
        
        Returns:
            {"latitude": float, "longitude": float}
        """
        if not self.googleApiKey:
            return {"latitude": lat, "longitude": lng}
        
        try:
            url = f"https://roads.googleapis.com/v1/snapToRoads?path={lat},{lng}&key={self.googleApiKey}"
            
            import httpx
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                res = await client.get(url)
                res.raise_for_status()
                apiData = res.json()
            
            if apiData.get("snappedPoints") and len(apiData["snappedPoints"]) > 0:
                return {
                    "latitude": apiData["snappedPoints"][0]["location"]["latitude"],
                    "longitude": apiData["snappedPoints"][0]["location"]["longitude"],
                }
            
            return {"latitude": lat, "longitude": lng}
        
        except Exception as error:
            print(f"Error snapping to road: {error}")
            return {"latitude": lat, "longitude": lng}
    
    async def getDistanceMatrix(
        self,
        origins: List[str],
        destinations: List[str]
    ) -> Dict[str, Any]:
        """
        Get distance and duration matrix from Google Distance Matrix API.
        
        Args:
            origins: List of "lat,lng" strings
            destinations: List of "lat,lng" strings
        
        Returns:
            {
                "origins": [...],
                "destinations": [...],
                "distanceKm": float,
                "durationMin": int,
                "raw": {...}
            }
        """
        if not self.googleApiKey:
            raise ValueError("Google API key not configured")
        
        try:
            originsParam = "|".join(origins)
            destinationsParam = "|".join(destinations)
            
            from urllib.parse import quote
            url = f"https://maps.googleapis.com/maps/api/distancematrix/json?destinations={quote(destinationsParam)}&origins={quote(originsParam)}&units=metric&key={self.googleApiKey}"
            
            import httpx
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
            
            if data.get("status") != "OK":
                error_msg = data.get("error_message", data.get("status"))
                raise ValueError(f"Google API Error: {data.get('status')} - {error_msg}")
            
            rows = data.get("rows", [])
            if not rows or len(rows) == 0:
                raise ValueError("No rows returned from Distance Matrix API")
            
            elements = rows[0].get("elements", [])
            if not elements or len(elements) == 0:
                raise ValueError("No elements returned from Distance Matrix API")
            
            element = elements[0]
            if not element or element.get("status") != "OK":
                status = element.get("status", "UNKNOWN") if element else "NO_ELEMENT"
                raise ValueError(f"Invalid route status: {status}")
            
            distance = element.get("distance")
            duration = element.get("duration")
            
            if not distance or not duration:
                raise ValueError("Missing distance or duration in API response")
            
            distanceKm = distance.get("value", 0) / 1000
            durationMin = int(round(duration.get("value", 0) / 60))
            
            return {
                "origins": origins,
                "destinations": destinations,
                "distanceKm": distanceKm,
                "durationMin": durationMin,
                "raw": data,
            }
        
        except Exception as error:
            print(f"Error fetching Distance Matrix: {error}")
            raise
    
    async def fetchPlaces(self, input: str) -> List[Dict[str, Any]]:
        """
        Fetch place autocomplete suggestions from Google Places API.
        
        Args:
            input: Search query (min 3 characters)
        
        Returns:
            List of place predictions
        """
        if not self.googleApiKey:
            return []
        
        if not input or len(input) < 3:
            return []
        
        try:
            from urllib.parse import quote
            url = f"https://maps.googleapis.com/maps/api/place/autocomplete/json?input={quote(input)}&key={self.googleApiKey}"
            
            import httpx
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                res = await client.get(url)
                res.raise_for_status()
                data = res.json()
            
            if data.get("status") != "OK":
                print(f"⚠️ Places API warning: {data.get('status')}, {data.get('error_message')}")
                return []
            
            return data.get("predictions", [])
        
        except Exception as error:
            print(f"Error fetching places: {error}")
            return []
    
    async def getPlaceDetails(self, placeId: str) -> Dict[str, float]:
        """
        Get place details including coordinates from Google Places API.
        
        Args:
            placeId: Google Place ID
        
        Returns:
            {"lat": float, "lng": float}
        """
        if not self.googleApiKey:
            raise ValueError("Google API key not configured")
        
        try:
            from urllib.parse import quote
            url = f"https://maps.googleapis.com/maps/api/place/details/json?place_id={quote(placeId)}&fields=geometry&key={self.googleApiKey}"
            
            import httpx
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                res = await client.get(url)
                res.raise_for_status()
                data = res.json()
            
            loc = data.get("result", {}).get("geometry", {}).get("location")
            if not loc:
                raise ValueError("Location not found")
            
            return {"lat": loc["lat"], "lng": loc["lng"]}
        
        except Exception as error:
            print(f"Error fetching place details: {error}")
            raise
    
    async def fetchAddressFromCoordinates(
        self,
        lat: float,
        lng: float,
    ) -> Dict[str, str]:
        """
        Reverse geocode coordinates to get address.
        
        Args:
            lat: Latitude
            lng: Longitude
        
        Returns:
            {"address": str}
        """
        if not self.googleApiKey:
            return {"address": "Address not found"}
        
        try:
            url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lng}&key={self.googleApiKey}"
            
            import httpx
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                res = await client.get(url)
                res.raise_for_status()
                data = res.json()
            
            if data.get("status") == "OK" and data.get("results") and len(data["results"]) > 0:
                return {"address": data["results"][0]["formatted_address"]}
            
            return {"address": "Address not found"}
        
        except Exception as error:
            print(f"Error fetching address: {error}")
            return {"address": "Address not found"}
    
    async def getTimezoneFromCoordinates(self, lat: float, lng: float) -> Dict[str, str]:
        """
        Get timezone information for given coordinates using Google Maps Time Zone API.
        
        Args:
            lat: Latitude
            lng: Longitude
        
        Returns:
            {"timeZoneId": str, "timeZoneName": str} or empty dict if error
        """
        if not self.googleApiKey:
            return {}
        
        try:
            import time
            timestamp = int(time.time())  # Current timestamp
            url = f"https://maps.googleapis.com/maps/api/timezone/json?location={lat},{lng}&timestamp={timestamp}&key={self.googleApiKey}"
            
            import httpx
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                res = await client.get(url)
                res.raise_for_status()
                data = res.json()
            
            if data.get("status") == "OK":
                return {
                    "timeZoneId": data.get("timeZoneId", ""),
                    "timeZoneName": data.get("timeZoneName", ""),
                }
            else:
                print(f"⚠️ Timezone API error: {data.get('status')}, {data.get('errorMessage')}")
                return {}
        
        except Exception as error:
            print(f"⚠️ Error getting timezone: {error}")
            return {}


# Global instance
_google_maps_service: Optional[GoogleMapsService] = None


def get_google_maps_service() -> GoogleMapsService:
    """Get or create the global Google Maps service instance"""
    global _google_maps_service
    if _google_maps_service is None:
        _google_maps_service = GoogleMapsService()
    return _google_maps_service


async def calculate_distance_duration_google(
    pickup: Dict[str, float],
    dropoff: Dict[str, float],
    stops: Optional[List[Dict[str, float]]] = None,
) -> Dict[str, Any]:
    """
    Calculate distance and duration using Google Maps Distance Matrix API.
    This is more accurate than haversine and should be used before fare API calls.
    
    Args:
        pickup: {"lat": float, "lng": float}
        dropoff: {"lat": float, "lng": float}
        stops: Optional list of {"lat": float, "lng": float}
    
    Returns:
        {
            "distanceKm": float,
            "durationMin": int,
            "success": bool
        }
    """
    # Validate inputs
    if not pickup or not isinstance(pickup, dict):
        raise ValueError("pickup must be a dict with 'lat' and 'lng' keys")
    if not dropoff or not isinstance(dropoff, dict):
        raise ValueError("dropoff must be a dict with 'lat' and 'lng' keys")
    
    if pickup.get("lat") is None or pickup.get("lng") is None:
        raise ValueError("pickup must have 'lat' and 'lng' values")
    if dropoff.get("lat") is None or dropoff.get("lng") is None:
        raise ValueError("dropoff must have 'lat' and 'lng' values")
    
    service = get_google_maps_service()
    
    if not service.googleApiKey:
        raise ValueError("GOOGLE_API_KEY is not set. Google Maps API is required for distance calculation.")
    
    try:
        # Build origin and destination strings
        origins = [f"{pickup['lat']},{pickup['lng']}"]
        destinations = [f"{dropoff['lat']},{dropoff['lng']}"]
        
        # If there are stops, we need to calculate route with waypoints
        # For now, use distance matrix for direct route
        # TODO: If stops exist, calculate route with waypoints and sum distances
        
        result = await service.getDistanceMatrix(origins, destinations)
        
        # Ensure result is not None and has required keys
        if result and isinstance(result, dict) and "distanceKm" in result and "durationMin" in result:
            return {
                "distanceKm": result["distanceKm"],
                "durationMin": result["durationMin"],
                "success": True,
            }
        else:
            raise ValueError(f"Invalid result from getDistanceMatrix: {result}")
    
    except Exception as e:
            print(f"⚠️ Google Maps API error: {e}")
            import traceback
            traceback.print_exc()
            raise ValueError(f"Google Maps API failed: {str(e)}")

