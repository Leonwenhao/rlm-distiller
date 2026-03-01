# SCRATCHPAD_CTO.md — RLM Distiller

## Session 5b — Scorer Fixes + Prompt Grounding (Feb 28 ~11 PM)

### Changes to `eval/scorers.py`

**routing_accuracy — rewritten with two-component fuzzy scoring:**
- Component A (weight 0.4): Agent name fuzzy matching via token Jaccard. Names are split on `_`, `-`, and camelCase boundaries, then compared. E.g., `security_analyzer` vs `custom_security_check` shares the `security` token.
- Component B (weight 0.6): File-level routing overlap. Extracts file paths from routing decision task descriptions (or falls back to raw_response). Compares both full paths and basenames, taking the better Jaccard score.
- Final = 0.4 * agent_name_score + 0.6 * file_routing_score

**error_detection_recall — rewritten with token-overlap matching:**
- Tokenizes error strings by splitting on `_`, `-`, whitespace, `/`, `:`, etc. Removes stop words.
- For each expected error, finds best-matching detected error by token Jaccard similarity.
- Threshold: 0.3 Jaccard to count as a match. Does not penalize extra detections (recall only).
- Prevents double-counting (each detected error can only match one expected error).

**retry_intelligence and synthesis_quality — unchanged** (working fine at 0.33 and 0.36).

### Changes to `eval/model.py`

Added prompt grounding constraints to the **system prompt** (lines 36-40):
- MUST select agents ONLY from available_agents list
- Use exact agent names in llm_query calls
- Report errors in filename_lineN_description format
- Include specific file names and line numbers in final answer

This won't affect iteration 1 scores (already recorded) but will improve iteration 2+ scores when retrained.

### Validation Test Results

```
Routing score: {'routing_accuracy': 0.567}   (was 0.005)
Error detection score: {'error_detection_recall': 0.5}   (was 0.068)
All scorers import OK
```

Both well above the 0.2 threshold. The test used:
- Routing: mismatched agent names (custom_security_check vs security_analyzer) but overlapping files
- Error detection: different format strings (userpy45_sql_format_string_vuln vs sql_injection_user_py_line_45)

### Deviations from Spec

- Prompt grounding was placed in the system prompt rather than user prompt. System prompt is more prominent and appropriate for constraints the model should always follow.
- Added double-count prevention in error_detection_recall (each detected error can only match one expected). Spec didn't require it but it prevents inflated scores.
- Added basename-only file matching as fallback for file routing (takes max of path and basename Jaccard). This handles cases where model references files without directory paths.

### Issues

- None encountered. All changes clean.

### Context Window Estimate

~15% used. 3 tasks completed (routing scorer, error detection scorer, prompt grounding + validation).


---

## Session 5c — Manual Loop Test + Overnight Deployment (Mar 1 ~12:00 AM)

### Iteration 1 Baseline (Re-eval with Fixed Scorers)

Model: LoRA adapter from checkpoints/iteration_1/ (trained on 39 traces, 3 epochs, 9.3 min)

| Metric                  | Score |
|-------------------------|-------|
| routing_accuracy        | 0.193 |
| error_detection_recall  | 0.000 |
| retry_intelligence      | 0.300 |
| synthesis_quality       | 0.530 |
| model_latency (avg)     | 83.8s |

Weave trace: https://wandb.ai/leonwenhao-dolores-research/rlm-distiller/r/call/019ca7b8-d505-7675-919d-2e00cbc98fd8

### Iteration 2 Scores (120-trace dataset)

Model: LoRA adapter from checkpoints/iteration_2/ (trained on 120 traces, 3 epochs, 27.2 min)
Training loss: 1.027 to 0.645 (mean), final token accuracy: 0.858

| Metric                  | Score |
|-------------------------|-------|
| routing_accuracy        | 0.094 |
| error_detection_recall  | 0.000 |
| retry_intelligence      | 0.280 |
| synthesis_quality       | 0.398 |
| model_latency (avg)     | 84.5s |

Weave trace: https://wandb.ai/leonwenhao-dolores-research/rlm-distiller/r/call/019ca7dd-c754-7ab1-9b5c-ab08cf6b409d

### Delta (Iteration 1 to 2)

| Metric                  | Iter 1 | Iter 2 | Delta  |
|-------------------------|--------|--------|--------|
| routing_accuracy        | 0.193  | 0.094  | -0.099 |
| error_detection_recall  | 0.000  | 0.000  |  0.000 |
| retry_intelligence      | 0.300  | 0.280  | -0.020 |
| synthesis_quality       | 0.530  | 0.398  | -0.132 |

