# -*- coding: utf-8 -*-
"""
step2_generate_sql.py
======================
الخطوة 2 من مشروع "insert": يقرأ آخر ملف missing_pmk_ids_*.json (مخرجات
step1_reconcile.py) ويولّد سكريبت SQL واحد فيه استعلامين:

    1) مواد القوانين الأساسية المفقودة  -> UD_leg_Article
    2) مواد التعديلات المفقودة          -> UD_leg_Related_Modification_Articles

الاستعلامين SELECT * (ما عندي أسماء أعمدة الجداول هذول غير عمود الـFK اللي
حكيت عنه، فـSELECT * أضمن من التخمين). شغّل السكريبت بالـRDP عبر SSMS (أو أي
أداة تستخدمها) - رح يطلع لك نتيجتين (result sets)، صدّر كل وحدة CSV UTF-8
منفصل بنفس التسمية المذكورة بتعليق أول كل استعلام بالملف الناتج.

هالسكريبت للقراءة فقط ومولّد نص - ما بيتصل بأي قاعدة بيانات (ما عندي وصول
لشبكتكم الداخلية أصلاً).

الاستخدام:
    python step2_generate_sql.py

يحتاج نفس .env تبع الخطوة 1 (يقرأ OUTPUT_DIR و LOG_DIR منه)، ويلقط تلقائياً
آخر ملف missing_pmk_ids_*.json موجود بمجلد OUTPUT_DIR.

النسخة: 1.0.0 - 2026-09-02
"""

from __future__ import annotations

import glob
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

__version__ = "1.0.0"

# أسماء أعمدة الربط (FK) حسب ما وصفهم أحمد - عدّلهم هون لو تغيّروا
FK_BASE_LAWS_COLUMN = "fnk_leg_Laws10689"
FK_AMENDMENTS_COLUMN = "fnk_leg_Legislative_Amendments10747"

TABLE_ARTICLES_BASE = "UD_leg_Article"
TABLE_ARTICLES_AMENDMENTS = "UD_leg_Related_Modification_Articles"

IDS_PER_LINE = 15  # للتنسيق بس - سهل تتابع الفرق لو عدّلت لاحقاً بـ git


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"step2_generate_sql_{ts}.log"

    logger = logging.getLogger("step2_generate_sql")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s",
                             datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info(f"بدء التشغيل - step2_generate_sql v{__version__}")
    logger.info(f"ملف اللوج: {log_file}")
    return logger


def find_latest_missing_ids_file(output_dir: Path, logger: logging.Logger) -> Path:
    pattern = str(output_dir / "missing_pmk_ids_*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(
            f"ما لقيت أي ملف missing_pmk_ids_*.json بمجلد {output_dir} - "
            f"شغّل step1_reconcile.py أول."
        )
    latest = Path(files[-1])  # الاسم فيه timestamp، فالترتيب الأبجدي = الترتيب الزمني
    logger.info(f"آخر ملف pmk_ID مفقودة: {latest.name} (من أصل {len(files)} ملف موجود)")
    return latest


def format_id_list(ids: list, indent: str = "    ") -> str:
    """يرجّع نص IN (...) مقسّم على أسطر - أسهل للقراءة والمراجعة بـgit diff."""
    ids_int = [int(i) for i in ids]  # نتأكد إنهم أرقام صحيحة، pmk_ID مفتاح رقمي
    lines = []
    for i in range(0, len(ids_int), IDS_PER_LINE):
        chunk = ids_int[i:i + IDS_PER_LINE]
        lines.append(indent + ", ".join(str(x) for x in chunk))
    return ",\n".join(lines)


def build_sql(base_ids: list, amend_ids: list, source_file: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [
        "-- ============================================================",
        "-- استخراج مواد القوانين/التعديلات المفقودة - مشروع insert",
        f"-- تم التوليد: {ts}",
        f"-- المصدر: {source_file}",
        f"-- عدد القوانين الأساسية: {len(base_ids)} | عدد التعديلات: {len(amend_ids)}",
        "-- شغّل الاستعلامين مع بعض بـSSMS، رح يطلعوا نتيجتين (result sets)",
        "-- منفصلتين. صدّر كل وحدة CSV (encoding: UTF-8) بنفس الاسم المذكور",
        "-- بالتعليق فوق كل استعلام، وحطهم بمجلد data/ الموجود بالمشروع.",
        "-- ============================================================",
        "",
    ]

    if base_ids:
        parts += [
            "-- [1] مواد القوانين الأساسية المفقودة",
            f"-- صدّر النتيجة باسم: base_articles_extract.csv",
            f"SELECT *",
            f"FROM {TABLE_ARTICLES_BASE}",
            f"WHERE {FK_BASE_LAWS_COLUMN} IN (",
            format_id_list(base_ids),
            f")",
            f"ORDER BY {FK_BASE_LAWS_COLUMN};",
            "",
        ]
    else:
        parts.append("-- ما في قوانين أساسية مفقودة حالياً - تم تخطي هالاستعلام\n")

    if amend_ids:
        parts += [
            "-- [2] مواد التعديلات المفقودة",
            f"-- صدّر النتيجة باسم: amendment_articles_extract.csv",
            f"SELECT *",
            f"FROM {TABLE_ARTICLES_AMENDMENTS}",
            f"WHERE {FK_AMENDMENTS_COLUMN} IN (",
            format_id_list(amend_ids),
            f")",
            f"ORDER BY {FK_AMENDMENTS_COLUMN};",
            "",
        ]
    else:
        parts.append("-- ما في تعديلات مفقودة حالياً - تم تخطي هالاستعلام\n")

    return "\n".join(parts)


def main():
    load_dotenv()
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output"))
    log_dir = Path(os.environ.get("LOG_DIR", "logs"))
    output_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging(log_dir)

    src = find_latest_missing_ids_file(output_dir, logger)
    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)

    base_ids = data.get("base", [])
    amend_ids = data.get("amendments", [])
    logger.info(f"قوانين أساسية مفقودة: {len(base_ids)}")
    logger.info(f"تعديلات مفقودة: {len(amend_ids)}")

    if not base_ids and not amend_ids:
        logger.warning("القائمتين فاضيتين - ما في شي يتولّد له SQL. تأكد من ملف step1 الناتج.")
        return

    sql_text = build_sql(base_ids, amend_ids, src.name)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sql_path = output_dir / f"step2_extract_articles_{ts}.sql"
    with open(sql_path, "w", encoding="utf-8-sig") as f:  # BOM حتى SSMS يتعرف UTF-8 صح لو فيه عربي بالتعليقات
        f.write(sql_text)

    logger.info(f"سكريبت SQL جاهز: {sql_path}")
    logger.info("افتحه بـSSMS، شغّله، وصدّر النتيجتين CSV زي ما موضّح بالتعليقات جوا الملف.")


if __name__ == "__main__":
    main()
