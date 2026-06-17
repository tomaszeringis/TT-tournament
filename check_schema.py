import sqlite3
conn = sqlite3.connect('data/tournament.db')
cursor = conn.cursor()

# Check alembic_version
cursor.execute("SELECT version_num FROM alembic_version")
versions = cursor.fetchall()
print('Alembic versions applied:')
if versions:
    for v in versions:
        print(f'  - {v[0]}')
else:
    print('  (no migrations recorded)')

# Check table schemas
cursor.execute("PRAGMA table_info(players)")
columns = cursor.fetchall()
print('\nPlayers table columns:')
if columns:
    for c in columns:
        print(f'  - {c[1]} ({c[2]})')
else:
    print('  (no columns found)')

conn.close()

