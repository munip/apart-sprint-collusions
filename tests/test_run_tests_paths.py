from collusion_lab.scenarios.swe.workspace import normalize_test_paths as norm


def test_stringified_lists_and_flags_are_normalised():
    assert norm("['tests/test_x.py::test_a', '-v']")[0] == ["tests/test_x.py::test_a"]
    assert norm(["--no-cov", "-x", "tests/test_x.py", "-k", "test_a"])[0] == ["tests/test_x.py"]
    paths, note = norm("['-c', 'import x; print(1)']")
    assert paths == [] and "ignored" in note
    assert norm(["-m", "pip", "install", "python-multipart"])[0] == []
    assert norm("tests")[0] == ["tests"] and norm(".scratch/test_try.py")[0] == [".scratch/test_try.py"]
