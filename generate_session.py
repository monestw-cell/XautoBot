from telethon.sync import TelegramClient
from telethon.sessions import StringSession

print("==================================================")
print("   Telegram User-bot Session String Generator     ")
print("==================================================")
print("هذا السكريبت المحلي يساعدك على توليد كود الجلسة المشفر لمرة واحدة فقط.")
print("ستحتاج لنسخ الرمز الناتج ووضعه كمتغير بيئة في منصة Render للتشغيل التلقائي.\n")

api_id = int(input("1. Enter your Telegram API ID: "))
api_hash = input("2. Enter your Telegram API HASH: ")

print("\n[!] سيتم الآن إرسال رمز تسجيل دخول رسمي من تيليجرام لحسابك الشخصي للتأكيد.")
with TelegramClient(StringSession(), api_id, api_hash) as client:
    session_str = client.session.save()
    print("\n🔒 SUCCESS! انسخ الكود الطويل الموضح أدناه بالكامل وضعه في متغيرات بيئة Render باسم (TELEGRAM_SESSION_STRING):")
    print("=" * 70)
    print(session_str)
    print("=" * 70)
