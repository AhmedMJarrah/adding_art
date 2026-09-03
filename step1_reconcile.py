# -*- coding: utf-8 -*-
"""
step1_reconcile.py
===================
الخطوة 1 من مشروع "insert": مقارنة ملف الـJSON (RefLaws) مع ملف الـCSV
المرجعي الكامل (98% دقة) لتحديد بالضبط:

    - FULLY_MISSING  : سلسلة (قانون أساسي + تعديلاته) مفقودة بالكامل من الـJSON.
    - PARTIAL_MISSING: القانون الأساسي موجود بالـJSON، بس ناقصه تعديل واحد أو أكثر.
    - COMPLETE       : كل شي بالسلسلة موجود.
    - حالات تعارض/غموض بالمطابقة تُسجَّل بتقرير منفصل للمراجعة اليدوية.

هالسكريبت للقراءة فقط - ما بيعدّل الـJSON ولا يتصل بأي قاعدة بيانات.
مخرجاته (بمجلد output/):
    missing_report_<ts>.csv     -> صف لكل سلسلة CSV مع حالتها وتفاصيل المطابقة
    ambiguous_report_<ts>.csv   -> الحالات اللي تحتاج مراجعة يدوية (لو وجدت)
    missing_pmk_ids_<ts>.json   -> قائمة pmk_ID المفقودة (أساسية/تعديلات) -
                                    هاي المدخل لخطوة استخراج المواد من قاعدة
                                    بيانات الديوان.

الاستخدام:
    python step1_reconcile.py

المتطلبات (requirements.txt):
    pandas
    python-dotenv

يحتاج ملف .env فيه:
    CSV_FILE=...
    JSON_FILE=...
    (اختياري) OUTPUT_DIR=output
    (اختياري) LOG_DIR=logs

النسخة: 1.3.0 - 2026-09-02
    - إضافة merge_plan_<ts>.json: خطة دمج جاهزة لـstep3 (add_new_top_level +
      extend_existing مع فهرس JSON فعلي لكل حالة) بدل ما step3 يعيد المطابقة
      من الصفر بالاسم (هش) - يستخدم نفس نتيجة المطابقة الحية من هالتشغيلة.

النسخة: 1.2.0 - 2026-09-02
    - إضافة مراجعة يدوية كاملة لـ297 حالة (بعد قراءة الموضوع الفعلي مو بس
      درجة تشابه الاسم): 3 تصحيحات "موجود غلط اتصنّف مفقود" و16 تصحيح
      "مفقود غلط اتصنّف موجود" (راجع MANUAL_OVERRIDE_* تحت).

النسخة: 1.1.0 - 2026-09-02
    - تقرير الحالات الغامضة صار فيه اسم/درجة التطابق (أو كل المرشحين
      المتنافسين مع رقم جريدتهم) - ما عاد تحتاج تقاطعه مع missing_report.

النسخة: 1.0.0 - 2026-09-02
"""

from __future__ import annotations

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
    MatchResult,
    build_pools,
    match_one,
    normalize_arabic_name,
    normalize_number,
    normalize_year,
)

__version__ = "1.3.0"

# ---------------------------------------------------------------------------
# قرارات اتفقنا عليها بالمحادثة (2026-09-02) - عدّلها هون لو تغيّر شي
# ---------------------------------------------------------------------------

# استثناء بالـpmk_ID: قانونين بالـCSV مسجّلين خطأ بسنة 1900، وهم أصلاً موجودين
# بالـJSON بسنتهم الصحيحة. تأكدت إنهن سلاسل مستقلة (صف وحيد لكل وحدة) فما
# في خطر نتيمة تعديلات مرتبطة فيهن.
EXCLUDED_PMK_IDS = {"8", "1489"}  # مجلة الاحكام العدلية / قانون الاراضي العثماني

# 5 صفوف بالـCSV عندها is_law=False (كلها "ملاحق" لقوانين موازنة). افتراضياً
# منضمّهم بالفحص لكن منعلّمهم بوضوح بالتقرير (عمود is_law) بدل ما نتجاهلهم
# بصمت. غيّرها لـFalse لو قررت تستثنيهم.
INCLUDE_NON_LAW_CHAINS = True

