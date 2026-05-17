import sys, json

data = json.load(sys.stdin)
model = data.get('model', {}).get('display_name', 'unknown')
used = data.get('context_window', {}).get('used_percentage')

if used is not None:
    pct = int(round(used))
    bar_width = 20
    filled = pct * bar_width // 100
    empty = bar_width - filled
    bar = '█' * filled + '░' * empty

    if pct >= 80:
        color = '\033[31m'
    elif pct >= 50:
        color = '\033[33m'
    else:
        color = '\033[32m'
    reset = '\033[0m'

    print(f'{model} | {bar} {color}{pct}%{reset}', end='')
else:
    print(f'{model} | context: --', end='')
