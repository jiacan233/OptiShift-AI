"""Unified TurnPlan contracts. No fixture interprets natural language."""
import pytest
from datetime import date
from backend.app.models import Employee, StaffingConstraint, ScheduleChange
from backend.app.database import DEMO_EMPLOYEES
from backend.app.models.dialogue import DialogueState,TurnCommand,ConditionEdit,Condition,PendingAction
from backend.app.services.dialogue_parser import parse_command,grounding_error
from backend.app.services.dialogue_reducer import reduce_command
from backend.app.services.llm_client import AIUnavailableError
from backend.app.services.agent_router import AgentRouter
from backend.app.services.read_query import normalize_plan
EMP=[Employee(**r) for r in DEMO_EMPLOYEES]
class LLM:
 enabled=True;model='fixture';last_request_metrics={}
 def __init__(self,*plans):self.plans=iter(plans);self.calls=[]
 def complete_json(self,**kw):
  self.calls.append(kw['schema_name'])
  if kw['schema_name']=='agent_semantic_verifier':return {'valid':True,'clarification':None}
  value=next(self.plans)
  if isinstance(value,Exception):raise value
  return value.model_dump(mode='json') if isinstance(value,TurnCommand) else value

def edit(eid='E07',day='Mon',**kw):return ConditionEdit(employee_ids=[eid],days=[day],type='unavailable',**kw)
def plan(**kw):return TurnCommand(edits=[edit()],declared_condition_count=1,mutation_requested=True,**kw)
@pytest.mark.parametrize('text',['为什么','不要排','随便的陌生文字','强制'])
def test_typed_plan_not_overridden_by_keywords(text):
 c=parse_command(text,DialogueState(),EMP,LLM(plan(execution='create_draft')))
 assert c.execution=='create_draft' and c.edits[0].type=='unavailable'
@pytest.mark.parametrize('text',['生成排班','为什么周一人多','你好'])
def test_disabled_parser_has_no_read_or_write_fallback(text):
 llm=LLM();llm.enabled=False
 with pytest.raises(AIUnavailableError):parse_command(text,DialogueState(),EMP,llm)
def test_timeout_no_fallback():
 llm=LLM(AIUnavailableError('timeout',error_type='read_timeout'))
 with pytest.raises(AIUnavailableError):parse_command('E07周一请假',DialogueState(),EMP,llm)
 assert len(llm.calls)==1

def test_malformed_no_fallback():
 with pytest.raises(AIUnavailableError):parse_command('修改',DialogueState(),EMP,LLM({'execution':'invalid'}))

def test_empty_mutation_one_repair():
 llm=LLM(TurnCommand(mutation_requested=True),plan())
 c=parse_command('修改',DialogueState(),EMP,llm)
 assert len(c.edits)==1 and llm.calls==['agent_semantic','agent_semantic_repair','agent_semantic_verifier']

def test_empty_twice_clarifies():
 llm=LLM(TurnCommand(mutation_requested=True),TurnCommand(mutation_requested=True))
 c=parse_command('修改',DialogueState(),EMP,llm)
 assert c.clarification and len(llm.calls)==2

@pytest.mark.parametrize('bad',[
 TurnCommand(edits=[edit('E99')],declared_condition_count=1),
 TurnCommand(edits=[ConditionEdit(employee_ids=['E07','E09'],days=['Mon','Wed'],type='leave')],declared_condition_count=1),
 TurnCommand(edits=[edit()],declared_condition_count=2),
 TurnCommand(reference='current'),
 TurnCommand(reference_ids=['missing']),
 TurnCommand(expected_revision=99),
 TurnCommand(expected_scenario_revision=99),
 TurnCommand(staffing_constraints=[StaffingConstraint(scope='DAY',days=['Wed'],shifts=['morning'],min_count=4)],declared_condition_count=1),
 TurnCommand(staffing_constraints=[StaffingConstraint(scope='SHIFT',days=['Wed'],min_count=4)],declared_condition_count=1),
 TurnCommand(edits=[edit()],declared_condition_count=1,read_query={'day':'Mon'}),
])
def test_invalid_plan_fails_as_whole(bad):assert grounding_error(bad,DialogueState(),EMP)

def test_reducer_rolls_back_mixed_unknown_batch():
 c=TurnCommand(edits=[edit(),edit('E99')]); original=DialogueState()
 state,error=reduce_command(original,c,message_id='m',employees=EMP,employee_revision=0)
 assert error and not state.conditions and not original.conditions

def test_pending_continuation_and_suppression():
 pending=PendingAction(employee_id='E07',type='assign',days=['Mon'],source_message_id='m',execution_on_complete='create_draft')
 state=DialogueState(pending=[pending])
 c=TurnCommand(edits=[ConditionEdit(shift='morning',reference_ids=[pending.id])],suppress_execution=True)
 result,_=reduce_command(state,c,message_id='m2',employees=EMP,employee_revision=0)
 assert not result.pending and result.conditions and c.execution=='none'

def test_staffing_persists_and_followup_consumes_same_bounds():
 c=TurnCommand(staffing_constraints=[StaffingConstraint(scope='SHIFT',days=['Wed'],shifts=['morning','evening'],min_count=4,target_count=4,max_count=4)])
 s,_=reduce_command(DialogueState(),c,message_id='m',employees=EMP,employee_revision=0)
 restored=DialogueState.model_validate_json(s.model_dump_json())
 s2,_=reduce_command(restored,TurnCommand(reference='current',execution='create_draft'),message_id='m2',employees=EMP,employee_revision=0)
 assert len(s2.staffing_constraints)==2 and all(x.min_count==x.max_count==4 for x in s2.staffing_constraints)

def test_query_normalization_does_not_reinterpret_text():
 p=normalize_plan('E09周二晚班',EMP,proposal={'employee_ids':['E07'],'day':'Mon','shift':'morning'})
 assert p.day=='Mon' and p.employee_ids==['E07'] and p.shift=='morning'

def test_staffing_boolean_count_rejected():
 with pytest.raises(ValueError):StaffingConstraint(scope='DAY',days=['Mon'],min_count=True)

def test_trusted_actions_still_work_without_llm():
 from backend.app.services.agent_router import TrustedAgentAction
 llm=LLM();llm.enabled=False
 r=AgentRouter(llm).route('not interpreted',employees=EMP,recent_messages=[],trusted_action=TrustedAgentAction(intent='generate'))
 assert r.mutation_requested and not llm.calls


def test_turnplan_schema_is_strict_and_complete():
    from backend.app.services.agent_router import agent_route_json_schema
    from backend.app.services.llm_client import validate_strict_json_schema
    schema = agent_route_json_schema()
    validate_strict_json_schema(schema)
    assert {"domain", "execution", "edits", "staffing_constraints", "reference", "suppress_execution"} <= set(schema["required"])
    assert schema["additionalProperties"] is False


def test_rejected_semantic_verification_blocks_entire_plan():
    class Reject(LLM):
        def complete_json(self, **kwargs):
            if kwargs["schema_name"] == "agent_semantic_verifier":
                return {"valid": False, "clarification": "条件被遗漏"}
            return super().complete_json(**kwargs)
    c = parse_command("two conditions", DialogueState(), EMP, Reject(plan()))
    assert c.clarification
    state, error = reduce_command(DialogueState(), c, message_id="m", employees=EMP, employee_revision=0)
    assert error and not state.conditions
