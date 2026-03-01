"""Weave model wrapper for Mistral orchestration endpoints."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import weave
from mistralai import Mistral


class OrchestratorModel(weave.Model):
    """Wraps a Mistral model endpoint for orchestration evaluation.

    Supports two backends:
    - model_endpoint="mistral" (default): uses the Mistral API
    - model_endpoint="http://localhost:8000/v1": uses an OpenAI-compatible endpoint (e.g. vLLM)
    """

    model_name: str = "mistral-small-latest"
    model_endpoint: str = "mistral"

    @weave.op
    def predict(self, task: str, file_tree: str, available_agents: list[str]) -> dict[str, Any]:
        """Call a chat completion endpoint and parse orchestration decisions."""

        system_prompt = (
            "You are a root orchestrator analyzing a codebase. "
            "Your available tools are:\n"
            "- `llm_query(agent, task, context)` — dispatch a focused task to a sub-LLM\n"
            "- `llm_batch(tasks)` — dispatch multiple tasks in parallel\n"
            "- `explore(path)` — list files in a directory\n"
            "- `read_metadata(file)` — get file size, last modified, imports\n\n"
            "Think step by step about how to orchestrate the analysis. "
            "Use multiple phases: exploration, decomposition & delegation, "
            "output evaluation with retries, cross-referencing, and final synthesis. "
            "End with answer['ready'] = True."
        )

        user_content = (
            f"File tree:\n```\n{file_tree}\n```\n\n"
            f"Available agents: {json.dumps(available_agents)}\n\n"
            f"Task: {task}\n\n"
            "Think step by step about how to orchestrate this analysis."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        if self.model_endpoint == "mistral":
            raw_text = self._call_mistral(messages)
        else:
            raw_text = self._call_openai_compatible(messages)

        parsed = parse_orchestration_response(raw_text)
        parsed["raw_response"] = raw_text
        return parsed

    def _call_mistral(self, messages: list[dict[str, str]]) -> str:
        """Call the Mistral API."""
        client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
        response = client.chat.complete(
            model=self.model_name,
            messages=messages,
            max_tokens=4096,
            temperature=0.7,
        )
        raw_content = response.choices[0].message.content
        if isinstance(raw_content, list):
            return "".join(getattr(part, "text", str(part)) for part in raw_content)
        return str(raw_content)

    def _call_openai_compatible(self, messages: list[dict[str, str]]) -> str:
        """Call an OpenAI-compatible endpoint (e.g. vLLM on Prime Intellect)."""
        from openai import OpenAI

        client = OpenAI(base_url=self.model_endpoint, api_key="dummy")
        response = client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=0.7,
            max_tokens=4096,
        )
        return response.choices[0].message.content


def parse_orchestration_response(text: str) -> dict[str, Any]:
    """Extract structured orchestration decisions from free-text output."""
    text_lower = text.lower()

    routing: dict[str, list[str]] = {}
    agent_pattern = re.findall(
        r"['\"]agent['\"]\s*:\s*['\"](\w+)['\"].*?['\"]task['\"]\s*:\s*['\"]([^'\"]+)['\"]",
        text,
        re.DOTALL,
    )
    for agent, task_desc in agent_pattern:
        routing.setdefault(agent, []).append(task_desc[:100])

    direct_calls = re.findall(r"llm_query\s*\(\s*['\"](\w+)['\"]", text)
    for agent in direct_calls:
        routing.setdefault(agent, [])

    detected_errors: list[str] = []
    error_patterns = re.findall(
        r"\*\*(?:CRITICAL|HIGH|MEDIUM|LOW)\*\*\s*[-—]\s*(.+?)(?:\n|$)",
        text,
    )
    for err in error_patterns:
        err_clean = re.sub(r"[^a-z0-9_\s]", "", err.lower().strip())
        err_id = "_".join(err_clean.split()[:6])
        if err_id:
            detected_errors.append(err_id)

    retry_decisions: list[str] = []
    retry_patterns = re.findall(
        r"(?:retry|re-analyze|retrying|re-run)\w*\s+(?:on\s+|with\s+|the\s+)?(\w+)",
        text_lower,
    )
    for target in retry_patterns:
        retry_decisions.append(f"retry_{target}")

    synthesis_markers: list[str] = []
    if "cross-reference" in text_lower or "cross_reference" in text_lower:
        synthesis_markers.append("cross_reference")
    if "confidence" in text_lower and re.search(r"confidence.*?0\.\d+", text_lower):
        synthesis_markers.append("confidence_score")
    if re.search(r"line[_\s]*\d+", text_lower):
        synthesis_markers.append("specific_line_numbers")
    if "confirmed by" in text_lower or "corroborated" in text_lower:
        synthesis_markers.append("cross_agent_confirmation")
    if "answer['ready'] = true" in text_lower or 'answer["ready"] = true' in text_lower:
        synthesis_markers.append("answer_ready_signal")

    num_calls = len(re.findall(r"llm_query|llm_batch", text))

    return {
        "routing_decisions": routing,
        "detected_errors": detected_errors,
        "retry_decisions": retry_decisions,
        "synthesis_markers": synthesis_markers,
        "num_sub_llm_calls": num_calls,
    }
