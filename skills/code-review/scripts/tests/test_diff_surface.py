#!/usr/bin/env python3
"""Tests for diff-surface.py — run with: python -m unittest skills/code-review/scripts/tests/test_diff_surface.py"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import diff_surface


def _git(args: list[str], cwd: str) -> None:
    subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True)


def _make_repo() -> str:
    d = tempfile.mkdtemp()
    _git(["init"], d)
    _git(["config", "user.email", "test@test.com"], d)
    _git(["config", "user.name", "Test"], d)
    return d


def _write_commit(repo: str, filename: str, content: str, msg: str = "commit") -> str:
    path = os.path.join(repo, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    _git(["add", filename], repo)
    _git(["commit", "-m", msg], repo)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def _run(args: list[str]) -> tuple[int, dict]:
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            diff_surface.main(args)
        code = 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    try:
        return code, json.loads(buf.getvalue())
    except Exception:
        return code, {}


class TestDiffSurface(unittest.TestCase):

    def test_basic_diff(self):
        repo = _make_repo()
        # Initial commit (base)
        base = _write_commit(repo, "src/main.py", "x = 1\n" * 10, "base")
        # Head: add test file
        head = _write_commit(repo, "tests/test_main.py", "assert True\n" * 5, "add tests")
        code, data = _run([repo, "--base", base, "--head", head])
        self.assertEqual(code, 0)
        self.assertEqual(data["source_files_changed"], 0)  # main.py unchanged in this diff
        self.assertEqual(data["test_files_changed"], 1)

    def test_no_tests(self):
        repo = _make_repo()
        base = _write_commit(repo, "src/a.py", "x = 1\n" * 5, "base")
        head = _write_commit(repo, "src/b.py", "y = 2\n" * 5, "add b")
        code, data = _run([repo, "--base", base, "--head", head])
        self.assertEqual(code, 0)
        self.assertEqual(data["test_files_changed"], 0)
        # test_source_ratio: no test_loc_added and source_loc_added > 0 → 0.0
        self.assertEqual(data["test_source_ratio"], 0.0)

    def test_new_and_deleted(self):
        repo = _make_repo()
        base = _write_commit(repo, "old.py", "x = 1\n", "old")
        _git(["rm", "old.py"], repo)
        _git(["commit", "-m", "remove old"], repo)
        head = _write_commit(repo, "new.py", "y = 2\n", "add new")
        code, data = _run([repo, "--base", base, "--head", head])
        self.assertEqual(code, 0)
        self.assertEqual(data["new_files"], 1)
        self.assertEqual(data["deleted_files"], 1)

    def test_config_classification(self):
        repo = _make_repo()
        base = _write_commit(repo, "README.md", "# hi\n", "base")
        _write_commit(repo, "config.yaml", "key: value\n", "yaml")
        head = _write_commit(repo, "pyproject.toml", "[tool]\n", "toml")
        code, data = _run([repo, "--base", base, "--head", head])
        self.assertEqual(code, 0)
        config_paths = [f["path"] for f in data["files"] if f["category"] == "config"]
        self.assertIn("config.yaml", config_paths)
        self.assertIn("pyproject.toml", config_paths)

    def test_test_file_patterns(self):
        repo = _make_repo()
        base = _write_commit(repo, "placeholder.py", "x=1\n", "base")
        _write_commit(repo, "test_foo.py", "pass\n", "t1")
        _write_commit(repo, "foo_test.go", "package foo\n", "t2")
        _write_commit(repo, "Tests/BarTests.swift", "// tests\n", "t3")
        head = _write_commit(repo, "__tests__/baz.js", "test()\n", "t4")
        code, data = _run([repo, "--base", base, "--head", head])
        self.assertEqual(code, 0)
        test_paths = {f["path"] for f in data["files"] if f["category"] == "test"}
        self.assertIn("test_foo.py", test_paths)
        self.assertIn("foo_test.go", test_paths)
        self.assertIn("Tests/BarTests.swift", test_paths)
        self.assertIn("__tests__/baz.js", test_paths)

    def test_bad_ref_exits_1(self):
        repo = _make_repo()
        _write_commit(repo, "a.py", "x=1\n", "init")
        code, _ = _run([repo, "--base", "deadbeef1234abcd"])
        self.assertEqual(code, 1)

    def test_complexity_delta_positive(self):
        repo = _make_repo()
        simple = "x = 1\ny = 2\nz = 3\n"
        complex_code = "\n".join([
            "def f():",
            "  if a: pass",
            "  if b: pass",
            "  for x in y: pass",
            "  while z: pass",
            "  try: pass",
            "  except: pass",
            "  if c: pass",
            "  if d: pass",
            "  for i in j: pass",
            "  if e: pass",
        ])
        base = _write_commit(repo, "src/foo.py", simple, "base simple")
        head = _write_commit(repo, "src/foo.py", complex_code, "make complex")
        code, data = _run([repo, "--base", base, "--head", head])
        self.assertEqual(code, 0)
        self.assertGreater(data["complexity_delta"], 0)

    def test_json_output_keys(self):
        repo = _make_repo()
        base = _write_commit(repo, "a.py", "x=1\n", "base")
        head = _write_commit(repo, "b.py", "y=2\n", "head")
        code, data = _run([repo, "--base", base, "--head", head])
        self.assertEqual(code, 0)
        for key in (
            "base", "head", "files_changed", "loc_added", "loc_removed",
            "test_files_changed", "source_files_changed", "config_files_changed",
            "new_files", "deleted_files", "test_source_ratio", "complexity_delta", "files",
        ):
            self.assertIn(key, data, f"Missing key: {key}")


if __name__ == "__main__":
    unittest.main()
