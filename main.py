import os
import asyncio
import datetime
import tweepy
import google.generativeai as genai
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# إعداد متغيرات البيئة (Environment Variables)
API_ID = int(os.environ.get("TELEGRAM_API_ID", 0))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "")
SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING", "")
SOURCE_CHANNEL = os.environ.get("SOURCE_CHANNEL", "")  # معرف القناة العامة مثل @username

X_CONSUMER_KEY = os.environ.get("X_CONSUMER_KEY", "")
X_CONSUMER_SECRET = os.environ.get("X_CONSUMER_SECRET", "")
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN", "")
X_ACCESS_TOKEN_SECRET = os.environ.get("X_ACCESS_TOKEN_SECRET", "")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# تحويل مدة التجميع من دقائق إلى ثوانٍ (الافتراضي 20 دقيقة)
BATCH_INTERVAL = int(os.environ.get("BATCH_INTERVAL_MINUTES", 20)) * 60 

# إعداد عميل منصة X باستخدام OAuth 1.0a للنشر عبر واجهة v2
x_client = tweepy.Client(
    consumer_key=X_CONSUMER_KEY,
    consumer_secret=X_CONSUMER_SECRET,
    access_token=X_ACCESS_TOKEN,
    access_token_secret=X_ACCESS_TOKEN_SECRET
)

# إعداد واجهة برمجة تطبيقات Gemini
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('gemini-1.5-flash')

# المتغيرات العامة لإدارة الحالة
message_queue = []
posts_sent_today = 0
last_reset_date = datetime.date.today()
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", 50))

# --- خادوم وهمي لفحص الصحة لتخطي قيود منصة Render ---
async def handle_health_check(reader, writer):
    while True:
        data = await reader.read(1024)
        if not data:
            break
        response = "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nOK"
        writer.write(response.encode('utf-8'))
        await writer.drain()
        break
    writer.close()

async def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = await asyncio.start_server(handle_health_check, '0.0.0.0', port)
    print(f" [Render Info] Health check server successfully running on port {port}")
    async with server:
        await server.serve_forever()

# --- المنطق البرمجي للتجميع التلقائي والتلخيص عبر الذكاء الاصطناعي ---
async def process_queue_periodically():
    global message_queue, posts_sent_today, last_reset_date
    print(f" [Scheduler] Queue processor active. Windows: Every {BATCH_INTERVAL / 60} minutes.")
    
    while True:
        await asyncio.sleep(BATCH_INTERVAL)
        
        # إعادة تصفير العداد عند بدء يوم جديد
        if datetime.date.today() > last_reset_date:
            posts_sent_today = 0
            last_reset_date = datetime.date.today()
            print(" [Counter] A new day started. Post counter has been reset to 0.")

        if not message_queue:
            continue

        if posts_sent_today >= DAILY_LIMIT:
            print(f" [Warning] Daily posting limit ({DAILY_LIMIT}) reached. Clearing queue.")
            message_queue.clear()
            continue

        # دمج كافة المنشورات المستلمة في نص واحد عريض لتقديمه للذكاء الاصطناعي
        combined_text = "\n---\n".join(message_queue)
        message_queue.clear()  # تفريغ الطابور للمستجدات القادمة

        # توجيه الـ Prompt المعدل بدقة لتوثيق الكارثة والمجاعة بطلبك
        prompt = (
            "أنت صحفي ومحرر مسؤول عن إدارة حساب مستقل على منصة X يوثق الأوضاع الإنسانية، "
            "مسار الحياة اليومية، وتطورات الكارثة والمجاعة في قطاع غزة من الداخل.\n"
            "قم بصياغة ملخص تغريدة واحدة احترافية ومؤثرة باللغة العربية بناءً على الأخبار والمستجدات التالية المتجمعة من الميدان:\n"
            f"{combined_text}\n\n"
            "الشروط الإلزامية الصارمة:\n"
            "1. يجب ألا يتجاوز النص النهائي 260 حرفاً مطلقاً (حفاظاً على مساحة أمان لمنصة X).\n"
            "2. ركز تماماً على تفاصيل الواقع الإنساني الحالي، ومستجدات الأزمة، وقصص الصمود والتحديات المعيشية.\n"
            "3. انقل تفاصيل نقص الغذاء، وسوء التغذية، والمجاعة بدقة وأمانة إذا وردت في المنشورات الأصلية لتوثيق حجم الكارثة الإنسانية.\n"
            "4. احذف ونظّف أي معرفات قنوات أخرى (مثل @username)، أو روابط تليجرام، أو عبارات ترويجية وإعلانية الأصلية.\n"
            "5. الصياغة يجب أن تكون مباشرة وقوية وبأسلوب رصين بدون أي مقدمات وبدون هاشتاغات.\n"
            "أعطني نص التغريدة النهائي مباشرةً."
        )

        try:
            print(" [Gemini API] Requesting dynamic text summarization...")
            response = gemini_model.generate_content(prompt)
            tweet_text = response.text.strip()
            
            # فحص أمان أخير لطول الحروف قبل الإرسال
            if len(tweet_text) > 280:
                tweet_text = tweet_text[:276] + "..."

            # النشر عبر API منصة X
            print(f" [X API] Dispatched Tweet text: {tweet_text}")
            x_client.create_tweet(text=tweet_text)
            posts_sent_today += 1
            print(f" [Success] Posted successfully. (Today's total: {posts_sent_today}/{DAILY_LIMIT})")

        except Exception as e:
            print(f" [Error] Failed during processing or publishing phase: {e}")

# --- إعداد مراقب ومستمع منصة تيليجرام (User-bot) ---
telethon_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@telethon_client.on(events.NewMessage(chats=SOURCE_CHANNEL))
async def telegram_handler(event):
    if event.message.message:
        text = event.message.message.strip()
        if text:
            print(f" [Telegram] Captured update: {text[:40]}...")
            message_queue.append(text)

# --- نقطة الانطلاق الأساسية للتطبيق ---
async def main():
    # 1. تشغيل خادوم فحص الصحة الخاص بمنصة Render في الخلفية
    asyncio.create_task(start_health_server())
    
    # 2. تشغيل مؤقت التجميع والتلخيص الذكي كل فتره زمنية محددة
    asyncio.create_task(process_queue_periodically())
    
    # 3. تسجيل الدخول والبدء في الاستماع لقنوات تيليجرام المصدرية
    print(" [Core] Starting Telethon User-bot client...")
    await telethon_client.start()
    print(" [Core] Bot is completely initialized and actively listening.")
    await telethon_client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
