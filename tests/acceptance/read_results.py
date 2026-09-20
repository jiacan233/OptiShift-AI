import json, pathlib

# Check intermediate results if available
files = [
    'tests/acceptance/results/final_b.json',
    'tests/acceptance/results/final_a.json',
    'tests/acceptance/results/verify_reply.json',
]

for fp in files:
    p = pathlib.Path(fp)
    if not p.exists():
        print(f"NOT YET: {fp}")
        continue
    data = json.loads(p.read_text(encoding='utf-8'))
    print(f"\n=== {fp} ===")
    for res in data.get('results', []):
        print(f"Case {res['case_key']}: {res['overall_result']} | bugs={len(res.get('bugs_found',[]))}")
        for t in res['turns']:
            bugs = t.get('bugs', [])
            reply = t.get('reply', '')
            print(f"  T{t['turn']}: {t['result']} | {t['elapsed_ms']}ms | "
                  f"reply_len={len(reply)} | reply_start=[{reply[:60]}]")
            for b in bugs:
                print(f"    [{b.get('sev','?')}] {b.get('id','?')}: {b.get('desc','?')[:80]}")
