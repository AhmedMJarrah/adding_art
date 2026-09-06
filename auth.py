# -*- coding: utf-8 -*-
"""
auth.py
=======
التحقق من بيانات الدخول. كلمات السر تُقرأ من st.secrets (نشر Streamlit
Cloud) أو من متغيرات البيئة (تشغيل محلي) - أبداً مش مكتوبة بالكود.

يحتاج (بـsecrets.toml أو .env):
    VOLUNTEER_PASSWORD   - كلمة سر موحّدة لكل حسابات قانوني_1..قانوني_N
    ADMIN_USERNAME       - اسم مستخدم الأدمن (افتراضي: admin)
    ADMIN_PASSWORD       - كلمة سر الأدمن (مختلفة عن كلمة سر القانونيين)

النسخة: 1.0.0 - 2026-09-03
"""

from __future__ import annotations

import os
from typing import Optional

import streamlit as st

from dotenv import load_dotenv
load_dotenv()

import sheets_client as sc


def _get_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    """يقرأ من st.secrets لو موجود، وإلا من متغيرات البيئة. st.secrets
    نفسها بترمي استثناء لو ملف secrets.toml مو موجود إطلاقاً (حالة
    التشغيل المحلي عند أحمد اللي بيعتمد .env بس) - نلتقطه ونرجع للبيئة."""
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key, default)


def valid_volunteer_usernames() -> set:
    return {f"{sc.ASSIGNEE_PREFIX}{i}" for i in range(1, sc.N_VOLUNTEERS + 1)}


def check_login(username: str, password: str) -> Optional[str]:
    """يرجع 'admin' أو 'volunteer' لو صحيح، وإلا None. ما يميّز بالرسالة
    بين 'اسم مستخدم غلط' و'كلمة سر غلط' عمداً (ممارسة أمان قياسية)."""
    username = (username or "").strip()
    if not username or not password:
        return None

    admin_username = _get_secret("ADMIN_USERNAME", "admin")
    admin_password = _get_secret("ADMIN_PASSWORD")
    if admin_password and username == admin_username and password == admin_password:
        return "admin"

    volunteer_password = _get_secret("VOLUNTEER_PASSWORD")
    if volunteer_password and username in valid_volunteer_usernames() and password == volunteer_password:
        return "volunteer"

    return None
