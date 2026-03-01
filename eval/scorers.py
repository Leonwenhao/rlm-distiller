"""Scoring functions for orchestration quality evaluation."""

from __future__ import annotations

import weave


@weave.op
def routing_accuracy(expected_routing: dict, model_output: dict) -> dict:
    """Jaccard similarity between expected and actual agent assignments."""
    expected_agents = set(expected_routing.keys())
    actual_routing = model_output.get("routing_decisions", {})
    actual_agents = set(actual_routing.keys())

    if not expected_agents and not actual_agents:
        return {"routing_accuracy": 1.0}
    if not expected_agents or not actual_agents:
        return {"routing_accuracy": 0.0}

    intersection = expected_agents & actual_agents
    union = expected_agents | actual_agents
    score = len(intersection) / len(union) if union else 0.0

    return {"routing_accuracy": round(score, 3)}


@weave.op
def error_detection_recall(known_errors: list, model_output: dict) -> dict:
    """Fraction of known errors detected by the model."""
    if not known_errors:
        return {"error_detection_recall": 1.0}

    detected = model_output.get("detected_errors", [])
    if not detected:
        return {"error_detection_recall": 0.0}

    stop_words = {"the", "in", "on", "a", "an", "of", "for", "and", "is", "to", "with"}

    def tokenize(s: str) -> set[str]:
        return set(s.lower().replace("_", " ").split()) - stop_words

    matches = 0
    for known in known_errors:
        known_tokens = tokenize(known)
        for det in detected:
            det_tokens = tokenize(det)
            overlap = known_tokens & det_tokens
            if len(overlap) >= 2:
                matches += 1
                break

    recall = matches / len(known_errors)
    return {"error_detection_recall": round(recall, 3)}


@weave.op
def retry_intelligence(expected_retries: list, model_output: dict) -> dict:
    """Score retry behavior against expected retry actions."""
    actual_retries = model_output.get("retry_decisions", [])

    if not expected_retries and not actual_retries:
        return {"retry_intelligence": 1.0}

    if not expected_retries and actual_retries:
        return {"retry_intelligence": 0.0}

    if expected_retries and not actual_retries:
        return {"retry_intelligence": 0.0}

    def normalize(s: str) -> str:
        return s.lower().replace("retry_", "").replace("retry ", "").strip()

    expected_normalized = {normalize(r) for r in expected_retries}
    actual_normalized = {normalize(r) for r in actual_retries}

    matches = sum(
        1
        for exp in expected_normalized
        if any(exp in act or act in exp for act in actual_normalized)
    )

    if matches == len(expected_normalized):
        score = 1.0
    elif matches > 0:
        score = 0.5 + (0.5 * matches / len(expected_normalized))
    elif actual_retries:
        score = 0.25
    else:
        score = 0.0

    return {"retry_intelligence": round(score, 3)}


@weave.op
def synthesis_quality(expected_synthesis_markers: list, model_output: dict) -> dict:
    """Score synthesis depth by expected marker coverage."""
    if not expected_synthesis_markers:
        return {"synthesis_quality": 1.0}

    actual_markers = set(model_output.get("synthesis_markers", []))
    expected_set = set(expected_synthesis_markers)

    matches = actual_markers & expected_set
    score = len(matches) / len(expected_set) if expected_set else 0.0

    return {"synthesis_quality": round(score, 3)}
