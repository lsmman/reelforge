#!/usr/bin/env python3
"""Tests for the parts of rf.py that quietly corrupt run.json when wrong."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rf import set_path  # noqa: E402


class SetPath(unittest.TestCase):
    def test_plain_key(self):
        o = {}
        set_path(o, "status", "done")
        self.assertEqual(o, {"status": "done"})

    def test_creates_missing_parents(self):
        o = {}
        set_path(o, "brief.subject", "x")
        self.assertEqual(o, {"brief": {"subject": "x"}})

    def test_walks_through_a_null_key(self):
        # A fresh run.json holds genre: null.
        o = {"genre": None}
        set_path(o, "genre.id", "portrait")
        self.assertEqual(o, {"genre": {"id": "portrait"}})

    def test_indexes_into_a_list_without_destroying_it(self):
        o = {"attempts": [{"n": 1, "file": "out/attempt-01.png"}]}
        set_path(o, "attempts.0.score", 92)
        self.assertEqual(o["attempts"][0]["file"], "out/attempt-01.png")
        self.assertEqual(o["attempts"][0]["score"], 92)
        self.assertIsInstance(o["attempts"], list)

    def test_replaces_a_list_element(self):
        o = {"xs": [1, 2, 3]}
        set_path(o, "xs.1", 9)
        self.assertEqual(o["xs"], [1, 9, 3])

    def test_does_not_clobber_siblings(self):
        o = {"brief": {"a": 1}}
        set_path(o, "brief.b", 2)
        self.assertEqual(o["brief"], {"a": 1, "b": 2})


if __name__ == "__main__":
    unittest.main(verbosity=2)
