# OptiShift-AI Agent Guide

## Default rule

Do not scan the entire repository unless explicitly necessary.

Never read generated artifacts, screenshots, logs, transcripts, or historical acceptance outputs by default.

## Main architecture

Frontend Agent flow:
- `frontend/src/components/agent/`
- `frontend/src/store/AgentStore.tsx`
- `frontend/src/api/client.ts`

Backend Agent orchestration:
- `backend/app/services/agent_service.py`

Intent / routing:
- `backend/app/services/agent_router.py`
- `backend/app/services/dialogue_*.py`
- `backend/app/services/intent_parser.py`
- `backend/app/services/agent_context.py`

Agent tools:
- `backend/app/services/agent_tools.py`

Scheduling:
- `backend/app/services/scheduling_service.py`

Solver:
- `backend/app/solver/`

Validation:
- `backend/app/validator/`

Persistence:
- `backend/app/repository/`

API:
- `backend/app/api/`

## Scheduling request reading order

For Agent / scheduling bugs, read only as needed:
1. Relevant frontend component/store (`frontend/src/components/agent/`, `frontend/src/store/AgentStore.tsx`)
2. Frontend API client (`frontend/src/api/client.ts`)
3. `backend/app/services/agent_service.py`
4. `backend/app/services/agent_router.py`
5. Dialogue state/parser/reducer (`backend/app/services/dialogue_*.py`) if multi-turn related
6. `backend/app/services/agent_tools.py`
7. `backend/app/services/scheduling_service.py`
8. Solver / validator (`backend/app/solver/`, `backend/app/validator/`) only if the issue actually reaches scheduling
9. Repository (`backend/app/repository/`) only when persistence/state is involved

## Do not read by default

- `artifacts/`
- `tests/acceptance/screenshots/`
- `report/*.png`
- Browser page-source dumps (`*.html`)
- Playwright output
- Historical logs (`*.log`)
- Generated transcripts (`transcript.json`, etc.)

Only inspect those when the task explicitly concerns a specific test result or historical run.

## Modification rule

Before changing code:
- Identify the smallest affected execution path.
- Avoid unrelated refactors.
- Preserve current Draft / Preview / Confirm / Cancel semantics.
- Preserve Force Generate violation reporting.
- Preserve multi-turn Scenario/Pending Action state unless the task explicitly changes it.

## Tests

Run the smallest relevant tests first.

Do not run every acceptance suite just to make a small code change unless specifically requested.

Production deployment and full acceptance testing are separate concerns.

## Git safety

Never use:
- `git reset --hard`
- `git clean -fd`
- Force push (`git push --force`, `git push --force-with-lease`)

without explicit user approval.
