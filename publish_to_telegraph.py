import os
import json
import time
import requests
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

# --- 2. إعدادات تليجرام ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.environ.get('TELEGRAM_CHANNEL_ID')

# --- 3. إعدادات Telegraph ---
TELEGRAPH_TOKEN = os.environ.get('TELEGRAPH_ACCESS_TOKEN')
if TELEGRAPH_TOKEN:
    telegraph_client = Telegraph(access_token=TELEGRAPH_TOKEN)
else:
    telegraph_client = Telegraph()
    telegraph_client.create_account(short_name='Ma7moud')

TARGET_NOVEL = "World Simulation Era" 
AUTHOR_NAME = "Ma7moud Elmahdy"
AUTHOR_URL = "https://t.me/NewStyleNovel"

def convert_to_telegraph_nodes(paragraphs, extracted_scenes, alt_lang_url, is_arabic=True, prev_url=None, next_url=None):
    """صياغة محتوى الفصل: التحكم في اللغة، التنسيق (الصور أولاً)، وأزرار التنقل"""
    nodes = []
    
    # 💡 1. شريط علوي لتبديل اللغة (يربط بين صفحتي Telegraph العربية والإنجليزية مباشرة)
    if alt_lang_url:
        lang_text = "🇺🇸 Read in English" if is_arabic else "🇪🇬 القراءة بالعربية"
        nodes.append({
            "tag": "p",
            "children": [
                {"tag": "a", "attrs": {"href": alt_lang_url}, "children": [lang_text]}
            ]
        })
        nodes.append({"tag": "hr"})

    # 💡 2. بناء متن الفصل (تأمين وضع الصورة قبل الفقرة التابعة لها)
    for index, text in enumerate(paragraphs):
        scene_at_this_p = next((s for s in extracted_scenes if int(s.get('paragraph_index', 0)) == index + 1), None)
        
        # حقن الصورة أولاً إذا وجدت
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
        
        # إلحاق نص الفقرة
        nodes.append({"tag": "p", "children": [text]})
    
    # 💡 3. شريط التنقل السفلي بين الفصول بنفس اللغة
    nodes.append({"tag": "hr"})
    nav_links = []
    
    if is_arabic:
        if prev_url:
            nav_links.append({"tag": "a", "attrs": {"href": prev_url}, "children": ["⬅️ الفصل السابق"]})
        else:
            nav_links.append("⏮️ بداية الرواية")
        nav_links.append("  |  ")
        if next_url:
            nav_links.append({"tag": "a", "attrs": {"href": next_url}, "children": ["الفصل التالي ➡️"]})
        else:
            nav_links.append("⏭️ أحدث فصل")
    else:
        if prev_url:
            nav_links.append({"tag": "a", "attrs": {"href": prev_url}, "children": ["⬅️ Previous Chapter"]})
        else:
            nav_links.append("⏮️ First Chapter")
        nav_links.append("  |  ")
        if next_url:
            nav_links.append({"tag": "a", "attrs": {"href": next_url}, "children": ["Next Chapter ➡️"]})
        else:
            nav_links.append("⏭️ Latest Chapter")

    nodes.append({
        "tag": "p",
        "children": nav_links
    })
    
    return nodes

