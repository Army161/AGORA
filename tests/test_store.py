"""Behavioural tests for the Agora workspace store.

store.py is pure stdlib, so this suite needs no dependencies and no MCP client:
    python -m unittest discover -s tests -v

Each test gets a throwaway workspace dir, so runs are independent and parallel-safe.
"""
from __future__ import annotations
import os
import sys
import tempfile
import shutil
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from store import AgoraStore, DEFAULT_LEASE_MINUTES, TASK_STATES  # noqa: E402


class AgoraTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="agora-test-")
        self.s = AgoraStore(self.root, "Test Workspace")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)


class TestBootstrap(AgoraTestCase):
    def test_join_bootstraps_workspace(self):
        self.s.join("a1", "claude_code", "Builder")
        for f in ("meta.json", "agents.json", "tasks.json", "locks.json",
                  "memory.json", "events.jsonl", "board.md", "AGENTS.md"):
            self.assertTrue(os.path.exists(os.path.join(self.root, f)), f"missing {f}")

    def test_unknown_surface_is_coerced(self):
        """An unrecognised surface must not poison the registry."""
        self.s.join("a1", "definitely-not-a-surface")
        agent = self.s.summary()["agents"][0]
        self.assertEqual(agent["surface"], "other")

    def test_rejoin_preserves_joined_at(self):
        first = self.s.join("a1", "claude_code", "Builder")["agents"][0]["joined_at"]
        again = self.s.join("a1", "claude_code", "Builder")["agents"][0]["joined_at"]
        self.assertEqual(first, again, "re-join must not reset joined_at")


class TestTaskLeases(AgoraTestCase):
    def setUp(self):
        super().setUp()
        self.s.join("alice", "claude_code")
        self.s.join("bob", "cowork")
        self.t = self.s.add_task("Ship the docs", "alice")["id"]

    def test_claim_marks_in_progress(self):
        t = self.s.claim_task(self.t, "alice")
        self.assertEqual(t["owner"], "alice")
        self.assertEqual(t["status"], "in_progress")
        self.assertGreater(t["lease_until"], 0)

    def test_second_claimer_is_refused(self):
        self.s.claim_task(self.t, "alice")
        res = self.s.claim_task(self.t, "bob")
        self.assertIn("error", res, "a live lease must block a second claimer")
        self.assertIn("alice", res["error"])

    def test_force_overrides_live_lease(self):
        self.s.claim_task(self.t, "alice")
        res = self.s.claim_task(self.t, "bob", force=True)
        self.assertEqual(res.get("owner"), "bob")

    def test_expired_lease_is_reclaimable_without_force(self):
        """A crashed agent must never block a task forever."""
        self.s.claim_task(self.t, "alice", ttl_minutes=1)
        tasks = self.s._load("tasks.json", {})
        tasks[self.t]["lease_until"] = 1  # far in the past
        self.s._save("tasks.json", tasks)
        res = self.s.claim_task(self.t, "bob")
        self.assertEqual(res.get("owner"), "bob", "expired lease should be freely claimable")

    def test_done_releases_ownership(self):
        self.s.claim_task(self.t, "alice")
        t = self.s.update_task(self.t, "alice", status="done")
        self.assertIsNone(t["owner"])
        self.assertEqual(t["lease_until"], 0)

    def test_invalid_status_rejected(self):
        res = self.s.update_task(self.t, "alice", status="nonsense")
        self.assertIn("error", res)
        for good in TASK_STATES:
            self.assertNotIn("error", self.s.update_task(self.t, "alice", status=good))

    def test_release_returns_task_to_pool(self):
        self.s.claim_task(self.t, "alice")
        t = self.s.release_task(self.t, "alice")
        self.assertEqual(t["status"], "todo")

    def test_claim_missing_task_errors(self):
        self.assertIn("error", self.s.claim_task("T-9999", "alice"))


class TestLocks(AgoraTestCase):
    def setUp(self):
        super().setUp()
        self.s.join("alice", "claude_code")
        self.s.join("bob", "cowork")

    def test_lock_blocks_other_holder(self):
        self.s.lock_resource("src/app.py", "alice")
        res = self.s.lock_resource("src/app.py", "bob")
        self.assertIn("error", res)

    def test_relocking_by_same_holder_is_allowed(self):
        self.s.lock_resource("src/app.py", "alice")
        self.assertNotIn("error", self.s.lock_resource("src/app.py", "alice"))

    def test_unlock_frees_resource(self):
        self.s.lock_resource("src/app.py", "alice")
        self.s.unlock_resource("src/app.py", "alice")
        self.assertNotIn("error", self.s.lock_resource("src/app.py", "bob"))

    def test_expired_lock_is_reclaimable(self):
        self.s.lock_resource("src/app.py", "alice")
        locks = self.s._load("locks.json", {})
        locks["src/app.py"]["lease_until"] = 1
        self.s._save("locks.json", locks)
        self.assertNotIn("error", self.s.lock_resource("src/app.py", "bob"))


