# -*- coding: utf-8 -*-
"""
step11_verify_zero_articles.py
==============================
سكربت تشخيصي (قراءة فقط - ما بيكتب ولا ملف مخرجات، بس لوج).

الهدف:
    إعادة فحص كل pmk_ID طلع بـzero_articles (ما انستخرجت إله مواد من قاعدة
    الديوان) مقابل الجسون الأصلي، باستخدام lib_matching v1.6.0 الحالي،
    و**بدون** أي تجاوز يدوي (MANUAL_STILL_MISSING). السبب:

    - قائمة MANUAL_STILL_MISSING بـstep9 بتعمل short-circuit قبل المطابقة
      (`if pmk_id in MANUAL_STILL_MISSING: return None`)، يعني هالعناصر
      **ما انفحصت إطلاقاً** بعد إصلاح Tier 2 (v1.6.0). قراراتها اتخذت
      بكود أقدم.
    - فحص ضد المجمّعين (أساسي + تعديلات) لكل عنصر، بغض النظر عن نوعه
      المفترض بالـCSV، لأن بنية السلاسل بالـCSV غير موثوقة.

الناتج: تقرير مفصّل باللوج فيه لكل عنصر:
    نتيجة المطابقة بمجمّع القوانين الأساسية، ونتيجتها بمجمّع التعديلات،
    وكل المرشحين الخام (نفس الرقم+السنة / نفس السنة+رقم الجريدة / أعلى
    تشابه بنفس السنة) مع درجاتهم - حتى نحكم على المحتوى مش على درجة لحالها.

الاستخدام:
    python step11_verify_zero_articles.py
    python step11_verify_zero_articles.py --zero-file output\\zero_articles_20260907_132256.json
    python step11_verify_zero_articles.py --pmk 4350 --pmk 6130

يحتاج .env: JSON_FILE (الجسون **الأصلي**), CSV_FILE, OUTPUT_DIR, LOG_DIR

النسخة: 1.0.0 - 2026-09-08
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

from lib_matching import (
    Candidate,
    MatchResult,
    build_pools,
    content_similarity,
    match_one,
    normalize_arabic_name,
    normalize_number,
    normalize_year,
)

__version__ = "1.0.0"

# علامات نصية معروفة بتدل إن الصف جاي من "استرجاع المحررين" مش من قاعدة
# الديوان - بندوّر عنها بكل أعمدة الصف بدل ما نفترض اسم عمود معيّن.
RECOVERY_MARKERS = (
    "مضاف من ملف المحررين",
    "مسترجَع من عمل الفريق السابق",
    "مسترجع من عمل الفريق السابق",
    "name_only",
)

TOP_N_SIMILAR = 5


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"step11_verify_zero_articles_{ts}.log"
    logger = logging.getLogger("step11_verify_zero_articles")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    logger.info(f"بدء التشغيل - step11_verify_zero_articles v{__version__}")
    logger.info(f"ملف اللوج: {log_file}")
    return logger


def find_latest(output_dir: Path, pattern: str, logger: logging.Logger) -> Path:
    files = sorted(glob.glob(str(output_dir / pattern)))
    if not files:
        raise FileNotFoundError(f"ما لقيت أي ملف يطابق {pattern} بمجلد {output_dir}")
    latest = Path(files[-1])
    logger.info(f"آخر ملف {pattern}: {latest.name} (من أصل {len(files)})")
    return latest


def build_base_pool(json_entries: list) -> list[Candidate]:
    return [
        Candidate(
            ref_id=f"top:{i}",
            number=normalize_number(e.get("Leg_Number")),
            year=normalize_year(e.get("Year")),
            name_norm=normalize_arabic_name(e.get("Leg_Name")),
            display_name=e.get("Leg_Name", "") or "",
            magazine_number=normalize_number(e.get("Magazine_Number")),
            magazine_page=normalize_number(e.get("Magazine_Page")),
        )
        for i, e in enumerate(json_entries)
    ]


def build_amendment_pool(json_entries: list) -> list[Candidate]:
    cands: list[Candidate] = []
    for i, entry in enumerate(json_entries):
        for j, mod in enumerate(entry.get("Mod_Legs") or []):
            cands.append(Candidate(
                ref_id=f"mod:{i}:{j}",
                number=normalize_number(mod.get("Leg_Number")),
                year=normalize_year(mod.get("Year")),
                name_norm=normalize_arabic_name(mod.get("Leg_Name")),
                display_name=mod.get("Leg_Name", "") or "",
                magazine_number=normalize_number(mod.get("Magazine_Number")),
                magazine_page=normalize_number(mod.get("Magazine_Page")),
            ))
    return cands


def describe_result(result: MatchResult) -> str:
    if not result.matched:
        return (f"لا مطابقة | tier={result.tier} | score={result.score:.3f} | "
                f"ambiguous={result.ambiguous} | {result.note or 'ماكو ملاحظة'}")
    return (f"مطابقة ✔ | tier={result.tier} | score={result.score:.3f} | "
            f"needs_review={result.needs_review} | ref={result.candidate_id} | "
            f"'{result.candidate_name}' | {result.note or '-'}")


def dump_candidates(logger: logging.Logger, label: str, name_norm: str,
                    number: Optional[str], year: Optional[str],
                    magazine_number: Optional[str],
                    pool_by_num_year: dict, pool_by_year: dict) -> None:
    """يطبع المرشحين الخام حتى نحكم على المحتوى الفعلي مش على درجة لحالها."""
    logger.info(f"  --- مرشحو {label} ---")

    exact = pool_by_num_year.get((number, year), []) if number and year else []
    if exact:
        logger.info(f"  [نفس الرقم+السنة] {len(exact)} مرشح:")
        for c in exact:
            sim = content_similarity(name_norm, c.name_norm)
            logger.info(f"      {sim:.3f} | {c.ref_id} | جريدة={c.magazine_number} | {c.display_name}")
    else:
        logger.info("  [نفس الرقم+السنة] لا يوجد")

    year_pool = pool_by_year.get(year, []) if year else []
    if magazine_number:
        mag = [c for c in year_pool if c.magazine_number == magazine_number]
        if mag:
            logger.info(f"  [نفس السنة+رقم الجريدة {magazine_number}] {len(mag)} مرشح:")
            for sim, c in sorted(((content_similarity(name_norm, c.name_norm), c) for c in mag),
                                 key=lambda x: x[0], reverse=True):
                logger.info(f"      {sim:.3f} | {c.ref_id} | صفحة={c.magazine_page} | {c.display_name}")
        else:
            logger.info(f"  [نفس السنة+رقم الجريدة {magazine_number}] لا يوجد")

    if year_pool:
        top = sorted(((content_similarity(name_norm, c.name_norm), c) for c in year_pool),
                     key=lambda x: x[0], reverse=True)[:TOP_N_SIMILAR]
        logger.info(f"  [أعلى {len(top)} تشابه بنفس السنة {year}] من أصل {len(year_pool)} مرشح:")
        for sim, c in top:
            logger.info(f"      {sim:.3f} | {c.ref_id} | رقم={c.number} | جريدة={c.magazine_number} | {c.display_name}")
    else:
        logger.info(f"  [نفس السنة {year}] لا يوجد أي مرشح بالجسون")


def recovery_flags(row: dict) -> list[str]:
    found = []
    for col, val in row.items():
        text = str(val)
        for marker in RECOVERY_MARKERS:
            if marker in text:
                found.append(f"{col}={text.strip()[:60]}")
                break
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="إعادة فحص عناصر بدون مواد مستخرجة")
    parser.add_argument("--zero-file", type=str, default=None,
                        help="مسار ملف zero_articles (افتراضياً آخر واحد بمجلد المخرجات)")
    parser.add_argument("--pmk", action="append", default=None,
                        help="فحص pmk_ID محدد (ممكن تكرارها) بدل ملف zero_articles")
    args = parser.parse_args()

    load_dotenv()
    csv_path = Path(os.environ["CSV_FILE"])
    json_path = Path(os.environ["JSON_FILE"])
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output"))
    log_dir = Path(os.environ.get("LOG_DIR", "logs"))
    logger = setup_logging(log_dir)

    if args.pmk:
        pmk_ids = [str(p) for p in args.pmk]
        logger.info(f"فحص يدوي لـ{len(pmk_ids)} pmk_ID من سطر الأوامر")
    else:
        zero_path = Path(args.zero_file) if args.zero_file else find_latest(output_dir, "zero_articles_*.json", logger)
        with open(zero_path, "r", encoding="utf-8") as f:
            pmk_ids = [str(p) for p in json.load(f)]
        logger.info(f"عدد العناصر بدون مواد: {len(pmk_ids)}")

    logger.info(f"تحميل CSV: {csv_path}")
    csv_df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    csv_by_pmk = {str(row["pmk_ID"]).strip(): row.to_dict() for _, row in csv_df.iterrows()}
    logger.info(f"صفوف CSV: {len(csv_by_pmk)}")

    logger.info(f"تحميل الجسون الأصلي: {json_path}")
    with open(json_path, "r", encoding="utf-8-sig") as f:
        json_entries = json.load(f)
    logger.info(f"عناصر أساسية بالجسون: {len(json_entries)}")
    if len(json_entries) != 2161:
        logger.warning(
            f"⚠ عدد العناصر {len(json_entries)} مش 2161 - متأكد إن JSON_FILE مؤشر "
            f"على الجسون **الأصلي** مش على ناتج مدموج؟"
        )

    base_pool = build_base_pool(json_entries)
    base_num_year, base_year = build_pools(base_pool)
    amend_pool = build_amendment_pool(json_entries)
    amend_num_year, amend_year = build_pools(amend_pool)
    logger.info(f"مجمّع أساسي: {len(base_pool)} | مجمّع تعديلات: {len(amend_pool)}")

    summary: list[tuple[str, str]] = []

    for pmk in pmk_ids:
        logger.info("=" * 78)
        row = csv_by_pmk.get(pmk)
        if row is None:
            logger.error(f"pmk_ID={pmk} مو موجود بالـCSV")
            summary.append((pmk, "غير موجود بالـCSV"))
            continue

        number = normalize_number(row.get("Law_Number"))
        year = normalize_year(row.get("Year"))
        raw_name = row.get("Law_Name", "") or ""
        name_norm = normalize_arabic_name(raw_name)
        mag_num = normalize_number(row.get("Magazine_Number"))
        mag_page = normalize_number(row.get("Magazine_Page_Number"))

        logger.info(f"pmk_ID={pmk} | رقم={number} | سنة={year} | جريدة={mag_num} صفحة={mag_page}")
        logger.info(f"  الاسم بالـCSV: '{raw_name}'")
        logger.info(f"  بعد التطبيع : '{name_norm}'")
        flags = recovery_flags(row)
        if flags:
            logger.info(f"  ⚑ صف مسترجَع (مش من قاعدة الديوان): {' | '.join(flags)}")

        res_base = match_one(number, year, name_norm, mag_num, mag_page, base_num_year, base_year)
        res_amend = match_one(number, year, name_norm, mag_num, mag_page, amend_num_year, amend_year)
        logger.info(f"  نتيجة مجمّع الأساسي  : {describe_result(res_base)}")
        logger.info(f"  نتيجة مجمّع التعديلات: {describe_result(res_amend)}")

        dump_candidates(logger, "الأساسي", name_norm, number, year, mag_num, base_num_year, base_year)
        dump_candidates(logger, "التعديلات", name_norm, number, year, mag_num, amend_num_year, amend_year)

        if res_base.matched or res_amend.matched:
            # ما نفضّل مجمّع على التاني بشكل ثابت - المجمّعين ممكن يرجعوا
            # مطابقة، والأصح ناخذ الأعلى تشابه محتوى (ظهرت هالحالة بالاختبار:
            # المجمّع الأساسي رجّع 0.667 والتعديلات رجّعت 1.000 لنفس السجل).
            if res_base.matched and res_amend.matched:
                where = "أساسي" if res_base.score >= res_amend.score else "تعديل"
                best = max(res_base.score, res_amend.score)
                verdict = f"مطابقة محتملة بمجمّع {where} (المجمّعان رجّعا مطابقة، الأعلى {best:.3f})"
            else:
                res = res_base if res_base.matched else res_amend
                where = "أساسي" if res_base.matched else "تعديل"
                verdict = f"مطابقة محتملة بمجمّع {where} ({res.score:.3f})"
        elif res_base.ambiguous or res_amend.ambiguous:
            verdict = "تعارض/غموض - يحتاج حكم بشري"
        else:
            verdict = "لا مرشح إطلاقاً - مفقود فعلاً"
        summary.append((pmk, verdict))

    logger.info("=" * 78)
    logger.info("=== ملخص ===")
    for pmk, verdict in summary:
        logger.info(f"  {pmk:>6} : {verdict}")
    logger.info(f"إجمالي: {len(summary)} عنصر")
    logger.info("تنبيه: الملخص مؤشر أولي فقط - الحكم النهائي لازم يكون بقراءة "
                "موضوع القانون الفعلي بالمرشحين أعلاه، مش بدرجة التشابه لحالها.")


if __name__ == "__main__":
    main()
