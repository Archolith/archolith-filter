import sqlite3, json

db = sqlite3.connect(r'C:\Users\thron\.local\share\opencode\opencode.db')
c = db.cursor()

# Count part types by scanning data
c.execute("SELECT data FROM part")
type_counts = {}
type_bytes = {}
total = 0
for row in c.fetchall():
    total += 1
    try:
        data = json.loads(row[0])
    except:
        continue
    ptype = data.get('type', 'unknown')
    type_counts[ptype] = type_counts.get(ptype, 0) + 1
    type_bytes[ptype] = type_bytes.get(ptype, 0) + len(row[0])

print("Part type distribution:")
for ptype in sorted(type_bytes, key=lambda x: -type_bytes[x]):
    print(f"  {ptype}: {type_counts[ptype]} parts, {type_bytes[ptype]:,} bytes ({type_bytes[ptype]/1024/1024:.1f} MB)")

# Get sample tool-result parts
print("\nSample tool-result parts:")
c.execute("SELECT data FROM part WHERE data LIKE '%tool-result%' LIMIT 5")
for row in c.fetchall():
    data = json.loads(row[0])
    tool = data.get('tool', '?')
    text = data.get('text', '')
    print(f"  tool={tool}, text_len={len(text)}, first100={text[:100]}")

# Get sample tool-call parts
print("\nSample tool-call parts:")
c.execute("SELECT data FROM part WHERE data LIKE '%tool-call%' LIMIT 5")
for row in c.fetchall():
    data = json.loads(row[0])
    tool = data.get('tool', '?')
    args = data.get('args', {})
    print(f"  tool={tool}, args_preview={json.dumps(args)[:100]}")
