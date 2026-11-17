"""Office-Travel data-safety and statistics tests.

Fake SQLite files and a fake GitHub only. travel.py is a Streamlit script, so
only the named functions are extracted from it (the app itself never runs).
"""
import ast
import base64
import gc
import json
import sqlite3
import tempfile
import unittest
import urllib
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd

SOURCE = Path(__file__).resolve().parent.parent / "travel.py"


def load(names, **env):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    missing = set(names) - {n.name for n in funcs}
    if missing:
        raise AssertionError(f"missing function(s): {sorted(missing)}")
    scope = {"sqlite3": sqlite3, "pd": pd, "json": json, "base64": base64,
             "urllib": urllib, "datetime": datetime, "TAIWAN_TZ": ZoneInfo("Asia/Taipei"), "time": SimpleNamespace(sleep=lambda _: None)}
    scope.update(env)
    exec(compile(ast.Module(body=funcs, type_ignores=[]), str(SOURCE), "exec"), scope)
    return scope


class FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.errors = []
    def error(self, text): self.errors.append(text)


def backup(members=(), records=()):
    return {"format": "office-travel-backup", "version": "2.0", "exported_at": "2026-01-01 00:00:00",
            "travel_location": "Fake place",
            "members": [{"id": i + 1, "name": n, "sort_order": i} for i, n in enumerate(members)],
            "records": [dict(id=i + 1, name=n, adults=1, children=0, children_0_6=0, children_7_13=0,
                             children_14_18=0, note="", record_time="2026-01-01 10:00",
                             participation_status="participating") for i, n in enumerate(records)]}


class FakeRemote:
    def __init__(self, data=None):
        self.data, self.fail, self.puts, self.gets = data, None, [], 0
    def get(self):
        self.gets += 1
        if self.fail:
            raise self.fail
        return (self.data, "sha-1" if self.data else None)


class StartupRestoreTests(unittest.TestCase):
    NAMES = ["db_connect", "execute_db", "get_db", "init_db", "get_restore_pending",
             "set_restore_pending", "run_startup_restore", "import_travel_data"]

    def setUp(self):
        # Windows cannot delete a SQLite file while a connection object is still alive
        # (travel.py's get_db leaves closing to the garbage collector), so collect first.
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(gc.collect)
        self.remote = FakeRemote()
        self.st = FakeStreamlit()
        self.configured = True
        self.env = load(self.NAMES, DB_FILE=str(Path(self.tmp.name) / "travel.db"), st=self.st,
                        github_is_configured=lambda: self.configured,
                        github_get_backup=self.remote.get)

    def counts(self):
        conn = sqlite3.connect(self.env["DB_FILE"])
        try:
            return tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                         for t in ("travel_members", "travel_records"))
        finally:
            conn.close()

    def start(self):
        is_new = self.env["init_db"]()
        return self.env["run_startup_restore"](is_new)

    def test_new_database_restores_backup_and_clears_pending(self):
        self.remote.data = backup(["甲", "乙"], ["甲"])
        self.assertEqual(self.start(), "restored")
        self.assertEqual(self.counts(), (2, 1))
        self.assertFalse(self.env["get_restore_pending"]())
        self.assertEqual(self.start(), "ready")  # next rerun: nothing pending

    def test_failed_restore_blocks_across_reruns_and_recovers_later(self):
        self.remote.data = backup(["甲", "乙"], ["甲"])
        self.remote.fail = TimeoutError("fake github timeout")
        self.assertEqual(self.start(), "failed")
        self.assertTrue(self.env["get_restore_pending"]())
        # Streamlit reruns: tables now exist, so init_db says "not new" — must STILL block.
        for _ in range(3):
            self.assertEqual(self.start(), "failed")
        self.assertEqual(self.counts(), (0, 0))
        self.assertEqual(self.remote.puts, [])
        self.assertIn("fake github timeout", self.st.session_state["restore_error"])
        self.remote.fail = None  # GitHub is back
        self.assertEqual(self.start(), "restored")
        self.assertEqual(self.counts(), (2, 1))
        self.assertEqual(self.start(), "ready")

    def test_undecryptable_or_invalid_backup_blocks_instead_of_wiping(self):
        self.remote.fail = ValueError("GitHub 備份無法解密")
        self.assertEqual(self.start(), "failed")
        self.remote.fail = None
        self.remote.data = {"format": "wrong"}
        self.assertEqual(self.start(), "failed")  # import rejects it; stays pending
        self.assertTrue(self.env["get_restore_pending"]())
        self.assertEqual(self.counts(), (0, 0))

    def test_verified_missing_backup_allows_fresh_start(self):
        self.remote.data = None
        self.assertEqual(self.start(), "missing")
        self.assertFalse(self.env["get_restore_pending"]())
        self.assertEqual(self.start(), "ready")

    def test_without_github_configuration_runs_locally(self):
        self.configured = False
        self.assertEqual(self.start(), "local_only")
        self.assertEqual(self.remote.gets, 0)

    def test_restore_marker_never_leaks_into_exported_backup(self):
        names = self.NAMES + ["export_travel_data", "get_location", "taiwan_now"]
        env = load(names, DB_FILE=self.env["DB_FILE"], st=self.st,
                   github_is_configured=lambda: True, github_get_backup=self.remote.get)
        self.remote.data = backup(["甲"], [])
        env["run_startup_restore"](env["init_db"]())
        exported = env["export_travel_data"]()
        self.assertNotIn("restore_pending", json.dumps(exported))


