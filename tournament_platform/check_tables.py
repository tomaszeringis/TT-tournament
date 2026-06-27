import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'data', 'tournament.db')
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print('Tables in database:')
if tables:
    for t in tables:
        print(f'  [OK] {t[0]}')
else:
    print('  (no tables found)')
conn.close()

