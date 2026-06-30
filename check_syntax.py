"""check_syntax.py — Validate all Python files in src/ and tests/ parse cleanly."""
import ast
import pathlib
import sys

errors = []
files = list(pathlib.Path("src").rglob("*.py")) + list(pathlib.Path("tests").rglob("*.py"))

for path in files:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        errors.append(f"SYNTAX ERROR in {path}: {e}")

if errors:
    for e in errors:
        print(e)
    sys.exit(1)
else:
    print(f"OK: All {len(files)} Python files parsed without syntax errors.")
