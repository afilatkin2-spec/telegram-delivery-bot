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
        
        # Создаем новый loop для каждого запроса
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(application.process_update(update))
            logger.info("✅ Update обработан")
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
        finally:
            loop.close()
        
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return 'OK', 200

@app.route('/debug')
def debug():
    return jsonify({
        "bot_imported": application is not None,
        "status": "running"
    })

@app.route('/')
def index():
    return jsonify({"status": "running"})
