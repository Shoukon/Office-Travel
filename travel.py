import streamlit as st
import json
from cryptography.fernet import Fernet, InvalidToken
import base64
import urllib.request
import urllib.parse
import urllib.error
import pandas as pd
import sqlite3
import time
import html
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

DB_FILE = "travel.db"
VERSION = "v1.1.2"
GITHUB_SYNC_SUPPRESSED = False


if "github_sync_result" not in st.session_state:
    st.session_state["github_sync_result"] = None

st.set_page_config(
    page_title=f"旅遊哦各位～ {VERSION}",
    page_icon="🚌",
    layout="wide"
)

st.markdown("""
<style>
html, body, button, input, textarea, select,
[data-baseweb], [class*="st-"]:not([data-testid="stIconMaterial"]) {
    font-family: "Microsoft JhengHei", "微軟正黑體", "Segoe UI Emoji",
                 "Noto Color Emoji", "Apple Color Emoji", sans-serif !important;
}
[data-testid="stIconMaterial"], .material-symbols-rounded,
.material-symbols-outlined {
    font-family: "Material Symbols Rounded" !important;
}
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
.stTabs [data-baseweb="tab-list"] {
    gap: 16px;
    border-bottom: 1px solid rgba(128,128,128,0.2);
}
.stTabs [data-baseweb="tab"] {
    height: 52px;
    border-radius: 8px 8px 0 0;
    background-color: transparent;
    padding: 10px 16px;
    font-weight: 600;
    color: #7f8c8d;
    font-size: 1.1rem;
    border: none;
}
.stTabs [aria-selected="true"] {
    color: #4A90E2 !important;
    border-bottom: 3px solid #4A90E2 !important;
}
.section-header {
    padding: 14px 20px;
    border-radius: 8px;
    margin-bottom: 15px;
    color: white;
    font-weight: 700;
    font-size: 1.2rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    box-shadow: 0 2px 6px rgba(0,0,0,0.15);
}
.header-people { background: linear-gradient(135deg, #4A90E2, #357ABD); }
.header-adult { background: linear-gradient(135deg, #5B8FF9, #3B6FD8); }
.header-child { background: linear-gradient(135deg, #5CB85C, #3F9440); }
.header-total { background: linear-gradient(135deg, #8E7CC3, #6F5AA8); }
.list-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding: 6px 8px;
    margin-bottom: 2px;
}
.list-col-left {
    display: flex;
    flex-direction: column;
    gap: 2px;
}
.list-title-group {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
}
.list-name {
    font-size: 1.15rem;
    font-weight: 700;
    color: var(--text-color);
    margin-right: 20px;
}
.list-qty {
    font-size: 1.15rem;
    font-weight: 800;
    color: #FF4B4B;
}
.custom-text {
    font-size: 1rem;
    color: #838484;
    margin-top: 2px;
    line-height: 1.4;
}
hr.person-divider {
    border: 0;
    height: 1px;
    background: rgba(128,128,128,0.3);
    margin: 16px 0;
}
.big-number {
    font-size: 2rem;
    font-weight: 800;
    line-height: 1.15;
}
.small-label {
    font-size: 0.95rem;
    color: #838484;
}
</style>
""", unsafe_allow_html=True)


def db_connect():
    return sqlite3.connect(DB_FILE, check_same_thread=False, timeout=10)


def execute_db(query, params=()):
    """Execute one SQLite write. GitHub backup is triggered explicitly."""
    for _ in range(5):
        conn = None
        try:
            conn = db_connect()
            cur = conn.cursor()
            cur.execute(query, params)
            affected = cur.rowcount
            conn.commit()
            return affected
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                time.sleep(0.1)
            else:
                raise
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    st.error("⚠️ 系統忙碌，請稍後再試。")
    return 0


def get_db(query, params=()):
    try:
        with db_connect() as conn:
            return pd.read_sql_query(query, conn, params=params)
    except Exception as e:
        st.error(f"⚠️ 資料庫讀取失敗：{e}")
        return pd.DataFrame()


