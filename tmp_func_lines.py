import re
lines = open('tournament_platform/app/pages/voice_scorekeeper.py').readlines()
result = []
for i, l in enumerate(lines, 1):
    if re.match(r'^(def |class )', l):
        result.append(f'{i}: {l.rstrip()}')
with open('tmp_output.txt', 'w') as f:
    f.write('\n'.join(result))
