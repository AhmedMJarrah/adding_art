# -*- coding: utf-8 -*-
"""
step9_build_corrected_plan.py
================================
يبني خطة دمج مصححة (merge_plan جديد) بعد اكتشاف مشكلة بنية السلاسل
بالـCSV (راجع المحادثة - تعديلات معاملة كأساسي مستقل، أو محطوطة بسلسلة
غلط). يعيد نفس فحص step8 (شامل، ضد كل الجسون الأصلي)، بس هالمرة بيبني
خطة دمج جديدة صحيحة بدل ما يكتفي بتقرير - وبيطبّق كمان 4 تصحيحات يدوية
من مراجعة فعلية لحالات كانت بثقة واطئة (راجع MANUAL_OVERRIDE تحت).

المنطق:
    - أي "قانون أساسي" بالخطة القديمة طلع فعلياً موجود كتعديل بمكان تاني
      -> يُستثنى تماماً (موجود أصلاً)، وأي تعديلات كانت معلَّقة عليه
      (بالخطة القديمة) تُعاد فحصها لحالها وتُلحق بمكانها الصحيح.
    - أي "تعديل" بالخطة القديمة (سواء ضمن سلسلة جديدة أو ملحق بقانون
      موجود) طلع موجود فعلاً بمكان تاني -> يُستثنى، ولا يُضاف بأي مكان
      (موجود بمحتواه الكامل أصلاً).
    - الباقي (مؤكد مفقود فعلاً) يدخل الخطة الجديدة بمكانه الصحيح.

الناتج يُسمّى merge_plan_<تاريخ أحدث> حتى step3_merge.py ياخذه تلقائياً
كآخر نسخة - ما يحتاج أي تعديل على step3 نفسه. **شغّل step3 بعدها ضد
الجسون الأصلي (RefLaws_v05_CorrMetaVol.json) مش الناتج المدموج القديم.**

الاستخدام:
    python step9_build_corrected_plan.py

يحتاج .env: CSV_FILE, JSON_FILE (الأصلي), OUTPUT_DIR, LOG_DIR

النسخة: 1.0.0 - 2026-09-06
"""

from __future__ import annotations

import glob
import json
import logging
import os
import sys
from collections import defaultdict
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

# مراجعة يدوية فعلية (2026-09-06) لـ6 حالات "موجودة" بثقة واطئة من تقرير
# step8 - قريت كل حالة وحكمت على الموضوع الفعلي مش بس درجة التشابه:
MANUAL_STILL_MISSING = {
    "6130",  # ذيل ضريبة الدخل != قانون التعدين (موضوع مختلف كلياً وسنة مختلفة)
    "2904",  # تسوية الاراضي != ضريبة الاراضي (تسجيل ملكية مقابل ضريبة - موضوعين مختلفين)
    "1627",  # نفس فخ "تسوية" مقابل "ضريبة" الاراضي
    "2661",  # اسم "تنفيذ قانون" فاضي من أي تفصيل مميّز - ما نقدر نأكد الربط
}
# (704 و2502 من نفس الدفعة راجعتهم ولقيتهم صحيحين - تركتهم على حالهم "موجودين")


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"step9_corrected_plan_{ts}.log"
    logger = logging.getLogger("step9_corrected_plan")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fh = logging.FileHandler(log_file, encoding="utf-8")
    ch = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fmt); ch.setFormatter(fmt)
    logger.addHandler(fh); logger.addHandler(ch)
    logger.info(f"بدء التشغيل - step9_build_corrected_plan v{__version__}")
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


def build_global_amendment_pool(json_entries: list) -> list:
    cands = []
    for i, entry in enumerate(json_entries):
        for j, mod in enumerate(entry.get("Mod_Legs") or []):
            cands.append(Candidate(
                ref_id=f"mod:{i}:{j}",
                number=normalize_number(mod.get("Leg_Number")),
                year=normalize_year(mod.get("Year")),
                name_norm=normalize_arabic_name(mod.get("Leg_Name")),
                display_name=mod.get("Leg_Name", ""),
                magazine_number=normalize_number(mod.get("Magazine_Number")),
                magazine_page=normalize_number(mod.get("Magazine_Page")),
            ))
    return cands