Scores dropped slightly. High variance expected with only 25 eval examples and non-deterministic model output. The first iter 1 run (without Weave) showed routing=0.169, synthesis=0.369 — so variance across runs is roughly 0.1.

### Weave Dashboard Status

CONFIRMED WORKING. Traces appear at:
https://wandb.ai/leonwenhao-dolores-research/rlm-distiller/weave

Key fix: WANDB_API_KEY was in ~/.bashrc behind a non-interactive guard. SSH commands don't source it. Fix: added to ~/.profile and pass explicitly via export in all SSH/tmux commands.

### Overnight Loop Status

RUNNING in tmux session "loop".

To check:
- tmux attach -t loop
- tail -f ~/rlm-distiller/loop_output.log
- cat ~/rlm-distiller/loop_results/loop_state.json

Loop params: model_endpoint=http://localhost:8000/v1, model_name=rlm-distiller, base_training_data=data/orchestration_traces_train.jsonl, max_iterations=6

W&B run: https://wandb.ai/leonwenhao-dolores-research/rlm-distiller/runs/yw9w1jfb

Expected: 3-4 completed iterations by morning (each ~1-1.5 hr: 35 min eval + 27 min train + 5 min serve + overhead).

No ANTHROPIC_API_KEY available, so targeted data generation uses fallback (augments existing training data).

### Bug Fixes Applied

1. finetune/run_iteration.sh — added Step 0: kill vLLM before training. Single-GPU setup cannot train while vLLM is serving. Without this fix, training OOMs.

2. finetune/run_iteration.sh — redirected vLLM server output to /tmp/vllm_server.log. Without this, subprocess.run(capture_output=True) in the loop blocks forever because the backgrounded vLLM process inherits stdout/stderr pipes.

### Context Window Estimate

~35% used. 4 tasks completed (iter 1 eval, iter 2 training, iter 2 eval, overnight loop started).


---

## Overnight Loop Results — Final (Mar 1, 1:02 PM)

Loop ran autonomously from 05:35 to 13:02 (7.5 hours), completing 7 iterations (0-6).

### Full Scorecard

| Iter | routing | errors | retry | synthesis | overall | Time |
|------|---------|--------|-------|-----------|---------|------|
| 0 | 0.088 | 0.000 | 0.410 | 0.375 | 0.218 | 06:06 |
| 1 | 0.121 | 0.000 | 0.300 | 0.387 | 0.202 | 07:16 |
| 2 | 0.104 | 0.010 | 0.530 | 0.377 | 0.255 | 08:25 |
| 3 | 0.119 | 0.000 | 0.300 | 0.395 | 0.204 | 09:34 |
| 4 | 0.098 | 0.010 | 0.440 | 0.451 | 0.250 | 10:43 |
| 5 | 0.097 | 0.000 | 0.400 | 0.459 | 0.239 | 11:53 |
| 6 | 0.100 | 0.000 | 0.490 | 0.409 | 0.250 | 13:02 |

### Trends

- synthesis_quality improved: 0.375 -> 0.459 (+22%)
- retry_intelligence peaked at 0.530 (iter 2), settled at 0.490 (iter 6)
- routing_accuracy peaked at 0.121 (iter 1), stabilized around 0.10
- error_detection_recall remained near zero (hardest dimension)
- Best overall: 0.255 (iter 2), with iters 4 and 6 tying at 0.250

### Timing Per Iteration

- Eval: ~31 min (25 examples, ~75s each)
- Failure analysis + data gen + merge: <1 min
- Training: ~37 min (augmented dataset grows each iteration)
- Server startup: ~2 min
- Total per iteration: ~71 min

### Infrastructure

- No errors or crashes across 7 iterations
- All Weave traces published successfully
- W&B run: https://wandb.ai/leonwenhao-dolores-research/rlm-distiller/runs/yw9w1jfb
- Weave dashboard: https://wandb.ai/leonwenhao-dolores-research/rlm-distiller/weave
- Loop state: ~/rlm-distiller/loop_results/loop_state.json
- Per-iteration eval results: ~/rlm-distiller/loop_results/eval_iteration_*.json
- vLLM currently serving iteration 6 model at http://localhost:8000/v1

### Checkpoints on Disk

- checkpoints/iteration_1/ through checkpoints/iteration_6/
- Each contains adapter_config.json + adapter_model.safetensors + training_metadata.json
