"""Office-Travel data-safety and statistics tests.

Fake SQLite files and a fake GitHub only. travel.py is a Streamlit script, so
only the named functions are extracted from it (the app itself never runs).
"""
import ast
import base64
import gc
import hmac
import json
import sqlite3
import tempfile
import unittest
import urllib
from unittest.mock import MagicMock
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd

SOURCE = Path(__file__).resolve().parent.parent / "travel.py"


class TrackedSqlite:
    """sqlite3 stand-in that remembers every connection so tests can close them.

    travel.py's get_db leaves closing to the garbage collector; on Windows that keeps
    the .db file locked and the temp folder cannot be deleted.
    """
    def __init__(self):
        self.connections = []
    def connect(self, *args, **kwargs):
        conn = sqlite3.connect(*args, **kwargs)
        self.connections.append(conn)
        return conn
    def close_all(self):
        for conn in self.connections:
            try:
                conn.close()
            except Exception:
                pass
        self.connections.clear()
    def __getattr__(self, name):
        return getattr(sqlite3, name)


def load(names, **env):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    missing = set(names) - {n.name for n in funcs}
    if missing:
        raise AssertionError(f"missing function(s): {sorted(missing)}")
    scope = {"sqlite3": env.pop("sqlite_module", sqlite3), "pd": pd, "json": json, "base64": base64,
             "urllib": urllib, "hmac": hmac, "datetime": datetime, "TAIWAN_TZ": ZoneInfo("Asia/Taipei"), "time": SimpleNamespace(sleep=lambda _: None)}
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
        self.tracked = TrackedSqlite()
        self.addCleanup(self.tmp.cleanup)   # runs last
        self.addCleanup(gc.collect)
        self.addCleanup(self.tracked.close_all)  # runs first
        self.remote = FakeRemote()
        self.st = FakeStreamlit()
        self.configured = True
        self.env = load(self.NAMES, sqlite_module=self.tracked,
                        DB_FILE=str(Path(self.tmp.name) / "travel.db"), st=self.st,
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
        env = load(names, sqlite_module=self.tracked, DB_FILE=self.env["DB_FILE"], st=self.st,
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


class AdminLoginTests(unittest.TestCase):
    def setUp(self):
        env = load(["verify_admin_password"], ADMIN_MAX_FAILURES=5, ADMIN_LOCK_SECONDS=60)
        self.verify = env["verify_admin_password"]
        self.throttle = {"failures": 0, "locked_until": 0.0}

    def test_correct_password_logs_in_and_resets_failures(self):
        self.throttle["failures"] = 3
        self.assertEqual(self.verify("pw", "pw", self.throttle, 100.0), (True, ""))
        self.assertEqual(self.throttle["failures"], 0)

    def test_wrong_empty_or_unconfigured_password_is_rejected(self):
        for candidate, expected in (("bad", "pw"), ("", "pw"), ("pw", ""), ("", "")):
            ok, _ = self.verify(candidate, expected, self.throttle, 100.0)
            self.assertFalse(ok, (candidate, expected))

    def test_five_failures_lock_even_the_correct_password_until_expiry(self):
        for _ in range(5):
            ok, message = self.verify("bad", "pw", self.throttle, 100.0)
        self.assertFalse(ok)
        self.assertIn("鎖定", message)
        ok, message = self.verify("pw", "pw", self.throttle, 130.0)
        self.assertFalse(ok)
        self.assertIn("31 秒", message)  # 160 - 130 = 30s left, rounded up
        self.assertEqual(self.verify("pw", "pw", self.throttle, 161.0), (True, ""))

    def test_non_ascii_password_works(self):
        self.assertTrue(self.verify("密碼123", "密碼123", self.throttle, 1.0)[0])


class AttrState(dict):
    __getattr__ = dict.get
    def __setattr__(self, key, value): self[key] = value


class AdminPanelTests(unittest.TestCase):
    """The admin features live in a main-page tab, not in a sidebar."""

    def build(self, logged_in):
        st = MagicMock()
        st.session_state = AttrState(admin_logged_in=logged_in)
        st.button.return_value = False
        st.text_input.return_value = ""
        st.tabs.side_effect = lambda labels: [MagicMock() for _ in labels]
        stubs = {n: MagicMock() for n in (
            "get_location", "save_location", "sync_github_backup", "set_github_sync_success_status",
            "manage_members_dialog", "export_travel_data", "github_is_configured", "get_db",
            "get_db_path", "get_db_size", "get_db_diagnostics", "import_travel_data", "execute_db",
            "restore_github_sync_status", "get_admin_password", "verify_admin_password",
            "admin_login_throttle", "get_github_settings", "taiwan_now")}
        stubs["export_travel_data"].return_value = {}
        stubs["get_db_size"].return_value = 0
        stubs["get_db_path"].return_value = "x.db"
        stubs["github_is_configured"].return_value = False
        stubs["get_db_diagnostics"].return_value = {"exists": True, "travel_members": 0,
            "travel_records": 0, "travel_config": 0, "secret_members": 0, "db_error": ""}
        stubs["test_github_encryption_key"] = lambda: (True, "")
        env = load(["render_admin_panel"], st=st, time=SimpleNamespace(monotonic=lambda: 0.0),
                   json=json, **stubs)
        return st, env["render_admin_panel"], stubs

    def test_logged_out_shows_only_the_login_form(self):
        st, render, stubs = self.build(False)
        render()
        st.text_input.assert_called_once()
        self.assertEqual(st.text_input.call_args.kwargs["type"], "password")
        st.tabs.assert_not_called()
        st.download_button.assert_not_called()
        stubs["export_travel_data"].assert_not_called()

    def test_logged_in_shows_the_four_admin_sections(self):
        st, render, _ = self.build(True)
        render()
        labels = st.tabs.call_args.args[0]
        self.assertEqual(len(labels), 4)
        for word in ("旅遊設定", "資料備份", "GitHub", "資料管理"):
            self.assertTrue(any(word in label for label in labels), word)

    def test_sidebar_is_gone_and_admin_tab_is_in_the_main_page(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("st.sidebar", text)
        self.assertIn('"🔐 管理員"', text)
        self.assertIn("with tab3:\n    render_admin_panel()", text)
        self.assertIn('initial_sidebar_state="collapsed"', text)


class ResetDialogTests(unittest.TestCase):
    """Clearing all records must be a dialog that closes on success and explains failure."""

    def build(self, sync_ok):
        st = MagicMock()
        st.session_state = AttrState(admin_logged_in=True)
        st.dialog = lambda *a, **k: (lambda f: f)
        st.button.return_value = True
        records = pd.DataFrame([{"id": 1, "name": "甲", "adults": 1}, {"id": 2, "name": "乙", "adults": 2}])
        count = pd.DataFrame([{"n": 37}])
        queries = []
        env = load(["admin_flash", "reset_records_dialog"], st=st,
                   get_db=lambda q, params=(): records if "travel_records" in q else count,
                   execute_db=lambda q, params=(): queries.append((q, params)),
                   sync_github_backup=lambda show_error=False: sync_ok,
                   taiwan_now=lambda: datetime(2026, 1, 1, 12, 0, 0))
        return st, env, queries

    def test_success_clears_flashes_and_closes_dialog_by_rerun(self):
        st, env, queries = self.build(True)
        env["reset_records_dialog"]()
        st.rerun.assert_called_once()
        st.error.assert_not_called()
        self.assertEqual(queries, [("DELETE FROM travel_records", ())])
        kind, text = st.session_state["admin_flash"]
        self.assertEqual(kind, "success")
        self.assertIn("已全部清除", text)
        self.assertEqual(st.session_state["github_sync_result"][0], "success")

    def test_failed_backup_restores_records_and_stays_open_with_the_reason(self):
        st, env, queries = self.build(False)
        env["reset_records_dialog"]()
        st.rerun.assert_not_called()
        st.error.assert_called_once()
        self.assertIn("已取消本次清除", st.error.call_args.args[0])
        inserts = [q for q in queries if q[0].startswith("INSERT INTO travel_records")]
        self.assertEqual(len(inserts), 2)
        self.assertNotIn("admin_flash", st.session_state)

    def test_non_admin_cannot_use_it(self):
        st, env, queries = self.build(True)
        st.session_state["admin_logged_in"] = False
        env["reset_records_dialog"]()
        self.assertEqual(queries, [])
        st.error.assert_called_once()

    def test_reset_is_no_longer_a_popover(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn('st.popover("🗑️ 清空全部旅遊資料"', text)
        self.assertIn("reset_records_dialog()", text)


class AdminFlashDisplayTests(AdminPanelTests):
    def test_flash_message_is_shown_once_on_the_admin_tab(self):
        st, render, _ = self.build(True)
        st.session_state["admin_flash"] = ("success", "✅ 旅遊地點已儲存：阿里山")
        render()
        self.assertIn("✅ 旅遊地點已儲存：阿里山", [c.args[0] for c in st.success.call_args_list])
        self.assertNotIn("admin_flash", st.session_state)

    def test_warning_flash_uses_warning_style(self):
        st, render, _ = self.build(True)
        st.session_state["admin_flash"] = ("warning", "備份未成功")
        render()
        st.warning.assert_any_call("備份未成功")


if __name__ == "__main__":
    unittest.main()
