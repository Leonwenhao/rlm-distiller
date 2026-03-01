# RLM Distiller — Autonomous Behavioral Fine-Tuning with Self-Improvement

**Mistral Worldwide Hackathon SF · Track 02 (Fine-Tuning by W&B)**  
**Dolores Research**

## What This Is

RLM Distiller fine-tunes Mistral Small 24B to perform multi-agent orchestration by distilling behavioral patterns from Claude Opus. Using QLoRA on a single A100 GPU, it runs an autonomous self-improvement loop: evaluate → diagnose weaknesses → generate targeted training data → retrain → repeat.

7 iterations completed overnight in 7.5 hours. 875 W&B Weave traces. Zero human intervention. Retry intelligence +29%, synthesis quality +22%, overall orchestration +17%.

## Deploy to Vercel

### Option A: GitHub + Vercel (recommended)
```bash
git init
git add .
git commit -m "RLM Distiller demo dashboard"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/rlm-distiller.git
git push -u origin main
```
Then go to vercel.com/new, import the repo, click Deploy.

### Option B: Vercel CLI
```bash
npm i -g vercel
vercel --prod
```

## Local Dev
```bash
npm install
npm run dev
```

## Key Links

- **W&B Project:** https://wandb.ai/leonwenhao-dolores-research/rlm-distiller
- **Weave Traces:** https://wandb.ai/leonwenhao-dolores-research/rlm-distiller/weave
- **DeepRepo (origin of thesis):** https://github.com/Leonwenhao/deeprepo

## Stack

Mistral Small 24B · QLoRA (PEFT + TRL) · vLLM · W&B Weave · Prime Intellect A100 · React + Recharts
