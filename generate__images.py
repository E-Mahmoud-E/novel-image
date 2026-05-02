import os
import json
import requests
import urllib.parse
import firebase_admin
from firebase_admin import credentials, firestore
import cloudinary
import cloudinary.uploader

# --- 1. إعداد الاتصال بـ Firestore ---
if not firebase_admin._apps:
    try:
        # قراءة المفتاح من GitHub Secrets
        cred_json = json.loads(os.getenv("FIREBASE_KEY"))
        cred = credentials.Certificate(cred_json)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        print(f"❌ خطأ في إعدادات Firebase: {e}")
        exit(1)

db = firestore.client()

# --- 2. إعدادات Cloudinary (من GitHub Secrets) ---
cloudinary.config( 
  cloud_name = "dnney0ffw", 
  api_key = "172942244898523", 
  api_secret = "vw9j3TFEaIVuEuiv3cEfiPruVLA" ,
  secure = True
)

def upload_to_cloudinary(image_content, file_name):
    """رفع الصورة إلى Cloudinary واسترجاع الرابط المباشر"""
    try:
        public_id = os.path.splitext(file_name)[0]
        upload_result = cloudinary.uploader.upload(
            image_content,
            public_id = public_id,
            folder = "novel_scenes", # المجلد داخل Cloudinary
            overwrite = True,
            resource_type = "image"
        )
        return upload_result.get("secure_url")
    except Exception as e:
        print(f"    ❌ خطأ أثناء الرفع لـ Cloudinary: {e}")
        return None

def process_factory():
    collection_name = 'Chapters' 
    # جلب جميع الوثائق
    docs = list(db.collection(collection_name).stream())
    
    # ترتيب الفصول لضمان التخطي الصحيح
    try:
        docs.sort(key=lambda x: int(x.to_dict().get('id', 0)))
    except:
        pass

    print(f"🚀 بدء الفحص... تم العثور على ({len(docs)}) وثيقة.")

    for doc in docs:
        data = doc.to_dict()
        ch_id_raw = data.get('id', '0')
        
        # تحويل الرقم للمقارنة
        try:
            ch_num = int(ch_id_raw)
        except ValueError:
            ch_num = 0

        # --- 🛡️ تخطي أول 250 فصل ---
        if ch_num <= 250:
            continue

        doc_ref = doc.reference
        scenes = data.get('scenes', [])
        has_new_images = False
        updated_scenes = []

        print(f"📖 جاري معالجة الفصل: {ch_num}")

        for scene in scenes:
            current_url = scene.get('image_url', '')
            
            # تخطي إذا كانت الصورة موجودة بالفعل على Cloudinary
            if current_url and "cloudinary.com" in current_url:
                updated_scenes.append(scene)
                continue

            p_index = scene.get('paragraph_index', 0)
            subject = scene.get('subject_name', 'Scene').replace(" ", "_")
            image_name = f"Ch{ch_num}_{p_index}_{subject}"
            
            visual_desc = scene.get('visual_description', '')
            if not visual_desc:
                updated_scenes.append(scene)
                continue

            # توليد الصورة عبر Pollinations AI
            safe_prompt = urllib.parse.quote(visual_desc)
            img_api_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1024&height=1024&nologo=true"

            try:
                print(f"  🎨 رسم صورة للمشهد {p_index}...")
                img_res = requests.get(img_api_url, timeout=120) 
                
                if img_res.status_code == 200:
                    # الرفع لـ Cloudinary
                    cloudinary_link = upload_to_cloudinary(img_res.content, image_name)
                    
                    if cloudinary_link:
                        print(f"  ✅ تم الرفع: {cloudinary_link}")
                        scene['image_url'] = cloudinary_link
                        has_new_images = True
                    else:
                        print(f"  ❌ فشل رفع الصورة.")
                else:
                    print(f"  ⚠️ سيرفر الرسم غير متاح حالياً (Code: {img_res.status_code})")
            
            except Exception as e:
                print(f"  ❌ خطأ فني: {e}")
            
            updated_scenes.append(scene)

        # حفظ التعديلات في Firestore
        if has_new_images:
            doc_ref.update({'scenes': updated_scenes})
            print(f"📝 تم تحديث بيانات الفصل {ch_num} بنجاح.")

if __name__ == "__main__":
    process_factory()
