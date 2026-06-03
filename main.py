import os
import sys
import json
import logging
import asyncio
import datetime
import tweepy
from aiohttp import web

# --- 1. إعداد الـ Logging الاحترافي الحقيقي المباشر ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def force_log(msg):
    """دالة طباعة فورية تتجاوز ذاكرة التخزين المؤقت لـ Render لضمان رؤية الأحداث فوراً"""
    print(f"📡 [LIVE] {datetime.datetime.now()} - {msg}", flush=True)

# --- 2. التحقق الصارم من متغيرات البيئة ---
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
DAILY_LIMIT           = int(os.environ.get("DAILY_LIMIT", "50"))

# --- 3. تهيئة مكتبات X و Gemini ---
x_client_v2 = tweepy.Client(
    consumer_key=X_CONSUMER_KEY, consumer_secret=X_CONSUMER_SECRET,
    access_token=X_ACCESS_TOKEN, access_token_secret=X_ACCESS_TOKEN_SECRET
)

import google.generativeai as genai
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)

# --- 4. الحالة العالمية المستمرة ---
posts_sent_today     = 0
last_reset_date      = datetime.date.today()
last_seen_message_id = None

# --- 5. إعداد تليجرام الصارم ---
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
                    force_log(f"✅ [STATE LOADED] last_id={last_seen_message_id} | count={posts_sent_today}")
                    return
                except Exception as parse_err:
                    continue
    except Exception as e:
        logger.error(f"خطأ في تحميل الحالة: {e}")
    force_log("ℹ️ لا توجد حالة محفوظة سابقة، بدء جلسة جديدة كلياً.")

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
        force_log(f"💾 [STATE SAVED TO CLOUD] last_id={last_id} | count={count}")
    except Exception as e:
        logger.error(f"خطأ في حفظ الحالة: {e}")

# --- 7. البرومبت الاحترافي الموجه بالكامل باللغة الإنجليزية ---
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

# --- 8. المحرك المركزي الصافي (يعمل مرة واحدة فقط عند استدعاء الرابط) ---
async def check_and_process_updates(target_channel_id):
    global posts_sent_today, last_reset_date, last_seen_message_id
    
    if datetime.date.today() > last_reset_date:
        posts_sent_today = 0
        last_reset_date = datetime.date.today()
        await save_state(posts_sent_today, last_seen_message_id)
        force_log("🔄 تصفير العداد اليومي تلقائياً.")

    if posts_sent_today >= DAILY_LIMIT:
        force_log(f"⚠️ حد يومي ({DAILY_LIMIT}) مكتمل.")
        return

    try:
        if not telethon_client.is_connected():
            force_log("🔗 [تنبيه شبكة] إعادة تنشيط اتصال تليجرام المباشر...")
            await asyncio.wait_for(telethon_client.connect(), timeout=15.0)

        if last_seen_message_id is None:
            force_log("📍 لا يوجد خط أساس، جاري القنص الرقمي لأحدث معرف...")
            msgs = await asyncio.wait_for(
                telethon_client.get_messages(target_channel_id, limit=1),
                timeout=15.0
            )
            if msgs:
                last_seen_message_id = msgs[0].id
                await save_state(posts_sent_today, last_seen_message_id)
                force_log(f"📸 تم تثبيت خط الأساس السحابي عند المعرف: {last_seen_message_id}")
            return

        force_log(f"🔍 جاري فحص الرسائل الجديدة بعد معرف: {last_seen_message_id}...")
        
        messages = await asyncio.wait_for(
            telethon_client.get_messages(
                target_channel_id,
                limit=50,
                min_id=last_seen_message_id,
                reverse=True
            ),
            timeout=20.0
        )

        count = len(messages) if messages else 0
        force_log(f"📊 نتيجة الفحص الشبكي: {count} رسالة جديدة.")

        if not messages:
            return

        new_texts = []
        highest_id = last_seen_message_id

        for msg in messages:
            if msg.id > highest_id:
                highest_id = msg.id
            if msg.message and msg.message.strip():
                new_texts.append(msg.message.strip())
                force_log(f"  📄 قنص ID={msg.id}: {msg.message[:40]}...")

        if highest_id > last_seen_message_id:
            last_seen_message_id = highest_id
            await save_state(posts_sent_today, last_seen_message_id)

        if not new_texts:
            force_log("💤 جميع الرسائل المكتشفة هي وسائط عارية بدون نصوص.")
            return

        force_log(f"📥 جاري دفع {len(new_texts)} منشور نصي إلى ذكاء Gemini...")
        combined_text = "\n---\n".join(new_texts)
        if len(combined_text) > 3500:
            combined_text = combined_text[:3500]

        final_prompt = GEMINI_PROMPT.format(combined_text=combined_text)
        response = await asyncio.wait_for(
            asyncio.to_thread(gemini_model.generate_content, final_prompt),
            timeout=40.0
        )
        tweet_text = response.text.strip()
        if len(tweet_text) > 280:
            tweet_text = tweet_text[:277] + "..."

        force_log(f"📝 التغريدة المجهزة للنشر: {tweet_text}")

        success = False
        for attempt in range(3):
            try:
                force_log(f"🚀 محاولة ضخ المنشور على منصة X (محاولة {attempt+1}/3)...")
                await asyncio.to_thread(x_client_v2.create_tweet, text=tweet_text)
                success = True
                break
            except Exception as xe:
                wait_time = (2 ** attempt) * 5
                force_log(f"⚠️ خطأ اتصال مع X، انتظار {wait_time} ثانية: {xe}")
                await asyncio.sleep(wait_time)

        if success:
            posts_sent_today += 1
            await save_state(posts_sent_today, last_seen_message_id)
            force_log(f"✅ تم النشر العالمي بنجاح! الرصيد اليومي: ({posts_sent_today}/{DAILY_LIMIT})")
        else:
            force_log("❌ فشل النشر النهائي على حساب X.")

    except Exception as err:
        logger.error(f"🚨 خطأ برمي في النواة: {err}", exc_info=True)

