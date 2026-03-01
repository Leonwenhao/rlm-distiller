#!/usr/bin/env python3
"""
Generate synthetic orchestration traces for RLM Distiller fine-tuning.

Produces 150 JSONL traces showing expert root-orchestrator behavior:
thorough exploration, aggressive decomposition, output evaluation,
strategic retry, cross-referencing, and deep synthesis.
"""

import anthropic
import json
import asyncio
import random
import os
import sys
import time
from pathlib import Path
from collections import Counter

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MODEL = "claude-sonnet-4-20250514"
TOTAL_TRACES = 150
TRAIN_COUNT = 120
EVAL_COUNT = 30
MAX_CONCURRENT = 5
OUTPUT_DIR = Path(__file__).resolve().parent
ALL_TRACES_FILE = OUTPUT_DIR / "orchestration_traces_all.jsonl"
TRAIN_FILE = OUTPUT_DIR / "orchestration_traces_train.jsonl"
EVAL_FILE = OUTPUT_DIR / "orchestration_traces_eval.jsonl"

CATEGORIES = [
    "security_audit",
    "bug_detection",
    "performance_analysis",
    "dependency_analysis",
    "refactoring_assessment",
]

LANGUAGE_WEIGHTS = {
    "python": 0.40,
    "javascript": 0.30,
    "go": 0.15,
    "rust": 0.10,
    "java": 0.05,
}

CODEBASE_SIZES = {
    "small": (5, 10),
    "medium": (10, 25),
    "large": (25, 50),
}

AGENT_POOLS = {
    "security_audit": [
        "security_analyzer", "auth_reviewer", "input_validator",
        "crypto_auditor", "config_checker",
    ],
    "bug_detection": [
        "type_checker", "logic_analyzer", "null_safety_checker",
        "concurrency_reviewer", "boundary_checker",
    ],
    "performance_analysis": [
        "memory_profiler", "query_analyzer", "io_profiler",
        "cache_analyzer", "allocation_tracker",
    ],
    "dependency_analysis": [
        "vulnerability_scanner", "version_checker", "license_auditor",
        "dependency_mapper", "update_advisor",
    ],
    "refactoring_assessment": [
        "duplication_detector", "coupling_analyzer", "dead_code_finder",
        "complexity_scorer", "pattern_matcher",
    ],
}

TASKS = {
    "security_audit": [
        "Identify all security vulnerabilities in the authentication and authorization system.",
        "Audit the API endpoints for injection vulnerabilities, broken access control, and data exposure.",
        "Review the session management and credential handling for security weaknesses.",
        "Analyze the input validation and sanitization across all user-facing endpoints.",
        "Assess the CORS configuration, CSP headers, and transport security posture.",
        "Examine the cryptographic implementations for weak algorithms or improper key management.",
        "Audit the file upload handling for path traversal, size limits, and content-type validation.",
        "Review the error handling and logging for information leakage and sensitive data exposure.",
        "Analyze the rate limiting, brute-force protection, and account lockout mechanisms.",
        "Assess the OAuth/SSO integration for token handling, redirect validation, and scope issues.",
    ],
    "bug_detection": [
        "Find all potential null pointer dereferences and unhandled error cases in the codebase.",
        "Identify type mismatches, implicit conversions, and type coercion bugs.",
        "Detect off-by-one errors, boundary condition failures, and range check issues.",
        "Find race conditions, deadlocks, and concurrency bugs in the async/parallel code.",
        "Identify logic errors in the business rule validation and state machine transitions.",
        "Detect memory leaks, dangling references, and resource cleanup issues.",
        "Find error handling bugs: swallowed exceptions, incorrect error propagation, missing cleanup.",
        "Identify data validation bugs where invalid input can corrupt application state.",
        "Detect integer overflow, underflow, and arithmetic edge cases across the codebase.",
        "Find bugs in the caching logic: stale data, cache invalidation failures, key collisions.",
    ],
    "performance_analysis": [
        "Identify N+1 query patterns and inefficient database access across the data layer.",
        "Profile memory usage patterns and find potential memory leaks or excessive allocations.",
        "Analyze I/O operations for blocking calls, missing async patterns, and bottlenecks.",
        "Evaluate caching strategies for miss rates, invalidation issues, and memory overhead.",
        "Find unnecessary object allocations, string concatenations, and data copies in hot paths.",
        "Analyze the request pipeline for middleware overhead and unnecessary processing.",
        "Identify slow algorithms: O(n^2) loops, redundant computations, missing indexes.",
        "Profile the serialization/deserialization paths for performance bottlenecks.",
        "Evaluate connection pooling, resource reuse, and lifecycle management efficiency.",
        "Analyze startup time, lazy loading patterns, and initialization overhead.",
    ],
    "dependency_analysis": [
        "Scan all dependencies for known security vulnerabilities and available patches.",
        "Identify version conflicts, incompatible peer dependencies, and resolution issues.",
        "Audit dependency licenses for compliance with the project's licensing requirements.",
        "Map the dependency graph to find circular dependencies and unnecessary transitive deps.",
        "Identify outdated packages with available major updates and breaking change risks.",
        "Detect unused dependencies that can be safely removed to reduce bundle size.",
        "Evaluate dependency health: maintenance status, community activity, bus factor.",
        "Find dependencies that duplicate functionality already available in the standard library.",
        "Assess the supply chain risk: typosquatting, maintainer changes, unpinned versions.",
        "Analyze the build dependency tree for optimization opportunities and faster builds.",
    ],
    "refactoring_assessment": [
        "Identify code duplication across modules and suggest extraction opportunities.",
        "Analyze coupling between components and identify tight coupling that limits testability.",
        "Find dead code: unreachable branches, unused exports, obsolete feature flags.",
        "Detect circular import chains and suggest dependency inversion strategies.",
        "Identify god classes/modules that violate single responsibility and need decomposition.",
        "Assess the test coverage gaps and identify untestable code that needs restructuring.",
        "Find inconsistent naming conventions, API styles, and coding patterns across the codebase.",
        "Evaluate the error handling patterns for consistency and identify anti-patterns.",
        "Identify opportunities to extract shared utilities and reduce cross-cutting concerns.",
        "Analyze the module boundaries and suggest a cleaner architecture decomposition.",
    ],
}

