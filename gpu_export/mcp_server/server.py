"""MCP server exposing self-improvement loop tools."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import weave
from mcp.server.fastmcp import FastMCP

from eval.model import OrchestratorModel
from eval.scorers import (
    error_detection_recall,
    retry_intelligence,
    routing_accuracy,
    synthesis_quality,
)


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

mcp = FastMCP("RLM-Distiller")


@mcp.tool()
def run_evaluation(model_name: str, dataset_path: str = "data/eval_dataset.json") -> dict:
    """Run orchestration quality evaluation on a Mistral model."""
    with open(dataset_path, encoding="utf-8") as f:
        rows = json.load(f)

    dataset = weave.Dataset(name="orchestration-eval-v1", rows=rows)
    model = OrchestratorModel(model_name=model_name)

    evaluation = weave.Evaluation(
        name=f"orchestration-quality-{model_name[:20]}",
        dataset=dataset,
        scorers=[
            routing_accuracy,
            error_detection_recall,
            retry_intelligence,
            synthesis_quality,
        ],
    )

    results = asyncio.run(evaluation.evaluate(model))

    return {
        "model": model_name,
        "results": results,
        "status": "completed",
    }


@mcp.tool()
def analyze_failures(eval_results: dict) -> dict:
    """Analyze evaluation output and rank weak orchestration dimensions."""
    results = eval_results.get("results", eval_results)

    dimension_scores: dict[str, list[float]] = {
        "routing_accuracy": [],
        "error_detection_recall": [],
        "retry_intelligence": [],
        "synthesis_quality": [],
    }

    for dimension in dimension_scores:
        _collect_dimension_scores(results, dimension, dimension_scores[dimension])

    failure_modes = []
    for dim, scores in dimension_scores.items():
        if not scores:
            continue

        avg = sum(scores) / len(scores)
        if avg < 0.8:
            failure_modes.append(
                {
                    "dimension": dim,
                    "average_score": round(avg, 3),
                    "severity": (
                        "critical"
                        if avg < 0.4
                        else "moderate"
                        if avg < 0.6
                        else "minor"
                    ),
                    "recommendation": _get_recommendation(dim, avg),
                }
            )

    failure_modes.sort(key=lambda x: x["average_score"])

    return {
        "failure_modes": failure_modes,
        "dimension_averages": {
            dim: round(sum(scores) / len(scores), 3) if scores else None
            for dim, scores in dimension_scores.items()
        },
        "total_dimensions_analyzed": len(dimension_scores),
        "dimensions_below_threshold": len(failure_modes),
    }


def _collect_dimension_scores(payload: Any, dimension: str, sink: list[float]) -> None:
    """Recursively collect numeric values for a dimension from nested results."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == dimension:
                if isinstance(value, (int, float)):
                    sink.append(float(value))
                elif isinstance(value, dict):
                    for candidate in ("mean", "avg", "value", "score"):
                        candidate_val = value.get(candidate)
                        if isinstance(candidate_val, (int, float)):
                            sink.append(float(candidate_val))
                            break
            _collect_dimension_scores(value, dimension, sink)
    elif isinstance(payload, list):
        for item in payload:
            _collect_dimension_scores(item, dimension, sink)


def _get_recommendation(dimension: str, score: float) -> str:
    """Generate a targeted recommendation for each failure dimension."""
    recommendations = {
        "routing_accuracy": (
            "Model is not assigning the right agents to tasks. "
            "Generate more training examples with diverse agent-to-task mappings "
            "and explicit reasoning about why each agent is chosen."
        ),
        "error_detection_recall": (
            "Model is missing errors in sub-agent outputs. "
            "Generate training examples where sub-agents return flawed results "
            "and the orchestrator explicitly evaluates and catches them."
        ),
        "retry_intelligence": (
            "Model is not retrying strategically. "
            "Generate examples with low-confidence sub-agent outputs "
            "where the orchestrator retries with more specific prompts."
        ),
        "synthesis_quality": (
            "Model final synthesis lacks depth. "
            "Generate examples with rich cross-referencing, confidence scores, "
            "and specific line-number citations in the final answer."
        ),
    }
    return recommendations.get(dimension, "Generate more diverse training examples.")