# مراجعة يدوية كاملة لـ297 حالة "تحتاج مراجعة" بتاريخ 2026-09-02 (بعد قراءة
# كل حالة والتأكد من الموضوع الفعلي، مو بس درجة تشابه الاسم):
#
# قوانين صنّفتها الخوارزمية "مفقودة" غلط - هي موجودة فعلاً بالـJSON بس
# بصياغة/تفصيل ما قدرت الخوارزمية تربطه (مرادف، جمع/مفرد، أو عنوان بلا
# كلمات مضمون أصلاً):
MANUAL_OVERRIDE_FOUND = {
    "1137",  # موظفي الحكومة 1939 - رقم الجريدة مطابق تماماً + نفس الموضوع
    "496",   # معاهدة جنيف = تنفيذ المعاهدات الدولية لتحسين حالة جرحى الجيوش (نفس المعاهدة، جمع/مفرد فوّت المطابقة)
    "4004",  # اسم مطابق حرفياً 100% بس بلا أي كلمة "مضمون" (عنوانه رقمي بحت) فسجّل تشابه صفر
}

# قوانين صنّفتها الخوارزمية "موجودة" غلط - نفس القالب اللغوي بس تفصيل مميّز
# مختلف (اسم شخص، رقم قانون، درجة إدارية، نوع ضريبة...الخ) فوّتته لأنه كلمة
# وحدة بالجملة:
MANUAL_OVERRIDE_MISSING = {
    "315",           # صندوق الملكة علياء != الصندوق الهاشمي للتنمية البشرية
    "367",           # جامعة الزرقاء != الجامعة الهاشمية (نفس الرقم 18/1992 صدفة)
    "13", "3715",    # راتب "ابراهيم زوار بك" != راتب "علي دهاج" (جنديين مختلفين)
    "200",           # راتب "احمد بن سعيد" != راتب "سليم بن دياب الكركي"
    "191",           # اتفاقية الصندوق الكويتي != اتفاقية بتروفينا البلجيكية
    "4300",          # الميزانية العامة != الميزانية الخاص الموقت
    "4350",          # حصة المصرف الزراعي من الضرائب != اعفاء بقايا الضرائب
    "5250",          # ذيل قانون الموظفين != ذيل قانون حقوق العائلة
    "5300",          # رسوم المحجر الصحي في معان != رسوم حمامات ماعين (معان != ماعين)
    "6088",          # ذيل التصرف بالاموال غير المنقولة != تعديل سرقة الحيوانات
    "1219",          # قانون السكة الحديدية (عام) != قانون سرقة مواد السكة الحديدية
    "3491",          # ملحق موازنة رقم 16/1984 != الموازنة العامة رقم 1/1984
    "6130",          # ذيل ضريبة الدخل != ذيل ضريبة الاراضي
    "6119",          # ذيل قانون التعدين != ذيل قانون المقالع
    "585",           # حاكمية درجة ثانية != حاكمية درجة ثالثة
}

# حالات ما قدرت تنحسم بثقة (اسم فاضي بالـCSV، أو تعارض حقيقي داخل الـJSON
# نفسه - نفس رقم الجريدة مكرر لأكثر من سجل). تُركت على وضعها الافتراضي
# (مفقودة - الخيار الآمن) عمداً، وهاي القائمة فقط للمتابعة لاحقاً لو حبيت:
# 103, 573 (اسم فاضي) | 237 (مو واضح) | 339, 4304, 4306, 4307, 5178 (تكرار
# رقم جريدة داخل الـJSON نفسه لسنة 1937) | 3182 (تصديق مقابل الغاء تصديق)


# ---------------------------------------------------------------------------
# تجهيز اللوج
# ---------------------------------------------------------------------------

def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"step1_reconcile_{ts}.log"

    logger = logging.getLogger("step1_reconcile")
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

    logger.info(f"بدء التشغيل - step1_reconcile v{__version__}")
    logger.info(f"ملف اللوج: {log_file}")
    return logger


# ---------------------------------------------------------------------------
# تحميل البيانات
# ---------------------------------------------------------------------------

