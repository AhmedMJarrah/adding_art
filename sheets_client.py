# -*- coding: utf-8 -*-
"""
sheets_client.py
=================
وحدة مشتركة للاتصال بملف "adding_articles" على Google Sheets، تُستخدم من
كل السكريبتات وتطبيق Streamlit لاحقاً - مكان واحد لمنطق الاتصال حتى ما
يتكرر بكل ملف.

الشيتات المتوقعة داخل الملف (تُنشأ تلقائياً أول مرة لو مو موجودة):
    "تكليفات": pmk_ID, النوع, اسم_التشريع, الرقم, السنة, رقم_الجريدة_الرسمية,
               رقم_الصفحة, تاريخ_الجريدة, القانوني_المسؤول, الحالة, ملاحظات
    "مواد":    pmk_ID, رقم_المادة, نص_المادة, أدخلها, وقت_الإدخال

النسخة: 1.2.0 - 2026-09-03
    - إضافة شيت "المستخدمون" (اسم_المستخدم، الاسم_المفضل، الجنس، أول_دخول)
      لدعم شاشة الترحيب لمرة وحدة بالتطبيق. init_workbook صار يرجّع 4 قيم
      بدل 3 - أي سكريبت يستدعيها لازم يتحدّث.
    - get_client صار يدعم secret_dict (لنشر Streamlit Cloud اللي ما فيه
      نظام ملفات محلي) بالإضافة لـsecret_path (التشغيل المحلي).

النسخة: 1.1.0 - 2026-09-03
    - دعم فتح الملف بالـSHEET_ID (أفضل وأضمن) مع بقاء الاسم كـfallback.

النسخة: 1.0.0 - 2026-09-03
"""

from __future__ import annotations

import logging
from typing import Optional

import gspread
from gspread.exceptions import SpreadsheetNotFound, WorksheetNotFound

SHEET_ASSIGNMENTS = "تكليفات"
SHEET_ARTICLES = "مواد"
SHEET_PROFILES = "المستخدمون"

ASSIGNMENTS_HEADERS = [
    "pmk_ID", "النوع", "اسم_التشريع", "الرقم", "السنة",
    "رقم_الجريدة_الرسمية", "رقم_الصفحة", "تاريخ_الجريدة",
    "القانوني_المسؤول", "الحالة", "ملاحظات",
]
ARTICLES_HEADERS = ["pmk_ID", "رقم_المادة", "نص_المادة", "أدخلها", "وقت_الإدخال"]
PROFILES_HEADERS = ["اسم_المستخدم", "الاسم_المفضل", "الجنس", "أول_دخول"]

STATUS_NOT_STARTED = "لم يبدأ"
STATUS_IN_PROGRESS = "جاري العمل"
STATUS_DONE = "تم"

N_VOLUNTEERS = 5
ASSIGNEE_PREFIX = "قانوني_"


def get_client(secret_path: Optional[str] = None, secret_dict: Optional[dict] = None) -> gspread.Client:
    """يفتح اتصال مصادَق. يدعم طريقتين: ملف على القرص (تشغيل محلي عند
    أحمد، عبر SECRET بالـ.env) أو dict بالذاكرة (نشر على Streamlit Cloud،
    عبر st.secrets - ما في نظام ملفات محلي هناك). يرمي استثناء واضح لو
    المسار غلط بدل ما ينهار برسالة gspread الخام."""
    if secret_dict is not None:
        return gspread.service_account_from_dict(secret_dict)
    if secret_path is not None:
        try:
            return gspread.service_account(filename=secret_path)
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"ملف الـService Account مو موجود بالمسار: {secret_path} - "
                f"تأكد من قيمة SECRET بملف .env"
            ) from e
    raise ValueError("لازم تمرر secret_path أو secret_dict - ولا واحد فيهم انعطى")


def open_workbook(
    client: gspread.Client,
    name: str = "adding_articles",
    sheet_id: Optional[str] = None,
) -> gspread.Spreadsheet:
    """يفضّل الفتح بالـID لو متوفر (أضمن وأسرع - ما يعتمد على تطابق اسم
    حرفي أو وجود نسخة وحيدة بهالاسم). يرجع للفتح بالاسم لو الـID مو موجود."""
    if sheet_id:
        try:
            return client.open_by_key(sheet_id)
        except SpreadsheetNotFound as e:
            raise SpreadsheetNotFound(
                f"ملف Google Sheets بالـID \"{sheet_id}\" مو موجود أو مو "
                f"مشارك مع إيميل الـService Account"
            ) from e
    try:
        return client.open(name)
    except SpreadsheetNotFound as e:
        raise SpreadsheetNotFound(
            f"ملف Google Sheets باسم \"{name}\" مو موجود أو مو مشارك مع "
            f"إيميل الـService Account - تأكد من الاسم والمشاركة (Editor)"
        ) from e


def get_or_create_worksheet(
    spreadsheet: gspread.Spreadsheet,
    title: str,
    headers: list,
    logger: Optional[logging.Logger] = None,
) -> gspread.Worksheet:
    """يرجّع الشيت لو موجود (ويتأكد من تطابق الأعمدة)، وإلا ينشئه بالأعمدة
    المطلوبة. ما يمسح أو يعيد ترتيب أعمدة موجودة أصلاً - بس يحذّر إذا
    مختلفة عن المتوقع."""
    log = logger or logging.getLogger(__name__)
    try:
        ws = spreadsheet.worksheet(title)
        existing = ws.row_values(1)
        if not existing:
            ws.append_row(headers)
            log.info(f"شيت \"{title}\" موجود بس فاضي - أضفت صف العناوين")
        elif existing != headers:
            log.warning(
                f"شيت \"{title}\" موجود بأعمدة مختلفة عن المتوقع!\n"
                f"  موجود : {existing}\n  متوقع : {headers}\n"
                f"  ما عدّلتها تلقائياً تفادياً لفقدان بيانات - راجعها يدوياً لو لازم"
            )
        else:
            log.info(f"شيت \"{title}\" موجود وبالأعمدة الصحيحة")
        return ws
    except WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=len(headers) + 2)
        ws.append_row(headers)
        log.info(f"أنشأت شيت \"{title}\" جديد بالأعمدة المطلوبة")
        return ws


def init_workbook(
    secret_path: Optional[str] = None,
    sheet_name: str = "adding_articles",
    sheet_id: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
    secret_dict: Optional[dict] = None,
):
    """نقطة الدخول الرئيسية - تفتح الاتصال وتضمن وجود الشيتات الثلاث بالشكل
    الصحيح. ترجّع (spreadsheet, assignments_ws, articles_ws, profiles_ws)."""
    log = logger or logging.getLogger(__name__)
    client = get_client(secret_path, secret_dict)
    log.info("تم الاتصال بـGoogle عبر الـService Account بنجاح")

    spreadsheet = open_workbook(client, sheet_name, sheet_id)
    log.info(f"تم فتح الملف: {spreadsheet.title} ({spreadsheet.url})")

    assignments_ws = get_or_create_worksheet(spreadsheet, SHEET_ASSIGNMENTS, ASSIGNMENTS_HEADERS, log)
    articles_ws = get_or_create_worksheet(spreadsheet, SHEET_ARTICLES, ARTICLES_HEADERS, log)
    profiles_ws = get_or_create_worksheet(spreadsheet, SHEET_PROFILES, PROFILES_HEADERS, log)

    return spreadsheet, assignments_ws, articles_ws, profiles_ws
