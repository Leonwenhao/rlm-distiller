#!/usr/bin/env python3
"""Autonomous self-improvement loop for RLM Distiller.

Runs N iterations of: evaluate -> analyze failures -> generate training data ->
fine-tune -> wait for served model -> repeat.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import math
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

def setup_logging(output_dir: str) -> logging.Logger:
    """Set up logging to both file and stdout."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(output_dir) / "loop.log"

    logger = logging.getLogger("rlm_distiller.loop")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger


def load_state(state_path: str) -> dict:
    """Load loop state from JSON file. Returns empty state if file doesn't exist."""
    path = Path(state_path)
    if not path.exists():
        return {}

    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state_path: str, state: dict):
    """Save loop state to JSON file."""
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")

    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")

    tmp_path.replace(path)


def run_evaluation(
    model_endpoint: str,
    eval_dataset_path: str,
    iteration: int,
    model_name: str = "mistral-small-latest",
    weave_project: str = "leonwenhao-dolores-research/rlm-distiller",
    logger: logging.Logger | None = None,
) -> dict:
    """Run evaluation and return aggregate + per-example scores."""
    from eval.model import OrchestratorModel
    from eval.scorers import (
        error_detection_recall,
        retry_intelligence,
        routing_accuracy,
        synthesis_quality,
    )

    try:
        import weave

        if os.environ.get("WANDB_API_KEY"):
            weave.init(weave_project)
        else:
            weave.init(weave_project, settings={"disabled": True})
    except Exception as exc:
        if logger:
            logger.warning("Weave init failed. Continuing without trace publishing: %s", exc)

    with open(eval_dataset_path, encoding="utf-8") as f:
        rows = json.load(f)

    model = OrchestratorModel(model_name=model_name, model_endpoint=model_endpoint)

    per_example_scores: list[dict[str, Any]] = []
    failed_predictions = 0

    for idx, row in enumerate(rows):
        try:
            model_output = model.predict(
                task=row["task"],
                file_tree=row["file_tree"],
                available_agents=row["available_agents"],
            )
        except Exception as exc:
            failed_predictions += 1
            model_output = {
                "routing_decisions": {},
                "detected_errors": [],
                "retry_decisions": [],
                "synthesis_markers": [],
                "raw_response": f"PREDICTION_ERROR: {exc}",
            }

        ra = routing_accuracy(row.get("expected_routing", {}), model_output)["routing_accuracy"]
        er = error_detection_recall(
            row.get("known_errors", []), model_output
        )["error_detection_recall"]
        ri = retry_intelligence(
            row.get("expected_retries", []), model_output
        )["retry_intelligence"]
        sq = synthesis_quality(
            row.get("expected_synthesis_markers", []), model_output
        )["synthesis_quality"]
        overall = round((ra + er + ri + sq) / 4, 3)

        per_example_scores.append(
            {
                "example_id": idx,
                "task": row.get("task", ""),
                "routing_accuracy": ra,
                "error_detection_recall": er,
                "retry_intelligence": ri,
                "synthesis_quality": sq,
                "overall_score": overall,
            }
        )

    if rows and failed_predictions >= math.ceil(len(rows) * 0.5):
        raise RuntimeError(
            f"Evaluation failed on {failed_predictions}/{len(rows)} examples; model endpoint likely unavailable"
        )

    def _mean(key: str) -> float:
        if not per_example_scores:
            return 0.0
        return round(sum(float(r[key]) for r in per_example_scores) / len(per_example_scores), 3)

    routing_mean = _mean("routing_accuracy")
    error_mean = _mean("error_detection_recall")
    retry_mean = _mean("retry_intelligence")
    synthesis_mean = _mean("synthesis_quality")
    overall_score = round((routing_mean + error_mean + retry_mean + synthesis_mean) / 4, 3)

    return {
        "iteration": iteration,
        "timestamp": datetime.now().isoformat(),
        "model_endpoint": model_endpoint,
        "model_name": model_name,
        "routing_accuracy": routing_mean,
        "error_detection_recall": error_mean,
        "retry_intelligence": retry_mean,
        "synthesis_quality": synthesis_mean,
        "overall_score": overall_score,
        "per_example_scores": per_example_scores,
        "failed_predictions": failed_predictions,
        "num_examples": len(rows),
    }


