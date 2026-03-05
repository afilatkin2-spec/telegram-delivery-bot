from flask import Flask, request
import json
import logging
import os
import sys
import asyncio
from functools import wraps

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Импортируем бота
try:
    from bot import application
    from telegram import Update
    logger.info("✅ Бот успешно импортирован")
except Exception as e:
    logger.error(f"❌ Ошибка импорта бота: {e}")
    application = None

# Секретный путь для вебхука
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "telegram-webhook-secret")

# Глобальный event loop
loop = None

def get_event_loop():
    """Получает или создает event loop"""
    global loop
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop

async def ensure_initialized():
    """Инициализирует application если нужно"""
    if application and not hasattr(application, '_initialized'):
        await application.initialize()
        application._initialized = True
        logger.info("✅ Application инициализирован")

def async_route(f):
    """Декоратор для асинхронных route"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        loop = get_event_loop()
        try:
            return loop.run_until_complete(f(*args, **kwargs))
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            return f"❌ Ошибка: {e}", 500
    return wrapper

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
@async_route
async def webhook():
    """Основной эндпоинт для вебхуков Telegram"""
    if request.method == 'POST':
        json_string = request.get_data().decode('utf-8')
        update = Update.de_json(json.loads(json_string), application.bot)
        
        # Инициализируем если нужно
        await ensure_initialized()
        
        # Обрабатываем обновление
        await application.process_update(update)
        
        return 'OK', 200
    return 'OK', 200

@app.route('/set_webhook', methods=['GET'])
@async_route
async def set_webhook():
    """Эндпоинт для установки вебхука"""
    railway_url = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if not railway_url:
        railway_url = request.host
    
    webhook_url = f"https://{railway_url}/{WEBHOOK_SECRET}"
    logger.info(f"Устанавливаем вебхук на: {webhook_url}")
    
    # Инициализируем если нужно
    await ensure_initialized()
    
    # Устанавливаем вебхук
    success = await application.bot.set_webhook(url=webhook_url)
    
    if success:
        # Получаем информацию о вебхуке
        webhook_info = await application.bot.get_webhook_info()
        logger.info(f"Информация о вебхуке: {webhook_info}")
        return f"✅ Webhook установлен на {webhook_url}", 200
    else:
        return "❌ Ошибка установки вебхука", 400

@app.route('/reset_webhook', methods=['GET'])
@async_route
async def reset_webhook():
    """Сброс вебхука (если нужно)"""
    await ensure_initialized()
    success = await application.bot.delete_webhook()
    if success:
        return "✅ Webhook удален", 200
    else:
        return "❌ Ошибка удаления вебхука", 400

if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
