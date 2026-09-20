# -*- coding: utf-8 -*-
"""Compile multi-turn acceptance report from all final_*.json results."""
import json, glob, datetime, os

all_results = []
for f in sorted(glob.glob('tests/acceptance/results/final_*.json')):
    with open(f, encoding='utf-8') as fp:
        data = json.load(fp)
        for r in data.get('results', []):
            all_results.append(r)

all_results.sort(key=lambda x: x.get('case_key', '99'))

print(f"Loaded {len(all_results)} cases.")
for r in all_results:
    print(r.get('case_id'), r.get('description'), r.get('overall_result'), len(r.get('turns', [])))
