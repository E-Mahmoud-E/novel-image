import os
import json
import time
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

# --- 1. إعداد الاتصال بـ Firebase (يدعم المحلي و GitHub تلقائياً) ---
if os.environ.get('FIREBASE_KEY'):
    # العمل سحابياً على GitHub Actions
    cred_json = json.loads(os.environ.get('FIREBASE_KEY'))
    cred = credentials.Certificate(cred_json)
else:
    # العمل محلياً على جهازك
    cred_path = r"D:\Novel\worldwide-simulation-era\firestore-key.json"
    cred = credentials.Certificate(cred_path)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --- 2. إعدادات الحماية والبيانات الرسمية لقناتك ---
# يقرأ التوكن بأمان من GitHub Secrets، وفي حال العمل المحلي يمكنك وضعه كمتغير بيئة أو استبداله مؤقتاً هنا
TELEGRAPH_TOKEN = os.environ.get('TELEGRAPH_ACCESS_TOKEN', 'YOUR_LOCAL_TOKEN_HERE')
TARGET_NOVEL = "worldwide-simulation-era"
AUTHOR_NAME = "Ma7moud Elmahdy"
AUTHOR_URL = "https://t.me/NewStyleNovel"

def create_telegraph_page(title, html_content):
    """إنشاء صفحة على Telegraph باستخدام نظام الـ API الرسمي والمحمي"""
    url = "https://api.telegra.ph/createPage"
    
    payload = {
        'access_token': TELEGRAPH_TOKEN,
        'title': title,
        'author_name': AUTHOR_NAME,
        'author_url': AUTHOR_URL,
        'content': json.dumps(html_content),
        'return_content': 'true'
    }
    
    try:
        response = requests.post(url, data=payload, timeout=30)
        res_data = response.json()
        if res_data.get('ok'):
            return res_data['result']['url']
        else:
            print(f"  ❌ خطأ من سيرفر Telegraph: {res_data.get('error')}")
            return None
    except Exception as e:
        print(f"  ❌ خطأ أثناء الاتصال بـ Telegraph API: {e}")
        return None

def convert_to_telegraph_nodes(paragraphs, extracted_scenes):
    """تحويل النص والصور المدمجة (القديمة والجديدة) إلى هيكل العناصر (Nodes) المعتمد في تليجرام"""
    nodes = []
    
    for index, text in enumerate(paragraphs):
        # إضافة نص الفقرة الحالية كعنصر P (نص عادي)
        nodes.append({"tag": "p", "children": [text]})
        
        # البحث عن مشهد أو صورة مخصصة لتكون بَعْد هذه الفقرة (تطابق الفهرسة البرمجية يبدأ من 1)
        scene_at_this_p = next((s for s in extracted_scenes if int(s.get('paragraph_index', 0)) == index + 1), None)
        
        if scene_at_this_p and scene_at_this_p.get('image_url'):
            # إضافة الصورة إلى مستند التليجرام
            nodes.append({
                "tag": "img",
                "attrs": {"src": scene_at_this_p['image_url']}
            })
            # إضافة عنوان فرعي مائل تحت الصورة يحمل اسم المشهد البصري
            if scene_at_this_p.get('subject_name'):
                nodes.append({
                    "tag": "figcaption",
                    "children": [f"Visual Scene: {scene_at_this_p['subject_name']}"]
                })
                
    return nodes

def process_telegraph_publishing():
    # جلب فصول الرواية المستهدفة التي تم ترجمتها بنجاح ولم تنشر بعد على تليجرام
    chapters_query = db.collection('Chapters') \
        .where(filter=FieldFilter('Novel_Name', '==', TARGET_NOVEL)) \
        .where(filter=FieldFilter('is_translated', '==', True)) \
        .stream()
    
    docs = list(chapters_query)
    
    # ترتيب الفصول رقمياً لضمان النشر المتسلسل الصحيح
    docs.sort(key=lambda x: int(''.join(filter(str.isdigit, x.id)) or 0))

    print(f"🚀 بدء تجهيز ونشر الفصول على Telegraph... تم العثور على ({len(docs)}) فصل جاهز.")

    for doc in docs:
        doc_data = doc.to_dict()
        ch_num_str = ''.join(filter(str.isdigit, doc.id))
        if not ch_num_str: continue
        ch_num = int(ch_num_str)
        
        # تخطي إذا كان الفصل منشورا مسبقا لمنع التكرار واستهلاك الـ API
        if doc_data.get('is_published_telegraph'):
            continue

        print(f"📦 جاري تحضير وصياغة مستند الفصل [{ch_num}] سحابياً...")
        
        content_ar = doc_data.get('content_ar', '')
        if not content_ar:
            print(f"  ⚠️ الفصل {ch_num} لا يحتوي على نص عربي مترجم، تخطي التجهيز.")
            continue

        # تنظيف وتقسيم النص العربي إلى فقرات حقيقية ونظيفة
        paragraphs = [p.strip() for p in content_ar.split('\n') if p.strip() != ""]
        
        # دمج الصور القديمة والجديدة معاً لضمان عدم اختفاء أي مخرج بصري قمت بتوليده
        old_scenes = doc_data.get('scenes', [])
        new_scenes = doc_data.get('analysis_data', {}).get('scenes', [])
        
        all_scenes_map = {}
        for scene in (old_scenes + new_scenes):
            if scene and scene.get('paragraph_index'):
                all_scenes_map[int(scene['paragraph_index'])] = scene
        
        extracted_scenes = list(all_scenes_map.values())

        # تحويل المحتوى المدمج بالكامل إلى هيكل الـ Nodes الذي يتطلبه التليجرام
        telegraph_nodes = convert_to_telegraph_nodes(paragraphs, extracted_scenes)
        
        # صياغة عنوان الصفحة الاحترافي المكتوب في أعلى المقال
        page_title = f"{doc_data.get('title', f'الفصل {ch_num}')}"

        # إرسال طلب النشر لـ Telegraph API
        telegraph_url = create_telegraph_page(page_title, telegraph_nodes)

        if telegraph_url:
            # تحديث حقول المستند في Firestore لتسجيل رابط النشر وتأكيده
            doc.reference.update({
                "telegraph_url": telegraph_url,
                "is_published_telegraph": True,
                "published_telegraph_at": firestore.SERVER_TIMESTAMP
            })
            print(f"  ✅ تم النشر بنجاح وحفظ الرابط في Firestore: {telegraph_url}")
            time.sleep(2) # تأخير بمقدار ثانيتين لتجنب الحظر المؤقت من خوادم Telegraph (Rate Limit)
        else:
            print(f"  ❌ فشل نشر وتجهيز صفحة الفصل {ch_num} على تليجرام.")

if __name__ == "__main__":
    process_telegraph_publishing()
    
