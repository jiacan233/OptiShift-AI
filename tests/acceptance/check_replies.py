import json, pathlib
data = json.loads(pathlib.Path('tests/acceptance/results/v2_case00.json').read_text(encoding='utf-8'))
for t in data['results'][0]['turns']:
    tn = t['turn']
    reply = t.get('reply','')
    print(f"T{tn}: reply_len={len(reply)} reply=[{reply[:120]}]")
    print()