def init_db():
    conn = db_connect()
    cur = conn.cursor()
    existing_tables = {
        row[0] for row in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('travel_members','travel_records','travel_config')"
        ).fetchall()
    }
    is_new_db = not existing_tables

    cur.execute("""
        CREATE TABLE IF NOT EXISTS travel_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS travel_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            adults INTEGER NOT NULL DEFAULT 0,
            children INTEGER NOT NULL DEFAULT 0,
            children_0_6 INTEGER NOT NULL DEFAULT 0,
            children_7_13 INTEGER NOT NULL DEFAULT 0,
            children_14_18 INTEGER NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT '',
            record_time TEXT NOT NULL
        )
    """)

    columns = [row[1] for row in cur.execute("PRAGMA table_info(travel_records)").fetchall()]
    migrations = {
        "children_0_6": "ALTER TABLE travel_records ADD COLUMN children_0_6 INTEGER NOT NULL DEFAULT 0",
        "children_7_13": "ALTER TABLE travel_records ADD COLUMN children_7_13 INTEGER NOT NULL DEFAULT 0",
        "children_14_18": "ALTER TABLE travel_records ADD COLUMN children_14_18 INTEGER NOT NULL DEFAULT 0",
    }
    for column, statement in migrations.items():
        if column not in columns:
            cur.execute(statement)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS travel_config (
            config_key TEXT PRIMARY KEY,
            config_value TEXT NOT NULL DEFAULT ''
        )
    """)

    cur.execute("""
        INSERT OR IGNORE INTO travel_config
        (config_key, config_value)
        VALUES ('travel_location', '')
    """)

    conn.commit()
    conn.close()
    conn = db_connect()
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(travel_records)").fetchall()]
        if "participation_status" not in cols:
            conn.execute("ALTER TABLE travel_records ADD COLUMN participation_status TEXT DEFAULT 'participating'")
            conn.commit()
    finally:
        conn.close()

    return is_new_db


TAIWAN_TZ = ZoneInfo("Asia/Taipei")


def taiwan_now():
    return datetime.now(TAIWAN_TZ)


def taiwan_now_str():
    return taiwan_now().strftime("%Y-%m-%d %H:%M")


def get_github_settings():
    try:
        cfg = st.secrets.get("github", {})
        token = str(cfg.get("token", "")).strip()
        owner = str(cfg.get("owner", "")).strip()
        repo = str(cfg.get("repo", "")).strip()
        branch = str(cfg.get("branch", "main")).strip() or "main"
        path = str(cfg.get("data_file", "travel_data.json")).strip() or "travel_data.json"
        return token, owner, repo, branch, path
    except Exception:
        return "", "", "", "main", "travel_data.json"


def github_is_configured():
    token, owner, repo, branch, path = get_github_settings()
    return bool(token and owner and repo and get_github_encryption_key())


def github_request(method, url, token, payload=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "office-travel-streamlit",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def test_github_encryption_key():
    key = get_github_encryption_key()
    if not key:
        return False, "尚未設定 encryption_key。"
    try:
        f = Fernet(key)
        test_plain = b"Office-Travel encryption test"
        encrypted = f.encrypt(test_plain)
        decrypted = f.decrypt(encrypted)
        if decrypted != test_plain:
            return False, "加密金鑰測試失敗。"
        return True, "加密金鑰正常，可以正常加密／解密。"
    except Exception as e:
        return False, f"encryption_key 格式錯誤：{e}"


def get_github_encryption_key():
    try:
        key = str(st.secrets.get("github", {}).get("encryption_key", "")).strip()
        if not key:
            return None
        return key.encode("utf-8")
    except Exception:
        return None


def encrypt_github_backup(data):
    key = get_github_encryption_key()
    if not key:
        raise ValueError("尚未設定 GitHub encryption_key。")
    payload = dict(data)
    payload["backup_format"] = "office-travel-encrypted-v1"
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return Fernet(key).encrypt(raw).decode("ascii")


def decrypt_github_backup(encrypted_text):
    key = get_github_encryption_key()
    if not key:
        raise ValueError("尚未設定 GitHub encryption_key。")
    try:
        raw = Fernet(key).decrypt(encrypted_text.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except (InvalidToken, ValueError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(
            "GitHub 備份無法解密：加密金鑰不正確，或 GitHub 上仍是舊版明文備份。"
        ) from e

    if data.get("backup_format") != "office-travel-encrypted-v1":
        raise ValueError("GitHub 備份格式不是目前的加密版本。")
    return data


def github_get_backup():
    token, owner, repo, branch, path = get_github_settings()
    if not (token and owner and repo):
        return None, None

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={urllib.parse.quote(branch, safe='')}"
    try:
        result = github_request("GET", url, token)
        encoded = result.get("content", "").replace("\n", "")
        if not encoded.strip():
            return None, result.get("sha")

        raw_text = base64.b64decode(encoded).decode("utf-8")
        if not raw_text.strip():
            return None, result.get("sha")

        # Migration path: the first v1.0.8 test created a plaintext JSON backup.
        # Do not try to import it as an encrypted backup. Return no backup data
        # but keep its SHA so the next sync can safely replace it in-place.
        try:
            data = decrypt_github_backup(raw_text)
            return data, result.get("sha")
        except ValueError:
            try:
                legacy = json.loads(raw_text)
                if isinstance(legacy, dict) and legacy.get("format") == "office-travel-backup":
                    return None, result.get("sha")
            except Exception:
                pass
            raise ValueError(
                "GitHub 備份無法解密：加密金鑰不正確，或備份內容已損壞。"
            )
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None
        raise


def github_put_backup(data):
    token, owner, repo, branch, path = get_github_settings()
    if not (token and owner and repo):
        return False, "尚未設定 GitHub Secrets。"

    _, sha = github_get_backup()
    encrypted_text = encrypt_github_backup(data)
    payload = {
        "message": f"Update encrypted travel data {taiwan_now().strftime('%Y-%m-%d %H:%M:%S')}",
        "content": base64.b64encode(encrypted_text.encode("ascii")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    try:
        github_request("PUT", url, token, payload)
        return True, ""
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code == 409:
            return False, "GitHub 備份發生版本衝突，請稍後再試。"
        return False, f"GitHub API 錯誤 {e.code}：{body[:300]}"
    except Exception as e:
        return False, str(e)


def sync_github_backup(show_error=False):
    if not github_is_configured():
        return False
    try:
        data = export_travel_data()
        ok, message = github_put_backup(data)
        if not ok and show_error:
            st.error(f"⚠️ GitHub 備份同步失敗：{message}")
        return ok
    except Exception as e:
        if show_error:
            st.error(f"⚠️ GitHub 備份同步失敗：{e}")
        return False


def restore_from_github_if_new_db(is_new_db):
    if not is_new_db or not github_is_configured():
        return False

    global GITHUB_SYNC_SUPPRESSED
    try:
        backup, _ = github_get_backup()
        if not backup:
            return False
        GITHUB_SYNC_SUPPRESSED = True
        import_travel_data(backup)
        return True
    except Exception as e:
        st.warning(f"⚠️ 找到 GitHub 備份，但自動還原失敗：{e}")
        return False
    finally:
        GITHUB_SYNC_SUPPRESSED = False


def export_travel_data():
    """Export all persistent travel data to a JSON-compatible dict."""
    data = {
        "format": "office-travel-backup",
        "version": "2.0",
        "exported_at": taiwan_now().strftime("%Y-%m-%d %H:%M:%S"),
        "travel_location": get_location(),
        "members": [],
        "records": [],
    }

    with db_connect() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        for row in cur.execute(
            "SELECT id, name, sort_order FROM travel_members ORDER BY sort_order, id"
        ):
            data["members"].append(dict(row))

        for row in cur.execute(
            """SELECT id, name, adults, children,
                      children_0_6, children_7_13, children_14_18,
                      note, record_time, participation_status
               FROM travel_records
               ORDER BY id"""
        ):
            data["records"].append(dict(row))

    return data


def import_travel_data(data):
    """Replace current travel data with a validated backup."""
    if not isinstance(data, dict):
        raise ValueError("備份檔格式錯誤。")

    if data.get("format") != "office-travel-backup":
        raise ValueError("不是旅遊系統的備份檔。")

    members = data.get("members")
    records = data.get("records")
    location = data.get("travel_location", "")

    if not isinstance(members, list) or not isinstance(records, list):
        raise ValueError("備份檔缺少名單或旅遊資料。")

    # Validate all records before changing the database.
    member_rows = []
    member_names = set()
    for item in members:
        if not isinstance(item, dict):
            raise ValueError("名單資料格式錯誤。")
        name = str(item.get("name", "")).strip()
        if not name or name in member_names:
            raise ValueError("名單包含空白或重複姓名。")
        member_names.add(name)
        sort_order = int(item.get("sort_order", len(member_rows)))
        member_rows.append((name, sort_order))

    record_rows = []
    record_names = set()
    member_name_set = set(member_names)
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("旅遊資料格式錯誤。")
        name = str(item.get("name", "")).strip()
        if not name or name in record_names:
            raise ValueError("旅遊資料包含空白或重複姓名。")
        record_names.add(name)
        if name not in member_name_set:
            raise ValueError(f"旅遊資料中的姓名「{name}」不在名單中。")

        try:
            adults = int(item.get("adults", 0))
            children = int(item.get("children", 0))
            age_0_6 = int(item.get("children_0_6", 0))
            age_7_13 = int(item.get("children_7_13", 0))
            age_14_18 = int(item.get("children_14_18", 0))
        except (TypeError, ValueError) as e:
            raise ValueError(f"「{name}」的人數資料格式錯誤。") from e

        values = (adults, children, age_0_6, age_7_13, age_14_18)
        if any(v < 0 for v in values):
            raise ValueError(f"「{name}」的人數不能為負數。")
        if children != age_0_6 + age_7_13 + age_14_18:
            raise ValueError(f"「{name}」的小孩總數與各年齡層人數不一致。")

        participation_status = str(
            item.get("participation_status", "participating")
        ).strip()
        if participation_status not in ("participating", "not_participating"):
            raise ValueError(f"「{name}」的參加狀態無效。")
        if participation_status == "not_participating" and any(values):
            raise ValueError(f"「{name}」設定為不參加時，人數必須全部為 0。")

        record_rows.append((
            name, adults, children, age_0_6, age_7_13, age_14_18,
            str(item.get("note", "")),
            str(item.get("record_time", "")),
            participation_status,
        ))

    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM travel_records")
        cur.execute("DELETE FROM travel_members")

        cur.executemany(
            """INSERT INTO travel_members (name, sort_order)
               VALUES (?, ?)""",
            member_rows,
        )

        cur.executemany(
            """INSERT INTO travel_records
               (name, adults, children, children_0_6, children_7_13,
                children_14_18, note, record_time, participation_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            record_rows,
        )

        cur.execute(
            """UPDATE travel_config
               SET config_value=?
               WHERE config_key='travel_location'""",
            (str(location).strip(),),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_admin_password():
    try:
        return str(st.secrets["admin"]["password"]).strip()
    except Exception:
        return ""


def get_db_path():
    return str(Path(DB_FILE).resolve())


def get_db_size():
    try:
        return Path(DB_FILE).stat().st_size
    except OSError:
        return 0

def get_db_diagnostics():
    result = {
        "path": get_db_path(),
        "exists": Path(DB_FILE).exists(),
        "size": get_db_size(),
        "travel_members": None,
        "travel_records": None,
        "travel_config": None,
        "secret_members": None,
    }

    try:
        with db_connect() as conn:
            cur = conn.cursor()
            for table in ("travel_members", "travel_records", "travel_config"):
                cur.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                )
                if cur.fetchone()[0]:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    result[table] = cur.fetchone()[0]
                else:
                    result[table] = "不存在"
    except Exception as e:
        result["db_error"] = str(e)

    try:
        settings = st.secrets.get("default_settings", {})
        names = settings.get("colleagues", [])
        result["secret_members"] = len(
            [str(name).strip() for name in names if str(name).strip()]
        )
    except Exception:
        result["secret_members"] = 0

    return result


