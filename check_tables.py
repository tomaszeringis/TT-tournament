import sqlite3
conn = sqlite3.connect('data/tournament.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
print([row[0] for row in cursor.fetchall()])
conn.close()
