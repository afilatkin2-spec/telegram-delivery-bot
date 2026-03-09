from flask import Flask, request, jsonify
import json
import logging
import os
import sys
import threading
import time
from functools import wraps

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Импортируем уже инициализированный application из bot.py
try:
    import bot
    from telegram import Update
    application = bot.application  # Уже готовый application
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
        try:
            return f(*args, **kwargs)
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
def webhook():
    """Основной эндпоинт для вебхуков - СИНХРОННАЯ ВЕРСИЯ"""
    logger.info("📩 Получен POST запрос")
    
    if application is None or Update is None:
        logger.error("❌ Бот не инициализирован")
        return 'OK', 200
    
    try:
        json_string = request.get_data().decode('utf-8')
        logger.info(f"📦 Данные получены, длина: {len(json_string)}")
        
        update_data = json.loads(json_string)
        update = Update.de_json(update_data, application.bot)
        
        # Создаем новый event loop для каждого запроса
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(application.process_update(update))
            logger.info("✅ Webhook обработан")
        finally:
            loop.close()
        
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return 'OK', 200

# Фоновый поток для поддержания жизни
def keep_alive():
    while True:
        time.sleep(30)
        logger.info("💓 Heartbeat - приложение живо")

threading.Thread(target=keep_alive, daemon=True).start()

if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
