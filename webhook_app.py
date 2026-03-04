from flask import Flask, request
import json
import logging
import os
import sys
from bot import main as bot_main, TOKEN, init_google_sheets, logger

# Настройка логирования для Railway
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)

app = Flask(__name__)

# Импортируем bot.py после настройки логирования
try:
    from telegram import Update
    from bot import application, TOKEN
    logger.info("✅ Бот успешно импортирован")
except Exception as e:
    logger.error(f"❌ Ошибка импорта бота: {e}")

# Секретный путь для вебхука (можно изменить на любой)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "telegram-webhook-secret")

@app.route('/')
def index():
    return json.dumps({
        "status": "running",
        "message": "Telegram bot is running on Railway!"
    }), 200

@app.route('/health')
def health():
    return json.dumps({"status": "healthy"}), 200

@app.route(f'/{WEBHOOK_SECRET}', methods=['POST'])
def webhook():
    """Основной эндпоинт для вебхуков Telegram"""
    if request.method == 'POST':
        try:
            json_string = request.get_data().decode('utf-8')
            update = Update.de_json(json.loads(json_string), application.bot)
            application.process_update(update)
            return 'OK', 200
        except Exception as e:
            logger.error(f"❌ Ошибка обработки вебхука: {e}")
            return 'Error', 500
    return 'OK', 200

@app.route('/set_webhook')
def set_webhook():
    """Эндпоинт для установки вебхука (вызвать один раз)"""
    try:
        railway_url = os.getenv("RAILWAY_PUBLIC_DOMAIN")
        if not railway_url:
            return "RAILWAY_PUBLIC_DOMAIN not set", 500
        
        webhook_url = f"https://{railway_url}/{WEBHOOK_SECRET}"
        success = application.bot.set_webhook(url=webhook_url)
        
        if success:
            return f"✅ Webhook установлен на {webhook_url}", 200
        else:
            return "❌ Ошибка установки вебхука", 400
    except Exception as e:
        return f"❌ Ошибка: {e}", 500

if __name__ == '__main__':
    # Запуск Flask приложения
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)