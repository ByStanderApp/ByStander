from flask import Flask, request, jsonify, make_response
import json
import os
from llama_cpp import Llama
from dotenv import load_dotenv
import requests

# Initialize Flask app
app = Flask(__name__)

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(dotenv_path=ENV_PATH, override=True)

# --- Global Variables for Local Llama LLM ---
llm = None
DEFAULT_MODEL_PATH = os.getenv("LLAMA_MODEL_PATH")

# --- Function to Initialize Local Llama Model ---
def initialize_llama_model():
    """
    Initializes llama.cpp local model (M1-optimized settings from otg_llama.py).
    Loads optional model path from .env file using LLAMA_MODEL_PATH.
    """

    global llm
    load_dotenv()
    model_path = os.environ.get("LLAMA_MODEL_PATH", DEFAULT_MODEL_PATH)

    if not os.path.exists(model_path):
        print(f"CRITICAL ERROR: Model file not found at: {model_path}")
        llm = None
        return

    try:
        llm = Llama(
            model_path=model_path,
            n_gpu_layers=-1,
            n_ctx=4096,
            f16_kv=True,
            verbose=True,
        )
        print(f"Llama model initialized successfully from: {model_path}")
    except Exception as e:
        print(f"CRITICAL ERROR initializing Llama model: {e}")
        llm = None

def generate_guidance_with_llm(prompt_text: str) -> dict:
    global llm
    if not llm:
        return {"error": "ระบบไม่พร้อมใช้งาน โปรดโทร 1669"}

    try:
        # Instruct the model to return a JSON object with three fields:
        # - guidance: the step-by-step advice (plain text, no asterisks). If the
        #   situation is an emergency, the guidance should start with
        #   "สถานการณ์นี้เป็นเหตุฉุกเฉิน".
        # - severity: one of: "critical", "mild", "none"
        # - facility_type: one of: "hospital", "clinic", "none"
        system_prompt = (
            "You are the ByStander Emergency Intelligence Engine, a professional medical dispatcher" 
            "specializing in Thai emergency protocols. Your goal is to provide immediate," 
            "stress-resistant, and factually perfect first-aid guidance."

            "OPERATIONAL RULES:"
                "1. LANGUAGE: Use professional yet easy-to-understand Thai (Central dialect)."
                "2. TONE: Calm, authoritative, and instructional to minimize user panic."
                "3. LOGIC: "
                    "- If the input is a MEDICAL/ACCIDENTAL emergency, categorize it as 'critical' or 'mild'."
                    "- If the input is NOT an emergency, categorize it as 'none' and provide a helpful, brief advisory."
                "4. SAFETY: Never provide instructions that require professional medical equipment unless specified in the context."
                "5. FORMAT: Output strictly in valid JSON. No Markdown formatting, no asterisks, no conversational filler."
        )

        user_prompt = (
            f"สถานการณ์: \"{prompt_text}\"\n"
            "ตอบเป็น JSON ที่มีฟิลด์: guidance, severity, facility_type. "
            "guidance:"
                "- หากเป็นเหตุฉุกเฉิน: เริ่มต้นด้วยประโยค 'สถานการณ์นี้เป็นเหตุฉุกเฉิน' ตามด้วยขั้นตอนการปฐมพยาบาลแบบ Step-by-Step ที่ละเอียดและถูกต้องตามหลักการแพทย์ไทย" 
                "- หากไม่ใช่เหตุฉุกเฉิน: เริ่มต้นด้วย 'สถานการณ์นี้ไม่ใช่เหตุฉุกเฉิน' และให้คำแนะนำเบื้องต้นที่เหมาะสม"
                "- ข้อกำหนด: ห้ามใช้เครื่องหมายดอกจัน (*) หรือสัญลักษณ์พิเศษ ให้ใช้เพียงลำดับตัวเลข 1, 2, 3 เท่านั้น"
            "severity: วิเคราะห์ระดับความรุนแรง เลือกเพียงหนึ่งค่า: [\"critical\", \"mild\", \"none\"]. "
            "facility_type: วิเคราะห์ระดับความรุนแรง เลือกเพียงหนึ่งค่า: [\"hospital\", \"clinic\", \"none\"]. "
            "ห้ามใส่เครื่องหมายดอกจัน (*) ในคำตอบ. ห้ามใส่คำอธิบายอื่นๆ นอกเหนือจาก JSON."
        )

        print(f"Sending prompt to local Llama: {user_prompt}")

        response = llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=1024,
            temperature=0.1,      # Low temperature = more factual/less "dumb" hallucination 
            top_p=0.9,
            repeat_penalty=1.1,
        )

        print(f"Received response from local Llama: {response}")

        if not isinstance(response, dict) or not response.get("choices"):
            return {"error": "ไม่สามารถสร้างคำแนะนำได้ โปรดติดต่อ 1669"}

        content = response["choices"][0]["message"]["content"].strip()

        # Try to parse JSON directly, otherwise try to extract JSON substring.
        import json
        try:
            parsed = json.loads(content)
            return parsed
        except Exception:
            # attempt to find a JSON object inside the text
            start = content.find('{')
            end = content.rfind('}')
            if start != -1 and end != -1 and end > start:
                try:
                    parsed = json.loads(content[start:end+1])
                    return parsed
                except Exception:
                    pass

        # Fallback: return the raw text in guidance field
        return {"guidance": content, "severity": "none", "facility_type": "none"}

    except Exception as e:
        print(f"Error: {e}")
        return {"error": "เกิดข้อผิดพลาดในการสื่อสารกับ AI โปรดโทร 1669"}


