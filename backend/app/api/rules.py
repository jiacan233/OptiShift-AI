from fastapi import APIRouter

from ..services.rules import public_rules
from .dependencies import scheduling_service


router = APIRouter(prefix="/api/rules", tags=["rules"])


@router.get("")
def list_rules() -> dict:
    rules = public_rules(scheduling_service.context_builder.rules)
    # Keep both naming forms so the API is useful without duplicating rule text in clients.
    for rule in rules:
        rule.setdefault("category", rule["kind"])
        rule.setdefault("name", rule["title"])
        rule.setdefault("enabled", True)
    return {"rules": rules, "config": scheduling_service.context_builder.rules.model_dump(mode="json")}