@mcp.tool()
def generate_training_data(failure_modes: list, num_examples: int = 50) -> str:
    """Generate targeted training examples addressing identified failure modes."""
    output_path = "data/targeted_traces_iter.jsonl"
    generated: list[dict[str, Any]] = []

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=anthropic_key)
            generated = _generate_with_claude(client, failure_modes, num_examples)
        except Exception as exc:  # pragma: no cover - network/API dependent
            print(f"Warning: Claude generation failed, falling back to templates: {exc}")
            generated = _generate_with_templates(failure_modes, num_examples)
    else:
        generated = _generate_with_templates(failure_modes, num_examples)

    with open(output_path, "w", encoding="utf-8") as f:
        for trace in generated:
            f.write(json.dumps(trace) + "\n")

    return output_path


def _generate_with_claude(client: Any, failure_modes: list, num_examples: int) -> list[dict[str, Any]]:
    failure_descriptions = "\n".join(
        f"- {fm['dimension']} (score: {fm['average_score']}): {fm['recommendation']}"
        for fm in failure_modes
    )

    scenario_types = [
        "security audit of a Python web application",
        "bug detection in a Node.js API",
        "performance analysis of a data pipeline",
        "dependency audit of a Python ML project",
        "refactoring assessment of a Go microservice",
    ]

    generated = []
    for i in range(num_examples):
        scenario = scenario_types[i % len(scenario_types)]
        prompt = (
            "Generate a synthetic orchestration trace for a root model analyzing a codebase.\n\n"
            f"Scenario: {scenario}\n\n"
            "The trace MUST strongly demonstrate these behaviors:\n"
            f"{failure_descriptions or '- improve all four dimensions'}\n\n"
            "Format the trace as a JSON object with a 'messages' array containing exactly 2 messages:\n"
            "1) a 'user' message with task/file tree/tools\n"
            "2) an 'assistant' message with exploration, llm_query/llm_batch, retries, "
            "cross-referencing, and answer['ready'] = True\n\n"
            "Return only valid JSON."
        )

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            text_block = ""
            if getattr(response, "content", None):
                for block in response.content:
                    if getattr(block, "type", "") == "text":
                        text_block += block.text
            trace = _parse_json_payload(text_block.strip())
            if isinstance(trace, dict) and "messages" in trace:
                generated.append(trace)
        except Exception as exc:  # pragma: no cover - network/API dependent
            print(f"Failed to generate trace {i}: {exc}")

    if not generated:
        return _generate_with_templates(failure_modes, num_examples)

    return generated


def _generate_with_templates(failure_modes: list, num_examples: int) -> list[dict[str, Any]]:
    dimensions = [fm.get("dimension", "general") for fm in failure_modes] or [
        "routing_accuracy",
        "error_detection_recall",
        "retry_intelligence",
        "synthesis_quality",
    ]

    scenarios = [
        "security audit",
        "bug detection",
        "performance analysis",
        "dependency audit",
        "refactoring assessment",
    ]

    traces = []
    for i in range(num_examples):
        scenario = scenarios[i % len(scenarios)]
        focus = dimensions[i % len(dimensions)]
        traces.append(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"Task: {scenario} for service-{i}. File tree: src/, tests/, config/. "
                            "Available tools: llm_query, llm_batch, explore, read_metadata."
                        ),
                    },
                    {
                        "role": "assistant",
                        "content": (
                            "Phase 1 exploration with explore(). Phase 2 delegation via llm_batch(). "
                            f"Focus on {focus}. Retry low-confidence outputs with llm_query(). "
                            "Cross-reference findings, assign confidence 0.82, cite line_42, "
                            "and set answer['ready'] = True."
                        ),
                    },
                ]
            }
        )

    return traces


def _parse_json_payload(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned)


