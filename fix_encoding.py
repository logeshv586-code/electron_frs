"""Replace all non-ASCII characters in face_pipeline.py and save_face.py with ASCII equivalents."""
import re

REPLACEMENTS = {
    '\u2500': '-',   # ─  box-drawing horizontal
    '\u2550': '=',   # ═  box-drawing double horizontal
    '\u00d7': '*',   # ×  multiplication sign
    '\u2013': '-',   # –  en-dash
    '\u2014': '--',  # —  em-dash
    '\u2018': "'",   # '  left single quote
    '\u2019': "'",   # '  right single quote
    '\u201c': '"',   # "  left double quote
    '\u201d': '"',   # "  right double quote
    '\u2026': '...', # …  ellipsis
    '\u2265': '>=',  # ≥
    '\u2264': '<=',  # ≤
}

files = [
    'backend_face/face_pipeline.py',
    'backend_face/save_face.py',
]

for fpath in files:
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()

    new_content = content
    for old, new in REPLACEMENTS.items():
        new_content = new_content.replace(old, new)

    # Check for any remaining non-ASCII
    remaining = [(i+1, line.rstrip()) for i, line in enumerate(new_content.split('\n'))
                 if any(ord(c) > 127 for c in line)]

    if new_content != content:
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"FIXED: {fpath}")
    else:
        print(f"OK (no changes): {fpath}")

    if remaining:
        print(f"  WARNING: {len(remaining)} lines still have non-ASCII:")
        for lno, line in remaining[:5]:
            print(f"    L{lno}: {repr(line[:80])}")
    else:
        print(f"  All ASCII clean!")