def analyze_failures(eval_results: dict) -> list:
    """Analyze bottom 30% examples and identify top failure modes."""
    per_example = list(eval_results.get("per_example_scores", []))
    if not per_example:
        return []

    sorted_rows = sorted(per_example, key=lambda r: r.get("overall_score", 0.0))
    bottom_n = max(1, math.ceil(len(sorted_rows) * 0.3))
    bottom_rows = sorted_rows[:bottom_n]

    failure_definitions = {
        "routing_failures": {
            "field": "routing_accuracy",
            "description": "Model assigned sub-agents poorly for the task decomposition.",
        },
        "missed_errors": {
            "field": "error_detection_recall",
            "description": "Model missed known defects surfaced in expected outputs.",
        },
        "bad_retry_decisions": {
            "field": "retry_intelligence",
            "description": "Model made poor retry decisions (unnecessary retries or missed retries).",
        },
        "shallow_synthesis": {
            "field": "synthesis_quality",
            "description": "Final synthesis lacked depth/corroboration/precision markers.",
        },
    }

    failure_modes: list[dict[str, Any]] = []
    threshold = 0.8
    for failure_type, spec in failure_definitions.items():
        field = spec["field"]
        failing = [r for r in bottom_rows if float(r.get(field, 0.0)) < threshold]
        if not failing:
            continue

        avg = sum(float(r.get(field, 0.0)) for r in failing) / len(failing)
        severity = round(1.0 - avg, 3)
        failure_modes.append(
            {
                "failure_type": failure_type,
                "description": spec["description"],
                "example_ids": [int(r["example_id"]) for r in failing],
                "severity": severity,
            }
        )

    failure_modes.sort(key=lambda f: f["severity"], reverse=True)
    return failure_modes


def _parse_json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    try:
        obj = json.loads(cleaned)
    except Exception:
        return None
    if isinstance(obj, dict):
        return obj
    return None


def _fallback_generate_examples(
    failure_modes: list,
    num_examples: int,
    existing_data_path: str | None,
) -> list[dict[str, Any]]:
    descriptions = [f"{f['failure_type']}: {f['description']}" for f in failure_modes]
    focus_text = " | ".join(descriptions) if descriptions else "improve orchestration quality"

    existing_examples: list[dict[str, Any]] = []
    if existing_data_path and Path(existing_data_path).exists():
        with open(existing_data_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    existing_examples.append(obj)

    generated: list[dict[str, Any]] = []
    if existing_examples:
        for i in range(num_examples):
            base = copy.deepcopy(existing_examples[i % len(existing_examples)])
            messages = base.get("messages")
            if isinstance(messages, list) and len(messages) >= 2:
                try:
                    messages[0]["content"] = str(messages[0].get("content", "")) + (
                        f"\n\n[Targeted focus {i + 1}] {focus_text}."
                    )
                    messages[1]["content"] = str(messages[1].get("content", "")) + (
                        "\n\nEnsure explicit agent routing rationale, retry criteria, cross-references, "
                        "confidence score, line citations, and answer['ready'] = True."
                    )
                except Exception:
                    pass
            generated.append(base)
        return generated

    scenario_types = [
        "security audit",
        "bug detection",
        "performance analysis",
        "dependency analysis",
        "refactoring assessment",
    ]
    for i in range(num_examples):
        scenario = scenario_types[i % len(scenario_types)]
        generated.append(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"Task: {scenario} for service_{i}. Available tools: llm_query, llm_batch, explore, "
                            f"read_metadata. Focus: {focus_text}."
                        ),
                    },
                    {
                        "role": "assistant",
                        "content": (
                            "Phase 1 explore. Phase 2 delegate via llm_batch and llm_query. "
                            "Evaluate outputs, retry low-confidence results, cross-reference findings, cite line_42, "
                            "assign confidence 0.84, and set answer['ready'] = True."
                        ),
                    },
                ]
            }
        )
    return generated


