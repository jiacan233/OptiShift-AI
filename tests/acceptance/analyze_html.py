import pathlib, re

html = pathlib.Path('tests/acceptance/results/send1_html.txt').read_text(encoding='utf-8')

# Search for text-heavy divs near the conversation area
# Look for classes that contain actual conversation text
search_terms = ['prose', 'markdown', 'message', 'reply', 'assistant', 'chat', 'copilot', 'response', 'content', 'text']

print("=== Searching for relevant class patterns ===")
for term in search_terms:
    pat = f'class="([^"]*{term}[^"]*)"'
    matches = list(set(re.findall(pat, html, re.IGNORECASE)))
    if matches:
        print(f"\nTerm '{term}':")
        for m in matches[:5]:
            print(f"  class=[{m[:100]}]")

# Also look at what's between the user message and exec record
print("\n=== Context around user message ===")
user_msg = "E02"
idx = html.find(user_msg)
if idx > 0:
    # Get surrounding HTML (2000 chars before and after)
    snippet = html[max(0, idx-500):idx+2000]
    # Find class attributes in this region
    classes = re.findall(r'class="([^"]{10,100})"', snippet)
    print("Classes near user message:")
    for c in classes[:30]:
        print(f"  [{c}]")
