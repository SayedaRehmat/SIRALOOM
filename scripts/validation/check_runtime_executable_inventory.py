#!/usr/bin/env python3
"""Check that runtime Python executable call sites match the reviewed inventory."""
from __future__ import annotations

import ast
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "backend" / "app"
INVENTORY = ROOT / "configs" / "engineering" / "runtime-executable-inventory.v1.json"
TRACKED = {"subprocess.run", "subprocess.Popen", "subprocess.call",
           "subprocess.check_call", "subprocess.check_output", "shutil.which"}


def name_of(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def main():
    expected = Counter()
    data = json.loads(INVENTORY.read_text(encoding="utf-8"))
    for row in data["entries"]:
        expected[(row["path"], row["function"], row["api"])] = row["count"]

    actual = Counter()
    for path in sorted(RUNTIME.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            api = name_of(node.func)
            if api not in TRACKED:
                continue
            function = "<module>"
            current = node
            while current in parents:
                current = parents[current]
                if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    function = current.name
                    break
            actual[(path.relative_to(ROOT).as_posix(), function, api)] += 1

    if actual != expected:
        for key, count in sorted((expected - actual).items()):
            print("STALE", count, "::".join(key))
        for key, count in sorted((actual - expected).items()):
            print("UNREGISTERED", count, "::".join(key))
        return 1
    print(f"Runtime executable inventory PASS: {sum(actual.values())} calls in {len(actual)} call-site groups.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
