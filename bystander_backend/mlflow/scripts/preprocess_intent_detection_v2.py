
def preprocess(query, params=None):
    print(f"[SCRIPT preprocess_intent_detection_v2.py] Detecting intent for: {query}")
    intent = "guidance" # Simulated
    if "operator" in query.lower():
        intent = "operator_script"
    elif "hospital" in query.lower() or "clinic" in query.lower():
        intent = "facility_finding"
    return {"original_query": query, "detected_intent": intent}