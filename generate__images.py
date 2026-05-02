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
    # سيقرأ المفتاح من الـ Secrets التي وضعتها في GitHub
    try:
        cred_json = json.loads(os.getenv("FIREBASE_KEY"))
        cred = credentials.Certificate(cred_json)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        print(f"❌ خطأ في إعدادات Firebase: {e}")

db = firestore.client()

# --- 2. إعدادات GitHub ---
GITHUB_TOKEN = os.getenv("MY_GITHUB_TOKEN")
REPO_OWNER = "E-Mahmoud-E"
REPO_NAME = "novel-image"

def upload_to_github(image_bytes, file_name):
    """وظيفة الرفع لـ GitHub واستخراج الرابط المباشر"""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_name}"
    encoded_content = base64.b64encode(image_bytes).decode("ascii")
    
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Content-Type": "application/json"}
    
    # فحص إذا كان الملف موجوداً لتحديثه بدلاً من إنشاء واحد جديد
    res = requests.get(url, headers=headers)
    sha = res.json().get('sha') if res.status_code == 200 else None

    data = {"message": f"توليد آلي للصورة: {file_name}", "content": encoded_content}
    if sha: data["sha"] = sha
    
    put_res = requests.put(url, json=data, headers=headers)
    if put_res.status_code in [200, 201]:
        # إرجاع الرابط المباشر للصورة (Raw URL)
        return f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{file_name}"
    return None

def process_factory():
    docs = db.collection('descriptions').stream()
    print("🚀 بدء فحص الفصول في Firestore...")

    for doc in docs:
        doc_ref = doc.reference
        data = doc.to_dict()
        scenes = data.get('scenes', [])
        ch_num = data.get('chapter_number', '0')

        updated_scenes = []
        has_new_images = False

        for scene in scenes:
            existing_url = scene.get('image_url') or scene.get('url')
            if existing_url:
                print(f"⏩ تخطي: فصل {ch_num} - الصورة موجودة.")
                updated_scenes.append(scene)
                continue

            p_index = scene.get('paragraph_index', 0)
            subject = scene.get('subject_name', 'Scene').replace(" ", "")
            image_name = f"Ch{ch_num}_{p_index}_{subject}.png"
            
            visual_desc = scene.get('visual_description', '')
            safe_prompt = urllib.parse.quote(visual_desc)
            img_api_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1024&height=1024&nologo=true"

            # --- 👇 تطوير: محاولة الرسم أكثر من مرة في حال حدوث Timeout ---
            success = False
            for attempt in range(3): # سيحاول 3 مرات
                try:
                    print(f"🎨 محاولة {attempt+1}: رسم صورة {image_name}...")
                    img_res = requests.get(img_api_url, timeout=120) # زدنا الوقت لـ 120 ثانية
                    
                    if img_res.status_code == 200:
                        github_link = upload_to_github(img_res.content, image_name)
                        if github_link:
                            print(f"✅ تم الرفع: {github_link}")
                            scene['image_url'] = github_link
                            has_new_images = True
                            success = True
                            break # نجحنا! اخرج من حلقة المحاولات
                    else:
                        print(f"⚠️ السيرفر رد برمز: {img_res.status_code}، سأحاول مجدداً..")
                
                except requests.exceptions.Timeout:
                    print(f"⏳ انتهى الوقت (Timeout) في المحاولة {attempt+1}..")
                except Exception as e:
                    print(f"❌ خطأ غير متوقع: {e}")
                
                time.sleep(5) # انتظر 5 ثوانٍ قبل المحاولة التالية لراحة السيرفر

            if not success:
                print(f"❌ فشل رسم المشهد {p_index} بعد 3 محاولات، سأنتقل للتالي.")
            
            updated_scenes.append(scene)

        if has_new_images:
            doc_ref.update({'scenes': updated_scenes})
            print(f"📝 تم تحديث الفصل {ch_num} في Firestore.")

if __name__ == "__main__":
    process_factory()