def generate_targeted_examples(
    failure_modes: list,
    num_examples: int = 40,
    existing_data_path: str | None = None,
    output_dir: str = "loop_results",
    logger: logging.Logger | None = None,
) -> str:
    """Generate targeted training examples with Anthropic; fallback to local variations."""
    num_examples = max(1, min(num_examples, 50))

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"targeted_examples_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

    generated: list[dict[str, Any]] = []
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    if anthropic_key:
        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=anthropic_key)
            failure_text = "\n".join(
                f"- {mode['failure_type']} (severity={mode['severity']}): {mode['description']}"
                for mode in failure_modes[:3]
            ) or "- improve across routing, error detection, retrying, and synthesis"

            scenario_types = [
                "security audit",
                "bug detection",
                "performance analysis",
                "dependency analysis",
                "refactoring assessment",
            ]

            for i in range(num_examples):
                scenario = scenario_types[i % len(scenario_types)]
                prompt = (
                    "Generate one orchestration training example as valid JSON.\n"
                    "Required schema: {\"messages\": [user_message, assistant_message]} with exactly 2 messages.\n"
                    "The assistant trace must show: exploration, decomposition, routing decisions, "
                    "evaluation of sub-agent outputs, retry logic, cross-referencing, and final synthesis "
                    "with answer['ready'] = True.\n"
                    f"Scenario: {scenario}.\n"
                    f"Model failure modes to correct:\n{failure_text}\n"
                    "Return JSON only (no markdown)."
                )

                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=3000,
                    messages=[{"role": "user", "content": prompt}],
                )

                text = ""
                for block in getattr(response, "content", []):
                    if getattr(block, "type", "") == "text":
                        text += block.text

                parsed = _parse_json_object(text)
                if parsed and isinstance(parsed.get("messages"), list) and len(parsed["messages"]) == 2:
                    generated.append(parsed)
        except Exception as exc:
            if logger:
                logger.warning("Anthropic generation failed; using fallback generator: %s", exc)

    if len(generated) < num_examples:
        fallback_needed = num_examples - len(generated)
        generated.extend(
            _fallback_generate_examples(
                failure_modes=failure_modes,
                num_examples=fallback_needed,
                existing_data_path=existing_data_path,
            )
        )

    with output_path.open("w", encoding="utf-8") as f:
        for item in generated[:num_examples]:
            f.write(json.dumps(item, ensure_ascii=True) + "\n")

    return str(output_path)


def merge_training_data(base_path: str, new_path: str, output_path: str) -> str:
    """Merge base training data with new targeted examples and dedupe lines."""
    seen: set[str] = set()
    merged: list[str] = []

    for path in (base_path, new_path):
        file_path = Path(path)
        if not file_path.exists():
            continue

        with file_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                key = line
                try:
                    obj = json.loads(line)
                    key = json.dumps(obj, sort_keys=True, separators=(",", ":"))
                except Exception:
                    pass

                if key in seen:
                    continue
                seen.add(key)
                merged.append(key)

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for line in merged:
            f.write(line + "\n")

    return str(out_path)


def run_finetuning(
    iteration: int,
    training_data_path: str,
    logger: logging.Logger | None = None,
) -> bool:
    """Run fine-tuning by calling finetune/run_iteration.sh."""
    command = ["bash", "finetune/run_iteration.sh", str(iteration), training_data_path]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=7200,
            check=False,
        )
    except subprocess.TimeoutExpired:
        if logger:
            logger.error("Fine-tuning timed out after 7200s for iteration %s", iteration)
        return False
    except Exception as exc:
        if logger:
            logger.error("Fine-tuning invocation failed for iteration %s: %s", iteration, exc)
        return False

    if result.returncode != 0:
        if logger:
            logger.error("Fine-tuning failed with return code %s", result.returncode)
            if result.stdout:
                logger.error("Fine-tuning stdout (tail): %s", result.stdout[-1000:])
            if result.stderr:
                logger.error("Fine-tuning stderr (tail): %s", result.stderr[-1000:])
        return False

    if logger:
        logger.info("Fine-tuning completed for iteration %s", iteration)
    return True


def wait_for_model_server(endpoint: str, timeout: int = 300) -> bool:
    """Wait for model server readiness via /models or /health."""
    import httpx

    base = endpoint.rstrip("/")
    urls = [f"{base}/models", f"{base}/health"]
    start = time.time()

    while time.time() - start < timeout:
        for url in urls:
            try:
                response = httpx.get(url, timeout=5)
                if response.status_code == 200:
                    return True
            except Exception:
                pass
        time.sleep(10)
    return False


