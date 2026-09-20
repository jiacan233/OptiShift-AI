import pathlib, re

html = pathlib.Path('tests/acceptance/results/send1_html.txt').read_text(encoding='utf-8')

# Find the copilot-overlay div and extract its content
idx = html.find('copilot-overlay')
if idx < 0:
    print("copilot-overlay NOT FOUND")
else:
    # Get the opening tag position
    start = html.rfind('<div', 0, idx)
    # Extract 8000 chars from there
    chunk = html[start:start+8000]
    
    # Find all class attrs in this chunk
    classes = re.findall(r'class="([^"]{5,120})"', chunk)
    print(f"Classes inside copilot-overlay ({len(classes)} found):")
    seen = set()
    for c in classes:
        if c not in seen:
            seen.add(c)
            print(f"  [{c}]")
    
    # Print a readable snippet
    print("\n=== Text content in copilot-overlay ===")
    # Strip tags
    text = re.sub(r'<[^>]+>', ' ', chunk)
    text = re.sub(r'\s+', ' ', text).strip()
    print(text[:3000])
