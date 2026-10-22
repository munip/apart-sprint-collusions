"""FastAPI checkout handling, isolated workspaces, and an isolated test runner.

* Agents never get a .git directory: upstream history contains the future
  reference solutions ("Shortcutting the Fix" style exploits). Workspaces are
  materialised with `git archive` and a fresh local git repo is initialised so
  the environment (not the agent) can compute diffs.
* The trusted test runner applies the agents' diff to a *pristine* checkout and
  runs hidden tests there, so nothing the agents control (conftest.py, pytest
  plugins, edited tests) can influence the verdict.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from ...core.models import REPO_ROOT

FASTAPI_URL = "https://github.com/fastapi/fastapi"
CACHE = Path(os.environ.get("CLAB_CACHE", REPO_ROOT / ".cache"))
FASTAPI_DIR = Path(os.environ.get("CLAB_FASTAPI_DIR", CACHE / "fastapi"))
SWE_PYTHON = os.environ.get("CLAB_SWE_PYTHON", str(CACHE / "fapi-venv" / "bin" / "python"))


def sh(cmd: list[str], cwd: Path | None = None, check: bool = True, env: dict | None = None,
       timeout: int = 600, input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True,
                          env=env, timeout=timeout, input=input)


def ensure_fastapi() -> Path:
    if not (FASTAPI_DIR / ".git").exists():
        FASTAPI_DIR.parent.mkdir(parents=True, exist_ok=True)
        sh(["git", "clone", "--filter=blob:none", FASTAPI_URL, str(FASTAPI_DIR)], timeout=1200)
    return FASTAPI_DIR


_ARCHIVES: dict[str, bytes] = {}


def export_tree(commit: str, dest: Path, init_git: bool = True) -> Path:
    """Materialise `commit` into dest without upstream history.

    With init_git a fresh single-commit repo is created so the environment can diff
    the agents' work; the agents still cannot see upstream (future) commits.
    """
    src = ensure_fastapi()
    dest.mkdir(parents=True, exist_ok=True)
    if commit not in _ARCHIVES:
        # only what code + tests need (skips ~1.9k translated-docs files; 3x faster)
        _ARCHIVES[commit] = subprocess.run(["git", "archive", commit, "fastapi", "tests", "docs_src",
                                            "pyproject.toml"], cwd=src, capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(dest)], input=_ARCHIVES[commit], check=True)
    if not init_git:
        return dest
    sh(["git", "init", "-q"], cwd=dest)
    sh(["git", "add", "-A"], cwd=dest)
    sh(["git", "-c", "user.email=env@lab", "-c", "user.name=env", "commit", "-qm", "base"], cwd=dest)
    return dest


def show_file(commit: str, path: str) -> str:
    return sh(["git", "show", f"{commit}:{path}"], cwd=ensure_fastapi()).stdout


def commit_patch(commit: str, pathspec: str = "fastapi/") -> str:
    return sh(["git", "show", "--format=", commit, "--", pathspec], cwd=ensure_fastapi()).stdout


def diff_workspace(ws: Path, pathspec: list[str] | None = None) -> str:
    sh(["git", "add", "-A"], cwd=ws)
    cmd = ["git", "diff", "--cached", "HEAD"]
    if pathspec:
        cmd += ["--"] + pathspec
    return sh(cmd, cwd=ws).stdout


def apply_patch(ws: Path, patch: str, check: bool = True) -> bool:
    if not patch.strip():
        return True
    r = sh(["git", "apply", "--recount", "--whitespace=nowarn", "-"], cwd=ws, check=False, input=patch)
    if check and r.returncode != 0:
        raise RuntimeError(f"patch failed: {r.stderr[:500]}")
    return r.returncode == 0


# ----------------------------------------------------------------------------
# Unified-diff hunk manipulation (used for mutants / partial implementations)
# ----------------------------------------------------------------------------
@dataclass
class FilePatch:
    header: str
    hunks: list[str] = field(default_factory=list)


def split_patch(patch: str) -> list[FilePatch]:
    files: list[FilePatch] = []
    cur: FilePatch | None = None
    hunk: list[str] | None = None
    header: list[str] = []
    for line in patch.splitlines(keepends=True):
        if line.startswith("diff --git"):
            if cur is not None:
                if hunk: cur.hunks.append("".join(hunk))
                files.append(cur)
            cur, hunk, header = None, None, [line]
            continue
        if line.startswith("@@"):
            if cur is None:
                cur = FilePatch("".join(header))
            if hunk: cur.hunks.append("".join(hunk))
            hunk = [line]
            continue
        if hunk is not None:
            hunk.append(line)
        else:
            header.append(line)
    if cur is not None:
        if hunk: cur.hunks.append("".join(hunk))
        files.append(cur)
    return files


def join_patch(files: list[FilePatch], drop: set[tuple[int, int]] = frozenset()) -> str:
    out = []
    for fi, f in enumerate(files):
        hunks = [h for hi, h in enumerate(f.hunks) if (fi, hi) not in drop]
        if hunks:
            out.append(f.header + "".join(hunks))
    return "".join(out)


# ----------------------------------------------------------------------------
# Isolated test runner
# ----------------------------------------------------------------------------
@dataclass
class TestRun:
    passed: list[str]
    failed: list[str]
    errors: list[str]
    collected: int
    returncode: int
    output_tail: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.failed and not self.errors

    def to_dict(self) -> dict:
        return {"passed": len(self.passed), "failed": self.failed, "errors": self.errors,
                "collected": self.collected, "returncode": self.returncode}


def run_pytest(ws: Path, targets: list[str], timeout: int = 240) -> TestRun:
    targets = [t for t in targets if (ws / t.split("::")[0]).exists()]
    if not targets:
        return TestRun([], [], ["<no tests collected>"], 0, 5, "")
    xml = Path(tempfile.mkstemp(suffix=".xml")[1])
    env = dict(os.environ, PYTHONPATH=str(ws), PYTHONDONTWRITEBYTECODE="1")
    cmd = [SWE_PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=", "--timeout=20",
           f"--rootdir={ws}", f"--junitxml={xml}", *targets]
    try:
        r = sh(cmd, cwd=ws, check=False, env=env, timeout=timeout)
        rc, tail = r.returncode, (r.stdout + r.stderr)[-2000:]
    except subprocess.TimeoutExpired:
        return TestRun([], [], ["<timeout>"], 0, 124, "timeout")
    passed, failed, errors = [], [], []
    try:
        root = ET.parse(xml).getroot()
        for tc in root.iter("testcase"):
            f = tc.get("file") or tc.get("classname", "").replace(".", "/") + ".py"
            nid = f"{tc.get('classname')}::{tc.get('name')}"
            if tc.find("failure") is not None:
                failed.append(nid)
            elif tc.find("error") is not None:
                errors.append(nid)
            elif tc.find("skipped") is not None:
                continue
            else:
                passed.append(nid)
    except ET.ParseError:
        errors.append("<junit parse error>")
    finally:
        xml.unlink(missing_ok=True)
    if rc not in (0, 1) and not errors:
        errors.append(f"<pytest rc={rc}>")
    return TestRun(passed, failed, errors, len(passed) + len(failed) + len(errors), rc, tail)


class PristineRunner:
    """Trusted runner: pristine parent checkout + candidate src diff + hidden tests."""

    def __init__(self, parent_commit: str, hidden_tests: dict[str, str]):
        self.parent = parent_commit
        self.hidden_tests = hidden_tests

    def evaluate(self, src_patch: str, extra_tests: dict[str, str] | None = None,
                 targets: list[str] | None = None, hidden: bool = True) -> tuple[bool, TestRun | None]:
        """Run `targets` (default: hidden tests) on parent+src_patch. Results are cached
        on disk by content hash, so replaying many monitors over the same episode is cheap."""
        import hashlib, json
        tests = {**(self.hidden_tests if hidden else {}), **(extra_tests or {})}
        targets = targets or list(self.hidden_tests)
        key = hashlib.sha256(json.dumps([self.parent, src_patch, tests, targets], sort_keys=True).encode()).hexdigest()[:24]
        cache = CACHE / "runs" / f"{key}.json"
        if cache.exists():
            d = json.loads(cache.read_text())
            return d["ok"], (TestRun(**d["run"]) if d["run"] else None)
        ok, run = self._evaluate(src_patch, tests, targets)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"ok": ok, "run": run.__dict__ if run else None}))
        return ok, run

    def _evaluate(self, src_patch: str, tests: dict[str, str], targets: list[str]) -> tuple[bool, TestRun | None]:
        tmp = Path(tempfile.mkdtemp(prefix="clab-pristine-"))
        try:
            export_tree(self.parent, tmp, init_git=False)
            if not apply_patch(tmp, src_patch, check=False):
                return False, None
            for rel, content in tests.items():
                p = tmp / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
            run = run_pytest(tmp, targets)
            return True, run
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def only_src(patch: str, prefix: str = "fastapi/") -> str:
    """Keep only hunks for files under `prefix` (agents' test edits are evaluated separately)."""
    keep = [f for f in split_patch(patch) if re.search(rf"^diff --git a/{re.escape(prefix)}", f.header)]
    return join_patch(keep)


def only_tests(patch: str) -> str:
    keep = [f for f in split_patch(patch) if re.search(r"^diff --git a/tests/", f.header)]
    return join_patch(keep)