# ---------------------------------------------------------------------------
# File tree templates per language
# ---------------------------------------------------------------------------
PYTHON_DIRS = ["src", "src/api", "src/models", "src/utils", "src/services", "tests", "tests/unit", "tests/integration", "config"]
PYTHON_FILES = [
    "main.py", "app.py", "config.py", "settings.py", "database.py",
    "auth.py", "middleware.py", "models.py", "schemas.py", "validators.py",
    "routes.py", "views.py", "controllers.py", "handlers.py", "serializers.py",
    "utils.py", "helpers.py", "exceptions.py", "constants.py", "types.py",
    "cache.py", "queue.py", "tasks.py", "signals.py", "permissions.py",
    "user_service.py", "auth_service.py", "email_service.py", "payment_service.py",
    "user_model.py", "order_model.py", "product_model.py", "session_model.py",
    "test_auth.py", "test_api.py", "test_models.py", "test_services.py",
    "conftest.py", "__init__.py", "wsgi.py", "asgi.py", "celery_app.py",
    "crypto.py", "tokens.py", "rate_limiter.py", "logging_config.py",
]

JS_DIRS = ["src", "src/routes", "src/middleware", "src/models", "src/services", "src/utils", "src/controllers", "lib", "tests", "tests/unit", "config"]
JS_FILES = [
    "index.ts", "app.ts", "server.ts", "config.ts", "database.ts",
    "auth.controller.ts", "user.controller.ts", "order.controller.ts",
    "auth.service.ts", "user.service.ts", "email.service.ts", "payment.service.ts",
    "auth.middleware.ts", "error.middleware.ts", "validation.middleware.ts", "cors.middleware.ts",
    "user.model.ts", "order.model.ts", "product.model.ts", "session.model.ts",
    "auth.routes.ts", "user.routes.ts", "api.routes.ts", "health.routes.ts",
    "validators.ts", "helpers.ts", "logger.ts", "constants.ts", "types.ts",
    "cache.ts", "queue.ts", "crypto.ts", "rate-limiter.ts",
    "auth.test.ts", "user.test.ts", "api.test.ts", "integration.test.ts",
    "jest.config.ts", "tsconfig.json", "package.json",
]

GO_DIRS = ["cmd", "cmd/server", "internal", "internal/handler", "internal/service", "internal/repository", "internal/middleware", "internal/model", "pkg", "pkg/auth", "pkg/crypto", "api", "config"]
GO_FILES = [
    "main.go", "server.go", "router.go", "config.go",
    "handler.go", "auth_handler.go", "user_handler.go", "health_handler.go",
    "service.go", "auth_service.go", "user_service.go", "email_service.go",
    "repository.go", "user_repository.go", "order_repository.go",
    "middleware.go", "auth_middleware.go", "logging_middleware.go", "rate_limiter.go",
    "model.go", "user.go", "order.go", "session.go",
    "auth.go", "jwt.go", "crypto.go", "validator.go",
    "handler_test.go", "service_test.go", "repository_test.go", "auth_test.go",
    "go.mod", "go.sum", "Makefile",
]

