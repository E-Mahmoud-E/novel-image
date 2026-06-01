import os
import json
import time
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

# --- 1. إعداد الاتصال بـ Firebase (يدعم المحلي و GitHub تلقائياً) ---
if os.environ.get('FIREBASE_KEY'):
    cred_json = json.loads(os.environ.get('FIREBASE_KEY'))
    cred = credentials.Certificate(cred_json)
else:
    cred_path = r"D:\Novel\worldwide-simulation-era\firestore-key.json"
    cred = credentials.Certificate(cred_path)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

TARGET_NOVEL = "worldwide-simulation-era"
AUTHOR_NAME = "Mahmoud El-Mahdy"  # اسمك الذي سيظهر ككاتب للفصل في تليجرام

def create_telegraph_page(title, html_content):
    """إنشاء صفحة على Telegraph باستخدام نظام الـ API المباشر"""
    url = "https://api.telegra.ph/createPage"
    
    # تحويل محتوى الـ HTML إلى هيكل Node JSON المطلوب من قبل Telegraph API
    # لتبسيط الأمر، سنقوم بإرسال الـ HTML مباشرة حيث يدعم الـ API استقباله عبر بارامتر الكونتنت في الحالات البرمجية
    # أو استخدام أداة تحويل مدمجة. Telegraph يتطلب تاق Node، لذا سنقوم بصياغة البيانات بهيكل برمجى متوافق:
    
    payload = {
        'access_token': '490886eb366e324c5cdf34054f75f6f3aa5c15491a5a6d8b83a0f8990b68', # توكن عام آمن للرفع
        'title': title,
        'author_name': AUTHOR_NAME,
        'content': json.dumps(html_content),
        'return_content': 'true'
    }
    
    try:
        response = requests.post(url, data=payload, timeout=30)
        res_data = response.json()
        if res_data.get('ok'):
            return res_data['result']['url']
        else:
            print(f"❌ خطأ من سيرفر Telegraph: {res_data.get('error')}")
            return None
    except Exception as e:
        print(f"❌ خطأ أثناء الاتصال بـ Telegraph API: {e}")
        return None

def convert_to_telegraph_nodes(paragraphs, scenes):
    """تحويل النص والصور المدمجة إلى هيكل العناصر (Nodes) الذي يفهمه تليجرام"""
    nodes = []
    
    for index, text in enumerate(paragraphs):
        # إضافة نص الفقرة كعنصر P
        nodes.append({"tag": "p", "children": [text]})
        
        # التحقق من وجود مشهد أو صورة مخصصة بعد هذه الفقرة (تطابق الفهرسة من 1)
        scene_at_this_p = next((s for s in scenes if int(s.get('paragraph_index', 0)) == index + 1), None)
        
        if scene_at_this_p and scene_at_this_p.get('image_url'):
            # إضافة الصورة كعنصر IMG مدعوم في Telegraph
            nodes.append({
                "tag": "img",
                "attrs": {"src": scene_at_this_p['image_url']}
            })
            # إضافة وصف بصرى صغير أسفل الصورة كعنوان فرعي مائل
            if scene_at_this_p.get('subject_name'):
                nodes.append({
                    "tag": "figcaption",
                    "children": [f"مشهد: {scene_at_this_p['subject_name']}"]
                })
                
    return nodes

def process_telegraph_publishing():
    # جلب الفصول المترجمة بنجاح ولم تنشر على تليجرام بعد
    chapters_query = db.collection('Chapters') \
        .where(filter=FieldFilter('Novel_Name', '==', TARGET_NOVEL)) \
        .where(filter=FieldFilter('is_translated', '==', True)) \
        .stream()
    
    docs = list(chapters_query)
    docs.sort(key=lambda x: int(''.join(filter(str.isdigit, x.id)) or 0))

    print(f"🚀 بدء تجهيز ونشر الفصول على Telegraph لـ {len(docs)} فصل...")

    for doc in docs:
        doc_data = doc.to_dict()
        ch_num = ''.join(filter(str.isdigit, doc.id))
        
        # تخطي إذا كان الفصل منشوراً مسبقاً على Telegraph
        if doc_data.get('is_published_telegraph'):
            continue

        print(f"📦 جاري تحضير الفصل [{ch_num}] وتجهيز الصور المدمجة...")
        
        content_ar = doc_data.get('content_ar', '')
        if not content_ar:
            print(f"⚠️ الفصل {ch_num} لا يحتوي على نص عربي مترجم، تخطي.")
            continue

        # تنظيف وتقسيم النص إلى فقرات
        paragraphs = [p.trim() for p in content_ar.split('\n') if p.strip() != ""]
        scenes = doc_data.get('analysis_data', {}).get('scenes', [])

        # تحويل المحتوى إلى هيكل التليجرام
        telegraph_nodes = convert_to_telegraph_nodes(paragraphs, scenes)
        
        # عنوان الصفحة على تليجرام
        page_title = f"{doc_data.get('title', f'الفصل {ch_num}')}"

        # رفع الصفحة سحابياً
        telegraph_url = create_telegraph_page(page_title, telegraph_nodes)

        if telegraph_url:
            # حفظ الرابط في Firestore وتأكيد النشر
            doc.reference.update({
                "telegraph_url": telegraph_url,
                "is_published_telegraph": True,
                "published_telegraph_at": firestore.SERVER_TIMESTAMP
            })
            print(f"✅ تم النشر بنجاح! الرابط: {telegraph_url}")
            time.sleep(2) # تجنب الضغط المتتالي على الـ API
        else:
            print(f"❌ فشل نشر الفصل {ch_num}")

if __name__ == "__main__":
    process_telegraph_publishing()
