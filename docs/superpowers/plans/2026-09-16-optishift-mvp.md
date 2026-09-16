# OptiShift AI MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or parallel agents with disjoint file ownership. Do not create or run tests until the user selects T0/T1/T2/T3.

**Goal:** Deliver a single-service React and FastAPI workforce scheduling application whose schedules are produced by OR-Tools, accepted by an independent validator, and persisted through draft/confirm/version lifecycles.

**Architecture:** The React workbench sends structured or parsed requests to FastAPI. FastAPI builds scheduling context from SQLite and employee master data, invokes deterministic CP-SAT, independently validates feasible results, and stores drafts before confirmation. Infeasible requests return structured three-level diagnosis without persisting an invalid schedule.

**Tech Stack:** React, Vite, TypeScript, Tailwind CSS, FastAPI, Pydantic, SQLite, OR-Tools CP-SAT.

**Spec:** `C:\Users\LEGION\Downloads\AI智能排班助手_最终架构与实施说明_含Solver(1).md`

## Global Constraints

- LLM may parse intent, resolve candidates, or polish factual explanations; it never schedules.
- H01 and R01 through R09 remain hard in the primary solver.
- The independent validator must pass before a draft can be confirmed.
- Replan requires an explicit confirmed base schedule and matching version.
- Diagnostic output can explain shortages but can never be saved as a schedule.
- Employee skills come only from master data and cannot be edited through the ordinary UI.
- No test code or test execution before the user chooses the requested test level.

## Work Items

- [ ] Build domain models, deterministic seed data, rules, primary solver, validator, and diagnosis.
- [ ] Build SQLite repositories, lifecycle services, request validation, diff, explanations, and FastAPI routes.
- [ ] Build the schedule workbench, employee view and management, rules center, diff, diagnosis, and entity clarification UI.
- [ ] Integrate the backend and frontend contracts and serve the production frontend from FastAPI.
- [ ] Add single-image Docker packaging, environment examples, logging, and run documentation.
- [ ] Recommend a test level and wait for the user's T0/T1/T2/T3 choice.
- [ ] After authorization, add the explicitly requested test suites at the selected level, execute verification, and fix failures.
- [ ] Run the authorized business flows and provide evidence-backed delivery results.
