from __future__ import annotations

import os
import logging
from typing import Any

import httpx

from ..models import Employee, Schedule


logger = logging.getLogger("optishift.explanation")


class ExplanationService:
    """Build a factual template first and optionally polish the same facts."""

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
            response = httpx.post(
                f"{os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1').rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
                    "temperature": 0,
                    "max_tokens": 180,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Rewrite the supplied scheduling summary clearly. Preserve every fact and number; add no reasoning or claims.",
                        },
                        {"role": "user", "content": base},
                    ],
                },
                timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "5")),
            )
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"].strip()
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
        "total": raw.get("total_count", len(checks)),
        "total_count": raw.get("total_count", len(checks)),
        "passed_count": raw.get("passed_count", sum(c["passed"] for c in checks)),
        "checks": checks,
        "hard_constraints": hard_constraints,
        "violations": raw.get("violations", []),
    }