def get_not_participating_count():
    return int(execute_scalar(
        "SELECT COUNT(*) FROM travel_records WHERE participation_status='not_participating'"
    ) or 0)


def get_location():
    df = get_db(
        "SELECT config_value FROM travel_config WHERE config_key='travel_location'"
    )
    return str(df.iloc[0]["config_value"]).strip() if not df.empty else ""


def get_members():
    return get_db(
        "SELECT id, name, sort_order FROM travel_members ORDER BY sort_order, id"
    )


def save_location(value):
    return execute_db(
        "UPDATE travel_config SET config_value=? WHERE config_key='travel_location'",
        (value.strip(),)
    )


def seed_members_from_secrets_once():
    members = get_members()
    if not members.empty:
        return

    try:
        settings = st.secrets.get("default_settings", {})
        names = settings.get("colleagues", [])
    except Exception:
        names = []

    cleaned = []
    for name in names:
        name = str(name).strip()
        if name and name not in cleaned:
            cleaned.append(name)

    for order, name in enumerate(cleaned):
        execute_db(
            "INSERT OR IGNORE INTO travel_members (name, sort_order) VALUES (?, ?)",
            (name, order)
        )


is_new_db = init_db()
restored_from_github = restore_from_github_if_new_db(is_new_db)
if not restored_from_github:
    seed_members_from_secrets_once()
    if is_new_db and github_is_configured():
        sync_github_backup(show_error=False)

if "user_name" not in st.session_state:
    st.session_state.user_name = None
if "admin_logged_in" not in st.session_state:
    st.session_state.admin_logged_in = False
if "confirm_reset" not in st.session_state:
    st.session_state.confirm_reset = False



def move_member(member_id, direction):
    members = get_members()
    if members.empty:
        return

    ids = members["id"].astype(int).tolist()
    try:
        index = ids.index(int(member_id))
    except ValueError:
        return

    target_index = index + direction
    if target_index < 0 or target_index >= len(ids):
        return

    current_id = ids[index]
    target_id = ids[target_index]
    current_order = int(members.iloc[index]["sort_order"])
    target_order = int(members.iloc[target_index]["sort_order"])

    execute_db(
        "UPDATE travel_members SET sort_order=? WHERE id=?",
        (target_order, current_id)
    )
    execute_db(
        "UPDATE travel_members SET sort_order=? WHERE id=?",
        (current_order, target_id)
    )

