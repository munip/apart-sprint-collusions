"""Helpers for scripted agents: build team test files from upstream test modules and
materialise patched file contents (so writes go through logged tools)."""
from __future__ import annotations

import ast
import shutil
import tempfile
from pathlib import Path

from . import repo as R


def test_functions(src: str) -> list[str]:
    tree = ast.parse(src)
    return [n.name for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")]


def assemble(src: str, keep: set[str]) -> str:
    """Module = all non-test top-level code + the selected test functions (with decorators)."""
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    out: list[str] = []
    for node in tree.body:
        is_test = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        if is_test and node.name not in keep:
            continue
        start = min([d.lineno for d in getattr(node, "decorator_list", [])] + [node.lineno]) - 1
        out.append("".join(lines[start:node.end_lineno]) + "\n")
    return "\n".join(out)


def drop_functions(src: str, names: set[str]) -> str:
    keep = set(test_functions(src)) - names
    return assemble(src, keep)


def fn_of(nodeid: str) -> str:
    """'tests.test_x::test_name[param]' -> 'test_name'"""
    return nodeid.split("::")[-1].split("[")[0]


def patched_files(parent: str, patch: str) -> dict[str, str]:
    """Return {path: new_content} for every file touched by `patch` applied on `parent`."""
    tmp = Path(tempfile.mkdtemp(prefix="clab-patch-"))
    try:
        R.export_tree(parent, tmp, init_git=False)
        R.apply_patch(tmp, patch)
        out = {}
        for f in R.split_patch(patch):
            path = f.header.split(" b/")[-1].split("\n")[0].strip()
            out[path] = (tmp / path).read_text()
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
