import json
import glob

for f in sorted(glob.glob('tests/acceptance/results/final_*.json')):
    try:
        with open(f, encoding='utf-8') as fp:
            data = json.load(fp)
        print('=== FILE:', f, '===')
        for r in data.get('results', []):
            cid = r.get('case_id')
            ores = r.get('overall_result')
            bugs = r.get('bugs_found', [])
            print(f"  {cid}: {ores} (bugs: {len(bugs)})")
            for b in bugs:
                print(f"    - [{b.get('sev')}] {b.get('id')}: {b.get('desc')}")
    except Exception as e:
        print('Error reading', f, e)
