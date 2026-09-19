# Agent Core live evaluations

Run offline regression with `python -m pytest -q`. Live cases are explicitly skipped
unless `LIVE_AGENT_EVAL=true` and `LLM_API_KEY` is present.

PowerShell, using the project's virtual environment:

```powershell
$env:LIVE_AGENT_EVAL = 'true'
$env:LLM_EVAL_MODEL = 'your-configured-model'
# Per-provider read timeout; default is 120 seconds. Other transport limits are unchanged.
$env:LLM_EVAL_TIMEOUT_SECONDS = '120'
# Complete AgentService turn budget; default is 300 seconds.
$env:LLM_EVAL_TURN_TIMEOUT_SECONDS = '300'
$env:LLM_EVAL_OUTPUT_DIR = 'artifacts/agent-evals/live'
.venv/Scripts/python.exe -m pytest tests/evals -v -rs
```

Configure the existing `LLM_API_KEY`, `LLM_BASE_URL` and `LLM_MODEL` through the
process environment. `LLM_EVAL_MODEL` optionally overrides `LLM_MODEL`.
`LLM_EVAL_TIMEOUT_SECONDS` limits an individual provider request, while
`LLM_EVAL_TURN_TIMEOUT_SECONDS` limits the complete AgentService turn (including
route, read tools and response composition). Keep the turn budget longer than
the provider budget when a case may require multiple model calls.
`LLM_EVAL_CASE_FILE` optionally replaces `agent_cases.json`. Never put keys in case
files or reports. The harness records visible provider content, normalized plans,
parameters, tool outputs, grounded final responses, timeline, latency, model and
prompt version. It never records hidden reasoning or authorization headers.

To load **only LLM settings** from the repository `.env` and execute live cases:
`python -m tests.evals`. This does not load `DATABASE_URL` or `APP_ENV` from `.env`.

Each case gets its own SQLite database from pytest's temporary directory, fixed
employees, two schedule snapshots, current RuleConfig and seeded suggestion
history. `DATABASE_URL` is not used to construct the evaluation database. After
fixture setup, SQL guards and SQLite `query_only` reject writes, and every table
is compared before/after. The dry-run entry point uses the production router,
normalization, week/reference resolver, tools and composer but omits persisted
conversation turns. Normal HTTP/SSE, persistence and idempotency are covered by
the backend and Playwright integration tests.

`case-*.json` and `summary.json` contain pass/fail/skip and deterministic failure
categories: wrong_intent, wrong_week, wrong_day, wrong_shift, wrong_employee,
implicit_history_reference, wrong_tool, forbidden_mutation, fact_mismatch,
hallucinated_fact, incomplete_answer, timeout, provider_error. No LLM judge is
used. An entirely skipped run has a null score, not a passing score. The final
answer is checked sentence-by-sentence against complete deterministic facts;
fixed Sunday employee lists and staffing counts are also checked independently.

Read questions use the workbench week unless explicitly redirected. No explicit
shift means both shifts. Current rules and employee skills are used for facts and
independent validation; missing previous-week history is reported as unknown.
Counterfactuals validate removal and all single-person replacements in memory.
They report re-solve/objective results as unknown/not_run and never claim global
uniqueness. Feasibility questions may run the unchanged CP-SAT solver in memory.

The LLM organizes complete verified sentences through a closed ID schema. It
cannot introduce free-form factual claims. This intentionally trades stylistic
freedom for reproducible, verifiable answers; unsupported general questions still
use the existing assistant path. Multi-day analyses request clarification.
