# CTO Scratchpad — RLM Distiller

## Session 5a
- **Started:** 2026-02-28 ~10:15 PM
- **Scope:** Priority 1 (Weave tracing fix) + Priority 2 (SCP training data)

## Priority 1: W&B Weave Tracing — Status: COMPLETE
- [x] SSH into GPU
- [x] grep all weave.init() calls, document current project strings
- [x] Check WANDB_API_KEY is set on GPU
- [x] Determine correct entity/project name
- [x] Fix weave.init() calls
- [x] Run minimal Weave trace test
- [x] Document: did the test throw errors? What was the output?

### Diagnosis Results

**weave.init() calls found in 4 files:**
- `eval/run_eval.py:36` — `weave.init("leonwenhao-dolores-research/rlm-distiller")`
- `loop/run_loop.py:102` — `weave.init(weave_project)` where `weave_project` defaults to `"leonwenhao-dolores-research/rlm-distiller"`
- `mcp_server/client.py:20` — `weave.init("leonwenhao-dolores-research/rlm-distiller")`
- `mcp_server/server.py:26` — `weave.init("leonwenhao-dolores-research/rlm-distiller")`

All use the same project string. All files gate on `WANDB_API_KEY` being set and fall back to `settings={"disabled": True}` if missing.

**Root cause: `WANDB_API_KEY` was not set on the GPU.**
- Not in `~/.bashrc`, not in env, not in `.netrc`
- Found the key in local machine's `~/.netrc` (under `api.wandb.ai`)
- The code was correct all along — it just needed the env var

**Entity verification:**
- `wandb.Api().viewer.entity` returned `leonwenhao-dolores-research` — matches all hardcoded strings
- No code changes needed to project strings

**Fix applied:**
- Added `export WANDB_API_KEY='...'` to `~/.bashrc` on GPU
- Key is now persisted across SSH sessions

**Minimal trace test — SUCCESS:**
```
weave: Logged in as Weights & Biases user: leonwenhao.
weave: View Weave data at https://wandb.ai/leonwenhao-dolores-research/rlm-distiller/weave
weave: https://wandb.ai/leonwenhao-dolores-research/rlm-distiller/r/call/019ca791-fc2a-7e0f-b5e8-bfebf5f2544a
Weave initialized successfully
Result: 84
Trace test complete - check W&B dashboard
```
No errors. Trace published successfully.

## Priority 2: Upload 150-Trace Dataset — Status: COMPLETE
- [x] Find local trace files (data/orchestration_traces_*.jsonl)
  - `data/orchestration_traces_train.jsonl` — 120 lines, 1.9 MB
  - `data/orchestration_traces_eval.jsonl` — 30 lines, 509 KB
  - `data/orchestration_traces_all.jsonl` — 150 lines, 2.4 MB
- [x] Verify local file sizes — CONFIRMED correct
- [x] Find private key — `~/Desktop/RLM Distiller/private_key.pem` (already chmod 400)
- [x] SCP files to GPU at ubuntu@216.81.248.143:~/rlm-distiller/data/
- [x] SSH in and verify line counts

**Verified on GPU:**
```
    150 /home/ubuntu/rlm-distiller/data/orchestration_traces_all.jsonl
     30 /home/ubuntu/rlm-distiller/data/orchestration_traces_eval.jsonl
    120 /home/ubuntu/rlm-distiller/data/orchestration_traces_train.jsonl
    300 total
```
All correct. Old 39/10/49 files have been replaced with 120/30/150.

## Decisions Made
- No code changes to weave.init() calls were needed — project strings were already correct
- Root cause was missing WANDB_API_KEY env var, now persisted in ~/.bashrc
- Used API key from local ~/.netrc to authenticate GPU

## Blockers / Questions for Operator
1. **W&B Entity:** `leonwenhao-dolores-research` (confirmed via wandb API)
2. **Dashboard URL:** https://wandb.ai/leonwenhao-dolores-research/rlm-distiller/weave — **please verify the test trace appears**
3. **Trace URL:** https://wandb.ai/leonwenhao-dolores-research/rlm-distiller/r/call/019ca791-fc2a-7e0f-b5e8-bfebf5f2544a
4. **SCP succeeded** — 120 train, 30 eval, 150 all confirmed on GPU
5. **No errors encountered** — both priorities completed cleanly

## Context Check
- Tasks completed this session: 2 (Priority 1 + Priority 2)
- Estimated context usage: MEDIUM (large SSH output history)
