"""Deterministic R04 preflight for persisted Pending Actions."""
from ..models import Day, Shift, OverrideScope
from ..models.dialogue import PendingAction


DAYS = dict(zip(Day, ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]))
SHIFTS = {Shift.MORNING: "早班", Shift.EVENING: "晚班"}


def force_dependencies(deps):
    # Pending records and revision counters change when saving the question.
    # Actual conditions, headcounts, schedule/rule/employee/history snapshots
    # must still match when the user confirms it.
    return {k: v for k, v in deps.items() if k not in {"scenario_hash", "scenario_revision"}}


def staffing_confirmation(constraints, rules, message_id):
    prompts, scopes, requested = [], {}, []
    for constraint in constraints:
        limit = constraint.max_count if constraint.max_count is not None else constraint.target_count
        conflicted = False
        for day in constraint.days:
            units = [[s] for s in constraint.shifts] if constraint.scope == "SHIFT" else [list(Shift)]
            for shifts in units:
                minimum = sum(rules.minimum_staff(day, shift) for shift in shifts)
                if limit is None or limit >= minimum:
                    continue
                conflicted = True
                label = DAYS[day] + (SHIFTS[shifts[0]] if constraint.scope == "SHIFT" else "")
                prompts.append(f"{label}当前规则至少需要{minimum}人，按{limit}人排班会违反R04，确定仍按{limit}人排吗？")
                deficit = minimum - limit
                for shift in shifts:
                    shortage = min(deficit, rules.minimum_staff(day, shift))
                    if shortage:
                        key = (day, shift)
                        scopes[key] = max(scopes.get(key, 0), shortage)
        # Once confirmed, the low soft goal must constrain the Force solver;
        # otherwise minimizing exceptions would silently return the baseline.
        requested.append(constraint.model_copy(update={"max_count": limit}) if conflicted else constraint)
    if not prompts:
        return None
    return PendingAction(kind="force_staffing", source_message_id=message_id,
        execution_on_complete="create_draft", prompt="\n".join(prompts),
        staffing_constraints=requested,
        requested_overrides=[OverrideScope(rule_id="R04", day=d, shift=s, allowed_shortage=n)
                             for (d, s), n in scopes.items()])