def _retry(
    func: Callable[[], Any],
    logger: logging.Logger,
    step_name: str,
    max_attempts: int = 3,
    initial_delay: float = 2.0,
) -> Any:
    """Run a step with exponential backoff retries."""
    attempt = 1
    while True:
        try:
            return func()
        except Exception as exc:
            if attempt >= max_attempts:
                raise
            sleep_s = initial_delay * (2 ** (attempt - 1))
            logger.warning(
                "Step '%s' failed (attempt %s/%s): %s. Retrying in %.1fs.",
                step_name,
                attempt,
                max_attempts,
                exc,
                sleep_s,
            )
            time.sleep(sleep_s)
            attempt += 1


def _format_score(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.3f}"
    return "N/A"


def _find_iteration_state(state: dict, iteration: int) -> dict[str, Any] | None:
    for item in state.get("iterations", []):
        if int(item.get("iteration", -1)) == iteration:
            return item
    return None


def _get_or_create_iteration_state(state: dict, iteration: int) -> dict[str, Any]:
    existing = _find_iteration_state(state, iteration)
    if existing is not None:
        return existing

    new_state = {
        "iteration": iteration,
        "started_at": datetime.now().isoformat(),
        "status": "IN_PROGRESS",
        "completed_steps": [],
    }
    state.setdefault("iterations", []).append(new_state)
    state["iterations"] = sorted(state["iterations"], key=lambda x: int(x.get("iteration", 0)))
    return new_state


def _mark_step_completed(iteration_state: dict, step_name: str) -> None:
    completed = iteration_state.setdefault("completed_steps", [])
    if step_name not in completed:
        completed.append(step_name)


def _detect_start_iteration(state: dict, resume: bool) -> int:
    if not resume:
        return 0

    done_statuses = {"COMPLETED", "FINETUNING_FAILED", "SERVING_FAILED", "FINAL_EVAL_COMPLETE"}
    sorted_states = sorted(state.get("iterations", []), key=lambda x: int(x.get("iteration", 0)))

    for it_state in sorted_states:
        if it_state.get("status") not in done_statuses:
            return int(it_state.get("iteration", 0))

    return int(state.get("last_completed_iteration", -1)) + 1


def _checkpoint(state_path: str, state: dict, iteration_state: dict | None = None) -> None:
    if iteration_state is not None:
        iteration_state["updated_at"] = datetime.now().isoformat()
    save_state(state_path, state)


