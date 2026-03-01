"""Run a Weave evaluation on a Mistral orchestrator model."""

from __future__ import annotations

import argparse
import asyncio
import json
import os

import weave

from eval.model import OrchestratorModel
from eval.scorers import (
    error_detection_recall,
    retry_intelligence,
    routing_accuracy,
    synthesis_quality,
)


def load_eval_dataset(path: str) -> list[dict]:
    """Load evaluation dataset from JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_evaluation(
    model_name: str,
    dataset_path: str = "data/eval_dataset.json",
    eval_name: str = "orchestration-quality",
) -> dict:
    """Run a full Weave evaluation and return aggregate scores."""
    project = "leonwenhao-dolores-research/rlm-distiller"
    try:
        if os.environ.get("WANDB_API_KEY"):
            weave.init(project)
        else:
            weave.init(project, settings={"disabled": True})
    except Exception:
        weave.init(project, settings={"disabled": True})

    rows = load_eval_dataset(dataset_path)
    dataset = weave.Dataset(name="orchestration-eval-v1", rows=rows)
    model = OrchestratorModel(model_name=model_name)

    evaluation = weave.Evaluation(
        name=eval_name,
        dataset=dataset,
        scorers=[
            routing_accuracy,
            error_detection_recall,
            retry_intelligence,
            synthesis_quality,
        ],
    )

    return asyncio.run(evaluation.evaluate(model))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run orchestration quality evaluation")
    parser.add_argument(
        "--model",
        default="mistral-small-latest",
        help="Mistral model name or fine-tuned model ID",
    )
    parser.add_argument(
        "--dataset",
        default="data/eval_dataset.json",
        help="Path to eval dataset",
    )
    parser.add_argument(
        "--eval-name",
        default="orchestration-quality",
        help="Name for this eval run",
    )
    args = parser.parse_args()

    print(f"Running evaluation on model: {args.model}")
    print(f"Dataset: {args.dataset}")
    print(f"Eval name: {args.eval_name}")

    results = run_evaluation(args.model, args.dataset, args.eval_name)
    print("\n=== RESULTS ===")
    print(json.dumps(results, indent=2, default=str))
