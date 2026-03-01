#!/usr/bin/env python3
"""Resume trace generation with incremental writes. No waiting."""

import anthropic
import json
import asyncio
import random
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_traces import (
    MODEL, CATEGORIES, LANGUAGE_WEIGHTS, CODEBASE_SIZES,
    TASKS, AGENT_POOLS,
    build_user_message, build_generation_prompt, validate_trace,
    ALL_TRACES_FILE, TRAIN_FILE, EVAL_FILE,
)

TARGET = 150
MAX_CONCURRENT = 5
# File handle for incremental writes
_outfile = None
_lock = asyncio.Lock()
_count = 0


async def gen_one(client, sem, idx, total, cat, lang, size, task, do_retry):
    global _count
    async with sem:
        user_msg = build_user_message(cat, lang, size, task)
        prompt = build_generation_prompt(cat, lang, size, task, do_retry)
        for attempt in range(3):
            try:
                r = await client.messages.create(
                    model=MODEL, max_tokens=4096, temperature=0.9,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = r.content[0].text
                if validate_trace(content):
                    trace = {"messages": [
                        {"role": "user", "content": user_msg},
                        {"role": "assistant", "content": content},
                    ]}
                    async with _lock:
                        _outfile.write(json.dumps(trace) + "\n")
                        _outfile.flush()
                        _count += 1
                        print(f"  [{_count}/{total}] {cat}, {lang}, {size}")
                    return True
                else:
                    if attempt < 2:
                        continue  # silent retry
            except anthropic.RateLimitError:
                await asyncio.sleep(2 ** (attempt + 1))
            except anthropic.APIError as e:
                print(f"  ERR trace {idx}: {str(e)[:80]}")
                await asyncio.sleep(1)
        return False


async def main():
    global _outfile
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set"); sys.exit(1)

    existing = 0
    if ALL_TRACES_FILE.exists():
        with open(ALL_TRACES_FILE) as f:
            existing = sum(1 for _ in f)
    needed = TARGET - existing
    if needed <= 0:
        print(f"Already have {existing} traces."); return

    print(f"Have {existing}, generating {needed} more -> {TARGET} total")
    print(f"Concurrency: {MAX_CONCURRENT}, Model: {MODEL}\n", flush=True)

    client = anthropic.AsyncAnthropic(api_key=api_key)
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    random.seed(int(time.time()))
    languages = list(LANGUAGE_WEIGHTS.keys())
    lang_weights = list(LANGUAGE_WEIGHTS.values())
    sizes = list(CODEBASE_SIZES.keys())

    scenarios = []
    per_cat = needed // len(CATEGORIES)
    remainder = needed % len(CATEGORIES)
    for i, cat in enumerate(CATEGORIES):
        n = per_cat + (1 if i < remainder else 0)
        tasks = TASKS[cat]
        for j in range(n):
            scenarios.append((
                cat,
                random.choices(languages, weights=lang_weights, k=1)[0],
                random.choice(sizes),
                tasks[j % len(tasks)],
                random.random() < 0.60,
            ))
    random.shuffle(scenarios)

    start = time.time()
    _outfile = open(ALL_TRACES_FILE, "a")

    # Fire all — semaphore throttles to MAX_CONCURRENT
    tasks = [
        gen_one(client, sem, i, needed, *s)
        for i, s in enumerate(scenarios)
    ]
    results = await asyncio.gather(*tasks)
    _outfile.close()

    ok = sum(1 for r in results if r)
    elapsed = time.time() - start
    total_now = existing + ok
    print(f"\nGenerated {ok}/{needed} in {elapsed:.0f}s. Total: {total_now}", flush=True)

    # Re-split
    with open(ALL_TRACES_FILE) as f:
        all_t = [json.loads(l) for l in f]
    random.seed(42)
    random.shuffle(all_t)
    ev = min(30, len(all_t) // 5)
    with open(EVAL_FILE, "w") as f:
        for t in all_t[:ev]: f.write(json.dumps(t) + "\n")
    with open(TRAIN_FILE, "w") as f:
        for t in all_t[ev:]: f.write(json.dumps(t) + "\n")
    print(f"Split: {len(all_t)-ev} train / {ev} eval")


if __name__ == "__main__":
    asyncio.run(main())
