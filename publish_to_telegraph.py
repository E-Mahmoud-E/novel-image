import os
import json
import time
import requests # تم إضافة المكتبة لإرسال الرسائل عبر الـ API
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from telegraph import Telegraph

# --- 1. إعداد الاتصال بـ Firebase ---
if os.environ.get('FIREBASE_KEY'):
    cred_json = json.loads(os.environ.get('FIREBASE_KEY'))
    cred = credentials.Certificate(cred_json)
else:
    cred_path = r"D:\Novel\worldwide-simulation-era\firestore-key.json"
    cred = credentials.Certificate(cred_path)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --- 2. إعدادات تليجرام المضافة (تُقرأ بأمان من بيئة العمل) ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.environ.get('TELEGRAM_CHANNEL_ID')

# --- 3. إعدادات Telegraph ---
telegraph_client = Telegraph()
TELEGRAPH_TOKEN = os.environ.get('TELEGRAPH_ACCESS_TOKEN')
if TELEGRAPH_TOKEN:
    telegraph_client.init_app(access_token=TELEGRAPH_TOKEN)
else:
    telegraph_client.create_account(short_name='Ma7moud')

TARGET_NOVEL = "worldwide-simulation-era"
AUTHOR_NAME = "Ma7moud Elmahdy"
AUTHOR_URL = "https://t.me/NewStyleNovel"

def convert_to_telegraph_nodes(paragraphs, extracted_scenes):
    nodes = []
    for index, text in enumerate(paragraphs):
        nodes.append({"tag": "p", "children": [text]})
        scene_at_this_p = next((s for s in extracted_scenes if int(s.get('paragraph_index', 0)) == index + 1), None)
        if scene_at_this_p and scene_at_this_p.get('image_url'):
            nodes.append({
                "tag": "img",
                "attrs": {"src": scene_at_this_p['image_url']}
            })
            if scene_at_this_p.get('subject_name'):
                nodes.append({
                    "tag": "p",
                    "children": [{"tag": "i", "children": [f"Visual Scene: {scene_at_this_p['subject_name']}"]}]
                })
    return nodes

def process_telegraph_publishing():
    chapters_query = db.collection('Chapters') \
        .where(filter=FieldFilter('Novel_Name', '==', TARGET_NOVEL)) \
        .where(filter=FieldFilter('is_translated', '==', True)) \
        .stream()
    
    docs = list(chapters_query)
    docs.sort(key=lambda x: int(''.join(filter(str.isdigit, x.id)) or 0))

    print(f"🚀 بدء تجهيز ونشر الفصول... تم العثور على ({len(docs)}) فصل.")

    for doc in docs:
        doc_data = doc.to_dict()
        ch_num_str = ''.join(filter(str.isdigit, doc.id))
        if not ch_num_str: continue
        ch_num = int(ch_num_str)
        
        if doc_data.get('is_published_telegraph'):
            continue

        print(f"📦 جاري تحضير وصياغة مستند الفصل [{ch_num}]...")
        
        content_ar = doc_data.get('content_ar', '')
        if not content_ar:
            print(f"  ⚠️ الفصل {ch_num} لا يحتوي على نص عربي مترجم، تخطي.")
            continue

        paragraphs = [p.strip() for p in content_ar.split('\n') if p.strip() != ""]
        
        old_scenes = doc_data.get('scenes', []) or []
        new_scenes = doc_data.get('analysis_data', {}).get('scenes', []) or []
        
        all_scenes_map = {}
        for scene in (old_scenes + new_scenes):
            if scene and scene.get('paragraph_index'):
                all_scenes_map[int(scene['paragraph_index'])] = scene
        
        extracted_scenes = list(all_scenes_map.values())
        telegraph_nodes = convert_to_telegraph_nodes(paragraphs, extracted_scenes)
        page_title = f"{doc_data.get('title', f'الفصل {ch_num}')}"

        try:
            # أولاً: توليد صفحة المعاينة الفورية
            response = telegraph_client.create_page(
                title=page_title,
                author_name=AUTHOR_NAME,
                author_url=AUTHOR_URL,
                content=telegraph_nodes
            )
            telegraph_url = response['url']
            print(f"  ✅ تم إنشاء رابط Telegraph: {telegraph_url}")
            
            # ثانياً (الزيادة هنا): إرسال الرابط فوراً إلى قناة التليجرام عبر البوت
            if TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID:
                telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                
                # نص الرسالة التي ستظهر للمشاهدين في القناة
                message_text = f"📢 *تمت إضافة فصل جديد للرواية!*\n\n📖 *{page_title}*\n\nاقرأ الآن مباشرة عبر المعاينة الفورية السريعة وبدون إعلانات:\n{telegraph_url}"
                
                payload = {
                    "chat_id": TELEGRAM_CHANNEL_ID,
                    "text": message_text,
                    "parse_mode": "Markdown"
                }
                
                telegram_res = requests.post(telegram_api_url, json=payload, timeout=15)
                if telegram_res.status_code == 200:
                    print("  📢 تم إرسال الإشعار بنجاح إلى قناة تليجرام.")
                else:
                    print(f"  ❌ فشل إرسال الإشعار للقناة. كود: {telegram_res.status_code}")
            else:
                print("  ⚠️ تخطي إرسال الإشعار لتليجرام لعدم وجود توكن البوت أو معرف القناة في البيئة الحالية (عمل محلي).")
            
            # ثالثاً: تحديث المستند في Firestore بعد النشر الفعلي والنجاح كاملاً
            doc.reference.update({
                "telegraph_url": telegraph_url,
                "is_published_telegraph": True,
                "published_telegraph_at": firestore.SERVER_TIMESTAMP
            })
            print(f"  💾 تم تحديث Firestore للفصل {ch_num}.")
            time.sleep(2)
            
        except Exception as e:
            print(f"  ❌ فشل نشر وتجهيز صفحة الفصل {ch_num}. الخطأ: {e}")

if __name__ == "__main__":
    process_telegraph_publishing()
    
