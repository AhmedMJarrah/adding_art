# -*- coding: utf-8 -*-
"""
convert_secret_to_toml.py
===========================
يحوّل ملف الـService Account JSON لصيغة [gcp_service_account] TOML جاهزة
تُلصَق مباشرة بخانة Secrets على Streamlit Cloud - بدون نسخ يدوي لأي حقل
(وهاد بالضبط سبب مشكلة "Invalid control character": النسخ اليدوي لحقل
private_key بيحوّل أحياناً الـ\\n لسطر حقيقي فينكسر الـJSON).

هالطريقة أضمن 100%: التطبيق بياخذ st.secrets["gcp_service_account"]
كجدول (dict) مباشرة، بدون ما يحتاج يعمل json.loads() إطلاقاً.

الاستخدام:
    python convert_secret_to_toml.py

يحتاج بـ.env: SECRET=<مسار ملف الـJSON>
"""

import json
import os

from dotenv import load_dotenv

load_dotenv()
secret_path = os.environ["SECRET"]

with open(secret_path, "r", encoding="utf-8") as f:
    data = json.load(f)

print("=" * 70)
print("انسخ كل السطور اللي تحت (من [gcp_service_account] لآخر سطر)")
print("والصقها بخانة Secrets على Streamlit Cloud")
print("=" * 70)
print()
print("[gcp_service_account]")
for key, value in data.items():
    # json.dumps على القيمة لحالها بيعطينا نص TOML صحيح ومهرَّب بشكل صحيح
    # (يشمل private_key بكل الـ\n اللي فيه) - نفس قواعد التهريب مشتركة
    # بين JSON وTOML للحالات الاعتيادية زي هاي.
    print(f"{key} = {json.dumps(value, ensure_ascii=False)}")
print()
print("=" * 70)
print("بعد هالجزء، كمّل بباقي المفاتيح (SHEET_NAME, SHEET_ID, ADMIN_USERNAME...)")
print("زي ما هي - هاي بس لجزء gcp_service_account.")
