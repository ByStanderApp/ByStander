import mlflow
import os
import json
import importlib.util # To import script functions dynamically
import anthropic
from dotenv import load_dotenv
import pandas as pd

# --- Global Claude Client and API Key ---
load_dotenv() 
CLAUDE_API_KEY = os.environ.get("CLAUDE_KEY")
claude_client = None 

# --- Configuration for each Version ---
VERSIONS_CONFIG = {
    "V1_Baseline": {
        "run_name": "ByStander_V1_Baseline_Direct_MultiScenario", 
        "description": "Version 1: Direct query to Claude, raw output, tested on multiple scenarios.",
        "prompt_file": "prompts/generic_prompt_template_v1.txt",
        "preprocessing_script_path": "scripts/preprocess_minimal_v1.py",
        "preprocessing_function_name": "preprocess",
        "postprocessing_script_path": "scripts/postprocess_raw_v1.py",
        "postprocessing_function_name": "postprocess",
        "params": {"claude_model_id": "claude-3-haiku-20240307"},
        "qualitative_metrics": {"overall_clarity": 3, "overall_actionability": 2, "overall_thai_relevance": 2} 
    },
    "V2_Prompt_Engineer": {
        "run_name": "ByStander_V2_Prompt_Engineered_MultiScenario",
        "description": "Version 2: Context-enhanced & role-specific prompting, tested on multiple scenarios.",
        "prompt_file": "prompts/guidance_prompt_template_v2.txt",
        "preprocessing_script_path": "scripts/preprocess_intent_detection_v2.py",
        "preprocessing_function_name": "preprocess",
        "postprocessing_script_path": "scripts/postprocess_raw_v2.py",
        "postprocessing_function_name": "postprocess",
        "params": {"claude_model_id": "claude-3-haiku-20240307", "prompt_focus": "guidance_thai_context"},
        "qualitative_metrics": {"overall_clarity": 4, "overall_actionability": 4, "overall_thai_relevance": 4}
    },
    "V3_App_Integrator": {
        "run_name": "ByStander_V3_Structured_IO_MultiScenario",
        "description": "Version 3: Structured I/O & application-aware logic, tested on multiple scenarios.",
        "prompt_file": "prompts/dynamic_prompt_template_v3.txt",
        "preprocessing_script_path": "scripts/preprocess_entity_extraction_v3.py",
        "preprocessing_function_name": "preprocess",
        "postprocessing_script_path": "scripts/postprocess_structured_output_v3.py",
        "postprocessing_function_name": "postprocess",
        "params": {
            "claude_model_id": "claude-3-haiku-20240307",
            "context": {"location_context": "Thailand", "app_name": "ByStander"}
        },
        "qualitative_metrics": {"overall_clarity": 5, "overall_actionability": 5, "overall_thai_relevance": 5, "overall_ui_suitability": 4}
    }
}

# --- Helper function to load module and function from script path ---
def load_function_from_script(script_path, function_name):
    spec = importlib.util.spec_from_file_location(
        os.path.basename(script_path).replace(".py", ""), script_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, function_name)


# --- Function to Initialize Claude Client Globally ---
def initialize_claude_client_globally():
    global claude_client
    if not CLAUDE_API_KEY:
        print("CRITICAL ERROR: CLAUDE_KEY environment variable not found.")
        claude_client = None
        return

    try:
        claude_client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        print(f"Anthropic client initialized successfully.")
    except Exception as e:
        print(f"CRITICAL ERROR initializing Anthropic client: {e}")
        claude_client = None

