import os
import sys
import json
import logging
import asyncio
import datetime
import tweepy
from aiohttp import web

# --- 1. إعداد الـ Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# --- 2. التحقق من متغيرات البيئة ---
REQUIRED_ENV_VARS = [
    "TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION_STRING", "SOURCE_CHANNEL",
    "X_CONSUMER_KEY", "X_CONSUMER_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET",
    "GEMINI_API_KEY"
]
missing_vars = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]
if missing_vars:
    logger.critical(f"❌ متغيرات البيئة التالية مفقودة: {missing_vars}")
    sys.exit(1)

API_ID                = int(os.environ["TELEGRAM_API_ID"])
API_HASH              = os.environ["TELEGRAM_API_HASH"]
SESSION_STRING        = os.environ["TELEGRAM_SESSION_STRING"]
SOURCE_CHANNEL        = os.environ["SOURCE_CHANNEL"]
X_CONSUMER_KEY        = os.environ["X_CONSUMER_KEY"]
X_CONSUMER_SECRET     = os.environ["X_CONSUMER_SECRET"]
X_ACCESS_TOKEN        = os.environ["X_ACCESS_TOKEN"]
X_ACCESS_TOKEN_SECRET = os.environ["X_ACCESS_TOKEN_SECRET"]
GEMINI_API_KEY        = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL_NAME     = os.environ.get("GEMINI_MODEL_NAME", "gemini-2.0-flash")
BATCH_INTERVAL = int(os.environ.get("BATCH_INTERVAL_MINUTES", "20")) * 60
DAILY_LIMIT           = int(os.environ.get("DAILY_LIMIT", "50"))

# --- 3. تهيئة مكتبات X و Gemini ---
x_client_v2 = tweepy.Client(
    consumer_key=X_CONSUMER_KEY, consumer_secret=X_CONSUMER_SECRET,
    access_token=X_ACCESS_TOKEN, access_token_secret=X_ACCESS_TOKEN_SECRET
)

import google.generativeai as genai
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)

# --- 4. الحالة العالمية ---
posts_sent_today     = 0
last_reset_date      = datetime.date.today()
last_seen_message_id = None

# --- 5. إعداد Telethon ---
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon import utils as tg_utils

telethon_client = TelegramClient(
    StringSession(SESSION_STRING), API_ID, API_HASH,
    connection_retries=10,
    retry_delay=3,
    auto_reconnect=True,
    request_retries=5,
)

# --- 6. إدارة الحالة عبر Telegram Saved Messages ---
STATE_MSG_TAG = "XBOT_STATE_V2"

async def load_state():
    global posts_sent_today, last_reset_date, last_seen_message_id
    try:
        async for msg in telethon_client.iter_messages('me', limit=30):
            if msg.message and msg.message.startswith(STATE_MSG_TAG):
                try:
                    payload = json.loads(msg.message[len(STATE_MSG_TAG)+1:])
                    last_seen_message_id = payload.get("last_id")
                    saved_date = payload.get("date", "")
                    if saved_date == str(datetime.date.today()):
                        posts_sent_today = payload.get("count", 0)
                    else:
                        posts_sent_today = 0
                    logger.info(f"✅ [STATE LOADED] last_id={last_seen_message_id} | count={posts_sent_today}")
                    return
                except Exception as parse_err:
                    logger.warning(f"فشل تحليل رسالة الحالة: {parse_err}")
                    continue
    except Exception as e:
        logger.error(f"خطأ في تحميل الحالة: {e}", exc_info=True)
    logger.info("ℹ️ لا توجد حالة محفوظة، جلسة جديدة.")

async def save_state(count, last_id):
    try:
        payload = json.dumps({"count": count, "last_id": last_id, "date": str(datetime.date.today())})
        new_text = f"{STATE_MSG_TAG}|{payload}"

        target_msg = None
        async for msg in telethon_client.iter_messages('me', limit=30):
            if msg.message and msg.message.startswith(STATE_MSG_TAG):
                target_msg = msg
                break

        if target_msg:
            await target_msg.edit(new_text)
        else:
            await telethon_client.send_message('me', new_text)

        logger.info(f"💾 [STATE SAVED] last_id={last_id} | count={count}")
    except Exception as e:
        logger.error(f"خطأ في حفظ الحالة: {e}", exc_info=True)

