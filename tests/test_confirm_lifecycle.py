"""Confirm uses persisted identity and validates both sides of a week boundary."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from backend.app.models import Assignment, Day, RuleConfig, Schedule, Shift
from backend.app.models.orm import ScheduleRecord
from backend.app.repository import ScheduleRepository
from backend.app.repository.schedules import ConfirmationConflictError
from backend.app.services.scheduling_service import SchedulingService
from tests.test_api import client, _confirm, _generate  # noqa: F401


def reoptimize(client, base):
    response = client.post('/api/schedule/replan', json={
        'base_schedule_id': base['schedule_id'], 'base_version': base['version'],
        'changes': [], 'minimize_changes': True,
    })
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, draft):
    return client.post('/api/schedule/confirm', json={
        'schedule_id': draft['schedule_id'], 'version': draft['version'],
    })


def test_v4_to_v5_with_confirmed_following_week_and_database_reload(client):
    base = _confirm(client, _generate(client))
    for _ in range(3):
        base = _confirm(client, reoptimize(client, base))
    following = client.post('/api/schedule/generate', json={'week_start': '2026-09-28'}).json()
    following = _confirm(client, following)
    draft = reoptimize(client, base)
    assert base['version'] == 4 and draft['version'] == 5
    assert draft['validation']['passed_count'] == 10

    response = confirm(client, draft)
    assert response.status_code == 200, response.text
    assert response.json()['schedule']['status'] == 'confirmed'
    for _ in range(2):  # Same canonical reads performed on browser refresh.
        context = client.get('/api/schedules/week-context?week_start=2026-09-21').json()
        assert context['confirmed_schedule']['schedule_id'] == draft['schedule_id']
        assert context['confirmed_schedule']['version'] == 5
        assert context['draft_schedule'] is None
    from backend.app.api.dependencies import schedule_repository
    from backend.app.database import Database
    reloaded = ScheduleRepository(Database(schedule_repository.database.url))
    assert reloaded.confirmed_for_week(draft_week := draft_date(draft)).version == 5
    assert reloaded.latest(status='draft', week_start=draft_week) is None
    assert reloaded.confirmed_for_week(draft_week + timedelta(days=7)).schedule_id == following['schedule_id']


def draft_date(draft):
    from datetime import date
    return date.fromisoformat(draft['schedule']['week_start'])


@pytest.mark.parametrize('body,field', [
    ({'version': 1}, 'schedule_id'),
    ({'draft_id': 'invented', 'version': 1}, 'schedule_id'),
    ({'schedule_id': '', 'version': 1}, 'schedule_id'),
    ({'schedule_id': 'id', 'version': '1'}, 'version'),
    ({'schedule_id': 'id', 'version': True}, 'version'),
    ({'schedule_id': 'id', 'version': 0}, 'version'),
    ({'schedule_id': 'id', 'version': 1, 'week_start': 'bad-week'}, 'week_start'),
])
def test_confirm_contract_is_strict_and_reports_field(client, body, field):
    response = client.post('/api/schedule/confirm', json=body)
    assert response.status_code == 422
    error = response.json()['error']
    assert error['code'] == 'validation_error'
    assert any(item['loc'][-1] == field for item in error['details'])


def test_missing_and_cancelled_identity_cannot_activate(client):
    assert confirm(client, {'schedule_id': 'missing', 'version': 1}).status_code == 404
    draft = _generate(client)
    assert client.post('/api/schedule/cancel', json={
        'schedule_id': draft['schedule_id'], 'version': draft['version'],
    }).status_code == 200
    assert confirm(client, draft).status_code == 404
    assert client.get('/api/schedules/latest?status=confirmed').json() is None


def test_draft_from_other_week_is_rejected(client):
    draft = _generate(client)
    response = client.post('/api/schedule/confirm', json={
        'schedule_id': draft['schedule_id'], 'version': draft['version'], 'week_start': '2026-09-28',
    })
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'draft_week_mismatch'
    assert client.get('/api/schedules/latest?status=confirmed').json() is None


def test_stale_persisted_base_and_wrong_version_are_conflicts(client):
    base = _confirm(client, _generate(client))
    draft = reoptimize(client, base)
    assert confirm(client, {**draft, 'version': 99}).status_code == 409
    from backend.app.api.dependencies import schedule_repository
    with schedule_repository.database.transaction() as session:
        session.get(ScheduleRecord, draft['schedule_id']).base_version = 99
    response = confirm(client, draft)
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'version_conflict'
    assert client.get('/api/schedules/latest?status=confirmed').json()['schedule_id'] == base['schedule_id']


def test_double_confirm_retry_and_old_confirmed_version(client):
    draft = _generate(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: confirm(client, draft), range(2)))
    assert [r.status_code for r in responses] == [200, 200]
    assert {r.json()['schedule_id'] for r in responses} == {draft['schedule_id']}
    assert confirm(client, draft).status_code == 200
    versions = client.get(f"/api/schedules/{draft['schedule_id']}/versions").json()['versions']
    assert len(versions) == 1
    next_draft = reoptimize(client, draft)
    _confirm(client, next_draft)
    assert confirm(client, draft).status_code == 409
    assert client.get('/api/schedules/latest?status=confirmed').json()['schedule_id'] == next_draft['schedule_id']


@pytest.mark.parametrize('rule,prior_days,next_days', [
    ('R07', [(Day.SUN, Shift.EVENING)], [(Day.MON, Shift.MORNING)]),
    ('R06', [(d, Shift.MORNING) for d in [Day.THU, Day.FRI, Day.SAT, Day.SUN]],
     [(d, Shift.MORNING) for d in [Day.MON, Day.TUE]]),
])
def test_confirm_preserves_protected_following_week_rules(repositories, employee_factory, week_start, rule, prior_days, next_days):
    employees, schedules = repositories
    employees.create(employee_factory('E01'))
    service = SchedulingService(employees, schedules)
    rules = RuleConfig(manager_per_shift=0, beverage_per_shift=0, cashier_per_shift=0,
                       weekday_min_staff=0, weekend_min_staff=0)
    service.context_builder.rules = rules
    service.context_builder.build(week_start)  # Persist known-empty initial history.

    def save(identity, week, days, base=None):
        schedule = Schedule(schedule_id=identity, week_start=week,
                            version=2 if base else 1, parent_schedule_id=base,
                            assignments=[Assignment(employee_id='E01', day=d, shift=s) for d, s in days])
        schedules.save_draft(schedule, lineage_id='base' if base else identity,
                             base_schedule_id=base, base_version=1 if base else None,
                             validation={'passed': True}, metadata={'rule_config': rules.model_dump(mode='json')})
        return schedule

    save('base', week_start, [])
    service.confirm('base', 1)
    save('next', week_start + timedelta(days=7), next_days)
    service.confirm('next', 1)
    save('candidate', week_start, prior_days, base='base')
    assert service.validate_stored('candidate')['confirmable']
    with pytest.raises(ConfirmationConflictError) as error:
        service.confirm('candidate', 2)
    assert error.value.code == 'following_week_conflict'
    assert rule in {v['rule_id'] for v in error.value.details['validation']['violations']}
    assert schedules.confirmed_for_week(week_start).schedule_id == 'base'
    assert schedules.get('candidate').status.value == 'draft'


def test_successor_created_after_validation_is_rejected(client, monkeypatch):
    from backend.app.api.dependencies import schedule_repository
    base = _confirm(client, _generate(client))
    next_draft = client.post('/api/schedule/generate', json={'week_start': '2026-09-28'}).json()
    draft = reoptimize(client, base)
    original = schedule_repository.confirm

    def race(schedule_id, version, **kwargs):
        if schedule_id == draft['schedule_id']:
            original(next_draft['schedule_id'], next_draft['version'])
        return original(schedule_id, version, **kwargs)

    monkeypatch.setattr(schedule_repository, 'confirm', race)
    response = confirm(client, draft)
    assert response.status_code == 409, response.text
    assert response.json()['error']['code'] == 'following_week_changed'
    assert client.get('/api/schedules/latest?status=confirmed&week_start=2026-09-21').json()['schedule_id'] == base['schedule_id']


def test_repository_does_not_skip_successor_validation(repositories, week_start):
    _, schedules = repositories
    for name, week in [('base', week_start), ('next', week_start + timedelta(days=7))]:
        schedules.save_draft(Schedule(schedule_id=name, week_start=week), lineage_id=name,
                             base_schedule_id=None, base_version=None, validation={'passed': True})
        schedules.confirm(name, 1)
    schedules.save_draft(Schedule(schedule_id='draft', week_start=week_start, version=2,
                                 parent_schedule_id='base'), lineage_id='base',
                         base_schedule_id='base', base_version=1, validation={'passed': True})
    with pytest.raises(ConfirmationConflictError):
        schedules.confirm('draft', 2)