def load_csv(csv_path: Path, logger: logging.Logger) -> pd.DataFrame:
    logger.info(f"تحميل CSV: {csv_path}")
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    logger.info(f"تم تحميل {len(df)} صف، {len(df.columns)} عمود")

    before = len(df)
    df = df[~df["pmk_ID"].isin(EXCLUDED_PMK_IDS)].copy()
    if before != len(df):
        logger.info(f"استُثني {before - len(df)} صف بالـpmk_ID: {sorted(EXCLUDED_PMK_IDS)}")

    non_law = df[df["is_law"] == "False"]
    if len(non_law):
        logger.warning(
            f"في {len(non_law)} صف is_law=False (ملاحق): pmk_ID="
            f"{list(non_law['pmk_ID'])} - "
            + ("رح تنضم بالفحص وتنعلّم بالتقرير" if INCLUDE_NON_LAW_CHAINS
               else "مستثناة حسب الإعداد الحالي INCLUDE_NON_LAW_CHAINS=False")
        )
        if not INCLUDE_NON_LAW_CHAINS:
            df = df[df["is_law"] != "False"].copy()

    return df


def load_json_entries(json_path: Path, logger: logging.Logger) -> list:
    logger.info(f"تحميل JSON: {json_path} (ملف كبير، ممكن ياخذ وقت)")
    t0 = datetime.now()
    with open(json_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    dt = (datetime.now() - t0).total_seconds()
    if not isinstance(data, list):
        raise ValueError(f"متوقع الجذر يكون list، طلع {type(data)}")
    logger.info(f"تم تحميل {len(data)} عنصر أساسي خلال {dt:.1f} ثانية")
    return data


# ---------------------------------------------------------------------------
# بناء المرشحين من الـJSON
# ---------------------------------------------------------------------------

def build_json_base_candidates(entries: list) -> list:
    """ref_id = index بالقائمة (مش الاسم) حتى ما ينلخبط لو تكرر اسمين."""
    cands = []
    for i, e in enumerate(entries):
        cands.append(Candidate(
            ref_id=str(i),
            number=normalize_number(e.get("Leg_Number")),
            year=normalize_year(e.get("Year")),
            name_norm=normalize_arabic_name(e.get("Leg_Name")),
            display_name=e.get("Leg_Name", ""),
            magazine_number=normalize_number(e.get("Magazine_Number")),
            magazine_page=normalize_number(e.get("Magazine_Page")),
        ))
    return cands


def build_json_amendment_candidates(entry: dict) -> list:
    cands = []
    for j, m in enumerate(entry.get("Mod_Legs") or []):
        cands.append(Candidate(
            ref_id=str(j),
            number=normalize_number(m.get("Leg_Number")),
            year=normalize_year(m.get("Year")),
            name_norm=normalize_arabic_name(m.get("Leg_Name")),
            display_name=m.get("Leg_Name", ""),
            magazine_number=normalize_number(m.get("Magazine_Number")),
            magazine_page=normalize_number(m.get("Magazine_Page")),
        ))
    return cands


# ---------------------------------------------------------------------------
# بناء سلاسل الـCSV
# ---------------------------------------------------------------------------

def build_csv_chains(df: pd.DataFrame) -> dict:
    """dict: chain_id -> {'base': row, 'amendments': [rows مرتبة حسب الموقع]}"""
    chains: dict = {}
    df = df.copy()
    df["_pos"] = df["chain_position_v2"].apply(
        lambda v: float(v) if v not in ("", None) else 0.0
    )
    for chain_id, g in df.groupby("chain_id_v2"):
        g = g.sort_values("_pos")
        rows = g.to_dict("records")
        chains[chain_id] = {"base": rows[0], "amendments": rows[1:]}
    return chains


# ---------------------------------------------------------------------------
# المنطق الرئيسي
# ---------------------------------------------------------------------------

def main():
    load_dotenv()
    csv_path = Path(os.environ["CSV_FILE"])
    json_path = Path(os.environ["JSON_FILE"])
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output"))
    log_dir = Path(os.environ.get("LOG_DIR", "logs"))
    output_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging(log_dir)

    df = load_csv(csv_path, logger)
    json_entries = load_json_entries(json_path, logger)

    logger.info("بناء فهرس المطابقة للقوانين الأساسية بالـJSON...")
    base_candidates = build_json_base_candidates(json_entries)
    base_pool_num_year, base_pool_year = build_pools(base_candidates)

    chains = build_csv_chains(df)
    logger.info(f"عدد السلاسل بالـCSV بعد الاستثناءات: {len(chains)}")

    report_rows = []
    ambiguous_rows = []
    missing_pmk_ids = {"base": [], "amendments": []}
    merge_plan = {"add_new_top_level": [], "extend_existing": []}
    stats = defaultdict(int)

    for chain_id, chain in chains.items():
        base = chain["base"]
        base_name_norm = normalize_arabic_name(base["Law_Name"])
        base_number = normalize_number(base["Law_Number"])
        base_year = normalize_year(base["Year"])
        base_mag_num = normalize_number(base["Magazine_Number"])
        base_mag_page = normalize_number(base["Magazine_Page_Number"])

        base_match = match_one(
            base_number, base_year, base_name_norm,
            base_mag_num, base_mag_page,
            base_pool_num_year, base_pool_year,
        )

        # تطبيق المراجعة اليدوية - يلغي قرار الخوارزمية للحالات المؤكدة يدوياً
        if base["pmk_ID"] in MANUAL_OVERRIDE_FOUND:
            base_match = MatchResult(matched=True, tier="MANUAL", score=1.0,
                                      candidate_name="(تأكيد يدوي - نفس القانون بصياغة مختلفة)")
        elif base["pmk_ID"] in MANUAL_OVERRIDE_MISSING:
            base_match = MatchResult(matched=False, tier="MANUAL", score=0.0,
                                      note="(تأكيد يدوي - قانون مختلف رغم تشابه القالب)")

        row = {
            "chain_id": chain_id,
            "base_pmk_ID": base["pmk_ID"],
            "base_Law_Name": base["Law_Name"],
            "base_Law_Number": base["Law_Number"],
            "base_Year": base["Year"],
            "is_law": base["is_law"],
            "n_amendments_csv": len(chain["amendments"]),
            "base_match_tier": base_match.tier,
            "base_match_score": round(base_match.score, 3),
            "base_matched_json_name": base_match.candidate_name,
            "missing_amendment_pmk_ids": "",
        }

        if base_match.ambiguous or base_match.needs_review:
            ambiguous_rows.append({
                "level": "base", "chain_id": chain_id,
                "pmk_ID": base["pmk_ID"], "Law_Name": base["Law_Name"],
                "Magazine_Number": base["Magazine_Number"],
                "match_tier": base_match.tier,
                "match_score": round(base_match.score, 3),
                "matched_or_competing_json_name": base_match.candidate_name,
                "reason": base_match.note,
            })

        if not base_match.matched:
            row["status"] = "FULLY_MISSING"
            missing_pmk_ids["base"].append(base["pmk_ID"])
            missing_pmk_ids["amendments"].extend(a["pmk_ID"] for a in chain["amendments"])
            stats["fully_missing"] += 1
            merge_plan["add_new_top_level"].append({
                "base_pmk_ID": base["pmk_ID"],
                "amendment_pmk_IDs": [a["pmk_ID"] for a in chain["amendments"]],
            })
        elif base_match.tier == "MANUAL":
            # تأكيد يدوي بدون فهرس JSON فعلي - ما نقدر نفحص تعديلاته آلياً،
            # نعتبرها مكتملة ونعلّم بلوج لو عندها تعديلات بالـCSV تحتاج مراجعة يدوية إضافية
            row["status"] = "COMPLETE"
            stats["complete"] += 1
            if chain["amendments"]:
                logger.warning(
                    f"تأكيد يدوي لـ pmk_ID={base['pmk_ID']} - عنده "
                    f"{len(chain['amendments'])} تعديل بالـCSV ما انفحصوا آلياً "
                    f"(راجعهم يدوياً): {[a['pmk_ID'] for a in chain['amendments']]}"
                )
        else:
            matched_entry = json_entries[int(base_match.candidate_id)]
            missing_amend_ids = []

            if chain["amendments"]:
                amend_candidates = build_json_amendment_candidates(matched_entry)
                amend_pool_num_year, amend_pool_year = build_pools(amend_candidates)

                for a in chain["amendments"]:
                    a_name_norm = normalize_arabic_name(a["Law_Name"])
                    a_number = normalize_number(a["Law_Number"])
                    a_year = normalize_year(a["Year"])
                    a_mag_num = normalize_number(a["Magazine_Number"])
                    a_mag_page = normalize_number(a["Magazine_Page_Number"])

                    a_match = match_one(
                        a_number, a_year, a_name_norm, a_mag_num, a_mag_page,
                        amend_pool_num_year, amend_pool_year,
                    )

                    if a_match.ambiguous or a_match.needs_review:
                        ambiguous_rows.append({
                            "level": "amendment", "chain_id": chain_id,
                            "pmk_ID": a["pmk_ID"], "Law_Name": a["Law_Name"],
                            "Magazine_Number": a["Magazine_Number"],
                            "match_tier": a_match.tier,
                            "match_score": round(a_match.score, 3),
                            "matched_or_competing_json_name": a_match.candidate_name,
                            "reason": a_match.note,
                        })

                    if not a_match.matched:
                        missing_amend_ids.append(a["pmk_ID"])
                        missing_pmk_ids["amendments"].append(a["pmk_ID"])

            row["missing_amendment_pmk_ids"] = ";".join(missing_amend_ids)
            if missing_amend_ids:
                row["status"] = "PARTIAL_MISSING"
                stats["partial_missing"] += 1
                merge_plan["extend_existing"].append({
                    "json_index": int(base_match.candidate_id),
                    "matched_json_name": base_match.candidate_name,
                    "amendment_pmk_IDs": missing_amend_ids,
                })
            else:
                row["status"] = "COMPLETE"
                stats["complete"] += 1

        report_rows.append(row)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    report_path = output_dir / f"missing_report_{ts}.csv"
    pd.DataFrame(report_rows).to_csv(report_path, index=False, encoding="utf-8-sig")
    logger.info(f"التقرير الرئيسي: {report_path}")

    if ambiguous_rows:
        amb_path = output_dir / f"ambiguous_report_{ts}.csv"
        pd.DataFrame(ambiguous_rows).to_csv(amb_path, index=False, encoding="utf-8-sig")
        logger.warning(f"{len(ambiguous_rows)} حالة تحتاج مراجعة يدوية -> {amb_path}")

    missing_ids_path = output_dir / f"missing_pmk_ids_{ts}.json"
    with open(missing_ids_path, "w", encoding="utf-8") as f:
        json.dump(missing_pmk_ids, f, ensure_ascii=False, indent=2)
    logger.info(f"قائمة الـpmk_ID المفقودة (مدخل الخطوة الجاية): {missing_ids_path}")

    merge_plan_path = output_dir / f"merge_plan_{ts}.json"
    with open(merge_plan_path, "w", encoding="utf-8") as f:
        json.dump(merge_plan, f, ensure_ascii=False, indent=2)
    logger.info(
        f"خطة الدمج (مدخل step3_merge.py): {merge_plan_path} - "
        f"{len(merge_plan['add_new_top_level'])} سجل جديد بمستوى أعلى، "
        f"{len(merge_plan['extend_existing'])} سجل موجود رح يتوسّع بتعديلات"
    )

    logger.info("=== ملخص ===")
    logger.info(f"سلاسل مفقودة بالكامل   : {stats['fully_missing']}")
    logger.info(f"سلاسل ناقصة تعديلات    : {stats['partial_missing']}")
    logger.info(f"سلاسل مكتملة           : {stats['complete']}")
    logger.info(f"حالات تحتاج مراجعة يدوية: {len(ambiguous_rows)}")
    logger.info(f"pmk_ID مفقودة (أساسية) : {len(missing_pmk_ids['base'])}")
    logger.info(f"pmk_ID مفقودة (تعديلات): {len(missing_pmk_ids['amendments'])}")


if __name__ == "__main__":
    main()
