"""Grounded response composition: the model orders facts, never authors facts.

Each complete sentence is rendered from a typed tool result. The LLM may organize
these sentences through a closed ID schema. Invalid/incomplete output falls back
to the deterministic order, so a number whitelist cannot accidentally accept a
correct number attributed to the wrong shift or employee.
"""
from __future__ import annotations

from ..execution import execution_stage
from .llm_client import AIUnavailableError
from .read_query import PROMPT_VERSION, ReadQueryPlan

DAYS = dict(zip(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"), ("周一", "周二", "周三", "周四", "周五", "周六", "周日")))
SHIFTS = {"morning": "早班", "evening": "晚班"}
READ_ONLY_NOTICE = "当前只是分析，没有修改排班。"


def fact_sentences(plan: ReadQueryPlan, facts: dict) -> list[str]:
    sentences = []
    if facts.get("status") == "no_schedule":
        sentences.append("目标周没有找到指定版本的排班。" if plan.version else "目标周当前没有可展示的排班。")
    else:
        status = {"draft": "草稿", "confirmed": "已确认版本", "cancelled": "已取消版本"}.get(facts.get("schedule_status"), "排班")
        sentences.append(f"读取 {facts['target_week']} 周的{status} v{facts['version']}（{facts['schedule_id']}）。")
    if facts.get("clarification"):
        sentences.append(facts["clarification"])
    show_slots = plan.question_type in {"schedule_overview", "staffing_explanation", "assignment_explanation", "coverage_analysis"}
    if show_slots:
        for slot in facts.get("slots", []):
            label = DAYS[slot["day"]] + SHIFTS[slot["shift"]]
            coverage = "；".join(f"{name} {slot[key]['actual']}/{slot[key]['required']}（{'达标' if slot[key]['passed'] else '不足'}）"
                                for key, name in (("manager", "店长"), ("beverage", "饮品"), ("cashier", "收银")))
            sentences.append(f"{label}：实际 {slot['actual_staff']} 人，最低 {slot['minimum_staff']} 人，超出最低人数 {slot['excess_staff']} 人；{coverage}。")
            if "assignments" in plan.requested_facts:
                sentences.append(f"{label}上班员工：{'、'.join(a['employee_id'] for a in slot['assignments']) or '无'}。")
                if plan.question_type == "coverage_analysis":
                    for key, name in (("manager", "店长"), ("beverage", "饮品"), ("cashier", "收银")):
                        sentences.append(f"{label}具备{name}技能：{'、'.join(a['employee_id'] for a in slot['assignments'] if key in a['skills']) or '无'}。")
        if plan.question_type == "staffing_explanation":
            sentences.append("最低人数是下限，不要求恰好等于该人数；超出下限不直接违反人数规则。仅凭人数不能判断移除人员后是否可行，还需检查技能覆盖和全周规则。")
    for employee in facts.get("employees", []) if plan.question_type == "assignment_explanation" else []:
        assignments = "、".join(DAYS[a['day']] + SHIFTS[a['shift']] for a in employee['assignments']) or "没有排班"
        sentences.append(f"{employee['id']} 在所查范围：{assignments}；本周共 {employee['weekly_shifts']} 个班次；技能为 {'、'.join(employee['skills'])}。")
        if plan.day:
            unavailable = plan.day.value not in employee["available_days"] or plan.day.value in employee["leave_days"]
            changes = [c for c in employee["requested_changes"] if c["day"] == plan.day.value]
            sentences.append(f"{employee['id']} 在{DAYS[plan.day.value]}的主数据状态：{'不可用或请假' if unavailable else '可用'}；该日排班记录的临时条件：{'、'.join(c['type'] for c in changes) or '无'}。")
        sentences.append("这些是安排事实，不构成唯一原因证明；是否必须由该员工上班，需要反事实验证。")
    if plan.question_type == "employee_workload" and facts.get("workload"):
        workload = facts["workload"]
        highest = max(workload.values())
        sentences.append(f"本周最多 {highest} 个班次：{'、'.join(e for e, n in workload.items() if n == highest)}。")
        sentences.append("各员工班次数：" + "；".join(f"{e}：{n}" for e, n in workload.items()) + "。")
    validation = facts.get("validation")
    if validation and plan.question_type in {"coverage_analysis", "staffing_explanation", "feasibility_explanation"}:
        violations = sorted({v["rule_id"] for v in validation["violations"]})
        sentences.append("独立校验发现违规：" + "、".join(violations) + "。" if violations else "已检查的规则未发现违规。")
        if validation.get("unknown_rules"):
            sentences.append("缺少上周历史，R06、R07 跨周条件尚不能完整验证，不能宣称全周合规。")
    if plan.question_type == "rule_explanation" and facts.get("rules"):
        r = facts["rules"]
        sentences.append(f"每班店长技能至少 {r['manager_per_shift']} 人、饮品技能至少 {r['beverage_per_shift']} 人、收银技能至少 {r['cashier_per_shift']} 人；工作日每班至少 {r['weekday_min_staff']} 人，周末每班至少 {r['weekend_min_staff']} 人。每人每周最多 {r['max_shifts_per_week']} 班，最多连续工作 {r['max_consecutive_days']} 天。每天最多一班，晚班后次日不能早班，请假或不可用人员不能安排。")
    if plan.question_type == "schedule_difference":
        diff = facts.get("difference")
        if diff is None:
            sentences.append("没有可比较的上一版本。")
        else:
            sentences.append(f"对比 v{facts['comparison_version']}：新增 {len(diff['added'])} 个 assignment，移除 {len(diff['removed'])} 个 assignment。")
            for key, label in (("added", "新增"), ("removed", "移除")):
                for a in diff[key]:
                    sentences.append(f"{label} {a['employee_id']} {DAYS[a['day']]}{SHIFTS[a['shift']]}。")
    for item in facts.get("counterfactuals", []):
        label = f"移除 {item['employee_id']} {DAYS[item['day']]}{SHIFTS[item['shift']]}"
        rule_ids = sorted({v["rule_id"] for v in item["slot_violations"]})
        sentences.append(f"{label}：{'当前班次人数和技能覆盖仍达标' if item['direct_removal_slot_passed'] else '当前班次违规 ' + '、'.join(rule_ids)}；全周校验{'通过' if item['direct_removal_valid'] is True else '未通过' if item['direct_removal_valid'] is False else '缺少历史，结论未知'}。")
        sentences.append(f"{label}后的已验证替代人选：{'、'.join(item['replacement_employee_ids']) or '未找到单人直接替代'}；该员工工作量减少 1 班。未重新求解，目标值变化未知，未证明该员工唯一必要。")
    feasibility = facts.get("feasibility")
    if feasibility:
        labels = {"optimal": "当前条件存在可行排班", "feasible": "当前条件存在可行排班", "infeasible": "当前条件下不可行", "unknown": "求解尚不能确定可行性", "history_unavailable": "缺少上周排班，无法完整判断可行性"}
        sentences.append(labels.get(feasibility["status"], "可行性未确定") + "；这是内存分析，没有保存求解结果。")
        for conflict in (feasibility.get("diagnosis") or {}).get("capacity_conflicts", []):
            sentences.append(f"{DAYS[conflict['day']]}{SHIFTS[conflict['shift']]} {conflict['rule_id']}：需要 {conflict['required']}，可用 {conflict['available']}，缺口 {conflict['shortage']}。")
    if plan.question_type == "general_question":
        sentences.append("可以查询排班人数、员工安排、技能覆盖、工作量、规则和版本差异；请说明要分析的对象。")
    return sentences


def compose_read_answer(llm, *, question: str, plan: ReadQueryPlan, facts: dict) -> tuple[str, dict]:
    sentences = fact_sentences(plan, facts)
    ids = [f"fact_{i}" for i in range(len(sentences))]
    audit = {"prompt_version": PROMPT_VERSION, "composition_mode": "deterministic", "sentence_ids": ids}
    order = ids
    with execution_stage("response_compose"):
        if llm.enabled:
            try:
                payload = llm.complete_json(
                    system="Organize a concise Chinese answer using the supplied verified sentences. Return every sentence ID exactly once in a helpful order, conclusion first. You may not author facts, omit evidence, or add sentences.",
                    user={"prompt_version": PROMPT_VERSION, "question": question,
                          "query_plan": plan.model_dump(mode="json"), "sentences": dict(zip(ids, sentences))},
                    stage="response_compose", schema_name="grounded_read_answer",
                    schema={"type": "object", "properties": {"sentence_ids": {"type": "array", "items": {"type": "string", "enum": ids}}}, "required": ["sentence_ids"], "additionalProperties": False},
                )
                proposed = payload.get("sentence_ids")
                if isinstance(proposed, list) and len(proposed) == len(ids) and set(proposed) == set(ids):
                    order = proposed
                    audit["composition_mode"] = "llm_grounded"
                else:
                    audit["fallback_reason"] = "invalid_sentence_selection"
            except AIUnavailableError as exc:
                audit["fallback_reason"] = exc.error_type
    lookup = dict(zip(ids, sentences))
    return "\n\n".join([*(lookup[key] for key in order), READ_ONLY_NOTICE]), audit