# --- 7. البرومبت ---
DEFAULT_PROMPT = (
    "You are the Editor-in-Chief of an independent documentation platform reporting directly from inside the Gaza Strip.\n"
    "Your objective is to craft a solemn, highly impactful, and concise humanitarian update in English based on the provided field updates below:\n"
    "[Field Notes]:\n{combined_text}\n\n"
    "Strict Editorial Constraints:\n"
    "1. Professional Brevity: Synthesize the core updates into a single coherent tweet. It must NOT exceed 250 characters.\n"
    "2. Objective Documentation: Faithfully translate and report the humanitarian reality, the current crisis, daily struggles, resilience, and starvation/famine if mentioned in the source updates. Keep the tone dignified yet powerful.\n"
    "3. Digital Sanitization: Absolutely remove all external links, Telegram channels, usernames starting with (@), and promotional phrases.\n"
    "4. Direct Framing: Start the update immediately. Do NOT use any introductory text, hashtags, or excessive emojis."
)
GEMINI_PROMPT = os.environ.get("GEMINI_PROMPT", DEFAULT_PROMPT)

# --- 8. خادم الصحة بـ aiohttp ---
async def health_handler(request):
    return web.Response(text="OK")

async def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"✅ خادم الصحة (aiohttp) يعمل على المنفذ {port}")

# --- 9. Keep-Alive منشط ومعدل ---
async def telegram_keep_alive():
    while True:
        await asyncio.sleep(120)  # فحص كل دقيقتين لإنعاش المجرى الشبكي سريعاً
        try:
            await telethon_client.get_me()
        except Exception as e:
            logger.warning(f"⚠️ [Keep-Alive] اكتشاف انقطاع صامت: {e} — جاري إعادة الاتصال...")
            try:
                await telethon_client.disconnect()
                await telethon_client.connect()
                logger.info("🔁 [Keep-Alive] تم تدمير المقبس المعلق وإعادة بناء الاتصال بنجاح.")
            except Exception as ce:
                logger.error(f"❌ [Keep-Alive] فشل إنعاش الشبكة السحابية: {ce}")

