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

# تهيئة المتغيرات العالمية للحالة
posts_sent_today = 0
last_reset_date = datetime.date.today()
last_seen_message_id = None

# --- 3. تهيئة مكتبة X وايرادات الذكاء الاصطناعي ---
x_client_v2 = tweepy.Client(
    consumer_key=X_CONSUMER_KEY, consumer_secret=X_CONSUMER_SECRET,
    access_token=X_ACCESS_TOKEN, access_token_secret=X_ACCESS_TOKEN_SECRET
)

import google.generativeai as genai
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)

# --- 4. محرك إدارة الحالة السحابي الذكي (Telegram Cloud Persistence) ---
async def load_bot_state_from_tg():
    """قراءة العدادات وآخر ID مسموع من الرسائل المحفوظة للمستخدم"""
    global posts_sent_today, last_reset_date, last_seen_message_id
    try:
        # البحث عن آخر رسالة حالة محفوظة تبدأ بالوسم الثابت
        messages = await telethon_client.get_messages('me', search='BOT_STATE_SYNC:', limit=1)
        if messages:
            state_text = messages[0].message
            # الصيغة المدخرة: BOT_STATE_SYNC:count:last_seen_id:date
            parts = state_text.split(':')
            if len(parts) >= 5:
                count = int(parts[1])
                last_id = int(parts[2]) if parts[2] != 'None' else None
                saved_date = parts[3]
                
                last_seen_message_id = last_id
                if saved_date == str(datetime.date.today()):
                    posts_sent_today = count
                else:
                    posts_sent_today = 0
                
                logger.info(f"🔎 [STATE LOADED FROM CLOUD] last_seen_id={last_seen_message_id}, count={posts_sent_today}")
                return
    except Exception as e:
        logger.error(f"⚠️ تفاجأ البوت بخطأ أثناء قراءة الحالة السحابية: {e}")
    
    # حالة افتراضية في حال عدم وجود سجلات سابقة
    posts_sent_today = 0
    last_seen_message_id = None
    logger.info("ℹ️ لم يتم العثور على حالة سحابية سابقة، تم بدء جلسة جديدة كلياً.")

async def save_bot_state_to_tg(count, last_id):
    """تعديل رسالة الحالة في السحابة لمنع تراكم وتشويه صندوق الرسائل المحفوظة"""
    try:
        state_text = f"BOT_STATE_SYNC:{count}:{last_id}:{datetime.date.today()}:🔒"
        messages = await telethon_client.get_messages('me', search='BOT_STATE_SYNC:', limit=1)
        
        if messages:
            # تحديث وتعديل نفس الرسالة السابقة بدلاً من إرسال رسالة جديدة لتظل الغرفة نظيفة
            await messages[0].edit(state_text)
        else:
            # إذا كانت أول مرة، قم بإنشاء الرسالة الأساسية
            await telethon_client.send_message('me', state_text)
        logger.info(f"💾 [STATE SAVED TO CLOUD] ID={last_id} | Count={count}")
    except Exception as e:
        logger.error(f"⚠️ فشل شحن وتأمين الحالة سحابياً على تليجرام: {e}")

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

# --- 6. خادم فحص الصحة لـ Render ---
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

# --- 7. المحرك المركزي المحدث كلياً بناءً على فكرتك وعقد المزامنة الرقمية ---
async def process_channel_polling(target_channel_id):
    global posts_sent_today, last_reset_date, last_seen_message_id
    logger.info(f"⏳ محرك الفحص والتلخيص الدوري يعمل بنجاح. دورة التجميع: كل {BATCH_INTERVAL / 60} دقيقة.")
    
    while True:
        if datetime.date.today() > last_reset_date:
            posts_sent_today = 0
            last_reset_date = datetime.date.today()
            await save_bot_state_to_tg(posts_sent_today, last_seen_message_id)
            logger.info("🔄 تم تصفير عداد النشر لبدء يوم جديد.")

        if posts_sent_today >= DAILY_LIMIT:
            logger.warning(f"⚠️ تم الوصول للحد اليومي المسموح ({DAILY_LIMIT}). تخطي هذه الدورة تلقائياً.")
            await asyncio.sleep(BATCH_INTERVAL)
            continue

        try:
            logger.info("🔍 [Polling] جاري فحص المنشورات الجديدة عبر مؤشر المزامنة...")
            
            # منطقك الذهبي الفعال لعمل Stateful Polling آمن
            if last_seen_message_id is not None:
                messages = await telethon_client.get_messages(
                    target_channel_id,
                    limit=50,
                    min_id=last_seen_message_id,
                    reverse=True  # ترتيب تصاعدي تصحيحي تلقائي
                )
            else:
                messages = await telethon_client.get_messages(target_channel_id, limit=1)
                if messages:
                    last_seen_message_id = messages[0].id
                    await save_bot_state_to_tg(posts_sent_today, last_seen_message_id)
                    logger.info(f"📸 تم تحديد خط الأساس الأولي السحابي عند المعرف: {last_seen_message_id}")
                await asyncio.sleep(BATCH_INTERVAL)
                continue

            if not messages:
                logger.info("💤 فحص دوري مكتمل: لا توجد رسائل جديدة كلياً في الشبكة.")
                await asyncio.sleep(BATCH_INTERVAL)
                continue

            new_texts = []
            highest_id = last_seen_message_id

            for msg in messages:
                if msg.message and msg.message.strip():
                    new_texts.append(msg.message.strip())
                if msg.id > highest_id:
                    highest_id = msg.id

            # قفز وتحديث المعرف مستمراً دائماً لمنع الحشر والتعليق بسبب الوسائط الصامتة
            if highest_id > last_seen_message_id:
                last_seen_message_id = highest_id
                await save_bot_state_to_tg(posts_sent_today, last_seen_message_id)

            if new_texts:
                logger.info(f"📥 تم رصد {len(new_texts)} منشور نصي جديد! جاري صياغة التحديث العالمي...")
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
                    await save_bot_state_to_tg(posts_sent_today, last_seen_message_id)
                    logger.info(f"✅ تم النشر على حساب X بنجاح! الرصيد المستهلك اليوم: {posts_sent_today}/{DAILY_LIMIT}")
                else:
                    logger.error("❌ فشل النشر على منصة X.")
            else:
                logger.info("💤 تم رصد منشورات جديدة ولكنها وسائط عارية بدون أي نصوص مراقبة.")
            
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

# --- 9. الدالة التشغيلية الكبرى لتشغيل البنى التحتية ---
async def main():
    asyncio.create_task(start_health_server())
    
    logger.info("🔗 جاري تشغيل عميل تليجرام والمصادقة الأمنية الحية...")
    await telethon_client.start()
    
    # 🛠️ حقن آلية استعادة الحالة السحابية فور الإقلاع وقبل بدء الفحص الدوري
    logger.info("🔄 جاري استدعاء وفحص ملف الحالة السحابية الدائم...")
    await load_bot_state_from_tg()
    
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
