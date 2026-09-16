from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..models import Schedule, ScheduleChange, WEEK_DAYS, SHIFTS


def build_diff(
    base: Schedule | None,
    current: Schedule,
    requested_changes: list[ScheduleChange] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    base_set = (
        {(a.employee_id, a.day.value, a.shift.value) for a in base.assignments}
        if base
        else set()
    )
    current_set = {
        (a.employee_id, a.day.value, a.shift.value) for a in current.assignments
    }
    added = sorted(current_set - base_set)
    removed = sorted(base_set - current_set)
    unchanged = sorted(base_set & current_set)
    by_shift: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(
        lambda: {"added": [], "removed": [], "unchanged": []}
    )
    for employee_id, day, shift in added:
        by_shift[(day, shift)]["added"].append(employee_id)
    for employee_id, day, shift in removed:
        by_shift[(day, shift)]["removed"].append(employee_id)
    for employee_id, day, shift in unchanged:
        by_shift[(day, shift)]["unchanged"].append(employee_id)
    shifts = [
        {"day": day, "shift": shift, **changes}
        for (day, shift), changes in sorted(by_shift.items())
        if changes["added"] or changes["removed"]
    ]
    affected = sorted({item[0] for item in added + removed})
    direct_ids = {change.employee_id for change in requested_changes or []}
    direct = sorted(set(affected) & direct_ids)
    related = sorted(set(affected) - direct_ids)
    changed_shift_count = sum(
        1 for changes in by_shift.values() if changes["added"] or changes["removed"]
    )
    diff = {
        "added": [
            {"employee_id": employee_id, "day": day, "shift": shift}
            for employee_id, day, shift in added
        ],
        "removed": [
            {"employee_id": employee_id, "day": day, "shift": shift}
            for employee_id, day, shift in removed
        ],
        "unchanged": [
            {"employee_id": employee_id, "day": day, "shift": shift}
            for employee_id, day, shift in unchanged
        ],
        "shifts": shifts,
        "changed_shifts": changed_shift_count,
        "affected_employees": affected,
        "unchanged_shifts": max(0, len(WEEK_DAYS) * len(SHIFTS) - changed_shift_count),
        "hard_violations": 0,
    }
    impact = {
        "direct_changes": direct,
        "related_changes": related,
        "unchanged_shifts": diff["unchanged_shifts"],
        "total_shifts": len(WEEK_DAYS) * len(SHIFTS),
    }
    return diff, impact
