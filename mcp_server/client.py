"""Client agent that chains MCP tools for self-improvement."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

import weave
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _safe_weave_init() -> Any:
    try:
        project = "leonwenhao-dolores-research/rlm-distiller"
        if os.environ.get("WANDB_API_KEY"):
            return weave.init(project)
        return weave.init(project, settings={"disabled": True})
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"Warning: Weave init failed: {exc}")
        return None


weave_client = _safe_weave_init()


@weave.op
async def run_self_improvement_cycle(model_name: str, iteration: int) -> dict:
    """Execute one full self-improvement cycle via MCP tools."""
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "mcp_server.server"],
        env={
            **os.environ,
            "MISTRAL_API_KEY": os.environ.get("MISTRAL_API_KEY", ""),
            "WANDB_API_KEY": os.environ.get("WANDB_API_KEY", ""),
            "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
        },
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print(f"\n{'=' * 60}")
            print(f"SELF-IMPROVEMENT CYCLE - Iteration {iteration}")
            print(f"Model: {model_name}")
            print(f"{'=' * 60}")

            print("\n[1/4] Running evaluation...")
            eval_result = await session.call_tool(
                "run_evaluation",
                arguments={
                    "model_name": model_name,
                    "dataset_path": "data/eval_dataset.json",
                },
            )
            eval_data = _extract_tool_payload(eval_result)
            print(f"  Eval complete. Keys: {list(eval_data.keys()) if isinstance(eval_data, dict) else type(eval_data).__name__}")

            print("\n[2/4] Analyzing failure modes...")
            failure_result = await session.call_tool(
                "analyze_failures",
                arguments={"eval_results": eval_data},
            )
            failure_data = _extract_tool_payload(failure_result)
            failure_modes = failure_data.get("failure_modes", []) if isinstance(failure_data, dict) else []
            print(f"  Found {len(failure_modes)} failure modes")
            for fm in failure_modes:
                print(f"    - {fm['dimension']}: {fm['average_score']} ({fm['severity']})")

            print("\n[3/4] Generating targeted training data...")
            if failure_modes:
                gen_result = await session.call_tool(
                    "generate_training_data",
                    arguments={
                        "failure_modes": failure_modes,
                        "num_examples": 50,
                    },
                )
                training_file_payload = _extract_tool_payload(gen_result)
                training_file = (
                    training_file_payload
                    if isinstance(training_file_payload, str)
                    else str(training_file_payload)
                )
                print(f"  Generated: {training_file}")
            else:
                training_file = ""
                print("  No failure modes - skipping generation")

            print("\n[4/4] Triggering fine-tuning job...")
            if training_file:
                ft_result = await session.call_tool(
                    "trigger_finetuning",
                    arguments={
                        "training_file": training_file,
                        "iteration": iteration + 1,
                    },
                )
                ft_data = _extract_tool_payload(ft_result)
                if not isinstance(ft_data, dict):
                    ft_data = {"status": "unexpected_response", "raw": ft_data}
                print(f"  Job submitted: {ft_data.get('job_id', 'unknown')}")
                print(f"  Status: {ft_data.get('status', 'unknown')}")
            else:
                ft_data = {"status": "skipped", "reason": "no failure modes to address"}
                print("  Skipped - no targeted data to train on")

            return {
                "iteration": iteration,
                "eval_results": eval_data,
                "failure_modes": failure_modes,
                "training_file": training_file,
                "finetuning_job": ft_data,
            }


def _extract_tool_payload(tool_result: Any) -> Any:
    """Extract JSON/text payload from MCP CallToolResult."""
    content = getattr(tool_result, "content", None)
    if not content:
        return {}

    first = content[0]
    if hasattr(first, "text"):
        text = first.text
        try:
            return json.loads(text)
        except Exception:
            return text

    if hasattr(first, "data"):
        return first.data

    return str(first)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run self-improvement cycle")
    parser.add_argument(
        "--model",
        default="mistral-small-latest",
        help="Model to evaluate",
    )
    parser.add_argument(
        "--iteration",
        type=int,
        default=0,
        help="Current iteration number",
    )
    args = parser.parse_args()

    result = asyncio.run(run_self_improvement_cycle(args.model, args.iteration))
    print(f"\n{'=' * 60}")
    print("CYCLE COMPLETE")
    print(f"{'=' * 60}")
    print(json.dumps(result, indent=2, default=str))