def process_telegraph_publishing():
    chapters_query = db.collection('Chapters') \
        .where(filter=FieldFilter('Novel_Name', '==', TARGET_NOVEL)) \
        .stream()
    
    docs = list(chapters_query)
    if not docs:
        print(f"❌ لم يتم العثور على أي فصول.")
        return

    docs.sort(key=lambda x: int(''.join(filter(str.isdigit, x.id)) or 0))
    
    # بناء خرائط روابط التنقل لكل لغة بشكل مستقل
    ar_url_map = {}
    en_url_map = {}
    for d in docs:
        ch_id = int(''.join(filter(str.isdigit, d.id)) or 0)
        data = d.to_dict()
        ar_url_map[ch_id] = data.get('telegraph_url')
        en_url_map[ch_id] = data.get('telegraph_en_url')

    print(f"🚀 بدء تجهيز الصفحات الثنائية (عربي/إنجليزي)...")
    published_count = 0

    for doc in docs:
        doc_data = doc.to_dict()
        ch_num = int(''.join(filter(str.isdigit, doc.id)) or 0)
        if not ch_num: continue
        
        # إذا تم نشر النسختين مسبقاً، نتخطى الفصل
        if doc_data.get('is_published_telegraph') is True and doc_data.get('telegraph_en_url'):
            continue

        content_ar = doc_data.get('content_ar', '')
        content_en = doc_data.get('content', '') # النص الإنجليزي الأصلي
        
        if not content_ar:
            continue

        print(f"📦 صياغة الفصل [{ch_num}] بالنسختين العربية والإنجليزية...")
        
        # تنظيف النصوص
        paragraphs_ar = [p.strip() for p in content_ar.split('\n') if p.strip() != ""]
        paragraphs_en = [p.strip() for p in content_en.split('\n') if p.strip() != ""]
        
        # تجهيز الصور المدمجة
        old_scenes = doc_data.get('scenes', []) or []
        new_scenes = doc_data.get('analysis_data', {}).get('scenes', []) or []
        all_scenes_map = {}
        for scene in (old_scenes + new_scenes):
            if scene and scene.get('paragraph_index'):
                all_scenes_map[int(scene['paragraph_index'])] = scene
        extracted_scenes = list(all_scenes_map.values())

        # روابط التنقل المحيطة بكل لغة
        prev_ar = ar_url_map.get(ch_num - 1)
        next_ar = ar_url_map.get(ch_num + 1)
        prev_en = en_url_map.get(ch_num - 1)
        next_en = en_url_map.get(ch_num + 1)

        try:
            # 1. إنشاء الصفحة الإنجليزية أولاً للحصول على رابطها ومشاركته في الصفحة العربية
            en_title = f"Chapter {ch_num}: {doc_data.get('title_en', 'Worldwide Simulation Era')}"
            en_nodes = convert_to_telegraph_nodes(paragraphs_en, extracted_scenes, alt_lang_url=None, is_arabic=False, prev_url=prev_en, next_url=next_en)
            
            en_res = telegraph_client.create_page(title=en_title, author_name=AUTHOR_NAME, author_url=AUTHOR_URL, content=en_nodes)
            telegraph_en_url = en_res['url']
            en_url_map[ch_num] = telegraph_en_url

            # 2. إنشاء الصفحة العربية وتمرير رابط الصفحة الإنجليزية بداخلها كزر تبديل لغة
            ar_title = f"{doc_data.get('title', f'الفصل {ch_num}')}"
            ar_nodes = convert_to_telegraph_nodes(paragraphs_ar, extracted_scenes, alt_lang_url=telegraph_en_url, is_arabic=True, prev_url=prev_ar, next_url=next_ar)
            
            ar_res = telegraph_client.create_page(title=ar_title, author_name=AUTHOR_NAME, author_url=AUTHOR_URL, content=ar_nodes)
            telegraph_ar_url = ar_res['url']
            ar_url_map[ch_num] = telegraph_ar_url

            # 3. تحديث الصفحة الإنجليزية لوضع رابط النسخة العربية بداخلها (ربط متبادل بالكامل)
            updated_en_nodes = convert_to_telegraph_nodes(paragraphs_en, extracted_scenes, alt_lang_url=telegraph_ar_url, is_arabic=False, prev_url=prev_en, next_url=next_en)
            telegraph_client.edit_page(
                path=en_res['path'],
                title=en_title,
                author_name=AUTHOR_NAME,
                author_url=AUTHOR_URL,
                content=updated_en_nodes
            )

            # 4. إرسال النسخة العربية للقناة
            if TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID:
                telegram_api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                message_text = f"📢 *تمت إضافة فصل جديد للرواية!*\n\n📖 *{ar_title}*\n\nاقرأ الآن بالعربية أو الإنجليزية مباشرة عبر المعاينة الفورية:\n{telegraph_ar_url}"
                payload = {"chat_id": TELEGRAM_CHANNEL_ID, "text": message_text, "parse_mode": "Markdown"}
                requests.post(telegram_api_url, json=payload, timeout=15)

            # 5. حفظ الرابطين في Firestore وتأكيد النشر
            doc.reference.update({
                "telegraph_url": telegraph_ar_url,
                "telegraph_en_url": telegraph_en_url,
                "is_published_telegraph": True,
                "published_telegraph_at": firestore.SERVER_TIMESTAMP
            })
            
            print(f"  ✅ تم ربط اللغتين وتحديث الفصل {ch_num} سحابياً بنجاح.")
            published_count += 1
            time.sleep(2)
            
        except Exception as e:
            print(f"  ❌ خطأ في معالجة الفصل {ch_num}: {e}")

    print(f"🏁 اكتملت العملية! تم نشر وتحديث: ({published_count}) فصل باللغتين.")

if __name__ == "__main__":
    process_telegraph_publishing()
    
