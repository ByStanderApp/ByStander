# main_app.py
from flask import Flask, request, jsonify, make_response
import json
import os
import anthropic # For Claude API
from dotenv import load_dotenv


# Initialize Flask app
app = Flask(__name__)

# --- Global Variables for Claude LLM ---
claude_client = None
CLAUDE_MODEL_NAME = "claude-3-haiku-20240307" # Using the latest Haiku model

# --- Function to Initialize Claude Client ---
def initialize_claude_client():
    """
    Initializes the Anthropic client.
    Loads API key from .env file first.
    This function should be called once when the Flask app starts.
    """
    global claude_client
    
    # Load environment variables from .env file
    load_dotenv() 
    
    api_key = os.environ.get("CLAUDE_KEY")
    if not api_key:
        print("CRITICAL ERROR: CLAUDE_KEY environment variable not found in environment or .env file.")
        print("Claude LLM guidance generation will not be available.")
        claude_client = None
        return

    try:
        claude_client = anthropic.Anthropic(api_key=api_key)
        print(f"Anthropic client initialized successfully for model: {CLAUDE_MODEL_NAME}.")
    except Exception as e:
        print(f"CRITICAL ERROR initializing Anthropic client: {e}")
        claude_client = None


# --- Helper Function for LLM Guidance Generation (using Claude) ---
def generate_guidance_with_llm(prompt_text: str, language: str = "th") -> str:
    """
    Generates emergency guidance using the configured Claude LLM.

    Args:
        prompt_text (str): The detailed prompt/instruction for the LLM.
        language (str): Target language (primarily for consistency, Claude will be prompted for Thai).

    Returns:
        str: The LLM-generated guidance or an error message.
    """
    global claude_client

    if not claude_client:
        print("Claude client not initialized. Returning placeholder response.")
        error_message = "ขออภัย ระบบ AI หลัก (Claude) ไม่พร้อมใช้งานในขณะนี้เนื่องจากปัญหาการตั้งค่า "
        if "อาหารติดคอ" in prompt_text:
            return error_message + "คำแนะนำเบื้องต้นสำหรับอาหารติดคอ: หากผู้ป่วยไอได้ ให้กระตุ้นให้ไอต่อ หากไอไม่ได้หรือไม่มีเสียง ให้ทำการรัดกระตุกหน้าท้อง (Heimlich) และโทร 1669 ทันที"
        return error_message + "โปรดติดต่อ 1669 เพื่อขอความช่วยเหลือทางการแพทย์ฉุกเฉินโดยตรง"

    try:
        print(f"--- Calling Claude LLM ({CLAUDE_MODEL_NAME}) ---")
        
        system_prompt = "คุณเป็นผู้ช่วย AI ที่เชี่ยวชาญการให้คำแนะนำการปฐมพยาบาลเบื้องต้นเป็นภาษาไทย กรุณาตอบเป็นภาษาไทยเท่านั้น ให้ข้อมูลที่ชัดเจน เป็นขั้นตอน และเน้นความปลอดภัย"

        # Claude API call
        response = claude_client.messages.create(
            model=CLAUDE_MODEL_NAME,
            max_tokens=1024,  # Max length of the generated response
            temperature=0.6,  # Controls randomness. Lower is more deterministic.
            system=system_prompt,
            messages=[
                {"role": "user", "content": prompt_text}
            ]
        )

        # Extract the text content from the response
        # Claude's response structure is a list of content blocks.
        if response.content and len(response.content) > 0 and hasattr(response.content[0], 'text'):
            guidance = response.content[0].text
            print(f"Claude LLM Raw Response: {guidance}")
            return guidance.strip()
        else:
            print(f"Claude LLM returned an unexpected response structure: {response}")
            return "ขออภัย ระบบ AI ไม่สามารถสร้างคำแนะนำได้ในขณะนี้ (โครงสร้างตอบกลับไม่ถูกต้อง)"


    except anthropic.APIConnectionError as e:
        print(f"Claude API Connection Error: {e}")
        return "ขออภัย เกิดปัญหาในการเชื่อมต่อกับระบบ AI กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ตและลองอีกครั้ง"
    except anthropic.RateLimitError as e:
        print(f"Claude API Rate Limit Error: {e}")
        return "ขออภัย ขณะนี้มีการใช้งานระบบ AI หนาแน่นเกินไป กรุณารอสักครู่แล้วลองอีกครั้ง"
    except anthropic.APIStatusError as e:
        print(f"Claude API Status Error (Code: {e.status_code}): {e.response}")
        return f"ขออภัย ระบบ AI ตอบกลับมาพร้อมข้อผิดพลาด (สถานะ: {e.status_code}) กรุณาลองอีกครั้งในภายหลัง"
    except Exception as e:
        print(f"Error during Claude guidance generation: {e}")
        return f"เกิดข้อผิดพลาดในการสื่อสารกับระบบ AI (Claude): {str(e)}. กรุณาลองใหม่อีกครั้งในภายหลังหรือติดต่อ 1669"

# --- API 3: Guidance Generation (Sentence Only) ---
@app.route('/generate_guidance_sentence_only', methods=['POST', 'OPTIONS']) # Added OPTIONS
def api_generate_guidance_sentence_only():
    if request.method == 'OPTIONS': # Handle preflight for this route
        return _build_cors_preflight_response()
    # Actual POST request handling
    try:
        data = request.get_json()
        if not data or 'sentence' not in data:
            return jsonify({"error": "ไม่พบข้อมูล 'sentence' ในคำขอ"}), 400
        thai_sentence = data['sentence']
        if not isinstance(thai_sentence, str) or not thai_sentence.strip():
            return jsonify({"error": "'sentence' ต้องเป็นสตริงที่ไม่ว่างเปล่า"}), 400
        prompt = (
            f"โปรดให้คำแนะนำการปฐมพยาบาลเบื้องต้นเป็นภาษาไทยอย่างละเอียดและเป็นขั้นตอน "
            f"สำหรับสถานการณ์ฉุกเฉินที่อธิบายด้วยประโยคนี้: \"{thai_sentence}\". "
            f"เน้นความปลอดภัยของผู้ช่วยเหลือและผู้ป่วย และแนะนำให้ติดต่อหน่วยแพทย์ฉุกเฉิน (1669) เมื่อจำเป็นอย่างยิ่ง"
        )
        guidance_text = generate_guidance_with_llm(prompt)
        response = jsonify({"guidance": guidance_text})
        return _corsify_actual_response(response) # Add CORS headers to actual response
    except Exception as e:
        print(f"Error in /generate_guidance_sentence_only: {e}")
        return jsonify({"error": f"เกิดข้อผิดพลาดในการสร้างคำแนะนำ: {str(e)}"}), 500
    

def _build_cors_preflight_response():
    response = make_response()
    response.headers.add("Access-Control-Allow-Origin", "*") # Allow all origins
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization") # Allow specific headers
    response.headers.add("Access-Control-Allow-Methods", "POST,GET,OPTIONS") # Allow specific methods
    return response

def _corsify_actual_response(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response
    
if __name__ == '__main__':
    # Initialize the Claude client when the Flask app starts.
    print("Starting Flask application... Initializing Claude Client.")
    initialize_claude_client()
    print("Claude Client initialization process complete (or attempted). Starting web server.")
    
    # Make sure your requirements.txt includes:
    # Flask
    # pythainlp
    # anthropic
    # (and any other dependencies pythainlp might have for its core functions)
    app.run(debug=True, host='0.0.0.0', port=5001)