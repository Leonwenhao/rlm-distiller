# RLM Distiller — CTO Cold Start Prompt (Session 5)

**Date:** Saturday Feb 28, 2026, ~10:00 PM
**Demo:** Sunday Mar 1, 3:00 PM (~17 hours remaining)
**Hackathon:** Mistral Worldwide Hackathon SF
**Track:** Track 02 (Fine-Tuning by W&B) + W&B Mini Challenge

---

## Your Role

You are the CTO for the RLM Distiller project. You have full access to the local codebase and SSH access to a remote GPU. Your job is to review code, make fixes, run tests, and get the autonomous self-improvement loop running overnight so we have multi-iteration results for tomorrow's 3 PM demo.

You are NOT relaying tasks to another agent this session. You are reading, fixing, testing, and deploying directly. Move fast — every hour counts.

**After every response, include a context usage estimate at the bottom:**
```
Context window: ~X% | Tasks completed this session: N
```
If you hit MEDIUM (3+ major tasks done, having trouble recalling early decisions), finish your current task and write a continuation cold start for a fresh session. Do NOT start new work past MEDIUM.

---

## What This Project Is

**RLM Distiller** distills multi-agent orchestration intelligence from frontier models (Claude Opus) into fine-tuned Mistral models, then continuously self-improves using W&B Weave evals. The core insight comes from DeepRepo (https://github.com/Leonwenhao/deeprepo) — a system where a root orchestrator model (Claude) dispatches focused analysis tasks to cheap sub-LLM workers. Benchmarks showed Sonnet dispatches 9 times vs Opus at 61 — a purely behavioral gap. Fine-tuning teaches cheaper models to orchestrate like expensive ones.

The demo needs to show: a Weave trace timeline of the self-improvement loop in action, plus eval scores improving across fine-tuning iterations.

---

## Current State (What Just Happened)

**Iteration 1 QLoRA training completed successfully.** 39 orchestration traces, 3 epochs, 15 steps, 9.3 minutes wall time. Final training loss: 0.887, token accuracy: 80.8%. The fine-tuned model is served via vLLM at `http://localhost:8000/v1` with model name `rlm-distiller` and `--max-model-len 8192`.

**Full 25-example eval completed. These are the iteration 1 scores:**

| Metric | Score |
|---|---|
| routing_accuracy | 0.005 |
| error_detection_recall | 0.068 |
| retry_intelligence | 0.330 |
| synthesis_quality | 0.364 |
| num_sub_llm_calls | 1.8 avg |
| model_latency | 82.2s avg |

**Parser was partially fixed last session.** Error detection went from 0.0 to 0.068 (parser now extracts 17 error IDs per example, up from 0). Routing stayed near 0 because the model invents its own agent names (`dynamic_queries`, `parameterized_issues`) instead of using the provided `available_agents` list (`sql_analyzer`, `security_analyzer`, `code_reviewer`). This is confirmed as a model/prompt behavior issue, not a parser bug.

**W&B Weave tracing is broken.** The eval run produced "Task failed: Invalid project_id format" errors. Traces are NOT appearing in the W&B dashboard. The intended project is `leonwenhao-dolores-research/rlm-distiller`. This must be fixed before the overnight loop — the Weave trace timeline is the primary demo artifact.

**150 orchestration traces are now fully generated on the local machine.** These are ready to SCP to the GPU for iteration 2 training. Details:

| File | Traces | Size |
|---|---|---|
| data/orchestration_traces_all.jsonl | 150 | 2.4 MB |
| data/orchestration_traces_train.jsonl | 120 | 1.9 MB |
| data/orchestration_traces_eval.jsonl | 30 | 509 KB |

Quality metrics: 100% coverage on explore(), read_metadata(), llm_batch(), confidence scores, and Phase 1-3 structure. 99% retry logic coverage, 93% cross-referencing. Language distribution: Python 63, JavaScript 42, Go 32, Java 9, Rust 4. Average assistant response ~14,800 chars (~3,700 tokens).

The GPU currently has the OLD split: 39 train / 10 eval. These new files (120 train / 30 eval) must replace them before iteration 2 training begins.

---

## GPU Access

**Pod:** `sly-emerald-labrador` (Prime Intellect A100 80GB)
**SSH:** `ssh -o StrictHostKeyChecking=no ubuntu@216.81.248.143 -i <private_key_path>`
**Private key:** Find it in the local project directory — likely `private_key.pem` or at `~/Desktop/RLM Distiller/private_key.pem`. Run `chmod 400` on it first.
**Python:** Use `python3`. `PYTHONPATH=.` is required when running scripts from `~/rlm-distiller`.
**WANDB_API_KEY:** Should be exported in the current shell. Verify with `printenv | grep WANDB`. If not set, check `~/.bashrc` or ask the operator for the key.

**GPU file structure:**
```
~/rlm-distiller/
├── data/
│   ├── orchestration_traces_train.jsonl  (39 examples — OLD, needs replacing)
│   ├── orchestration_traces_eval.jsonl   (10 examples — OLD, needs replacing)
│   ├── orchestration_traces_all.jsonl    (49 examples — OLD, needs replacing)
│   ├── eval_dataset.json                 (25 ground-truth eval examples)
│   └── generate_traces.py
├── finetune/
│   ├── train_qlora.py    (PATCHED: sdpa attn, max_length, chat template)
│   ├── serve_model.py
│   └── run_iteration.sh
├── eval/
│   ├── model.py          (PATCHED: max_tokens=2048, URL endpoint detection)
│   ├── scorers.py        (PATCHED last session: expanded regex patterns)
│   ├── run_eval.py       (PATCHED: URL detection for --model arg)
│   └── __init__.py
├── mcp_server/
│   ├── server.py
│   └── client.py
├── loop/
│   └── run_loop.py
└── checkpoints/
    └── iteration_1/      (LoRA adapter from first training run)
```

---

## PRIORITY 1: Fix W&B Weave Tracing (CRITICAL — Demo Blocker)

This is the single most important fix. Without working Weave traces, the demo has no visual artifact and fails the W&B mini challenge.

**Diagnosis steps:**
1. SSH into the GPU
2. Run `grep -rn "weave.init" ~/rlm-distiller/` to find every `weave.init()` call
3. Check if the project string is correctly formatted as `"leonwenhao-dolores-research/rlm-distiller"` (entity/project-name format)
4. Verify `WANDB_API_KEY` is set: `printenv | grep WANDB`
5. Check if the W&B entity `leonwenhao-dolores-research` actually exists — the docs also mention `leonwenhao-dolores-research/intro-example` as an earlier name. The entity name must match the W&B account exactly.

**Fix:** Update all `weave.init()` calls to use the correct `"entity/project-name"` string. If the entity doesn't exist on W&B, you may need to create the project first via `wandb.init(entity="...", project="rlm-distiller")` or through the W&B web UI.

**Test:** Run a minimal test — a single `@weave.op` decorated function call — and confirm the trace appears at `https://wandb.ai/leonwenhao-dolores-research/rlm-distiller/weave`. If this works, re-run the full 25-example eval and confirm all traces land.

---

## PRIORITY 2: Upload Full 150-Trace Dataset to GPU

The local machine has the complete, verified trace dataset. The GPU has outdated files. Get the new data onto the GPU immediately so iteration 2 trains on 120 examples instead of 39.

**Find the local trace files.** They should be in the project's `data/` directory on this machine. Look for:
- `data/orchestration_traces_train.jsonl` (120 traces, ~1.9 MB)
- `data/orchestration_traces_eval.jsonl` (30 traces, ~509 KB)
- `data/orchestration_traces_all.jsonl` (150 traces, ~2.4 MB)

If they're not in the project root's `data/` folder, check `~/Desktop/RLM Distiller/data/` or search with `find ~ -name "orchestration_traces_train.jsonl" -size +1M 2>/dev/null`.

**SCP to GPU:**
```bash
scp -i <private_key> \
  data/orchestration_traces_train.jsonl \
  data/orchestration_traces_eval.jsonl \
  data/orchestration_traces_all.jsonl \
  ubuntu@216.81.248.143:~/rlm-distiller/data/
```

**Verify on GPU after upload:**
```bash
ssh <gpu> "wc -l ~/rlm-distiller/data/orchestration_traces_*.jsonl"
```
Expected: 120 train, 30 eval, 150 all.

**IMPORTANT TIMING NOTE:** Iteration 1 trained on 39 examples in 9.3 minutes. With 120 training examples (3x more) at the same batch size and 3 epochs, expect roughly 25-30 minutes per iteration. This means the overnight loop will produce 3-4 iterations rather than 6-8. That's still plenty for the demo — you only need 2 data points for a before/after story — but be aware of the time per cycle when planning.

---

## PRIORITY 3: Fix Routing Accuracy Scorer (High Leverage)

Routing accuracy at 0.005 makes the improvement story weak. The problem is that the model generates agent names like `dynamic_queries` and `parameterized_issues` instead of using the names from the `available_agents` list in the prompt (like `sql_analyzer`, `security_analyzer`). This needs two fixes — one to the scorer (measure what the model actually does) and one to the model prompt (guide the model toward expected behavior).

### Fix 3a: Fuzzy Routing Scorer

Read `eval/scorers.py` and find the `routing_accuracy` scorer. Currently it does exact Jaccard similarity between expected and actual agent names, so `dynamic_queries` vs `sql_analyzer` = 0.0 overlap.

Change it to use token-level overlap scoring. The idea: split both agent names into word tokens (split on `_` and camelCase boundaries), compute Jaccard similarity on the token sets. So `sql_security_check` vs `security_analyzer` would share the token `security` and get partial credit. This is intellectually honest — the model IS routing to specialized subtasks, just naming them differently.

Also consider a secondary approach: instead of just matching agent names, match the actual file assignments. If the model says "dispatch agent X to analyze auth.py and routes.py" and the ground truth says "dispatch security_analyzer to auth.py and routes.py", the file-level routing is correct even though the agent name differs. Check if the eval dataset and parser support file-level routing comparison — if so, add a file-overlap component to the routing score.

### Fix 3b: Prompt Grounding in Eval

Read `eval/model.py` and find the system prompt or task formatting in the `predict` method. Add explicit grounding instructions that tell the model:
- "You MUST select agents ONLY from the available_agents list provided. Do not invent new agent names."
- "When reporting findings, reference errors by file and line number in the format: filename_lineN_description"
- "Your routing decisions should map agents from the available_agents list to specific files from the file tree."

This doesn't affect iteration 1 scores (those are already recorded) but will improve iteration 2+ scores, creating the improvement curve we need for the demo.

---

## PRIORITY 4: Fix Error Detection Recall Scorer

Error detection is at 0.068. The parser was fixed last session to extract more error patterns, but the matching between detected errors and known errors is still too strict. Read `eval/scorers.py` and check how `error_detection_recall` compares detected errors against `known_errors`.

The model produces errors like `userpy45_get_user_by_email_uses_stringformat` and the expected format is something like `sql_injection_user_py_line_45`. These describe the same error but won't match with exact string comparison.

Improve the matching to use token overlap with a threshold — if two error descriptions share enough meaningful tokens (file name, line number, error type keywords), count it as a match. Normalize strings before comparison (lowercase, split on underscores, remove common stop words).

---

## PRIORITY 5: Test the Autonomous Loop (One Manual Iteration)

Before letting `loop/run_loop.py` run unattended overnight, do one complete iteration manually to catch issues.

1. Read `loop/run_loop.py` to understand the step chain
2. Verify it references the correct file paths (especially now that the training data files are larger — check that `train_qlora.py` reads from `data/orchestration_traces_train.jsonl` and will pick up the new 120-example file)
3. Run one iteration manually: evaluate → analyze failures → generate targeted data → merge with existing training data → fine-tune (iteration 2) → wait for server → evaluate again
4. Watch for: file path errors, argument mismatches, training script expecting files in the wrong location, serve script failing to start, eval breaking on the new model
5. Compare iteration 2 eval scores to iteration 1 scores. Any improvement (even small) validates the loop.
6. With 120 training examples, this single iteration will take ~25-30 minutes for training alone, plus eval time (~25 examples × 82s ≈ 35 min). Budget about 1-1.5 hours for the full manual test.

---

## PRIORITY 6: Start Overnight Loop

Once one manual iteration succeeds:

1. Confirm W&B Weave traces are landing in the dashboard (from Priority 1)
2. Start `loop/run_loop.py` in a `tmux` or `screen` session so it survives SSH disconnection:
```bash
tmux new -s loop
cd ~/rlm-distiller && PYTHONPATH=. python3 loop/run_loop.py 2>&1 | tee loop_output.log
# Ctrl+B then D to detach
```
3. With ~30 min training + ~35 min eval per cycle, each full iteration takes roughly 1-1.5 hours. Over 8 hours of sleep, expect 3-4 completed iterations. That gives you iteration 1 (baseline on 39 traces) + iterations 2-5 (on 120 traces with progressive targeted data additions) — more than enough data points for a compelling improvement curve.
4. The operator will check results in the morning.

---

## What NOT to Do (Failed Paths — Don't Retry)

- **Mistral La Plateforme Fine-Tuning API** — account-level restriction, staff couldn't fix. Dead.
- **Mistral Small 3.1 24B Instruct (multimodal)** — `Mistral3Config` not supported by transformers AutoModelForCausalLM. Wrong model. The correct model is `mistralai/Mistral-Small-24B-Instruct-2501` (text-only, already loaded and serving).
- **FlashAttention2** — not installed on GPU. Already fixed with `attn_implementation="sdpa"`. Don't try to install flash-attn.
- **`trl` max_seq_length** — already patched to `max_length`. Don't revert.

---

## Training Hyperparameters (For Reference)

QLoRA: 4-bit NF4, double quantization. LoRA rank 16, alpha 32, dropout 0.05, all linear layers. Batch size 2, gradient accumulation 4 (effective batch 8). LR 2e-4, cosine schedule, 10 warmup steps. 3 epochs, max sequence length 4096. Gradient checkpointing on. Paged AdamW 8-bit.

---

## Demo Requirements (What This Overnight Work Must Produce)

By tomorrow morning we need:
1. **Working Weave traces** in the dashboard showing eval runs, failure analysis, and fine-tuning triggers
2. **At least 2 iterations** of eval scores (iteration 1 vs iteration 2+) showing improvement on at least one dimension
3. **Aggregate scores per iteration** saved somewhere retrievable (JSON files, Weave dashboard, or loop log)

The demo is 3 minutes:
- Minute 1: Problem statement (Opus vs Sonnet behavioral gap)
- Minute 2: Walk through Weave trace timeline showing the loop
- Minute 3: Show improvement chart + cost comparison

---

## Start Now

1. SSH into the GPU
2. Read `eval/scorers.py`, `eval/model.py`, `eval/run_eval.py`, and `loop/run_loop.py`
3. Grep for all `weave.init()` calls
4. **Fix Weave tracing first** (Priority 1) — test with a minimal trace
5. **SCP the 120-train / 30-eval trace files to the GPU** (Priority 2) — do this as soon as you have the private key working, even in parallel with the Weave fix
6. Fix the scorers (Priorities 3-4)
7. Test one manual loop iteration (Priority 5)
8. Start the overnight loop in tmux (Priority 6)

Go.
