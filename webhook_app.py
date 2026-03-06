from flask import Flask, request, jsonify
import json
import logging
import os
import sys
import asyncio

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

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
    return loop

# Инициализируем loop при старте
init_loop()
logger.info("✅ Глобальный event loop инициализирован")

# Импортируем бота
try:
    import bot
    from telegram import Update
    application = bot.application
    TOKEN = bot.TOKEN
    logger.info("✅ Бот импортирован")
except Exception as e:
    logger.error(f"❌ Ошибка импорта: {e}")
    application = None
    Update = None

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
        
        # Используем ГЛОБАЛЬНЫЙ loop, не закрываем его!
        global loop
        if loop.is_closed():
            loop = init_loop()
        
        # Запускаем обработку в глобальном loop
        future = asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
        
        # Добавляем callback для логирования ошибок
        def handle_future(future):
            try:
                future.result()
                logger.info("✅ Update обработан успешно")
            except Exception as e:
                logger.error(f"❌ Ошибка обработки: {e}")
        
        future.add_done_callback(handle_future)
        
        logger.info("✅ Update передан в обработку")
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return 'OK', 200

@app.route('/debug')
def debug():
    return jsonify({
        "bot_imported": application is not None,
        "loop_exists": loop is not None,
        "loop_closed": loop.is_closed() if loop else None,
        "status": "running"
    })

@app.route('/')
def index():
    return jsonify({"status": "running"})

if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
