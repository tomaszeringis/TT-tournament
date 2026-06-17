import sqlite3
conn = sqlite3.connect('data/tournament.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print('Tables in database:')
if tables:
    for t in tables:
        print(f'  ✓ {t[0]}')
else:
    print('  (no tables found)')
conn.close()

