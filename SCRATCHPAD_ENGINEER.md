# SCRATCHPAD_ENGINEER

## What I implemented

### Files created/updated
- `requirements.txt`
- `eval/__init__.py`
- `eval/model.py`
- `eval/scorers.py`
- `eval/run_eval.py`
- `mcp_server/__init__.py`
- `mcp_server/server.py`
- `mcp_server/client.py`
- `data/eval_dataset.json`
- `SCRATCHPAD_ENGINEER.md`

### Approach taken
- Built a complete eval package:
  - `OrchestratorModel` as a `weave.Model` wrapper around Mistral chat completions.
  - Heuristic parser for routing/error/retry/synthesis extraction.
  - Four scorer ops: `routing_accuracy`, `error_detection_recall`, `retry_intelligence`, `synthesis_quality`.
  - Standalone runner `eval/run_eval.py` with CLI args.
- Built MCP server with 4 tools:
  - `run_evaluation`
  - `analyze_failures`
  - `generate_training_data`
  - `trigger_finetuning`
- Built MCP client to run full loop:
  - `run_evaluation -> analyze_failures -> generate_training_data -> trigger_finetuning`
- Created `data/eval_dataset.json` with 25 examples across the 5 requested categories.
  - Validated constraints: 25 rows, agent count range 2-5, retry count range 0-3, known error count range 2-6.

## Deviations from spec (and why)
- Used `.venv/bin/python` and `.venv/bin/pip` instead of `python`/`pip` because `python` was not available on PATH in this environment.
- Added non-interactive Weave fallback in `eval/run_eval.py`, `mcp_server/server.py`, and `mcp_server/client.py`:
  - If `WANDB_API_KEY` is missing, initialize Weave in disabled mode (`settings={"disabled": True}`) to prevent blocking login prompts.
  - This keeps local startup/import smoke tests working without interactive auth and preserves full tracing behavior when credentials are present.
- `generate_training_data` now has a template fallback when Anthropic API generation is unavailable (e.g., missing key/network), so the MCP tool still returns a usable JSONL path.

## Issues/questions encountered
- `weave.init(...)` with no W&B auth prompts for interactive login and blocks server startup in stdio mode.
- `requests` emits `RequestsDependencyWarning` about `urllib3`/`chardet` compatibility after install.
- Offline environment produced Sentry/network retry warnings during some imports/startup checks.

## Verification results (command outputs)

1. Install dependencies
- Command:
  - `.venv/bin/python -m pip install -r requirements.txt`
- Result (tail):
  - `Successfully installed ... mcp-1.26.0 ... weave-0.52.29 ...`

2. Import smoke test
- Command:
  - `.venv/bin/python -c "from eval.model import OrchestratorModel; from eval.scorers import routing_accuracy; print('OK')"`
- Output:
  - `OK`

3. MCP server startup smoke test
- Command:
  - `.venv/bin/python -m mcp_server.server`
- Startup output:
  - `Starting RLM-Distiller MCP Server...`
  - `Tools: run_evaluation, analyze_failures, generate_training_data, trigger_finetuning`
- Note:
  - In this terminal harness, stopping stdio server via EOF/interrupt can print async cancellation traces; startup itself is successful.

4. Weave init smoke test
- Command:
  - `WEAVE_DISABLED=true .venv/bin/python -c "import weave; weave.init('leonwenhao-dolores-research/rlm-distiller'); print('Weave OK')"`
- Output:
  - `Weave OK`

5. Dataset validation
- Command:
  - `.venv/bin/python -m json.tool data/eval_dataset.json`
- Output:
  - `JSON_OK`
- Command:
  - dataset constraint script
- Output:
  - `rows 25`
  - `agents_min_max 2 5`
  - `retries_min_max 0 3`
  - `known_errors_min_max 2 6`

## Status
NEEDS_REVIEW

---

## Update: Autonomous Self-Improvement Loop (loop/run_loop.py)

### What I implemented

#### Files created/updated
- `loop/__init__.py` (empty init)
- `loop/run_loop.py` (full autonomous loop orchestration script)
- `SCRATCHPAD_ENGINEER.md` (this update)

#### Approach taken
- Implemented a standalone loop orchestrator that does **not** use MCP:
  - Directly evaluates via `OrchestratorModel` + scorer functions from `eval/scorers.py`.
  - Performs per-example scoring and aggregate metric calculation.
  - Computes bottom-30% failure analysis into:
    - `routing_failures`
    - `missed_errors`
    - `bad_retry_decisions`
    - `shallow_synthesis`
  - Generates targeted examples with Anthropic API when available.
  - Falls back to local generation by mutating existing training examples (or templates) when Anthropic is unavailable.
  - Merges base + targeted JSONL with deduplication.
  - Invokes `finetune/run_iteration.sh` and waits for server health (`/models` then `/health`).
- Added recovery/reliability behavior:
  - State checkpointing after every step into `loop_state.json`.
  - Atomic state writes (`.tmp` then rename).
  - Resume logic that restarts from the first non-final iteration and skips already-completed steps.
  - Exponential backoff retries (3 attempts) for each step.
  - Fine-tuning failure handling: marks iteration `FINETUNING_FAILED` and continues loop.
  - Serving failure handling: marks iteration `SERVING_FAILED` and continues loop.
  - Iteration-level exception handling logs full traceback and continues next iteration.
- Added dual logging:
  - stdout + `loop_results/loop.log`.
  - eval payload persisted per iteration (`eval_iteration_<n>.json`) and summarized into `loop_state.json`.
- Added W&B resilience:
  - `weave.init` is wrapped so failures do not stop the loop.
  - optional `wandb.log` when `WANDB_API_KEY` is available.

### Deviations from spec (and why)
- Added `--model_name` CLI argument (default `mistral-small-latest`) so the script can target specific served model IDs if needed.
- Used lazy imports for eval modules inside `run_evaluation()`:
  - This ensures `from loop.run_loop import main` and state helper imports work even when optional eval dependencies are not present at import time.
- Weave project path in loop uses `leonwenhao-dolores-research/{wandb_project}`:
  - Keeps project configurable via CLI and consistent with requested `--wandb_project`.

### Issues/questions encountered
- Environment `python` binary is not guaranteed on PATH; `.venv/bin/python` was used for verification commands.
- `loop` import originally failed due eager import chain (`eval.model -> weave`) before dependency availability; fixed via lazy imports.

### Test results (output)

1. Import test
- Command:
  - `.venv/bin/python -c "from loop.run_loop import main; print('OK')"`
- Output:
  - `OK`

2. State save/load test
- Command:
  - `.venv/bin/python -c "from loop.run_loop import save_state, load_state; save_state('/tmp/test_state.json', {'test': True, 'iterations': []}); s = load_state('/tmp/test_state.json'); assert s['test'] == True; print('State save/load OK')"`
- Output:
  - `State save/load OK`

3. Compile check
- Command:
  - `.venv/bin/python -m compileall loop`
- Output:
  - `Listing 'loop'...`
  - `Compiling 'loop/run_loop.py'...`

4. Resume behavior sanity check
- Command:
  - `.venv/bin/python -c "from loop.run_loop import _detect_start_iteration; s={'iterations':[{'iteration':0,'status':'COMPLETED','completed_steps':['evaluation']},{'iteration':1,'status':'IN_PROGRESS','completed_steps':['evaluation','failure_analysis']}],'last_completed_iteration':0}; print('Resume target', _detect_start_iteration(s, True))"`
- Output:
  - `Resume target 1`

## Status
NEEDS_REVIEW
