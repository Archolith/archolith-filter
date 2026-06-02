import sqlite3, json

db = sqlite3.connect(r'C:\Users\thron\.local\share\opencode\opencode.db')
c = db.cursor()

# Get a tool part with actual content
c.execute("SELECT data FROM part WHERE data LIKE '%\"type\":\"tool\"%' LIMIT 10")
for row in c.fetchall():
    data = json.loads(row[0])
    keys = list(data.keys())
    tool_name = data.get('tool', '?')
    text = data.get('text', '')
    content = data.get('content', '')
    output = data.get('output', '')
    result = data.get('result', '')
    # Print structure
    print(f"keys={keys}, tool={tool_name}")
    if text:
        print(f"  text: {len(text)} chars, preview={text[:80]}")
    if content:
        print(f"  content: {len(str(content))} chars, preview={str(content)[:80]}")
    if output:
        print(f"  output: {len(output)} chars, preview={output[:80]}")
    if result:
        print(f"  result: {len(str(result))} chars, preview={str(result)[:80]}")
    # Check for nested fields
    for k in keys:
        v = data.get(k, '')
        if isinstance(v, str) and len(v) > 100:
            print(f"  {k}: {len(v)} chars")
        elif isinstance(v, (dict, list)):
            print(f"  {k}: {type(v).__name__}, len={len(str(v))}")
    print()
