#!/usr/bin/env python3
"""
QLoRA fine-tuning script for RLM Distiller.
Trains Mistral Small 3.1 24B Instruct on orchestration traces.

Usage:
    python finetune/train_qlora.py \
        --training_data data/orchestration_traces_train.jsonl \
        --eval_data data/orchestration_traces_eval.jsonl \
        --output_dir checkpoints/iteration_1 \
        --num_epochs 3 \
        --learning_rate 2e-4 \
        --batch_size 2 \
        --gradient_accumulation_steps 4 \
        --max_seq_length 4096 \
        --wandb_project rlm-distiller \
        --iteration 1
"""

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer

MODEL_ID = "mistralai/Mistral-Small-24B-Instruct-2501"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QLoRA fine-tuning for RLM Distiller")
    parser.add_argument("--training_data", type=str, required=True, help="Path to training JSONL")
    parser.add_argument("--eval_data", type=str, default=None, help="Path to eval JSONL")
    parser.add_argument("--output_dir", type=str, required=True, help="Checkpoint output directory")
    parser.add_argument("--num_epochs", type=int, default=3)
    parser.add_argument("--learning_rate", type=float, default=2e-4)
    parser.add_argument("--batch_size", type=int, default=2)
    parser.add_argument("--gradient_accumulation_steps", type=int, default=4)
    parser.add_argument("--max_seq_length", type=int, default=4096)
    parser.add_argument("--wandb_project", type=str, default="rlm-distiller")
    parser.add_argument("--iteration", type=int, default=1)
    parser.add_argument("--base_model", type=str, default=MODEL_ID)
    parser.add_argument("--lora_r", type=int, default=16)
    parser.add_argument("--lora_alpha", type=int, default=32)
    parser.add_argument("--warmup_steps", type=int, default=10)
    parser.add_argument("--save_steps", type=int, default=50)
    parser.add_argument("--eval_steps", type=int, default=50)
    parser.add_argument("--logging_steps", type=int, default=10)
    return parser.parse_args()


def load_jsonl(path: str) -> list[dict]:
    """Load a JSONL file and return list of parsed objects."""
    data = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                data.append(obj)
            except json.JSONDecodeError as e:
                print(f"WARNING: Skipping malformed line {i + 1} in {path}: {e}")
    return data


def validate_data(data: list[dict], path: str, num_check: int = 5) -> None:
    """Validate training data format before starting."""
    if not data:
        raise ValueError(f"No valid examples found in {path}")

    for i, example in enumerate(data[:num_check]):
        if "messages" not in example:
            raise ValueError(
                f"Example {i} in {path} missing 'messages' key. "
                f"Expected format: {{\"messages\": [{{\"role\": ..., \"content\": ...}}]}}"
            )
        messages = example["messages"]
        if not isinstance(messages, list) or len(messages) < 2:
            raise ValueError(
                f"Example {i} in {path}: 'messages' must be a list with at least 2 messages"
            )
        for j, msg in enumerate(messages):
            if "role" not in msg or "content" not in msg:
                raise ValueError(
                    f"Example {i}, message {j} in {path}: missing 'role' or 'content'"
                )

    print(f"Validated {min(num_check, len(data))}/{len(data)} examples from {path}")


def create_dataset(data: list[dict], tokenizer) -> Dataset:
    """Convert JSONL data to a HuggingFace Dataset with formatted text."""
    formatted_texts = []
    for example in data:
        # Mistral Small 3.1 tokenizer lacks a chat_template — set one explicitly
        if not getattr(tokenizer, 'chat_template', None):
            tokenizer.chat_template = "{% for message in messages %}{% if message['role'] == 'user' %}[INST] {{ message['content'] }} [/INST]{% elif message['role'] == 'assistant' %}{{ message['content'] }}</s>{% endif %}{% endfor %}"
        text = tokenizer.apply_chat_template(
            example["messages"], tokenize=False, add_generation_prompt=False
        )
        formatted_texts.append(text)
    return Dataset.from_dict({"text": formatted_texts})