class PutGuardTests(unittest.TestCase):
    def setUp(self):
        self.remote = FakeRemote()
        self.requests = []
        self.put = load(["github_put_backup"],
            get_github_settings=lambda: ("tok", "o", "r", "main", "travel_data.json"),
            github_get_backup=self.remote.get,
            encrypt_github_backup=lambda data: json.dumps(data),
            github_request=lambda method, url, token, payload=None: self.requests.append((method, payload)),
            taiwan_now=lambda: __import__("datetime").datetime(2026, 1, 1))["github_put_backup"]

    def test_refuses_to_overwrite_real_backup_with_empty_database(self):
        self.remote.data = backup(["甲", "乙"], ["甲"])
        ok, message = self.put(backup())
        self.assertFalse(ok)
        self.assertIn("拒絕", message)
        self.assertEqual(self.requests, [])

    def test_members_only_database_may_overwrite_after_records_cleared(self):
        # Admin "clear all records" keeps the member list: this must still back up.
        self.remote.data = backup(["甲"], ["甲"])
        ok, _ = self.put(backup(["甲"], []))
        self.assertTrue(ok)
        self.assertEqual(self.requests[0][0], "PUT")
        self.assertEqual(self.requests[0][1]["sha"], "sha-1")

    def test_first_upload_without_remote_file_has_no_sha(self):
        ok, _ = self.put(backup(["甲"], []))
        self.assertTrue(ok)
        self.assertNotIn("sha", self.requests[0][1])

    def test_unreadable_remote_never_uploads(self):
        self.remote.fail = TimeoutError("fake")
        with self.assertRaises(TimeoutError):
            self.put(backup(["甲"], []))
        self.assertEqual(self.requests, [])


class SyncAfterWriteTests(unittest.TestCase):
    def run_case(self, ok):
        calls = []
        env = load(["sync_after_write"],
                   sync_github_backup=lambda show_error=False: ok,
                   set_github_sync_success_status=lambda: calls.append("status"))
        return env["sync_after_write"](), calls

    def test_confirmed_backup_updates_status(self):
        self.assertEqual(self.run_case(True), (True, ["status"]))

    def test_failed_backup_is_reported_not_hidden(self):
        self.assertEqual(self.run_case(False), (False, []))

    def test_new_record_insert_triggers_backup(self):
        # Regression: the first submission used to be saved locally only.
        text = SOURCE.read_text(encoding="utf-8")
        marker = "INSERT INTO travel_records\n                           (name, adults"
        self.assertIn(marker, text)
        after = text[text.index(marker):]
        self.assertIn("sync_after_write()", after[:1800])


class StatisticsTests(unittest.TestCase):
    def setUp(self):
        self.totals = load(["compute_travel_totals"])["compute_travel_totals"]

    def frame(self, rows):
        cols = ["name", "adults", "children", "children_0_6", "children_7_13",
                "children_14_18", "participation_status"]
        return pd.DataFrame(rows, columns=cols)

    def test_totals_add_up(self):
        df = self.frame([
            ("甲", 2, 3, 1, 1, 1, "participating"),
            ("乙", 1, 0, 0, 0, 0, "participating"),
            ("丙", 0, 0, 0, 0, 0, "not_participating"),
            ("丁", 3, 1, 0, 1, 0, "participating"),
        ])
        t = self.totals(df)
        self.assertEqual((t["adults"], t["children"], t["total"]), (6, 4, 10))
        self.assertEqual((t["age_0_6"], t["age_7_13"], t["age_14_18"]), (1, 2, 1))
        self.assertEqual((t["participating"], t["not_participating"]), (3, 1))
        self.assertEqual(t["mismatched"], [])

    def test_not_participating_rows_never_count_even_with_stale_numbers(self):
        df = self.frame([("甲", 2, 1, 1, 0, 0, "participating"),
                         ("乙", 5, 2, 1, 1, 0, "not_participating")])
        t = self.totals(df)
        self.assertEqual((t["adults"], t["children"], t["total"]), (2, 1, 3))
        self.assertEqual(t["not_participating"], 1)

    def test_missing_status_counts_as_participating(self):
        df = self.frame([("甲", 1, 0, 0, 0, 0, None)])
        self.assertEqual(self.totals(df)["total"], 1)

    def test_inconsistent_children_column_is_flagged_and_ages_win(self):
        df = self.frame([("舊資料", 1, 2, 0, 0, 0, "participating"),
                         ("正常", 1, 1, 1, 0, 0, "participating")])
        t = self.totals(df)
        self.assertEqual(t["mismatched"], ["舊資料"])
        self.assertEqual(t["children"], 1)

    def test_empty_frame(self):
        t = self.totals(pd.DataFrame())
        self.assertEqual((t["total"], t["participating"], t["not_participating"]), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
