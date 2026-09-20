import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
BASE = 'https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com'


def get(path):
    with urlopen(BASE + path, timeout=30) as response:
        return json.load(response)


reports = []
conversations = {}
drafts = []
for run in ['production-browser', 'production-browser-harness-recheck', 'production-browser-final']:
    report = json.loads((ROOT / run / 'results.json').read_text(encoding='utf-8'))
    assert report.get('ended'), run
    reports.append(report)
    for item in report['conversations']:
        conversations[item['cid']] = item
    drafts.extend(report['drafts'])

# The initial G harness failed before recording its new empty conversation.
first_g = next(c for c in reports[0]['conversations'] if c['case'] == 'G')
for item in get('/api/agent/conversations?browser_workspace_id=' + first_g['workspace'])['conversations']:
    conversations[item['conversation_id']] = {
        'cid': item['conversation_id'], 'workspace': first_g['workspace'], 'case': 'G-initial-audited',
    }

scenarios = []
for item in conversations.values():
    state = get(f"/api/agent/conversations/{item['cid']}/scenario?browser_workspace_id={item['workspace']}&week_start=2026-10-05")
    assert not state['patches'], item['cid']
    scenarios.append({'conversation_id': item['cid'], 'case': item['case'], **state})

week = get('/api/schedules/week-context?week_start=2026-10-05')
confirmed = week['confirmed_schedule']
assignments = sorted([a['employee_id'], a['day'], a['shift']] for a in confirmed['assignments'])
signature = {
    'schedule_id': confirmed['schedule_id'], 'version': confirmed['version'],
    'hash': hashlib.sha256(json.dumps(assignments, separators=(',', ':')).encode()).hexdigest(),
}
assert all(signature == {k: r['baseline'][k] for k in signature} for r in reports)
assert week['draft_schedule'] is None
versions = get('/api/schedules/' + signature['schedule_id'] + '/versions')['versions']
by_id = {v['schedule_id']: v for v in versions}
for draft in drafts:
    record = by_id[draft['schedule_id']]
    assert record['status'] == 'cancelled' and record['version'] == draft['version']
    draft['final_status'] = record['status']
employees = get('/api/employees')['employees']
employee_ids = sorted(e['id'] for e in employees)
assert employee_ids == [f'E{i:02}' for i in range(1, 21)]
result = {'confirmed': signature, 'active_draft': None, 'test_drafts': drafts,
          'employee_ids': employee_ids, 'scenario_states': scenarios,
          'conversations_retained_for_audit': len(conversations)}
(ROOT / 'production-final-audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print('Confirmed baseline unchanged:', signature)
print('Cancelled owned test drafts:', len(drafts), 'Empty scenario states:', len(scenarios))
