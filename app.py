# -*- coding: utf-8 -*-
"""
app.py
======
تطبيق Streamlit الرئيسي لمنصة إدخال القوانين المفقودة. صفحة واحدة بتوجيه
حسب الدور (قانوني/ة أو أدمن) عبر st.session_state - مو تطبيق متعدد
الصفحات منفصل.

التدفق:
    تسجيل دخول -> (ترحيب لمرة وحدة لو حساب جديد) -> واجهة القانوني/ة
                                                   -> لوحة الأدمن (لو admin)

النسخة: 1.0.0 - 2026-09-03
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import auth
import data_access as da
import sheets_client as sc

st.set_page_config(page_title="منصة استكمال القوانين", page_icon="⚖", layout="wide")

# ---------------------------------------------------------------------------
# RTL - Streamlit افتراضياً LTR، لازم نفرض الاتجاه بـCSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
:root {
    --sky-50: #F0F9FF; --sky-100: #E0F2FE; --sky-200: #BAE6FD;
    --sky-600: #0284C7; --sky-700: #0369A1; --navy: #0C4A6E;
    --ink: #0F172A; --muted: #64748B;
}
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
    direction: rtl !important; font-size: 17px !important;
    background-color: #FFFFFF !important;
}
.stApp, .stApp p, .stApp span, .stApp label, .stApp div { text-align: right !important; }
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] span,
[data-testid="stWidgetLabel"] p, [data-testid="stWidgetLabel"] label {
    color: var(--ink) !important;
}

/* حقول الإدخال */
.stTextInput input, .stTextArea textarea, .stNumberInput input {
    text-align: right !important; font-size: 16px !important;
    background-color: #FFFFFF !important; color: var(--ink) !important;
    border: 1px solid var(--sky-200) !important; border-radius: 8px !important;
}
.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: var(--sky-600) !important; box-shadow: 0 0 0 1px var(--sky-600) !important;
}

/* الأزرار */
.stButton button, [data-testid="stFormSubmitButton"] button {
    width: 100%; font-size: 16px !important; border-radius: 8px !important;
    background-color: var(--sky-600) !important; color: #FFFFFF !important; border: none !important;
}
.stButton button:hover, [data-testid="stFormSubmitButton"] button:hover {
    background-color: var(--sky-700) !important;
}
button[kind="secondary"] {
    background-color: #FFFFFF !important; color: var(--sky-700) !important;
    border: 1px solid var(--sky-200) !important;
}

/* النماذج والبطاقات */
div[data-testid="stForm"] {
    border: 1px solid var(--sky-200) !important; border-radius: 14px !important;
    padding: 1.5rem !important; background: var(--sky-50) !important;
}
[data-testid="stMetric"] {
    background: var(--sky-50) !important; border: 1px solid var(--sky-200) !important;
    border-radius: 12px !important; padding: 0.8rem !important;
}
[data-testid="stMetricValue"], [data-testid="stMetricLabel"] { color: var(--ink) !important; }
.stProgress > div > div > div { background-color: var(--sky-600) !important; }
[data-testid="stRadio"] label, [data-testid="stCheckbox"] label { color: var(--ink) !important; }

/* عناوين مخصّصة */
.app-h1 { font-size: 30px; font-weight: 700; color: var(--navy); margin-bottom: 4px; }
.app-h2 { font-size: 22px; font-weight: 600; color: var(--navy); margin: 1.2rem 0 0.8rem; }
.app-caption { font-size: 15px; color: var(--muted); margin-bottom: 1.2rem; }
.app-card {
    background: var(--sky-50); border: 1px solid var(--sky-200); border-radius: 14px;
    padding: 1.1rem 1.35rem; margin-bottom: 1rem;
}
.app-card .badge {
    display: inline-block; background: var(--sky-600); color: #FFFFFF !important;
    font-size: 13px; padding: 3px 12px; border-radius: 20px; margin-bottom: 8px;
}
.app-card .title { font-size: 18px; font-weight: 700; color: var(--navy); margin: 6px 0 10px; line-height: 1.5; }
.app-card .meta { font-size: 14px; color: #334155; margin-bottom: 3px; }
</style>
""", unsafe_allow_html=True)


def h1(text: str):
    st.markdown(f'<div class="app-h1">{text}</div>', unsafe_allow_html=True)


