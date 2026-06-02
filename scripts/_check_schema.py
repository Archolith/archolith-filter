import sqlite3
db = sqlite3.connect(r'C:\Users\thron\.local\share\opencode\opencode.db')
c = db.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print("Tables:", tables)

for table in ['message', 'part', 'session', 'session_message']:
    try:
        c.execute(f"PRAGMA table_info({table})")
        cols = c.fetchall()
        print(f"\n{table}:")
        for col in cols:
            print(f"  {col[1]} {col[2]}")
        # Also get a sample row
        c.execute(f"SELECT * FROM {table} LIMIT 1")
        row = c.fetchone()
        if row:
            print(f"  Sample row (first 3 cols): {row[:3]}")
        else:
            print(f"  (empty)")
    except Exception as e:
        print(f"{table}: {e}")
