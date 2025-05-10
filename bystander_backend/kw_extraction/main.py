# main_app.py
from flask import Flask, request, jsonify
from pythainlp.tokenize import word_tokenize # Though not strictly needed for extract_keywords with string input
from pythainlp.summarize import extract_keywords
import json # For potential future LLM interaction if it returns JSON

# Initialize Flask app
app = Flask(__name__)

# --- API 1: Keyword Extraction ---
@app.route('/extract_keywords', methods=['POST'])
def api_extract_keywords():
    """
    API endpoint to extract keywords from a Thai sentence.
    Expects JSON input: {"sentence": "ข้อความภาษาไทย"}
    Returns JSON output: {"keywords": ["คำ1", "คำ2", ...]} or {"error": "ข้อความแสดงข้อผิดพลาด"}
    """
    try:
        # Get data from the POST request
        data = request.get_json()

        # Validate input
        if not data or 'sentence' not in data:
            return jsonify({"error": "ไม่พบข้อมูล 'sentence' ในคำขอ"}), 400 # Bad Request

        thai_text = data['sentence']
        if not isinstance(thai_text, str) or not thai_text.strip(): # Check if it's a non-empty string
            return jsonify({"error": "'sentence' ต้องเป็นสตริงที่ไม่ว่างเปล่า"}), 400

        # Keyword extraction using PyThaiNLP
        # The extract_keywords function can take a raw string directly.
        # It will perform tokenization internally.
        # max_keywords can be adjusted based on desired output length.
        keywords = extract_keywords(thai_text, max_keywords=15) 
        
        # Return the extracted keywords as a JSON list
        return jsonify({"keywords": list(keywords)}), 200 # OK

    except Exception as e:
        # Log the exception for debugging purposes on the server
        print(f"Error in /extract_keywords: {e}")
        # Return a generic error message to the client
        return jsonify({"error": f"เกิดข้อผิดพลาดในการประมวลผล: {str(e)}"}), 500 # Internal Server Error


# --- Root Endpoint for Basic Testing ---
@app.route('/', methods=['GET'])
def home():
    """A simple GET endpoint to confirm the API is running."""
    return "<h1>API ระบบแนะนำการปฐมพยาบาลเบื้องต้น ByStander</h1><p>API พร้อมใช้งานแล้ว โปรดดูเอกสารประกอบสำหรับวิธีการเรียกใช้งาน endpoint ต่างๆ</p>"

if __name__ == '__main__':
    # Ensure you have the necessary libraries installed:
    # pip install Flask pythainlp
    
    # PyThaiNLP might require downloading corpus data on first use for some functionalities.
    # You can pre-download if needed, though extract_keywords often works without explicit downloads.
    # from pythainlp.corpus import download
    # try:
    #     download('TNC_WORDS') # Example corpus, check pythainlp docs if needed
    # except Exception as e:
    #     print(f"Could not download pythainlp corpus (this might be okay): {e}")

    # Run the Flask development server
    # debug=True is useful for development as it provides detailed error pages and auto-reloads on code changes.
    # host='0.0.0.0' makes the server accessible from other devices on the same network.
    # port=5000 is the default Flask port.
    app.run(debug=True, host='0.0.0.0', port=5001)