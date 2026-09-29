import sqlite3

conn = sqlite3.connect('data.sqlite')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [row[0] for row in cursor.fetchall()]
print('Tables:', tables)

if 'child' in tables:
    cursor.execute("SELECT child_id, name, device_id FROM child")
    children = cursor.fetchall()
    print(f'Children count: {len(children)}')
    for c in children:
        print(f'  ID: {c[0]}, Name: {c[1]}, Device: {c[2]}')

conn.close()