def main():
    args = parse_args()
    start_time = time.time()

    print("=" * 60)
    print(f"RLM Distiller - QLoRA Fine-tuning (Iteration {args.iteration})")
    print("=" * 60)
    print(f"Base model: {args.base_model}")
    print(f"Training data: {args.training_data}")
    print(f"Eval data: {args.eval_data}")
    print(f"Output dir: {args.output_dir}")
    print(f"Epochs: {args.num_epochs}, LR: {args.learning_rate}")
    print(f"Batch size: {args.batch_size}, Grad accum: {args.gradient_accumulation_steps}")
    print(f"Effective batch size: {args.batch_size * args.gradient_accumulation_steps}")
    print(f"Max seq length: {args.max_seq_length}")
    print("=" * 60)

    # --- Load and validate data ---
    print("\nLoading training data...")
    train_data = load_jsonl(args.training_data)
    validate_data(train_data, args.training_data)
    print(f"Loaded {len(train_data)} training examples")

    eval_data = None
    if args.eval_data and os.path.exists(args.eval_data):
        print("Loading eval data...")
        eval_data = load_jsonl(args.eval_data)
        validate_data(eval_data, args.eval_data)
        print(f"Loaded {len(eval_data)} eval examples")

    # --- W&B setup ---
    wandb_enabled = bool(os.environ.get("WANDB_API_KEY"))
    if wandb_enabled:
        import wandb

        wandb.init(
            project=args.wandb_project,
            name=f"qlora-iter{args.iteration}",
            config=vars(args),
        )
        report_to = "wandb"
        print("W&B logging enabled")
    else:
        report_to = "none"
        print("W&B not configured, logging to console only")

    # --- Quantization config ---
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    # --- Load tokenizer ---
    print("\nLoading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        tokenizer.pad_token_id = tokenizer.eos_token_id

    # --- Create datasets ---
    print("Formatting datasets with chat template...")
    train_dataset = create_dataset(train_data, tokenizer)
    eval_dataset = create_dataset(eval_data, tokenizer) if eval_data else None
    print(f"Train dataset: {len(train_dataset)} examples")
    if eval_dataset:
        print(f"Eval dataset: {len(eval_dataset)} examples")

    # --- Load model ---
    print(f"\nLoading model {args.base_model} with 4-bit quantization...")
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
        attn_implementation="sdpa",
    )
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    print(f"Model loaded. Memory allocated: {torch.cuda.memory_allocated() / 1e9:.1f} GB")

    # --- LoRA config ---
    lora_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
    )

    model = get_peft_model(model, lora_config)
    trainable, total = model.get_nb_trainable_parameters()
    print(f"Trainable parameters: {trainable:,} / {total:,} ({100 * trainable / total:.2f}%)")

    # --- Training arguments ---
    os.makedirs(args.output_dir, exist_ok=True)

    training_args = SFTConfig(
        output_dir=args.output_dir,
        num_train_epochs=args.num_epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        lr_scheduler_type="cosine",
        warmup_steps=args.warmup_steps,
        bf16=True,
        logging_steps=args.logging_steps,
        save_steps=args.save_steps,
        save_total_limit=3,
        eval_strategy="steps" if eval_dataset else "no",
        eval_steps=args.eval_steps if eval_dataset else None,
        report_to=report_to,
        run_name=f"qlora-iter{args.iteration}",
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        max_length=args.max_seq_length,
        dataset_text_field="text",
        packing=False,
        optim="paged_adamw_8bit",
        seed=42,
    )

    # --- Trainer ---
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        processing_class=tokenizer,
    )

    # --- Handle Ctrl+C gracefully ---
    def save_on_interrupt(sig, frame):
        print("\n\nInterrupt received! Saving checkpoint before exit...")
        emergency_dir = os.path.join(args.output_dir, "emergency_checkpoint")
        trainer.save_model(emergency_dir)
        tokenizer.save_pretrained(emergency_dir)
        print(f"Emergency checkpoint saved to {emergency_dir}")
        sys.exit(1)

    signal.signal(signal.SIGINT, save_on_interrupt)
    signal.signal(signal.SIGTERM, save_on_interrupt)

    # --- Train ---
    print("\n" + "=" * 60)
    print("Starting training...")
    print("=" * 60)

    try:
        train_result = trainer.train()
    except torch.cuda.OutOfMemoryError:
        print("\n" + "=" * 60)
        print("ERROR: CUDA Out of Memory!")
        print("Try reducing:")
        print(f"  --batch_size (current: {args.batch_size}) -> try 1")
        print(f"  --max_seq_length (current: {args.max_seq_length}) -> try 2048")
        print(f"  --gradient_accumulation_steps (current: {args.gradient_accumulation_steps}) -> increase to compensate for smaller batch")
        print("=" * 60)
        sys.exit(1)

    # --- Save final adapter ---
    print("\nSaving final LoRA adapter...")
    trainer.save_model(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)

    # Save training metadata
    metadata = {
        "iteration": args.iteration,
        "base_model": args.base_model,
        "training_data": args.training_data,
        "num_epochs": args.num_epochs,
        "learning_rate": args.learning_rate,
        "lora_r": args.lora_r,
        "lora_alpha": args.lora_alpha,
        "train_examples": len(train_dataset),
        "eval_examples": len(eval_dataset) if eval_dataset else 0,
        "max_seq_length": args.max_seq_length,
        "train_runtime_seconds": train_result.metrics.get("train_runtime", 0),
        "train_loss": train_result.metrics.get("train_loss", None),
    }
    with open(os.path.join(args.output_dir, "training_metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    # --- Log final metrics ---
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print("Training complete!")
    print(f"  Output dir: {args.output_dir}")
    print(f"  Train loss: {train_result.metrics.get('train_loss', 'N/A')}")
    print(f"  Train runtime: {train_result.metrics.get('train_runtime', 0):.0f}s")
    print(f"  Total wall time: {elapsed:.0f}s ({elapsed / 60:.1f} min)")
    print("=" * 60)

    if wandb_enabled:
        wandb.log({"final_train_loss": train_result.metrics.get("train_loss", 0)})
        wandb.finish()


if __name__ == "__main__":
    main()