RUST_DIRS = ["src", "src/handlers", "src/models", "src/services", "src/middleware", "src/utils", "tests", "benches"]
RUST_FILES = [
    "main.rs", "lib.rs", "config.rs", "db.rs", "errors.rs",
    "auth.rs", "user.rs", "session.rs", "crypto.rs",
    "handlers.rs", "auth_handler.rs", "user_handler.rs", "health_handler.rs",
    "models.rs", "user_model.rs", "order_model.rs",
    "middleware.rs", "auth_middleware.rs", "rate_limiter.rs",
    "services.rs", "auth_service.rs", "user_service.rs",
    "utils.rs", "validators.rs", "types.rs",
    "test_auth.rs", "test_handlers.rs", "test_integration.rs",
    "Cargo.toml", "Cargo.lock",
]

JAVA_DIRS = [
    "src/main/java/com/example", "src/main/java/com/example/controller",
    "src/main/java/com/example/service", "src/main/java/com/example/repository",
    "src/main/java/com/example/model", "src/main/java/com/example/config",
    "src/main/java/com/example/security", "src/main/java/com/example/dto",
    "src/main/java/com/example/exception", "src/main/java/com/example/util",
    "src/test/java/com/example", "src/main/resources",
]
JAVA_FILES = [
    "Application.java", "SecurityConfig.java", "WebConfig.java", "DatabaseConfig.java",
    "AuthController.java", "UserController.java", "OrderController.java", "HealthController.java",
    "AuthService.java", "UserService.java", "EmailService.java", "PaymentService.java",
    "UserRepository.java", "OrderRepository.java", "SessionRepository.java",
    "User.java", "Order.java", "Session.java", "Role.java",
    "JwtTokenProvider.java", "AuthenticationFilter.java", "RateLimiter.java",
    "UserDto.java", "LoginRequest.java", "SignupRequest.java",
    "GlobalExceptionHandler.java", "ResourceNotFoundException.java",
    "ValidationUtil.java", "CryptoUtil.java",
    "AuthServiceTest.java", "UserControllerTest.java", "IntegrationTest.java",
    "application.yml", "pom.xml",
]

LANG_ASSETS = {
    "python": (PYTHON_DIRS, PYTHON_FILES),
    "javascript": (JS_DIRS, JS_FILES),
    "go": (GO_DIRS, GO_FILES),
    "rust": (RUST_DIRS, RUST_FILES),
    "java": (JAVA_DIRS, JAVA_FILES),
}


def generate_file_tree(language: str, size: str) -> str:
    dirs, files = LANG_ASSETS[language]
    min_files, max_files = CODEBASE_SIZES[size]
    num_files = random.randint(min_files, max_files)
    chosen = random.sample(files, min(num_files, len(files)))
    tree_entries = []
    for f in chosen:
        d = random.choice(dirs)
        lines = random.randint(40, 500)
        tree_entries.append((d, f, lines))
    tree_entries.sort(key=lambda x: (x[0], x[1]))
    lines_out = []
    current_dir = None
    for d, f, lc in tree_entries:
        if d != current_dir:
            current_dir = d
            lines_out.append(f"{d}/")
        lines_out.append(f"  {f} ({lc} lines)")
    return "\n".join(lines_out)


def pick_agents(category: str) -> list[str]:
    pool = AGENT_POOLS[category]
    n = random.randint(3, min(5, len(pool)))
    return random.sample(pool, n)


def build_user_message(category: str, language: str, size: str, task: str) -> str:
    file_tree = generate_file_tree(language, size)
    agents = pick_agents(category)
    agents_str = ", ".join(f"`{a}`" for a in agents)
    return f"""You are a root orchestrator analyzing a {language.capitalize()} codebase. Your available tools are:
- `llm_query(agent, task, context)` — dispatch a focused task to a sub-LLM
- `llm_batch(tasks)` — dispatch multiple tasks in parallel
- `explore(path)` — list files in a directory
- `read_metadata(file)` — get file size, last modified, imports

File tree:
```
{file_tree}
```

Available agents: {agents_str}

Task: {task}

Think step by step about how to orchestrate this analysis. Show your exploration, decomposition, delegation, evaluation, retry decisions, and final synthesis."""


