from flask import Flask, request, jsonify
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

# Глобальный event loop
loop = None

def init_loop():
    """Инициализирует глобальный event loop"""
    global loop
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    logger.info("✅ Глобальный event loop инициализирован")
    return loop

# Инициализируем loop сразу при загрузке
init_loop()

# Импортируем бота
try:
    import bot
    from telegram import Update
    application = bot.application
    TOKEN = bot.TOKEN
    logger.info("✅ Бот импортирован")
except Exception as e:
    logger.error(f"❌ Ошибка при импорте: {e}")
    application = None
    Update = None

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "pavdanf")
logger.info(f"🔑 Секрет: {WEBHOOK_SECRET}")

def async_route(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        global loop
        try:
            if loop.is_closed():
                loop = init_loop()
            return loop.run_until_complete(f(*args, **kwargs))
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            return jsonify({"error": str(e)}), 500
    return wrapper

@app.route('/')
def index():
    return jsonify({"status": "running"})

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

@app.route(f'/{WEBHOOK_SECRET}', methods=['POST'])
@async_route
async def webhook():
    """Основной эндпоинт для вебхуков"""
    logger.info("📩 Получен POST запрос")
    
    if application is None or Update is None:
        logger.error("❌ Бот не инициализирован")
        return 'OK', 200
    
    try:
        json_string = request.get_data().decode('utf-8')
        logger.info(f"📦 Данные получены, длина: {len(json_string)}")
        
        update_data = json.loads(json_string)
        update = Update.de_json(update_data, application.bot)
        
        await application.process_update(update)
        logger.info("✅ Webhook обработан")
        
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return 'OK', 200

@app.route('/set_webhook', methods=['GET'])
@async_route
async def set_webhook():
    """Установка вебхука"""
    if application is None:
        return jsonify({"error": "Bot not initialized"}), 500
    
    railway_url = request.host
    webhook_url = f"https://{railway_url}/{WEBHOOK_SECRET}"
    
    success = await application.bot.set_webhook(
        url=webhook_url,
        drop_pending_updates=True
    )
    
    if success:
        return jsonify({"success": True, "message": f"Webhook set to {webhook_url}"})
    return jsonify({"error": "Failed to set webhook"}), 400

@app.route('/debug')
def debug():
    return jsonify({
        "bot_imported": application is not None,
        "status": "running"
    })

if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
