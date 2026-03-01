"""Scoring functions for orchestration quality evaluation."""

from __future__ import annotations

import re

import weave


def _tokenize_name(name: str) -> set[str]:
    """Split an agent name into word tokens.

    Splits on underscores, hyphens, and camelCase boundaries.
    E.g. 'security_analyzer' -> {'security', 'analyzer'}
         'customSecurityCheck' -> {'custom', 'security', 'check'}
    """
    # Insert underscore at camelCase boundaries
    s = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    tokens = re.split(r"[_\-]+", s.lower())
    return {t for t in tokens if t}


def _extract_files(strings: list[str]) -> set[str]:
    """Extract file path references from a list of strings."""
    files: set[str] = set()
    for s in strings:
        found = re.findall(
            r"[\w/.\-]+\.(?:py|js|ts|sql|rb|go|java|cpp|c|h|rs|yaml|yml|json|xml|html|css)\b",
            s,
        )
        files.update(found)
    return files


@weave.op
def routing_accuracy(expected_routing: dict, model_output: dict) -> dict:
    """Two-component routing accuracy with fuzzy agent name matching
    and file-level routing overlap.

    Score = 0.4 * agent_name_score + 0.6 * file_routing_score
    """
    actual_routing = model_output.get("routing_decisions", {})

    expected_agents = list(expected_routing.keys())
    actual_agents = list(actual_routing.keys())

    if not expected_agents and not actual_agents:
        return {"routing_accuracy": 1.0}
    if not expected_agents:
        return {"routing_accuracy": 0.0}

    # --- Component A: Agent name fuzzy matching (weight 0.4) ---
    agent_scores: list[float] = []
    for exp_agent in expected_agents:
        exp_tokens = _tokenize_name(exp_agent)
        best = 0.0
        for act_agent in actual_agents:
            act_tokens = _tokenize_name(act_agent)
            union = exp_tokens | act_tokens
            jaccard = len(exp_tokens & act_tokens) / len(union) if union else 0.0
            best = max(best, jaccard)
        agent_scores.append(best)
    agent_name_score = sum(agent_scores) / len(agent_scores)

    # --- Component B: File-level routing overlap (weight 0.6) ---
    expected_files: set[str] = set()
    for files in expected_routing.values():
        expected_files.update(files)

    # Extract files from model routing decisions (task descriptions may contain file refs)
    actual_files: set[str] = set()
    for _agent, tasks in actual_routing.items():
        for item in tasks:
            if re.search(r"\.(?:py|js|ts|sql|rb|go|java)\b", item):
                # Could be a bare file path or a description containing file refs
                actual_files.update(_extract_files([item]))

    # Fallback: extract file refs from the raw response if routing had none
    if not actual_files and model_output.get("raw_response"):
        actual_files = _extract_files([model_output["raw_response"]])

    if not expected_files and not actual_files:
        file_score = 1.0
    elif not expected_files or not actual_files:
        file_score = 0.0
    else:
        # Try both full-path and basename-only matching, take the better one
        path_union = expected_files | actual_files
        path_jaccard = len(expected_files & actual_files) / len(path_union) if path_union else 0.0

        exp_basenames = {f.rsplit("/", 1)[-1] for f in expected_files}
        act_basenames = {f.rsplit("/", 1)[-1] for f in actual_files}
        base_union = exp_basenames | act_basenames
        base_jaccard = len(exp_basenames & act_basenames) / len(base_union) if base_union else 0.0

        file_score = max(path_jaccard, base_jaccard)

    final = 0.4 * agent_name_score + 0.6 * file_score
    return {"routing_accuracy": round(final, 3)}


@weave.op
def error_detection_recall(known_errors: list, model_output: dict) -> dict:
    """Token-overlap recall scorer with 0.3 Jaccard threshold.

    For each expected error, finds the best-matching detected error by
    token Jaccard similarity. If best match >= 0.3, counts as detected.
    Extra detections are not penalized (recall only).
    """
    if not known_errors:
        return {"error_detection_recall": 1.0}

    detected = model_output.get("detected_errors", [])
    if not detected:
        return {"error_detection_recall": 0.0}

    stop_words = {"the", "a", "an", "in", "on", "is", "of", "for", "and", "to", "with"}

    def tokenize(s: str) -> set[str]:
        # Split on underscores, hyphens, whitespace, slashes, colons, dots, and other non-alnum
        parts = re.split(r"[_\-\s/:.,;()]+", s.lower())
        expanded: list[str] = []
        for p in parts:
            expanded.extend(re.split(r"[^a-z0-9]+", p))
        return {t for t in expanded if t and t not in stop_words}

    matches = 0
    used: set[int] = set()
    for known in known_errors:
        known_tokens = tokenize(known)
        if not known_tokens:
            continue
        best_score = 0.0
        best_idx = -1
        for i, det in enumerate(detected):
            if i in used:
                continue
            det_tokens = tokenize(det)
            union = known_tokens | det_tokens
            jaccard = len(known_tokens & det_tokens) / len(union) if union else 0.0
            if jaccard > best_score:
                best_score = jaccard
                best_idx = i
        if best_score >= 0.3:
            matches += 1
            if best_idx >= 0:
                used.add(best_idx)

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