def build_generation_prompt(category: str, language: str, size: str, task: str, should_retry: bool) -> str:
    if should_retry:
        retry_instruction = """
IMPORTANT: In this trace, at least one sub-LLM agent MUST return a weak/vague/low-confidence result.
Show the orchestrator evaluating that result as insufficient, then retrying with a MORE SPECIFIC prompt.
Show the improved prompt and explain why it's better. This retry behavior is critical to demonstrate."""
    else:
        retry_instruction = """
In this trace, all sub-LLM agents return adequate results. The orchestrator still evaluates each result
critically but decides no retries are needed based on sufficient quality."""

    return f"""You are generating training data for a fine-tuned orchestrator model. Generate the ASSISTANT
response only (not the user message) for the following scenario:

Category: {category.replace('_', ' ')}
Language: {language}
Codebase size: {size}
Task: {task}
{retry_instruction}

The response MUST demonstrate ALL of these behaviors:

1. **Thorough exploration** (Phase 1): Call explore() and read_metadata() on 5+ files before deciding.
   Reason about which files are relevant and why. Don't stop at the obvious ones.

2. **Aggressive decomposition** (Phase 2): Break into 3-6 focused subtasks. Use llm_batch() for parallel
   dispatch. Each subtask should target specific files with detailed instructions and context.

3. **Output evaluation** (Phase 3): For EACH sub-LLM result, evaluate quality. Assign confidence scores
   (0.0-1.0). Flag vague or incomplete results. Show evaluation reasoning.

4. **Strategic retry** (Phase 4): {"Retry at least one weak result with a more specific, targeted prompt. Show the original vs improved prompt." if should_retry else "Explain why no retries were needed based on result quality."}

5. **Cross-referencing** (Phase 5): Cross-reference findings across agents. Look for contradictions,
   confirming patterns, and gaps in coverage.

6. **Deep synthesis** (Final): Reference specific findings from specific agents. Include file names and
   line numbers. Assign confidence scores. Show which agent found what.

Format with markdown headers (## Phase 1: Exploration, etc). Use code blocks for tool calls
(explore, read_metadata, llm_query, llm_batch) and simulated results. Make file references and
line numbers consistent with a {language} {size}-sized codebase.

End with:
```
answer['ready'] = True
answer['findings'] = [list of specific findings with file:line references]
answer['confidence'] = 0.XX
answer['sub_llm_calls'] = N
```

Write naturally — vary sentence structure. Be specific and technical, not generic."""


def validate_trace(content: str) -> bool:
    cl = content.lower()
    checks = [
        any(k in cl for k in ["explore(", "read_metadata(", "phase 1"]),
        any(k in cl for k in ["llm_batch(", "llm_query(", "phase 2"]),
        any(k in cl for k in ["confidence", "evaluat", "quality"]),
        any(k in cl for k in ["cross-referenc", "contradict", "pattern", "phase 5"]),
        any(k in cl for k in ["answer[", "findings", "synthesis"]),
        len(content) > 1500,
    ]
    return all(checks)


async def generate_one_trace(
    client: anthropic.AsyncAnthropic,
    semaphore: asyncio.Semaphore,
    index: int,
    category: str,
    language: str,
    size: str,
    task: str,
    should_retry: bool,
) -> dict | None:
    async with semaphore:
        user_message = build_user_message(category, language, size, task)
        gen_prompt = build_generation_prompt(category, language, size, task, should_retry)

        for attempt in range(3):
            try:
                response = await client.messages.create(
                    model=MODEL,
                    max_tokens=4096,
                    temperature=0.9,
                    messages=[{"role": "user", "content": gen_prompt}],
                )
                assistant_content = response.content[0].text

                if validate_trace(assistant_content):
                    trace = {
                        "messages": [
                            {"role": "user", "content": user_message},
                            {"role": "assistant", "content": assistant_content},
                        ]
                    }
                    label = f"{category}, {language}, {size}"
                    print(f"Generated trace {index + 1}/{TOTAL_TRACES} ({label})")
                    return trace
                else:
                    print(f"  Trace {index + 1} attempt {attempt + 1} failed validation, retrying...")
            except anthropic.RateLimitError:
                wait = 2 ** (attempt + 2)
                print(f"  Rate limited on trace {index + 1}, waiting {wait}s...")
                await asyncio.sleep(wait)
            except anthropic.APIError as e:
                print(f"  API error on trace {index + 1}: {e}, attempt {attempt + 1}")
                await asyncio.sleep(2)

        print(f"  WARNING: Failed to generate valid trace {index + 1} after 3 attempts")
        return None


