# -*- coding: utf-8 -*-
"""
step6_init_sheets.py
=====================
يتصل بملف "adding_articles" على Google Sheets ويضمن وجود الشيتين
المطلوبين ("تكليفات" و"مواد") بالأعمدة الصحيحة - ينشئهم لو مو موجودين،
وإلا يتحقق منهم بدون ما يلمس بيانات موجودة.

شغّله مرة وحدة بالبداية، وآمن تشغّله أكثر من مرة (idempotent).

الاستخدام:
    python step6_init_sheets.py

يحتاج بـ.env:
    SECRET=<مسار ملف الـService Account JSON>
    (اختياري) SHEET_NAME=adding_articles

النسخة: 1.0.0 - 2026-09-03
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from sheets_client import init_workbook

__version__ = "1.0.0"


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"step6_init_sheets_{ts}.log"
    logger = logging.getLogger("step6_init_sheets")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fh = logging.FileHandler(log_file, encoding="utf-8")
    ch = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fmt); ch.setFormatter(fmt)
    logger.addHandler(fh); logger.addHandler(ch)
    logger.info(f"بدء التشغيل - step6_init_sheets v{__version__}")
    logger.info(f"ملف اللوج: {log_file}")
    return logger


def main():
    load_dotenv()
    secret_path = os.environ["SECRET"]
    sheet_name = os.environ.get("SHEET_NAME", "adding_articles")
    sheet_id = os.environ.get("SHEET_ID")  # مفضّل لو موجود - راجع رسالة Claude لمكانه بالرابط
    log_dir = Path(os.environ.get("LOG_DIR", "logs"))
    logger = setup_logging(log_dir)

    try:
        spreadsheet, assignments_ws, articles_ws, profiles_ws = init_workbook(secret_path, sheet_name, sheet_id, logger)
    except Exception as e:
        logger.error(f"فشل الاتصال أو التهيئة: {e}")
        raise

    logger.info("=== جاهز ===")
    logger.info(f"رابط الملف: {spreadsheet.url}")
    logger.info(f"شيت التكليفات: {assignments_ws.title} ({assignments_ws.row_count} صف متاح)")
    logger.info(f"شيت المواد: {articles_ws.title} ({articles_ws.row_count} صف متاح)")
    logger.info(f"شيت المستخدمين: {profiles_ws.title} ({profiles_ws.row_count} صف متاح)")


if __name__ == "__main__":
    main()
