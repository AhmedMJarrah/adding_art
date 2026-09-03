# -*- coding: utf-8 -*-
"""
step3_merge.py
===============
الخطوة 3 (الأخيرة) من مشروع "insert": يدمج القوانين والتعديلات المفقودة
داخل ملف الـJSON الرئيسي (RefLaws)، معتمداً:
    - الميتاداتا (الاسم/الرقم/السنة/الجريدة/التواريخ...) من ملف الـCSV
      المرجعي (نفس الملف يلي استخدمناه بـstep1).
    - نصوص المواد من ملفي تصدير SQL (step2): base_articles_extract.csv
      و amendment_articles_extract.csv.
    - خطة الدمج (merge_plan_*.json من step1) اللي بتحدد بالضبط: أي قانون
      يصير سجل جديد بأعلى مستوى (add_new_top_level)، وأي تعديل يُضاف داخل
      Mod_Legs لقانون موجود مسبقاً (extend_existing) مع فهرسه بالضبط.

هالسكريبت **ما بيعدّل الملف الأصلي** - بيطلع نسخة جديدة بمجلد output/
(أو JSON_OUTPUT_FILE من .env)، راجعها وتأكد منها قبل ما تستبدل الأصلي.

قرارات اتخذناها بالمحادثة (2026-09-02):
    - Publication: يُبنى فقط لو Magazine_Number + Magazine_Page + Magazine_Date
      كلهم موجودين، وإلا يترك فاضي (مش دائماً القالب صحيح 100%، فما نخمن).
    - URL: فاضي دائماً للسجلات الجديدة (ما إلها مصدر من نفس الموقع الأصلي).
    - نص المادة: نفضّل عمود Article، ولو فاضي ناخذ OldArticle. نشيل ترويسة
      "المادة رقم..." المكرّرة من بداية النص (لأنها موجودة أصلاً بحقل title
      منفصل بهيكلية الجسون)، ونحول <br/> لأسطر عادية.

**ملاحظة مهمة لأحمد**: جدول UD_leg_Related_Modification_Articles ما فيه
غير نوع وحيد من المواد (نص التعديل نفسه). هيكلية الجسون الحالية فيها حقلين
منفصلين بالـMod_Legs: Base_Articles (نص التعديل) و Reflected_Articles (نص
القانون الأصلي بعد تطبيق التعديل). أنا بس عبّيت Base_Articles من الاستخراج -
Reflected_Articles تركتها فاضية لأنه ما عندي مصدر بيانات لها بهالمرحلة.

الاستخدام:
    python step3_merge.py

يحتاج بالإضافة لـ.env الموجود (CSV_FILE, JSON_FILE, OUTPUT_DIR, LOG_DIR):
    (اختياري) BASE_ARTICLES_CSV=data/base_articles_extract.csv
    (اختياري) AMENDMENT_ARTICLES_CSV=data/amendment_articles_extract.csv
    (اختياري) JSON_OUTPUT_FILE=output/RefLaws_merged_<ts>.json (افتراضي)

النسخة: 1.0.0 - 2026-09-02
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# تطبيع بسيط (نسخة مصغّرة عن lib_matching - بس اللي نحتاجه هون)
# ---------------------------------------------------------------------------

def clean_number(value) -> str:
    """يشيل .0 الزايدة والمسافات. يرجّع '' لو فاضي (مش None - أسهل للكتابة بالجسون)."""
    if value is None:
        return ""
    v = str(value).strip()
    if v == "" or v.lower() == "nan":
        return ""
    if v.endswith(".0"):
        v = v[:-2]
    return v


_DATE_FORMATS_IN = ["%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%d/%m/%Y"]


def reformat_date(value) -> str:
    """يحاول يفهم صيغة التاريخ الجاية من الـCSV (مختلفة بين الأعمدة: YYYY-MM-DD
    أو M/D/YYYY) ويرجّعها بصيغة الجسون DD-MM-YYYY. لو ما قدر يفهمها، يرجّعها
    زي ما هي مع تحذير باللوج بدل ما يطيح البرنامج أو يخترع تاريخ غلط."""
    if value is None:
        return ""
    v = str(value).strip()
    if v == "" or v.lower() == "nan":
        return ""
    for fmt in _DATE_FORMATS_IN:
        try:
            dt = datetime.strptime(v, fmt)
            return dt.strftime("%d-%m-%Y")
        except ValueError:
            continue
    return v  # ما قدرنا نفهمها - نرجعها خام بدل ما نخترع


_BR_TAG = re.compile(r"<br\s*/?>", re.IGNORECASE)
_LEADING_ARTICLE_HEADING = re.compile(
    r"^\s*(المادة\s*\(?\d*\)?\s*[-–:]?\s*|المادة\s+[\u0600-\u06FF]+\s*[-–:]?\s*)",
)


def clean_article_text(article: str, old_article: str) -> str:
    """يختار المصدر الأنسب (Article أولاً، وإلا OldArticle)، يحول <br/> لأسطر،
    ويشيل ترويسة "المادة X" المكرّرة من البداية (موجودة أصلاً بحقل title
    منفصل بهيكلية الجسون - ما بدنا نكررها جوا النص)."""
    text = article if (article and str(article).strip().lower() not in ("nan", "none")) else old_article
    if not text or str(text).strip().lower() in ("nan", "none"):
        return ""
    text = str(text)
    text = _BR_TAG.sub("\n", text)
    text = _LEADING_ARTICLE_HEADING.sub("", text, count=1)
    text = re.sub(r"\n{3,}", "\n\n", text)  # أسطر فاضية زايدة
    return text.strip()


def build_article_title(article_number: str) -> str:
    return f"- المادة {article_number}"


# ---------------------------------------------------------------------------
# تجهيز اللوج
# ---------------------------------------------------------------------------

def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"step3_merge_{ts}.log"

    logger = logging.getLogger("step3_merge")
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

    logger.info(f"بدء التشغيل - step3_merge v{__version__}")
    logger.info(f"ملف اللوج: {log_file}")
    return logger


def find_latest(output_dir: Path, pattern: str, logger: logging.Logger, required: bool = True) -> Path | None:
    files = sorted(glob.glob(str(output_dir / pattern)))
    if not files:
        if required:
            raise FileNotFoundError(f"ما لقيت أي ملف يطابق {pattern} بمجلد {output_dir}")
        return None
    latest = Path(files[-1])
    logger.info(f"آخر ملف {pattern}: {latest.name} (من أصل {len(files)})")
    return latest


# ---------------------------------------------------------------------------
# تحميل وتجميع المواد المستخرجة
# ---------------------------------------------------------------------------

def load_articles_by_fk(csv_path: Path, fk_column: str, logger: logging.Logger) -> dict:
    """يقرأ ملف تصدير SQL ويرجّع dict: pmk_ID (الـFK) -> [قائمة مواد مرتبة]."""
    logger.info(f"تحميل مواد: {csv_path}")
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")

    before = len(df)
    if "isDelete" in df.columns:
        df = df[~df["isDelete"].isin(["1", "1.0", "True", "true"])]
    if "DeleteArticle" in df.columns:
        df = df[~df["DeleteArticle"].isin(["1", "1.0", "True", "true"])]
    if before != len(df):
        logger.info(f"استُثني {before - len(df)} صف معلَّم isDelete/DeleteArticle")

    df["_artnum_sort"] = pd.to_numeric(df["Article_Number"], errors="coerce").fillna(0)
    df = df.sort_values(["_artnum_sort"])

    grouped: dict = defaultdict(list)
    for _, row in df.iterrows():
        fk = clean_number(row.get(fk_column, ""))
        if not fk:
            continue
        art_num = clean_number(row.get("Article_Number", ""))
        text = clean_article_text(row.get("Article", ""), row.get("OldArticle", ""))
        grouped[fk].append({
            "text": text,
            "title": build_article_title(art_num),
            "article_number": art_num,
        })

    logger.info(f"تجميع مواد لـ {len(grouped)} قانون/تعديل مميّز من {len(df)} صف")
    return grouped


# ---------------------------------------------------------------------------
# بناء سجلات الجسون من صفوف الـCSV
# ---------------------------------------------------------------------------

def build_publication(row: dict) -> str:
    num = clean_number(row.get("Magazine_Number", ""))
    page = clean_number(row.get("Magazine_Page_Number", ""))
    date = reformat_date(row.get("Magazine_Date", ""))
    if not (num and page and date):
        return ""  # بيانات ناقصة - نفضّل فاضي على تخمين (تعليمات أحمد)
    return f"المنشور كما صدر أصلاً في عدد الجريدة الرسمية رقم {num} على الصفحة {page} بتاريخ {date}"


def build_base_entry(csv_row: dict, articles: list, mod_legs: list, logger: logging.Logger) -> dict:
    # نعتمد فقط على الأعمدة "_final" (المُدقَّقة من مشروع التوفيق السابق)،
    # ما نرجع للعمود الخام لو فاضي - لقينا حالة حقيقية (pmk_ID=249) وين
    # End_Date_final فاضي بس عمود end_date الخام = 1973 لقانون صدر 1997
    # (تاريخ نهاية قبل الصدور!). فاضي أصدق من رقم خاطئ.
    active_date = csv_row.get("Active_Date_final", "")
    end_date = csv_row.get("End_Date_final", "")

    return {
        "Leg_Name": csv_row.get("Law_Name", ""),
        "Publication": build_publication(csv_row),
        "Leg_Number": clean_number(csv_row.get("Law_Number", "")),
        "Year": clean_number(csv_row.get("Year", "")),
        "Article_Count": str(len(articles)),
        "Replaced_For": csv_row.get("Replaced_For", ""),
        "Canceled_By": csv_row.get("Canceled_By", ""),
        "Magazine_Number": clean_number(csv_row.get("Magazine_Number", "")),
        "Magazine_Page": clean_number(csv_row.get("Magazine_Page_Number", "")),
        "Magazine_Date": reformat_date(csv_row.get("Magazine_Date", "")),
        "Issue_Date": "",  # مو موجود بالـCSV المرجعي - تُرك فاضي عمداً
        "Active_Date": reformat_date(active_date),
        "End_Date": reformat_date(end_date),
        "Replaced_By": csv_row.get("Replaced_By", ""),
        "URL": "",  # تعليمات أحمد - فاضي دائماً للسجلات الجديدة
        "Base_Articles": articles,
        "Mod_Legs": mod_legs,
    }


def build_mod_leg_entry(csv_row: dict, articles: list, logger: logging.Logger) -> dict:
    pmk_id = csv_row["pmk_ID"]
    active_date = csv_row.get("Active_Date_final", "")
    end_date = csv_row.get("End_Date_final", "")

    if not articles:
        logger.warning(f"تعديل pmk_ID={pmk_id}: ما انلقت له أي مواد بالاستخراج")

    return {
        "Magazine_Date": reformat_date(csv_row.get("Magazine_Date", "")),
        "Magazine_Page": clean_number(csv_row.get("Magazine_Page_Number", "")),
        "Magazine_Number": clean_number(csv_row.get("Magazine_Number", "")),
        "Leg_Number": clean_number(csv_row.get("Law_Number", "")),
        "Leg_Name": csv_row.get("Law_Name", ""),
        "Year": clean_number(csv_row.get("Year", "")),
        "is_amendment": True,
        "URL": "",
        "Publication": build_publication(csv_row),
        "Article_Count": str(len(articles)),
        "Replaced_For": csv_row.get("Replaced_For", ""),
        "Canceled_By": csv_row.get("Canceled_By", ""),
        "Issue_Date": "",
        "Active_Date": reformat_date(active_date),
        "End_Date": reformat_date(end_date),
        "Replaced_By": csv_row.get("Replaced_By", ""),
        # ملاحظة: Reflected_Articles فاضية عمداً - ما عندنا مصدر بيانات لها
        # بهالمرحلة (راجع الملاحظة بأعلى الملف).
        "Reflected_Articles": [],
        "Base_Articles": articles,
    }


# ---------------------------------------------------------------------------
# المنطق الرئيسي
# ---------------------------------------------------------------------------

def main():
    load_dotenv()
    csv_path = Path(os.environ["CSV_FILE"])
    json_path = Path(os.environ["JSON_FILE"])
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output"))
    log_dir = Path(os.environ.get("LOG_DIR", "logs"))
    base_articles_path = Path(os.environ.get("BASE_ARTICLES_CSV", "data/base_articles_extract.csv"))
    amend_articles_path = Path(os.environ.get("AMENDMENT_ARTICLES_CSV", "data/amendment_articles_extract.csv"))
    output_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging(log_dir)

    merge_plan_path = find_latest(output_dir, "merge_plan_*.json", logger)
    with open(merge_plan_path, "r", encoding="utf-8") as f:
        merge_plan = json.load(f)
    logger.info(
        f"خطة الدمج: {len(merge_plan['add_new_top_level'])} سجل جديد، "
        f"{len(merge_plan['extend_existing'])} سجل رح يتوسّع"
    )

    logger.info(f"تحميل CSV المرجعي: {csv_path}")
    csv_df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    csv_by_pmk = {row["pmk_ID"]: row.to_dict() for _, row in csv_df.iterrows()}
    logger.info(f"تم فهرسة {len(csv_by_pmk)} صف من الـCSV حسب pmk_ID")

    base_articles = load_articles_by_fk(base_articles_path, "fnk_leg_Laws10689", logger)
    amend_articles = load_articles_by_fk(amend_articles_path, "fnk_leg_Legislative_Amendments10747", logger)

    logger.info(f"تحميل JSON: {json_path} (ملف كبير، ممكن ياخذ وقت)")
    t0 = datetime.now()
    with open(json_path, "r", encoding="utf-8-sig") as f:
        json_entries = json.load(f)
    logger.info(f"تم تحميل {len(json_entries)} عنصر خلال {(datetime.now()-t0).total_seconds():.1f} ثانية")

    stats = defaultdict(int)
    zero_article_pmks = []

    # --- [1] سجلات جديدة بأعلى مستوى ---
    for item in merge_plan["add_new_top_level"]:
        base_pmk = item["base_pmk_ID"]
        csv_row = csv_by_pmk.get(base_pmk)
        if csv_row is None:
            logger.error(f"pmk_ID={base_pmk} مو موجود بالـCSV المرجعي - تم تخطيه!")
            stats["skipped_missing_from_csv"] += 1
            continue

        articles = base_articles.get(base_pmk, [])
        if not articles:
            zero_article_pmks.append(base_pmk)

        mod_legs = []
        for amend_pmk in item["amendment_pmk_IDs"]:
            a_row = csv_by_pmk.get(amend_pmk)
            if a_row is None:
                logger.error(f"تعديل pmk_ID={amend_pmk} مو موجود بالـCSV - تم تخطيه!")
                continue
            a_arts = amend_articles.get(amend_pmk, [])
            if not a_arts:
                zero_article_pmks.append(amend_pmk)
            mod_legs.append(build_mod_leg_entry(a_row, a_arts, logger))
            stats["amendments_added_nested"] += 1

        new_entry = build_base_entry(csv_row, articles, mod_legs, logger)
        json_entries.append(new_entry)
        stats["base_added"] += 1

    # --- [2] توسيع سجلات موجودة بتعديلات جديدة ---
    for item in merge_plan["extend_existing"]:
        idx = item["json_index"]
        if idx >= len(json_entries):
            logger.error(f"json_index={idx} خارج نطاق القائمة (طولها {len(json_entries)}) - تم تخطيه!")
            continue
        target = json_entries[idx]
        if "Mod_Legs" not in target or target["Mod_Legs"] is None:
            target["Mod_Legs"] = []

        for amend_pmk in item["amendment_pmk_IDs"]:
            a_row = csv_by_pmk.get(amend_pmk)
            if a_row is None:
                logger.error(f"تعديل pmk_ID={amend_pmk} مو موجود بالـCSV - تم تخطيه!")
                continue
            a_arts = amend_articles.get(amend_pmk, [])
            if not a_arts:
                zero_article_pmks.append(amend_pmk)
            target["Mod_Legs"].append(build_mod_leg_entry(a_row, a_arts, logger))
            stats["amendments_added_extended"] += 1

        if "Article_Count" in target:
            pass  # ما نلمس Article_Count تبع القانون الأساسي نفسه - هاي بتخص موادّه هو بس

    # --- الحفظ (ملف جديد - ما نلمس الأصلي) ---
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(os.environ.get("JSON_OUTPUT_FILE", output_dir / f"RefLaws_merged_{ts}.json"))
    logger.info(f"كتابة الناتج: {out_path} (ممكن ياخذ وقت لأنه ملف كبير)")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(json_entries, f, ensure_ascii=False)
    logger.info(f"تم الحفظ: {out_path} ({len(json_entries)} عنصر بأعلى مستوى)")

    logger.info("=== ملخص ===")
    logger.info(f"سجلات أساسية جديدة أُضيفت : {stats['base_added']}")
    logger.info(f"تعديلات أُضيفت (سجل جديد) : {stats['amendments_added_nested']}")
    logger.info(f"تعديلات أُضيفت (سجل موجود): {stats['amendments_added_extended']}")
    logger.info(f"تخطّي (مو موجود بالـCSV)  : {stats['skipped_missing_from_csv']}")
    logger.info(f"pmk_ID بدون أي مواد مستخرجة: {len(zero_article_pmks)}")
    if zero_article_pmks:
        zero_path = output_dir / f"zero_articles_{ts}.json"
        with open(zero_path, "w", encoding="utf-8") as f:
            json.dump(zero_article_pmks, f, ensure_ascii=False, indent=2)
        logger.warning(f"قائمة الـpmk_ID بدون مواد (راجعها): {zero_path}")


if __name__ == "__main__":
    main()
