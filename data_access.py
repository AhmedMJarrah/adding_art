# -*- coding: utf-8 -*-
"""
data_access.py
===============
طبقة وسيطة بين تطبيق Streamlit وGoogle Sheets - كل القراءة/الكتابة تمر من
هون بدل ما app.py يحكي مباشرة مع gspread. بتستخدم كاش خفيف (5 ثواني) على
القراءة لتقليل عدد الطلبات، وأي كتابة بتلغي الكاش فوراً حتى المستخدم
يشوف التغيير من غير تأخير.

النسخة: 1.0.0 - 2026-09-03
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional

import pandas as pd
import streamlit as st

import sheets_client as sc

CACHE_TTL = 5  # ثواني - توازن بين "لحظي" وتقليل ضغط طلبات Sheets API


class ConnectionStatus:
    """حالة الاتصال الأخيرة - تُقرأ من لوحة الأدمن كمؤشر."""
    connected: bool = False
    last_success: Optional[datetime] = None
    last_error: Optional[str] = None


@st.cache_resource(show_spinner="جاري الاتصال بقاعدة البيانات...")
def _get_workbook():
    secret_dict = None
    secret_path = None
    has_cloud_secrets = False
    try:
        has_cloud_secrets = "gcp_service_account" in st.secrets
    except Exception:
        has_cloud_secrets = False  # ما في secrets.toml إطلاقاً - تشغيل محلي عادي

    if has_cloud_secrets:
        raw = st.secrets["gcp_service_account"]
        secret_dict = json.loads(raw) if isinstance(raw, str) else dict(raw)
    else:
        secret_path = os.environ.get("SECRET")

    def _secret_or_env(key, default=None):
        try:
            if key in st.secrets:
                return st.secrets[key]
        except Exception:
            pass
        return os.environ.get(key, default)

    sheet_name = _secret_or_env("SHEET_NAME", "adding_articles")
    sheet_id = _secret_or_env("SHEET_ID")

    return sc.init_workbook(
        secret_path=secret_path, sheet_name=sheet_name, sheet_id=sheet_id, secret_dict=secret_dict,
    )


def get_workbook():
    """يرجع (spreadsheet, assignments_ws, articles_ws, profiles_ws). يحدّث
    ConnectionStatus بكل محاولة - النجاح والفشل - حتى لوحة الأدمن تعرض
    آخر حالة اتصال فعلية."""
    try:
        wb = _get_workbook()
        ConnectionStatus.connected = True
        ConnectionStatus.last_success = datetime.now()
        ConnectionStatus.last_error = None
        return wb
    except Exception as e:
        ConnectionStatus.connected = False
        ConnectionStatus.last_error = str(e)
        raise


def _clear_data_cache():
    get_assignments_df.clear()
    get_articles_df.clear()
    get_profiles_df.clear()


# ---------------------------------------------------------------------------
# قراءة (كاش خفيف)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_assignments_df() -> pd.DataFrame:
    _, ws, _, _ = get_workbook()
    records = ws.get_all_records()
    return pd.DataFrame(records, columns=sc.ASSIGNMENTS_HEADERS) if records else pd.DataFrame(columns=sc.ASSIGNMENTS_HEADERS)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_articles_df() -> pd.DataFrame:
    _, _, ws, _ = get_workbook()
    records = ws.get_all_records()
    return pd.DataFrame(records, columns=sc.ARTICLES_HEADERS) if records else pd.DataFrame(columns=sc.ARTICLES_HEADERS)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_profiles_df() -> pd.DataFrame:
    _, _, _, ws = get_workbook()
    records = ws.get_all_records()
    return pd.DataFrame(records, columns=sc.PROFILES_HEADERS) if records else pd.DataFrame(columns=sc.PROFILES_HEADERS)


def get_profile(username: str) -> Optional[dict]:
    df = get_profiles_df()
    match = df[df["اسم_المستخدم"] == username]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def get_user_items(username: str) -> pd.DataFrame:
    df = get_assignments_df()
    return df[df["القانوني_المسؤول"] == username].reset_index(drop=True)


def get_item_articles(pmk_id: str) -> pd.DataFrame:
    df = get_articles_df()
    if df.empty:
        return df
    return df[df["pmk_ID"] == str(pmk_id)].sort_values(
        "رقم_المادة", key=lambda s: pd.to_numeric(s, errors="coerce")
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# كتابة (فورية - تلغي الكاش بعدها مباشرة)
# ---------------------------------------------------------------------------

def save_profile(username: str, display_name: str, gender: str):
    _, _, _, ws = get_workbook()
    existing = get_profiles_df()
    if not existing.empty and username in existing["اسم_المستخدم"].values:
        row_idx = existing.index[existing["اسم_المستخدم"] == username][0] + 2
        ws.update(f"B{row_idx}:C{row_idx}", [[display_name, gender]])
    else:
        ws.append_row([username, display_name, gender, datetime.now().strftime("%Y-%m-%d %H:%M")])
    _clear_data_cache()


def update_assignment(pmk_id: str, status: Optional[str] = None, notes: Optional[str] = None):
    """يحدّث الحالة و/أو الملاحظات لعنصر معيّن بشيت التكليفات."""
    _, ws, _, _ = get_workbook()
    df = get_assignments_df()
    matches = df.index[df["pmk_ID"] == str(pmk_id)]
    if len(matches) == 0:
        raise ValueError(f"pmk_ID={pmk_id} مو موجود بشيت التكليفات")
    row_idx = matches[0] + 2

    status_col = sc.ASSIGNMENTS_HEADERS.index("الحالة") + 1
    notes_col = sc.ASSIGNMENTS_HEADERS.index("ملاحظات") + 1
    if status is not None:
        ws.update_cell(row_idx, status_col, status)
    if notes is not None:
        ws.update_cell(row_idx, notes_col, notes)
    _clear_data_cache()


def save_article(pmk_id: str, article_number: str, text: str, entered_by: str):
    """يضيف مادة جديدة، أو يحدّث نصها لو رقم المادة موجود أصلاً لنفس
    القانون (تعديل/استئناف، مش تكرار)."""
    _, _, ws, _ = get_workbook()
    df = get_articles_df()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    if not df.empty:
        matches = df.index[(df["pmk_ID"] == str(pmk_id)) & (df["رقم_المادة"] == str(article_number))]
    else:
        matches = []

    if len(matches) > 0:
        row_idx = matches[0] + 2
        ws.update(f"C{row_idx}:E{row_idx}", [[text, entered_by, now]])
    else:
        ws.append_row([str(pmk_id), str(article_number), text, entered_by, now])
    _clear_data_cache()


def delete_article(pmk_id: str, article_number: str):
    _, _, ws, _ = get_workbook()
    df = get_articles_df()
    matches = df.index[(df["pmk_ID"] == str(pmk_id)) & (df["رقم_المادة"] == str(article_number))]
    if len(matches) == 0:
        return
    row_idx = matches[0] + 2
    ws.delete_rows(row_idx)
    _clear_data_cache()


def reassign_item(pmk_id: str, new_assignee: str):
    _, ws, _, _ = get_workbook()
    df = get_assignments_df()
    matches = df.index[df["pmk_ID"] == str(pmk_id)]
    if len(matches) == 0:
        raise ValueError(f"pmk_ID={pmk_id} مو موجود بشيت التكليفات")
    row_idx = matches[0] + 2
    col = sc.ASSIGNMENTS_HEADERS.index("القانوني_المسؤول") + 1
    ws.update_cell(row_idx, col, new_assignee)
    _clear_data_cache()
