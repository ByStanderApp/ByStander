#!/usr/bin/env python3
import argparse
import inspect
import json
import os
from typing import Any, Dict, Optional, Tuple

from datasets import Dataset, load_dataset
from trl import SFTTrainer
from transformers import TrainingArguments
from unsloth import FastLanguageModel, is_bfloat16_supported


BASE_DIR = os.path.dirname(__file__)
DEFAULT_DATASET_PATH = os.path.join(BASE_DIR, "bystander_augmented_gemini.jsonl")


SYSTEM_PROMPT = (
    "You are the ByStander Emergency Intelligence Engine, a professional medical dispatcher "
    "specializing in Thai emergency protocols. Your goal is to provide immediate, "
    "stress-resistant, and factually perfect first-aid guidance. "
    "OPERATIONAL RULES: "
    "1. LANGUAGE: Use professional yet easy-to-understand Thai (Central dialect). "
    "2. TONE: Calm, authoritative, and instructional to minimize user panic. "
    "3. LOGIC: If the input is a MEDICAL/ACCIDENTAL emergency, categorize it as 'critical' or 'mild'. "
    "If the input is NOT an emergency, categorize it as 'none' and provide a helpful, brief advisory. "
    "4. SAFETY: Never provide instructions that require professional medical equipment unless specified in context. "
    "5. FORMAT: Output strictly in valid JSON with keys guidance, severity, facility_type. "
    "No Markdown formatting, no asterisks, no conversational filler."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Production fine-tuning for ByStander (Unsloth + LoRA).")
    parser.add_argument("--dataset-path", default=DEFAULT_DATASET_PATH, help="Path to JSONL training file.")
    parser.add_argument("--base-model", default="typhoon-ai/llama3.2-typhoon2-1b", help="HF base model name.")
    parser.add_argument("--output-dir", default=os.path.join(BASE_DIR, "outputs", "bystander_sft"), help="Output directory.")
    parser.add_argument("--max-seq-length", type=int, default=2048)
    parser.add_argument("--load-in-4bit", action="store_true", default=True)
    parser.add_argument("--no-load-in-4bit", action="store_false", dest="load_in_4bit")
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=16)
    parser.add_argument("--lora-dropout", type=float, default=0.0)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--num-epochs", type=float, default=3.0)
    parser.add_argument("--max-steps", type=int, default=-1, help="Override epoch training if > 0.")
    parser.add_argument("--warmup-steps", type=int, default=50)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--eval-ratio", type=float, default=0.05, help="Validation split ratio.")
    parser.add_argument("--logging-steps", type=int, default=10)
    parser.add_argument("--save-steps", type=int, default=100)
    parser.add_argument("--eval-steps", type=int, default=100)
    parser.add_argument("--seed", type=int, default=3407)
    parser.add_argument("--save-gguf", action="store_true", help="Export GGUF q4_k_m after training.")
    return parser.parse_args()


def normalize_severity(v: Any) -> str:
    s = str(v or "").strip().lower()
    if s in {"critical", "mild", "none"}:
        return s
    return "none"


def normalize_facility(v: Any) -> str:
    s = str(v or "").strip().lower()
    if s in {"hospital", "clinic", "none"}:
        return s
    return "none"


def build_user_prompt(input_text: str) -> str:
    return (
        f"สถานการณ์: \"{input_text}\"\n"
        "ตอบเป็น JSON ที่มีฟิลด์: guidance, severity, facility_type. "
        "guidance: "
        "- หากเป็นเหตุฉุกเฉิน: เริ่มต้นด้วยประโยค 'สถานการณ์นี้เป็นเหตุฉุกเฉิน' "
        "ตามด้วยขั้นตอนการปฐมพยาบาลแบบ Step-by-Step ที่ละเอียดและถูกต้องตามหลักการแพทย์ไทย "
        "- หากไม่ใช่เหตุฉุกเฉิน: เริ่มต้นด้วย 'สถานการณ์นี้ไม่ใช่เหตุฉุกเฉิน' และให้คำแนะนำเบื้องต้นที่เหมาะสม "
        "- ข้อกำหนด: ห้ามใช้เครื่องหมายดอกจัน (*) หรือสัญลักษณ์พิเศษ ให้ใช้เพียงลำดับตัวเลข 1, 2, 3 เท่านั้น "
        "severity: วิเคราะห์ระดับความรุนแรง เลือกเพียงหนึ่งค่า: [\"critical\", \"mild\", \"none\"]. "
        "facility_type: วิเคราะห์ระดับความรุนแรง เลือกเพียงหนึ่งค่า: [\"hospital\", \"clinic\", \"none\"]. "
        "ห้ามใส่เครื่องหมายดอกจัน (*) ในคำตอบ. ห้ามใส่คำอธิบายอื่นๆ นอกเหนือจาก JSON."
    )


def make_target_json(row: Dict[str, Any]) -> str:
    guidance = str(row.get("guidance", "") or "").strip()
    severity = normalize_severity(row.get("severity", "none"))
    facility = normalize_facility(row.get("facility_type", "none"))

    # If guidance is missing, try extracting from "output" legacy field.
    if not guidance:
        output_text = str(row.get("output", "") or "").strip()
        if output_text:
            if "|" in output_text:
                guidance = output_text.split("|", 1)[0].strip()
            else:
                # If output looks like JSON already, parse it.
                try:
                    parsed = json.loads(output_text)
                    if isinstance(parsed, dict):
                        guidance = str(parsed.get("guidance", "") or "").strip()
                        severity = normalize_severity(parsed.get("severity", severity))
                        facility = normalize_facility(parsed.get("facility_type", facility))
                except Exception:
                    guidance = output_text

    if not guidance:
        guidance = "สถานการณ์นี้ไม่ใช่เหตุฉุกเฉิน 1. ประเมินอาการ 2. ติดตามอาการ 3. หากแย่ลงให้โทร 1669"

    target = {
        "guidance": guidance,
        "severity": severity,
        "facility_type": facility,
    }
    return json.dumps(target, ensure_ascii=False)


