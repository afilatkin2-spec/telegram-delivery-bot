from flask import Flask, request, jsonify
import json
import logging
import os
import sys
import asyncio
import traceback
from functools import wraps

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Создаем Flask приложение
app = Flask(__name__)

# Глобальный event loop - один на всё приложение
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

# Инициализируем loop при старте
init_loop()

# Декоратор для асинхронных функций в Flask
def async_route(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        global loop
        if loop.is_closed():
            loop = init_loop()
        # Запускаем асинхронную функцию в глобальном loop НЕ ЖДЕМ РЕЗУЛЬТАТА
        asyncio.run_coroutine_threadsafe(f(*args, **kwargs), loop)
        # Сразу возвращаем OK, не ждем выполнения
        return jsonify({"status": "accepted"}), 202
    return wrapper

# Импортируем бота
try:
    import bot
    from telegram import Update
    application = bot.application
    TOKEN = bot.TOKEN
    
    if application is None:
        raise ImportError("application is None")
    if Update is None:
        raise ImportError("Update is None")
        
    logger.info("✅ Бот успешно импортирован")
    
    handlers_count = sum(len(h) for h in application.handlers.values())
    logger.info(f"✅ Зарегистрировано обработчиков: {handlers_count}")
    
    # Инициализируем application в глобальном loop
    future = asyncio.run_coroutine_threadsafe(application.initialize(), loop)
    future.result(timeout=10)
    logger.info("✅ Application инициализирован")
    
except Exception as e:
    logger.error(f"❌ Ошибка импорта: {e}")
    application = None
    Update = None
    TOKEN = None

# Секретный путь для вебхука
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "pavdanf")
logger.info(f"🔑 Секрет: {WEBHOOK_SECRET}")

@app.route(f'/{WEBHOOK_SECRET}', methods=['POST'])
@async_route
async def webhook():
    """Обработчик вебхука"""
    logger.info("📩 Получен POST запрос")
    
    if application is None or Update is None:
        logger.error("❌ Бот не инициализирован")
        return
    
    try:
        json_string = request.get_data().decode('utf-8')
        logger.info(f"📦 Данные получены, длина: {len(json_string)}")
        
        update_data = json.loads(json_string)
        update = Update.de_json(update_data, application.bot)
        
        logger.info("🔄 Запускаем обработку update...")
        await application.process_update(update)
        
        logger.info("✅ Update обработан успешно")
        
    except json.JSONDecodeError as e:
        logger.error(f"❌ Ошибка парсинга JSON: {e}")
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        logger.error(traceback.format_exc())

@app.route('/debug')
def debug():
    """Отладочная информация"""
    handlers = 0
    if application:
        handlers = sum(len(h) for h in application.handlers.values())
    
    return jsonify({
        "bot_imported": application is not None,
        "update_imported": Update is not None,
        "handlers_count": handlers,
        "webhook_secret": WEBHOOK_SECRET,
        "loop_exists": loop is not None,
        "loop_closed": loop.is_closed() if loop else None
    })

@app.route('/')
def index():
    return jsonify({
        "status": "running",
        "message": "Telegram bot is running on Railway!"
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
