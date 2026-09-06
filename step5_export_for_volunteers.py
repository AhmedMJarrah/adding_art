# -*- coding: utf-8 -*-
"""
step5_export_for_volunteers.py
===============================
يولّد ملف CSV بكل القوانين/التعديلات اللي ثبت (بعد step4) إنها مو موجودة
بقاعدة بيانات الديوان إطلاقاً - هاي هي القائمة اللي رح تتعبى يدوياً من
خلال واجهة المتطوعين.

كل صف فيه معلومات التعريف الكاملة (من الـCSV المرجعي) حتى المتطوع يقدر
يحدد المستند الصحيح بدقة (بالجريدة الرسمية أو أي مصدر ثاني)، بالإضافة
لعمود "النوع" (قانون أساسي / تعديل) حتى تكون واضحة بواجهة الإدخال.

الاستخدام:
    python step5_export_for_volunteers.py

يحتاج نفس .env (CSV_FILE, OUTPUT_DIR, LOG_DIR) - يقرأ تلقائياً آخر
zero_articles_*.json و merge_plan_*.json (لتصنيف أساسي/تعديل، نفس منطق step4).

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

import pandas as pd
from dotenv import load_dotenv

__version__ = "1.0.0"


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"step5_export_{ts}.log"
    logger = logging.getLogger("step5_export")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fh = logging.FileHandler(log_file, encoding="utf-8")
    ch = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fmt); ch.setFormatter(fmt)
    logger.addHandler(fh); logger.addHandler(ch)
    logger.info(f"بدء التشغيل - step5_export_for_volunteers v{__version__}")
    logger.info(f"ملف اللوج: {log_file}")
    return logger


def find_latest(output_dir: Path, pattern: str, logger: logging.Logger) -> Path:
    files = sorted(glob.glob(str(output_dir / pattern)))
    if not files:
        raise FileNotFoundError(f"ما لقيت أي ملف يطابق {pattern} بمجلد {output_dir}")
    latest = Path(files[-1])
    logger.info(f"آخر ملف {pattern}: {latest.name} (من أصل {len(files)})")
    return latest


def classify(zero_ids: list, merge_plan: dict) -> dict:
    base_ids = {item["base_pmk_ID"] for item in merge_plan["add_new_top_level"]}
    amend_ids = set()
    for item in merge_plan["add_new_top_level"]:
        amend_ids.update(item["amendment_pmk_IDs"])
    for item in merge_plan["extend_existing"]:
        amend_ids.update(item["amendment_pmk_IDs"])

    result = {}
    for pmk in {str(i) for i in zero_ids}:
        if pmk in base_ids:
            result[pmk] = "قانون أساسي"
        elif pmk in amend_ids:
            result[pmk] = "تعديل"
        else:
            result[pmk] = "غير مصنَّف"  # نفس تحذير step4 - نادر الحدوث
    return result


def main():
    load_dotenv()
    csv_path = Path(os.environ["CSV_FILE"])
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output"))
    log_dir = Path(os.environ.get("LOG_DIR", "logs"))
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logging(log_dir)

    zero_path = find_latest(output_dir, "zero_articles_*.json", logger)
    with open(zero_path, "r", encoding="utf-8") as f:
        zero_ids = json.load(f)

    merge_plan_path = find_latest(output_dir, "merge_plan_*.json", logger)
    with open(merge_plan_path, "r", encoding="utf-8") as f:
        merge_plan = json.load(f)

    type_map = classify(zero_ids, merge_plan)
    unclassified = [k for k, v in type_map.items() if v == "غير مصنَّف"]
    if unclassified:
        logger.warning(f"{len(unclassified)} pmk_ID ما انصنّفوا (نفس المشكلة يلي شفناها بstep4): {unclassified}")

    logger.info(f"تحميل CSV المرجعي: {csv_path}")
    csv_df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    csv_df = csv_df[csv_df["pmk_ID"].isin(type_map.keys())].copy()
    logger.info(f"تم إيجاد {len(csv_df)} صف من أصل {len(type_map)} pmk_ID مطلوب")

    missing_from_csv = set(type_map.keys()) - set(csv_df["pmk_ID"])
    if missing_from_csv:
        logger.error(f"{len(missing_from_csv)} pmk_ID مو موجودين حتى بالـCSV المرجعي! {sorted(missing_from_csv, key=int)}")

    csv_df["النوع"] = csv_df["pmk_ID"].map(type_map)
    csv_df["حالة_الإدخال"] = ""  # عمود فاضي - رح تعبيه واجهة المتطوعين (لسا ما بدأ / جاري / تم)

    def clean_num(v):
        v = str(v).strip()
        return v[:-2] if v.endswith(".0") else v

    for col in ["Law_Number", "Year", "Magazine_Number", "Magazine_Page_Number"]:
        if col in csv_df.columns:
            csv_df[col] = csv_df[col].apply(clean_num)

    # ما ضمّينا Active_Date - لقينا حالات فيها تاريخ نفاذ قبل سنة القانون
    # نفسه (بيانات غير موثوقة أحياناً بهالعمود بالـCSV)، وأصلاً مو ضروري
    # لتحديد المستند الصحيح - رقم/صفحة/تاريخ الجريدة كافيين لهيك.
    out_cols = {
        "pmk_ID": "pmk_ID",
        "النوع": "النوع",
        "Law_Name": "اسم_التشريع",
        "Law_Number": "الرقم",
        "Year": "السنة",
        "Magazine_Number": "رقم_الجريدة_الرسمية",
        "Magazine_Page_Number": "رقم_الصفحة",
        "Magazine_Date": "تاريخ_الجريدة",
        "حالة_الإدخال": "حالة_الإدخال",
    }
    missing_cols = [c for c in out_cols if c not in csv_df.columns]
    if missing_cols:
        logger.error(f"أعمدة متوقعة مو موجودة بالـCSV: {missing_cols}")
    present_cols = [c for c in out_cols if c in csv_df.columns]
    out_df = csv_df[present_cols].rename(columns=out_cols)

    out_df = out_df.sort_values(["النوع", "السنة", "الرقم"] if "السنة" in out_df.columns else "النوع")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"volunteers_missing_articles_{ts}.csv"
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    logger.info(f"=== ملخص ===")
    logger.info(f"إجمالي: {len(out_df)}")
    for t, n in out_df["النوع"].value_counts().items():
        logger.info(f"  {t}: {n}")
    logger.info(f"الملف الجاهز للمتطوعين: {out_path}")


if __name__ == "__main__":
    main()
