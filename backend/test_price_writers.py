"""
Guard test: backend/pricer is the only writer of instruments.current_price.

Agents must never write prices. The Planner once wrote random numbers and
US-dollar Polygon prices into the shared instruments table, and the Tagger
wrote an LLM-guessed price. This test reads the source (no AWS, no database)
and fails if any of that comes back.

Run from the backend directory:
    uv run test_price_writers.py
"""

import ast
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).parent

# Only these directories may write to the instruments table at all
ALLOWED_WRITERS = ("database", "pricer")

SKIP_PARTS = {".venv", "__pycache__", "node_modules", "package", "build"}

RAW_SQL_WRITE = re.compile(r"\b(update|insert\s+into)\s+instruments\b", re.IGNORECASE)


def python_files():
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND)
        if SKIP_PARTS.intersection(rel.parts):
            continue
        yield rel, path


def first_arg_is_instruments(call: ast.Call) -> bool:
    return bool(call.args) and isinstance(call.args[0], ast.Constant) and call.args[0].value == "instruments"


def find_violations():
    violations = []

    for rel, path in python_files():
        allowed = rel.parts[0] in ALLOWED_WRITERS
        if allowed or rel.name == Path(__file__).name:
            continue

        tree = ast.parse(path.read_text(), filename=str(rel))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                method = node.func.attr
                if method in ("update", "insert") and first_arg_is_instruments(node):
                    violations.append(f"{rel}:{node.lineno} writes to the instruments table with .{method}()")
                if method == "update_price":
                    violations.append(f"{rel}:{node.lineno} calls update_price() outside backend/pricer")
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and RAW_SQL_WRITE.search(node.value):
                violations.append(f"{rel}:{node.lineno} has raw SQL that writes to instruments")

    return violations


def tagger_schema_price_fields():
    """The Tagger's structured output must not ask the LLM for a price."""
    tree = ast.parse((BACKEND / "tagger" / "agent.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "InstrumentClassification":
            return [
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and "price" in stmt.target.id.lower()
            ]
    raise AssertionError("InstrumentClassification not found in tagger/agent.py")


def main():
    failures = find_violations()
    failures += [f"tagger/agent.py: InstrumentClassification has a '{f}' field" for f in tagger_schema_price_fields()]

    if failures:
        print("FAIL: only backend/pricer may write instrument prices")
        for failure in failures:
            print(f"  - {failure}")
        sys.exit(1)

    print("PASS: no code outside backend/database and backend/pricer writes to instruments,")
    print("      and the Tagger's output schema has no price field")


if __name__ == "__main__":
    main()
