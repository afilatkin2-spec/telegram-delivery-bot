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

# Импортируем бота
try:
    import bot
    from telegram import Update
    application = bot.application
    TOKEN = bot.TOKEN
    logger.info("✅ Бот успешно импортирован")
    
    # Проверяем наличие обработчиков
    handlers_count = sum(len(h) for h in application.handlers.values())
    logger.info(f"✅ Зарегистрировано обработчиков: {handlers_count}")
    
except Exception as e:
    logger.error(f"❌ Ошибка импорта: {e}")
    application = None
    Update = None
    TOKEN = None

# Секретный путь для вебхука
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "pavdanf")
logger.info(f"🔑 Секрет: {WEBHOOK_SECRET}")

@app.route(f'/{WEBHOOK_SECRET}', methods=['POST'])
def webhook():
    """Обработчик вебхука - СИНХРОННАЯ ВЕРСИЯ"""
    logger.info("📩 Получен POST запрос")
    
    try:
        # Получаем данные
        json_string = request.get_data().decode('utf-8')
        logger.info(f"📦 Данные получены, длина: {len(json_string)}")
        
        # Парсим update
        update_data = json.loads(json_string)
        update = Update.de_json(update_data, application.bot)
        
        # СОЗДАЕМ НОВЫЙ LOOP И ЖДЕМ РЕЗУЛЬТАТ
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            logger.info("🔄 Запускаем обработку update...")
            loop.run_until_complete(application.process_update(update))
            logger.info("✅ Update обработан успешно")
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке update: {e}")
            logger.error(traceback.format_exc())
        finally:
            loop.close()
        
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
    """Отладочная информация"""
    handlers = 0
    if application:
        handlers = sum(len(h) for h in application.handlers.values())
    
    return jsonify({
        "bot_imported": application is not None,
        "handlers_count": handlers,
        "webhook_secret": WEBHOOK_SECRET
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
