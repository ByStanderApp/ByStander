from flask import Flask, request, jsonify, make_response
import json
import os
from openai import OpenAI  # DeepSeek uses the OpenAI SDK
from dotenv import load_dotenv

# Initialize Flask app
app = Flask(__name__)

# --- Global Variables for DeepSeek LLM ---
deepseek_client = None
DEEPSEEK_MODEL_NAME = "deepseek-chat" # DeepSeek's standard chat model

# --- Function to Initialize DeepSeek Client ---
def initialize_deepseek_client():
    """
    Initializes the DeepSeek client using the OpenAI SDK.
    Loads API key from .env file.
    """
    
    global deepseek_client
    load_dotenv() 
    api_key = os.environ.get("DEEPSEEK_KEY")
    if not api_key:
        print("CRITICAL ERROR: DEEPSEEK_KEY not found in .env file.")
        deepseek_client = None
        return

    try:
        # DeepSeek points to a specific base_url
        deepseek_client = OpenAI(
            api_key=api_key, 
            base_url="https://api.deepseek.com"
        )
        print(f"DeepSeek client initialized successfully.")
    except Exception as e:
        print(f"CRITICAL ERROR initializing DeepSeek client: {e}")
        deepseek_client = None


def generate_guidance_with_llm(prompt_text: str, language: str = "th") -> str:
    global deepseek_client

    if not deepseek_client:
        return "ขออภัย ระบบไม่พร้อมใช้งานในขณะนี้ โปรดโทร 1669"

    try:
        print(f"--- Calling DeepSeek LLM (Plain Text Mode) ---")
        
        # We explicitly tell the AI NOT to use asterisks or markdown
        system_prompt = (
            "คุณเป็นผู้ช่วยให้คำแนะนำการปฐมพยาบาลเบื้องต้น "
            "ข้อกำหนดสำคัญ: ห้ามใช้เครื่องหมายดอกจัน (*) หรือ Markdown (เช่น **ตัวหนา**) โดยเด็ดขาด "
            "ให้ตอบเป็นข้อความธรรมดา (Plain Text) เท่านั้น "
            "ใช้ตัวเลข (1, 2, 3) สำหรับขั้นตอนหลัก และใช้เครื่องหมายยัติภังค์ (-) สำหรับขั้นตอนย่อย"
        )

        response = deepseek_client.chat.completions.create(
            model=DEEPSEEK_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_text}
            ],
            temperature=0.3, # Lower temperature makes the AI follow formatting rules better
            stream=False
        )

        if response.choices:
            guidance = response.choices[0].message.content
            # Extra safety: strip out any asterisks if the AI accidentally includes them
            clean_guidance = guidance.replace("*", "").strip()
            return clean_guidance
        else:
            return "ไม่สามารถสร้างคำแนะนำได้ โปรดติดต่อ 1669"

    except Exception as e:
        print(f"Error: {e}")
        return "เกิดข้อผิดพลาดในการสื่อสารกับ AI โปรดโทร 1669"

# --- API: Guidance Generation ---
@app.route('/generate_guidance_sentence_only', methods=['POST', 'OPTIONS'])
def api_generate_guidance_sentence_only():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
    
    try:
        data = request.get_json()
        thai_sentence = data.get('sentence', '')

        # Updated prompt to match the structure of your image
        prompt = ( 
            f"สถานการณ์: \"{thai_sentence}\" "
            "หากเป็นเหตุฉุกเฉิน ให้ขึ้นต้นว่า สถานการณ์นี้เป็นเหตุฉุกเฉิน "
            "จากนั้นให้คำแนะนำเป็นลำดับขั้นตอนดังนี้: "
            "1. ประเมินความปลอดภัย "
            "2. โทรขอความช่วยเหลือ (ระบุเบอร์ 1669) "
            "3. การปฐมพยาบาลเบื้องต้นตามสถานการณ์ที่ได้รับแจ้ง "
            "4. การรอความช่วยเหลือ "
            "ย้ำ: ห้ามใส่เครื่องหมายดอกจัน (*) ในคำตอบ ให้ใช้เพียงข้อความธรรมดาเท่านั้น"
        )
        
        guidance_text = generate_guidance_with_llm(prompt)
        return _corsify_actual_response(jsonify({"guidance": guidance_text}))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

def _build_cors_preflight_response():
    response = make_response()
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "POST,GET,OPTIONS")
    return response

def _corsify_actual_response(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response
    
if __name__ == '__main__':
    print("Starting Flask application... Initializing DeepSeek Client.")
    initialize_deepseek_client()
    app.run(debug=True, host='0.0.0.0', port=5001)