@mcp.tool()
def trigger_finetuning(
    training_file: str,
    iteration: int,
    base_training_file: str = "data/orchestration_traces_train.jsonl",
) -> dict:
    """Submit a fine-tuning job by running QLoRA training locally on GPU.

    Merges base + new training data, then runs finetune/run_iteration.sh
    which handles training and model serving.
    """
    import subprocess

    # Merge base training data with new targeted traces
    merged_path = f"data/merged_training_iter_{iteration}.jsonl"
    with open(merged_path, "w", encoding="utf-8") as out:
        if os.path.exists(base_training_file):
            with open(base_training_file, encoding="utf-8") as f:
                for line in f:
                    out.write(line)

        if training_file and os.path.exists(training_file):
            with open(training_file, encoding="utf-8") as f:
                for line in f:
                    out.write(line)

    with open(merged_path, encoding="utf-8") as f:
        training_examples = sum(1 for _ in f)

    print(f"Merged training data: {training_examples} examples -> {merged_path}")

    # Run the fine-tuning + serving iteration
    try:
        result = subprocess.run(
            ["bash", "finetune/run_iteration.sh", str(iteration), merged_path],
            capture_output=True,
            text=True,
            timeout=7200,  # 2 hour timeout
        )
        return {
            "status": "SUCCEEDED" if result.returncode == 0 else "FAILED",
            "iteration": iteration,
            "training_examples": training_examples,
            "checkpoint_dir": f"checkpoints/iteration_{iteration}",
            "stdout": result.stdout[-2000:],  # last 2000 chars
            "stderr": result.stderr[-2000:] if result.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "TIMEOUT",
            "iteration": iteration,
            "training_examples": training_examples,
            "error": "Fine-tuning timed out after 2 hours",
        }
    except Exception as exc:
        return {
            "status": "FAILED",
            "iteration": iteration,
            "training_examples": training_examples,
            "error": str(exc),
        }


# --- Mistral La Plateforme API fallback (commented out) ---
# If Mistral's fine-tuning API gets fixed, uncomment and use this instead:
#
# @mcp.tool()
# def trigger_finetuning_mistral_api(
#     training_file: str,
#     iteration: int,
#     base_training_file: str = "data/orchestration_traces_train.jsonl",
# ) -> dict:
#     """Upload merged training data and submit a Mistral fine-tuning job."""
#     from mistralai import Mistral
#
#     client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
#
#     merged_path = f"data/merged_training_iter_{iteration}.jsonl"
#     with open(merged_path, "w", encoding="utf-8") as out:
#         if os.path.exists(base_training_file):
#             with open(base_training_file, encoding="utf-8") as f:
#                 for line in f:
#                     out.write(line)
#         if training_file and os.path.exists(training_file):
#             with open(training_file, encoding="utf-8") as f:
#                 for line in f:
#                     out.write(line)
#
#     with open(merged_path, "rb") as merged_fp:
#         training_data = client.files.upload(
#             file={"file_name": f"training_iter_{iteration}.jsonl", "content": merged_fp}
#         )
#
#     job_kwargs = {
#         "model": "mistral-small-latest",
#         "training_files": [{"file_id": training_data.id, "weight": 1}],
#         "hyperparameters": {"training_steps": 100, "learning_rate": 0.0001},
#         "auto_start": True,
#     }
#     wandb_key = os.environ.get("WANDB_API_KEY")
#     if wandb_key:
#         job_kwargs["integrations"] = [{"project": "rlm-distiller", "api_key": wandb_key}]
#
#     job = client.fine_tuning.jobs.create(**job_kwargs)
#     with open(merged_path, encoding="utf-8") as f:
#         training_examples = sum(1 for _ in f)
#     return {
#         "job_id": job.id, "status": job.status, "iteration": iteration,
#         "training_examples": training_examples,
#         "model": getattr(job, "fine_tuned_model", "pending"),
#     }


if __name__ == "__main__":
    print("Starting RLM-Distiller MCP Server...")
    print("Tools: run_evaluation, analyze_failures, generate_training_data, trigger_finetuning")
    mcp.run(transport="stdio")
