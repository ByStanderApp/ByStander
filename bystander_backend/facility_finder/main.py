from flask import Flask, request, jsonify, make_response
import requests
import os
from dotenv import load_dotenv

app = Flask(__name__)

# Load environment variables
load_dotenv()
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

def _build_cors_preflight_response():
    """Build CORS preflight response"""
    response = make_response()
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "POST,GET,OPTIONS")
    return response

def _corsify_actual_response(response):
    """Add CORS headers to actual response"""
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response

def search_nearby_facilities(latitude, longitude, facility_type, severity):
    """
    Search for nearby hospitals or clinics using Google Maps Places API
    
    Args:
        latitude: User's latitude
        longitude: User's longitude
        facility_type: "hospital" or "clinic"
        severity: "critical", "mild", or "none"
    
    Returns:
        List of up to 5 facilities with their details
    """
    if not GOOGLE_MAPS_API_KEY:
        return {"error": "Google Maps API key not configured"}
    
    # Determine search type based on facility_type and severity
    if facility_type == "hospital" or severity == "critical":
        search_type = "hospital"
        radius = 5000  # 5km for hospitals
    elif facility_type == "clinic":
        search_type = "doctor"  # Using 'doctor' type for clinics
        radius = 3000  # 3km for clinics
    else:
        search_type = "hospital"
        radius = 5000
    
    # Google Places API - Nearby Search
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    
    params = {
        "location": f"{latitude},{longitude}",
        "radius": radius,
        "type": search_type,
        "language": "th",
        "key": GOOGLE_MAPS_API_KEY
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") != "OK":
            print(f"Google Places API error: {data.get('status')} - {data.get('error_message', 'No error message')}")
            return {"error": f"Unable to find facilities: {data.get('status')}"}
        
        results = data.get("results", [])[:5]  # Get top 5 results
        
        facilities = []
        for place in results:
            # Get place details for more information
            place_id = place.get("place_id")
            details = get_place_details(place_id)
            
            facility = {
                "place_id": place_id,
                "name": place.get("name", ""),
                "address": place.get("vicinity", ""),
                "latitude": place["geometry"]["location"]["lat"],
                "longitude": place["geometry"]["location"]["lng"],
                "rating": place.get("rating", 0),
                "user_ratings_total": place.get("user_ratings_total", 0),
                "open_now": place.get("opening_hours", {}).get("open_now", None),
                "phone_number": details.get("phone_number", ""),
                "website": details.get("website", ""),
                "types": place.get("types", [])
            }
            facilities.append(facility)
        
        return {"facilities": facilities, "total": len(facilities)}
    
    except requests.RequestException as e:
        print(f"Error calling Google Places API: {e}")
        return {"error": "Failed to search for facilities"}

def get_place_details(place_id):
    """
    Get detailed information about a place using Place Details API
    
    Args:
        place_id: Google Place ID
    
    Returns:
        Dictionary with place details
    """
    if not GOOGLE_MAPS_API_KEY:
        return {}
    
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    
    params = {
        "place_id": place_id,
        "fields": "formatted_phone_number,website,opening_hours",
        "language": "th",
        "key": GOOGLE_MAPS_API_KEY
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") == "OK":
            result = data.get("result", {})
            return {
                "phone_number": result.get("formatted_phone_number", ""),
                "website": result.get("website", ""),
                "opening_hours": result.get("opening_hours", {})
            }
        else:
            print(f"Place Details API error: {data.get('status')}")
            return {}
    
    except requests.RequestException as e:
        print(f"Error calling Place Details API: {e}")
        return {}

@app.route('/find_facilities', methods=['POST', 'OPTIONS'])
def find_facilities():
    """
    Endpoint to find nearby medical facilities
    
    Request body:
    {
        "latitude": float,
        "longitude": float,
        "facility_type": "hospital" or "clinic",
        "severity": "critical", "mild", or "none"
    }
    """
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
    
    try:
        data = request.get_json()
        
        # Validate required fields
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        facility_type = data.get('facility_type', 'hospital')
        severity = data.get('severity', 'none')
        
        if latitude is None or longitude is None:
            return _corsify_actual_response(jsonify({
                "error": "latitude and longitude are required"
            })), 400
        
        # Convert to float
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except ValueError:
            return _corsify_actual_response(jsonify({
                "error": "Invalid latitude or longitude format"
            })), 400
        
        # Validate values
        if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            return _corsify_actual_response(jsonify({
                "error": "Invalid latitude or longitude values"
            })), 400
        
        # Search for facilities
        result = search_nearby_facilities(latitude, longitude, facility_type, severity)
        
        if "error" in result:
            return _corsify_actual_response(jsonify(result)), 503
        
        return _corsify_actual_response(jsonify(result))
    
    except Exception as e:
        print(f"Error in find_facilities endpoint: {e}")
        return _corsify_actual_response(jsonify({
            "error": f"Internal server error: {str(e)}"
        })), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "ok", "service": "facility_finder"})

if __name__ == '__main__':
    print("Starting Facility Finder Flask application...")
    if not GOOGLE_MAPS_API_KEY:
        print("WARNING: GOOGLE_MAPS_API_KEY not found in environment variables")
        print("Please add it to your .env file")
    app.run(debug=True, host='0.0.0.0', port=5002)