def main():
    parser = argparse.ArgumentParser(description="RLM Distiller self-improvement loop")
    parser.add_argument("--model_endpoint", default="http://localhost:8000/v1")
    parser.add_argument("--model_name", default=os.environ.get("MODEL_NAME", "mistral-small-latest"))
    parser.add_argument("--base_training_data", required=True)
    parser.add_argument("--eval_dataset", default="data/eval_dataset.json")
    parser.add_argument("--max_iterations", type=int, default=6)
    parser.add_argument("--output_dir", default="loop_results")
    parser.add_argument("--wandb_project", default="rlm-distiller")
    parser.add_argument("--resume", action="store_true", help="Resume from saved state")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    logger = setup_logging(args.output_dir)
    state_path = os.path.join(args.output_dir, "loop_state.json")

    if args.resume:
        state = load_state(state_path)
        if not state:
            state = {
                "iterations": [],
                "started_at": datetime.now().isoformat(),
                "last_completed_iteration": -1,
            }
        start_iteration = _detect_start_iteration(state, resume=True)
        logger.info("Resuming from iteration %s", start_iteration)
    else:
        state = {
            "iterations": [],
            "started_at": datetime.now().isoformat(),
            "last_completed_iteration": -1,
        }
        start_iteration = 0

    wandb_run = None
    try:
        if os.environ.get("WANDB_API_KEY"):
            import wandb

            wandb_run = wandb.init(
                project=args.wandb_project,
                name=f"self-improvement-loop-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
                config={
                    "model_endpoint": args.model_endpoint,
                    "model_name": args.model_name,
                    "base_training_data": args.base_training_data,
                    "eval_dataset": args.eval_dataset,
                    "max_iterations": args.max_iterations,
                },
                reinit=True,
            )
    except Exception as exc:
        logger.warning("W&B run init failed. Continuing without wandb.log: %s", exc)

    for iteration in range(start_iteration, args.max_iterations + 1):
        logger.info("%s", "=" * 60)
        logger.info("ITERATION %s", iteration)
        logger.info("%s", "=" * 60)

        iteration_state = _get_or_create_iteration_state(state, iteration)
        iteration_state.setdefault("started_at", datetime.now().isoformat())
        iteration_state["status"] = "IN_PROGRESS"
        _checkpoint(state_path, state, iteration_state)

        try:
            if "evaluation" not in iteration_state.get("completed_steps", []):
                logger.info("Step 1: Running evaluation...")
                eval_results = _retry(
                    lambda: run_evaluation(
                        model_endpoint=args.model_endpoint,
                        eval_dataset_path=args.eval_dataset,
                        iteration=iteration,
                        model_name=args.model_name,
                        weave_project=f"leonwenhao-dolores-research/{args.wandb_project}",
                        logger=logger,
                    ),
                    logger=logger,
                    step_name="evaluation",
                )
                iteration_state["eval_results"] = eval_results
                iteration_state["eval_scores"] = {
                    "routing_accuracy": eval_results["routing_accuracy"],
                    "error_detection_recall": eval_results["error_detection_recall"],
                    "retry_intelligence": eval_results["retry_intelligence"],
                    "synthesis_quality": eval_results["synthesis_quality"],
                    "overall_score": eval_results["overall_score"],
                }

                eval_file = Path(args.output_dir) / f"eval_iteration_{iteration}.json"
                eval_file.write_text(json.dumps(eval_results, indent=2), encoding="utf-8")
                iteration_state["eval_results_path"] = str(eval_file)

                if wandb_run is not None:
                    try:
                        wandb_run.log({
                            "iteration": iteration,
                            "routing_accuracy": eval_results["routing_accuracy"],
                            "error_detection_recall": eval_results["error_detection_recall"],
                            "retry_intelligence": eval_results["retry_intelligence"],
                            "synthesis_quality": eval_results["synthesis_quality"],
                            "overall_score": eval_results["overall_score"],
                        })
                    except Exception as exc:
                        logger.warning("wandb.log failed: %s", exc)

                _mark_step_completed(iteration_state, "evaluation")
                _checkpoint(state_path, state, iteration_state)
            else:
                eval_results = iteration_state.get("eval_results")
                if not eval_results and iteration_state.get("eval_results_path"):
                    eval_results = json.loads(
                        Path(iteration_state["eval_results_path"]).read_text(encoding="utf-8")
                    )
                    iteration_state["eval_results"] = eval_results

            logger.info(
                "Eval scores: routing=%s errors=%s retry=%s synthesis=%s overall=%s",
                _format_score(iteration_state.get("eval_scores", {}).get("routing_accuracy")),
                _format_score(iteration_state.get("eval_scores", {}).get("error_detection_recall")),
                _format_score(iteration_state.get("eval_scores", {}).get("retry_intelligence")),
                _format_score(iteration_state.get("eval_scores", {}).get("synthesis_quality")),
                _format_score(iteration_state.get("eval_scores", {}).get("overall_score")),
            )

            if iteration == args.max_iterations:
                logger.info("Final iteration reached; stopping after evaluation.")
                iteration_state["status"] = "FINAL_EVAL_COMPLETE"
                iteration_state["completed_at"] = datetime.now().isoformat()
                state["last_completed_iteration"] = iteration
                _checkpoint(state_path, state, iteration_state)
                break

            if "failure_analysis" not in iteration_state.get("completed_steps", []):
                logger.info("Step 2: Analyzing failure modes...")
                failures = _retry(
                    lambda: analyze_failures(eval_results),
                    logger=logger,
                    step_name="failure_analysis",
                )
                iteration_state["failure_modes"] = failures
                _mark_step_completed(iteration_state, "failure_analysis")
                _checkpoint(state_path, state, iteration_state)
            else:
                failures = iteration_state.get("failure_modes", [])

            logger.info(
                "Top failure modes: %s",
                [f.get("failure_type") for f in failures[:3]],
            )

            if "data_generation" not in iteration_state.get("completed_steps", []):
                logger.info("Step 3: Generating targeted training examples...")
                new_data_path = _retry(
                    lambda: generate_targeted_examples(
                        failure_modes=failures[:3],
                        num_examples=40,
                        existing_data_path=args.base_training_data,
                        output_dir=args.output_dir,
                        logger=logger,
                    ),
                    logger=logger,
                    step_name="data_generation",
                )
                iteration_state["new_training_data"] = new_data_path
                _mark_step_completed(iteration_state, "data_generation")
                _checkpoint(state_path, state, iteration_state)
            else:
                new_data_path = iteration_state.get("new_training_data", "")

            if "merge_data" not in iteration_state.get("completed_steps", []):
                logger.info("Step 4: Merging base and targeted training data...")
                merged_path = os.path.join(
                    args.output_dir,
                    f"training_data_iter_{iteration + 1}.jsonl",
                )
                merged_path = _retry(
                    lambda: merge_training_data(
                        base_path=args.base_training_data,
                        new_path=new_data_path,
                        output_path=merged_path,
                    ),
                    logger=logger,
                    step_name="merge_data",
                )
                iteration_state["merged_training_data"] = merged_path
                _mark_step_completed(iteration_state, "merge_data")
                _checkpoint(state_path, state, iteration_state)
            else:
                merged_path = iteration_state.get("merged_training_data", "")

            if "finetuning" not in iteration_state.get("completed_steps", []):
                logger.info("Step 5: Starting fine-tuning iteration %s...", iteration + 1)

                def _do_finetune() -> bool:
                    ok = run_finetuning(iteration + 1, merged_path, logger=logger)
                    if not ok:
                        raise RuntimeError("Fine-tuning script returned non-zero status")
                    return True

                try:
                    _retry(_do_finetune, logger=logger, step_name="finetuning")
                except Exception as exc:
                    logger.error(
                        "Fine-tuning failed for iteration %s after retries. Continuing with current model.",
                        iteration + 1,
                    )
                    iteration_state["finetuning_success"] = False
                    iteration_state["status"] = "FINETUNING_FAILED"
                    iteration_state["error"] = str(exc)
                    iteration_state["completed_at"] = datetime.now().isoformat()
                    state["last_completed_iteration"] = iteration
                    _checkpoint(state_path, state, iteration_state)
                    continue

                iteration_state["finetuning_success"] = True
                _mark_step_completed(iteration_state, "finetuning")
                _checkpoint(state_path, state, iteration_state)

            if "wait_for_server" not in iteration_state.get("completed_steps", []):
                logger.info("Step 6: Waiting for model server readiness...")

                def _wait() -> bool:
                    ready = wait_for_model_server(args.model_endpoint)
                    if not ready:
                        raise RuntimeError("Model server did not become healthy in time")
                    return True

                try:
                    _retry(_wait, logger=logger, step_name="wait_for_server")
                except Exception as exc:
                    logger.error(
                        "Model server did not recover for iteration %s. Continuing with previous model.",
                        iteration + 1,
                    )
                    iteration_state["status"] = "SERVING_FAILED"
                    iteration_state["error"] = str(exc)
                    iteration_state["completed_at"] = datetime.now().isoformat()
                    state["last_completed_iteration"] = iteration
                    _checkpoint(state_path, state, iteration_state)
                    continue

                _mark_step_completed(iteration_state, "wait_for_server")
                _checkpoint(state_path, state, iteration_state)

            iteration_state["status"] = "COMPLETED"
            iteration_state["completed_at"] = datetime.now().isoformat()
            state["last_completed_iteration"] = iteration
            _checkpoint(state_path, state, iteration_state)

        except Exception as exc:
            logger.error("Iteration %s failed: %s", iteration, exc, exc_info=True)
            iteration_state["status"] = "ERROR"
            iteration_state["error"] = str(exc)
            iteration_state["completed_at"] = datetime.now().isoformat()
            state["last_completed_iteration"] = iteration
            _checkpoint(state_path, state, iteration_state)
            continue

    logger.info("\n%s", "=" * 60)
    logger.info("LOOP COMPLETE - SUMMARY")
    logger.info("%s", "=" * 60)
    for it in sorted(state.get("iterations", []), key=lambda x: int(x.get("iteration", 0))):
        scores = it.get("eval_scores", {})
        logger.info(
            "Iteration %s: overall=%s routing=%s errors=%s retry=%s synthesis=%s [%s]",
            it.get("iteration"),
            _format_score(scores.get("overall_score")),
            _format_score(scores.get("routing_accuracy")),
            _format_score(scores.get("error_detection_recall")),
            _format_score(scores.get("retry_intelligence")),
            _format_score(scores.get("synthesis_quality")),
            it.get("status", "UNKNOWN"),
        )

    if wandb_run is not None:
        try:
            wandb_run.finish()
        except Exception:
            pass


if __name__ == "__main__":
    main()