def synthesize_speech_with_google(text: str) -> dict:
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return {"error": "Google API key not configured"}

    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}"
    payload = {
        "input": {"text": text},
        "voice": {
            "languageCode": "th-TH",
            "name": "th-TH-Standard-A",
            "ssmlGender": "FEMALE"
        },
        "audioConfig": {
            "audioEncoding": "MP3",
            "speakingRate": 1.0,
            "pitch": 0.0
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        audio_content = data.get("audioContent")
        if not audio_content:
            return {"error": "ไม่สามารถสร้างเสียงได้"}
        return {"audioContent": audio_content}
    except requests.RequestException as e:
        try:
            error_data = response.json() if 'response' in locals() else {}
            message = error_data.get("error", {}).get("message", str(e))
        except Exception:
            message = str(e)
        return {"error": f"Google TTS error: {message}"}

# --- API: Guidance Generation ---
@app.route('/generate_guidance_sentence_only', methods=['POST', 'OPTIONS'])
def api_generate_guidance_sentence_only():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
    
    try:
        data = request.get_json()
        prompt_text = data.get('sentence', '')
        
        if not prompt_text:
            return _corsify_actual_response(jsonify({"error": "prompt is required"})), 400
        
        result = generate_guidance_with_llm(prompt_text)
        
        if not isinstance(result, dict):
            return _corsify_actual_response(jsonify({"error": "ไม่สามารถสร้างคำแนะนำได้ โปรดติดต่อ 1669"})), 503

        if result.get('error'):
            return _corsify_actual_response(jsonify(result)), 503

        # Ensure we have the expected fields
        guidance = result.get('guidance') if isinstance(result, dict) else None
        severity = result.get('severity') if isinstance(result, dict) else 'none'
        facility_type = result.get('facility_type') if isinstance(result, dict) else 'none'

        return _corsify_actual_response(jsonify({
            "guidance": guidance,
            "severity": severity,
            "facility_type": facility_type
        }))
    except Exception as e:
        return _corsify_actual_response(jsonify({"error": str(e)})), 500


@app.route('/synthesize_speech', methods=['POST', 'OPTIONS'])
def api_synthesize_speech():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()

    try:
        data = request.get_json() or {}
        text = data.get('text', '').strip()

        if not text:
            return _corsify_actual_response(jsonify({"error": "text is required"})), 400

        result = synthesize_speech_with_google(text)
        if result.get("error"):
            return _corsify_actual_response(jsonify(result)), 503

        return _corsify_actual_response(jsonify(result))
    except Exception as e:
        return _corsify_actual_response(jsonify({"error": str(e)})), 500
    

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
    print("Starting Flask application... Initializing local Llama model.")
    initialize_llama_model()
    app.run(debug=True, host='0.0.0.0', port=5001)