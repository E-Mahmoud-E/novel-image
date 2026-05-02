import os
import json
import base64
import requests
import time
import urllib.parse
import firebase_admin
from firebase_admin import credentials, firestore

# 1. إعداد الاتصال بـ Firestore باستخدام المفتاح السري
if not firebase_admin._apps:
    # جلب المفتاح من أسرار GitHub
    cred_json = json.loads(os.getenv("FIREBASE_KEY"))
    cred = credentials.Certificate(cred_json)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# 2. إعدادات GitHub (كما فعلنا سابقاً)
GITHUB_TOKEN = os.getenv("MY_GITHUB_TOKEN")
REPO_OWNER = "E-Mahmoud-E"
REPO_NAME = "novel-image"

def upload_to_github(image_bytes, file_name):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_name}"
    encoded_content = base64.b64encode(image_bytes).decode("ascii")
    
    # التحقق إذا كان الملف موجوداً لتحديثه
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    res = requests.get(url, headers=headers)
    sha = res.json().get('sha') if res.status_code == 200 else None

    data = {"message": f"توليد صورة: {file_name}", "content": encoded_content}
    if sha: data["sha"] = sha
    
    response = requests.put(url, json=data, headers=headers)
    return response.status_code in [200, 201]

def process_from_firestore():
    # هنا ضع اسم الـ Collection الخاص بك في Firestore (مثلاً 'chapters_descriptions')
    docs = db.collection('descriptions').stream()

    for doc in docs:
        data = doc.to_dict()
        # نفترض أن كل وثيقة تحتوي على قائمة 'scenes' كما في ملفاتك السابقة
        scenes = data.get('scenes', [])
        ch_num = data.get('chapter_number', '0')

        for scene in scenes:
            p_index = scene['paragraph_index']
            subject = scene['subject_name'].replace(" ", "")
            image_name = f"Ch{ch_num}_{p_index}_{subject}.png"

            print(f"🎨 رسم وصورة لـ: {image_name}")
            
            safe_prompt = urllib.parse.quote(scene['visual_description'])
            img_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1024&height=1024&nologo=true"

            img_res = requests.get(img_url)
            if img_res.status_code == 200:
                if upload_to_github(img_res.content, image_name):
                    print(f"✅ تم الرفع: {image_name}")
            
            time.sleep(2)

if __name__ == "__main__":
    process_from_firestore()
