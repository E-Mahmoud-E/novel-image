import os
import json
import base64
import requests
import time
import urllib.parse
import firebase_admin
from firebase_admin import credentials, firestore

# --- 1. إعداد الاتصال بـ Firestore ---
if not firebase_admin._apps:
    try:
        # قراءة المفتاح من بيئة العمل (GitHub Secrets)
        cred_json = json.loads(os.getenv("FIREBASE_KEY"))
        cred = credentials.Certificate(cred_json)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        print(f"❌ خطأ في إعدادات Firebase: {e}")

db = firestore.client()

# --- 2. إعدادات GitHub (تأكد من صحة هذه البيانات) ---
GITHUB_TOKEN = os.getenv("MY_GITHUB_TOKEN")
REPO_OWNER = "E-Mahmoud-E"
REPO_NAME = "novel-image"

def upload_to_github(image_bytes, file_name):
    """رفع الصورة إلى GitHub واسترجاع الرابط المباشر"""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_name}"
    encoded_content = base64.b64encode(image_bytes).decode("ascii")
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Content-Type": "application/json"}
    
    # فحص إذا كان الملف موجوداً بالفعل لتحديثه (SHA)
    res = requests.get(url, headers=headers)
    sha = res.json().get('sha') if res.status_code == 200 else None

    data = {"message": f"توليد آلي: {file_name}", "content": encoded_content}
    if sha: data["sha"] = sha
    
    put_res = requests.put(url, json=data, headers=headers)
    if put_res.status_code in [200, 201]:
        return f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{file_name}"
    return None

def process_factory():
    # --- 💡 تنبيه هام: تأكد أن الاسم 'descriptions' هو نفسه الموجود في Firestore ---
    collection_name = 'descriptions' 
    docs = list(db.collection(collection_name).stream())
    
    print(f"🚀 بدء الفحص... تم العثور على ({len(docs)}) وثيقة في مجموعة [{collection_name}]")

    if len(docs) == 0:
        print(f"⚠️ تحذير: لم نجد أي بيانات! تأكد من أن اسم المجموعة هو '{collection_name}' وليس شيئاً آخر.")
        return

    for doc in docs:
        doc_ref = doc.reference
        data = doc.to_dict()
        scenes = data.get('scenes', [])
        ch_num = data.get('chapter_number', '0')

        updated_scenes = []
        has_new_images = False

        print(f"📖 فحص الفصل رقم: {ch_num}")

        for scene in scenes:
            # 🔍 فحص هل الصورة موجودة مسبقاً في أي حقل (image_url أو url أو link)
            if any(scene.get(k) for k in ['image_url', 'url', 'link']):
                print(f"  ⏩ تخطي المشهد {scene.get('paragraph_index')}: موجود بالفعل.")
                updated_scenes.append(scene)
                continue

            p_index = scene.get('paragraph_index', 0)
            subject = scene.get('subject_name', 'Scene').replace(" ", "")
            image_name = f"Ch{ch_num}_{p_index}_{subject}.png"
            
            visual_desc = scene.get('visual_description', '')
            if not visual_desc: continue

            safe_prompt = urllib.parse.quote(visual_desc)
            img_api_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1024&height=1024&nologo=true"

            # محاولة الرسم مع معالجة الأخطاء والـ Timeout
            try:
                print(f"  🎨 جاري رسم صورة جديدة: {image_name}...")
                # انتظر حتى 180 ثانية (3 دقائق) لإعطاء فرصة للسيرفر البطيء
                img_res = requests.get(img_api_url, timeout=180) 
                
                if img_res.status_code == 200:
                    github_link = upload_to_github(img_res.content, image_name)
                    if github_link:
                        print(f"  ✅ تم الرفع بنجاح: {github_link}")
                        scene['image_url'] = github_link
                        has_new_images = True
                    else:
                        print(f"  ❌ فشل الرفع لـ GitHub.")
                else:
                    print(f"  ⚠️ سيرفر الرسم رد بـ: {img_res.status_code}")
            
            except Exception as e:
                print(f"  ❌ خطأ أثناء معالجة المشهد: {e}")
            
            updated_scenes.append(scene)

        # تحديث Firestore فقط في حالة وجود صور جديدة فعلياً
        if has_new_images:
            doc_ref.update({'scenes': updated_scenes})
            print(f"📝 تم تحديث بيانات الفصل {ch_num} في Firestore.")

if __name__ == "__main__":
    process_factory()
