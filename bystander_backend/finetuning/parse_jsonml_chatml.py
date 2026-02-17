import json
import os

# Your input data (simulated from your JSON snippet)
# Use paths relative to this script so it works when invoked from repo root
BASE_DIR = os.path.dirname(__file__)
input_file = os.path.join(BASE_DIR, "bystander_chatml.jsonl")
output_file = os.path.join(BASE_DIR, "bystander_chatml_ready.jsonl")

def convert_to_chatml(input_path, output_path):
    with open(input_path, 'r', encoding='utf-8') as f_in, \
         open(output_path, 'w', encoding='utf-8') as f_out:
        
        for line in f_in:
            data = json.loads(line)
            messages = data.get("messages", [])
            
            # 1. Standardize System Prompt
            # OpenThaiGPT recommends: คุณคือผู้ช่วยตอบคำถามที่ฉลาดและซื่อสัตย์
            chatml_text = "<|im_start|>system\nคุณคือผู้ช่วยตอบคำถามที่ฉลาดและซื่อสัตย์<|im_end|>\n"
            
            # 2. Extract User Content
            user_content = ""
            assistant_content = ""
            
            for msg in messages:
                role = msg.get("role")
                content = msg.get("content")

                if role == "user":
                    if isinstance(content, str):
                        user_content = content
                    elif content is not None:
                        user_content = str(content)

                elif role == "assistant":
                    # Skip non-string assistant contents (e.g., NaN parsed as float)
                    if not isinstance(content, str):
                        continue
                    else:
                        assistant_content = content
            
            # 3. Construct the final ChatML string
            if user_content and assistant_content:
                chatml_text += f"<|im_start|>user\n{user_content}<|im_end|>\n"
                chatml_text += f"<|im_start|>assistant\n{assistant_content}<|im_end|>"
                
                # Write in the format SFTTrainer expects
                json.dump({"text": chatml_text}, f_out, ensure_ascii=False)
                f_out.write("\n")

convert_to_chatml(input_file, output_file)
print(f"File saved to {output_file}")