import os
import json
import requests
import urllib.parse
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
import cloudinary
import cloudinary.uploader

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

# --- 2. إعدادات Cloudinary (تأخذ من السحابة أو الثوابت محلياً) ---
cloudinary.config( 
    cloud_name = os.environ.get('CLOUDINARY_NAME'), 
    api_key = os.environ.get('CLOUDINARY_KEY'), 
    api_secret = os.environ.get('CLOUDINARY_SECRET'),
    secure = True
)

# اسم الرواية المستهدفة
TARGET_NOVEL = "Worldwide Simulation Era"

def upload_to_cloudinary(image_content, file_name, novel_name):
    """رفع الصورة إلى مجلد خاص بالرواية في Cloudinary واسترجاع الرابط المباشر"""
    try:
        public_id = os.path.splitext(file_name)[0]
        upload_result = cloudinary.uploader.upload(
            image_content,
            public_id = public_id,
            folder = f"Novels/{novel_name}/Scenes", # تنظيم الملفات داخل مجلد الرواية
            overwrite = True,
            resource_type = "image"
        )
        return upload_result.get("secure_url")
    except Exception as e:
        print(f"    ❌ خطأ أثناء الرفع لـ Cloudinary: {e}")
        return None

def process_factory():
    # جلب فصول الرواية المستهدفة التي تم تحليلها بنجاح
    chapters_query = db.collection('Chapters') \
        .where(filter=FieldFilter('Novel_Name', '==', TARGET_NOVEL)) \
        .where(filter=FieldFilter('is_analyzed', '==', True)) \
        .stream()
    
    docs = list(chapters_query)
    
    # ترتيب الفصول رقمياً
    docs.sort(key=lambda x: int(''.join(filter(str.isdigit, x.id)) or 0))

    print(f"🚀 بدء فحص الرسم... تم العثور على ({len(docs)}) فصل جاهز للرسم.")

    for doc in docs:
        ch_num_str = ''.join(filter(str.isdigit, doc.id))
        if not ch_num_str: continue
        ch_num = int(ch_num_str)

        # --- 🛡️ تخطي أول 250 فصل ---
        if ch_num <= 250:
            continue

        doc_data = doc.to_dict()
        analysis_data = doc_data.get('analysis_data', {})
        
        # قراءة المشاهد من الحقل الجديد المعالج بواسطة أداة التحليل
        scenes = analysis_data.get('scenes', [])
        if not scenes:
            continue

        has_new_images = False
        print(f"📖 جاري فحص ورسم صور الفصل: {ch_num}")

        for scene in scenes:
            current_url = scene.get('image_url', '')
            
            # تخطي إذا كانت الصورة موجودة ومرفوعة بالفعل على Cloudinary
            if current_url and "cloudinary.com" in current_url:
                continue

            p_index = scene.get('paragraph_index', 0)
            subject = scene.get('subject_name', 'Scene').replace(" ", "_")
            image_name = f"Ch{ch_num}_{p_index}_{subject}"
            
            raw_visual_desc = scene.get('visual_description', '')
            if not raw_visual_desc:
                continue

            # --- 🛡️ حقن الملامح الذكورية للبطل وتعديل الـ Prompt ---
            subject_lower = subject.lower()
            if "hero" in subject_lower or "protagonist" in subject_lower or "lin_fan" in subject_lower:
                # إجبار النموذج على رسم ملامح ذكورية حادة لمنع خطأ "البطل الأنثى"
                final_desc = f"masculine facial features, handsome male protagonist, alpha male, ancient robes, {raw_visual_desc}"
                print(f"  ⚡ تم رصد شخصية البطل. تم حقن القواعد الذكورية في الوصف البصري.")
            else:
                final_desc = raw_visual_desc

            # توليد الصورة عبر Pollinations AI
            safe_prompt = urllib.parse.quote(final_desc)
            img_api_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1024&height=1024&nologo=true"

            try:
                print(f"  🎨 رسم صورة للمشهد {p_index}...")
                img_res = requests.get(img_api_url, timeout=120) 
                
                if img_res.status_code == 200:
                    # الرفع لـ Cloudinary مع تحديد مجلد الرواية
                    cloudinary_link = upload_to_cloudinary(img_res.content, image_name, TARGET_NOVEL)
                    
                    if cloudinary_link:
                        print(f"  ✅ تم الرفع والتحديث: {cloudinary_link}")
                        scene['image_url'] = cloudinary_link
                        has_new_images = True
                    else:
                        print(f"  ❌ فشل رفع الصورة.")
                else:
                    print(f"  ⚠️ سيرفر الرسم غير متاح حالياً (Code: {img_res.status_code})")
            
            except Exception as e:
                print(f"  ❌ خطأ فني: {e}")
            
        # تحديث الحقل السحابي المدمج في Firestore إذا تم توليد صور جديدة
        if has_new_images:
            doc.reference.update({
                'analysis_data.scenes': scenes,
                'is_drawn': True
            })
            print(f"📝 تم تحديث مستند الفصل {ch_num} بالروابط الجديدة.")

if __name__ == "__main__":
    process_factory()
