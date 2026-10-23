"""Write permissions must work regardless of OS path separators (regression: Windows denied every write)."""
from pathlib import Path, PureWindowsPath

from collusion_lab.core.evidence import EvidenceLog
from collusion_lab.scenarios.swe.workspace import TaskBundle, Workspace


def test_role_write_permissions_and_backslash_paths(tmp_path):
    task = TaskBundle.load("T3")
    ws = Workspace.create(tmp_path / "repo", task, EvidenceLog(None), "ep")
    assert ws.tool("implementer", "write_file", path="fastapi/x_new.py", content="x = 1\n").startswith("wrote")
    assert ws.tool("tester", "write_file", path="tests\\test_feature_x.py", content="def test_x():\n    pass\n").startswith("wrote")
    assert (tmp_path / "repo" / "tests" / "test_feature_x.py").exists()
    assert ws.tool("tester", "write_file", path="fastapi/evil.py", content="").startswith("permission denied")
    assert "\r\n" not in (tmp_path / "repo" / "fastapi" / "x_new.py").read_bytes().decode()


def test_posix_relative_path_matches_prefix():
    # what Windows produced before the fix
    assert str(PureWindowsPath("tests/test_a.py")) == "tests\\test_a.py"
    assert PureWindowsPath("tests/test_a.py").as_posix().startswith("tests/")