class TestHandoffs(AgoraTestCase):
    def setUp(self):
        super().setUp()
        self.s.join("alice", "claude_code")
        self.s.join("bob", "cowork")

    def test_handoff_lifecycle_and_doc(self):
        h = self.s.create_handoff("alice", "bob", "Finish the parser",
                                  "Tokeniser done, parser stubbed.",
                                  context="See src/parse.py",
                                  artifacts=["src/parse.py"], next_steps=["write tests"])
        hid = h["id"]
        self.assertEqual(h["status"], "open")
        self.assertTrue(os.path.exists(os.path.join(self.root, "handoffs", f"{hid}.md")))

        self.assertEqual(self.s.ack_handoff(hid, "bob", "on it")["status"], "acked")
        done = self.s.complete_handoff(hid, "bob", "shipped")
        self.assertEqual(done["status"], "done")
        self.assertEqual(len(done["log"]), 2, "ack + complete should both be logged")

    def test_open_handoffs_are_targeted(self):
        self.s.create_handoff("alice", "bob", "For Bob", "x")
        self.s.create_handoff("alice", "any", "For anyone", "y")
        bob = [h["title"] for h in self.s.summary(for_agent="bob")["open_handoffs"]]
        self.assertIn("For Bob", bob)
        self.assertIn("For anyone", bob, "'any' handoffs must be visible to everyone")

        carol = [h["title"] for h in self.s.summary(for_agent="carol")["open_handoffs"]]
        self.assertNotIn("For Bob", carol, "handoffs addressed to bob must not leak to carol")

    def test_unknown_handoff_errors(self):
        self.assertIn("error", self.s.ack_handoff("H-9999", "bob"))


class TestMessages(AgoraTestCase):
    def setUp(self):
        super().setUp()
        for a in ("alice", "bob", "carol"):
            self.s.join(a, "other")

    def test_direct_message_is_not_visible_to_third_party(self):
        self.s.send_message("alice", "bob", "secret plan")
        self.assertEqual(len(self.s.get_messages("bob")), 1)
        self.assertEqual(len(self.s.get_messages("carol")), 0)

    def test_broadcast_reaches_everyone(self):
        self.s.send_message("alice", "all", "standup in 5")
        for who in ("bob", "carol"):
            self.assertEqual(len(self.s.get_messages(who)), 1)


class TestEventLog(AgoraTestCase):
    def test_seq_is_monotonic_and_incremental_polling_works(self):
        self.s.join("alice", "claude_code")
        self.s.add_task("one", "alice")
        self.s.add_task("two", "alice")

        events = self.s.events()
        seqs = [e["seq"] for e in events]
        self.assertEqual(seqs, sorted(seqs), "event seq must be monotonic")
        self.assertEqual(len(set(seqs)), len(seqs), "event seq must be unique")

        tail = self.s.events(since_seq=seqs[-1])
        self.assertEqual(tail, [], "polling from the newest seq should return nothing")

        self.s.post_update("alice", "still here")
        self.assertEqual(len(self.s.events(since_seq=seqs[-1])), 1)


class TestMemory(AgoraTestCase):
    def test_pins_are_newest_first(self):
        self.s.join("alice", "claude_code")
        self.s.add_pin("ship on friday", "alice")
        self.s.add_pin("use tabs", "alice")
        self.assertEqual(self.s.get_memory()["pinned"][0]["text"], "use tabs")

    def test_style_merges_rather_than_replaces(self):
        self.s.set_style({"voice": "terse"})
        self.s.set_style({"format": "markdown"})
        style = self.s.get_memory()["style"]
        self.assertEqual(style["voice"], "terse", "second write must not clobber the first")
        self.assertEqual(style["format"], "markdown")


class TestConcurrency(AgoraTestCase):
    def test_only_one_thread_wins_a_contested_claim(self):
        """The mutex must make claim_task a genuine critical section."""
        self.s.join("host", "claude_code")
        tid = self.s.add_task("contested", "host")["id"]

        winners, errors = [], []

        def grab(name):
            res = self.s.claim_task(tid, name)
            (winners if "error" not in res else errors).append(name)

        threads = [threading.Thread(target=grab, args=(f"agent{i}",)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(winners), 1, f"exactly one claimer should win, got {winners}")
        self.assertEqual(len(errors), 7)

    def test_concurrent_writes_keep_event_seq_unique(self):
        self.s.join("host", "claude_code")

        def spam(n):
            for i in range(5):
                self.s.post_update("host", f"{n}-{i}")

        threads = [threading.Thread(target=spam, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        seqs = [e["seq"] for e in self.s.events(limit=200)]
        self.assertEqual(len(set(seqs)), len(seqs), "concurrent appends must not duplicate seq")


if __name__ == "__main__":
    unittest.main(verbosity=2)