def build_scenario_list() -> list[dict]:
    scenarios = []
    languages = list(LANGUAGE_WEIGHTS.keys())
    lang_weights = list(LANGUAGE_WEIGHTS.values())
    sizes = list(CODEBASE_SIZES.keys())

    for cat in CATEGORIES:
        tasks = TASKS[cat]
        for i in range(30):
            lang = random.choices(languages, weights=lang_weights, k=1)[0]
            size = random.choice(sizes)
            task = tasks[i % len(tasks)]
            should_retry = random.random() < 0.60
            scenarios.append({
                "category": cat,
                "language": lang,
                "size": size,
                "task": task,
                "should_retry": should_retry,
            })

    random.shuffle(scenarios)
    return scenarios


async def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    client = anthropic.AsyncAnthropic(api_key=api_key)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    random.seed(42)
    scenarios = build_scenario_list()

    print(f"Generating {TOTAL_TRACES} orchestration traces...")
    print(f"  Model: {MODEL}")
    print(f"  Concurrency: {MAX_CONCURRENT}")
    print(f"  Output: {ALL_TRACES_FILE}")
    print()

    stats = Counter()
    start_time = time.time()
    traces_all = []

    with open(ALL_TRACES_FILE, "w") as f:
        batch_size = MAX_CONCURRENT * 3
        for batch_start in range(0, len(scenarios), batch_size):
            batch_end = min(batch_start + batch_size, len(scenarios))
            batch = scenarios[batch_start:batch_end]

            coros = [
                generate_one_trace(
                    client, semaphore,
                    batch_start + i,
                    s["category"], s["language"], s["size"],
                    s["task"], s["should_retry"],
                )
                for i, s in enumerate(batch)
            ]

            results = await asyncio.gather(*coros)

            for i, result in enumerate(results):
                if result is not None:
                    s = batch[i]
                    f.write(json.dumps(result) + "\n")
                    f.flush()
                    traces_all.append((result, s["category"]))
                    stats[s["category"]] += 1
                    stats[f"lang_{s['language']}"] += 1
                    stats[f"size_{s['size']}"] += 1

    elapsed = time.time() - start_time
    total_generated = len(traces_all)

    print(f"\n{'='*60}")
    print(f"Generation complete in {elapsed:.0f}s")
    print(f"Total traces: {total_generated}/{TOTAL_TRACES}")
    print(f"\nPer category:")
    for cat in CATEGORIES:
        print(f"  {cat}: {stats[cat]}")
    print(f"\nPer language:")
    for lang in LANGUAGE_WEIGHTS:
        print(f"  {lang}: {stats[f'lang_{lang}']}")
    print(f"\nPer size:")
    for size in CODEBASE_SIZES:
        print(f"  {size}: {stats[f'size_{size}']}")

    # Stratified train/eval split
    by_category = {cat: [] for cat in CATEGORIES}
    for trace, cat in traces_all:
        by_category[cat].append(trace)

    train_traces = []
    eval_traces = []
    eval_per_cat = EVAL_COUNT // len(CATEGORIES)

    for cat in CATEGORIES:
        cat_traces = by_category[cat]
        random.shuffle(cat_traces)
        eval_traces.extend(cat_traces[:eval_per_cat])
        train_traces.extend(cat_traces[eval_per_cat:])

    with open(TRAIN_FILE, "w") as f:
        for trace in train_traces:
            f.write(json.dumps(trace) + "\n")

    with open(EVAL_FILE, "w") as f:
        for trace in eval_traces:
            f.write(json.dumps(trace) + "\n")

    print(f"\nSplit: {len(train_traces)} train, {len(eval_traces)} eval")
    print(f"Train: {TRAIN_FILE}")
    print(f"Eval:  {EVAL_FILE}")

    # Verify 3 samples
    print(f"\n{'='*60}")
    print("Verification: 3 random traces\n")
    sample = random.sample(traces_all, min(3, len(traces_all)))
    for i, (trace, cat) in enumerate(sample):
        asst = trace["messages"][1]["content"]
        print(f"--- Sample {i+1} ({cat}) ---")
        print(f"  User msg:  {len(trace['messages'][0]['content'])} chars")
        print(f"  Asst msg:  {len(asst)} chars")
        print(f"  explore():       {'explore(' in asst}")
        print(f"  read_metadata(): {'read_metadata(' in asst}")
        print(f"  llm_batch():     {'llm_batch(' in asst}")
        print(f"  llm_query():     {'llm_query(' in asst}")
        print(f"  confidence:      {'confidence' in asst.lower()}")
        has_answer = "answer[" in asst
        print(f"  answer[]:        {has_answer}")
        print(f"  Preview: {asst[:200]}...")
        print()

    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