def recheck(pmk_id: str, csv_row: dict, pool_num_year: dict, pool_year: dict):
    if pmk_id in MANUAL_STILL_MISSING:
        return None  # None = "مؤكد مفقود يدوياً" - ما نحتاج حتى نجرب المطابقة
    number = normalize_number(csv_row.get("Law_Number"))
    year = normalize_year(csv_row.get("Year"))
    name_norm = normalize_arabic_name(csv_row.get("Law_Name"))
    mag_num = normalize_number(csv_row.get("Magazine_Number"))
    mag_page = normalize_number(csv_row.get("Magazine_Page_Number"))
    result = match_one(number, year, name_norm, mag_num, mag_page, pool_num_year, pool_year)
    return result if result.matched else None


def top_index_from_ref(ref_id: str) -> int:
    return int(ref_id.split(":")[1])


def main():
    load_dotenv()
    csv_path = Path(os.environ["CSV_FILE"])
    json_path = Path(os.environ["JSON_FILE"])
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output"))
    log_dir = Path(os.environ.get("LOG_DIR", "logs"))
    logger = setup_logging(log_dir)

    old_plan_path = find_latest(output_dir, "merge_plan_*.json", logger)
    with open(old_plan_path, "r", encoding="utf-8") as f:
        old_plan = json.load(f)

    csv_df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    csv_by_pmk = {row["pmk_ID"]: row.to_dict() for _, row in csv_df.iterrows()}

    logger.info(f"تحميل JSON الأصلي: {json_path}")
    with open(json_path, "r", encoding="utf-8-sig") as f:
        json_entries = json.load(f)
    logger.info(f"تم تحميل {len(json_entries)} عنصر أساسي")

    base_pool = build_base_pool(json_entries)
    base_pool_num_year, base_pool_year = build_pools(base_pool)
    amend_pool = build_global_amendment_pool(json_entries)
    amend_pool_num_year, amend_pool_year = build_pools(amend_pool)
    logger.info(f"مجمّع التعديلات الشامل: {len(amend_pool)} تعديل")

    new_add_new_top_level = []
    new_extend = defaultdict(list)
    stats = defaultdict(int)

    def recheck_amendment(pmk):
        row = csv_by_pmk.get(pmk)
        if row is None:
            logger.error(f"pmk_ID={pmk} مو موجود بالـCSV - استثني")
            return "csv_missing", None
        r = recheck(pmk, row, amend_pool_num_year, amend_pool_year)
        if r is None:
            return "missing", None
        return "found", top_index_from_ref(r.candidate_id)

    for item in old_plan["add_new_top_level"]:
        base_pmk = item["base_pmk_ID"]
        base_row = csv_by_pmk.get(base_pmk)
        if base_row is None:
            logger.error(f"pmk_ID={base_pmk} (أساسي) مو موجود بالـCSV - استثني")
            continue

        base_result = recheck(base_pmk, base_row, amend_pool_num_year, amend_pool_year)

        if base_result is None:
            # لسا مؤكد مفقود كقانون مستقل - نحتفظ فيه، ونصفّي أولاده
            still_missing_kids = []
            for amend_pmk in item["amendment_pmk_IDs"]:
                status, idx = recheck_amendment(amend_pmk)
                if status == "missing":
                    still_missing_kids.append(amend_pmk)
                    stats["amendments_kept_under_new_base"] += 1
                elif status == "found":
                    # موجود فعلاً بمكان تانِ بالجسون - نستثنيه تماماً، ما نضيفه
                    # بأي مكان (إعادة إضافته حتى بمكانه "الصحيح" بتصير تكرار
                    # لمحتوى موجود أصلاً).
                    stats["amendments_excluded_duplicate"] += 1
                    logger.info(f"تعديل pmk_ID={amend_pmk} موجود فعلاً بمكان تانِ بالجسون - استُثني")
            new_add_new_top_level.append({"base_pmk_ID": base_pmk, "amendment_pmk_IDs": still_missing_kids})
            stats["base_kept"] += 1
        else:
            # "الأساسي" هذا فعلياً تعديل موجود بمكان تانِ - نستثنيه كلياً
            true_parent_idx = top_index_from_ref(base_result.candidate_id)
            stats["base_excluded_duplicate"] += 1
            logger.info(
                f"pmk_ID={base_pmk} ('{base_row.get('Law_Name','')[:50]}...') كان مخطط "
                f"يُضاف كقانون جديد - لقيته فعلياً تعديل موجود جوا "
                f"'{base_result.candidate_name[:50]}...' - استثنيته"
            )
            # أولاده (لو معندهوش) نتحقق منهم لحالهم - لو لسا مفقودين فعلياً،
            # مكانهم الصحيح المنطقي صار جوا نفس الأب الحقيقي يلي انلقى فيه
            # "الأساسي" المزيف (مش تحته هو، لأنه أصلاً مو أب حقيقي).
            for amend_pmk in item["amendment_pmk_IDs"]:
                status, idx = recheck_amendment(amend_pmk)
                if status == "missing":
                    new_extend[true_parent_idx].append(amend_pmk)
                    stats["amendments_reattached"] += 1
                elif status == "found":
                    stats["amendments_excluded_duplicate"] += 1
                    logger.info(f"تعديل pmk_ID={amend_pmk} موجود فعلاً بمكان تانِ بالجسون - استُثني")

    for item in old_plan["extend_existing"]:
        json_index = item["json_index"]
        for amend_pmk in item["amendment_pmk_IDs"]:
            status, idx = recheck_amendment(amend_pmk)
            if status == "missing":
                new_extend[json_index].append(amend_pmk)
                stats["amendments_kept_existing_extend"] += 1
            elif status == "found":
                # موجود فعلاً بمكان تانِ (أو حتى بنفس المكان يلي كنا رح نضيفه
                # فيه) - بالحالتين محتواه موجود أصلاً، نستثنيه تماماً.
                stats["amendments_excluded_duplicate"] += 1
                note = "بنفس القانون المخطط له" if idx == json_index else "بقانون مختلف عن المخطط (سلسلة كانت غلط)"
                logger.info(f"تعديل pmk_ID={amend_pmk} موجود فعلاً بالجسون ({note}) - استُثني")

    corrected_plan = {
        "add_new_top_level": new_add_new_top_level,
        "extend_existing": [
            {"json_index": idx, "matched_json_name": json_entries[idx].get("Leg_Name", ""), "amendment_pmk_IDs": ids}
            for idx, ids in new_extend.items()
        ],
    }

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"merge_plan_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(corrected_plan, f, ensure_ascii=False, indent=2)

    total_base = len(new_add_new_top_level)
    total_amend = sum(len(item["amendment_pmk_IDs"]) for item in corrected_plan["add_new_top_level"]) + \
                  sum(len(item["amendment_pmk_IDs"]) for item in corrected_plan["extend_existing"])

    logger.info("=== ملخص ===")
    logger.info(f"قوانين أساسية بقيت (مؤكد مفقودة): {stats['base_kept']}")
    logger.info(f"قوانين أساسية استُثنيت (تكرار مكتشف): {stats['base_excluded_duplicate']}")
    logger.info(f"تعديلات استُثنيت (تكرار مكتشف): {stats['amendments_excluded_duplicate']}")
    logger.info(f"تعديلات أُعيد إلحاقها بمكانها الصحيح (كان أبوها مزيّف): {stats['amendments_reattached']}")
    logger.info(f"إجمالي الخطة المصححة: {total_base} أساسي + {total_amend} تعديل = {total_base + total_amend}")
    logger.info(f"خطة الدمج المصححة: {out_path}")
    logger.info("=" * 60)
    logger.info("الخطوة الجاية: شغّل step3_merge.py **ضد الجسون الأصلي** (تأكد")
    logger.info("JSON_FILE بالـ.env لسا مؤشر على RefLaws_v05_CorrMetaVol.json)")
    logger.info("حتى يستخدم هالخطة المصححة بدل القديمة.")


if __name__ == "__main__":
    main()