def format_chat_text(input_text: str, target_json: str) -> str:
    user_content = build_user_prompt(input_text=input_text)
    return (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
        f"{SYSTEM_PROMPT}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
        f"{user_content}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
        f"{target_json}<|eot_id|>"
    )


def format_dataset_batch(examples: Dict[str, Any]) -> Dict[str, Any]:
    inputs = examples.get("input", [])
    texts = []
    for i in range(len(inputs)):
        row = {k: examples[k][i] for k in examples.keys()}
        input_text = str(row.get("input", "") or "").strip()
        if not input_text:
            texts.append("")
            continue
        target_json = make_target_json(row)
        texts.append(format_chat_text(input_text=input_text, target_json=target_json))
    return {"text": texts}


def load_and_prepare_dataset(path: str, eval_ratio: float, seed: int) -> Tuple[Dataset, Optional[Dataset]]:
    ds = load_dataset("json", data_files={"train": path}, split="train")
    if len(ds) == 0:
        raise RuntimeError(f"Dataset is empty: {path}")

    ds = ds.filter(lambda x: str(x.get("input", "") or "").strip() != "")
    ds = ds.map(format_dataset_batch, batched=True, desc="Formatting chat dataset")
    ds = ds.filter(lambda x: str(x.get("text", "") or "").strip() != "")

    if len(ds) < 20 or eval_ratio <= 0.0:
        return ds, None

    split = ds.train_test_split(test_size=eval_ratio, seed=seed, shuffle=True)
    return split["train"], split["test"]


def main() -> None:
    args = parse_args()

    if not os.path.exists(args.dataset_path):
        raise FileNotFoundError(f"Dataset not found: {args.dataset_path}")

    os.makedirs(args.output_dir, exist_ok=True)

    print(f"Loading dataset: {args.dataset_path}")
    train_ds, eval_ds = load_and_prepare_dataset(
        path=args.dataset_path,
        eval_ratio=args.eval_ratio,
        seed=args.seed,
    )
    print(f"Train samples: {len(train_ds)}")
    print(f"Eval samples: {len(eval_ds) if eval_ds is not None else 0}")

    print(f"Loading base model: {args.base_model}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base_model,
        max_seq_length=args.max_seq_length,
        dtype=None,
        load_in_4bit=args.load_in_4bit,
    )

    model = FastLanguageModel.get_peft_model(
        model,
        r=args.lora_r,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=args.seed,
    )

    eval_strategy = "steps" if eval_ds is not None else "no"
    training_kwargs = dict(
        output_dir=args.output_dir,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=max(1, args.batch_size),
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.learning_rate,
        num_train_epochs=args.num_epochs,
        max_steps=args.max_steps,
        warmup_steps=args.warmup_steps,
        weight_decay=args.weight_decay,
        logging_steps=args.logging_steps,
        eval_steps=args.eval_steps,
        save_strategy="steps",
        save_steps=args.save_steps,
        save_total_limit=3,
        load_best_model_at_end=(eval_ds is not None),
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        fp16=not is_bfloat16_supported(),
        bf16=is_bfloat16_supported(),
        optim="adamw_8bit",
        lr_scheduler_type="cosine",
        seed=args.seed,
        report_to="none",
    )

    # Transformers compatibility: some versions use eval_strategy, others evaluation_strategy.
    ta_params = inspect.signature(TrainingArguments.__init__).parameters
    if "evaluation_strategy" in ta_params:
        training_kwargs["evaluation_strategy"] = eval_strategy
    else:
        training_kwargs["eval_strategy"] = eval_strategy

    sft_params = inspect.signature(SFTTrainer.__init__).parameters
    sft_kwargs: Dict[str, Any] = {
        "model": model,
        "train_dataset": train_ds,
        "eval_dataset": eval_ds,
        "args": TrainingArguments(**training_kwargs),
    }
    if "tokenizer" in sft_params:
        sft_kwargs["tokenizer"] = tokenizer
    elif "processing_class" in sft_params:
        sft_kwargs["processing_class"] = tokenizer
    if "dataset_text_field" in sft_params:
        sft_kwargs["dataset_text_field"] = "text"
    if "max_seq_length" in sft_params:
        sft_kwargs["max_seq_length"] = args.max_seq_length
    if "dataset_num_proc" in sft_params:
        sft_kwargs["dataset_num_proc"] = 2
    if "packing" in sft_params:
        sft_kwargs["packing"] = False

    trainer = SFTTrainer(**sft_kwargs)

    print("Starting fine-tuning...")
    trainer.train()

    adapter_dir = os.path.join(args.output_dir, "adapter")
    os.makedirs(adapter_dir, exist_ok=True)
    model.save_pretrained(adapter_dir)
    tokenizer.save_pretrained(adapter_dir)
    print(f"Saved LoRA adapter: {adapter_dir}")

    if args.save_gguf:
        gguf_dir = os.path.join(args.output_dir, "gguf_q4_k_m")
        os.makedirs(gguf_dir, exist_ok=True)
        try:
            model.save_pretrained_gguf(gguf_dir, tokenizer, quantization_method="q4_k_m")
            print(f"Saved GGUF: {gguf_dir}")
        except Exception as exc:
            print(f"[WARN] GGUF export failed: {exc}")

    print("Fine-tuning complete.")


if __name__ == "__main__":
    main()
