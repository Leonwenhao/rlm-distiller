#!/usr/bin/env python3
"""
Serve fine-tuned Mistral model with vLLM.
Loads base model + LoRA adapter and exposes OpenAI-compatible API.

Usage:
    python finetune/serve_model.py \
        --base_model mistralai/Mistral-Small-24B-Instruct-2501 \
        --lora_path checkpoints/iteration_1 \
        --port 8000

The endpoint will be available at:
    http://localhost:8000/v1/chat/completions

Compatible with OpenAI client:
    from openai import OpenAI
    client = OpenAI(base_url="http://localhost:8000/v1", api_key="dummy")
    response = client.chat.completions.create(
        model="rlm-distiller",
        messages=[{"role": "user", "content": "..."}]
    )
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time


MODEL_ID = "mistralai/Mistral-Small-24B-Instruct-2501"
SERVED_MODEL_NAME = "rlm-distiller"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve fine-tuned model with vLLM")
    parser.add_argument("--base_model", type=str, default=MODEL_ID)
    parser.add_argument("--lora_path", type=str, required=True, help="Path to LoRA adapter checkpoint")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--max_model_len", type=int, default=4096)
    parser.add_argument("--gpu_memory_utilization", type=float, default=0.90)
    parser.add_argument("--merge_and_serve", action="store_true",
                        help="Merge LoRA into base model before serving (fallback mode)")
    return parser.parse_args()


def check_lora_path(lora_path: str) -> None:
    """Validate that the LoRA adapter path exists and has required files."""
    if not os.path.isdir(lora_path):
        print(f"ERROR: LoRA path does not exist: {lora_path}")
        sys.exit(1)

    adapter_config = os.path.join(lora_path, "adapter_config.json")
    if not os.path.exists(adapter_config):
        print(f"ERROR: No adapter_config.json found in {lora_path}")
        print("This doesn't look like a valid LoRA adapter directory.")
        sys.exit(1)

    print(f"LoRA adapter found at {lora_path}")
    with open(adapter_config) as f:
        config = json.load(f)
    print(f"  Base model: {config.get('base_model_name_or_path', 'unknown')}")
    print(f"  LoRA rank: {config.get('r', 'unknown')}")


def serve_with_lora(args: argparse.Namespace) -> None:
    """Serve base model + LoRA adapter using vLLM's native LoRA support."""
    print("\n" + "=" * 60)
    print("Starting vLLM server with LoRA adapter...")
    print(f"  Base model: {args.base_model}")
    print(f"  LoRA path: {args.lora_path}")
    print(f"  Port: {args.port}")
    print("=" * 60)

    cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", args.base_model,
        "--served-model-name", SERVED_MODEL_NAME,
        "--port", str(args.port),
        "--host", args.host,
        "--max-model-len", str(args.max_model_len),
        "--gpu-memory-utilization", str(args.gpu_memory_utilization),
        "--enable-lora",
        "--lora-modules", json.dumps({"name": SERVED_MODEL_NAME, "path": os.path.abspath(args.lora_path)}),
        "--max-lora-rank", "64",
        "--trust-remote-code",
    ]

    print(f"\nRunning: {' '.join(cmd)}")
    try:
        os.execvp(sys.executable, cmd)
    except Exception as e:
        print(f"\nERROR: Failed to start vLLM with LoRA: {e}")
        print("Falling back to merge-and-serve approach...")
        merge_and_serve(args)


def merge_and_serve(args: argparse.Namespace) -> None:
    """Fallback: merge LoRA weights into base model, then serve the merged model."""
    print("\n" + "=" * 60)
    print("Merge-and-serve fallback mode")
    print("  Merging LoRA weights into base model...")
    print("=" * 60)

    merged_path = os.path.join(os.path.dirname(args.lora_path), "merged_model")

    if os.path.exists(merged_path) and os.path.exists(os.path.join(merged_path, "config.json")):
        print(f"  Using existing merged model at {merged_path}")
    else:
        print("  Loading base model + LoRA adapter for merging...")
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)

        model = AutoModelForCausalLM.from_pretrained(
            args.base_model,
            torch_dtype=torch.bfloat16,
            device_map="auto",
            trust_remote_code=True,
        )

        print("  Applying LoRA adapter...")
        model = PeftModel.from_pretrained(model, args.lora_path)

        print("  Merging and unloading...")
        model = model.merge_and_unload()

        print(f"  Saving merged model to {merged_path}...")
        os.makedirs(merged_path, exist_ok=True)
        model.save_pretrained(merged_path)
        tokenizer.save_pretrained(merged_path)
        print("  Merge complete!")

        # Free memory before starting vLLM
        del model
        del tokenizer
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # Serve the merged model
    print(f"\nStarting vLLM server with merged model...")
    cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", merged_path,
        "--served-model-name", SERVED_MODEL_NAME,
        "--port", str(args.port),
        "--host", args.host,
        "--max-model-len", str(args.max_model_len),
        "--gpu-memory-utilization", str(args.gpu_memory_utilization),
        "--trust-remote-code",
    ]

    print(f"Running: {' '.join(cmd)}")
    os.execvp(sys.executable, cmd)


def main():
    args = parse_args()
    check_lora_path(args.lora_path)

    if args.merge_and_serve:
        merge_and_serve(args)
    else:
        serve_with_lora(args)


if __name__ == "__main__":
    main()
