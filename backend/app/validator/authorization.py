"""Deterministic authorization matching and stable audit identities."""
import hashlib
import json
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any

from ..models import SchedulingContext
from ..models.overrides import OverrideAuthorization

PROTECTED_RULES = {"H01", "R05", "R06", "R07"}
RULE_NAMES = {
    "H01": "每日最多一个班次", "R01": "店长覆盖", "R02": "饮品覆盖",
    "R03": "收银覆盖", "R04": "总人数覆盖", "R05": "每周班次上限",
    "R06": "连续工作天数", "R07": "班次休息", "R08": "请假或不可用", "R09": "员工引用",
}


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def constraint_id(week, rule, day, shift, employee=None) -> str:
    return "constraint_" + fingerprint([str(week), rule, day, shift, employee])[:24]


def context_snapshot(context: SchedulingContext, week_start: date) -> dict:
    payload = context.model_dump(mode="json")
    # Assignments are goals, not changes to the employee's availability.
    payload["employees"] = sorted(payload["employees"], key=lambda item: item["id"])
    for employee in payload["employees"]:
        for key in ("skills", "available_days", "leave_days"):
            employee[key] = sorted(employee[key])
    payload["target_week"] = week_start.isoformat()
    payload.pop("override_scopes", None)
    # Optimization choices do not change the authorization's constraint scope.
    payload.pop("minimize_changes", None)
    return payload


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def authorization_is_active(
    authorization: OverrideAuthorization,
    *,
    week: date,
    base_schedule_id: str | None,
    base_version: int | None,
    scenario_revision: int,
    employee_revision: int,
    rules_fingerprint: str,
    constraint_snapshot_hash: str,
) -> bool:
    return (
        authorization.status in {"ACTIVE", "CONSUMED"}
        and authorization.target_week == week
        and authorization.base_schedule_id == base_schedule_id
        and authorization.base_version == base_version
        and authorization.scenario_revision == scenario_revision
        and authorization.employee_revision == employee_revision
        and authorization.rules_fingerprint == rules_fingerprint
        and authorization.constraint_snapshot_hash == constraint_snapshot_hash
        and (authorization.status == "CONSUMED" or authorization.expires_at > datetime.now(timezone.utc))
    )


def classify_validation(validation: dict, week: date,
                        authorizations: list[OverrideAuthorization] | None = None) -> dict:
    result = deepcopy(validation)
    groups = {name: [] for name in ("authorized_violations", "unauthorized_violations",
                                   "protected_violations", "integrity_violations")}
    ledger = []
    for raw in result.get("violations", []):
        rule = raw["rule_id"]
        details = raw.get("details") or {}
        expected = details.get("expected", details.get("required", details.get("maximum")))
        actual = details.get("actual")
        shortage = max(0, expected - actual) if rule in {"R01", "R02", "R03", "R04"} else None
        cid = constraint_id(week.isoformat(), rule, raw.get("day"), raw.get("shift"), raw.get("employee_id"))
        match = next((item for item in (authorizations or []) if
                      item.status in {"ACTIVE", "CONSUMED"} and
                      (item.status == "CONSUMED" or item.expires_at > datetime.now(timezone.utc)) and
                      item.constraint_id == cid and item.target_week == week and
                      item.rule_id == rule and _value(item.day) == raw.get("day") and
                      _value(item.shift) == raw.get("shift") and item.employee_id == raw.get("employee_id") and
                      (rule == "R08" or (shortage is not None and shortage <= (item.allowed_shortage or 0)))), None)
        group = ("integrity_violations" if rule == "R09" else
                 "protected_violations" if rule in PROTECTED_RULES else
                 "authorized_violations" if match else "unauthorized_violations")
        category = {"integrity_violations": "INTEGRITY_VIOLATION",
                    "protected_violations": "PROTECTED_RULE_VIOLATION",
                    "authorized_violations": "VIOLATED_AUTHORIZED",
                    "unauthorized_violations": "VIOLATED_UNAUTHORIZED"}[group]
        item = {**raw, "violation_id": "vio_" + fingerprint([cid, details, raw["message"]])[:24],
                "rule_name": RULE_NAMES.get(rule, rule), "category": category,
                "constraint_id": cid, "expected": "not_scheduled" if rule == "R08" else expected,
                "actual": "scheduled" if rule == "R08" else actual, "shortage": shortage,
                "excess": max(0, actual - expected) if rule == "R05" and actual is not None else None,
                "authorized": group == "authorized_violations",
                "authorization_id": match.override_id if match else None,
                "authorization_source": match.authorization_source if match else None}
        groups[group].append(item)
        ledger.append(item)
    passed = bool(result.get("passed", result.get("valid", False))) and not ledger
    confirmable = passed or bool(ledger) and not any(groups[key] for key in
                      ("unauthorized_violations", "protected_violations", "integrity_violations"))
    result.update(groups)
    result.update(passed=passed, valid=passed, confirmable=confirmable, violations=ledger,
                  compliance_status="compliant" if passed else "authorized_violations" if confirmable else "invalid")
    for check in result.get("checks", []):
        instances = [item for item in ledger if item["rule_id"] == check["rule_id"]]
        check["classification"] = ("SATISFIED" if check["passed"] else
                                    "INTEGRITY_VIOLATION" if check["rule_id"] == "R09" else
                                    "PROTECTED_RULE_VIOLATION" if check["rule_id"] in PROTECTED_RULES else
                                    "VIOLATED_AUTHORIZED" if instances and all(x["authorized"] for x in instances)
                                    else "VIOLATED_UNAUTHORIZED")
        check["details"] = {"violations": instances}
    return result


def compliance_fields(validation: dict, lifecycle=None) -> dict:
    passed = bool(validation.get("passed", validation.get("valid", False)))
    return {"lifecycle_status": lifecycle,
            "compliance_status": validation.get("compliance_status", "compliant" if passed else "invalid"),
            "confirmable": validation.get("confirmable", passed),
            **{key: validation.get(key, []) for key in ("violations", "authorized_violations",
                "unauthorized_violations", "protected_violations", "integrity_violations")}}
