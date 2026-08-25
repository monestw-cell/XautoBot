# X-Telegram Sync Bot (أداة أتمتة النشر بين X وتلغرام) 🤖🔄

أداة بايثون مؤتمتة لمزامنة التغريدات ونشر المحتوى تلقائياً بين منصتي X (تويتر سابقاً) وقنوات/مجموعات Telegram.

---

## 🌟 نبذة عن المشروع (Overview)

**X-Telegram Sync Bot** هو بوت أتمتة خفيف وسريع، صُمم لمراقبة حسابات محددة أو وسوم على منصة X ونقل التغريدات والوسائط (صور، فيديوهات، نصوص) فورياً وتلقائياً إلى قنوات أو مجموعات التلغرام دون تدخل يدوي، مع سيرفر ويب مدمج للحفاظ على استمرارية التشغيل السحابي.

---

## ✨ المميزات الرئيسية (Key Features)

- **مراقبة ونشر تلقائي وفوري:** تتبع التغريدات الجديدة وإعادة نشرها في قنوات التلغرام بتنسيق أنيق.
- **دعم الوسائط المتعددة:** التعامل مع الصور، مقاطع الفيديو، والروابط التفاعلية.
- **تصفية المحتوى (Content Filtering):** فلترة التغريدات بناءً على الكلمات المفتاحية أو الردود (Excluding Replies/Retweets).
- **نظام تسجيل متقدم (Logging):** تسجيل مفصل للأحداث وتتبع الأخطاء بدقة.
- **خادم فحص الصحة السحابي (Health Server):** مدمج لضمان بقاء البوت فعالاً على منصات مثل Koyeb, Render, Fly.io أو VPS.

---

## 🛠️ التقنيات المستخدمة (Tech Stack)

- **Language:** Python 3.10+
- **X / Twitter API:** `tweepy`
- **Telegram Bot API:** `aiohttp` / `python-telegram-bot`
- **Deployment:** Docker & Python Web Server

---

## 🚀 التثبيت والتشغيل (Installation & Setup)

### 1. الإعداد المحلي
```bash
# استنساخ المستودع
git clone https://github.com/monestw-cell/x-telegram-sync-bot.git
cd x-telegram-sync-bot

# تثبيت التبعيات
pip install -r requirements.txt

# تشغيل البوت بعد ضبط المتغيرات
python main.py
```

### 2. التشغيل عبر Docker
```bash
docker build -t x-telegram-sync-bot .
docker run -d --name x-sync-bot x-telegram-sync-bot
```

---

## 📄 الترخيص (License)
هذا المشروع مرخص تحت رخصة [MIT](LICENSE).
