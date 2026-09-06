# -*- coding: utf-8 -*-
"""
step8_global_recheck.py
=========================
اكتشفنا إنه بنية السلاسل بالـCSV (chain_id_v2/chain_position_v2) فيها
أخطاء حقيقية ببعض الصفوف (خصوصاً المُسترجَعة من عمل فريق سابق):
    - تعديلات معاملة كـ"قانون أساسي مستقل" (chain_position_v2=0) رغم
      إنها فعلياً متداخلة جوا قانون تاني بالجسون.
    - تعديلات محطوطة بسلسلة غلط (مثلاً تعديل 1971 ضمن سلسلة قانون 1999).

step1_reconcile.py وثق ببنية السلاسل هاي وبحث كل عنصر بمكان واحد بس (أعلى
مستوى للأساسيات، أو جوا الأب المحدد بالسلسلة للتعديلات) - فأي عنصر بالمكان
الغلط ظهر "مفقود" رغم وجوده الفعلي بالجسون بمكان تاني.

هالسكريبت يعيد فحص **كل** عنصر مصنَّف "مفقود" (أساسي أو تعديل، من
merge_plan الأخير) ضد:
    [أ] مجمّع كل القوانين الأساسية بأعلى مستوى (نفس فحص step1)
    [ب] مجمّع **كل** التعديلات (Mod_Legs) من **كل** قانون بالجسون كامل -
        بغض النظر عن أي سلسلة الـCSV حاطة العنصر فيها

أي عنصر ينلقى بـ[ب] وهو مصنَّف "أساسي مفقود" -> خطأ تصنيف (تعديل اتعامل
كأساسي). أي عنصر ينلقى بـ[ب] تحت أب غير اللي افترضته السلسلة -> خطأ سلسلة.
بالحالتين: **موجود فعلاً، ما تضيفه** - غير هيك بتصير نسخة مكررة بالجسون.

الاستخدام:
    python step8_global_recheck.py

يحتاج .env: CSV_FILE, JSON_FILE (الأصلي، مش الناتج المدموج!), OUTPUT_DIR, LOG_DIR

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

from lib_matching import (
    Candidate,
    build_pools,
    match_one,
    normalize_arabic_name,
    normalize_number,
    normalize_year,
)

__version__ = "1.0.0"


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"step8_recheck_{ts}.log"
    logger = logging.getLogger("step8_recheck")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fh = logging.FileHandler(log_file, encoding="utf-8")
    ch = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fmt); ch.setFormatter(fmt)
    logger.addHandler(fh); logger.addHandler(ch)
    logger.info(f"بدء التشغيل - step8_global_recheck v{__version__}")
    logger.info(f"ملف اللوج: {log_file}")
    return logger


def find_latest(output_dir: Path, pattern: str, logger: logging.Logger) -> Path:
    files = sorted(glob.glob(str(output_dir / pattern)))
    if not files:
        raise FileNotFoundError(f"ما لقيت أي ملف يطابق {pattern} بمجلد {output_dir}")
    latest = Path(files[-1])
    logger.info(f"آخر ملف {pattern}: {latest.name} (من أصل {len(files)})")
    return latest


def build_base_pool(json_entries: list) -> list:
    cands = []
    for i, e in enumerate(json_entries):
        cands.append(Candidate(
            ref_id=f"top:{i}",
            number=normalize_number(e.get("Leg_Number")),
            year=normalize_year(e.get("Year")),
            name_norm=normalize_arabic_name(e.get("Leg_Name")),
            display_name=e.get("Leg_Name", ""),
            magazine_number=normalize_number(e.get("Magazine_Number")),
            magazine_page=normalize_number(e.get("Magazine_Page")),
        ))
    return cands


def build_global_amendment_pool(json_entries: list) -> tuple:
    """يرجّع (candidates, parent_lookup) - parent_lookup[ref_id] = اسم القانون
    الأب الحقيقي بالجسون، حتى نقدر نبلّغ أحمد وين بالضبط لقينا العنصر."""
    cands = []
    parent_lookup = {}
    for i, entry in enumerate(json_entries):
        parent_name = entry.get("Leg_Name", "")
        for j, mod in enumerate(entry.get("Mod_Legs") or []):
            ref_id = f"mod:{i}:{j}"
            cands.append(Candidate(
                ref_id=ref_id,
                number=normalize_number(mod.get("Leg_Number")),
                year=normalize_year(mod.get("Year")),
                name_norm=normalize_arabic_name(mod.get("Leg_Name")),
                display_name=mod.get("Leg_Name", ""),
                magazine_number=normalize_number(mod.get("Magazine_Number")),
                magazine_page=normalize_number(mod.get("Magazine_Page")),
            ))
            parent_lookup[ref_id] = parent_name
    return cands, parent_lookup


def check_one(csv_row: dict, pool_num_year: dict, pool_year: dict) -> dict:
    number = normalize_number(csv_row.get("Law_Number"))
    year = normalize_year(csv_row.get("Year"))
    name_norm = normalize_arabic_name(csv_row.get("Law_Name"))
    mag_num = normalize_number(csv_row.get("Magazine_Number"))
    mag_page = normalize_number(csv_row.get("Magazine_Page_Number"))
    result = match_one(number, year, name_norm, mag_num, mag_page, pool_num_year, pool_year)
    return {
        "matched": result.matched, "tier": result.tier, "score": round(result.score, 3),
        "needs_review": result.needs_review, "candidate_id": result.candidate_id,
        "candidate_name": result.candidate_name,
    }


def main():
    load_dotenv()
    csv_path = Path(os.environ["CSV_FILE"])
    json_path = Path(os.environ["JSON_FILE"])
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output"))
    log_dir = Path(os.environ.get("LOG_DIR", "logs"))
    logger = setup_logging(log_dir)

    merge_plan_path = find_latest(output_dir, "merge_plan_*.json", logger)
    with open(merge_plan_path, "r", encoding="utf-8") as f:
        merge_plan = json.load(f)

    base_ids = [item["base_pmk_ID"] for item in merge_plan["add_new_top_level"]]
    amend_ids = []
    for item in merge_plan["add_new_top_level"]:
        amend_ids.extend(item["amendment_pmk_IDs"])
    for item in merge_plan["extend_existing"]:
        amend_ids.extend(item["amendment_pmk_IDs"])
    logger.info(f"من merge_plan: {len(base_ids)} أساسي مفقود، {len(amend_ids)} تعديل مفقود")

    csv_df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    csv_by_pmk = {row["pmk_ID"]: row.to_dict() for _, row in csv_df.iterrows()}

    logger.info(f"تحميل JSON الأصلي: {json_path} (ملف كبير، ممكن ياخذ وقت)")
    with open(json_path, "r", encoding="utf-8-sig") as f:
        json_entries = json.load(f)
    logger.info(f"تم تحميل {len(json_entries)} عنصر أساسي")

    base_pool = build_base_pool(json_entries)
    base_pool_num_year, base_pool_year = build_pools(base_pool)

    amend_pool, parent_lookup = build_global_amendment_pool(json_entries)
    amend_pool_num_year, amend_pool_year = build_pools(amend_pool)
    logger.info(f"مجمّع التعديلات الشامل: {len(amend_pool)} تعديل من كل الجسون")

    rows = []
    false_negatives = 0

    for pmk in base_ids:
        csv_row = csv_by_pmk.get(pmk)
        if csv_row is None:
            logger.error(f"pmk_ID={pmk} (أساسي) مو موجود بالـCSV!")
            continue
        r_top = check_one(csv_row, base_pool_num_year, base_pool_year)
        r_amend = check_one(csv_row, amend_pool_num_year, amend_pool_year)
        found_as_amendment = r_amend["matched"]
        if found_as_amendment:
            false_negatives += 1
        rows.append({
            "pmk_ID": pmk, "نوع_CSV": "أساسي", "الاسم": csv_row.get("Law_Name"),
            "الرقم": csv_row.get("Law_Number"), "السنة": csv_row.get("Year"),
            "موجود_كأساسي_بالجسون": r_top["matched"],
            "موجود_كتعديل_بمكان_ما": found_as_amendment,
            "الأب_الحقيقي_لو_انلقى": parent_lookup.get(r_amend["candidate_id"], "") if found_as_amendment else "",
            "طبقة_المطابقة": r_amend["tier"] if found_as_amendment else r_top["tier"],
            "درجة_التشابه": r_amend["score"] if found_as_amendment else r_top["score"],
            "يحتاج_تأكيد_يدوي": r_amend["needs_review"] if found_as_amendment else False,
            "الخلاصة": "موجود فعلاً - لا تضيفه (تعديل اتصنّف أساسي غلط)" if found_as_amendment
                       else "مفقود فعلاً - أضفه",
        })

    for pmk in amend_ids:
        csv_row = csv_by_pmk.get(pmk)
        if csv_row is None:
            logger.error(f"pmk_ID={pmk} (تعديل) مو موجود بالـCSV!")
            continue
        r_amend = check_one(csv_row, amend_pool_num_year, amend_pool_year)
        found = r_amend["matched"]
        if found:
            false_negatives += 1
        rows.append({
            "pmk_ID": pmk, "نوع_CSV": "تعديل", "الاسم": csv_row.get("Law_Name"),
            "الرقم": csv_row.get("Law_Number"), "السنة": csv_row.get("Year"),
            "موجود_كأساسي_بالجسون": False,
            "موجود_كتعديل_بمكان_ما": found,
            "الأب_الحقيقي_لو_انلقى": parent_lookup.get(r_amend["candidate_id"], "") if found else "",
            "طبقة_المطابقة": r_amend["tier"],
            "درجة_التشابه": r_amend["score"],
            "يحتاج_تأكيد_يدوي": r_amend["needs_review"],
            "الخلاصة": "موجود فعلاً - لا تضيفه (كان بسلسلة/أب غلط بالـCSV)" if found
                       else "مفقود فعلاً - أضفه",
        })

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"global_recheck_{ts}.csv"
    pd.DataFrame(rows).to_csv(out_path, index=False, encoding="utf-8-sig")

    logger.info("=== ملخص ===")
    logger.info(f"إجمالي فُحص: {len(rows)}")
    logger.info(f"لقيناهم موجودين فعلاً بمكان تاني (false negatives): {false_negatives}")
    logger.info(f"مؤكدين مفقودين فعلاً: {len(rows) - false_negatives}")
    logger.info(f"التقرير الكامل: {out_path}")


if __name__ == "__main__":
    main()
