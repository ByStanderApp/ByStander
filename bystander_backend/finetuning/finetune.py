import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
    BitsAndBytesConfig
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer

# 1. Setup Model and Tokenizer
model_id = "openthaigpt/openthaigpt1.5-7b-instruct" #

# Optional: Use 4-bit quantization to save memory (QLoRA)
# If bitsandbytes isn't available on this system, fall back to disabling 4-bit
try:
    import bitsandbytes  # noqa: F401
    _load_in_4bit = True
except Exception:
    print("bitsandbytes not available; falling back to load_in_4bit=False")
    _load_in_4bit = False

# If CUDA is not available we cannot use 4-bit quantization; fall back safely
if _load_in_4bit and not torch.cuda.is_available():
    print("CUDA not available; disabling 4-bit quantization to avoid dispatch errors.")
    _load_in_4bit = False

bnb_config = BitsAndBytesConfig(
    load_in_4bit=_load_in_4bit,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16,
)

tokenizer = AutoTokenizer.from_pretrained(model_id)
tokenizer.pad_token = tokenizer.eos_token

# Prepare kwargs for from_pretrained depending on quantization/offload needs
load_kwargs = {}
if _load_in_4bit:
    # Allow safe offload of fp32 params to CPU when necessary and let HF auto map devices.
    load_kwargs.update({
        "device_map": "auto",
        "llm_int8_enable_fp32_cpu_offload": True,
        # Provide a generous CPU offload allowance; adjust if your machine is constrained.
        "max_memory": {"cpu": "200GB"},
    })
else:
    # When not using 4-bit, rely on automatic device placement (may still require ample GPU RAM)
    load_kwargs.update({"device_map": "auto"})

model = AutoModelForCausalLM.from_pretrained(
    model_id,
    quantization_config=bnb_config,
    **load_kwargs,
)

# 2. Prepare for PEFT
model = prepare_model_for_kbit_training(model)

peft_config = LoraConfig(
    r=64,             # Recommended rank for OpenThaiGPT
    lora_alpha=128,    # Recommended alpha
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM"
)

model = get_peft_model(model, peft_config)

# 3. Load Your Dataset (Example: Emergency Guidance Data)
# Your dataset should be in a format like: {"instruction": "...", "output": "..."}
dataset = load_dataset("json", data_files="bystander_chatml.jsonl", split="train")

# 4. Define Training Arguments
training_args = TrainingArguments(
    output_dir="./openthaigpt-bystander-adapter",
    per_device_train_batch_size=4,
    gradient_accumulation_steps=4,
    learning_rate=1e-4, # OpenThaiGPT 1.5 used 1e-4
    num_train_epochs=3,
    logging_steps=10,
    optim="paged_adamw_32bit",
    save_strategy="epoch",
    fp16=True,
)

# 5. Initialize Trainer
trainer = SFTTrainer(
    model=model,
    train_dataset=dataset,
    peft_config=peft_config,
    dataset_text_field="text", # Ensure your dataset has a 'text' field or use a formatting function
    max_seq_length=2048,
    tokenizer=tokenizer,
    args=training_args,
)

# 6. Start Training
trainer.train()

# 7. Save the Adapter
model.save_pretrained("./final-bystander-adapter")