# --- 10. المحرك الرئيسي المحصن بمهلات أمان صارمة ---
async def process_channel_polling(target_channel_id):
    global posts_sent_today, last_reset_date, last_seen_message_id
    logger.info(f"⏳ محرك الفحص يعمل. دورة كل {BATCH_INTERVAL / 60} دقيقة.")

    cycle = 0
    while True:
        cycle += 1
        logger.info(f"🔁 ===== دورة #{cycle} | last_id={last_seen_message_id} | sent={posts_sent_today}/{DAILY_LIMIT} =====")

        if datetime.date.today() > last_reset_date:
            posts_sent_today = 0
            last_reset_date = datetime.date.today()
            await save_state(posts_sent_today, last_seen_message_id)
            logger.info("🔄 تصفير عداد اليوم.")

        if posts_sent_today >= DAILY_LIMIT:
            logger.warning(f"⚠️ حد يومي ({DAILY_LIMIT}) مكتمل. انتظار...")
            await asyncio.sleep(BATCH_INTERVAL)
            continue

        try:
            if last_seen_message_id is None:
                logger.info("📍 لا يوجد خط أساس، جاري تحديده...")
                # حمينا تأسيس خط الأساس بمهلة أمان 15 ثانية لمنع التعليق عند أول حركة
                msgs = await asyncio.wait_for(
                    telethon_client.get_messages(target_channel_id, limit=1),
                    timeout=15.0
                )
                if msgs:
                    last_seen_message_id = msgs[0].id
                    await save_state(posts_sent_today, last_seen_message_id)
                    logger.info(f"📸 خط الأساس: {last_seen_message_id}")
                else:
                    logger.warning("⚠️ القناة فارغة أو لا يمكن الوصول إليها!")
                await asyncio.sleep(BATCH_INTERVAL)
                continue

            logger.info(f"🔍 جلب الرسائل بعد ID={last_seen_message_id}...")

            # 🛠️ حقن الحصن البرمجي: حد أقصى 20 ثانية للاستجابة الشبكية، وإلا ينهار الطلب المعلق وينتقل للدورة القادمة
            try:
                messages = await asyncio.wait_for(
                    telethon_client.get_messages(
                        target_channel_id,
                        limit=50,
                        min_id=last_seen_message_id,
                        reverse=True
                    ),
                    timeout=20.0
                )
            except asyncio.TimeoutError:
                logger.warning("⏱️ [تنبيه شبكة] خوادم تليجرام معلقة ومجمدة حالياً. كسر الطلب لتفادي القفل وتأجيل الدورة...")
                logger.info(f"⏸️ انتظار {BATCH_INTERVAL/60} دقيقة لبدء الدورة القادمة...")
                await asyncio.sleep(BATCH_INTERVAL)
                continue

            count = len(messages) if messages else 0
            logger.info(f"📊 نتيجة الجلب: {count} رسالة.")

            if not messages:
                logger.info("💤 لا رسائل جديدة.")
                logger.info(f"⏸️ انتظار {BATCH_INTERVAL/60} دقيقة...")
                await asyncio.sleep(BATCH_INTERVAL)
                continue

            new_texts  = []
            highest_id = last_seen_message_id

            for msg in messages:
                if msg.id > highest_id:
                    highest_id = msg.id
                if msg.message and msg.message.strip():
                    new_texts.append(msg.message.strip())
                    logger.info(f"  📄 ID={msg.id}: {msg.message[:80]}...")

            if highest_id > last_seen_message_id:
                last_seen_message_id = highest_id
                await save_state(posts_sent_today, last_seen_message_id)

            if not new_texts:
                logger.info("💤 كل الرسائل الجديدة وسائط بدون نص.")
                logger.info(f"⏸️ انتظار {BATCH_INTERVAL/60} دقيقة...")
                await asyncio.sleep(BATCH_INTERVAL)
                continue

            logger.info(f"📥 {len(new_texts)} رسالة نصية → جاري التلخيص...")
            combined_text = "\n---\n".join(new_texts)
            if len(combined_text) > 3500:
                combined_text = combined_text[:3500]

            final_prompt = GEMINI_PROMPT.format(combined_text=combined_text)
            response = await asyncio.wait_for(
                asyncio.to_thread(gemini_model.generate_content, final_prompt),
                timeout=45.0
            )
            tweet_text = response.text.strip()
            if len(tweet_text) > 280:
                tweet_text = tweet_text[:277] + "..."

            logger.info(f"📝 التغريدة ({len(tweet_text)} حرف): {tweet_text}")

            success = False
            for attempt in range(3):
                try:
                    logger.info(f"🚀 نشر على X (محاولة {attempt+1}/3)...")
                    await asyncio.to_thread(x_client_v2.create_tweet, text=tweet_text)
                    success = True
                    break
                except Exception as xe:
                    wait_time = (2 ** attempt) * 5
                    logger.warning(f"⚠️ خطأ X (محاولة {attempt+1}): {xe}")
                    await asyncio.sleep(wait_time)

            if success:
                posts_sent_today += 1
                await save_state(posts_sent_today, last_seen_message_id)
                logger.info(f"✅ نُشر على X! ({posts_sent_today}/{DAILY_LIMIT})")
            else:
                logger.error("❌ فشل النشر على X بعد 3 محاولات.")

        except asyncio.TimeoutError:
            logger.error("⏰ انتهت مهلة محرك الـ Gemini.")
        except Exception as err:
            logger.error(f"🚨 خطأ غير متوقع في دورة الفحص: {err}", exc_info=True)

        logger.info(f"⏸️ انتظار {BATCH_INTERVAL/60} دقيقة...")
        await asyncio.sleep(BATCH_INTERVAL)

# --- 11. الدالة الرئيسية ---
async def main():
    await start_health_server()

    logger.info("🔗 تشغيل عميل تيليجرام...")
    await telethon_client.start()
    logger.info("✅ تيليجرام متصل بنجاح.")

    await load_state()

    asyncio.ensure_future(telegram_keep_alive())

    try:
        logger.info(f"🔍 جاري تحديد القناة: {SOURCE_CHANNEL}")
        channel_entity    = await telethon_client.get_entity(SOURCE_CHANNEL)
        target_channel_id = tg_utils.get_peer_id(channel_entity)
        logger.info(f"🎯 القناة محددة ومعتمدة: {target_channel_id}")

        await process_channel_polling(target_channel_id)

    except Exception as e:
        logger.error(f"❌ خطأ حرج في النواة main: {e}", exc_info=True)
        await telethon_client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 إيقاف يدوي.")
