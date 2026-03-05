from flask import Flask, request
import json
import logging
import os
import sys
import asyncio

# Настройка логирования для Railway
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Импортируем только то, что реально нужно
try:
    from bot import application
    from telegram import Update
    logger.info("✅ Бот успешно импортирован")
except Exception as e:
    logger.error(f"❌ Ошибка импорта бота: {e}")

# Секретный путь для вебхука
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
            
            # Создаем новый event loop для асинхронной обработки
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(application.process_update(update))
            finally:
                loop.close()
            
            return 'OK', 200
        except Exception as e:
            logger.error(f"❌ Ошибка обработки вебхука: {e}")
            return 'Error', 500
    return 'OK', 200

@app.route('/set_webhook')
async def set_webhook():
    """Эндпоинт для установки вебхука (вызвать один раз)"""
    try:
        railway_url = os.getenv("RAILWAY_PUBLIC_DOMAIN")
        if not railway_url:
            railway_url = request.host
            logger.info(f"Домен из запроса: {railway_url}")
        
        webhook_url = f"https://{railway_url}/{WEBHOOK_SECRET}"
        logger.info(f"Устанавливаем вебхук на: {webhook_url}")
        
        # ВАЖНО: добавляем await
        success = await application.bot.set_webhook(url=webhook_url)
        
        if success:
            # Проверяем информацию о вебхуке
            webhook_info = await application.bot.get_webhook_info()
            logger.info(f"Информация о вебхуке: {webhook_info}")
            return f"✅ Webhook установлен на {webhook_url}", 200
        else:
            return "❌ Ошибка установки вебхука", 400
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return f"❌ Ошибка: {e}", 500

@app.route('/webhook_info')
async def webhook_info():
    """Проверка информации о вебхуке"""
    try:
        webhook_info = await application.bot.get_webhook_info()
        return json.dumps({
            "url": webhook_info.url,
            "has_custom_certificate": webhook_info.has_custom_certificate,
            "pending_update_count": webhook_info.pending_update_count,
            "max_connections": webhook_info.max_connections
        }), 200
    except Exception as e:
        return f"❌ Ошибка: {e}", 500

if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)