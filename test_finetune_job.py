#!/usr/bin/env python3
"""
test_finetune_job.py — Submit a test fine-tuning job to Mistral La Plateforme
to measure wall-clock turnaround time.

Usage:
    export MISTRAL_API_KEY="your_key"
    export WANDB_API_KEY="your_key"    # optional, for W&B integration
    python test_finetune_job.py

This submits ~10 orchestration traces as a minimal fine-tuning job.
The ONLY thing that matters here is: how long does it take from submission to SUCCEEDED?
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Verify API key is set ──────────────────────────────────────────────
if not os.environ.get("MISTRAL_API_KEY"):
    print("ERROR: Set MISTRAL_API_KEY environment variable first.")
    sys.exit(1)

from mistralai import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

# ── Generate 10 synthetic orchestration traces ─────────────────────────
# These are simplified but structurally correct — they capture the key
# behavioral patterns we want the model to learn: exploration, decomposition,
# delegation via llm_query/llm_batch, output evaluation, retry logic, synthesis.

TRACES = [
    # Trace 1: Security audit with retry
    {
        "messages": [
            {
                "role": "user",
                "content": (
                    "You are a root orchestrator analyzing a Python codebase. "
                    "Your available tools are:\n"
                    "- `llm_query(agent, task, context)` — dispatch a focused task to a sub-LLM\n"
                    "- `llm_batch(tasks)` — dispatch multiple tasks in parallel\n"
                    "- `explore(path)` — list files in a directory\n"
                    "- `read_metadata(file)` — get file size, last modified, imports\n\n"
                    "File tree:\n```\nsrc/\n├── auth.py (142 lines)\n├── models.py (89 lines)\n"
                    "├── utils.py (67 lines)\n├── api/\n│   ├── routes.py (203 lines)\n"
                    "│   └── middleware.py (54 lines)\n└── tests/\n    └── test_auth.py (91 lines)\n```\n\n"
                    "Task: Identify all security vulnerabilities in this authentication system.\n\n"
                    "Think step by step about how to orchestrate this analysis."
                )
            },
            {
                "role": "assistant",
                "content": (
                    "I'll systematically analyze this codebase for security vulnerabilities "
                    "using a multi-phase orchestration approach.\n\n"
                    "## Phase 1: Exploration\n\n"
                    "Before delegating anything, I need to understand what I'm working with.\n\n"
                    "```python\nexplore('src/')\nread_metadata('src/auth.py')\n"
                    "read_metadata('src/api/middleware.py')\nread_metadata('src/api/routes.py')\n"
                    "read_metadata('src/utils.py')\nread_metadata('src/models.py')\n```\n\n"
                    "The auth system spans auth.py (primary logic), middleware.py (request-level checks), "
                    "routes.py (endpoint protection), and possibly utils.py (helper functions). "
                    "models.py likely defines the User model with password storage.\n\n"
                    "## Phase 2: Decomposition & Parallel Delegation\n\n"
                    "I'll dispatch 5 focused analysis tasks in parallel:\n\n"
                    "```python\nresults = llm_batch([\n"
                    "    {'agent': 'security_analyzer', 'task': 'Analyze auth.py for: authentication bypass, "
                    "weak password handling, session management flaws, credential storage issues, timing attacks', "
                    "'context': 'auth.py: 142 lines, imports: bcrypt, jwt, datetime, models'},\n"
                    "    {'agent': 'security_analyzer', 'task': 'Analyze middleware.py for: authorization bypass, "
                    "missing auth checks on routes, CORS misconfiguration, header injection', "
                    "'context': 'middleware.py: 54 lines, imports: functools, jwt'},\n"
                    "    {'agent': 'security_analyzer', 'task': 'Analyze routes.py for: unprotected endpoints, "
                    "missing rate limiting, input validation gaps, SQL/NoSQL injection, SSRF', "
                    "'context': 'routes.py: 203 lines, imports: flask, auth, models, utils'},\n"
                    "    {'agent': 'security_analyzer', 'task': 'Analyze utils.py for: unsafe deserialization, "
                    "path traversal in file operations, insecure random number generation', "
                    "'context': 'utils.py: 67 lines, imports: os, hashlib, json'},\n"
                    "    {'agent': 'code_reviewer', 'task': 'Analyze test_auth.py for security test coverage gaps: "
                    "what attack vectors are NOT tested?', "
                    "'context': 'test_auth.py: 91 lines, tests for: login, register, token_refresh'}\n"
                    "])\n```\n\n"
                    "## Phase 3: Output Evaluation & Selective Retry\n\n"
                    "```python\nfor i, result in enumerate(results):\n"
                    "    if result['confidence'] < 0.7 or len(result['findings']) < 2:\n"
                    "        # Sub-LLM was too superficial — retry with more specific guidance\n"
                    "        results[i] = llm_query(\n"
                    "            'security_analyzer',\n"
                    "            f'Your previous analysis was too surface-level. '  \n"
                    "            f'Re-analyze with specific focus on: {result.get(\"uncertain_areas\", \"all areas\")}. '\n"
                    "            f'I need specific line-level findings, not general observations.',\n"
                    "            result['context'] + '\\nPrevious findings: ' + json.dumps(result['findings'])\n"
                    "        )\n```\n\n"
                    "The routes.py analyzer returned low confidence — retrying with emphasis on the 203-line file's "
                    "complexity and need for thorough endpoint enumeration.\n\n"
                    "## Phase 4: Cross-Reference\n\n"
                    "```python\ncross_check = llm_query(\n"
                    "    'logic_analyzer',\n"
                    "    'Cross-reference these security findings. Identify: (1) contradictions between reports, "
                    "(2) vulnerabilities that span multiple files, (3) attack chains combining multiple weaknesses',\n"
                    "    json.dumps([r['findings'] for r in results])\n"
                    ")\n```\n\n"
                    "## Final Synthesis\n\n"
                    "Combining all sub-agent reports with cross-reference analysis:\n\n"
                    "1. **CRITICAL** — JWT tokens lack expiration validation in auth.py (line 67). middleware.py "
                    "checks token signature but not expiry (line 23). Attack chain: stolen token works forever.\n"
                    "2. **HIGH** — 3 unprotected endpoints in routes.py: /api/debug (line 145), /api/export (line 167), "
                    "/api/admin/logs (line 189). No middleware.auth_required decorator.\n"
                    "3. **HIGH** — utils.py uses hashlib.md5 for generating password reset tokens (line 34). "
                    "Predictable tokens enable account takeover.\n"
                    "4. **MEDIUM** — bcrypt cost factor is 4 in auth.py (line 12), should be 12+.\n"
                    "5. **LOW** — test_auth.py has zero tests for SQL injection on login, no tests for rate limiting.\n\n"
                    "```python\nanswer['ready'] = True\nanswer['vulnerabilities'] = [\n"
                    "    {'severity': 'CRITICAL', 'file': 'auth.py', 'line': 67, 'type': 'jwt_no_expiry'},\n"
                    "    {'severity': 'HIGH', 'file': 'routes.py', 'lines': [145, 167, 189], 'type': 'unprotected_endpoints'},\n"
                    "    {'severity': 'HIGH', 'file': 'utils.py', 'line': 34, 'type': 'weak_token_generation'},\n"
                    "    {'severity': 'MEDIUM', 'file': 'auth.py', 'line': 12, 'type': 'weak_bcrypt_cost'},\n"
                    "    {'severity': 'LOW', 'file': 'test_auth.py', 'type': 'missing_security_tests'}\n"
                    "]\nanswer['confidence'] = 0.88\nanswer['sub_llm_calls'] = 7  # 5 initial + 1 retry + 1 cross-ref\n```"
                )
            }
        ]
    },

    # Trace 2: Performance analysis — thorough exploration pattern
    {
        "messages": [
            {
                "role": "user",
                "content": (
                    "You are a root orchestrator analyzing a Node.js Express application. "
                    "Your available tools are:\n"
                    "- `llm_query(agent, task, context)` — dispatch a focused task to a sub-LLM\n"
                    "- `llm_batch(tasks)` — dispatch multiple tasks in parallel\n"
                    "- `explore(path)` — list files in a directory\n"
                    "- `read_metadata(file)` — get file size, last modified, imports\n\n"
                    "File tree:\n```\nserver/\n├── index.js (45 lines)\n├── config.js (28 lines)\n"
                    "├── routes/\n│   ├── users.js (156 lines)\n│   └── products.js (234 lines)\n"
                    "├── models/\n│   ├── User.js (67 lines)\n│   └── Product.js (89 lines)\n"
                    "├── middleware/\n│   └── cache.js (43 lines)\n"
                    "└── utils/\n    └── db.js (78 lines)\n```\n\n"
                    "Task: Find all performance bottlenecks in this application.\n\n"
                    "Think step by step about how to orchestrate this analysis."
                )
            },
            {
                "role": "assistant",
                "content": (
                    "I'll systematically identify performance bottlenecks through structured "
                    "delegation and thorough evaluation.\n\n"
                    "## Phase 1: Thorough Exploration\n\n"
                    "Performance issues often hide in the connections between files, not individual files. "
                    "I need to map the dependency graph before delegating.\n\n"
                    "```python\nexplore('server/')\nfor f in ['index.js', 'config.js', 'routes/users.js', "
                    "'routes/products.js', 'models/User.js', 'models/Product.js', "
                    "'middleware/cache.js', 'utils/db.js']:\n"
                    "    read_metadata(f'server/{f}')\n```\n\n"
                    "Key observations from metadata: db.js imports 'mongoose' and has no connection pooling config. "
                    "products.js is the largest route file at 234 lines — likely complex queries. "
                    "cache.js exists but is only imported by users.js, not products.js.\n\n"
                    "## Phase 2: Decomposition\n\n"
                    "I'll attack this from 4 angles simultaneously:\n\n"
                    "```python\nresults = llm_batch([\n"
                    "    {'agent': 'perf_analyzer', 'task': 'Analyze db.js for: missing connection pooling, "
                    "missing indexes on queries, connection leak patterns, no query timeout configuration', "
                    "'context': 'db.js: 78 lines, imports: mongoose'},\n"
                    "    {'agent': 'perf_analyzer', 'task': 'Analyze products.js for: N+1 query patterns, "
                    "missing pagination, unbounded result sets, synchronous operations that should be async, "
                    "missing caching for expensive queries', "
                    "'context': 'products.js: 234 lines, imports: Product model, db'},\n"
                    "    {'agent': 'perf_analyzer', 'task': 'Analyze users.js for: N+1 queries, "
                    "redundant database calls, opportunities for query optimization', "
                    "'context': 'users.js: 156 lines, imports: User model, db, cache middleware'},\n"
                    "    {'agent': 'dependency_analyzer', 'task': 'Analyze cache.js and trace its usage: "
                    "is it applied to the right routes? Are cache invalidation patterns correct? "
                    "What routes SHOULD have caching but dont?', "
                    "'context': 'cache.js: 43 lines. Only imported by users.js, NOT by products.js (234 lines)'}\n"
                    "])\n```\n\n"
                    "## Phase 3: Evaluation & Retry\n\n"
                    "```python\n# The db.js analysis came back shallow — it mentioned connection pooling\n"
                    "# but didn't analyze the actual connection pattern\n"
                    "if results[0]['confidence'] < 0.75:\n"
                    "    results[0] = llm_query(\n"
                    "        'perf_analyzer',\n"
                    "        'Your analysis of db.js was too generic. I need you to specifically analyze: '\n"
                    "        '(1) How connections are created/destroyed per request, '\n"
                    "        '(2) Whether mongoose connection events are handled, '\n"
                    "        '(3) What happens under concurrent load. Be specific about line numbers.',\n"
                    "        results[0]['context'] + '\\nPrevious analysis: ' + results[0]['summary']\n"
                    "    )\n\n"
                    "# Cross-reference the cache analysis with the products.js analysis\n"
                    "cross_ref = llm_query(\n"
                    "    'perf_analyzer',\n"
                    "    'Products.js (234 lines, complex queries) has NO caching, while users.js '\n"
                    "    '(156 lines, simpler queries) does have caching. Analyze the performance '\n"
                    "    'impact of this discrepancy. What queries in products.js would benefit most from caching?',\n"
                    "    json.dumps([results[1]['findings'], results[3]['findings']])\n"
                    ")\n```\n\n"
                    "## Final Synthesis\n\n"
                    "1. **CRITICAL** — No connection pooling in db.js. Each request creates a new mongoose "
                    "connection (line 12: `mongoose.connect()` called per-request in middleware). Under load, "
                    "this will exhaust database connections. Fix: move to connection pool with `mongoose.createConnection()` "
                    "at startup.\n"
                    "2. **HIGH** — N+1 query pattern in products.js lines 45-67: fetching product list then "
                    "looping to fetch each product's reviews individually. Fix: use `.populate()` or aggregation.\n"
                    "3. **HIGH** — products.js has zero caching despite being the most query-heavy route (234 lines). "
                    "The cache middleware in cache.js is only applied to users.js. Applying it to the product list "
                    "endpoint alone would reduce DB load by an estimated 70%.\n"
                    "4. **MEDIUM** — No pagination on GET /products (line 34). Returns all products. "
                    "Will degrade linearly with data growth.\n"
                    "5. **MEDIUM** — Synchronous file operation in products.js line 189: `fs.readFileSync` "
                    "for product image processing. Blocks the event loop.\n\n"
                    "```python\nanswer['ready'] = True\nanswer['bottlenecks'] = [...]\n"
                    "answer['confidence'] = 0.91\nanswer['sub_llm_calls'] = 6  # 4 initial + 1 retry + 1 cross-ref\n```"
                )
            }
        ]
    },

    # Trace 3: Bug detection — aggressive decomposition
    {
        "messages": [
            {
                "role": "user",
                "content": (
                    "You are a root orchestrator analyzing a Python data pipeline. "
                    "Your available tools are:\n"
                    "- `llm_query(agent, task, context)` — dispatch a focused task to a sub-LLM\n"
                    "- `llm_batch(tasks)` — dispatch multiple tasks in parallel\n"
                    "- `explore(path)` — list files in a directory\n"
                    "- `read_metadata(file)` — get file size, last modified, imports\n\n"
                    "File tree:\n```\npipeline/\n├── ingestion.py (198 lines)\n├── transform.py (267 lines)\n"
                    "├── validation.py (134 lines)\n├── output.py (89 lines)\n"
                    "├── config.py (45 lines)\n└── tests/\n    ├── test_transform.py (156 lines)\n"
                    "    └── test_validation.py (78 lines)\n```\n\n"
                    "Task: Find all bugs in this data pipeline, especially data corruption risks.\n\n"
                    "Think step by step about how to orchestrate this analysis."
                )
            },
            {
                "role": "assistant",
                "content": (
                    "Data pipelines have a particularly insidious class of bugs: silent data corruption "
                    "where the pipeline completes 'successfully' but produces wrong results. I'll orchestrate "
                    "a thorough analysis targeting these.\n\n"
                    "## Phase 1: Exploration & Dependency Mapping\n\n"
                    "```python\nexplore('pipeline/')\n"
                    "# Map the data flow: ingestion → transform → validation → output\n"
                    "for f in ['ingestion.py', 'transform.py', 'validation.py', 'output.py', 'config.py']:\n"
                    "    read_metadata(f'pipeline/{f}')\n"
                    "# Also check test coverage\n"
                    "read_metadata('pipeline/tests/test_transform.py')\n"
                    "read_metadata('pipeline/tests/test_validation.py')\n```\n\n"
                    "Key observation: transform.py (267 lines) is the largest and most complex. "
                    "ingestion.py has NO tests. output.py has NO tests. These are the highest-risk files.\n\n"
                    "## Phase 2: Multi-Angle Decomposition\n\n"
                    "I'm decomposing into 6 subtasks — more than usual because data corruption bugs "
                    "require both within-file and cross-file analysis:\n\n"
                    "```python\nresults = llm_batch([\n"
                    "    # Within-file bugs\n"
                    "    {'agent': 'bug_detector', 'task': 'Find bugs in ingestion.py: type coercion errors, "
                    "encoding issues, missing null/empty checks on input data, race conditions in file I/O', "
                    "'context': 'ingestion.py: 198 lines, imports: pandas, csv, json, pathlib'},\n"
                    "    {'agent': 'bug_detector', 'task': 'Find bugs in transform.py: off-by-one errors, "
                    "incorrect aggregations, floating point precision loss, mutation of shared data structures, "
                    "incorrect merge/join logic', "
                    "'context': 'transform.py: 267 lines, imports: pandas, numpy, datetime'},\n"
                    "    {'agent': 'bug_detector', 'task': 'Find bugs in validation.py: validators that are too "
                    "permissive, missing edge cases (empty strings, NaN, infinity, negative zero), schema drift', "
                    "'context': 'validation.py: 134 lines, imports: pandas, jsonschema'},\n"
                    "    {'agent': 'bug_detector', 'task': 'Find bugs in output.py: data loss during serialization, "
                    "encoding issues, truncation, missing error handling on write failures', "
                    "'context': 'output.py: 89 lines, imports: pandas, json, pathlib'},\n"
                    "    # Cross-file data flow bugs\n"
                    "    {'agent': 'logic_analyzer', 'task': 'Analyze the data contract between ingestion.py → "
                    "transform.py → validation.py → output.py. What assumptions does each stage make about "
                    "its input that the previous stage might violate?', "
                    "'context': 'Data flow: ingestion reads raw data, transform applies business logic, "
                    "validation checks output, output writes results'},\n"
                    "    # Test coverage gap analysis\n"
                    "    {'agent': 'code_reviewer', 'task': 'Compare test coverage: test_transform.py (156 lines) "
                    "vs transform.py (267 lines), test_validation.py (78 lines) vs validation.py (134 lines). "
                    "Note: ingestion.py and output.py have ZERO tests. What critical paths are untested?', "
                    "'context': 'Test files exist only for transform and validation'}\n"
                    "])\n```\n\n"
                    "## Phase 3: Evaluation & Targeted Retry\n\n"
                    "```python\n# The cross-file analysis (result[4]) is the most valuable — check it carefully\n"
                    "if results[4]['confidence'] < 0.8:\n"
                    "    results[4] = llm_query(\n"
                    "        'logic_analyzer',\n"
                    "        'Your data contract analysis was incomplete. Specifically analyze: '\n"
                    "        '(1) What happens if ingestion produces NaN values — does transform handle them? '\n"
                    "        '(2) Does validation catch all the ways transform could corrupt data? '\n"
                    "        '(3) Are there data types that change between stages (e.g., int→float)?',\n"
                    "        results[4]['context'] + '\\nPrevious: ' + results[4]['summary']\n"
                    "    )\n\n"
                    "# Also retry the transform analysis — it's the most complex file\n"
                    "if len(results[1]['findings']) < 3:\n"
                    "    results[1] = llm_query(\n"
                    "        'bug_detector',\n"
                    "        'transform.py is 267 lines and you found fewer than 3 bugs. '\n"
                    "        'This is almost certainly incomplete. Focus specifically on: '\n"
                    "        'pandas operations that silently drop data, datetime timezone issues, '\n"
                    "        'and groupby operations with unexpected behavior on NaN keys.',\n"
                    "        results[1]['context']\n"
                    "    )\n```\n\n"
                    "## Final Synthesis\n\n"
                    "Cross-referencing all 6 analyses reveals 4 confirmed bugs and 2 high-risk gaps:\n\n"
                    "1. **CRITICAL** — transform.py line 45: `df.groupby('category').mean()` silently drops "
                    "rows where category is NaN. Ingestion.py does NOT filter NaN categories. Data loss is "
                    "silent — no error, just missing rows in output.\n"
                    "2. **CRITICAL** — Data contract violation: ingestion.py outputs timestamps as strings "
                    "(ISO format), but transform.py line 78 does `pd.to_datetime()` without specifying timezone. "
                    "If input has mixed UTC/local times, results are silently wrong.\n"
                    "3. **HIGH** — transform.py line 134: floating point aggregation loses precision on "
                    "financial amounts. Uses `df.sum()` instead of `Decimal`.\n"
                    "4. **HIGH** — validation.py line 67: schema validator accepts empty strings as valid "
                    "for required fields. Downstream consumers will fail.\n"
                    "5. **MEDIUM** — output.py has zero error handling on `df.to_json()` — if disk is full "
                    "or path is invalid, partial writes corrupt the output file.\n"
                    "6. **GAP** — ingestion.py and output.py have zero tests. These are the entry and exit "
                    "points of the pipeline — the highest-risk places to have no coverage.\n\n"
                    "```python\nanswer['ready'] = True\nanswer['bugs'] = [...]\n"
                    "answer['confidence'] = 0.87\nanswer['sub_llm_calls'] = 8  # 6 initial + 2 retries\n```"
                )
            }
        ]
    },

    # Trace 4: Dependency analysis — minimal retry needed
    {
        "messages": [
            {
                "role": "user",
                "content": (
                    "You are a root orchestrator analyzing a Python web application. "
                    "Your available tools are:\n"
                    "- `llm_query(agent, task, context)` — dispatch a focused task to a sub-LLM\n"
                    "- `llm_batch(tasks)` — dispatch multiple tasks in parallel\n"
                    "- `explore(path)` — list files in a directory\n"
                    "- `read_metadata(file)` — get file size, last modified, imports\n\n"
                    "File tree:\n```\napp/\n├── requirements.txt\n├── setup.py\n├── main.py (56 lines)\n"
                    "├── api/ (4 files, 450 total lines)\n├── models/ (3 files, 230 total lines)\n"
                    "└── utils/ (2 files, 120 total lines)\n```\n\n"
                    "Task: Audit all dependencies for security vulnerabilities and version conflicts.\n\n"
                    "Think step by step about how to orchestrate this analysis."
                )
            },
            {
                "role": "assistant",
                "content": (
                    "Dependency auditing requires checking both declared dependencies AND actual usage patterns. "
                    "A vulnerability in a dependency that's imported but never called is lower risk than one in a "
                    "hot code path.\n\n"
                    "## Phase 1: Exploration\n\n"
                    "```python\nexplore('app/')\nread_metadata('app/requirements.txt')\n"
                    "read_metadata('app/setup.py')\n"
                    "# Map actual imports across all source files\n"
                    "for d in ['api', 'models', 'utils']:\n"
                    "    explore(f'app/{d}/')\n"
                    "    for f in get_files(f'app/{d}/'):\n"
                    "        read_metadata(f)\n```\n\n"
                    "## Phase 2: Decomposition\n\n"
                    "```python\nresults = llm_batch([\n"
                    "    {'agent': 'security_analyzer', 'task': 'Analyze requirements.txt for known CVEs. "
                    "For each dependency, check: (1) is the pinned version affected by any CVE? "
                    "(2) is there a newer patched version? (3) is the package actively maintained?', "
                    "'context': 'requirements.txt contents: flask==2.0.1, SQLAlchemy==1.4.23, "
                    "requests==2.26.0, PyJWT==2.1.0, cryptography==3.4.7, celery==5.1.2, redis==3.5.3'},\n"
                    "    {'agent': 'dependency_analyzer', 'task': 'Check for version conflicts and "
                    "incompatibilities between: flask 2.0.1, SQLAlchemy 1.4.23, celery 5.1.2. "
                    "Are transitive dependencies compatible?', "
                    "'context': 'setup.py specifies Python >=3.8'},\n"
                    "    {'agent': 'code_reviewer', 'task': 'Map which dependencies are actually imported "
                    "and used in the codebase vs just listed in requirements.txt. Identify unused dependencies.', "
                    "'context': 'Source files: main.py imports flask, api/ imports flask+SQLAlchemy+PyJWT, "
                    "models/ imports SQLAlchemy, utils/ imports requests+cryptography'},\n"
                    "    {'agent': 'security_analyzer', 'task': 'For the dependencies actually used in hot paths "
                    "(flask, SQLAlchemy, PyJWT, cryptography), analyze how they are used: are deprecated APIs "
                    "called? Are there insecure configuration patterns?', "
                    "'context': 'api/ uses PyJWT for auth tokens, cryptography for password hashing, "
                    "SQLAlchemy for all DB queries'}\n"
                    "])\n```\n\n"
                    "## Phase 3: Evaluation\n\n"
                    "```python\n# All results came back with confidence > 0.8 — no retry needed\n"
                    "# But I should cross-reference the CVE findings with actual usage\n"
                    "cross_ref = llm_query(\n"
                    "    'security_analyzer',\n"
                    "    'Cross-reference: CVE findings indicate vulnerabilities in PyJWT 2.1.0 and "
                    "cryptography 3.4.7. The usage analysis shows these are in auth hot paths. "
                    "Assess the actual exploitability given how these libraries are used.',\n"
                    "    json.dumps([results[0]['findings'], results[3]['findings']])\n"
                    ")\n```\n\n"
                    "## Final Synthesis\n\n"
                    "1. **CRITICAL** — PyJWT 2.1.0 has CVE-2022-29217: algorithm confusion attack allows "
                    "forging tokens. This is in the auth hot path (api/auth.py). Upgrade to >=2.4.0.\n"
                    "2. **HIGH** — cryptography 3.4.7 has CVE-2023-23931: memory corruption in certain "
                    "operations. Used for password hashing in api/auth.py. Upgrade to >=39.0.1.\n"
                    "3. **MEDIUM** — requests 2.26.0 has no critical CVEs but is significantly outdated. "
                    "Only used in utils/ for external API calls.\n"
                    "4. **LOW** — celery 5.1.2 listed in requirements but NOT imported anywhere. "
                    "Unused dependency — remove it.\n"
                    "5. **INFO** — redis 3.5.3 is listed but only used as celery backend. Since celery "
                    "is unused, redis is also dead weight.\n\n"
                    "```python\nanswer['ready'] = True\nanswer['vulnerabilities'] = [...]\n"
                    "answer['confidence'] = 0.92\nanswer['sub_llm_calls'] = 5  # 4 initial + 1 cross-ref\n```"
                )
            }
        ]
    },

    # Trace 5: Refactoring assessment — synthesis depth
    {
        "messages": [
            {
                "role": "user",
                "content": (
                    "You are a root orchestrator analyzing a Python ML training pipeline. "
                    "Your available tools are:\n"
                    "- `llm_query(agent, task, context)` — dispatch a focused task to a sub-LLM\n"
                    "- `llm_batch(tasks)` — dispatch multiple tasks in parallel\n"
                    "- `explore(path)` — list files in a directory\n"
                    "- `read_metadata(file)` — get file size, last modified, imports\n\n"
                    "File tree:\n```\nml/\n├── train.py (456 lines)\n├── data_loader.py (234 lines)\n"
                    "├── model.py (178 lines)\n├── evaluate.py (145 lines)\n├── utils.py (312 lines)\n"
                    "├── config.py (67 lines)\n└── scripts/\n    ├── preprocess.py (189 lines)\n"
                    "    └── export.py (123 lines)\n```\n\n"
                    "Task: Assess refactoring opportunities. Where is the technical debt highest?\n\n"
                    "Think step by step about how to orchestrate this analysis."
                )
            },
            {
                "role": "assistant",
                "content": (
                    "Technical debt assessment requires understanding both code quality AND "
                    "architectural patterns. I'll analyze at both levels.\n\n"
                    "## Phase 1: Exploration\n\n"
                    "```python\nexplore('ml/')\n# Check all files — line counts suggest train.py and utils.py are bloated\n"
                    "for f in ['train.py', 'data_loader.py', 'model.py', 'evaluate.py', "
                    "'utils.py', 'config.py', 'scripts/preprocess.py', 'scripts/export.py']:\n"
                    "    read_metadata(f'ml/{f}')\n```\n\n"
                    "Red flags from metadata: train.py is 456 lines (likely God object), utils.py is 312 lines "
                    "(likely dumping ground), and both have high import counts.\n\n"
                    "## Phase 2: Decomposition\n\n"
                    "```python\nresults = llm_batch([\n"
                    "    {'agent': 'code_reviewer', 'task': 'Analyze train.py (456 lines) for: God class/function "
                    "anti-pattern, mixed responsibilities, code that should be extracted into separate modules. "
                    "Count distinct responsibilities.', "
                    "'context': 'train.py: 456 lines, imports: torch, numpy, wandb, data_loader, model, evaluate, utils, config'},\n"
                    "    {'agent': 'code_reviewer', 'task': 'Analyze utils.py (312 lines) for: unrelated functions "
                    "grouped together, code duplication with other files, functions that belong in specific modules "
                    "rather than a generic utils file.', "
                    "'context': 'utils.py: 312 lines, imports: numpy, torch, json, pathlib, logging, typing'},\n"
                    "    {'agent': 'logic_analyzer', 'task': 'Analyze the coupling between all modules. Map which "
                    "files import which. Identify circular dependencies, high fan-in modules (imported by many), "
                    "and high fan-out modules (import many things).', "
                    "'context': 'Module dependency hints: train.py imports everything, utils.py imported by 5 files'},\n"
                    "    {'agent': 'code_reviewer', 'task': 'Identify code duplication across the entire codebase. "
                    "Are there similar functions in train.py and evaluate.py? Does preprocess.py duplicate "
                    "data_loader.py logic?', "
                    "'context': 'preprocess.py: 189 lines, data_loader.py: 234 lines — both handle data'},\n"
                    "    {'agent': 'style_reviewer', 'task': 'Check for inconsistent patterns: mixed naming "
                    "conventions, inconsistent error handling, magic numbers, missing type hints, "
                    "undocumented public functions.', "
                    "'context': 'All Python files, total ~1700 lines'}\n"
                    "])\n```\n\n"
                    "## Phase 3: Evaluation & Targeted Retry\n\n"
                    "```python\n# The coupling analysis is critical for refactoring recommendations\n"
                    "if not results[2].get('dependency_graph'):\n"
                    "    results[2] = llm_query(\n"
                    "        'logic_analyzer',\n"
                    "        'I need an actual dependency graph, not just a description. Format as: '\n"
                    "        'module → [imports]. Also calculate: which module, if changed, would require '\n"
                    "        'the most other modules to be retested?',\n"
                    "        results[2]['context']\n"
                    "    )\n```\n\n"
                    "## Final Synthesis\n\n"
                    "Cross-referencing all analyses, the tech debt clusters into 3 refactoring priorities:\n\n"
                    "**Priority 1: Split train.py (Effort: Medium, Impact: High)**\n"
                    "train.py has 5 distinct responsibilities (found by code_reviewer): data preparation, "
                    "model initialization, training loop, checkpointing, and logging/metrics. Extract into "
                    "train_loop.py, checkpoint.py, and metrics.py. This will reduce coupling analysis score "
                    "from 8 (fan-out) to 3 per module.\n\n"
                    "**Priority 2: Dissolve utils.py (Effort: Low, Impact: Medium)**\n"
                    "utils.py contains 14 functions (found by code_reviewer) spanning 4 unrelated domains: "
                    "tensor operations (→ move to model.py), file I/O (→ data_loader.py), "
                    "logging setup (→ new logging_config.py), and metric calculations (→ evaluate.py). "
                    "5 of these functions duplicate logic already in data_loader.py (confirmed by duplication analysis).\n\n"
                    "**Priority 3: Unify data handling (Effort: High, Impact: High)**\n"
                    "preprocess.py and data_loader.py share 3 nearly-identical functions "
                    "(found by duplication analysis). Merge into a single data pipeline with clear stages.\n\n"
                    "```python\nanswer['ready'] = True\nanswer['refactoring_priorities'] = [...]\n"
                    "answer['confidence'] = 0.84\nanswer['sub_llm_calls'] = 6  # 5 initial + 1 retry\n```"
                )
            }
        ]
    },

    # Trace 6: Simple task — fewer dispatches but still thorough
    {
        "messages": [
            {
                "role": "user",
                "content": (
                    "You are a root orchestrator analyzing a Python utility module. "
                    "Your available tools are:\n"
                    "- `llm_query(agent, task, context)` — dispatch a focused task to a sub-LLM\n"
                    "- `llm_batch(tasks)` — dispatch multiple tasks in parallel\n"
                    "- `explore(path)` — list files in a directory\n"
                    "- `read_metadata(file)` — get file size, last modified, imports\n\n"
                    "File tree:\n```\nlib/\n├── retry.py (78 lines)\n├── http_client.py (134 lines)\n"
                    "└── tests/\n    └── test_retry.py (45 lines)\n```\n\n"
                    "Task: Check this HTTP client library for reliability issues.\n\n"
                    "Think step by step about how to orchestrate this analysis."
                )
            },
            {
                "role": "assistant",
                "content": (
                    "Small codebase, but reliability issues in HTTP clients can be subtle. "
                    "I'll be thorough even with fewer files.\n\n"
                    "## Phase 1: Exploration\n\n"
                    "```python\nexplore('lib/')\nread_metadata('lib/retry.py')\n"
                    "read_metadata('lib/http_client.py')\nread_metadata('lib/tests/test_retry.py')\n```\n\n"
                    "http_client.py imports retry.py — they work together. Test coverage only exists for "
                    "the retry module, not the HTTP client itself.\n\n"
                    "## Phase 2: Decomposition\n\n"
                    "```python\nresults = llm_batch([\n"
                    "    {'agent': 'reliability_analyzer', 'task': 'Analyze http_client.py for: missing timeouts, "
                    "no connection pooling, missing retry on transient errors, improper error handling on "
                    "network failures, resource leaks (unclosed connections/sessions)', "
                    "'context': 'http_client.py: 134 lines, imports: requests, json, retry'},\n"
                    "    {'agent': 'reliability_analyzer', 'task': 'Analyze retry.py for: retry strategy issues "
                    "(exponential backoff?), missing jitter, incorrect max retry count, retry on non-transient "
                    "errors (4xx), missing circuit breaker pattern', "
                    "'context': 'retry.py: 78 lines, imports: time, functools, logging'},\n"
                    "    {'agent': 'code_reviewer', 'task': 'Analyze test_retry.py for: are edge cases tested? "
                    "Does it test retry exhaustion? Does it test the interaction between retry and http_client?', "
                    "'context': 'test_retry.py: 45 lines — only tests retry.py, NOT http_client.py'}\n"
                    "])\n```\n\n"
                    "## Phase 3: Evaluation\n\n"
                    "```python\n# Cross-reference retry and http_client findings\n"
                    "cross_ref = llm_query(\n"
                    "    'logic_analyzer',\n"
                    "    'The retry module and HTTP client work together. Analyze: '\n"
                    "    '(1) Does http_client correctly use retry for transient failures? '\n"
                    "    '(2) Are there cases where retry makes things WORSE (e.g., retrying POST requests)? '\n"
                    "    '(3) Is there proper timeout × retry interaction?',\n"
                    "    json.dumps([results[0]['findings'], results[1]['findings']])\n"
                    ")\n```\n\n"
                    "## Final Synthesis\n\n"
                    "1. **HIGH** — http_client.py has no default timeout (line 23: `requests.get(url)` without "
                    "`timeout` parameter). Combined with retry, this means a hanging server blocks the client "
                    "for retry_count × infinity seconds.\n"
                    "2. **HIGH** — retry.py retries on ALL exceptions including 400 Bad Request (line 34). "
                    "Non-transient errors should not be retried.\n"
                    "3. **MEDIUM** — No exponential backoff in retry.py. Fixed 1-second sleep between retries "
                    "(line 41) will hammer a recovering server.\n"
                    "4. **MEDIUM** — http_client.py creates a new `requests.Session()` per call (line 15) "
                    "instead of reusing connections.\n"
                    "5. **LOW** — test_retry.py doesn't test retry exhaustion behavior.\n\n"
                    "```python\nanswer['ready'] = True\nanswer['reliability_issues'] = [...]\n"
                    "answer['confidence'] = 0.89\nanswer['sub_llm_calls'] = 4  # 3 initial + 1 cross-ref\n```"
                )
            }
        ]
    },

    # Trace 7: Complex multi-service analysis
    {
        "messages": [
            {
                "role": "user",
                "content": (
                    "You are a root orchestrator analyzing a microservices system. "
                    "Your available tools are:\n"
                    "- `llm_query(agent, task, context)` — dispatch a focused task to a sub-LLM\n"
                    "- `llm_batch(tasks)` — dispatch multiple tasks in parallel\n"
                    "- `explore(path)` — list files in a directory\n"
                    "- `read_metadata(file)` — get file size, last modified, imports\n\n"
                    "File tree:\n```\nservices/\n├── gateway/\n│   ├── main.py (123 lines)\n│   └── router.py (189 lines)\n"
                    "├── auth/\n│   ├── service.py (234 lines)\n│   └── tokens.py (67 lines)\n"
                    "├── orders/\n│   ├── service.py (345 lines)\n│   └── models.py (156 lines)\n"
                    "├── payments/\n│   ├── service.py (267 lines)\n│   └── stripe_client.py (89 lines)\n"
                    "└── shared/\n    ├── events.py (45 lines)\n    └── schemas.py (78 lines)\n```\n\n"
                    "Task: Identify all inter-service communication failures and data consistency risks.\n\n"
                    "Think step by step about how to orchestrate this analysis."
                )
            },
            {
                "role": "assistant",
                "content": (
                    "Microservice communication failures are among the hardest bugs to find because "
                    "they only manifest under specific timing conditions. I need to analyze both "
                    "individual services AND their interactions.\n\n"
                    "## Phase 1: Deep Exploration\n\n"
                    "```python\nexplore('services/')\n"
                    "# Map every service's structure and dependencies\n"
                    "for svc in ['gateway', 'auth', 'orders', 'payments', 'shared']:\n"
                    "    explore(f'services/{svc}/')\n"
                    "    for f in get_files(f'services/{svc}/'):\n"
                    "        read_metadata(f)\n```\n\n"
                    "Key findings from metadata: gateway/router.py calls all 3 services. orders/service.py "
                    "is the most complex at 345 lines and imports both auth and payments. shared/events.py "
                    "suggests an event-driven pattern. All services import shared/schemas.py.\n\n"
                    "## Phase 2: Aggressive Decomposition\n\n"
                    "7 subtasks — I need to cover both within-service and cross-service failure modes:\n\n"
                    "```python\nresults = llm_batch([\n"
                    "    # Per-service resilience analysis\n"
                    "    {'agent': 'reliability_analyzer', 'task': 'Analyze gateway/router.py for: missing "
                    "circuit breakers, no timeout on downstream calls, missing fallback responses, "
                    "cascading failure risk when a downstream service is slow', "
                    "'context': 'router.py: 189 lines, calls auth, orders, and payments services via HTTP'},\n"
                    "    {'agent': 'reliability_analyzer', 'task': 'Analyze orders/service.py for: distributed "
                    "transaction issues — this service coordinates between auth (verify user) and payments "
                    "(charge card). What happens if auth succeeds but payment fails? Is there rollback?', "
                    "'context': 'orders/service.py: 345 lines, imports: auth_client, payments_client, models'},\n"
                    "    {'agent': 'reliability_analyzer', 'task': 'Analyze payments/stripe_client.py for: "
                    "missing idempotency keys, no webhook verification, improper error handling on Stripe API failures', "
                    "'context': 'stripe_client.py: 89 lines, imports: stripe, json'},\n"
                    "    # Cross-service data consistency\n"
                    "    {'agent': 'logic_analyzer', 'task': 'Analyze shared/events.py: is the event bus "
                    "at-least-once or exactly-once? Are events idempotent? What happens on event delivery failure?', "
                    "'context': 'events.py: 45 lines, likely Redis or RabbitMQ based'},\n"
                    "    {'agent': 'logic_analyzer', 'task': 'Analyze shared/schemas.py: do all services use "
                    "the same version of shared schemas? Are there breaking changes? Is schema validation "
                    "enforced at service boundaries?', "
                    "'context': 'schemas.py: 78 lines, imported by ALL services'},\n"
                    "    # Failure scenario analysis\n"
                    "    {'agent': 'reliability_analyzer', 'task': 'Analyze this failure scenario: a user places "
                    "an order. Orders service calls auth (succeeds), then calls payments (times out after 30s). "
                    "What state is the system in? Is the order created? Is money charged? Can the user retry safely?', "
                    "'context': 'Orders coordinates auth + payments. No saga pattern visible in imports.'},\n"
                    "    {'agent': 'reliability_analyzer', 'task': 'Analyze this failure scenario: payments service "
                    "crashes mid-Stripe-charge. Stripe charges the card but the webhook callback fails. "
                    "How does the system reconcile?', "
                    "'context': 'payments/stripe_client.py handles Stripe API. shared/events.py handles inter-service events.'}\n"
                    "])\n```\n\n"
                    "## Phase 3: Evaluation & Critical Retry\n\n"
                    "```python\n# The distributed transaction analysis (result[1]) is the highest-value finding\n"
                    "if 'rollback' not in results[1]['summary'].lower() and 'saga' not in results[1]['summary'].lower():\n"
                    "    results[1] = llm_query(\n"
                    "        'reliability_analyzer',\n"
                    "        'You did not address the rollback question. When an order creation involves '\n"
                    "        'auth verification AND payment charging, what happens on partial failure? '\n"
                    "        'Is there a saga pattern? Compensation transactions? Or is data left inconsistent?',\n"
                    "        results[1]['context'] + '\\nPrevious: ' + results[1]['summary']\n"
                    "    )\n\n"
                    "# Cross-reference all failure scenarios\n"
                    "cross_ref = llm_query(\n"
                    "    'logic_analyzer',\n"
                    "    'Synthesize ALL failure scenario analyses. Are there common patterns? '\n"
                    "    'Does the system have a consistent strategy for handling partial failures, '\n"
                    "    'or is each service handling it differently?',\n"
                    "    json.dumps([r['findings'] for r in results[5:7]] + [results[1]['findings']])\n"
                    ")\n```\n\n"
                    "## Final Synthesis\n\n"
                    "The system has no consistent failure handling strategy — each service does it differently:\n\n"
                    "1. **CRITICAL** — No saga pattern in orders/service.py. When payment fails after auth "
                    "succeeds, the order is created in the database but never charged. There's no compensation "
                    "transaction and no cleanup job. Users get free orders on payment timeouts.\n"
                    "2. **CRITICAL** — gateway/router.py has no circuit breaker. When payments service is slow "
                    "(line 67: 60s timeout), ALL requests back up. Gateway's thread pool exhausts in ~30 concurrent "
                    "requests, taking down the entire system including healthy services.\n"
                    "3. **HIGH** — payments/stripe_client.py has no idempotency keys (confirmed by analysis). "
                    "If a user retries a failed order, they can be double-charged.\n"
                    "4. **HIGH** — events.py uses at-least-once delivery with no deduplication. "
                    "Event handlers in orders and payments are not idempotent — replayed events will "
                    "duplicate side effects.\n"
                    "5. **MEDIUM** — schemas.py has no versioning. A breaking schema change will silently corrupt "
                    "cross-service messages.\n\n"
                    "```python\nanswer['ready'] = True\nanswer['failures'] = [...]\n"
                    "answer['confidence'] = 0.86\nanswer['sub_llm_calls'] = 9  # 7 initial + 1 retry + 1 cross-ref\n```"
                )
            }
        ]
    },

    # Trace 8: API review — error handling focus
    {
        "messages": [
            {
                "role": "user",
                "content": (
                    "You are a root orchestrator analyzing a REST API. "
                    "Your available tools are:\n"
                    "- `llm_query(agent, task, context)` — dispatch a focused task to a sub-LLM\n"
                    "- `llm_batch(tasks)` — dispatch multiple tasks in parallel\n"
                    "- `explore(path)` — list files in a directory\n"
                    "- `read_metadata(file)` — get file size, last modified, imports\n\n"
                    "File tree:\n```\napi/\n├── app.py (45 lines)\n├── routes/\n│   ├── users.py (167 lines)\n"
                    "│   ├── posts.py (189 lines)\n│   └── comments.py (134 lines)\n"
                    "├── middleware/\n│   ├── auth.py (56 lines)\n│   └── rate_limit.py (34 lines)\n"
                    "└── models/\n    ├── user.py (78 lines)\n    └── post.py (65 lines)\n```\n\n"
                    "Task: Review this API for error handling gaps and edge cases.\n\n"
                    "Think step by step about how to orchestrate this analysis."
                )
            },
            {
                "role": "assistant",
                "content": (
                    "Error handling in REST APIs has two failure modes: unhandled exceptions that crash "
                    "the server, and caught exceptions that return misleading or insecure error responses. "
                    "I need to check both.\n\n"
                    "## Phase 1: Exploration\n\n"
                    "```python\nexplore('api/')\nexplore('api/routes/')\nexplore('api/middleware/')\nexplore('api/models/')\n"
                    "for f in ['app.py', 'routes/users.py', 'routes/posts.py', 'routes/comments.py', "
                    "'middleware/auth.py', 'middleware/rate_limit.py', 'models/user.py', 'models/post.py']:\n"
                    "    read_metadata(f'api/{f}')\n```\n\n"
                    "## Phase 2: Decomposition\n\n"
                    "```python\nresults = llm_batch([\n"
                    "    {'agent': 'error_analyzer', 'task': 'Analyze routes/users.py for: unhandled exceptions "
                    "in CRUD operations, missing input validation, database errors that leak to client, "
                    "missing 404/409/422 responses for edge cases', "
                    "'context': 'users.py: 167 lines, imports: flask, models.user, middleware.auth'},\n"
                    "    {'agent': 'error_analyzer', 'task': 'Analyze routes/posts.py for: same error handling "
                    "gaps. Additionally check: what happens when a post references a deleted user? "
                    "What about concurrent updates?', "
                    "'context': 'posts.py: 189 lines, imports: flask, models.post, models.user'},\n"
                    "    {'agent': 'error_analyzer', 'task': 'Analyze routes/comments.py for: nested resource "
                    "error handling — what happens when the parent post doesn\\'t exist? What about deeply "
                    "nested comment chains?', "
                    "'context': 'comments.py: 134 lines, imports: flask, models.post'},\n"
                    "    {'agent': 'security_analyzer', 'task': 'Analyze all error responses for information "
                    "leakage: do any error messages expose stack traces, database schema, file paths, "
                    "or internal service details to the client?', "
                    "'context': 'Routes return JSON error responses. Check for exception.__str__() in responses'},\n"
                    "    {'agent': 'code_reviewer', 'task': 'Check middleware/auth.py and rate_limit.py: "
                    "what happens when auth fails? Is there a consistent error format? Does rate_limit.py "
                    "return proper 429 with Retry-After header?', "
                    "'context': 'auth.py: 56 lines, rate_limit.py: 34 lines'}\n"
                    "])\n```\n\n"
                    "## Phase 3: Evaluation\n\n"
                    "```python\n# The information leakage check is critical\n"
                    "if results[3]['confidence'] < 0.8:\n"
                    "    results[3] = llm_query(\n"
                    "        'security_analyzer',\n"
                    "        'Be more thorough on information leakage. Check specifically: '\n"
                    "        '(1) bare except clauses that format exception as string, '\n"
                    "        '(2) Flask debug mode in app.py, '\n"
                    "        '(3) SQL error messages in database operation catches',\n"
                    "        results[3]['context']\n"
                    "    )\n\n"
                    "# Consistency check across all routes\n"
                    "cross_ref = llm_query(\n"
                    "    'code_reviewer',\n"
                    "    'Compare error handling patterns across users.py, posts.py, and comments.py. '\n"
                    "    'Are error response formats consistent? Do all routes handle the same edge cases '\n"
                    "    'the same way, or is there inconsistency?',\n"
                    "    json.dumps([results[0]['findings'], results[1]['findings'], results[2]['findings']])\n"
                    ")\n```\n\n"
                    "## Final Synthesis\n\n"
                    "1. **HIGH** — Inconsistent error response format across routes (confirmed by cross-reference). "
                    "users.py returns `{'error': msg}`, posts.py returns `{'message': msg}`, comments.py returns "
                    "plain strings. Clients can't reliably parse errors.\n"
                    "2. **HIGH** — posts.py line 78: accessing a post by deleted user returns 500 "
                    "(unhandled IntegrityError) instead of 404. Database error leaks SQL table names.\n"
                    "3. **HIGH** — auth.py returns full JWT decode error in 401 response (line 34). "
                    "This tells attackers which JWT library and version is used.\n"
                    "4. **MEDIUM** — No global exception handler in app.py. Any unhandled exception returns "
                    "Flask's default HTML error page with stack trace in debug mode.\n"
                    "5. **MEDIUM** — rate_limit.py returns 429 but without Retry-After header. "
                    "Well-behaved clients can't throttle correctly.\n"
                    "6. **LOW** — comments.py doesn't check if parent post exists before creating a comment "
                    "(line 45). Returns cryptic database error instead of 404.\n\n"
                    "```python\nanswer['ready'] = True\nanswer['error_handling_gaps'] = [...]\n"
                    "answer['confidence'] = 0.90\nanswer['sub_llm_calls'] = 7  # 5 initial + 1 retry + 1 cross-ref\n```"
                )
            }
        ]
    },

    # Trace 9: Type safety analysis
    {
        "messages": [
            {
                "role": "user",
                "content": (
                    "You are a root orchestrator analyzing a Python data science project. "
                    "Your available tools are:\n"
                    "- `llm_query(agent, task, context)` — dispatch a focused task to a sub-LLM\n"
                    "- `llm_batch(tasks)` — dispatch multiple tasks in parallel\n"
                    "- `explore(path)` — list files in a directory\n"
                    "- `read_metadata(file)` — get file size, last modified, imports\n\n"
                    "File tree:\n```\nanalysis/\n├── pipeline.py (289 lines)\n├── features.py (178 lines)\n"
                    "├── models.py (145 lines)\n├── viz.py (98 lines)\n└── utils.py (67 lines)\n```\n\n"
                    "Task: Find all type safety issues that could cause silent data corruption.\n\n"
                    "Think step by step about how to orchestrate this analysis."
                )
            },
            {
                "role": "assistant",
                "content": (
                    "Type safety in data science code is especially dangerous because pandas/numpy silently "
                    "coerce types, leading to corrupt results with no errors. I need to trace type flows "
                    "across the entire pipeline.\n\n"
                    "## Phase 1: Exploration\n\n"
                    "```python\nexplore('analysis/')\nfor f in ['pipeline.py', 'features.py', 'models.py', "
                    "'viz.py', 'utils.py']:\n    read_metadata(f'analysis/{f}')\n```\n\n"
                    "pipeline.py is the main orchestrator (289 lines) calling features.py → models.py → viz.py. "
                    "All files import pandas and numpy.\n\n"
                    "## Phase 2: Decomposition\n\n"
                    "```python\nresults = llm_batch([\n"
                    "    {'agent': 'type_checker', 'task': 'Analyze pipeline.py for: implicit type conversions "
                    "between pipeline stages, DataFrame columns changing dtype silently, "
                    "int→float conversion from NaN introduction, string→numeric coercion', "
                    "'context': 'pipeline.py: 289 lines, imports: pandas, features, models, viz'},\n"
                    "    {'agent': 'type_checker', 'task': 'Analyze features.py for: feature engineering "
                    "operations that change column dtypes, categorical encoding producing unexpected types, "
                    "datetime parsing failures that silently produce NaT', "
                    "'context': 'features.py: 178 lines, imports: pandas, numpy, sklearn.preprocessing'},\n"
                    "    {'agent': 'type_checker', 'task': 'Analyze models.py for: model input type requirements "
                    "vs actual input types from features.py, numpy/pandas type mismatches, "
                    "prediction output types vs expected downstream types', "
                    "'context': 'models.py: 145 lines, imports: sklearn, pandas, numpy'},\n"
                    "    {'agent': 'logic_analyzer', 'task': 'Trace the DataFrame type contract through the "
                    "full pipeline: what dtypes does pipeline.py expect from features.py? What dtypes does "
                    "models.py expect? Are these contracts documented or enforced anywhere?', "
                    "'context': 'Flow: pipeline → features → models → viz. No type annotations visible.'}\n"
                    "])\n```\n\n"
                    "## Phase 3: Evaluation\n\n"
                    "```python\n# Type contract analysis is the most important — ensure it's thorough\n"
                    "if 'dtype' not in results[3]['summary'] or results[3]['confidence'] < 0.75:\n"
                    "    results[3] = llm_query(\n"
                    "        'logic_analyzer',\n"
                    "        'Your type contract analysis lacked specifics. I need: '\n"
                    "        '(1) specific column names and their expected vs actual dtypes at each stage, '\n"
                    "        '(2) where NaN introduction changes int columns to float, '\n"
                    "        '(3) where string categories get silently converted to numeric.',\n"
                    "        results[3]['context']\n"
                    "    )\n\n"
                    "cross_ref = llm_query(\n"
                    "    'type_checker',\n"
                    "    'Cross-reference type issues across all analyses. Find cases where a type change '\n"
                    "    'in features.py causes a silent error in models.py or viz.py.',\n"
                    "    json.dumps([r['findings'] for r in results])\n"
                    ")\n```\n\n"
                    "## Final Synthesis\n\n"
                    "1. **CRITICAL** — features.py line 56: `pd.to_numeric(df['age'], errors='coerce')` silently "
                    "converts non-numeric ages to NaN. This changes the column from int64 to float64. "
                    "models.py line 23 does integer comparison `age > 18` which now fails silently for NaN rows.\n"
                    "2. **HIGH** — pipeline.py line 134: merging two DataFrames where the join key is 'id' — "
                    "but left table has id as int64 and right table has id as string. Pandas silently "
                    "converts to object type, and the merge produces zero matches.\n"
                    "3. **HIGH** — features.py line 89: `LabelEncoder` applied to a column with unseen "
                    "categories at prediction time. No error — just wrong integer codes.\n"
                    "4. **MEDIUM** — viz.py line 45: plotting function receives float predictions but "
                    "formats as integers for display, silently truncating decimal precision.\n\n"
                    "```python\nanswer['ready'] = True\nanswer['type_issues'] = [...]\n"
                    "answer['confidence'] = 0.85\nanswer['sub_llm_calls'] = 6  # 4 initial + 1 retry + 1 cross-ref\n```"
                )
            }
        ]
    },

    # Trace 10: Concurrency analysis
    {
        "messages": [
            {
                "role": "user",
                "content": (
                    "You are a root orchestrator analyzing a Python async web scraper. "
                    "Your available tools are:\n"
                    "- `llm_query(agent, task, context)` — dispatch a focused task to a sub-LLM\n"
                    "- `llm_batch(tasks)` — dispatch multiple tasks in parallel\n"
                    "- `explore(path)` — list files in a directory\n"
                    "- `read_metadata(file)` — get file size, last modified, imports\n\n"
                    "File tree:\n```\nscraper/\n├── main.py (89 lines)\n├── crawler.py (234 lines)\n"
                    "├── parser.py (156 lines)\n├── storage.py (112 lines)\n"
                    "├── rate_limiter.py (45 lines)\n└── config.py (34 lines)\n```\n\n"
                    "Task: Find all concurrency bugs and race conditions.\n\n"
                    "Think step by step about how to orchestrate this analysis."
                )
            },
            {
                "role": "assistant",
                "content": (
                    "Concurrency bugs in async Python are notoriously hard to find because they depend on "
                    "timing. I need to analyze both the async patterns AND shared state access.\n\n"
                    "## Phase 1: Exploration\n\n"
                    "```python\nexplore('scraper/')\nfor f in ['main.py', 'crawler.py', 'parser.py', "
                    "'storage.py', 'rate_limiter.py', 'config.py']:\n    read_metadata(f'scraper/{f}')\n```\n\n"
                    "crawler.py is the core (234 lines) with asyncio imports. storage.py likely has shared state. "
                    "rate_limiter.py is small but critical for correctness under concurrency.\n\n"
                    "## Phase 2: Decomposition\n\n"
                    "```python\nresults = llm_batch([\n"
                    "    {'agent': 'concurrency_analyzer', 'task': 'Analyze crawler.py for: shared mutable state "
                    "accessed from multiple coroutines, missing locks on shared data structures, "
                    "asyncio.gather() without error handling, unbounded task creation', "
                    "'context': 'crawler.py: 234 lines, imports: asyncio, aiohttp, parser, storage, rate_limiter'},\n"
                    "    {'agent': 'concurrency_analyzer', 'task': 'Analyze storage.py for: concurrent writes "
                    "to the same file/database, missing atomicity on write operations, "
                    "read-modify-write races on counters or caches', "
                    "'context': 'storage.py: 112 lines, imports: aiofiles, json, pathlib'},\n"
                    "    {'agent': 'concurrency_analyzer', 'task': 'Analyze rate_limiter.py for: token bucket "
                    "or leaky bucket race conditions, counter updates that are not atomic, "
                    "timing issues in rate limit windows', "
                    "'context': 'rate_limiter.py: 45 lines, imports: asyncio, time'},\n"
                    "    {'agent': 'logic_analyzer', 'task': 'Analyze the interaction between crawler.py and "
                    "rate_limiter.py: if 100 coroutines check the rate limit simultaneously, "
                    "can more than the allowed number proceed? Is there a TOCTOU race?', "
                    "'context': 'crawler.py calls rate_limiter.check() before each request'}\n"
                    "])\n```\n\n"
                    "## Phase 3: Evaluation & Retry\n\n"
                    "```python\n# The rate limiter TOCTOU analysis is critical\n"
                    "if 'toctou' not in results[3]['summary'].lower() and 'time-of-check' not in results[3]['summary'].lower():\n"
                    "    results[3] = llm_query(\n"
                    "        'concurrency_analyzer',\n"
                    "        'You missed the TOCTOU analysis. Specifically: rate_limiter.check() returns True '\n"
                    "        'but between the check and the actual HTTP request, other coroutines also check '\n"
                    "        'and get True. Is the rate limit enforced atomically? Show the race window.',\n"
                    "        results[3]['context']\n"
                    "    )\n\n"
                    "# Cross-reference storage and crawler\n"
                    "cross_ref = llm_query(\n"
                    "    'concurrency_analyzer',\n"
                    "    'Multiple crawler coroutines write to storage simultaneously. '\n"
                    "    'Analyze: can two coroutines write to the same output file? '\n"
                    "    'Can a read see partially-written data?',\n"
                    "    json.dumps([results[0]['findings'], results[1]['findings']])\n"
                    ")\n```\n\n"
                    "## Final Synthesis\n\n"
                    "1. **CRITICAL** — rate_limiter.py has a classic TOCTOU race (lines 12-18): "
                    "`check()` reads the counter, checks against limit, then increments — but these "
                    "are three separate operations without a lock. Under 100 concurrent coroutines, "
                    "~3x the rate limit passes through.\n"
                    "2. **CRITICAL** — crawler.py line 78: shared `visited_urls` set is modified from "
                    "multiple coroutines without locking. `if url not in visited` → `visited.add(url)` "
                    "is not atomic. Duplicate crawls will occur.\n"
                    "3. **HIGH** — storage.py line 34: `aiofiles.open('output.jsonl', 'a')` from multiple "
                    "coroutines. Individual writes may interleave, producing malformed JSON lines. "
                    "Need an asyncio.Lock or write queue.\n"
                    "4. **MEDIUM** — crawler.py line 112: `asyncio.gather(*tasks)` with no semaphore bound. "
                    "If the URL frontier has 10,000 URLs, it creates 10,000 simultaneous connections. "
                    "Will exhaust file descriptors and get IP-banned.\n"
                    "5. **MEDIUM** — No error handling on `asyncio.gather()` — if one task raises, "
                    "default behavior depends on `return_exceptions` flag which isn't set.\n\n"
                    "```python\nanswer['ready'] = True\nanswer['concurrency_bugs'] = [...]\n"
                    "answer['confidence'] = 0.88\nanswer['sub_llm_calls'] = 6  # 4 initial + 1 retry + 1 cross-ref\n```"
                )
            }
        ]
    }
]


# ── Write JSONL files ──────────────────────────────────────────────────
TRAIN_FILE = "orchestration_traces_train.jsonl"
EVAL_FILE = "orchestration_traces_eval.jsonl"

# Use first 8 for training, last 2 for eval (80/20 split)
train_traces = TRACES[:8]
eval_traces = TRACES[8:]

print(f"Writing {len(train_traces)} training traces to {TRAIN_FILE}")
with open(TRAIN_FILE, "w") as f:
    for trace in train_traces:
        f.write(json.dumps(trace) + "\n")

print(f"Writing {len(eval_traces)} eval traces to {EVAL_FILE}")
with open(EVAL_FILE, "w") as f:
    for trace in eval_traces:
        f.write(json.dumps(trace) + "\n")

# ── Verify file sizes ─────────────────────────────────────────────────
train_size = Path(TRAIN_FILE).stat().st_size
eval_size = Path(EVAL_FILE).stat().st_size
print(f"\nFile sizes: train={train_size:,} bytes, eval={eval_size:,} bytes")

# ── Submit fine-tuning job ─────────────────────────────────────────────
print("\n" + "="*60)
print("SUBMITTING TEST FINE-TUNING JOB TO MISTRAL LA PLATEFORME")
print("="*60)

start_time = time.time()
start_dt = datetime.now().isoformat()
print(f"\nStart time: {start_dt}")

# Step 1: Upload files
print("\n[1/4] Uploading training data...")
training_data = client.files.upload(file={
    "file_name": TRAIN_FILE,
    "content": open(TRAIN_FILE, "rb"),
})
print(f"  Training file ID: {training_data.id}")

print("[2/4] Uploading validation data...")
validation_data = client.files.upload(file={
    "file_name": EVAL_FILE,
    "content": open(EVAL_FILE, "rb"),
})
print(f"  Validation file ID: {validation_data.id}")

# Step 2: Create fine-tuning job
print("\n[3/4] Creating fine-tuning job...")

# Build job config — include W&B integration if key is available
job_kwargs = {
    "model": "open-mistral-nemo",  # Mistral Nemo (12B) — mistral-small-latest doesn't support fine-tuning
    "training_files": [{"file_id": training_data.id, "weight": 1}],
    "validation_files": [validation_data.id],
    "hyperparameters": {
        "training_steps": 10,      # Minimal steps — this is just a timing test
        "learning_rate": 0.0001,
    },
    "auto_start": False,
}

# Add W&B integration if API key is available
wandb_key = os.environ.get("WANDB_API_KEY")
if wandb_key:
    job_kwargs["integrations"] = [
        {
            "project": "rlm-distiller",
            "api_key": wandb_key,
        }
    ]
    print("  W&B integration: ENABLED")
else:
    print("  W&B integration: SKIPPED (no WANDB_API_KEY set)")

created_job = client.fine_tuning.jobs.create(**job_kwargs)
print(f"  Job ID: {created_job.id}")
print(f"  Initial status: {created_job.status}")

# Step 3: Wait for validation, then start
print("\n[4/4] Waiting for validation...")
while True:
    status = client.fine_tuning.jobs.get(job_id=created_job.id)
    print(f"  Status: {status.status}")
    if status.status == "VALIDATED":
        print("  Starting job...")
        client.fine_tuning.jobs.start(job_id=created_job.id)
        break
    elif status.status in ("RUNNING", "SUCCEEDED"):
        # auto_start might have kicked in, or it validated and started
        break
    elif status.status == "FAILED":
        print(f"\n  JOB FAILED during validation!")
        print(f"  Check the Mistral dashboard for error details.")
        sys.exit(1)
    time.sleep(5)

# Step 4: Poll until completion
print("\nPolling for completion (Ctrl+C to stop and check later)...")
print(f"Job ID for manual checking: {created_job.id}")
print()

try:
    while True:
        status = client.fine_tuning.jobs.get(job_id=created_job.id)
        elapsed = time.time() - start_time
        elapsed_min = elapsed / 60
        print(f"  [{elapsed_min:.1f} min] Status: {status.status}")
        
        if status.status == "SUCCEEDED":
            end_time = time.time()
            total_minutes = (end_time - start_time) / 60
            print(f"\n{'='*60}")
            print(f"JOB COMPLETED!")
            print(f"{'='*60}")
            print(f"  Total wall-clock time: {total_minutes:.1f} minutes")
            print(f"  Fine-tuned model name: {status.fine_tuned_model}")
            print(f"\n  THIS NUMBER IS YOUR OVERNIGHT STRATEGY:")
            if total_minutes < 30:
                print(f"  {total_minutes:.0f} min → You can do 8+ iterations overnight. Aggressive loop.")
            elif total_minutes < 60:
                print(f"  {total_minutes:.0f} min → You can do 4-6 iterations overnight. Solid.")
            elif total_minutes < 120:
                print(f"  {total_minutes:.0f} min → You can do 2-3 iterations overnight. Plan carefully.")
            else:
                print(f"  {total_minutes:.0f} min → Switch to Ministral 14B or parallelize.")
            break
            
        elif status.status == "FAILED":
            print(f"\n  JOB FAILED after {elapsed_min:.1f} minutes")
            print(f"  Check Mistral dashboard for error details.")
            break
            
        time.sleep(30)  # Poll every 30 seconds

except KeyboardInterrupt:
    elapsed = (time.time() - start_time) / 60
    print(f"\n\nInterrupted after {elapsed:.1f} minutes. Job still running.")
    print(f"Resume monitoring with:")
    print(f"  python -c \"from mistralai import Mistral; import os; c=Mistral(api_key=os.environ['MISTRAL_API_KEY']); s=c.fine_tuning.jobs.get(job_id='{created_job.id}'); print(s.status, getattr(s, 'fine_tuned_model', 'N/A'))\"")
