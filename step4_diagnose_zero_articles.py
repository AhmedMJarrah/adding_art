# -*- coding: utf-8 -*-
"""
step4_diagnose_zero_articles.py
================================
يولّد سكريبت SQL تشخيصي للتأكد من الـpmk_ID اللي طلعوا بدون مواد بالاستخراج
(zero_articles_*.json من step3): هل فعلاً ما إلها مواد بقاعدة بيانات الديوان،
ولا في مشكلة ربط/فلترة سببت غيابها بالغلط؟

بيقرأ zero_articles_*.json (قائمة مسطّحة) و merge_plan_*.json (عشان نعرف
مين منها أساسي ومين تعديل - zero_articles ما بيفرّق بينهم) ويولّد SQL فيه
4 استعلامات تشخيصية:

    [1] هل سجل القانون الأساسي نفسه موجود بجدول UD_leg_Laws؟
    [2] كم صف مادة فعلي موجود له بـUD_leg_Article (بما فيها المحذوفة/التاريخية)؟
    [3] هل سجل التعديل نفسه موجود بجدول UD_leg_Legislative_Amendments؟
    [4] كم صف مادة فعلي موجود له بـUD_leg_Related_Modification_Articles؟

الاستعلامات [2] و[4] ما بتفلتر isDelete/isHistorical عمداً - بدنا نشوف
الصورة الكاملة، الفلترة كانت بس بسكريبت الدمج (step3).

الاستخدام:
    python step4_diagnose_zero_articles.py

النسخة: 1.0.0 - 2026-09-03
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

FK_LAWS = "fnk_leg_Laws10689"
FK_AMENDMENTS = "fnk_leg_Legislative_Amendments10747"
IDS_PER_LINE = 15


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"step4_diagnose_{ts}.log"
    logger = logging.getLogger("step4_diagnose")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fh = logging.FileHandler(log_file, encoding="utf-8")
    ch = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fmt); ch.setFormatter(fmt)
    logger.addHandler(fh); logger.addHandler(ch)
    logger.info(f"بدء التشغيل - step4_diagnose_zero_articles v{__version__}")
    logger.info(f"ملف اللوج: {log_file}")
    return logger


def find_latest(output_dir: Path, pattern: str, logger: logging.Logger) -> Path:
    files = sorted(glob.glob(str(output_dir / pattern)))
    if not files:
        raise FileNotFoundError(f"ما لقيت أي ملف يطابق {pattern} بمجلد {output_dir}")
    latest = Path(files[-1])
    logger.info(f"آخر ملف {pattern}: {latest.name} (من أصل {len(files)})")
    return latest


def format_id_list(ids: list, indent: str = "    ") -> str:
    ids_int = sorted({int(i) for i in ids})
    lines = []
    for i in range(0, len(ids_int), IDS_PER_LINE):
        chunk = ids_int[i:i + IDS_PER_LINE]
        lines.append(indent + ", ".join(str(x) for x in chunk))
    return ",\n".join(lines)


def split_base_vs_amendment(zero_ids: list, merge_plan: dict) -> tuple[list, list]:
    """zero_articles.json قائمة مسطّحة ما بتفرّق أساسي عن تعديل - نستنتج
    التصنيف من merge_plan.json (نفس التشغيلة) بدل ما نطلب من أحمد يرفع
    ملف إضافي أو يعيد تشغيل step3."""
    base_ids_known = {item["base_pmk_ID"] for item in merge_plan["add_new_top_level"]}
    amend_ids_known = set()
    for item in merge_plan["add_new_top_level"]:
        amend_ids_known.update(item["amendment_pmk_IDs"])
    for item in merge_plan["extend_existing"]:
        amend_ids_known.update(item["amendment_pmk_IDs"])

    zero_set = {str(i) for i in zero_ids}
    base_zero = sorted(zero_set & base_ids_known, key=int)
    amend_zero = sorted(zero_set & amend_ids_known, key=int)

    unclassified = zero_set - base_ids_known - amend_ids_known
    return base_zero, amend_zero, sorted(unclassified, key=int)


def build_sql(base_ids: list, amend_ids: list, source_file: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [
        "-- ============================================================",
        "-- تشخيص الـpmk_ID اللي طلعت بدون مواد بالاستخراج - مشروع insert",
        f"-- تم التوليد: {ts}",
        f"-- المصدر: {source_file}",
        f"-- قوانين أساسية للتشخيص: {len(base_ids)} | تعديلات للتشخيص: {len(amend_ids)}",
        "-- شغّل الاستعلامات الأربعة مع بعض، وصدّر كل نتيجة CSV منفصل بنفس",
        "-- الاسم المذكور بالتعليق فوقها.",
        "-- ============================================================",
        "",
    ]

    if base_ids:
        parts += [
            "-- [1] هل سجل القانون الأساسي نفسه موجود بجدول UD_leg_Laws؟",
            "-- صدّر باسم: diag_base_laws_exist.csv",
            "SELECT *",
            "FROM UD_leg_Laws",
            "WHERE pmk_ID IN (",
            format_id_list(base_ids),
            ");",
            "",
            "-- [2] كم صف مادة فعلي له بـUD_leg_Article - بدون أي فلترة",
            "--     (نشوف حتى المحذوف/التاريخي، عشان نتأكد الفلترة مو سبب الغياب)",
            "-- صدّر باسم: diag_base_articles_count.csv",
            f"SELECT {FK_LAWS} AS pmk_ID,",
            "       COUNT(*) AS total_rows,",
            "       SUM(CASE WHEN isDelete = 1 THEN 1 ELSE 0 END) AS deleted_rows,",
            "       SUM(CASE WHEN isHistorical = 1 THEN 1 ELSE 0 END) AS historical_rows",
            "FROM UD_leg_Article",
            f"WHERE {FK_LAWS} IN (",
            format_id_list(base_ids),
            ")",
            f"GROUP BY {FK_LAWS}",
            f"ORDER BY {FK_LAWS};",
            "",
        ]
    else:
        parts.append("-- ما في قوانين أساسية للتشخيص\n")

    if amend_ids:
        parts += [
            "-- [3] هل سجل التعديل نفسه موجود بجدول UD_leg_Legislative_Amendments؟",
            "-- صدّر باسم: diag_amendments_exist.csv",
            "SELECT *",
            "FROM UD_leg_Legislative_Amendments",
            "WHERE pmk_ID IN (",
            format_id_list(amend_ids),
            ");",
            "",
            "-- [4] كم صف مادة فعلي له بـUD_leg_Related_Modification_Articles - بدون فلترة",
            "-- صدّر باسم: diag_amendment_articles_count.csv",
            f"SELECT {FK_AMENDMENTS} AS pmk_ID,",
            "       COUNT(*) AS total_rows,",
            "       SUM(CASE WHEN isDelete = 1 THEN 1 ELSE 0 END) AS deleted_rows,",
            "       SUM(CASE WHEN isHistorical = 1 THEN 1 ELSE 0 END) AS historical_rows",
            "FROM UD_leg_Related_Modification_Articles",
            f"WHERE {FK_AMENDMENTS} IN (",
            format_id_list(amend_ids),
            ")",
            f"GROUP BY {FK_AMENDMENTS}",
            f"ORDER BY {FK_AMENDMENTS};",
            "",
        ]
    else:
        parts.append("-- ما في تعديلات للتشخيص\n")

    return "\n".join(parts)


def main():
    load_dotenv()
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output"))
    log_dir = Path(os.environ.get("LOG_DIR", "logs"))
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logging(log_dir)

    zero_path = find_latest(output_dir, "zero_articles_*.json", logger)
    with open(zero_path, "r", encoding="utf-8") as f:
        zero_ids = json.load(f)
    logger.info(f"إجمالي pmk_ID بدون مواد: {len(zero_ids)}")

    merge_plan_path = find_latest(output_dir, "merge_plan_*.json", logger)
    with open(merge_plan_path, "r", encoding="utf-8") as f:
        merge_plan = json.load(f)

    base_ids, amend_ids, unclassified = split_base_vs_amendment(zero_ids, merge_plan)
    logger.info(f"منها أساسية: {len(base_ids)} | تعديلات: {len(amend_ids)}")
    if unclassified:
        logger.warning(
            f"{len(unclassified)} pmk_ID ما قدرت أصنّفهم أساسي/تعديل من merge_plan "
            f"(تأكد إنه merge_plan وzero_articles من نفس التشغيلة): {unclassified}"
        )

    sql_text = build_sql(base_ids, amend_ids, zero_path.name)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sql_path = output_dir / f"step4_diagnose_{ts}.sql"
    with open(sql_path, "w", encoding="utf-8-sig") as f:
        f.write(sql_text)
    logger.info(f"سكريبت SQL التشخيصي جاهز: {sql_path}")


if __name__ == "__main__":
    main()
