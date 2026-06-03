import os
import sys
import json
import logging
import asyncio
import datetime
import tweepy

# --- 1. إعداد الـ Logging الاحترافي للبث الفوري المباشر ---
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

# شحن الإعدادات من البيئة المحيطة
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

# --- 3. تهيئة مكتبة X وايرادات الذكاء الاصطناعي ---
x_client_v2 = tweepy.Client(
    consumer_key=X_CONSUMER_KEY, consumer_secret=X_CONSUMER_SECRET,
    access_token=X_ACCESS_TOKEN, access_token_secret=X_ACCESS_TOKEN_SECRET
)

import google.generativeai as genai
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)

# --- 4. إدارة حالة العداد اليومي ومعرفات التتبع المستمر (Persistence) ---
def load_bot_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                count = data.get("count", 0)
                last_id = data.get("last_seen_id", None)
                
                if data.get("date") == str(datetime.date.today()):
                    return count, datetime.date.today(), last_id
                return 0, datetime.date.today(), last_id
        except Exception as e:
            logger.error(f"خطأ أثناء قراءة ملف الحالة: {e}")
    return 0, datetime.date.today(), None

def save_bot_state(count, last_id):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({
                "count": count, 
                "date": str(datetime.date.today()), 
                "last_seen_id": last_id
            }, f)
    except Exception as e:
        logger.error(f"خطأ أثناء حفظ ملف الحالة: {e}")

posts_sent_today, last_reset_date, last_seen_message_id = load_bot_state()

# --- 5. البرومبت الاحترافي الموجه بالكامل باللغة الإنجليزية ---
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

# --- 6. خادم فحص الصحة السليم لـ Render ---
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
        logger.info(f"✅ خادم فحص الصحة يعمل بنجاح على المنفذ: {port}")
        async with server:
            await server.serve_forever()
    except Exception as e:
        logger.critical(f"فشل تشغيل خادم الصحة لـ Render: {e}")

# --- 7. المحرك المركزي المحدث والمحصن ضد منشورات الوسائط الفارغة ---
async def process_channel_polling(target_channel_id):
    global posts_sent_today, last_reset_date, last_seen_message_id
    logger.info(f"⏳ محرك الفحص والتلخيص الدوري يعمل بنجاح. دورة التجميع: كل {BATCH_INTERVAL / 60} دقيقة.")
    
    while True:
        if datetime.date.today() > last_reset_date:
            posts_sent_today = 0
            last_reset_date = datetime.date.today()
            save_bot_state(posts_sent_today, last_seen_message_id)
            logger.info("🔄 تم تصفير عداد النشر لبدء يوم جديد.")

        if posts_sent_today >= DAILY_LIMIT:
            logger.warning(f"⚠️ تم الوصول للحد اليومي المسموح ({DAILY_LIMIT}). تخطي هذه الدورة تلقائياً.")
            await asyncio.sleep(BATCH_INTERVAL)
            continue

        try:
            logger.info("🔍 [Polling] جاري فحص وسحب المنشورات الجديدة من خوادم تليجرام...")
            messages = await telethon_client.get_messages(target_channel_id, limit=20)
            
            if messages:
                if last_seen_message_id is None:
                    last_seen_message_id = messages[0].id
                    save_bot_state(posts_sent_today, last_seen_message_id)
                    logger.info(f"📸 تم تحديد خط الأساس للمنشورات المستهدفة عند المعرف: {last_seen_message_id}")
                    await asyncio.sleep(BATCH_INTERVAL)
                    continue

                new_texts = []
                highest_id = last_seen_message_id
                
                for msg in reversed(messages):
                    if msg.id > last_seen_message_id:
                        if msg.message and msg.message.strip():
                            new_texts.append(msg.message.strip())
                        if msg.id > highest_id:
                            highest_id = msg.id

                if new_texts:
                    logger.info(f"📥 تم رصد {len(new_texts)} منشور جديد! جاري صياغة التحديث العالمي...")
                    combined_text = "\n---\n".join(new_texts)
                    if len(combined_text) > 3500:
                        combined_text = combined_text[:3500]

                    final_prompt = GEMINI_PROMPT.format(combined_text=combined_text)
                    
                    logger.info(f"🤖 استدعاء محرك {GEMINI_MODEL_NAME} للتوليد بالإنجليزية...")
                    response = await asyncio.wait_for(
                        asyncio.to_thread(gemini_model.generate_content, final_prompt),
                        timeout=45.0
                    )
                    tweet_text = response.text.strip()
                    
                    if len(tweet_text) > 280:
                        tweet_text = tweet_text[:277] + "..."

                    success = False
                    for attempt in range(3):
                        try:
                            logger.info(f"🚀 محاولة نشر التغريدة الإنجليزية (محاولة {attempt+1}/3)...")
                            await asyncio.to_thread(x_client_v2.create_tweet, text=tweet_text)
                            success = True
                            break
                        except Exception as e:
                            wait_time = (2 ** attempt) * 5
                            logger.warning(f"⚠️ خطأ مؤقت في شبكة X: {e}")
                            await asyncio.sleep(wait_time)

                    if success:
                        posts_sent_today += 1
                        last_seen_message_id = highest_id
                        save_bot_state(posts_sent_today, last_seen_message_id)
                        logger.info(f"✅ تم النشر على حساب X بنجاح! الرصيد: {posts_sent_today}/{DAILY_LIMIT}")
                    else:
                        logger.error("❌ فشل النشر على منصة X. سيتم إعادة المحاولة في الدورة القادمة.")
                else:
                    logger.info("💤 فحص دوري مكتمل: لا توجد منشورات نصية جديدة في القناة.")
                    # 🛠️ التحديث الحاسم: دفع خط الأساس للأمام حتى لو كانت المنشورات الجديدة مجرد صور فارغة لمنع التعليق
                    if highest_id > last_seen_message_id:
                        last_seen_message_id = highest_id
                        save_bot_state(posts_sent_today, last_seen_message_id)
            
        except Exception as err:
            logger.error(f"🚨 خطأ حرج داخل دورة الفحص المباشر: {err}")
            
        await asyncio.sleep(BATCH_INTERVAL)

# --- 8. إعداد وتأسيس العميل النصي لتيليجرام ---
from telethon import TelegramClient
from telethon.sessions import StringSession

telethon_client = TelegramClient(
    StringSession(SESSION_STRING), API_ID, API_HASH,
    connection_retries=5,  
    retry_delay=5
)

# --- 9. الدالة التشغيلية الكبرى ---
async def main():
    asyncio.create_task(start_health_server())
    
    logger.info("🔗 جاري تشغيل عميل تليجرام والمصادقة الأمنية الحية...")
    await telethon_client.start()
    
    try:
        logger.info(f"🔄 جاري قراءة وتأمين الكيان الشبكي لـ {SOURCE_CHANNEL}...")
        channel_entity = await telethon_client.get_entity(SOURCE_CHANNEL)
        
        from telethon import utils
        target_channel_id = utils.get_peer_id(channel_entity)
        logger.info(f"🎯 تم التوثق من القناة بنجاح بالـ ID: {target_channel_id}")
        
        logger.info("🚀 إطلاق محرك الفحص والتلخيص الدوري الفعال 24/7...")
        await process_channel_polling(target_channel_id)
        
    except Exception as ent_err:
        logger.error(f"❌ خطأ حرج: فشل تشغيل بنية الفحص الدوري: {ent_err}")
        await telethon_client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 تم إيقاف البوت يدوياً.")
