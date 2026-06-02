import sqlite3, json

db = sqlite3.connect(r'C:\Users\thron\.local\share\opencode\opencode.db')
c = db.cursor()

# Get tool parts with their state structure
c.execute("SELECT data FROM part WHERE data LIKE '%\"type\":\"tool\"%' LIMIT 3")
for row in c.fetchall():
    data = json.loads(row[0])
    state = data.get('state', {})
    state_keys = list(state.keys()) if isinstance(state, dict) else 'NOT_DICT'
    print(f"tool={data.get('tool','?')}, state_keys={state_keys}")
    if isinstance(state, dict):
        for k in state_keys:
            v = state.get(k, '')
            if isinstance(v, str) and len(v) > 50:
                print(f"  {k}: {len(v)} chars, preview={v[:80]}")
            elif isinstance(v, (dict, list)):
                print(f"  {k}: {type(v).__name__}, len={len(str(v))}, preview={str(v)[:80]}")
            else:
                print(f"  {k}: {repr(v)[:80]}")
    print()
