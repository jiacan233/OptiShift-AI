"""Execution authority is independent from extracting scheduling conditions.

Read-only language wins over imperative language. A bare fact such as 上班
does not authorize a mutation; a request must contain an action construction.
"""
import re


def suppresses_execution(text: str) -> bool:
    return bool(re.search(
        r"(?:先别|先不要|暂时别|暂时不|不要真的|不要|不许|别|先不)[^，,。；;]{0,5}"
        r"(?:生成|执行|重排|排|改|强制)|不要.*(?:上班|安排|放到|调到)|只(?:是)?(?:想)?(?:问|记录|记下来|看看)|"
        r"如果|假如|假设|会怎[样么]|能不能|可不可以|能上吗|能排吗|为什么|"
        r"分析|先看看|看看.*(?:是否|行不行|合不合适)|合适吗|是否可行|"
        r"(?:已经|之前|原来|昨天).*(?:安排|上班|排)|取消|撤销", text))


def is_assignment_request(text: str) -> bool:
    """Recognize a family of imperative constructions, not individual sentences."""
    domain = bool(re.search(r"E\d{2}|员工|排班|[早晚]班|[他她].*(?:排|上班)|^帮我安排[。！!]*$", text, re.I))
    action = bool(re.search(
        r"排(?:进|到|上|一下|个|一?个[早晚]班)|安排(?:上班|个班|一下|上)|"
        r"安排.+上班|帮我安排|(?:把|给|让).*(?:排|安排|上(?:个班|班|[早晚]班)?(?:$|[，,。！!]))|"
        r"让.*(?:来上|上班|上个班|上[早晚]班)|(?:放|加|调|挪|换)(?:到|进)|来上", text))
    return domain and action


def is_explicit_draft_request(text: str) -> bool:
    if suppresses_execution(text) or re.search(r"试排|preview", text, re.I):
        return False
    legacy = bool(re.search(r"重新排|重排|生成|排一版|帮我排|保存当前方案|采用当前方案|现在按.+排", text))
    # Preferences and availability statements remain record-only unless the
    # user independently asks to generate/replan.
    constraint = bool(re.search(r"优先|偏好|请假|不可用|不能上|不上班|不排班", text))
    return legacy or (is_assignment_request(text) and not constraint)
