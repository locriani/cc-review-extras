#!/usr/bin/env python3
"""Tests for hotspot.py — run with: python -m unittest skills/code-review/scripts/tests/test_hotspot.py"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import hotspot


def _git(args: list[str], cwd: str) -> None:
    subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True)


def _make_repo() -> str:
    d = tempfile.mkdtemp()
    _git(["init"], d)
    _git(["config", "user.email", "test@test.com"], d)
    _git(["config", "user.name", "Test"], d)
    return d


def _write_commit(repo: str, filename: str, content: str, msg: str = "commit") -> None:
    path = os.path.join(repo, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    _git(["add", filename], repo)
    _git(["commit", "-m", msg], repo)


def _run(args: list[str]) -> tuple[int, dict]:
    """Run hotspot.main() and capture stdout JSON + exit code."""
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            hotspot.main(args)
        code = 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    try:
        return code, json.loads(buf.getvalue())
    except Exception:
        return code, {}


class TestHotspot(unittest.TestCase):

    def test_basic_hotspot(self):
        repo = _make_repo()
        complex_code = "\n".join([
            "def foo():",
            "  if x:",
            "    for i in range(10):",
            "      if y:",
            "        while z:",
            "          pass",
            "  else:",
            "    try:",
            "      pass",
            "    except Exception:",
            "      pass",
        ])
        simple_code = "x = 1\ny = 2\nz = 3\n"
        # commit complex.py 5 times, simple.py once
        for i in range(5):
            _write_commit(repo, "complex.py", complex_code + f"\n# v{i}", f"complex v{i}")
        _write_commit(repo, "simple.py", simple_code, "simple once")
        code, data = _run([repo])
        self.assertEqual(code, 0)
        files = {f["path"]: f for f in data["files"]}
        self.assertIn("complex.py", files)
        self.assertIn("simple.py", files)
        self.assertGreater(files["complex.py"]["hotspot_score"], files["simple.py"]["hotspot_score"])

    def test_top_n(self):
        repo = _make_repo()
        for i in range(5):
            _write_commit(repo, f"file{i}.py", f"x = {i}\n", f"add file{i}")
        code, data = _run([repo, "--top", "2"])
        self.assertEqual(code, 0)
        self.assertEqual(len(data["files"]), 2)

    def test_since_filter(self):
        repo = _make_repo()
        _write_commit(repo, "old.py", "x = 1\n", "old commit")
        # Tag as old by forcing date via env — simpler: use a future anchor
        # Just verify that --since HEAD excludes previous commit
        _write_commit(repo, "new.py", "y = 2\n", "new commit")
        # Get SHA of the second-to-last commit
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD~1"], cwd=repo, text=True
        ).strip()
        code, data = _run([repo, "--since", sha])
        self.assertEqual(code, 0)
        paths = [f["path"] for f in data["files"]]
        self.assertIn("new.py", paths)
        self.assertNotIn("old.py", paths)

    def test_exclude_glob(self):
        repo = _make_repo()
        for i in range(3):
            _write_commit(repo, "Foo.generated.swift", f"// v{i}\n", f"gen v{i}")
        _write_commit(repo, "real.swift", "let x = 1\n", "real")
        code, data = _run([repo, "--exclude", "*.generated.swift"])
        self.assertEqual(code, 0)
        paths = [f["path"] for f in data["files"]]
        self.assertNotIn("Foo.generated.swift", paths)
        self.assertIn("real.swift", paths)

    def test_not_a_git_repo(self):
        d = tempfile.mkdtemp()
        code, _ = _run([d])
        self.assertEqual(code, 1)

    def test_no_commits(self):
        repo = _make_repo()
        code, data = _run([repo])
        self.assertEqual(code, 0)
        self.assertEqual(data.get("files", []), [])

    def test_deleted_file_appears(self):
        repo = _make_repo()
        for i in range(3):
            _write_commit(repo, "gone.py", f"x = {i}\n", f"gone v{i}")
        _git(["rm", "gone.py"], repo)
        _git(["commit", "-m", "delete gone.py"], repo)
        code, data = _run([repo])
        self.assertEqual(code, 0)
        paths = [f["path"] for f in data["files"]]
        self.assertIn("gone.py", paths)
        gone = next(f for f in data["files"] if f["path"] == "gone.py")
        self.assertGreaterEqual(gone["churn"], 3)
        self.assertEqual(gone["complexity"], 0)

    def test_complexity_weighting(self):
        repo = _make_repo()
        cf_heavy = "\n".join([
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
        plain = "\n".join([f"x{i} = {i}" for i in range(len(cf_heavy.splitlines()))])
        _write_commit(repo, "cf.py", cf_heavy, "cf")
        _write_commit(repo, "plain.py", plain, "plain")
        # Touch both equally (one more commit each)
        _write_commit(repo, "cf.py", cf_heavy + "\n# v2", "cf2")
        _write_commit(repo, "plain.py", plain + "\n# v2", "plain2")
        code, data = _run([repo])
        self.assertEqual(code, 0)
        files = {f["path"]: f for f in data["files"]}
        self.assertGreater(files["cf.py"]["complexity"], files["plain.py"]["complexity"])

    def test_json_output_shape(self):
        repo = _make_repo()
        _write_commit(repo, "a.py", "x = 1\n", "init")
        code, data = _run([repo])
        self.assertEqual(code, 0)
        for key in ("generated_at", "repo", "since", "files"):
            self.assertIn(key, data)
        for f in data["files"]:
            for key in ("path", "churn", "complexity", "hotspot_score", "last_changed_iso"):
                self.assertIn(key, f)


if __name__ == "__main__":
    unittest.main()
