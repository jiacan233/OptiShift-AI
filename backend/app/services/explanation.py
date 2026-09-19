from __future__ import annotations

import logging
import os
from contextlib import nullcontext
from typing import Any

from ..execution import current_execution, traced
from ..models import Employee, Schedule
from .llm_client import AgentLLMClient

logger = logging.getLogger("optishift.explanation")


class ExplanationService:
    """Build a factual template first and optionally polish the same facts."""

    def __init__(self, llm: AgentLLMClient | None = None):
        self.llm = llm

    @traced("explanation")
    def build(
        self,
        schedule: Schedule,
        employees: list[Employee],
        validation: dict[str, Any],
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        employee_map = {employee.id: employee for employee in employees}
        preference_matches = int(
            metrics.get(
                "preference_satisfied",
                sum(
                    1
                    for assignment in schedule.assignments
                    if employee_map[assignment.employee_id].preferred_shift == assignment.shift
                ),
            )
        )
        base = (
            f"Generated {len(schedule.assignments)} assignments for the week of "
            f"{schedule.week_start.isoformat()}. "
            f"{validation.get('passed_count', 0)}/{validation.get('total', 10)} hard checks pass. "
            f"{preference_matches} assignments match employee shift preferences."
        )
        if validation.get("compliance_status") == "authorized_violations":
            base += f" {len(validation.get('authorized_violations', []))} explicitly authorized exceptions remain; this schedule is not fully compliant."
            return {"text": base, "source": "deterministic_template", "llm_fallback": True}
        if os.getenv("LLM_ENABLED", "").lower() not in {"1", "true", "yes"}:
            return {"text": base, "source": "deterministic_template", "llm_fallback": True}
        api_key = os.getenv("LLM_API_KEY", "").strip()
        if not api_key:
            logger.info("llm_fallback_triggered reason=missing_api_key operation=explanation")
            return {
                "text": base,
                "source": "deterministic_template",
                "llm_fallback": True,
                "fallback_reason": "missing_api_key",
            }
        try:
            trace = current_execution.get()
            if trace and trace.remaining("explanation") < 5:
                return {"text": base, "source": "deterministic_template", "llm_fallback": True}
            with nullcontext(self.llm) if self.llm else AgentLLMClient() as client:
                text = client.complete_text(
                    stage="explanation",
                    system="Rewrite this scheduling summary clearly. Preserve every fact and number; add no reasoning or claims.",
                    user={"summary": base},
                )
            return {"text": text or base, "source": "llm_polished", "llm_fallback": False}
        except Exception as exc:
            logger.info(
                "llm_fallback_triggered reason=%s operation=explanation",
                type(exc).__name__,
            )
            return {
                "text": base,
                "source": "deterministic_template",
                "llm_fallback": True,
                "fallback_reason": type(exc).__name__,
            }


def normalize_validation(result: Any) -> dict[str, Any]:
    raw = result.model_dump(mode="json") if hasattr(result, "model_dump") else dict(result)
    hard_constraints = raw.get("hard_constraints", {})
    checks = []
    for rule_id, check in hard_constraints.items():
        violations = check.get("violations", [])
        checks.append(
            {
                "rule_id": rule_id,
                "passed": check.get("passed", False),
                "message": (
                    "Passed"
                    if check.get("passed", False)
                    else "; ".join(item.get("message", "Violation") for item in violations)
                ),
                "details": {"violations": violations},
            }
        )
    valid = bool(raw.get("valid", False))
    return {
        "passed": valid,
        "valid": valid,
        "confirmable": valid,
        "compliance_status": "compliant" if valid else "invalid",
        "coverage": raw.get("coverage", []),
        "total": raw.get("total_count", len(checks)),
        "total_count": raw.get("total_count", len(checks)),
        "passed_count": raw.get("passed_count", sum(c["passed"] for c in checks)),
        "checks": checks,
        "hard_constraints": hard_constraints,
        "violations": raw.get("violations", []),
        "authorized_violations": [],
        "unauthorized_violations": [],
        "protected_violations": [],
        "integrity_violations": [],
    }
