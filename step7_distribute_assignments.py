# -*- coding: utf-8 -*-
"""
step7_distribute_assignments.py
=================================
يوزّع كل الصفوف بملف volunteers_missing_articles_*.csv (من step5) على 5
حسابات دخول (قانوني_1 .. قانوني_5) بشكل عشوائي متساوي ومعزول (كل عنصر
لشخص واحد بس، بدون تداخل)، ويكتبهم دفعة وحدة بشيت "تكليفات".

آمن التشغيل المتكرر: لو الشيت فيه بيانات أصلاً (غير صف العناوين)، يتوقف
ويحذّر بدل ما يكرر الصفوف - لازم تفريغ الشيت يدوياً أو تمرر --force لو
قاصد فعلاً تعيد التوزيع من الصفر.

الاستخدام:
    python step7_distribute_assignments.py
    python step7_distribute_assignments.py --force   # لإعادة التوزيع (يمسح ويعيد الكتابة)

النسخة: 1.0.0 - 2026-09-03
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import random
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from sheets_client import ASSIGNMENTS_HEADERS, STATUS_NOT_STARTED, init_workbook

__version__ = "1.0.0"

N_VOLUNTEERS = 5
ASSIGNEE_PREFIX = "قانوني_"
RANDOM_SEED = 42  # ثابت حتى التوزيع يكون قابل لإعادة الإنتاج لو احتجنا


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"step7_distribute_{ts}.log"
    logger = logging.getLogger("step7_distribute")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fh = logging.FileHandler(log_file, encoding="utf-8")
    ch = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fmt); ch.setFormatter(fmt)
    logger.addHandler(fh); logger.addHandler(ch)
    logger.info(f"بدء التشغيل - step7_distribute_assignments v{__version__}")
    logger.info(f"ملف اللوج: {log_file}")
    return logger


def find_latest(output_dir: Path, pattern: str, logger: logging.Logger) -> Path:
    files = sorted(glob.glob(str(output_dir / pattern)))
    if not files:
        raise FileNotFoundError(f"ما لقيت أي ملف يطابق {pattern} بمجلد {output_dir}")
    latest = Path(files[-1])
    logger.info(f"آخر ملف {pattern}: {latest.name} (من أصل {len(files)})")
    return latest


def distribute(pmk_ids: list, n: int, seed: int) -> list:
    """يرجّع قائمة أسماء المسؤولين بنفس ترتيب pmk_ids المُعطى، بعد توزيع
    عشوائي متساوي قدر الإمكان على n شخص."""
    shuffled_idx = list(range(len(pmk_ids)))
    random.Random(seed).shuffle(shuffled_idx)

    assignees = [None] * len(pmk_ids)
    for rank, idx in enumerate(shuffled_idx):
        person_num = (rank % n) + 1
        assignees[idx] = f"{ASSIGNEE_PREFIX}{person_num}"
    return assignees


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="امسح بيانات شيت التكليفات الحالية وأعد التوزيع من الصفر")
    args = parser.parse_args()

    load_dotenv()
    secret_path = os.environ["SECRET"]
    sheet_name = os.environ.get("SHEET_NAME", "adding_articles")
    sheet_id = os.environ.get("SHEET_ID")
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output"))
    log_dir = Path(os.environ.get("LOG_DIR", "logs"))
    logger = setup_logging(log_dir)

    src_path = find_latest(output_dir, "volunteers_missing_articles_*.csv", logger)
    df = pd.read_csv(src_path, dtype=str, keep_default_na=False)
    logger.info(f"تم تحميل {len(df)} صف من {src_path.name}")

    spreadsheet, assignments_ws, articles_ws, profiles_ws = init_workbook(secret_path, sheet_name, sheet_id, logger)

    existing_rows = assignments_ws.get_all_values()
    has_data = len(existing_rows) > 1  # أكثر من صف العناوين لحاله
    if has_data and not args.force:
        logger.error(
            f"شيت \"تكليفات\" فيه أصلاً {len(existing_rows)-1} صف بيانات! "
            f"ما رح أضيف فوقهم تفادياً للتكرار. فرّغ الشيت يدوياً، أو شغّل "
            f"بـ--force لو قاصد تمسح وتعيد التوزيع من الصفر."
        )
        sys.exit(1)
    if has_data and args.force:
        logger.warning(f"--force مفعّل: رح أمسح {len(existing_rows)-1} صف موجود وأعيد التوزيع")
        assignments_ws.resize(rows=1)  # يبقي صف العناوين بس
        assignments_ws.append_row(ASSIGNMENTS_HEADERS)

    assignees = distribute(df["pmk_ID"].tolist(), N_VOLUNTEERS, RANDOM_SEED)
    df["القانوني_المسؤول"] = assignees
    df["الحالة"] = STATUS_NOT_STARTED
    df["ملاحظات"] = ""

    rows = df[ASSIGNMENTS_HEADERS].values.tolist()
    logger.info(f"جاري كتابة {len(rows)} صف بشيت التكليفات...")
    assignments_ws.append_rows(rows, value_input_option="USER_ENTERED")
    logger.info("تمت الكتابة بنجاح")

    logger.info("=== توزيع الشغل ===")
    for i in range(1, N_VOLUNTEERS + 1):
        count = assignees.count(f"{ASSIGNEE_PREFIX}{i}")
        logger.info(f"  {ASSIGNEE_PREFIX}{i}: {count} عنصر")


if __name__ == "__main__":
    main()
