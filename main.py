import os
import sys
import json
import logging
import asyncio
import datetime
import tweepy

# --- 1. إعداد الـ Logging الاحترافي ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# --- 2. التحقق الصارم من متغيرات البيئة عند الإقلاع ---
REQUIRED_ENV_VARS = [
    "TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION_STRING", "SOURCE_CHANNEL",
    "X_CONSUMER_KEY", "X_CONSUMER_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET",
    "GEMINI_API_KEY"
]

missing_vars = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]
if missing_vars:
    logger.critical(f"❌ فشل إقلاع البوت. متغيرات البيئة التالية مفقودة: {missing_vars}")
    sys.exit(1)

# شحن الإعدادات
API_ID = int(os.environ.get("TELEGRAM_API_ID"))
API_HASH = os.environ.get("TELEGRAM_API_HASH")
SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING")
SOURCE_CHANNEL = os.environ.get("SOURCE_CHANNEL")

X_CONSUMER_KEY = os.environ.get("X_CONSUMER_KEY")
X_CONSUMER_SECRET = os.environ.get("X_CONSUMER_SECRET")
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN")
X_ACCESS_TOKEN_SECRET = os.environ.get("X_ACCESS_TOKEN_SECRET")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL_NAME", "gemini-2.0-flash")

BATCH_INTERVAL = int(os.environ.get("BATCH_INTERVAL_MINUTES", "20")) * 60
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "50"))
STATE_FILE = "/tmp/bot_state.json"

# --- 3. تهيئة مكتبة X (واجهة v2 النصية للحساب المجاني) ---
x_client_v2 = tweepy.Client(
    consumer_key=X_CONSUMER_KEY, consumer_secret=X_CONSUMER_SECRET,
    access_token=X_ACCESS_TOKEN, access_token_secret=X_ACCESS_TOKEN_SECRET
)

import google.generativeai as genai
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)

# طابور آمن نصوص فقط
message_queue = asyncio.Queue()

# --- 4. إدارة حالة العداد اليومي (Persistence) ---
def load_bot_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                if data.get("date") == str(datetime.date.today()):
                    return data.get("count", 0), datetime.date.today()
        except Exception as e:
            logger.error(f"خطأ أثناء قراءة ملف الحالة: {e}")
    return 0, datetime.date.today()

def save_bot_state(count):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"count": count, "date": str(datetime.date.today())}, f)
    except Exception as e:
        logger.error(f"خطأ أثناء حفظ ملف الحالة: {e}")

posts_sent_today, last_reset_date = load_bot_state()

# --- 5. البرومبت المطور باللغة الإنجليزية المعزول بالكامل ---
DEFAULT_PROMPT = (
    "You are the Editor-in-Chief of an independent documentation platform reporting directly from inside the Gaza Strip.\n"
    "Your objective is to craft a solemn, highly impactful, and concise humanitarian update in English based on the provided field updates below:\n"
    "[Field Notes]:\n{combined_text}\n\n"
    "Strict Editorial Constraints:\n"
    "1. Professional Brevity: Synthesize the core updates into a single coherent tweet. It must NOT exceed 250 characters.\n"
    "2. Objective Documentation: Faithfully translate and report the humanitarian reality, the current crisis, daily struggles, resilience, and starvation/famine if mentioned in the source updates. Keep the tone dignified yet powerful.\n"
    "3. Digital Sanitization: Absolutely remove all external links, Telegram channels, usernames starting with (@), and promotional phrases.\n"
    "4. Direct Framing: Start the update immediately. Do NOT use any introductory text (e.g., 'Here is the summary'), hashtags, or excessive emojis."
)
GEMINI_PROMPT = os.environ.get("GEMINI_PROMPT", DEFAULT_PROMPT)

# --- 6. خادم الصحة السليم لـ Render ---
async def handle_health_check(reader, writer):
    try:
        data = await reader.read(1024)
        if data:
            response = "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nOK"
            writer.write(response.encode('utf-8'))
            await writer.drain()
    except Exception as e:
        logger.error(f"خطأ في سيرفر الفحص: {e}")
    finally:
        writer.close()
        await writer.wait_closed()

async def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    try:
        server = await asyncio.start_server(handle_health_check, '0.0.0.0', port)
        logger.info(f"✅ خادم فحص الصحة يعمل على المنفذ: {port}")
        async with server:
            await server.serve_forever()
    except Exception as e:
        logger.critical(f"فشل تشغيل خادم الصحة لـ Render: {e}")