@st.dialog("👥 管理旅遊名單", width="large")
def manage_members_dialog():
    if not st.session_state.admin_logged_in:
        st.error("🔒 只有管理員可以使用此功能。")
        return

    st.caption("新增、修改或刪除旅遊名單。修改後會永久保存於 travel.db。")

    search = st.text_input("🔎 搜尋姓名", placeholder="輸入姓名關鍵字")
    members = get_members()

    if search.strip():
        members = members[
            members["name"].astype(str).str.contains(
                search.strip(), case=False, na=False
            )
        ]

    st.write(f"目前共 {len(get_members())} 人")

    all_members = get_members()
    all_ids = all_members["id"].astype(int).tolist() if not all_members.empty else []

    for _, row in members.iterrows():
        member_id = int(row["id"])
        name = str(row["name"])
        position = all_ids.index(member_id) if member_id in all_ids else 0
        is_first = position == 0
        is_last = position == len(all_ids) - 1

        c_name, c_up, c_down, c_edit, c_delete = st.columns(
            [6, 0.7, 0.7, 0.8, 0.8],
            vertical_alignment="center"
        )

        with c_name:
            st.markdown(f"**👤 {html.escape(name)}**")

        with c_up:
            if st.button(
                "⬆️",
                key=f"member_up_{member_id}",
                disabled=is_first,
                help="往上移",
                use_container_width=True
            ):
                move_member(member_id, -1)
                sync_github_backup(show_error=False)
                st.rerun()

        with c_down:
            if st.button(
                "⬇️",
                key=f"member_down_{member_id}",
                disabled=is_last,
                help="往下移",
                use_container_width=True
            ):
                move_member(member_id, 1)
                sync_github_backup(show_error=False)
                st.rerun()

        with c_edit:
            if st.button(
                "✏️",
                key=f"member_edit_{member_id}",
                help="修改姓名",
                use_container_width=True
            ):
                st.session_state["editing_member_id"] = member_id

        with c_delete:
            if st.button(
                "🗑️",
                key=f"member_delete_{member_id}",
                help="移除人員",
                use_container_width=True
            ):
                st.session_state["deleting_member_id"] = member_id

        if st.session_state.get("editing_member_id") == member_id:
            new_name = st.text_input(
                "修改姓名",
                value=name,
                key=f"member_name_{member_id}"
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button("💾 儲存", key=f"member_save_{member_id}", type="primary", use_container_width=True):
                    new_name = new_name.strip()
                    exists = get_db(
                        "SELECT id FROM travel_members WHERE name=? AND id<>?",
                        (new_name, member_id)
                    )
                    if not new_name:
                        st.error("姓名不能為空。")
                    elif not exists.empty:
                        st.error("這個姓名已存在。")
                    else:
                        old = get_db(
                            "SELECT name FROM travel_members WHERE id=?",
                            (member_id,)
                        )
                        old_name = str(old.iloc[0]["name"]) if not old.empty else ""
                        execute_db(
                            "UPDATE travel_members SET name=? WHERE id=?",
                            (new_name, member_id)
                        )
                        if old_name and old_name != new_name:
                            execute_db(
                                "UPDATE travel_records SET name=? WHERE name=?",
                                (new_name, old_name)
                            )
                        sync_github_backup(show_error=False)
                        st.session_state.pop("editing_member_id", None)
                        st.rerun()
            with c2:
                if st.button("取消", key=f"member_cancel_{member_id}", use_container_width=True):
                    st.session_state.pop("editing_member_id", None)
                    st.rerun()

        if st.session_state.get("deleting_member_id") == member_id:
            st.warning(f"確定要移除「{name}」嗎？既有旅遊統計資料不會刪除。")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("🗑️ 確定移除", key=f"member_confirm_delete_{member_id}", type="primary", use_container_width=True):
                    execute_db("DELETE FROM travel_members WHERE id=?", (member_id,))
                    sync_github_backup(show_error=False)
                    st.session_state.pop("deleting_member_id", None)
                    if st.session_state.user_name == name:
                        st.session_state.user_name = None
                    st.rerun()
            with c2:
                if st.button("取消", key=f"member_cancel_delete_{member_id}", use_container_width=True):
                    st.session_state.pop("deleting_member_id", None)
                    st.rerun()

        st.markdown("<hr class='person-divider'>", unsafe_allow_html=True)

    st.markdown("### ➕ 新增人員")
    new_member = st.text_input(
        "姓名",
        placeholder="輸入新姓名",
        key="new_member_name"
    )

    if st.button("＋ 新增人員", type="primary", use_container_width=True):
        new_member = new_member.strip()
        if not new_member:
            st.error("請輸入姓名。")
        else:
            exists = get_db(
                "SELECT id FROM travel_members WHERE name=?",
                (new_member,)
            )
            if not exists.empty:
                st.error("這個姓名已存在。")
            else:
                max_order = get_db(
                    "SELECT COALESCE(MAX(sort_order), -1) AS max_order FROM travel_members"
                )
                order = int(max_order.iloc[0]["max_order"]) + 1
                execute_db(
                    "INSERT INTO travel_members (name, sort_order) VALUES (?, ?)",
                    (new_member, order)
                )
                sync_github_backup(show_error=False)
                st.toast(f"✅ 已新增：{new_member}")
                st.rerun()



@st.dialog("✏️ 修改我的旅遊資料")
def edit_my_record_dialog(user_name):
    current = get_db(
        "SELECT * FROM travel_records WHERE name=? LIMIT 1",
        (user_name,)
    )
    if current.empty:
        st.info("目前沒有可修改的旅遊資料。")
        return

    row = current.iloc[0]
    current_status = str(row.get("participation_status", "participating") or "participating")

    participation = st.radio(
        "參加狀態",
        ["參加", "不參加"],
        index=0 if current_status == "participating" else 1,
        horizontal=True,
        key="my_edit_participation_status"
    )

    adults = st.number_input(
        "👨 大人",
        min_value=0,
        step=1,
        value=int(row["adults"]),
        format="%d",
        key="my_edit_adults",
        disabled=(participation == "不參加")
    )

    st.markdown("### 🧒 小孩")
    c1, c2, c3 = st.columns(3)
    with c1:
        age_0_6 = st.number_input(
            "0-6歲",
            min_value=0,
            step=1,
            value=int(row.get("children_0_6", 0)),
            format="%d",
            key="my_edit_0_6",
            disabled=(participation == "不參加")
        )
    with c2:
        age_7_13 = st.number_input(
            "7-13歲",
            min_value=0,
            step=1,
            value=int(row.get("children_7_13", 0)),
            format="%d",
            key="my_edit_7_13",
            disabled=(participation == "不參加")
        )
    with c3:
        age_14_18 = st.number_input(
            "14-18歲",
            min_value=0,
            step=1,
            value=int(row.get("children_14_18", 0)),
            format="%d",
            key="my_edit_14_18",
            disabled=(participation == "不參加")
        )

    if participation == "不參加":
        adults = 0
        age_0_6 = 0
        age_7_13 = 0
        age_14_18 = 0

    children = int(age_0_6) + int(age_7_13) + int(age_14_18)
    st.caption(f"🧒 小孩合計：{children} 人")

    note = st.text_area(
        "📝 備註",
        value=str(row["note"] or ""),
        height=110,
        key="my_edit_note"
    )

    total = int(adults) + children
    st.caption(f"👥 總人數：{total} 人")

    if st.button("💾 儲存我的修改", type="primary", use_container_width=True):
        if total <= 0 and participation == "參加":
            st.error("請至少填寫 1 位大人或小孩。")
            return

        affected = execute_db(
            """UPDATE travel_records
               SET adults=?, children=?, children_0_6=?, children_7_13=?,
                   children_14_18=?, note=?, participation_status=?, record_time=?
               WHERE name=?""",
            (
                int(adults),
                children,
                int(age_0_6),
                int(age_7_13),
                int(age_14_18),
                note.strip(),
                "participating" if participation == "參加" else "not_participating",
                taiwan_now().strftime("%Y-%m-%d %H:%M"),
                user_name
            )
        )
        if affected == 1:
            st.toast(f"✅ 已更新：{user_name}")
            st.rerun()


@st.dialog("✏️ 編輯旅遊資料")
def edit_record_dialog(record_id):
    if not st.session_state.admin_logged_in:
        st.error("🔒 只有管理員可以編輯。")
        return

    current = get_db(
        "SELECT * FROM travel_records WHERE id=?",
        (record_id,)
    )
    if current.empty:
        st.error("找不到這筆資料。")
        return

    row = current.iloc[0]
    name = str(row["name"])
    current_status = str(row.get("participation_status", "participating") or "participating")

    participation = st.radio(
        "參加狀態",
        ["參加", "不參加"],
        index=0 if current_status == "participating" else 1,
        horizontal=True,
        key=f"admin_edit_participation_{record_id}"
    )

    adults = st.number_input(
        "👨 大人",
        min_value=0,
        step=1,
        value=int(row["adults"]),
        format="%d",
        key=f"admin_edit_adults_{record_id}",
        disabled=(participation == "不參加")
    )

    st.markdown("### 🧒 小孩")
    c1, c2, c3 = st.columns(3)
    with c1:
        age_0_6 = st.number_input(
            "0-6歲",
            min_value=0,
            step=1,
            value=int(row.get("children_0_6", 0)),
            format="%d",
            key=f"admin_edit_0_6_{record_id}",
            disabled=(participation == "不參加")
        )
    with c2:
        age_7_13 = st.number_input(
            "7-13歲",
            min_value=0,
            step=1,
            value=int(row.get("children_7_13", 0)),
            format="%d",
            key=f"admin_edit_7_13_{record_id}",
            disabled=(participation == "不參加")
        )
    with c3:
        age_14_18 = st.number_input(
            "14-18歲",
            min_value=0,
            step=1,
            value=int(row.get("children_14_18", 0)),
            format="%d",
            key=f"admin_edit_14_18_{record_id}",
            disabled=(participation == "不參加")
        )

    if participation == "不參加":
        adults = 0
        age_0_6 = 0
        age_7_13 = 0
        age_14_18 = 0

    children = int(age_0_6) + int(age_7_13) + int(age_14_18)
    st.caption(f"🧒 小孩合計：{children} 人")

    note = st.text_area(
        "📝 備註",
        value=str(row["note"] or ""),
        height=100,
        key=f"admin_edit_note_{record_id}"
    )

    total = int(adults) + children
    st.caption(f"👥 總人數：{total} 人")

    if st.button("💾 儲存修改", type="primary", use_container_width=True):
        if total <= 0 and participation == "參加":
            st.error("請至少填寫 1 位大人或小孩。")
        else:
            execute_db(
                """UPDATE travel_records
                   SET adults=?, children=?, children_0_6=?, children_7_13=?,
                       children_14_18=?, note=?, participation_status=?, record_time=?
                   WHERE id=?""",
                (
                    int(adults),
                    children,
                    int(age_0_6),
                    int(age_7_13),
                    int(age_14_18),
                    note.strip(),
                    "participating" if participation == "參加" else "not_participating",
                    taiwan_now().strftime("%Y-%m-%d %H:%M"),
                    record_id
                )
            )
            st.toast(f"✅ 已更新：{name}")
            st.rerun()


with st.sidebar:
    st.header("⚙️ 旅遊管理")

    st.subheader("📍 旅遊地點")
    location = get_location()

    if st.session_state.admin_logged_in:
        location_input = st.text_input(
            "旅遊地點名稱",
            value=location,
            placeholder="例如：阿里山、台南兩日遊"
        )
        if st.button("💾 儲存旅遊地點", type="primary", use_container_width=True):
            if not location_input.strip():
                st.error("請輸入旅遊地點。")
            else:
                save_location(location_input)
                sync_github_backup(show_error=False)
                st.toast("✅ 旅遊地點已儲存！")
                st.rerun()
    else:
        st.info(f"📍 {location}" if location else "尚未設定旅遊地點")

    st.divider()
    st.subheader("🔐 管理員")

    if st.session_state.admin_logged_in:
        st.success("🔓 管理員已登入")

        if st.button("👥 管理旅遊名單", type="primary", use_container_width=True):
            manage_members_dialog()

        if st.button("🔒 管理員登出", use_container_width=True):
            st.session_state.admin_logged_in = False
            st.session_state.confirm_reset = False
            st.rerun()

        st.divider()
        st.subheader("💾 資料備份")

        backup_data = export_travel_data()
        backup_json = json.dumps(
            backup_data, ensure_ascii=False, indent=2
        ).encode("utf-8")

        st.download_button(
            "📥 匯出旅遊資料",
            data=backup_json,
            file_name=f"office_travel_backup_{taiwan_now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            use_container_width=True,
        )

        uploaded_backup = st.file_uploader(
            "📤 匯入旅遊資料",
            type=["json"],
            key="travel_backup_upload",
            help="匯入後會以備份檔內容取代目前的名單、旅遊資料與旅遊地點。",
        )

        if uploaded_backup is not None:
            st.warning("⚠️ 匯入會取代目前的名單、旅遊資料與旅遊地點。請確認你上傳的是正確備份。")
            if st.button("✅ 確定匯入此備份", key="confirm_import_backup", use_container_width=True):
                original_data = None
                try:
                    imported = json.loads(uploaded_backup.getvalue().decode("utf-8"))
                    original_data = export_travel_data()

                    GITHUB_SYNC_SUPPRESSED = True
                    try:
                        import_travel_data(imported)
                    finally:
                        GITHUB_SYNC_SUPPRESSED = False

                    if not sync_github_backup(show_error=False):
                        raise RuntimeError("GitHub 備份同步失敗，匯入已取消。")

                    st.session_state.pop("travel_backup_upload", None)
                    st.toast("✅ 旅遊資料匯入成功！")
                    st.rerun()
                except Exception as e:
                    if original_data is not None:
                        try:
                            GITHUB_SYNC_SUPPRESSED = True
                            try:
                                import_travel_data(original_data)
                            finally:
                                GITHUB_SYNC_SUPPRESSED = False
                        except Exception:
                            pass
                    st.error(f"❌ 匯入未完成：{e}")

        st.divider()
        st.subheader("☁️ GitHub 永久資料")

        _sync_result = st.session_state.get("github_sync_result")
        if _sync_result:
            _kind, _message = _sync_result
            if _kind == "success":
                st.success(_message)
            else:
                st.error(_message)

        key_ok, key_message = test_github_encryption_key()
        if key_ok:
            st.caption("🔐 encryption_key：正常")
        else:
            st.error(f"🔐 encryption_key：{key_message}")

        if st.button("🔎 測試加密金鑰", key="test_github_encryption_key", use_container_width=True):
            if key_ok:
                st.success("✅ 加密金鑰正常，可以正常加密／解密。")
            else:
                st.error(f"❌ {key_message}")
        if github_is_configured():
            token, owner, repo, branch, path = get_github_settings()
            st.caption(f"儲存位置：{owner}/{repo}/{path}（{branch}）")
            if st.button("☁️ 立即同步目前資料", use_container_width=True):
                # 每一次按鈕都視為一次新的同步；完成後以「最後一次同步」
                # 的形式保留結果與時間，避免使用者誤認上一筆訊息。
                st.session_state["github_sync_result"] = None

                if sync_github_backup(show_error=False):
                    sync_time = taiwan_now().strftime("%Y-%m-%d %H:%M:%S")
                    member_count = int(
                        get_db("SELECT COUNT(*) AS n FROM travel_members").iloc[0]["n"]
                    )
                    record_count = int(
                        get_db("SELECT COUNT(*) AS n FROM travel_records").iloc[0]["n"]
                    )
                    st.session_state["github_sync_result"] = (
                        "success",
                        f"🟢 **最後一次同步成功**\n\n"
                        f"同步時間：{sync_time}（台灣時間）  \n"
                        f"名單：{member_count} 人｜旅遊資料：{record_count} 筆"
                    )
                else:
                    st.session_state["github_sync_result"] = (
                        "error",
                        "🔴 **最後一次同步失敗**\n\n"
                        "請檢查 GitHub 設定與錯誤資訊。"
                    )

                st.rerun()
        else:
            st.warning("⚠️ 尚未設定 GitHub 備份。請在 Streamlit Secrets 加入 [github] 設定。")

        st.divider()
        st.subheader("🗑️ 資料管理")

        with st.popover("🗑️ 清空全部旅遊資料", use_container_width=True):
            st.warning(
                "⚠️ 此操作會清除全部旅遊資料，但不會刪除名單與旅遊地點。"
            )
            st.caption(
                "清除後會同步更新 GitHub 永久備份，"
                "之後 Reboot 不會恢復已清除的旅遊資料。"
            )
            if st.button(
                "✅ 確定清除並同步 GitHub",
                key="reset_confirm",
                type="primary",
                use_container_width=True,
            ):
                original_records = get_db("SELECT * FROM travel_records")
                try:
                    execute_db("DELETE FROM travel_records")
                    if not sync_github_backup(show_error=False):
                        raise RuntimeError("GitHub 備份同步失敗，已取消本次清除。")
                except Exception as e:
                    execute_db("DELETE FROM travel_records")
                    for _, row in original_records.iterrows():
                        cols = list(original_records.columns)
                        vals = [row[c] for c in cols]
                        placeholders = ",".join(["?"] * len(cols))
                        execute_db(
                            f"INSERT INTO travel_records ({','.join(cols)}) VALUES ({placeholders})",
                            tuple(vals)
                        )
                    st.session_state.confirm_reset = False
                    st.error(f"❌ 清除未完成：{e}")
                else:
                    st.session_state.confirm_reset = False
                    sync_time = taiwan_now().strftime("%Y-%m-%d %H:%M:%S")
                    member_count = int(
                        get_db("SELECT COUNT(*) AS n FROM travel_members").iloc[0]["n"]
                    )
                    st.session_state["github_sync_result"] = (
                        "success",
                        f"🟢 **最後一次同步成功**\n\n"
                        f"同步時間：{sync_time}（台灣時間）  \n"
                        f"名單：{member_count} 人｜旅遊資料：0 筆"
                    )
                    st.toast("🗑️ 旅遊資料已清除，GitHub 備份也已更新。")
                st.rerun()

        with st.expander("🗄️ 資料庫資訊"):
            records_count = get_db("SELECT COUNT(*) AS n FROM travel_records")
            members_count = get_db("SELECT COUNT(*) AS n FROM travel_members")
            record_n = int(records_count.iloc[0]["n"]) if not records_count.empty else 0
            member_n = int(members_count.iloc[0]["n"]) if not members_count.empty else 0
            st.caption(f"名單：{member_n} 人　｜　旅遊資料：{record_n} 筆")
            st.caption(f"資料庫：{get_db_path()}")
            st.caption(f"檔案大小：{get_db_size():,} bytes")

            diag = get_db_diagnostics()
            st.markdown("**🔎 資料庫診斷**")
            st.caption(f"資料庫檔案存在：{'是' if diag['exists'] else '否'}")
            st.caption(f"travel_members：{diag['travel_members']} 筆")
            st.caption(f"travel_records：{diag['travel_records']} 筆")
            st.caption(f"travel_config：{diag['travel_config']} 筆")
            st.caption(f"Secrets 名單：{diag['secret_members']} 人")
            if diag.get("db_error"):
                st.error(f"資料庫診斷失敗：{diag['db_error']}")

    else:
        st.info("目前為一般使用者模式")
        admin_input = st.text_input(
            "管理員密碼",
            type="password",
            placeholder="請輸入管理員密碼"
        )
        if st.button("🔓 登入管理員", type="primary", use_container_width=True):
            if not admin_input:
                st.error("⚠️ 請輸入管理員密碼。")
            elif not get_admin_password():
                st.error("⚠️ 尚未設定 [admin] password。")
            elif admin_input == get_admin_password():
                st.session_state.admin_logged_in = True
                st.toast("✅ 管理員登入成功！")
                st.rerun()
            else:
                st.error("❌ 管理員密碼錯誤。")


@st.fragment(run_every="10s")
def render_stats():
    c1, c2 = st.columns([8, 1])
    with c1:
        location = get_location()
        text = f"📍 {html.escape(location)}　" if location else ""
        st.markdown(
            f'<div style="text-align:right;color:#838484;">'
            f'{text}更新於 {taiwan_now().strftime("%H:%M:%S")}</div>',
            unsafe_allow_html=True
        )
    with c2:
        if st.button("🔄", key="refresh_stats", use_container_width=True):
            st.rerun(scope="fragment")

    df = get_db("SELECT * FROM travel_records ORDER BY id")
    if df.empty:
        st.info("🚌 目前尚無旅遊人數資料，等待大家填寫……")
        return

    adults = int(df["adults"].sum())
    age_0_6_total = int(df["children_0_6"].sum())
    age_7_13_total = int(df["children_7_13"].sum())
    age_14_18_total = int(df["children_14_18"].sum())
    children = age_0_6_total + age_7_13_total + age_14_18_total
    total = adults + children
    not_participating = int(
        (df.get("participation_status", "participating") == "not_participating").sum()
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f'<div class="section-header header-adult"><div>👨 大人</div><div>{adults} 人</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="section-header header-child"><div>🧒 小孩</div><div>{children} 人</div></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="section-header header-total"><div>👥 總人數</div><div>{total} 人</div></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="section-header header-people"><div>🚫 不參加</div><div>{not_participating} 人</div></div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="section-header header-people">'
        '<div>🧒 小孩年齡分布</div>'
        f'<div>小孩合計 {children} 人</div></div>',
        unsafe_allow_html=True
    )

    a1, a2, a3, a4 = st.columns(4)
    a1.metric("0-6歲", age_0_6_total)
    a2.metric("7-13歲", age_7_13_total)
    a3.metric("14-18歲", age_14_18_total)
    a4.metric("小孩合計", children)

    st.markdown(
        f'<div class="section-header header-people"><div>📋 旅遊人數明細</div><div>{total} 人</div></div>',
        unsafe_allow_html=True
    )

    for _, row in df.iterrows():
        record_id = int(row["id"])
        name = html.escape(str(row["name"]))
        adult = int(row["adults"])
        child = int(row["children"])
        person_total = adult + child
        status = str(row.get("participation_status", "participating") or "participating")
        note = html.escape(str(row["note"] or "").strip())
        person_0_6 = int(row.get("children_0_6", 0))
        person_7_13 = int(row.get("children_7_13", 0))
        person_14_18 = int(row.get("children_14_18", 0))

        parts = []
        if adult:
            parts.append(f"大人 × {adult}")
        if child:
            parts.append(f"小孩 × {child}")

        if st.session_state.admin_logged_in:
            c_info, c_total, c_edit, c_delete = st.columns([5.2, 1.1, .7, .7])
        else:
            c_info, c_total = st.columns([6.2, 1.1])
            c_edit = c_delete = None

        with c_info:
            if status == "not_participating":
                st.markdown(
                    f'<div class="list-row"><div class="list-col-left">'
                    f'<div class="list-title-group">'
                    f'<span class="list-name">👤 {name}</span>'
                    f'<span class="list-qty">🚫 不參加</span>'
                    f'</div></div></div>',
                    unsafe_allow_html=True
                )
            age_parts = []
            if person_0_6:
                age_parts.append(f"0-6歲 × {person_0_6}")
            if person_7_13:
                age_parts.append(f"7-13歲 × {person_7_13}")
            if person_14_18:
                age_parts.append(f"14-18歲 × {person_14_18}")
            age_html = f'<div class="custom-text">🧒 {"　".join(age_parts)}</div>' if age_parts else ""
            note_html = f'<div class="custom-text">📝 {note}</div>' if note else ""
            if status == "participating":
                st.markdown(
                    f'<div class="list-row"><div class="list-col-left">'
                    f'<div class="list-title-group">'
                    f'<span class="list-name">👤 {name}</span>'
                    f'<span class="list-qty">{"　".join(parts)}</span>'
                    f'</div>{age_html}{note_html}</div></div>',
                    unsafe_allow_html=True
                )

        with c_total:
            st.markdown(
                f'<div style="text-align:right;font-size:1.15rem;font-weight:800;color:#7f8c8d;">'
                f'共 {person_total} 人</div>',
                unsafe_allow_html=True
            )

        if st.session_state.admin_logged_in:
            with c_edit:
                if st.button("✏️", key=f"record_edit_{record_id}", use_container_width=True):
                    edit_record_dialog(record_id)
            with c_delete:
                with st.popover("🗑️", key=f"record_delete_{record_id}"):
                    st.write(f"刪除 **{name}** 的旅遊資料？")
                    if st.button("⭕ 確認刪除", key=f"record_delete_confirm_{record_id}", type="primary", use_container_width=True):
                        execute_db("DELETE FROM travel_records WHERE id=?", (record_id,))
                        sync_github_backup(show_error=False)
                        st.toast(f"🗑️ 已刪除：{name}")
                        st.rerun(scope="fragment")

        st.markdown("<hr class='person-divider'>", unsafe_allow_html=True)


# 使用者切換時清除表單狀態，避免 A 使用者的 widget 值殘留到 B 使用者。
st.title("🚌 旅遊哦各位～")

tab1, tab2 = st.tabs(["📝 填寫人數", "📊 旅遊統計"])

with tab1:
    members = get_members()
    member_names = members["name"].tolist() if not members.empty else []

    if not member_names:
        st.warning("⚠️ 尚未建立旅遊名單，請管理員先新增人員。")
    else:
        c_user, c_btn = st.columns([3, 1.5])
        with c_user:
            if st.session_state.user_name:
                st.info(f"目前使用者：**{html.escape(st.session_state.user_name)}**")
            else:
                st.warning("⚠️ 尚未選擇姓名")
        with c_btn:
            if st.button("👤 選擇／切換使用者", type="primary", use_container_width=True):
                @st.dialog("👤 請選擇您的姓名")
                def choose_user():
                    selected = st.pills(
                        "姓名",
                        member_names,
                        selection_mode="single",
                        label_visibility="collapsed"
                    )
                    if selected:
                        # 使用者切換時，不能只清除 widget state。
                        # Streamlit 的 widget 若仍保留同一個 key，value= 不一定會覆蓋
                        # session_state，因此要直接把「新使用者自己的資料」寫入各 widget key。
                        selected_row = get_db(
                            """SELECT adults, children_0_6, children_7_13,
                                      children_14_18, note, participation_status
                               FROM travel_records
                               WHERE name=? LIMIT 1""",
                            (selected,)
                        )

                        if not selected_row.empty:
                            row = selected_row.iloc[0]
                            st.session_state["input_participation_status"] = (
                                "參加"
                                if str(row.get("participation_status", "participating") or "participating") == "participating"
                                else "不參加"
                            )
                            st.session_state["input_adults"] = int(row.get("adults", 0) or 0)
                            st.session_state["input_child_0_6"] = int(row.get("children_0_6", 0) or 0)
                            st.session_state["input_child_7_13"] = int(row.get("children_7_13", 0) or 0)
                            st.session_state["input_child_14_18"] = int(row.get("children_14_18", 0) or 0)
                            st.session_state["input_note"] = str(row.get("note", "") or "")
                        else:
                            # 尚未填寫過的使用者，載入乾淨的預設值。
                            st.session_state["input_participation_status"] = "參加"
                            st.session_state["input_adults"] = 1
                            st.session_state["input_child_0_6"] = 0
                            st.session_state["input_child_7_13"] = 0
                            st.session_state["input_child_14_18"] = 0
                            st.session_state["input_note"] = ""

                        st.session_state.user_name = selected
                        st.rerun()
                choose_user()

        if st.session_state.user_name not in member_names:
            st.info("👆 請先選擇姓名，再填寫同行人數。")
        else:
            user_name = st.session_state.user_name
            existing = get_db(
                "SELECT * FROM travel_records WHERE name=? LIMIT 1",
                (user_name,)
            )
            has_existing = not existing.empty

            if has_existing:
                row = existing.iloc[0]
                current_status = str(row.get("participation_status", "participating") or "participating")
                current_adults = int(row["adults"])
                current_0_6 = int(row.get("children_0_6", 0))
                current_7_13 = int(row.get("children_7_13", 0))
                current_14_18 = int(row.get("children_14_18", 0))
                current_note = str(row["note"] or "")
            else:
                current_status = "participating"
                current_adults = 1
                current_0_6 = 0
                current_7_13 = 0
                current_14_18 = 0
                current_note = ""

            location = get_location()
            title = html.escape(location) if location else "🚌 同行人數"
            st.markdown(
                f'<div class="section-header header-people">'
                f'<div>📍 {title}</div><div>同行人數</div></div>',
                unsafe_allow_html=True
            )

            participation = st.radio(
                "參加狀態",
                ["參加", "不參加"],
                index=0 if current_status == "participating" else 1,
                horizontal=True,
                key="input_participation_status"
            )

            st.markdown("### 👨 大人")
            adults = st.number_input(
                "大人",
                min_value=0,
                step=1,
                value=current_adults,
                format="%d",
                key="input_adults",
                disabled=(participation == "不參加")
            )

            st.markdown("### 🧒 小孩")
            c1, c2, c3 = st.columns(3)
            with c1:
                age_0_6 = st.number_input(
                    "0-6歲",
                    min_value=0,
                    step=1,
                    value=current_0_6,
                    format="%d",
                    key="input_child_0_6",
                    disabled=(participation == "不參加")
                )
            with c2:
                age_7_13 = st.number_input(
                    "7-13歲",
                    min_value=0,
                    step=1,
                    value=current_7_13,
                    format="%d",
                    key="input_child_7_13",
                    disabled=(participation == "不參加")
                )
            with c3:
                age_14_18 = st.number_input(
                    "14-18歲",
                    min_value=0,
                    step=1,
                    value=current_14_18,
                    format="%d",
                    key="input_child_14_18",
                    disabled=(participation == "不參加")
                )

            if participation == "不參加":
                adults = 0
                age_0_6 = 0
                age_7_13 = 0
                age_14_18 = 0

            children = int(age_0_6) + int(age_7_13) + int(age_14_18)
            st.caption(f"🧒 小孩合計：{children} 人")

            total = int(adults) + children
            st.markdown(
                f'<div style="text-align:center;padding:8px 0 14px;">'
                f'<span class="small-label">本次填寫</span><br>'
                f'<span class="big-number">👥 {total} 人</span></div>',
                unsafe_allow_html=True
            )

            note = st.text_area(
                "📝 備註",
                value=current_note,
                placeholder="例如：需要兒童座椅、飲食需求、同行關係……（可不填）",
                height=110,
                key="input_note"
            )

            if st.button("＋ 填寫我的旅遊資料", type="primary", use_container_width=True):
                if has_existing:
                    st.info("ℹ️ 你已經填寫過旅遊資料，請使用下方「✏️ 修改我的資料」。")
                elif total <= 0 and participation == "參加":
                    st.error("請至少填寫 1 位大人或小孩。")
                else:
                    execute_db(
                        """INSERT INTO travel_records
                           (name, adults, children, children_0_6, children_7_13,
                            children_14_18, note, record_time, participation_status)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            user_name,
                            0 if participation == "不參加" else int(adults),
                            0 if participation == "不參加" else children,
                            0 if participation == "不參加" else int(age_0_6),
                            0 if participation == "不參加" else int(age_7_13),
                            0 if participation == "不參加" else int(age_14_18),
                            note.strip(),
                            taiwan_now().strftime("%Y-%m-%d %H:%M"),
                            "participating" if participation == "參加" else "not_participating"
                        )
                    )
                    st.toast(f"✅ 已完成填寫：{user_name}")
                    st.rerun()

            if has_existing:
                row = get_db(
                    "SELECT * FROM travel_records WHERE name=? LIMIT 1",
                    (user_name,)
                ).iloc[0]
                my_total = int(row["adults"]) + int(row["children"])
                st.markdown(
                    f'<div class="section-header header-total">'
                    f'<div>📋 {html.escape(user_name)} 的目前資料</div>'
                    f'<div>共 {my_total} 人</div></div>',
                    unsafe_allow_html=True
                )

                summary = []
                if str(row.get("participation_status", "participating") or "participating") == "not_participating":
                    summary.append("🚫 不參加")
                if int(row["adults"]):
                    summary.append(f"👨 大人 × {int(row['adults'])}")
                if int(row["children"]):
                    summary.append(f"🧒 小孩 × {int(row['children'])}")
                st.markdown("　".join(summary))

                if str(row["note"] or "").strip():
                    st.caption(f"📝 {html.escape(str(row['note']))}")

                if st.button(
                    "✏️ 修改我的資料",
                    type="secondary",
                    use_container_width=True,
                    key="edit_my_record"
                ):
                    edit_my_record_dialog(user_name)

with tab2:
    render_stats()
