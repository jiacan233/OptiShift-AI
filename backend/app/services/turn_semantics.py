"""Independent turn dimensions and conservative current-message safety evidence."""
from enum import StrEnum
import re

from pydantic import BaseModel, ConfigDict

from .product_knowledge import resolve_product_topics


class AgentDomain(StrEnum):
    SCHEDULING = "scheduling"
    PRODUCT = "product"
    SMALLTALK = "smalltalk"
    OUT_OF_SCOPE = "out_of_scope"


class SpeechAct(StrEnum):
    QUESTION = "question"
    ACTION_REQUEST = "action_request"
    CAPABILITY_QUESTION = "capability_question"
    EXPLANATION_REQUEST = "explanation_request"


class TurnSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: AgentDomain
    speech_act: SpeechAct
    classification_source: str = "deterministic"


def polite_action_evidence(text: str) -> bool:
    return bool(re.search(r"(?:帮我|替我|请|麻烦|给我).*(?:重新排|重排|生成|排一下|出一版|安排)|(?:please|for me).*\b(?:replan|generate)\b", text, re.I))


def non_scheduling_semantics(text: str) -> TurnSemantics | None:
    """Local evidence may deny a write; topic mentions alone never grant one."""
    topics = resolve_product_topics(text)
    explanation = bool(re.search(r"干嘛|做什么|是什么|怎么工作|如何工作|为什么|什么是|区别|会发生什么|what .*does|how .*work", text, re.I))
    hypothetical = bool(re.search(r"(?:如果|假如).*(?:会|怎样|如何)", text))
    capability = bool(re.search(r"(?:你|助手|系统).*(?:能|会|可以|支持)|只是问|支持.*吗|can you|do you support", text, re.I))
    # Embedded quoted/conditional actions are not present-tense authorization.
    if topics and (explanation or hypothetical or capability) and (not polite_action_evidence(text) or hypothetical or "只是问" in text):
        return TurnSemantics(domain=AgentDomain.PRODUCT, speech_act=SpeechAct.EXPLANATION_REQUEST if explanation or hypothetical else SpeechAct.CAPABILITY_QUESTION)
    if any(entry.id == "assistant.identity" for entry, _ in topics):
        return TurnSemantics(domain=AgentDomain.PRODUCT, speech_act=SpeechAct.QUESTION)
    if re.fullmatch(r"\s*(?:(?:你好|您好|嗨|哈[哈]+|谢谢(?:你)?|感谢(?:你)?|辛苦了|早上好|晚上好|hello|hi|thanks)[！!。，,？?\s]*)+", text, re.I):
        return TurnSemantics(domain=AgentDomain.SMALLTALK, speech_act=SpeechAct.QUESTION)
    if re.search(r"天气|股票|比特币|菜谱|写代码|weather|stock price|recipe", text, re.I) and not polite_action_evidence(text):
        return TurnSemantics(domain=AgentDomain.OUT_OF_SCOPE, speech_act=SpeechAct.QUESTION)
    return None
