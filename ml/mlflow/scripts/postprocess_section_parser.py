import re
import json

def parse_sections(raw_response):
    """Parses the Claude response based on specific section headers."""
    sections = {
        "assessment_raw": None,
        "guidance_raw": None,
        "reasoning_raw": None,
    }
    # Use regex to find content between headers or from header to end, ignoring case of headers
    assessment_match = re.search(r"===EMERGENCY ASSESSMENT===(.*?)(?:===GUIDANCE THAI===|===REASONING THAI===|\Z)", raw_response, re.DOTALL | re.IGNORECASE)
    guidance_match = re.search(r"===GUIDANCE THAI===(.*?)(?:===REASONING THAI===|\Z)", raw_response, re.DOTALL | re.IGNORECASE)
    reasoning_match = re.search(r"===REASONING THAI===(.*)", raw_response, re.DOTALL | re.IGNORECASE)

    if assessment_match:
        sections["assessment_raw"] = assessment_match.group(1).strip()
    if guidance_match:
        sections["guidance_raw"] = guidance_match.group(1).strip()
    if reasoning_match:
        sections["reasoning_raw"] = reasoning_match.group(1).strip()
    return sections

def postprocess(claude_response, params=None):
    """Processes the sectioned Claude response into a structured dictionary."""
    print(f"[SCRIPT postprocess_section_parser.py] Parsing response:\n{claude_response[:300]}...") # Log snippet

    sections = parse_sections(claude_response)
    processed_output = {
        "is_emergency": False,
        "assessment_reasoning_en": "Error: Assessment section not found.",
        "guidance_thai": None,
        "guidance_reasoning_thai": None,
        "raw_claude_output": claude_response # Keep raw for debugging
    }

    # Process Assessment
    if sections["assessment_raw"]:
        assessment_text = sections["assessment_raw"]
        if re.match(r"^\s*YES", assessment_text, re.IGNORECASE): # Check start ignoring case/space
            processed_output["is_emergency"] = True
            processed_output["assessment_reasoning_en"] = re.sub(r"^\s*YES\.?\s*", "", assessment_text, flags=re.IGNORECASE).strip()
        elif re.match(r"^\s*NO", assessment_text, re.IGNORECASE):
             processed_output["is_emergency"] = False
             processed_output["assessment_reasoning_en"] = re.sub(r"^\s*NO\.?\s*", "", assessment_text, flags=re.IGNORECASE).strip()
        else:
             processed_output["assessment_reasoning_en"] = f"Warning: Could not parse YES/NO from assessment: {assessment_text}"
             # Attempt to infer based on guidance/reasoning presence if assessment is unclear
             if (sections["guidance_raw"] and sections["guidance_raw"].upper() != "N/A") or \
                (sections["reasoning_raw"] and sections["reasoning_raw"].upper() != "N/A"):
                 processed_output["is_emergency"] = True
                 print("[SCRIPT WARNING] Assessment unclear, but inferring YES based on guidance/reasoning presence.")


    # Process Guidance (only if emergency was determined)
    if processed_output["is_emergency"] and sections["guidance_raw"] and sections["guidance_raw"].upper() != "N/A":
        guidance_steps = [step.strip() for step in sections["guidance_raw"].split('\n') if step.strip()]
        # # Remove potential numbering like "1.", "2." for cleaner list
        # guidance_steps = [re.sub(r"^\d+\.\s*", "", step) for step in guidance_steps]
        processed_output["guidance_thai"] = guidance_steps if guidance_steps else None # Ensure not empty list
    elif not processed_output["is_emergency"] and sections["guidance_raw"] and sections["guidance_raw"].upper() != "N/A":
         print("[SCRIPT WARNING] Guidance found but assessment was NO or unclear. Discarding guidance.")
         processed_output["guidance_thai"] = None


    # Process Reasoning (only if emergency was determined)
    if processed_output["is_emergency"] and sections["reasoning_raw"] and sections["reasoning_raw"].upper() != "N/A":
        processed_output["guidance_reasoning_thai"] = sections["reasoning_raw"]
    elif not processed_output["is_emergency"] and sections["reasoning_raw"] and sections["reasoning_raw"].upper() != "N/A":
        print("[SCRIPT WARNING] Reasoning found but assessment was NO or unclear. Discarding reasoning.")
        processed_output["guidance_reasoning_thai"] = None

    return processed_output