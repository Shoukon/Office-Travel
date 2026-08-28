import streamlit as st
import pandas as pd
import sqlite3
import time
import html
from datetime import datetime

DB_FILE = "travel.db"

st.set_page_config(
    page_title="旅遊哦各位～ v1.0.5",
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
    for _ in range(5):
        try:
            conn = db_connect()
            cur = conn.cursor()
            cur.execute(query, params)
            affected = cur.rowcount
            conn.commit()
            conn.close()
            return affected
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                time.sleep(0.1)
            else:
                raise
    st.error("⚠️ 系統忙碌，請稍後再試。")
    return 0


def get_db(query, params=()):
    try:
        with db_connect() as conn:
            return pd.read_sql_query(query, conn, params=params)
    except Exception:
        return pd.DataFrame()


def init_db():
    conn = db_connect()
    cur = conn.cursor()

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


@st.cache_data(ttl=300, show_spinner=False)
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


init_db()
seed_members_from_secrets_once()

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

    adults = st.number_input(
        "👨 大人",
        min_value=0,
        step=1,
        value=int(row["adults"]),
        format="%d",
        key="my_edit_adults"
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
            key="my_edit_0_6"
        )
    with c2:
        age_7_13 = st.number_input(
            "7-13歲",
            min_value=0,
            step=1,
            value=int(row.get("children_7_13", 0)),
            format="%d",
            key="my_edit_7_13"
        )
    with c3:
        age_14_18 = st.number_input(
            "14-18歲",
            min_value=0,
            step=1,
            value=int(row.get("children_14_18", 0)),
            format="%d",
            key="my_edit_14_18"
        )

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
        if total <= 0:
            st.error("請至少填寫 1 位大人或小孩。")
            return

        affected = execute_db(
            """UPDATE travel_records
               SET adults=?, children=?, children_0_6=?, children_7_13=?,
                   children_14_18=?, note=?, record_time=?
               WHERE name=?""",
            (
                int(adults),
                children,
                int(age_0_6),
                int(age_7_13),
                int(age_14_18),
                note.strip(),
                datetime.now().strftime("%Y-%m-%d %H:%M"),
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

    adults = st.number_input(
        "👨 大人",
        min_value=0,
        step=1,
        value=int(row["adults"]),
        format="%d",
        key=f"admin_edit_adults_{record_id}"
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
            key=f"admin_edit_0_6_{record_id}"
        )
    with c2:
        age_7_13 = st.number_input(
            "7-13歲",
            min_value=0,
            step=1,
            value=int(row.get("children_7_13", 0)),
            format="%d",
            key=f"admin_edit_7_13_{record_id}"
        )
    with c3:
        age_14_18 = st.number_input(
            "14-18歲",
            min_value=0,
            step=1,
            value=int(row.get("children_14_18", 0)),
            format="%d",
            key=f"admin_edit_14_18_{record_id}"
        )

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
        if total <= 0:
            st.error("請至少填寫 1 位大人或小孩。")
        else:
            execute_db(
                """UPDATE travel_records
                   SET adults=?, children=?, children_0_6=?, children_7_13=?,
                       children_14_18=?, note=?, record_time=?
                   WHERE id=?""",
                (
                    int(adults),
                    children,
                    int(age_0_6),
                    int(age_7_13),
                    int(age_14_18),
                    note.strip(),
                    datetime.now().strftime("%Y-%m-%d %H:%M"),
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
        st.subheader("🗑️ 資料管理")

        if st.button("🗑️ 清空全部旅遊資料", use_container_width=True):
            st.session_state.confirm_reset = True

        with st.expander("🗄️ 資料庫資訊"):
            records_count = get_db("SELECT COUNT(*) AS n FROM travel_records")
            members_count = get_db("SELECT COUNT(*) AS n FROM travel_members")
            record_n = int(records_count.iloc[0]["n"]) if not records_count.empty else 0
            member_n = int(members_count.iloc[0]["n"]) if not members_count.empty else 0
            st.caption(f"名單：{member_n} 人　｜　旅遊資料：{record_n} 筆")
            st.caption(f"資料庫：{get_db_path()}")
            st.caption(f"檔案大小：{get_db_size():,} bytes")

        if st.session_state.confirm_reset:
            st.warning("⚠️ 確定清空全部旅遊人數資料？此動作無法復原。")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ 確定清除", key="reset_confirm", use_container_width=True):
                    execute_db("DELETE FROM travel_records")
                    st.session_state.confirm_reset = False
                    st.toast("🗑️ 全部旅遊資料已清除！")
                    st.rerun()
            with c2:
                if st.button("❌ 取消", key="reset_cancel", use_container_width=True):
                    st.session_state.confirm_reset = False
                    st.rerun()
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
            f'{text}更新於 {datetime.now().strftime("%H:%M:%S")}</div>',
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

    c1, c2, c3 = st.columns(3)
    c1.markdown(f'<div class="section-header header-adult"><div>👨 大人</div><div>{adults} 人</div></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="section-header header-child"><div>🧒 小孩</div><div>{children} 人</div></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="section-header header-total"><div>👥 總人數</div><div>{total} 人</div></div>', unsafe_allow_html=True)

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
            age_parts = []
            if person_0_6:
                age_parts.append(f"0-6歲 × {person_0_6}")
            if person_7_13:
                age_parts.append(f"7-13歲 × {person_7_13}")
            if person_14_18:
                age_parts.append(f"14-18歲 × {person_14_18}")
            age_html = f'<div class="custom-text">🧒 {"　".join(age_parts)}</div>' if age_parts else ""
            note_html = f'<div class="custom-text">📝 {note}</div>' if note else ""
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
                        st.toast(f"🗑️ 已刪除：{name}")
                        st.rerun(scope="fragment")

        st.markdown("<hr class='person-divider'>", unsafe_allow_html=True)


st.title("🚌 旅遊哦各位～ v1.0.4")

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
                current_adults = int(row["adults"])
                current_0_6 = int(row.get("children_0_6", 0))
                current_7_13 = int(row.get("children_7_13", 0))
                current_14_18 = int(row.get("children_14_18", 0))
                current_note = str(row["note"] or "")
            else:
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

            st.markdown("### 👨 大人")
            adults = st.number_input(
                "大人",
                min_value=0,
                step=1,
                value=current_adults,
                format="%d",
                key="input_adults"
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
                    key="input_child_0_6"
                )
            with c2:
                age_7_13 = st.number_input(
                    "7-13歲",
                    min_value=0,
                    step=1,
                    value=current_7_13,
                    format="%d",
                    key="input_child_7_13"
                )
            with c3:
                age_14_18 = st.number_input(
                    "14-18歲",
                    min_value=0,
                    step=1,
                    value=current_14_18,
                    format="%d",
                    key="input_child_14_18"
                )

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

            label = "💾 更新我的旅遊資料" if has_existing else "＋ 填寫我的旅遊資料"
            if st.button(label, type="primary", use_container_width=True):
                if total <= 0:
                    st.error("請至少填寫 1 位大人或小孩。")
                elif has_existing:
                    execute_db(
                        """UPDATE travel_records
                           SET adults=?, children=?, note=?, record_time=?
                           WHERE name=?""",
                        (
                            int(adults), children, int(age_0_6), int(age_7_13),
                            int(age_14_18), note.strip(),
                            datetime.now().strftime("%Y-%m-%d %H:%M"),
                            user_name
                        )
                    )
                    st.toast(f"✅ 已更新：{user_name}")
                    st.rerun()
                else:
                    execute_db(
                        """INSERT INTO travel_records
                           (name, adults, children, children_0_6, children_7_13,
                            children_14_18, note, record_time)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            user_name, int(adults), children, int(age_0_6),
                            int(age_7_13), int(age_14_18), note.strip(),
                            datetime.now().strftime("%Y-%m-%d %H:%M")
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
