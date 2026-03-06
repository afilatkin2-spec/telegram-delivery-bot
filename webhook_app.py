from flask import Flask, request, jsonify
import json
import logging
import os
import sys
import asyncio
import traceback

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Создаем Flask приложение
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
    return loop

# Инициализируем loop при старте
init_loop()
logger.info("✅ Event loop инициализирован")

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
    
    # Application уже инициализирован в bot.py
    
except ImportError as e:
    logger.error(f"❌ Ошибка импорта: {e}")
    application = None
    Update = None
    TOKEN = None
except Exception as e:
    logger.error(f"❌ Неожиданная ошибка: {e}")
    application = None
    Update = None
    TOKEN = None

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "pavdanf")
logger.info(f"🔑 Секрет: {WEBHOOK_SECRET}")

@app.route(f'/{WEBHOOK_SECRET}', methods=['POST'])
def webhook():
    """Обработчик вебхука"""
    logger.info("📩 Получен POST запрос")
    
    if application is None or Update is None:
        logger.error("❌ Бот не инициализирован")
        return 'OK', 200
    
    try:
        json_string = request.get_data().decode('utf-8')
        logger.info(f"📦 Данные получены, длина: {len(json_string)}")
        
        update_data = json.loads(json_string)
        update = Update.de_json(update_data, application.bot)
        
        global loop
        if loop.is_closed():
            loop = init_loop()
        
        logger.info("🔄 Запускаем обработку update...")
        
        # ВАЖНО: создаем задачу и ДОБАВЛЯЕМ CALLBACK для отслеживания
        future = asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
        
        def handle_future(future):
            try:
                future.result()  # Получаем результат или исключение
                logger.info("✅ Update обработан успешно")
            except Exception as e:
                logger.error(f"❌ Ошибка обработки update: {e}")
                logger.error(traceback.format_exc())
        
        future.add_done_callback(handle_future)
        
        logger.info("✅ Update передан в обработку")
        return 'OK', 200
        
    except json.JSONDecodeError as e:
        logger.error(f"❌ Ошибка парсинга JSON: {e}")
        return 'OK', 200
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        logger.error(traceback.format_exc())
        return 'OK', 200

@app.route('/debug')
def debug():
    handlers = 0
    if application:
        handlers = sum(len(h) for h in application.handlers.values())
    
    return jsonify({
        "bot_imported": application is not None,
        "update_imported": Update is not None,
        "handlers_count": handlers,
        "webhook_secret": WEBHOOK_SECRET,
        "loop_closed": loop.is_closed() if loop else None
    })

@app.route('/')
def index():
    return jsonify({"status": "running"})

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
