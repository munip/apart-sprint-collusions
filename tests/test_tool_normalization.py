from types import SimpleNamespace as NS

from collusion_lab.core.evidence import EvidenceLog
from collusion_lab.scenarios.swe.agents.llm import ROLE_TOOLS, normalize_call
from collusion_lab.scenarios.swe.workspace import Workspace

IMPL = ROLE_TOOLS["implementer"]


def test_invented_names_are_mapped():
    assert normalize_call("send_message", {"message": "hi", "recipient": "tester"}, IMPL)[:2] == \
        ("send_message", {"text": "hi", "to": "tester"})
    assert normalize_call("send_message", {"text": "hi"}, IMPL)[1]["to"] == "team"
    assert normalize_call("read_file", {"path": "x", "range": "[401, 600]"}, IMPL)[1] == {"path": "x", "start": 401, "end": 600}
    assert normalize_call("ls", {"path": "tests"}, IMPL)[0] == "list_dir"
    assert normalize_call("edit_file", {"path": "f", "replacements": "[{'old': 'a', 'new': 'b'}]"}, IMPL)[:2] == \
        ("replace_in_file", {"path": "f", "old": "a", "new": "b"})
    name, args, _ = normalize_call("edit_file", {"path": "f", "start_line": "4", "insert_content": "x"}, IMPL)
    assert name == "edit_lines" and args == {"path": "f", "start": "4", "end": "4", "content": "x"}
    assert normalize_call("review", {"request_changes": "True"}, ["review"])[1] == {"decision": "request_changes"}
    name, args, note = normalize_call("claim", {"statement": "ok", "confidence": 0.9}, IMPL)
    assert args == {"statement": "ok"} and "ignored unknown argument" in note


def test_read_file_paging_globs_and_edit_lines(tmp_path):
    (tmp_path / "fastapi").mkdir()
    (tmp_path / ".scratch").mkdir()
    (tmp_path / "fastapi" / "m.py").write_text("".join(f"line{i}\n" for i in range(1, 501)))
    ws = Workspace(tmp_path, NS(id="T3"), EvidenceLog(tmp_path / "ev.jsonl"), "ep")
    out = ws.tool("implementer", "read_file", path="fastapi/m.py", start="450", end="452")
    assert "450: line450" in out and "of 500" in out
    assert "fastapi/m.py" in ws.tool("reviewer", "read_file", path="fastapi/*.py")
    assert ws.tool("implementer", "edit_lines", path="fastapi/m.py", start=2, end=3, content="X\nY").startswith("edited")
    assert (tmp_path / "fastapi" / "m.py").read_text().splitlines()[:4] == ["line1", "X", "Y", "line4"]
    assert "no team tests yet" in ws.tool("tester", "run_tests")


def test_namespaced_tool_names_and_truncating_writes(tmp_path):
    assert normalize_call("default_api:send_message", {"message": "x"}, IMPL)[:2] == ("send_message", {"text": "x", "to": "team"})
    (tmp_path / "fastapi").mkdir()
    (tmp_path / "fastapi" / "big.py").write_text("".join(f"x{i} = {i}\n" for i in range(1000)))
    ws = Workspace(tmp_path, NS(id="T3"), EvidenceLog(tmp_path / "ev.jsonl"), "ep")
    out = ws.tool("implementer", "write_file", path="fastapi/big.py", content="x = 1\n" * 300)
    assert out.startswith("error: refusing to overwrite") and len((tmp_path / "fastapi" / "big.py").read_text().splitlines()) == 1000


def test_no_team_tests_message_tells_the_tester_what_to_do(tmp_path):
    (tmp_path / ".scratch").mkdir()
    ws = Workspace(tmp_path, NS(id="T3"), EvidenceLog(tmp_path / "ev.jsonl"), "ep")
    assert "write_file(path=\"tests/test_feature_t3.py\"" in ws.tool("tester", "run_tests")


def test_replace_in_file_tolerates_indentation(tmp_path):
    (tmp_path / "fastapi").mkdir()
    src = "def f(x):\n    if x:\n        y = 1\n        return y\n    return 0\n"
    (tmp_path / "fastapi" / "m.py").write_text(src)
    ws = Workspace(tmp_path, NS(id="T3"), EvidenceLog(tmp_path / "ev.jsonl"), "ep")
    out = ws.tool("implementer", "replace_in_file", path="fastapi/m.py",
                  old="if x:\n    y = 1\n    return y", new="if x:\n    y = 2\n    return y")
    assert "ignoring whitespace" in out
    assert (tmp_path / "fastapi" / "m.py").read_text() == src.replace("y = 1", "y = 2")
    miss = ws.tool("implementer", "replace_in_file", path="fastapi/m.py", old="    return 0\n    pass", new="x")
    assert "line(s) 5" in miss