# --- 9. خادم ويب المستجيب للحدث الفوري (الكرون جوب يقود التنفيذ) ---
cycle_counter = 0
execution_lock = asyncio.Lock()

async def health_handler(request):
    global cycle_counter
    cycle_counter += 1
    target_id = request.app['target_channel_id']
    
    force_log(f"⚡ ====== [نبضة الكرون جوب] انطلاق الدورة الحية #{cycle_counter} ======")
    
    if execution_lock.locked():
        force_log("⚠️ هناك دورة فحص قيد التنفيذ حالياً، تخطي هذا الطلب تلافياً للتصادم.")
        return web.Response(text="BUSY")
        
    async with execution_lock:
        await check_and_process_updates(target_id)
        
    force_log(f"✨ ====== انتهاء الدورة #{cycle_counter} بنجاح، العودة لوضع النوم الآمن ======")
    return web.Response(text="OK")

# --- 10. الدالة الرئيسية الجامعة لخطوط البنية التحتية ---
async def main():
    force_log("🔗 تشغيل عميل تليجرام وتأمين بروتوكول MTProto السحابي...")
    await telethon_client.start()
    force_log("✅ تليجرام متصل وموثق سحابياً.")

    await load_state()

    try:
        force_log(f"🔍 جاري تحديد الكيان الشبكي الصارم لـ {SOURCE_CHANNEL}...")
        channel_entity    = await telethon_client.get_entity(SOURCE_CHANNEL)
        target_channel_id = tg_utils.get_peer_id(channel_entity)
        force_log(f"🎯 القناة معتمدة برقم المعرّف الشامل: {target_channel_id}")

        # إطلاق السيرفر وتمرير المعرف له ليعمل بنمط التجاوب الفوري عند كل طرق للرابط
        port = int(os.environ.get("PORT", 8080))
        app = web.Application()
        app['target_channel_id'] = target_channel_id
        app.router.add_get("/", health_handler)
        app.router.add_get("/health", health_handler)
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        force_log(f"🚀 خادم الويب يعمل بالكامل على المنفذ {port}. بانتظار طرقات الكرون جوب الخارجي...")

        # إبقاء النواة الرئيسية حية ومستمعة بشكل صامت تماماً
        await asyncio.Event().wait()

    except Exception as e:
        logger.error(f"❌ خطأ حرج في النواة main: {e}", exc_info=True)
        await telethon_client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        force_log("🛑 تم إيقاف البوت يدوياً.")
