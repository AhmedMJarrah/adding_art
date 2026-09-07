# -*- coding: utf-8 -*-
"""
step10_diagnose_specific.py
=============================
تشخيص مركّز لحالات معينة (بالـpmk_ID) طلعت "مفقودة" رغم إنها تبدو متطابقة
ظاهرياً بالاسم/الرقم/السنة مع الجسون. يطبع كل المرشحين بالجسون اللي عندهم
نفس (الرقم، السنة) المطلوبة، مع تفاصيلهم الكاملة ونتيجة match_one بالضبط
- حتى نشوف هل في تعارض (أكثر من مرشح) وليش انحسم غلط أو ما انحسم.

عدّل قائمة PMK_IDS_TO_CHECK تحت وحط أي pmk_ID بدك تشخصه.

الاستخدام:
    python step10_diagnose_specific.py

يحتاج .env: CSV_FILE, JSON_FILE (الأصلي)

النسخة: 1.0.0 - 2026-09-06
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from lib_matching import (
    build_pools,
    match_one,
    normalize_arabic_name,
    normalize_number,
    normalize_year,
    content_similarity,
)
import step9_build_corrected_plan as s9  # لإعادة استخدام build_base_pool بالضبط

PMK_IDS_TO_CHECK = ["3643", "4140"]  # ضيف أي pmk_ID تاني هون


def main():
    load_dotenv()
    csv_path = Path(os.environ["CSV_FILE"])
    json_path = Path(os.environ["JSON_FILE"])

    print(f"تحميل CSV: {csv_path}")
    csv_df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    csv_by_pmk = {row["pmk_ID"]: row.to_dict() for _, row in csv_df.iterrows()}

    print(f"تحميل JSON: {json_path} (ممكن ياخذ وقت)")
    with open(json_path, "r", encoding="utf-8-sig") as f:
        json_entries = json.load(f)
    print(f"تم تحميل {len(json_entries)} عنصر\n")

    base_pool = s9.build_base_pool(json_entries)
    base_pool_num_year, base_pool_year = build_pools(base_pool)

    for pmk in PMK_IDS_TO_CHECK:
        print("=" * 78)
        print(f"pmk_ID = {pmk}")
        row = csv_by_pmk.get(pmk)
        if row is None:
            print("  !! مو موجود بالـCSV إطلاقاً")
            continue

        number = normalize_number(row.get("Law_Number"))
        year = normalize_year(row.get("Year"))
        name_norm = normalize_arabic_name(row.get("Law_Name"))
        mag_num = normalize_number(row.get("Magazine_Number"))
        mag_page = normalize_number(row.get("Magazine_Page_Number"))

        print(f"  من الـCSV: الاسم='{row.get('Law_Name')}'")
        print(f"             الرقم={row.get('Law_Number')} -> بعد التطبيع: {number}")
        print(f"             السنة={row.get('Year')} -> بعد التطبيع: {year}")
        print(f"             الجريدة: رقم={mag_num} صفحة={mag_page}")
        print()

        candidates = base_pool_num_year.get((number, year), [])
        print(f"  عدد المرشحين بالجسون بنفس (الرقم={number}, السنة={year}): {len(candidates)}")
        for c in candidates:
            sim = content_similarity(name_norm, c.name_norm)
            print(f"    - '{c.display_name}'")
            print(f"      جريدة: رقم={c.magazine_number} صفحة={c.magazine_page} | تشابه المحتوى مع الـCSV: {round(sim,3)}")

        if not candidates:
            print("  -> ما في ولا مرشح بنفس الرقم+السنة! (يعني الرقم أو السنة نفسهن مختلفين شوي عن الجسون - تحقق يدوياً)")

        result = match_one(number, year, name_norm, mag_num, mag_page, base_pool_num_year, base_pool_year)
        print()
        print(f"  نتيجة match_one: matched={result.matched}, tier={result.tier}, "
              f"score={round(result.score,3)}, ambiguous={result.ambiguous}")
        print(f"  ملاحظة: {result.note}")
        print()

    print("=" * 78)


if __name__ == "__main__":
    main()