# --- Claude API Call (Modified to return token counts) ---
def call_claude_api(prompt_text, version_name="Unknown", model_id="claude-3-haiku-20240307", max_tokens=1024):
    global claude_client
    if claude_client is None:
        error_message = "Claude client is not initialized. Cannot make API call."
        print(f"[API Call Error for {version_name}] {error_message}")
        return f"Error: {error_message}", 0, 0

    print(f"\n[Real Claude API Call for {version_name}] Sending prompt to model '{model_id}':")
    print("------------------------------------")
    print(prompt_text)
    print("------------------------------------")

    input_tokens = 0
    output_tokens = 0

    try:
        response = claude_client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            messages=[
                {"role": "user", "content": prompt_text}
            ]
        )
        
        if response.content and len(response.content) > 0 and hasattr(response.content[0], 'text'):
            claude_response_text = response.content[0].text
            print(f"[Real Claude API] Received response: {claude_response_text[:200]}...\n")
            
            if response.usage:
                input_tokens = response.usage.input_tokens
                output_tokens = response.usage.output_tokens
                print(f"[Real Claude API] Tokens used - Input: {input_tokens}, Output: {output_tokens}")
            return claude_response_text, input_tokens, output_tokens
        else:
            error_message = "Claude API response was empty or not in the expected format."
            print(f"[Real Claude API] Error: {error_message}")
            return f"Error: {error_message}", input_tokens, output_tokens

    except Exception as e:
        error_message = f"Error calling Claude API: {str(e)}"
        print(error_message)
        # Log error artifact if an MLflow run is active (this function might be called during setup)
        if mlflow.active_run():
            mlflow.log_param(f"{version_name}_api_error_details", error_message)
            error_artifact_path = f"claude_api_error_{version_name}.txt"
            with open(error_artifact_path, "w") as f_err:
                f_err.write(f"Prompt that caused error:\n{prompt_text}\n\nError:\n{str(e)}")
            mlflow.log_artifact(error_artifact_path)
        return f"Error: {error_message}", input_tokens, output_tokens


