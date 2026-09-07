# -*- coding: utf-8 -*-
"""
lib_matching.py
================
وحدة مطابقة مشتركة لمشروع "insert" - تُستخدم بخطوة المقارنة (Step 1) وممكن
تُستخدم لاحقاً بخطوات ثانية.

المنهجية المتفق عليها معك:
    Tier 1 -> تطابق (رقم القانون + السنة) بعد التطبيع. لو في أكثر من مرشح
              بنفس الرقم والسنة (تعارض)، نفرزهم حسب تشابه الاسم.
    Tier 2 -> لو الرقم فاضي بأحد الطرفين: (السنة + رقم/صفحة الجريدة).
    Tier 3 -> لو فشل كل ما سبق: (السنة + تشابه اسم قوي جداً) - وتُعلَّم
              دائماً "تحتاج مراجعة يدوية" لأنها أضعف طبقة.

كل نتيجة فيها تشابه اسم واطئ (حتى لو تطابق الرقم+السنة) تُعلَّم كمان
needs_review=True حتى ما ننسحب على تطابق رقمي فقط بدون تأكيد الاسم.

النسخة: 1.5.0 - 2026-09-06
    - تصحيح تعارض "نفس المحتوى مكرر حرفياً": لو المرشحين المتعارضين على
      نفس رقم+سنة كلهم متطابقين شبه تمام مع بعض (تعديل واحد مكرر فعلياً
      جوا الجسون تحت أكثر من قانون أب)، نقبل المطابقة بدل ما نرفضها
      كـ"تعارض ما انحل" - المحتوى موجود أصلاً بغض النظر عن أي نسخة تحديداً.
      اكتُشفت بحالتين حقيقيتين (تعديل مكرر تحت أب وحد، وتعديل مكرر تحت 4).

النسخة: 1.4.0 - 2026-09-02
    - تراجعت عن قرار "ارفض Tier 2 دائماً" من v1.3.0. كان مبني على عيّنة
      صغيرة (8 حالات) قِيست بالمقياس الحرفي القديم المعطوب. لما شغّلتها
      بمقياس المحتوى الجديد على عيّنة حقيقية أكبر (446 حالة)، طلع التوزيع
      واضح: ~80% درجتها 0.9+ (صحيحة)، بس ~13% قريبة من صفر (غلط فعلاً).
      رجّعت Tier 2 لنظام الثقة المتدرج نفسه المستخدم بـTier 1 (قبول فوق
      0.10، بدون مراجعة فوق 0.50) بدل الرفض الكامل.

النسخة: 1.3.0 - 2026-09-02
    - تغيير جوهري: التشابه الحرفي (SequenceMatcher على النص الكامل) فشل
      فعلياً مع عناوين التشريعات الأردنية - عناوين قوانين مختلفة الموضوع
      كلياً بس نفس السنة بتاخذ تشابه حرفي 0.82-0.86 بسبب القالب المتكرر
      ("قانون معدل رقم X لسنة Y (قانون ... المعدل لسنة Y)")، بنفس مدى
      القوانين الصحيحة فعلاً (0.83-0.86) - يعني ولا عتبة كانت رح تفصل بينهم.
      استبدلته بـ content_similarity: تشابه Jaccard على "كلمات المحتوى"
      فقط بعد إزالة كلمات القالب (قانون/رقم/لسنة/معدل/مؤقت...). جُرّب على
      حالات حقيقية صح وغلط وفصل بينهم بوضوح (غلط=0.0-0.25، صح=0.6+).
    - Tier 2 (سنة+جريدة، الرقم فاضي): تجربة فعلية على البيانات الحقيقية
      طلعت 7 من 8 نتائج غلط (رقم الجريدة تطابق صدفة). عدّلتها لترجع دائماً
      "مرشح للمراجعة" بس مش "تطابق تلقائي" - بغض النظر عن درجة التشابه.

النسخة: 1.2.0 - 2026-09-02
    - تصحيح: Tier 1b (الفصل برقم الجريدة) كان يثق برقم الجريدة حتى لو
      الاسم بعيد كليا عن المرشح - سبب 3 مطابقات خاطئة فعلية بالبيانات
      الحقيقية (تشابه اسم 0.33-0.35 لقوانين مالها علاقة ببعض إطلاقاً).
      أضفت MAGAZINE_TIEBREAK_MIN_SIM=0.40 كحد أدنى قبل القبول.

النسخة: 1.1.0 - 2026-09-02
    - إضافة Tier 1b: فصل تعارضات الرقم+السنة اللي أسماءها متطابقة تقريباً
      (نمط "ملحق بقانون الموازنة") عن طريق رقم الجريدة بدل ما تبقى معلّقة.
    - تعارضات ما انفصلت تحمل الآن أسماء كل المرشحين ورقم جريدتهم بدل
      ما ترجع فاضية، حتى تنراجع بدون داعي لملف تشخيصي منفصل.

النسخة: 1.0.0 - 2026-09-02
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Optional

__version__ = "1.5.0"

# ---------------------------------------------------------------------------
# تطبيع النصوص والأرقام
# ---------------------------------------------------------------------------

_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u06D6-\u06ED]")
_TATWEEL = "\u0640"


def normalize_arabic_name(text: Optional[str]) -> str:
    """تطبيع اسم القانون للمقارنة: تشكيل/تطويل، توحيد الألف/الهمزة/التاء
    المربوطة، إزالة الترقيم، توحيد المسافات."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = _DIACRITICS.sub("", t)
    t = t.replace(_TATWEEL, "")
    t = re.sub(r"[إأآا]", "ا", t)
    t = re.sub(r"ى", "ي", t)
    t = re.sub(r"ة", "ه", t)
    t = re.sub(r"ؤ", "و", t)
    t = re.sub(r"ئ", "ي", t)
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def normalize_number(value) -> Optional[str]:
    """يشيل .0 الزايدة من تصدير CSV والأصفار البادئة. يرجّع None لو فاضي."""
    if value is None:
        return None
    v = str(value).strip()
    if v == "" or v.lower() == "nan":
        return None
    if v.endswith(".0"):
        v = v[:-2]
    v = v.lstrip("0") or "0"
    return v


