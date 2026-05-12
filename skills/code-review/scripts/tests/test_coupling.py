#!/usr/bin/env python3
"""Tests for coupling.py — run with: python -m unittest skills/code-review/scripts/tests/test_coupling.py"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import coupling


def _git(args: list[str], cwd: str) -> None:
    subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True)


def _make_repo() -> str:
    d = tempfile.mkdtemp()
    _git(["init"], d)
    _git(["config", "user.email", "test@test.com"], d)
    _git(["config", "user.name", "Test"], d)
    return d


def _write_file(repo: str, filename: str, content: str) -> None:
    path = os.path.join(repo, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    _git(["add", filename], repo)


def _commit(repo: str, msg: str = "commit") -> None:
    _git(["commit", "-m", msg], repo)


def _run(args: list[str]) -> tuple[int, dict]:
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            coupling.main(args)
        code = 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    try:
        return code, json.loads(buf.getvalue())
    except Exception:
        return code, {}


class TestCoupling(unittest.TestCase):

    def test_basic_coupling(self):
        repo = _make_repo()
        for i in range(5):
            _write_file(repo, "a.py", f"x = {i}\n")
            _write_file(repo, "b.py", f"y = {i}\n")
            _commit(repo, f"change both v{i}")
        code, data = _run([repo, "--min-support", "3"])
        self.assertEqual(code, 0)
        pairs = data.get("pairs", [])
        found = any(
            {p["file_a"], p["file_b"]} == {"a.py", "b.py"} for p in pairs
        )
        self.assertTrue(found, f"Expected a.py/b.py pair, got: {pairs}")
        pair = next(p for p in pairs if {p["file_a"], p["file_b"]} == {"a.py", "b.py"})
        self.assertEqual(pair["co_changes"], 5)

    def test_min_support_filter(self):
        repo = _make_repo()
        for i in range(2):
            _write_file(repo, "a.py", f"x = {i}\n")
            _write_file(repo, "b.py", f"y = {i}\n")
            _commit(repo, f"pair v{i}")
        code, data = _run([repo, "--min-support", "3"])
        self.assertEqual(code, 0)
        pairs = data.get("pairs", [])
        found = any({p["file_a"], p["file_b"]} == {"a.py", "b.py"} for p in pairs)
        self.assertFalse(found)

    def test_coupling_strength(self):
        repo = _make_repo()
        # a.py changed 10x, b.py changed 10x, together 7x
        for i in range(7):
            _write_file(repo, "a.py", f"x = {i}\n")
            _write_file(repo, "b.py", f"y = {i}\n")
            _commit(repo, f"both v{i}")
        for i in range(3):
            _write_file(repo, "a.py", f"x = solo{i}\n")
            _commit(repo, f"a solo v{i}")
        code, data = _run([repo, "--min-support", "3"])
        self.assertEqual(code, 0)
        pairs = data.get("pairs", [])
        pair = next((p for p in pairs if {p["file_a"], p["file_b"]} == {"a.py", "b.py"}), None)
        self.assertIsNotNone(pair)
        self.assertAlmostEqual(pair["coupling_strength"], 0.7, places=2)
        self.assertEqual(pair["implied_risk"], "high")

    def test_implied_risk_levels(self):
        repo = _make_repo()
        # Build three pairs with known strengths: ~0.75, ~0.5, ~0.2
        # Pair 1: c+d change together 6/8 times → 0.75 → high
        for i in range(6):
            _write_file(repo, "c.py", f"x={i}\n")
            _write_file(repo, "d.py", f"y={i}\n")
            _commit(repo, f"cd v{i}")
        for i in range(2):
            _write_file(repo, "c.py", f"x=c{i}\n")
            _commit(repo, f"c solo {i}")
        # Pair 2: e+f change together 4/8 times → 0.5 → medium
        for i in range(4):
            _write_file(repo, "e.py", f"x={i}\n")
            _write_file(repo, "f.py", f"y={i}\n")
            _commit(repo, f"ef v{i}")
        for i in range(4):
            _write_file(repo, "e.py", f"x=e{i}\n")
            _commit(repo, f"e solo {i}")
        # Pair 3: g+h change together 3/15 times → 0.2 → low
        for i in range(3):
            _write_file(repo, "g.py", f"x={i}\n")
            _write_file(repo, "h.py", f"y={i}\n")
            _commit(repo, f"gh v{i}")
        for i in range(12):
            _write_file(repo, "g.py", f"x=g{i}\n")
            _commit(repo, f"g solo {i}")

        code, data = _run([repo, "--min-support", "3"])
        self.assertEqual(code, 0)
        pairs = {frozenset([p["file_a"], p["file_b"]]): p for p in data["pairs"]}
        cd = pairs.get(frozenset(["c.py", "d.py"]))
        ef = pairs.get(frozenset(["e.py", "f.py"]))
        gh = pairs.get(frozenset(["g.py", "h.py"]))
        self.assertIsNotNone(cd)
        self.assertIsNotNone(ef)
        self.assertIsNotNone(gh)
        self.assertEqual(cd["implied_risk"], "high")
        self.assertEqual(ef["implied_risk"], "medium")
        self.assertEqual(gh["implied_risk"], "low")

    def test_exclude_glob(self):
        repo = _make_repo()
        for i in range(5):
            _write_file(repo, "package.lock", f"v{i}\n")
            _write_file(repo, "src/main.py", f"x={i}\n")
            _commit(repo, f"both v{i}")
        code, data = _run([repo, "--min-support", "3", "--exclude", "*.lock"])
        self.assertEqual(code, 0)
        for p in data.get("pairs", []):
            self.assertNotIn(".lock", p["file_a"])
            self.assertNotIn(".lock", p["file_b"])

    def test_top_n(self):
        repo = _make_repo()
        files = [f"f{i}.py" for i in range(6)]
        for _ in range(5):
            for i in range(0, 6, 2):
                _write_file(repo, files[i], f"x={_}\n")
                _write_file(repo, files[i + 1], f"y={_}\n")
                _commit(repo, f"pair{i//2} v{_}")
        code, data = _run([repo, "--min-support", "3", "--top", "2"])
        self.assertEqual(code, 0)
        self.assertLessEqual(len(data.get("pairs", [])), 2)

    def test_single_file_commits_ignored(self):
        repo = _make_repo()
        for i in range(5):
            _write_file(repo, "solo.py", f"x={i}\n")
            _commit(repo, f"solo v{i}")
        code, data = _run([repo, "--min-support", "2"])
        self.assertEqual(code, 0)
        self.assertEqual(data.get("pairs", []), [])

    def test_not_a_git_repo(self):
        d = tempfile.mkdtemp()
        code, _ = _run([d])
        self.assertEqual(code, 1)

    def test_empty_result(self):
        repo = _make_repo()
        for i in range(2):
            _write_file(repo, "a.py", f"x={i}\n")
            _write_file(repo, "b.py", f"y={i}\n")
            _commit(repo, f"v{i}")
        code, data = _run([repo, "--min-support", "5"])
        self.assertEqual(code, 0)
        self.assertEqual(data.get("pairs", []), [])

    def test_json_output_shape(self):
        repo = _make_repo()
        for i in range(4):
            _write_file(repo, "a.py", f"x={i}\n")
            _write_file(repo, "b.py", f"y={i}\n")
            _commit(repo, f"v{i}")
        code, data = _run([repo, "--min-support", "3"])
        self.assertEqual(code, 0)
        for key in ("generated_at", "repo", "since", "min_support", "pairs"):
            self.assertIn(key, data, f"Missing key: {key}")


if __name__ == "__main__":
    unittest.main()
