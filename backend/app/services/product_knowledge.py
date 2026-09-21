from __future__ import annotations

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass
from ..execution import traced


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class ProductKnowledgeEntry:
    id: str
    name: str
    aliases: tuple[str, ...]
    description: str
    what_happens: str
    side_effects: str
    requires_state: str | None = None
    chat_executable: bool = False
    requires_manual_action: bool = False
    limitations: str = ""
    design_rationale: str = "先预览、校验，再由用户决定是否应用。"


CATALOG: tuple[ProductKnowledgeEntry, ...] = (
    ProductKnowledgeEntry("assistant.identity", "OptiShift AI", ("你是谁", "你叫什么"), "我是 OptiShift AI 排班助手。", "我可以基于当前员工、规则和排班数据回答问题并提出排班草稿。", "不会仅因聊天修改正式排班。"),
    ProductKnowledgeEntry("assistant.capabilities", "助手能力", ("你能干嘛", "你能做什么", "你可以做什么", "支持什么", "你的能力"), "我可以查询排班和员工安排、解释规则、分析人数与技能覆盖、工作量和可行性，提供建议、生成草稿并按明确条件重新排班；强制生成需要精确授权。", "排班操作经过求解和独立校验。", "不能通过聊天确认正式排班、修改员工主数据、编造员工日期规则或静默忽略硬规则。"),
    ProductKnowledgeEntry("workflow.draft", "排班草稿", ("草稿", "draft", "候选方案"), "草稿是 Solver 生成、等待人工检查的候选排班版本。", "草稿会显示在工作台供检查。", "会产生待确认版本，但不会改变正式确认版本。", chat_executable=False, requires_manual_action=True),
    ProductKnowledgeEntry("workflow.confirm", "确认生效", ("确认生效", "确认按钮", "确认这个版本", "应用版本"), "确认生效会把当前有效草稿设为正式排班版本。", "正式排班版本发生改变。", "聊天不能直接确认排班，请在工作台检查草稿后手动确认。", "必须存在有效草稿。", False, True),
    ProductKnowledgeEntry("workflow.cancel_draft", "取消草稿", ("取消草稿", "撤销草稿"), "取消草稿会放弃当前待确认的候选版本。", "待确认草稿不再作为候选版本。", "不会修改已确认的正式排班。", "必须存在有效草稿。", False, True),
    ProductKnowledgeEntry("workflow.replan", "重新排班", ("重新排班", "重新排", "重排", "replan"), "可以根据明确条件重新求解当前正式排班，并尽量减少改动。", "成功后创建新的待确认草稿，不会自动发布。", "仍受当前规则、独立校验、待确认草稿和版本保护约束。", "目标周须有正式排班，且没有待确认草稿。", True, limitations="能力询问本身不会执行重排。"),
    ProductKnowledgeEntry("workflow.force_generate", "强制生成", ("强制生成", "force generate"), "强制生成是在明确授权范围内生成带有授权冲突标记的草稿。", "生成结果会保留授权冲突并要求人工检查。", "不会绕过未授权规则，也不会直接确认正式版本。", "覆盖缺口需要规则、日期、班次和缺口上限；请假或不可用例外需要员工、日期和班次。", True, limitations="仅支持现有授权范围；工时、连续工作、晚转早及员工技能来源不能由 Force 覆盖。询问能力不构成授权。"),
    ProductKnowledgeEntry("ui.employee_view", "员工视图", ("员工视图", "按员工看"), "员工视图按员工组织排班，便于查看每个人的班次和负荷。", "只改变工作台的展示方式。", "不会改变排班数据。"),
    ProductKnowledgeEntry("ui.date_view", "日期视图", ("日期视图", "按日期看"), "日期视图按日期和班次组织排班，便于查看每天的覆盖情况。", "只改变工作台的展示方式。", "不会改变排班数据。"),
    ProductKnowledgeEntry("ui.ai_health", "检测 AI", ("检测 AI", "检测AI", "AI 健康", "AI health"), "检测 AI 用于检查当前 AI 服务的连通性与路由解析能力。", "点击后会发起真实 AI 健康检查，并显示结果。", "不会生成、修改或确认排班。", requires_manual_action=True),
    ProductKnowledgeEntry("workflow.generate", "生成排班", ("生成排班", "生成草稿", "生成本周排班"), "可以根据当前员工数据和排班规则生成排班草稿。", "可行结果经独立校验后保存为草稿，等待工作台手动确认。", "正式排班不会自动改变。", "目标周没有待确认草稿，且具备校验需要的历史数据。", True),
    ProductKnowledgeEntry("workflow.current", "当前版", ("当前版", "正式版本"), "当前版是工作台中当前正式生效的排班。", "可以和草稿方案预览比较。", "切换预览不会应用草稿。"),
    ProductKnowledgeEntry("workflow.candidate", "智能排班方案", ("智能排班方案", "候选方案", "Candidate Plan"), "方案区展示真实的当前版和待确认的草稿方案。", "选择卡片可预览对应排班，并查看与当前版的比较。", "选择卡片不会确认草稿。", limitations="只有真实草稿支持工作台手动确认，不会自动发布候选方案。"),
    ProductKnowledgeEntry("ui.rules", "规则页面", ("规则页面", "规则页"), "规则页面展示当前排班规则。", "实际规则来自服务端规则目录，校验器按当前规则检查排班。", "查看规则不会改变排班。"),
    ProductKnowledgeEntry("workflow.scenario", "场景试排", ("场景试排", "试排方案"), "场景试排保存本会话的临时排班条件并分析可行性。", "返回预览、覆盖缺口或建议；采用当前方案时才尝试保存草稿。", "试排不等于确认正式排班。", chat_executable=True),
)


def resolve_product_topics(topic_ids: list[str]) -> list[tuple[ProductKnowledgeEntry, str]]:
    """Lookup parser-selected catalog IDs, never classify user prose."""
    return [(entry, entry.id) for entry in CATALOG if entry.id in topic_ids]


def _entry_answer(entry: ProductKnowledgeEntry) -> str:
    parts = [entry.description, entry.what_happens]
    if entry.side_effects:
        parts.append(entry.side_effects)
    if entry.requires_state:
        parts.append(f"前提：{entry.requires_state}")
    if entry.limitations:
        parts.append(f"限制：{entry.limitations}")
    return "\n".join(parts)


@traced("response_compose")
def compose_product_help(topics: list[tuple[ProductKnowledgeEntry, str]]) -> str:
    if not topics:
        return "请说明想了解哪个功能，例如确认生效、取消草稿、重新排班或员工视图。"
    return "\n\n".join(_entry_answer(entry) for entry, _ in topics)
