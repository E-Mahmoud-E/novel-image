import os
import json
import time
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from openai import OpenAI

# --- 1. إعداد الاتصال بـ Firebase (يدعم المحلي و GitHub تلقائياً) ---
if os.environ.get('FIREBASE_KEY'):
    # العمل على GitHub Actions
    cred_json = json.loads(os.environ.get('FIREBASE_KEY'))
    cred = credentials.Certificate(cred_json)
else:
    # العمل محلياً على جهازك
    cred_path = r"D:\Novel\worldwide-simulation-era\firestore-key.json"
    cred = credentials.Certificate(cred_path)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --- 2. إعداد عميل OpenRouter ---
# يقرأ المفتاح من GitHub Secrets أو يستخدم المفتاح الثابت محلياً
api_key = os.environ.get('OPENROUTER_API_KEY')
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

# اسم الرواية المستهدفة
TARGET_NOVEL = "World Simulation Era"
def process_translation():
    # جلب الفصول التي تم تحليلها بنجاح ولم يتم ترجمتها بعد
    chapters_query = db.collection('Chapters') \
        .where(filter=FieldFilter('Novel_Name', '==', TARGET_NOVEL)) \
        .where(filter=FieldFilter('is_analyzed', '==', True)) \
        .stream()
    
    docs = list(chapters_query)
    
    # ترتيب الفصول رقمياً مع الحماية من قيم المعرفات التي لا تحوي أرقاماً
    docs.sort(key=lambda x: int(''.join(filter(str.isdigit, x.id)) or 0))

    print(f"🌍 بدء الترجمة المنفصلة لـ {len(docs)} فصل من رواية [{TARGET_NOVEL}]...")

    for doc in docs:
        ch_num = ''.join(filter(str.isdigit, doc.id))
        doc_data = doc.to_dict()
        
        # تخطي إذا كان الفصل مترجماً مسبقاً
        if doc_data.get('is_translated'):
            continue

        print(f"✍️ جاري ترجمة الفصل [{ch_num}] بالاعتماد على سياق الـ Firebase المعالج...")
        content_en = doc_data.get('content', '')
        analysis_data = doc_data.get('analysis_data', {})
        
        if not content_en:
            print(f"⚠️ الفصل {ch_num} لا يحتوي على نص إنجليزي، تخطي.")
            continue

        # --- استدعاء بيانات السياق والقاموس من Firestore ---
        translation_guide = analysis_data.get('translation_guide', {})
        gender_map = translation_guide.get('gender_map', {})
        key_terms = translation_guide.get('key_terms', {})
        social_matrix = analysis_data.get('social_matrix', [])

        # بناء تعليمات صيغ المخاطبة بناءً على العلاقات المكتشفة
        social_instructions = ""
        for relation in social_matrix:
            social_instructions += f"- Character '{relation.get('from')}' addresses '{relation.get('to')}' with a tone of [{relation.get('tone')}]. Use the Arabic honorific style: '{relation.get('honorifics_ar')}'.\n"

        # --- البرومبت الموجه للمترجم ---
        system_prompt = f"""
        Role: You are a Master Literary Translator specialized in professional Light Novels and Cultivation/Fantasy genres.
        Task: Translate the provided novel text from English to Arabic.
        
        Strict Translation Rules & Memory Constraints:
        1. Tone: Output elegant, highly immersive, and descriptive Arabic novel prose (Fusha - فصحى بليغة). Avoid literal translation completely.
        2. Terminology Consistency (Glossary): You MUST use these exact Arabic terms found in the database: {key_terms}.
        3. Gender Enforcement: Adhere strictly to this character gender map for verbs and pronouns: {gender_map}.
        4. Protagonist Rule: The main character of '{TARGET_NOVEL}' is MALE. Never use female pronouns or verbs for him.
        5. Social Dynamics & Honorifics (Dialogue Tone): Apply these relationship dynamics for dialogues in this chapter:
        {social_instructions}
        6. Formatting: Keep the original paragraph layout intact. Do not add summaries or notes outside the story text.
        """

        try:
            response = client.chat.completions.create(
                model='google/gemini-2.0-flash-001',
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Text to translate:\n\n{content_en}"}
                ],
                temperature=0.6,
                max_tokens=4000
            )

            translated_text = response.choices[0].message.content

            # تحديث مستند الفصل بالترجمة العربية في Firestore مباشرة
            doc.reference.update({
                "content_ar": translated_text,
                "is_translated": True,
                "translated_at": firestore.SERVER_TIMESTAMP
            })

            print(f"✅ تم ترجمة وحفظ الفصل {ch_num} سحابياً.")
            time.sleep(3)

        except Exception as e:
            print(f"❌ خطأ أثناء ترجمة الفصل {ch_num}: {e}")
            if "402" in str(e):
                print("🛑 توقف السكربت بسبب الرصيد.")
                break

if __name__ == "__main__":
    process_translation()
