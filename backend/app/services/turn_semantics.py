"""Typed turn dimensions; natural language classification is owned by the LLM."""
from pydantic import BaseModel, ConfigDict
from ..models.dialogue import AgentDomain, SpeechAct

class TurnSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: AgentDomain
    speech_act: SpeechAct
    classification_source: str = "semantic_parser"
