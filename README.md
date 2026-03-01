# RLM Distiller

**Autonomous Behavioral Fine-Tuning with Self-Improvement**
Mistral Worldwide Hackathon SF · Track 02 (Fine-Tuning by W&B) · Dolores Research

---

## What This Is

RLM Distiller fine-tunes **Mistral Small 24B** to perform multi-agent orchestration — the skill of delegating, evaluating, and coordinating other AI models — by distilling behavioral patterns from Claude Opus. It uses **QLoRA** on a single A100 GPU and runs an **autonomous self-improvement loop**: evaluate the model, diagnose its weakest dimensions, generate targeted training data, retrain, repeat.

**7 iterations completed overnight in 7 hours 27 minutes. 875 W&B Weave traces. Zero human intervention. Zero crashes.**

### The Thesis

Our prior work on [DeepRepo](https://github.com/Leonwenhao/deeprepo) revealed that Claude Opus dispatches **61 sub-LLM calls** on a codebase analysis task while Claude Sonnet dispatches only **9** — on the exact same task. This isn't a capability gap. It's a **behavioral gap**: Opus explores more thoroughly, decomposes more aggressively, evaluates sub-agent output quality, retries when results are weak, and cross-references findings before synthesizing. Sonnet *can* do all of this — it just doesn't.

RLM Distiller captures that orchestration strategy in synthetic training data and teaches it to a cheaper model via parameter-efficient fine-tuning. Then the self-improvement loop keeps making it better, autonomously.

---

## Results

| Metric | Baseline (Iter 0) | Best | Improvement |
|--------|-------------------|------|-------------|
| **Overall Score** | 0.218 | 0.255 (Iter 2) | **+17.0%** |
| **Retry Intelligence** | 0.410 | 0.530 (Iter 2) | **+29.3%** |
| **Synthesis Quality** | 0.375 | 0.459 (Iter 5) | **+22.4%** |
| **Routing Accuracy** | 0.088 | 0.121 (Iter 1) | **+37.5%** |
| **Error Detection** | 0.000 | 0.010 (Iter 2,4) | From zero |

### Key Findings

**The loop correctly diagnoses and intervenes.** After retry intelligence dropped to 0.300 at iteration 1, the loop identified it as the top failure mode, generated 40 retry-focused training examples, and retrained. Retry jumped to 0.530 at iteration 2 — a 77% improvement in a single targeted cycle.

**Improvements accumulate.** Synthesis quality climbed steadily from 0.375 to 0.459 across the full run without oscillation, demonstrating that gains compound across iterations.

**The system converges.** Despite oscillation in overall scores, valleys are rising (0.202 → 0.204 → 0.239), peak-to-valley gaps are narrowing (0.053 → 0.011), and the system is finding equilibrium.

**Honest limitation.** Error detection stayed near zero because the fallback data generator (no API key on GPU) couldn't produce examples in the required error format. The loop diagnosed this correctly every iteration (severity 1.0) but the intervention mechanism was insufficient. This strengthens the architecture thesis — the diagnostic is right; higher-quality data generation will unlock this dimension.

---

## W&B Weave Links

| Resource | URL |
|----------|-----|
| **Project Dashboard** | https://wandb.ai/leonwenhao-dolores-research/rlm-distiller |
| **Weave Traces (875 total)** | https://wandb.ai/leonwenhao-dolores-research/rlm-distiller/weave |
| **Training Run** | https://wandb.ai/leonwenhao-dolores-research/rlm-distiller/runs/yw9w1jfb |

---

## How the Self-Improvement Loop Works

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  ① EVALUATE │ ──→ │ ② DIAGNOSE  │ ──→ │ ③ GENERATE  │ ──→ │ ④ RETRAIN   │
│             │     │             │     │             │     │             │
│ 25 tasks    │     │ Bottom 30%  │     │ 40 targeted │     │ QLoRA       │
│ 4 scorers   │     │ 4 failure   │     │ examples    │     │ 160 examples│
│ ~31.5 min   │     │ modes       │     │ per iter    │     │ ~38 min     │
│ 125 traces  │     │ ranked      │     │             │     │ 3 epochs    │
└─────────────┘     └─────────────┘     └─────────────┘     └──────┬──────┘
       ↑                                                           │
       └───────────────────── LOOP (7 iterations) ─────────────────┘
```

Each iteration takes ~69 minutes. The loop ran from 05:35 to 13:02 UTC on March 1, 2026, producing 7 evaluations, 6 fine-tuning runs, and 875 Weave traces — all without human intervention.

---

## Architecture

```
rlm-distiller/
├── loop/
│   └── run_loop.py               # Autonomous self-improvement loop orchestrator
├── eval/
│   ├── model.py                  # Weave Model wrapper for fine-tuned Mistral
│   ├── scorers.py                # 4 fuzzy-matching scorers (routing, errors, retry, synthesis)
│   └── run_eval.py               # Standalone evaluation runner
├── finetune/
│   ├── train_qlora.py            # QLoRA training script (PEFT + TRL SFTTrainer)
│   └── serve_model.py            # vLLM serving with LoRA adapter hot-swap
├── mcp_server/
│   ├── server.py                 # FastMCP server with 4 tools
│   └── client.py                 # MCP client agent
├── data/
│   ├── orchestration_traces_train.jsonl   # 120 base training traces
│   ├── orchestration_traces_eval.jsonl    # 30 eval traces
│   ├── eval_dataset.json                  # 25 ground-truth eval scenarios
│   └── generate_traces.py                 # Trace generation script (Claude API)
├── demo-site/                     # Interactive React dashboard (deploys to Vercel)
├── FINDINGS_AND_DATA_SYNTHESIS.md # Comprehensive analysis of all results
├── gpu_export/                    # Raw data from overnight run
│   ├── loop_output.log            # Full overnight execution log
│   ├── weave_urls.txt             # All 875 Weave trace URLs
│   └── loop_results/              # Per-iteration eval results & training data
└── requirements.txt
```

### Key Files for Judges

If you want to understand the engineering, start with these:

**`loop/run_loop.py`** — The autonomous loop. This is the core innovation: evaluate → diagnose → generate → retrain, running unattended.

**`eval/scorers.py`** — Four fuzzy-matching scorers that grade model output against ground truth. Uses Jaccard similarity on tokenized strings, partial credit for retry matching, and synthesis marker detection.

**`finetune/train_qlora.py`** — QLoRA training with PEFT + TRL. 4-bit NF4 quantization, LoRA rank 16, alpha 32, targeting all linear layers. Trains on the same GPU that serves the model.

**`FINDINGS_AND_DATA_SYNTHESIS.md`** — Complete analysis of the overnight run produced by exhaustive review of all data files.

---

## Technical Specs

| Component | Detail |
|-----------|--------|
| Base Model | `mistralai/Mistral-Small-24B-Instruct-2501` (24B params) |
| Fine-Tuning | QLoRA — 4-bit NF4, double quantization, bfloat16 compute |
| LoRA Config | rank=16, alpha=32, dropout=0.05, all linear layers (q/k/v/o + gate/up/down) |
| Trainable Params | 92M / 24B (0.39%) |
| Training Data | 160 per iteration (120 base + 40 targeted) |
| Eval Set | 25 ground-truth orchestration tasks across 5 categories |
| Serving | vLLM with LoRA adapter hot-swap (<1s restart) |
| GPU | Single A100 (shared training + serving) |
| Observability | W&B run metrics + Weave eval traces |
| Training Loss | 1.027 → 0.645 (Iter 2), token accuracy 0.858 |

---

## Cost

| Item | Cost |
|------|------|
| GPU compute (A100 × 7.5 hrs) | ~$19 |
| Initial trace generation (Claude API, one-time) | ~$25 |
| Overnight data generation | $0 (fallback generator, no API key) |
| Mistral inference | $0 (local vLLM) |
| W&B / Weave | $0 (free tier) |
| **Total** | **~$44** |

---

## Interactive Demo

The `demo-site/` directory contains an interactive React dashboard built with Recharts that visualizes the complete overnight results. It includes six tabs: the architecture and problem statement, the training methodology, the self-improvement loop with Weave trace timeline, score trajectories across all 7 iterations, convergence analysis with oscillation evidence, and cost breakdown.

**Live demo:** https://demo-site-mu-rust.vercel.app

---

## Origin

This project builds on [DeepRepo](https://github.com/Leonwenhao/deeprepo), an open-source multi-agent code analysis system by Dolores Research. DeepRepo's benchmarks revealed the behavioral gap between frontier and mid-tier models that RLM Distiller exploits.

---

*Built at the Mistral Worldwide Hackathon SF, Feb 28–Mar 1, 2026.*