# --- Main Experiment Function (Modified for multiple scenarios) ---
def run_bystander_experiment(version_key, config, list_of_user_queries): # Takes a list of queries
    print(f"\n--- Starting Experiment for Version: {version_key} (Multiple Scenarios) ---")
    with mlflow.start_run(run_name=config["run_name"]) as run:
        mlflow.set_tag("version_key", version_key)
        mlflow.log_param("description", config["description"])
        if "params" in config:
            mlflow.log_params(config["params"])
        
        # Log general artifacts for the version (prompts, scripts)
        if os.path.exists(config["prompt_file"]):
            mlflow.log_artifact(config["prompt_file"], artifact_path="version_setup/prompts")
        mlflow.log_param("prompt_template_file", os.path.basename(config["prompt_file"]))

        if os.path.exists(config["preprocessing_script_path"]):
            mlflow.log_artifact(config["preprocessing_script_path"], artifact_path="version_setup/scripts")
        mlflow.log_param("preprocessing_script", os.path.basename(config["preprocessing_script_path"]))

        if os.path.exists(config["postprocessing_script_path"]):
            mlflow.log_artifact(config["postprocessing_script_path"], artifact_path="version_setup/scripts")
        mlflow.log_param("postprocessing_script", os.path.basename(config["postprocessing_script_path"]))


        preprocess_fn = load_function_from_script(config["preprocessing_script_path"], config["preprocessing_function_name"])
        postprocess_fn = load_function_from_script(config["postprocessing_script_path"], config["postprocessing_function_name"])
        model_to_use = config.get("params", {}).get("claude_model_id", "claude-3-haiku-20240307")

        all_scenarios_data = []
        total_input_tokens_for_run = 0
        total_output_tokens_for_run = 0

        for i, user_query in enumerate(list_of_user_queries):
            scenario_id = f"scenario_{i+1:02d}"
            print(f"\n  Processing {scenario_id}: '{user_query[:50]}...' for version {version_key}")

            scenario_data = {
                "scenario_id": scenario_id,
                "user_query": user_query,
                "processed_input": None,
                "actual_prompt_sent": None,
                "claude_raw_response": None,
                "final_bystander_output": None,
                "input_tokens": 0,
                "output_tokens": 0,
                "api_error": None
            }

            # 1. Pre-processing
            processed_input = preprocess_fn(user_query, params=config.get("params"))
            scenario_data["processed_input"] = json.dumps(processed_input, ensure_ascii=False) if isinstance(processed_input, dict) else str(processed_input)

            # 2. Load and format prompt
            with open(config["prompt_file"], 'r', encoding='utf-8') as f:
                prompt_template = f.read()
            
            actual_prompt = prompt_template.replace("[user_query]", str(user_query))
            if isinstance(processed_input, dict): # For V3 style
                if "raw_query" in processed_input:
                     actual_prompt = prompt_template.replace("[user_query]", processed_input.get("raw_query", user_query))
                actual_prompt = actual_prompt.replace("[extracted_entities]", json.dumps(processed_input.get("locations", []), ensure_ascii=False))
                actual_prompt = actual_prompt.replace("[emergency_type]", processed_input.get("emergency_type", "not specified"))
                actual_prompt = actual_prompt.replace("[location_context]", config.get("params", {}).get("context", {}).get("location_context", "Thailand"))
            scenario_data["actual_prompt_sent"] = actual_prompt

            # 3. Call Claude
            claude_response, in_tokens, out_tokens = call_claude_api(
                prompt_text=actual_prompt,
                version_name=f"{version_key}_{scenario_id}", 
                model_id=model_to_use
            )
            scenario_data["claude_raw_response"] = claude_response
            scenario_data["input_tokens"] = in_tokens
            scenario_data["output_tokens"] = out_tokens
            total_input_tokens_for_run += in_tokens
            total_output_tokens_for_run += out_tokens
            if claude_response.startswith("Error:"):
                scenario_data["api_error"] = claude_response


            # 4. Post-processing
            final_output = postprocess_fn(claude_response, params=config.get("params"))
            scenario_data["final_bystander_output"] = json.dumps(final_output, indent=2, ensure_ascii=False) if isinstance(final_output, dict) else str(final_output)
            
            all_scenarios_data.append(scenario_data)

        # Log the collected data for all scenarios as a table
        if all_scenarios_data:
            scenario_df = pd.DataFrame(all_scenarios_data)
            mlflow.log_table(data=scenario_df, artifact_file="scenario_results.json") # Log the DataFrame

        # Log total token usage for the run
        mlflow.log_metric("total_input_tokens", total_input_tokens_for_run)
        mlflow.log_metric("total_output_tokens", total_output_tokens_for_run)

        # Log overall qualitative metrics for the version's strategy
        if "qualitative_metrics" in config:
            mlflow.log_metrics(config["qualitative_metrics"])

        print(f"MLflow Run ID for {version_key} (Multi-Scenario): {run.info.run_id}")
        print(f"--- Experiment for {version_key} Complete ---")


if __name__ == "__main__":
    initialize_claude_client_globally()
    if claude_client is None:
        print("Exiting script due to Claude client initialization failure.")
        exit()

    # Define your list of emergency scenarios (user queries)
    emergency_scenarios = [
        "มีอุบัติเหตุรถชนกันใกล้ BTS อโศก มีคนเจ็บ ต้องการคำแนะนำด่วน",
        "ตึกถล่มที่สีลม ช่วยด้วย มีคนติดอยู่ข้างใน",
        "พบคนหมดสติ ไม่หายใจ แถวสยามสแควร์ ต้องทำยังไง",
        "ไฟไหม้บ้านที่คลองเตย มีควันเยอะมาก",
        "มีคนชักอยู่ในรถที่จอดอยู่ริมถนน",
        "มีคนอาหารติดคออยู่ใกล้ฉัน"
    ]

    # Run experiments for all versions, each with all scenarios
    for version_key_name, version_config_data in VERSIONS_CONFIG.items():
        run_bystander_experiment(version_key_name, version_config_data, emergency_scenarios)

    print("\nAll multi-scenario experiments complete.")
    print("To view results, run 'mlflow ui' in your terminal in this directory.")