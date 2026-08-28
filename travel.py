import streamlit as st
import pandas as pd
import sqlite3
import time
import html
from datetime import datetime

# ==========================================
# 0. 系統設定區
# ==========================================
DB_FILE = "travel.db"

# 名單沿用原本「點餐哦各位～」的 Secrets 設定：
# [default_settings]
# colleagues = ["姓名A", "姓名B", ...]
# 同時相容舊版 [settings]。

# ==========================================
# 1. 頁面設定與 CSS
#    保留「點餐哦各位～ v3.5.2」的整體視覺風格
# ==========================================
st.set_page_config(
    page_title="旅遊哦各位～ v1.0",
    page_icon="🚌",
    layout="wide"
)

custom_css = """
<style>
    /* Windows 11 繁中環境：延續原版字體設定 */
    html, body, button, input, textarea, select,
    [data-baseweb], [class*="st-"]:not([data-testid="stIconMaterial"]) {
        font-family:
            "Microsoft JhengHei",
            "微軟正黑體",
            "Segoe UI Emoji",
            "Noto Color Emoji",
            "Apple Color Emoji",
            sans-serif !important;
    }

    /* 保留 Streamlit Material Symbols 原生字型 */
    [data-testid="stIconMaterial"],
    .material-symbols-rounded,
    .material-symbols-outlined {
        font-family: "Material Symbols Rounded" !important;
        font-weight: normal !important;
        font-style: normal !important;
        font-size: inherit;
        line-height: 1;
        letter-spacing: normal;
        text-transform: none;
        white-space: nowrap;
        word-wrap: normal;
        direction: ltr;
        -webkit-font-feature-settings: "liga";
        -webkit-font-smoothing: antialiased;
        font-feature-settings: "liga";
    }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* Tabs：延續原版 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 16px;
        border-bottom: 1px solid rgba(128,128,128,0.2);
        padding-bottom: 0px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 52px;
        border-radius: 8px 8px 0 0;
        background-color: transparent;
        padding: 10px 16px;
        font-weight: 600;
        color: #7f8c8d;
        font-size: 1.1rem;
        transition: all 0.2s ease;
        border: none;
    }
    .stTabs [data-baseweb="tab"]:hover {
        background-color: rgba(128,128,128,0.05);
        color: var(--text-color);
    }
    .stTabs [aria-selected="true"] {
        background-color: transparent !important;
        color: #4A90E2 !important;
        border-bottom: 3px solid #4A90E2 !important;
    }

    /* 區塊標頭：沿用原版卡片語言，但改成旅遊用途 */
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

    /* 清單排版：沿用 v3.5.2 */
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
    .list-price {
        font-size: 1.15rem;
        font-weight: 700;
        color: #7f8c8d;
        padding-top: 2px;
    }
    .custom-text {
        font-size: 1.0rem;
        color: #838484;
        margin-top: 2px;
        line-height: 1.4;
    }
    hr.soft-divider {
        border: 0;
        height: 1px;
        background: rgba(128,128,128,0.1);
        margin: 4px 0;
    }
    hr.person-divider {
        border: 0;
        height: 1px;
        background: rgba(128,128,128,0.3);
        margin: 16px 0;
    }

    .big-number {
        font-size: 2.0rem;
        font-weight: 800;
        line-height: 1.15;
    }
    .small-label {
        font-size: 0.95rem;
        color: #838484;
    }
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

# ==========================================
# 2. 設定 / 名單
# ==========================================
def get_colleagues_from_secrets():
    colleagues = []
    try:
        settings = st.secrets.get("default_settings", {})
        if not settings:
            settings = st.secrets.get("settings", {})
        colleagues = list(settings.get("colleagues", []))
    except Exception:
        pass
    return unique_clean_list(colleagues)


def unique_clean_list(values):
    result = []
    seen = set()
    for value in values:
        if value is None:
            continue
        value = str(value).strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


colleagues_list = get_colleagues_from_secrets()
if not colleagues_list:
    colleagues_list = ["請在 Streamlit Secrets 的 [default_settings] 設定人員"]

# ==========================================
# 3. 資料庫
# ==========================================
RECORD_COLUMNS = [
    "id", "name", "adults", "children", "note", "record_time"
]


def init_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS travel_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                adults INTEGER NOT NULL DEFAULT 0,
                children INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                record_time TEXT NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def execute_db(query, params=()):
    max_retries = 5
    for _ in range(max_retries):
        try:
            conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=10)
            c = conn.cursor()
            c.execute(query, params)
            affected_rows = c.rowcount
            conn.commit()
            conn.close()
            return affected_rows
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                time.sleep(0.1)
            else:
                raise
    st.error("⚠️ 系統忙碌（Database Locked），請稍後再試。")
    return False


def get_db(query, params=()):
    max_retries = 3
    last_error = None
    for _ in range(max_retries):
        conn = None
        try:
            conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=10)
            df = pd.read_sql_query(query, conn, params=params)
            df.attrs["db_error"] = False
            return df
        except sqlite3.OperationalError as e:
            last_error = e
            if "locked" in str(e).lower():
                time.sleep(0.2)
            else:
                break
        except Exception as e:
            last_error = e
            break
        finally:
            if conn is not None:
                conn.close()

    failed_df = pd.DataFrame(columns=RECORD_COLUMNS)
    failed_df.attrs["db_error"] = True
    failed_df.attrs["db_error_message"] = str(last_error) if last_error else "Unknown database read error"
    return failed_df


def get_records_df():
    df = get_db("SELECT * FROM travel_records ORDER BY id")
    if df.attrs.get("db_error", False):
        return df
    if df.empty:
        return pd.DataFrame(columns=RECORD_COLUMNS)
    for column in RECORD_COLUMNS:
        if column not in df.columns:
            df[column] = 0 if column in ("adults", "children") else ""
    df["adults"] = pd.to_numeric(df["adults"], errors="coerce").fillna(0).astype(int)
    df["children"] = pd.to_numeric(df["children"], errors="coerce").fillna(0).astype(int)
    return df[RECORD_COLUMNS].copy()


init_db()

# ==========================================
# 4. Sidebar：管理本次旅遊資料
# ==========================================
with st.sidebar:
    st.header("⚙️ 旅遊管理")
    st.caption("名單沿用原本的 Streamlit Secrets 設定。")

    st.divider()
    st.subheader("清空本次旅遊資料")

    if "confirm_reset" not in st.session_state:
        st.session_state.confirm_reset = False

    if st.button("🗑️ 清空本次資料", type="secondary", use_container_width=True):
        st.session_state.confirm_reset = True

    if st.session_state.confirm_reset:
        st.warning("⚠️ 確定清空全部旅遊人數資料？此動作無法復原。")
        c1, c2 = st.columns(2)
        if c1.button("✅ 確定", key="confirm_reset_travel", use_container_width=True):
            execute_db("DELETE FROM travel_records")
            st.session_state.confirm_reset = False
            st.toast("🗑️ 本次旅遊資料已清空！")
            st.rerun()
        if c2.button("❌ 取消", key="cancel_reset_travel", use_container_width=True):
            st.session_state.confirm_reset = False
            st.rerun()

# ==========================================
# 5. Dialog：選擇姓名 / 編輯紀錄
# ==========================================
@st.dialog("👤 請選擇您的姓名")
def login_dialog():
    st.caption("請選擇您的姓名以開始填寫旅遊人數")
    selected = st.pills(
        "姓名",
        colleagues_list,
        selection_mode="single",
        label_visibility="collapsed"
    )
    if selected:
        st.session_state["user_name"] = selected
        st.rerun()


@st.dialog("✏️ 編輯旅遊人數")
def edit_record_dialog(record_id, cur_name, cur_adults, cur_children, cur_note):
    current = get_db(
        "SELECT * FROM travel_records WHERE id = ?",
        (record_id,)
    )
    if current.empty:
        st.error("⚠️ 找不到這筆資料，可能已被刪除。")
        return

    new_name = st.text_input("姓名", value=str(cur_name)).strip()
    c1, c2 = st.columns(2)
    new_adults = c1.number_input(
        "大人",
        min_value=0,
        step=1,
        value=max(0, int(cur_adults)),
        format="%d"
    )
    new_children = c2.number_input(
        "小孩",
        min_value=0,
        step=1,
        value=max(0, int(cur_children)),
        format="%d"
    )
    new_note = st.text_area(
        "備註",
        value=str(cur_note or ""),
        placeholder="例如：需要兒童座椅、飲食需求、同行關係……",
        height=100
    ).strip()

    total = int(new_adults) + int(new_children)
    st.caption(f"👥 總人數：{total} 人")

    if st.button("💾 儲存修改", type="primary", use_container_width=True):
        if not new_name:
            st.error("姓名不能為空。")
        elif total <= 0:
            st.error("請至少填寫 1 位大人或小孩。")
        else:
            affected = execute_db(
                "UPDATE travel_records SET name=?, adults=?, children=?, note=? WHERE id=?",
                (new_name, int(new_adults), int(new_children), new_note, record_id)
            )
            if affected == 1:
                st.toast("✅ 旅遊資料已更新！")
                st.rerun()

# ==========================================
# 6. 統計看板
# ==========================================
@st.fragment(run_every="10s")
def render_stats_section():
    c_ref_text, c_ref_btn = st.columns([8, 1], vertical_alignment="center")
    with c_ref_text:
        st.markdown(
            f'<div style="text-align:right; color:color-mix(in srgb, var(--text-color) 58%, transparent); '
            f'font-size:0.9rem; margin:0; padding:0;">更新於 {datetime.now().strftime("%H:%M:%S")}</div>',
            unsafe_allow_html=True
        )
    with c_ref_btn:
        if st.button("🔄", help="立即重新整理統計資料", use_container_width=True, key="btn_refresh_stats"):
            st.rerun(scope="fragment")

    df = get_records_df()
    if df.attrs.get("db_error", False):
        st.error("⚠️ 暫時無法讀取旅遊資料，請稍後重新整理。")
        return

    if df.empty:
        st.info("🚌 目前尚無旅遊人數資料，等待大家填寫……")
        return

    total_adults = int(df["adults"].sum())
    total_children = int(df["children"].sum())
    total_people = total_adults + total_children
    total_people_with_record = len(df)

    # 頂部總覽：簡潔、直接看懂
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            f'<div class="section-header header-adult"><div>👨 大人</div><div>{total_adults} 人</div></div>',
            unsafe_allow_html=True
        )
    with c2:
        st.markdown(
            f'<div class="section-header header-child"><div>🧒 小孩</div><div>{total_children} 人</div></div>',
            unsafe_allow_html=True
        )
    with c3:
        st.markdown(
            f'<div class="section-header header-total"><div>👥 總人數</div><div>{total_people} 人</div></div>',
            unsafe_allow_html=True
        )

    st.markdown(
        f'<div style="text-align:right; color:color-mix(in srgb, var(--text-color) 58%, transparent); '
        f'font-size:0.95rem; margin:-4px 0 12px 0;">已填寫 {total_people_with_record} 人</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="section-header header-people">'
        '<div>📋 旅遊人數明細</div>'
        f'<div>{total_people} 人</div>'
        '</div>',
        unsafe_allow_html=True
    )

    # 每位填寫者一列；姓名、總人數、大人/小孩、備註一眼看完
    for _, row in df.iterrows():
        name = html.escape(str(row["name"]))
        adults = int(row["adults"])
        children = int(row["children"])
        total = adults + children
        note = str(row["note"] or "").strip()
        safe_note = html.escape(note)

        people_text = f"大人 × {adults}　小孩 × {children}"
        if adults == 0:
            people_text = f"小孩 × {children}"
        elif children == 0:
            people_text = f"大人 × {adults}"

        c_info, c_total, c_edit, c_delete = st.columns([5.2, 1.1, 0.7, 0.7], vertical_alignment="center")
        with c_info:
            note_html = f'<div class="custom-text">📝 {safe_note}</div>' if note else ""
            st.markdown(
                f'<div class="list-row">'
                f'  <div class="list-col-left">'
                f'    <div class="list-title-group">'
                f'      <span class="list-name">👤 {name}</span>'
                f'      <span class="list-qty">{people_text}</span>'
                f'    </div>'
                f'    {note_html}'
                f'  </div>'
                f'</div>',
                unsafe_allow_html=True
            )
        with c_total:
            st.markdown(
                f'<div style="text-align:right; font-size:1.15rem; font-weight:800; color:#7f8c8d;">'
                f'共 {total} 人</div>',
                unsafe_allow_html=True
            )
        with c_edit:
            if st.button("✏️", key=f"edit_{int(row['id'])}", help="修改", use_container_width=True):
                st.session_state["_edit_record_request"] = {
                    "id": int(row["id"]),
                    "name": row["name"],
                    "adults": adults,
                    "children": children,
                    "note": row["note"],
                }
                st.rerun()
        with c_delete:
            with st.popover("🗑️", help="刪除", use_container_width=True):
                st.write(f"刪除 **{name}** 的資料？")
                if st.button("⭕ 確認", key=f"delete_confirm_{int(row['id'])}", type="primary", use_container_width=True):
                    affected = execute_db("DELETE FROM travel_records WHERE id = ?", (int(row["id"]),))
                    if affected == 1:
                        st.toast(f"✅ 已刪除：{row['name']}")
                        st.rerun(scope="fragment")

        st.markdown("<hr class='person-divider'>", unsafe_allow_html=True)

# ==========================================
# 7. 主畫面
# ==========================================
if "user_name" not in st.session_state:
    st.session_state["user_name"] = None

st.title("🚌 旅遊哦各位～")
tab1, tab2 = st.tabs(["📝 填寫人數", "📊 旅遊統計"])

with tab1:
    if st.button("🔄 重新整理資料", type="secondary", use_container_width=True):
        st.rerun()

    with st.container():
        st.markdown('<h5>👤 請選擇您的姓名</h5>', unsafe_allow_html=True)
        c_user, c_btn = st.columns([3, 1.5], vertical_alignment="center")
        with c_user:
            if st.session_state["user_name"]:
                st.info(f"目前使用者：**{html.escape(str(st.session_state['user_name']))}**")
            else:
                st.warning("⚠️ 尚未選擇姓名")
        with c_btn:
            if st.button(
                "👤 選擇／切換使用者",
                use_container_width=True,
                type="primary" if not st.session_state["user_name"] else "secondary"
            ):
                login_dialog()

    if not st.session_state["user_name"]:
        st.info("👆 請先選擇姓名，再填寫同行人數。")
    else:
        user_name = st.session_state["user_name"]

        existing = get_db(
            "SELECT * FROM travel_records WHERE name = ? ORDER BY id DESC LIMIT 1",
            (user_name,)
        )
        has_existing = not existing.empty

        if has_existing:
            current = existing.iloc[0]
            current_adults = int(current["adults"])
            current_children = int(current["children"])
            current_note = str(current["note"] or "")
            st.caption("已有資料會預填在下方，重新送出會更新你的資料。")
        else:
            current_adults = 1
            current_children = 0
            current_note = ""

        st.markdown(
            '<div class="section-header header-people">'
            '<div>🚌 同行人數</div>'
            '<div>請填寫大人／小孩</div>'
            '</div>',
            unsafe_allow_html=True
        )

        c_adult, c_child = st.columns(2)
        with c_adult:
            adults = st.number_input(
                "👨 大人",
                min_value=0,
                step=1,
                value=current_adults,
                format="%d",
                key="travel_adults"
            )
        with c_child:
            children = st.number_input(
                "🧒 小孩",
                min_value=0,
                step=1,
                value=current_children,
                format="%d",
                key="travel_children"
            )

        total = int(adults) + int(children)
        st.markdown(
            f'<div style="text-align:center; padding:8px 0 14px 0;">'
            f'<span class="small-label">本次填寫</span><br>'
            f'<span class="big-number">👥 {total} 人</span>'
            f'</div>',
            unsafe_allow_html=True
        )

        note = st.text_area(
            "📝 備註",
            value=current_note,
            placeholder="例如：需要兒童座椅、飲食需求、同行關係……（可不填）",
            height=110,
            key="travel_note"
        ).strip()

        button_label = "💾 更新我的旅遊資料" if has_existing else "＋ 填寫我的旅遊資料"
        if st.button(button_label, type="primary", use_container_width=True):
            if total <= 0:
                st.toast("🚫 請至少填寫 1 位大人或小孩！", icon="⚠️")
            elif has_existing:
                record_id = int(existing.iloc[0]["id"])
                affected = execute_db(
                    "UPDATE travel_records SET adults=?, children=?, note=?, record_time=? WHERE id=?",
                    (
                        int(adults), int(children), note,
                        datetime.now().strftime("%Y-%m-%d %H:%M"),
                        record_id
                    )
                )
                if affected == 1:
                    st.toast(f"✅ 已更新：{user_name}，共 {total} 人")
                    st.rerun()
            else:
                affected = execute_db(
                    "INSERT INTO travel_records (name, adults, children, note, record_time) VALUES (?, ?, ?, ?, ?)",
                    (
                        user_name, int(adults), int(children), note,
                        datetime.now().strftime("%Y-%m-%d %H:%M")
                    )
                )
                if affected == 1:
                    st.toast(f"✅ 已完成填寫：{user_name}，共 {total} 人")
                    st.rerun()

        # 只顯示自己的資料，讓主頁維持單純
        st.write("")
        my_data = get_db(
            "SELECT * FROM travel_records WHERE name = ? ORDER BY id DESC LIMIT 1",
            (user_name,)
        )
        if not my_data.empty:
            row = my_data.iloc[0]
            my_total = int(row["adults"]) + int(row["children"])
            st.markdown(
                '<div class="section-header header-total">'
                f'<div>📋 {html.escape(str(user_name))} 的目前資料</div>'
                f'<div>共 {my_total} 人</div>'
                '</div>',
                unsafe_allow_html=True
            )
            summary_text = f"大人 × {int(row['adults'])}　小孩 × {int(row['children'])}"
            st.markdown(f"**{summary_text}**")
            if str(row["note"] or "").strip():
                st.caption(f"📝 {html.escape(str(row['note']))}")

with tab2:
    render_stats_section()

# ==========================================
# 8. 編輯 Dialog 請求處理
# ==========================================
edit_request = st.session_state.get("_edit_record_request")
if edit_request:
    st.session_state.pop("_edit_record_request", None)
    edit_record_dialog(
        edit_request["id"],
        edit_request["name"],
        edit_request["adults"],
        edit_request["children"],
        edit_request["note"]
    )
