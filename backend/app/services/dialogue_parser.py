"""Bounded slot parsing against explicit, week-scoped identities (never raw history)."""
import re

from ..models.dialogue import ConditionEdit, TurnCommand
from ..models.domain import ChangeType, Shift
from .intent_parser import IntentParser
from .router_stages import RouterRun, parse_stage


def number(text):
    match = re.search(r"(?:这|那|当前|现在|最终)?\s*([一二两三四五六七八九十\d]+)\s*(?:个条件|条|个要求|项|个人|个最终条件)", text)
    if not match:
        return None
    raw = match.group(1)
    return int(raw) if raw.isdigit() else {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}.get(raw)


def kind(text):
    if re.search(r"优先|偏好|prefer", text, re.I):
        return ChangeType.PREFERENCE
    if re.search(r"请假|leave", text, re.I):
        return ChangeType.LEAVE
    if re.search(r"不可排|不能排|不上班|不排班|不要排|不可用|不能上|都不上|unavailable", text, re.I):
        return ChangeType.UNAVAILABLE
    if re.search(r"去掉|移出|调.*出去|撤下|unassign", text, re.I):
        return ChangeType.UNASSIGN
    if re.search(r"允许|可以上|恢复可用|available", text, re.I):
        return ChangeType.AVAILABLE
    if re.search(r"上班|让.*上|放进|排进|排到|安排|assign", text, re.I) or re.search(r"[早晚]班上", text):
        return ChangeType.ASSIGN
    return None


