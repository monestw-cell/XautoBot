FROM python:3.10-slim

WORKDIR /app

# تثبيت الحزم والمكتبات المطلوبة
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ كافة ملفات المشروع إلى داخل الحاوية
COPY . .

# فتح المنفذ الإلزامي لمنصة Render المجانية
EXPOSE 8080

# أمر تشغيل البوت الأساسي
CMD ["python", "main.py"]
