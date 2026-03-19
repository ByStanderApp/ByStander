# Placeholder for structured output
def postprocess(claude_response, params=None):
    print(f"[SCRIPT postprocess_structured_output_v3.py] Structuring: {claude_response}")
    steps = []
    if "Step 1:" in claude_response:
        steps = [s.strip() for s in claude_response.split("Step")[1:]]
        steps = [f"Action {i}: {s.split(':')[1].strip() if ':' in s else s}" for i, s in enumerate(steps, 1)]

    # Simulate adding Thai context
    processed_output = {
        "summary": claude_response.split('.')[0] if '.' in claude_response else claude_response,
        "guidance_steps": steps or ["Refer to raw response."],
        "suggested_actions_thai": []
    }
    if "call 191" in claude_response.lower():
        processed_output["suggested_actions_thai"].append("โทรแจ้งตำรวจ 191")
    if "call 1669" in claude_response.lower():
        processed_output["suggested_actions_thai"].append("โทรเรียกรถพยาบาล 1669")

    return processed_output