def deterministic_command(text, state, employees):
    normalized = text.strip().rstrip("。.!！")
    ids = list(dict.fromkeys(re.findall(r"(?<![A-Za-z0-9_])E\d{2}(?![A-Za-z0-9_])", text, re.I)))
    ids = [item.upper() for item in ids]
    days = IntentParser.extract_days(text)
    shifts = [v for v, token in [(Shift.MORNING, "早班"), (Shift.EVENING, "晚班")] if token in text]
    shift = shifts[0] if len(shifts) == 1 else None
    command = TurnCommand()
    suppress = bool(re.search(r"(?:先别|先不要|不要真的|不要|不许|别|先不)[^，。；]{0,5}(?:生成|执行|重排|排班|强制)|先别排", text))
    execute = bool(re.search(r"重新排|重排|生成|排一版|帮我排|保存当前方案|采用当前方案", text)) and not suppress
    preview = bool(re.search(r"试排|preview", text, re.I))
    hypothetical = bool(re.search(r"如果.*(?:怎样|影响|合适|如何)|会怎样|先分析|先不要.*你先分析|可不可以|先不要改|先分析，不要改", text))
    advice = bool(re.search(r"(?:给我|给出|提供).*(?:方案|建议)|优化方案|拆成具体调整", text))
    explicit_record = bool(re.search(r"记住|记录|设成|设为", text))
    reference = bool(re.search(r"条件|要求|这[一二两三四\d]|最终|当前方案|修正后的|一出一进|现在.*重排", text))
    if execute:
        command.execution = "create_draft"
    elif advice:
        command.execution = "advice"
    elif preview:
        command.execution = "preview"
    elif hypothetical:
        command.execution = "analyze"
    command.expected_count = number(text) if reference else None
    if re.search(r"(?:再加|加一|添加|增加).*?[一二两三\d]+(?:个|条)", text) and not execute:
        command.expected_count = None
    command.reference = "current" if reference else "none"
    command.minimize_changes = bool(re.search(r"少改|少动|最小改动", text))
    command.adopt = explicit_record and bool(state.proposals)
    # A reference to an immutable card and a natural-language ordinal are distinct.
    exact = re.search(r"sug_[a-zA-Z0-9_]+", text)
    ordinal = re.search(r"第\s*([一二两三四五\d]+)\s*(?:条|个方案|个建议)", text)
    if exact or ordinal:
        command.reference = "suggestion"
        command.suggestion_id = exact.group() if exact else None
        raw = ordinal.group(1) if ordinal else None
        command.suggestion_ordinal = int(raw) if raw and raw.isdigit() else {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}.get(raw)
        command.adopt = bool(re.search(r"采纳|采用|按.*(?:改|排)|应用", text))
        command.inspect = not command.adopt
        command.expected_count = None
        return command
    correction = re.search(r"不是\s*周[一二三四五六日天]，?\s*是\s*周[一二三四五六日天]", text)
    if correction and len(days) == 2:
        command.edits = [ConditionEdit(operation="correct", days=[days[-1]], old_day=days[0])]
        command.execution = "none"
        return command
    if re.search(r"(?:取消|撤销|不要了).*(?:待补|待完成|这个动作)|(?:这个|刚才的).*(?:不调了|不用补|取消)|取消.*pending", text, re.I):
        command.edits = [ConditionEdit(operation="cancel_pending")]
        return command
    remove = bool(re.search(r"取消|撤销|不要了|那个不要|这个不要|保持原样", text))
    if remove:
        command.edits.append(ConditionEdit(operation="remove", employee_ids=ids,
            days=days[:1] if len(days) > 1 else days, type=ChangeType.LEAVE if "取消" in text and "请假" in text else None))
        # Explicit keep is a separate operation, reduced atomically with removal.
        keep = re.search(r"保留(.+)", text)
        if keep:
            tail = keep.group(1)
            command.edits.append(ConditionEdit(employee_ids=re.findall(r"E\d{2}", tail) or ids,
                days=IntentParser.extract_days(tail) or days, shift=shift, type=kind(tail)))
        command.execution = "none"
        return command
    inspect = bool(re.search(r"复述|说一遍|理解|有效的|最终条件|准备改哪|准备执行几|还有没有限制|旧条件|具体条件|不存在|具体是哪几|记住|作用的目标周", text))
    if inspect and not re.search(r"改成|再加|来理解", text):
        command.inspect = True
        return command
    # A slot answer only binds a single existing pending action.
    slot_only = bool(re.fullmatch(r"(?:E\d{2}|周[一二三四五六日天]|[早晚]班)(?:[。.!！])?", text.strip(), re.I))
    if slot_only or re.fullmatch(r"(?:班次)?还是[早晚]班[。.!！]?", text.strip()):
        if state.pending:
            command.edits = [ConditionEdit(employee_ids=ids, days=days, shift=shift)]
        elif ids:
            command.edits = [ConditionEdit(operation="focus", employee_ids=ids)]
        elif state.focus and state.focus.kind in {"condition", "proposal"} and shift:
            command.edits = [ConditionEdit(operation="correct", shift=shift)]
        else:
            command.clarification = "当前周没有可补充的动作，请说明这个日期或班次对应的员工和要求。"
        return command
    # Reporting facts, checking absence and reasons must not manufacture edits.
    read = bool(re.search(r"怎么排|排了几个|为什么|哪些|有哪些|是谁|谁的|列出来|主要会违反|最少恢复哪个|会影响谁", text))
    if read and not hypothetical and not execute and not advice and not re.search(r"再加|改成|最终想要", text):
        return None
    fragments = re.split(r"[，,。；;]|(?=(?<![A-Za-z0-9_])E\d{2}(?![A-Za-z0-9_]))", text)
    # Employee splitting retains the opening verb for phrases such as 把E11从…去掉.
    current_ids = ids[:1] if len(ids) == 1 else []
    for fragment in fragments:
        fragment_ids = re.findall(r"(?<![A-Za-z0-9_])E\d{2}(?![A-Za-z0-9_])", fragment, re.I)
        if fragment_ids:
            current_ids = [x.upper() for x in fragment_ids]
        fragment_days = IntentParser.extract_days(fragment)
        fragment_shift = next((v for v, token in [(Shift.MORNING, "早班"), (Shift.EVENING, "晚班")] if token in fragment), None)
        change_kind = kind(fragment)
        if not change_kind:
            continue
        if not fragment_days and not fragment_ids and not (state.pending and re.search(r"他|她|上班", fragment)):
            continue
        if re.search(r"其他.*还是|其他.*不能", fragment):
            continue
        group_skill = "manager" if re.search(r"所有.*manager|manager.*都", text, re.I) else None
        resolved_ids = current_ids
        if not resolved_ids and re.search(r"他|她|那个人|让", fragment) and len(state.employee_focus) == 1:
            resolved_ids = state.employee_focus
        command.edits.append(ConditionEdit(employee_ids=resolved_ids,
            days=fragment_days, shift=fragment_shift, type=change_kind,
            proposal=(hypothetical or preview) and not explicit_record, group_skill=group_skill))
    if not command.edits and (re.search(r"我想调|我要调|想让他上班|我选E", text)):
        if re.search(r"[二两三四五\d]+个人", text) and not ids:
            command.inspect = True
            command.expected_count = None
            return command
        command.edits = [ConditionEdit(employee_ids=ids, type=kind(text))]
    if command.edits:
        # A vague preface with a headcount is not an execution collection reference.
        if not days and not any(e.days for e in command.edits):
            command.expected_count = None
        return command
    if execute or preview or advice or explicit_record:
        if execute and state.current():
            command.reference = "current"
        command.explicit_empty = execute and not reference and not state.current()
        return command
    if state.current() and re.search(r"检查|分析|冲突|影响|这样|这样呢|可行|合规|几条|条件|工作量.*高|最小|少改|少动", text):
        command.inspect = True
        command.execution = "analyze" if re.search(r"检查|分析|影响|可行|合规", text) else "none"
        command.reference = "current"
        return command
    return None


def parse_command(text, state, employees, llm):
    command = deterministic_command(text, state, employees)
    if command is not None:
        return command
    # Existing read router handles ordinary fact questions. Use a semantic parser
    # only for action language beyond the deterministic grammar.
    if not re.search(r"希望|打算|帮.*调|改一下|换成|挪|安排成|想让|采纳", text):
        return None
    if not llm.enabled:
        return TurnCommand(clarification="请说明要修改的员工、日期、班次或要采纳的条件。")
    return parse_stage(llm, RouterRun(), TurnCommand, name="agent_dialogue", system=(
        "Parse only the current user turn into a typed scheduling command. Use the supplied week-scoped "
        "state for explicit references and pronouns, never invent slots. Full conditions are record-only "
        "by default. Hypotheses are proposals. create_draft requires explicit present-turn execution; "
        "先别生成 prevents execution but preserves edits. Corrections target exact ids; removals match "
        "the stated scope. Incomplete operations preserve known slots. Do not authorize force. "
        "Return clarification on ambiguous references. source must be semantic_parser."),
        user={"text": text, "state": state.model_dump(mode="json"),
              "known_employee_ids": [e.id for e in employees]})