def normalize_year(value) -> Optional[str]:
    return normalize_number(value)


def name_similarity(a: str, b: str) -> float:
    """تشابه حرفي كامل - أبقيتها للمرجعية بس ما عاد تُستخدم بقرارات المطابقة
    (شفنا فعلياً إنها بتفشل مع عناوين التشريعات القالبية - راجع v1.3.0 تحت)."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


# كلمات "قالبية" متكررة بعناوين التشريعات الأردنية (قانون/رقم/لسنة/معدل...)
# بتتكرر بنفس الشكل تقريباً بكل عنوان بغض النظر عن الموضوع الفعلي، وبتسبب
# تشابه حرفي عالي بين قانونين مختلفين تماماً بس نفس القالب ونفس السنة.
# مبنية بتطبيق normalize_arabic_name عليها حتى تطابق شكل النص بعد التطبيع
# بالضبط (بعدين تحويل ة->ه وؤ->و... الخ).
_RAW_STOPWORDS = [
    "قانون", "رقم", "لسنة", "معدل", "مؤقت",
    "تعديل", "تعديلات", "وتعديلاته", "وتعديلاتها", "مشروع", "و",
]
LEGISLATIVE_STOPWORDS = {normalize_arabic_name(w) for w in _RAW_STOPWORDS}


def _strip_al(word: str) -> str:
    """يشيل "ال" التعريف من أول الكلمة حتى "الميزانية" و"ميزانية" يتحسبوا
    نفس الكلمة."""
    return word[2:] if word.startswith("ال") and len(word) > 4 else word


def content_words(name_norm: str) -> set:
    """كلمات "المحتوى" الفعلية بعد إزالة القالب والأرقام - هاي اللي بتحدد
    موضوع القانون الحقيقي (مو صياغة العنوان). لازم نشيل "ال" التعريف قبل
    ما نفحص إذا الكلمة قالبية، وإلا "القانون" (بأل) ما بتنطابق مع "قانون"
    المسجّلة بقائمة القالب فتتسرب كأنها كلمة مضمون."""
    out = set()
    for w in name_norm.split():
        w2 = _strip_al(w)
        if w2 in LEGISLATIVE_STOPWORDS or w2.isdigit():
            continue
        out.add(w2)
    return out


def content_similarity(a_norm: str, b_norm: str) -> float:
    """تشابه Jaccard على كلمات المحتوى (بعد إزالة القالب). هاي المقياس
    المعتمد فعلياً بقرارات المطابقة - جربناها ضد حالات حقيقية صح وغلط
    وفصلت بينهم بوضوح، عكس التشابه الحرفي العادي اللي فشل تماماً معهم."""
    wa, wb = content_words(a_norm), content_words(b_norm)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


# ---------------------------------------------------------------------------
# هياكل البيانات
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    """مرشّح للمطابقة من جهة الـJSON (قانون أساسي أو تعديل ضمن Mod_Legs).
    ref_id لازم يكون فريد وقابل لإعادة الوصول للعنصر الأصلي (مثلاً index
    بالقائمة) - ما نعتمد على الاسم كمعرّف لأنه ممكن يتكرر."""
    ref_id: str
    number: Optional[str]
    year: Optional[str]
    name_norm: str
    display_name: str = ""
    magazine_number: Optional[str] = None
    magazine_page: Optional[str] = None


@dataclass
class MatchResult:
    matched: bool
    tier: Optional[str] = None
    score: float = 0.0
    candidate_id: Optional[str] = None
    candidate_name: str = ""
    ambiguous: bool = False
    needs_review: bool = False
    note: str = ""


def build_pools(candidates: Iterable[Candidate]):
    """يبني فهرسين لتسريع البحث: حسب (رقم، سنة) وحسب (سنة) لوحدها."""
    pool_by_num_year: dict = {}
    pool_by_year: dict = {}
    for c in candidates:
        if c.number is not None and c.year is not None:
            pool_by_num_year.setdefault((c.number, c.year), []).append(c)
        if c.year is not None:
            pool_by_year.setdefault(c.year, []).append(c)
    return pool_by_num_year, pool_by_year


# عتبات القرار - مركزية هون حتى تصير سهلة التعديل بدون ما تروح تلاقيهن مبعثرين
# كلهن الآن على مقياس content_similarity (Jaccard على كلمات المحتوى)، مو
# التشابه الحرفي القديم - جُرّبت الأرقام هذول ضد حالات حقيقية من بياناتك:
# الغلط سجّل 0.0-0.25 دائماً، والصح سجّل 0.6+ دائماً بالحالات الضعيفة العدد،
# و0.15-0.25 بالحالات القصيرة (كلمة مفتاحية وحدة بس صحيحة، زي "استملاك").
NAME_SIM_ACCEPT_T1 = 0.10        # فوق الصفر التام فقط - رقم+سنة مطابقين أصلاً قرينة قوية
NAME_SIM_CONFIDENT_T1 = 0.50     # فوق هالقيمة نثق بالتطابق بدون مراجعة يدوية
NAME_SIM_TIEBREAK_MARGIN = 0.15  # الفرق المطلوب بين أفضل مرشحين لحسم تعارض
NAME_SIM_NEAR_IDENTICAL = 0.90   # فوق هالقيمة، اعتبرها "نفس المحتوى" حتى لو تعادل مرشحين
NAME_SIM_ACCEPT_T3 = 0.45        # لا يوجد رقم يثبّت القرار هون، فلازم تشابه محتوى واضح
MAGAZINE_TIEBREAK_MIN_SIM = 0.10  # حد أدنى (فوق الصفر) قبل ما نثق برقم الجريدة كفاصل


def match_one(number: Optional[str], year: Optional[str], name_norm: str,
              magazine_number: Optional[str], magazine_page: Optional[str],
              pool_by_num_year: dict, pool_by_year: dict) -> MatchResult:
    """يحاول مطابقة سجل واحد (من CSV) مقابل مجموعة مرشحين (من JSON)."""

    # --- Tier 1: رقم + سنة ---
    if number is not None and year is not None:
        candidates = pool_by_num_year.get((number, year), [])
        if len(candidates) == 1:
            c = candidates[0]
            sim = content_similarity(name_norm, c.name_norm)
            if sim >= NAME_SIM_ACCEPT_T1:
                return MatchResult(
                    matched=True, tier="T1", score=sim,
                    candidate_id=c.ref_id, candidate_name=c.display_name,
                    needs_review=(sim < NAME_SIM_CONFIDENT_T1),
                    note="" if sim >= NAME_SIM_CONFIDENT_T1
                    else "رقم وسنة مطابقين بس تشابه المحتوى واطئ - أكّد يدوياً إنه نفس القانون",
                )
            return MatchResult(
                matched=False, tier="T1", score=sim, ambiguous=True,
                candidate_id=c.ref_id, candidate_name=c.display_name,
                needs_review=True,
                note="رقم وسنة مطابقين بس مافي أي كلمة مضمون مشتركة بالاسم - على الأغلب قانون مختلف تماماً، تأكد يدوياً",
            )
        elif len(candidates) > 1:
            scored = sorted(
                ((content_similarity(name_norm, c.name_norm), c) for c in candidates),
                key=lambda x: x[0], reverse=True,
            )
            best_score, best_c = scored[0]
            second_score = scored[1][0] if len(scored) > 1 else 0.0

            if best_score >= NAME_SIM_ACCEPT_T1 and (best_score - second_score) > NAME_SIM_TIEBREAK_MARGIN:
                return MatchResult(
                    matched=True, tier="T1", score=best_score,
                    candidate_id=best_c.ref_id, candidate_name=best_c.display_name,
                    note=f"تعارض رقم+سنة ({len(candidates)} مرشحين) - انحسم بالاسم",
                )

            # الاسم لحاله ما فصل (غالباً لأن الأسماء متطابقة تقريباً حرفياً -
            # نمط معروف بقوانين "ملحق بقانون الموازنة" اللي بتتكرر بنفس
            # الرقم/السنة/الاسم لكن بجريدة رسمية مختلفة). نجرب نفصل برقم الجريدة
            # **قبل** أي قرار "تكرار حرفي" - رقم الجريدة أدق لو قادر يفصل
            # فعلياً، بس فقط لو الاسم أصلاً فيه تشابه محتوى حقيقي - غير هيك
            # رقم الجريدة ممكن يتطابق صدفة بين قانونين مختلفين تماماً بالموضوع
            # (شفنا حالات حقيقية زي هيك بالضبط).
            if magazine_number is not None:
                mag_matches = [c for c in candidates if c.magazine_number == magazine_number]
                if len(mag_matches) == 1:
                    c = mag_matches[0]
                    sim = content_similarity(name_norm, c.name_norm)
                    if sim >= MAGAZINE_TIEBREAK_MIN_SIM:
                        return MatchResult(
                            matched=True, tier="T1b", score=sim,
                            candidate_id=c.ref_id, candidate_name=c.display_name,
                            needs_review=True,
                            note=f"تعارض رقم+سنة ({len(candidates)} مرشحين، أسماء متشابهة) - انحسم برقم الجريدة",
                        )
                    # رقم الجريدة تطابق صدفة بس مافي تشابه محتوى إطلاقاً - ما نثق فيه

            # رقم الجريدة ما قدر يفصل (فاضي، أو متطابق هو نفسه بين كل
            # المرشحين). لو المرشحين كلهم متطابقين شبه تمام مع بعض (نفس
            # الاسم/الرقم/السنة/الجريدة) - هاي حالة حقيقية اكتشفناها: نفس
            # التعديل مكرر حرفياً جوا الجسون تحت أكثر من قانون أب (تعديل
            # يمس أكثر من قانون، أو تكرار بالمصدر نفسه). بما إنه ما في أي
            # إشارة (لا اسم ولا جريدة) تفرّق بينهم، المحتوى موجود أصلاً بغض
            # النظر عن أي نسخة تحديداً - نقبل بدل ما نرفض كـ"تعارض ما انحل".
            if best_score >= NAME_SIM_NEAR_IDENTICAL and second_score >= NAME_SIM_NEAR_IDENTICAL:
                return MatchResult(
                    matched=True, tier="T1", score=best_score,
                    candidate_id=best_c.ref_id, candidate_name=best_c.display_name,
                    needs_review=False,
                    note=f"نفس المحتوى مكرر حرفياً {len(candidates)} مرات بالجسون (رقم الجريدة ما فصل بينهم) - موجود أصلاً",
                )

            all_names = "؛ ".join(
                f"{c.display_name} [جريدة {c.magazine_number}]" for c in candidates
            )
            return MatchResult(
                matched=False, tier="T1", score=best_score, ambiguous=True,
                needs_review=True, candidate_name=all_names,
                note=f"تعارض رقم+سنة ({len(candidates)} مرشحين) - الاسم ورقم الجريدة ما فصلوا",
            )

    # --- Tier 2: سنة + رقم/صفحة الجريدة (لما الرقم فاضي بأحد الطرفين) ---
    # ملاحظة مهمة: كنت رفضت هاي الطبقة تماماً بنسخة سابقة بناءً على عيّنة
    # صغيرة (8 حالات) قِيست بالتشابه الحرفي القديم. لما قِيست نفس الطبقة على
    # عيّنة حقيقية أكبر (446 حالة) بمقياس المحتوى الجديد، طلع التوزيع واضح
    # جداً: ~80% من الحالات درجتها 0.9+ (تطابق شبه تام - صحيحة فعلياً)، وبس
    # ~13% قريبة من الصفر (تطابق جريدة صدفة - غلط). يعني الطبقة نفسها موثوقة،
    # المشكلة كانت بالمقياس القديم بس. رجّعتها تستخدم نفس نظام الثقة المتدرج
    # متل Tier 1.
    if year is not None and magazine_number is not None:
        for c in pool_by_year.get(year, []):
            if c.magazine_number == magazine_number and (
                magazine_page is None or c.magazine_page is None or c.magazine_page == magazine_page
            ):
                sim = content_similarity(name_norm, c.name_norm)
                if sim >= NAME_SIM_ACCEPT_T1:
                    return MatchResult(
                        matched=True, tier="T2", score=sim,
                        candidate_id=c.ref_id, candidate_name=c.display_name,
                        needs_review=(sim < NAME_SIM_CONFIDENT_T1),
                        note="" if sim >= NAME_SIM_CONFIDENT_T1
                        else "مطابقة سنة+جريدة (الرقم فاضي) بتشابه محتوى متوسط - أكّد يدوياً",
                    )
                return MatchResult(
                    matched=False, tier="T2", score=sim, ambiguous=True,
                    candidate_id=c.ref_id, candidate_name=c.display_name,
                    needs_review=True,
                    note="مطابقة سنة+جريدة (الرقم فاضي) بس مافي تشابه محتوى - على الأغلب رقم جريدة تطابق صدفة",
                )

    # --- Tier 3: سنة + تشابه محتوى قوي (أضعف طبقة، مافي رقم يثبّتها) ---
    if year is not None:
        best, best_sim = None, 0.0
        for c in pool_by_year.get(year, []):
            sim = content_similarity(name_norm, c.name_norm)
            if sim > best_sim:
                best_sim, best = sim, c
        if best is not None and best_sim >= NAME_SIM_ACCEPT_T3:
            return MatchResult(
                matched=True, tier="T3", score=best_sim,
                candidate_id=best.ref_id, candidate_name=best.display_name,
                needs_review=True,
                note="مطابقة بالاسم فقط (Tier 3) - لازم تأكيد يدوي",
            )

    return MatchResult(matched=False, tier=None, score=0.0, note="ماكو أي مرشح مطابق")