# --- 7. معالجة وتلخيص ونشر البيانات في طابور مجدول ---
async def process_queue_periodically():
    global posts_sent_today, last_reset_date
    logger.info(f"⏳ معالج الطابور المجدول يعمل بنجاح. دورة التجميع: كل {BATCH_INTERVAL / 60} دقيقة.")
    
    while True:
        await asyncio.sleep(BATCH_INTERVAL)
        
        if datetime.date.today() > last_reset_date:
            posts_sent_today = 0
            last_reset_date = datetime.date.today()
            save_bot_state(posts_sent_today)
            logger.info("🔄 تم تصفير عداد النشر لليوم الجديد.")

        if message_queue.empty():
            continue

        if posts_sent_today >= DAILY_LIMIT:
            logger.warning(f"⚠️ تم الوصول للحد اليومي المسموح ({DAILY_LIMIT}). سيتم الاحتفاظ بالرسائل في الطابور حتى يفتح العداد تلقائياً.")
            continue

        # تفريغ الطابور بأمان (تم تبسيطها وحذف task_done غير المستخدمة بناءً على رؤيتك)
        captured_texts = []
        while not message_queue.empty():
            text_item = message_queue.get_nowait()
            captured_texts.append(text_item)

        # تحسين حجم البرومبت والحد من تضخم النصوص
        combined_text = "\n---\n".join(captured_texts)
        if len(combined_text) > 3500:
            logger.warning("⚠️ حجم النصوص المجمعة كبير جداً، تم اقتطاع آخر 3500 حرف فقط لحماية السياق.")
            combined_text = combined_text[:3500]

        final_prompt = GEMINI_PROMPT.format(combined_text=combined_text)

        try:
            logger.info(f"🤖 استدعاء محرك {GEMINI_MODEL_NAME} للتوليد والتلخيص باللغة الإنجليزية...")
            
            response = await asyncio.wait_for(
                asyncio.to_thread(gemini_model.generate_content, final_prompt),
                timeout=45.0
            )
            tweet_text = response.text.strip()
            
            # 🛠️ تحسين دقة القص بناءً على تعديلك الرقمي الحسابي (277 حرف + 3 نقاط = 280 حرف تماماً)
            if len(tweet_text) > 280:
                tweet_text = tweet_text[:277] + "..."

            success = False
            rate_limited = False

            for attempt in range(3):
                try:
                    logger.info(f"🚀 محاولة نشر التغريدة الإنجليزية (محاولة {attempt+1}/3)...")
                    await asyncio.to_thread(x_client_v2.create_tweet, text=tweet_text)
                    success = True
                    break
                except tweepy.errors.TooManyRequests as e:
                    logger.error(f"🛑 حد النشر الأقصى لـ X (429 Rate Limit). إعادة المحتوى للطابور فوراً: {e}")
                    for txt in captured_texts:
                        await message_queue.put(txt)
                    rate_limited = True
                    break
                except Exception as e:
                    wait_time = (2 ** attempt) * 5
                    logger.warning(f"⚠️ خطأ اتصال مؤقت. تراجع أسّي لمدة {wait_time} ثانية: {e}")
                    await asyncio.sleep(wait_time)

            if success:
                posts_sent_today += 1
                save_bot_state(posts_sent_today)
                logger.info(f"✅ تم النشر بنجاح! الرصيد المستهلك اليوم: {posts_sent_today}/{DAILY_LIMIT}")
            else:
                if not rate_limited:
                    logger.error("❌ فشل النشر بعد استنفاد محاولات الشبكة. إعادة النصوص إلى الطابور.")
                    for txt in captured_texts:
                        await message_queue.put(txt)

        except asyncio.TimeoutError:
            logger.error(f"⏱️ انتهت مهلة الاستجابة لـ Gemini. إعادة النصوص المجمعة للطابور لتفادي ضياعها.")
            for txt in captured_texts:
                await message_queue.put(txt)
        except Exception as core_err:
            logger.error(f"🚨 خطأ فادح غير متوقع داخل دورة المعالجة: {core_err}")

# --- 8. مراقب قنوات تيليجرام ---
from telethon import TelegramClient, events
from telethon.sessions import StringSession

telethon_client = TelegramClient(
    StringSession(SESSION_STRING), API_ID, API_HASH,
    connection_retries=5,  # 5 محاولات إعادة اتصال ذكية عند أي سقوط لحظي للشبكة
    retry_delay=5
)

@telethon_client.on(events.NewMessage(chats=SOURCE_CHANNEL))
async def telegram_handler(event):
    try:
        if event.message.message:
            text = event.message.message.strip()
            if text:
                logger.info("📥 إضافة تحديث نصي جديد إلى طابور الـ Queue الآمن.")
                await message_queue.put(text)
    except Exception as e:
        logger.error(f"خطأ في معالج استقبال رسائل تليجرام: {e}")

# --- 9. الدالة التشغيلية الكبرى ---
async def main():
    asyncio.create_task(start_health_server())
    asyncio.create_task(process_queue_periodically())
    
    logger.info("🔗 جاري تشغيل مستمع تليجرام وبدء المراقبة الإخبارية...")
    await telethon_client.start()
    logger.info("🚀 البوت مستقر تماماً ومجهّز للنشر العالمي باللغة الإنجليزية 100%.")
    await telethon_client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 تم إيقاف البوت يدوياً.")
