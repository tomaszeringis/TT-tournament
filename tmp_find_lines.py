import re
filepath = r'C:\Users\TomasZeringis\PycharmProjects\tournament_platform\tournament_platform\app\pages\voice_scorekeeper.py'
with open(filepath) as f:
    for i, l in enumerate(f, 1):
        if re.match(r'^(def |class )', l):
            print(f'{i}: {l.rstrip()}')