def h2(text: str):
    st.markdown(f'<div class="app-h2">{text}</div>', unsafe_allow_html=True)


def caption(text: str):
    st.markdown(f'<div class="app-caption">{text}</div>', unsafe_allow_html=True)


def logout_button():
    if st.button("تسجيل الخروج", key="logout_btn"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()


def _handle_stale_item_error():
    """يُستدعى لما عملية كتابة تفشل لأن العنصر ما عاد موجود بشيت التكليفات
    (مثلاً أعيد توزيعه، أو الصفحة كانت مفتوحة بنسخة قديمة مخزَّنة). نحدّث
    الكاش ونرجّع القانوني/ة للقائمة المحدَّثة بدل ما نطيح التطبيق.
    الرسالة تُخزَّن بالجلسة وتُعرض بعد الـrerun (st.warning قبل st.rerun
    مباشرة ما بتوصل للمستخدم أبداً - الـrerun بيلغيها قبل ما تترسم)."""
    da.get_assignments_df.clear()
    da.get_articles_df.clear()
    st.session_state.pop("selected_pmk", None)
    st.session_state["pending_notice"] = "هذا العنصر تغيّر أو ما عاد متوفر بنفس الحالة - رجّعناك للقائمة المحدَّثة."
    st.rerun()


# ---------------------------------------------------------------------------
# تسجيل الدخول
# ---------------------------------------------------------------------------

def render_login():
    h1("منصة استكمال القوانين المفقودة")
    caption("سجّل دخولك للمتابعة")
    with st.form("login_form"):
        username = st.text_input("اسم المستخدم")
        password = st.text_input("كلمة السر", type="password")
        submitted = st.form_submit_button("دخول", width='stretch')
        if submitted:
            role = auth.check_login(username, password)
            if role is None:
                st.error("اسم المستخدم أو كلمة السر غير صحيحة.")
            else:
                st.session_state.username = username.strip()
                st.session_state.role = role
                st.rerun()


# ---------------------------------------------------------------------------
# الترحيب لمرة وحدة (قانوني/ة جديد)
# ---------------------------------------------------------------------------

def render_onboarding():
    st.markdown(
        "<div style='display:flex; justify-content:center; margin-top:2rem;'>",
        unsafe_allow_html=True,
    )
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        h2("أهلاً فيك")
        caption("قبل ما نبلش، بدنا نتعرف عليك بسرعة")
        with st.form("onboarding_form"):
            display_name = st.text_input("شو بتحب ننادينك؟", placeholder="مثلاً: سارة")
            gender = st.radio("الجنس", ["أنثى", "ذكر"], horizontal=True)
            submitted = st.form_submit_button("متابعة", width='stretch')
            if submitted:
                if not display_name.strip():
                    st.error("اكتب اسم قبل ما تكمل.")
                else:
                    da.save_profile(st.session_state.username, display_name.strip(), gender)
                    st.session_state.display_name = display_name.strip()
                    st.session_state.gender = gender
                    st.rerun()
        st.caption("رح نستخدم هالمعلومة بس لمخاطبتك بشكل صحيح داخل المنصة")
    st.markdown("</div>", unsafe_allow_html=True)


def legal_title(gender: str) -> str:
    return "القانونية" if gender == "أنثى" else "القانوني"


# ---------------------------------------------------------------------------
# واجهة القانوني/ة
# ---------------------------------------------------------------------------

def render_item_card(item: pd.Series):
    st.markdown(f"""
    <div class="app-card">
        <span class="badge">{item['النوع']}</span>
        <span style="font-size:13px; color:#64748B; margin-right:8px;">pmk_ID: {item['pmk_ID']}</span>
        <div class="title">{item['اسم_التشريع']}</div>
        <div class="meta">الرقم والسنة: {item['الرقم']} لسنة {item['السنة']}</div>
        <div class="meta">الجريدة الرسمية: عدد {item['رقم_الجريدة_الرسمية']} - صفحة {item['رقم_الصفحة']} - {item['تاريخ_الجريدة']}</div>
    </div>
    """, unsafe_allow_html=True)


def render_item_detail(username: str, item: pd.Series):
    pmk_id = str(item["pmk_ID"])
    render_item_card(item)

    started_key = f"marked_started_{pmk_id}"
    if item["الحالة"] == sc.STATUS_NOT_STARTED and not st.session_state.get(started_key):
        try:
            da.update_assignment(pmk_id, status=sc.STATUS_IN_PROGRESS)
            st.session_state[started_key] = True
            st.rerun()
        except ValueError:
            _handle_stale_item_error()
            return

    articles_df = da.get_item_articles(pmk_id)
    h2("مواد القانون")

    for _, row in articles_df.iterrows():
        art_num = str(row["رقم_المادة"])
        col1, col2, col3 = st.columns([5, 1, 1])
        with col1:
            new_text = st.text_area(
                f"المادة {art_num}", value=row["نص_المادة"],
                key=f"text_{pmk_id}_{art_num}", height=100, label_visibility="visible",
            )
        with col2:
            st.write("")
            if st.button("حفظ", key=f"save_{pmk_id}_{art_num}", width='stretch'):
                try:
                    da.save_article(pmk_id, art_num, new_text, username)
                    st.toast("تم حفظ المادة")
                    st.rerun()
                except ValueError:
                    _handle_stale_item_error()
        with col3:
            st.write("")
            if st.button("حذف", key=f"del_{pmk_id}_{art_num}", width='stretch'):
                try:
                    da.delete_article(pmk_id, art_num)
                    st.rerun()
                except ValueError:
                    _handle_stale_item_error()

    slots_key = f"new_slots_{pmk_id}"
    if slots_key not in st.session_state:
        st.session_state[slots_key] = []

    for slot_id in list(st.session_state[slots_key]):
        col1, col2, col3 = st.columns([1, 4, 1])
        with col1:
            num_val = st.text_input("رقم المادة", key=f"newnum_{pmk_id}_{slot_id}")
        with col2:
            text_val = st.text_area("نص المادة", key=f"newtext_{pmk_id}_{slot_id}", height=100)
        with col3:
            st.write("")
            if st.button("حفظ", key=f"savenew_{pmk_id}_{slot_id}", width='stretch'):
                if not num_val.strip() or not text_val.strip():
                    st.error("لازم رقم ونص المادة قبل الحفظ.")
                else:
                    try:
                        da.save_article(pmk_id, num_val.strip(), text_val, username)
                        st.session_state[slots_key].remove(slot_id)
                        st.toast("تم حفظ المادة")
                        st.rerun()
                    except ValueError:
                        _handle_stale_item_error()

    if st.button("+ إضافة مادة", key=f"add_{pmk_id}"):
        next_slot = (max(st.session_state[slots_key]) + 1) if st.session_state[slots_key] else 1
        st.session_state[slots_key].append(next_slot)
        st.rerun()

    st.markdown("---")
    notes = st.text_area("ملاحظات (اختياري)", value=item.get("ملاحظات", ""), key=f"notes_{pmk_id}")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("حفظ الملاحظات ومتابعة لاحقاً", key=f"savelater_{pmk_id}", width='stretch'):
            try:
                da.update_assignment(pmk_id, notes=notes)
                st.toast("تم الحفظ")
                st.rerun()
            except ValueError:
                _handle_stale_item_error()
    with col2:
        if st.button("إنهاء هذا العنصر", key=f"finish_{pmk_id}", width='stretch', type="primary"):
            try:
                da.update_assignment(pmk_id, status=sc.STATUS_DONE, notes=notes)
                st.session_state.pop("selected_pmk", None)
                st.toast("تم إنهاء العنصر")
                st.rerun()
            except ValueError:
                _handle_stale_item_error()

    if st.button("رجوع للقائمة", key=f"back_{pmk_id}"):
        st.session_state.pop("selected_pmk", None)
        st.rerun()


def render_volunteer_view(username: str, display_name: str, gender: str):
    title = legal_title(gender)
    items = da.get_user_items(username)

    if "pending_notice" in st.session_state:
        st.warning(st.session_state.pop("pending_notice"))

    if "selected_pmk" in st.session_state:
        selected = items[items["pmk_ID"] == st.session_state["selected_pmk"]]
        if not selected.empty:
            render_item_detail(username, selected.iloc[0])
            return
        st.session_state.pop("selected_pmk", None)

    done_count = (items["الحالة"] == sc.STATUS_DONE).sum()
    total_count = len(items)

    col1, col2 = st.columns([3, 1])
    with col1:
        h2(f"أهلاً {title} {display_name}")
    with col2:
        logout_button()

    st.progress(done_count / total_count if total_count else 0, text=f"{done_count} / {total_count}")

    status_filter = st.radio(
        "عرض", ["الكل", sc.STATUS_NOT_STARTED, sc.STATUS_IN_PROGRESS, sc.STATUS_DONE],
        horizontal=True, label_visibility="collapsed",
    )
    filtered = items if status_filter == "الكل" else items[items["الحالة"] == status_filter]

    for _, item in filtered.iterrows():
        with st.container():
            render_item_card(item)
            if st.button("فتح", key=f"open_{item['pmk_ID']}"):
                st.session_state["selected_pmk"] = item["pmk_ID"]
                st.rerun()


# ---------------------------------------------------------------------------
# لوحة الأدمن
# ---------------------------------------------------------------------------

def render_admin_view():
    col1, col2 = st.columns([3, 1])
    with col1:
        h2("لوحة تحكم المدير")
        caption("مشروع استكمال القوانين المفقودة")
    with col2:
        logout_button()

    if da.ConnectionStatus.connected:
        st.success(
            f"متصل بـGoogle Sheets - آخر مزامنة ناجحة: "
            f"{da.ConnectionStatus.last_success.strftime('%H:%M:%S')}"
        )
    else:
        st.error(f"في مشكلة بالاتصال: {da.ConnectionStatus.last_error}")

    items = da.get_assignments_df()
    total = len(items)
    done = (items["الحالة"] == sc.STATUS_DONE).sum()
    in_progress = (items["الحالة"] == sc.STATUS_IN_PROGRESS).sum()
    not_started = (items["الحالة"] == sc.STATUS_NOT_STARTED).sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("إجمالي العناصر", total)
    c2.metric("مكتملة", int(done))
    c3.metric("جاري العمل عليها", int(in_progress))
    c4.metric("لم يبدأ بعد", int(not_started))

    h2("تقدم القانونيين")
    profiles = da.get_profiles_df()
    for i in range(1, sc.N_VOLUNTEERS + 1):
        uname = f"{sc.ASSIGNEE_PREFIX}{i}"
        person_items = items[items["القانوني_المسؤول"] == uname]
        p_total = len(person_items)
        p_done = (person_items["الحالة"] == sc.STATUS_DONE).sum()
        prof_match = profiles[profiles["اسم_المستخدم"] == uname] if not profiles.empty else pd.DataFrame()
        display = prof_match.iloc[0]["الاسم_المفضل"] if not prof_match.empty else uname

        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.write(f"**{display}** ({uname})")
            st.progress(p_done / p_total if p_total else 0, text=f"{p_done} / {p_total}")
        with col2:
            reassign_target = st.selectbox(
                "إعادة توزيع إلى", [f"{sc.ASSIGNEE_PREFIX}{j}" for j in range(1, sc.N_VOLUNTEERS + 1) if j != i],
                key=f"reassign_sel_{uname}", label_visibility="collapsed",
            )
        with col3:
            if st.button("نقل الغير مكتمل", key=f"reassign_btn_{uname}"):
                pending = person_items[person_items["الحالة"] != sc.STATUS_DONE]
                for pmk in pending["pmk_ID"]:
                    da.reassign_item(pmk, reassign_target)
                st.toast(f"تم نقل {len(pending)} عنصر إلى {reassign_target}")
                st.rerun()

    notes_df = items[items["ملاحظات"].astype(str).str.strip() != ""]
    if not notes_df.empty:
        h2("ملاحظات القانونيين")
        st.dataframe(
            notes_df[["pmk_ID", "اسم_التشريع", "القانوني_المسؤول", "ملاحظات"]],
            width='stretch', hide_index=True,
        )


# ---------------------------------------------------------------------------
# التوجيه الرئيسي
# ---------------------------------------------------------------------------

def main():
    if "username" not in st.session_state:
        render_login()
        return

    if st.session_state.role == "admin":
        render_admin_view()
        return

    profile = da.get_profile(st.session_state.username)
    if profile is None:
        render_onboarding()
        return

    render_volunteer_view(
        st.session_state.username, profile["الاسم_المفضل"], profile["الجنس"],
    )


if __name__ == "__main__":
    main()
