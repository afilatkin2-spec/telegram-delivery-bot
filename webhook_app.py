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

# Импортируем бота и необходимые классы
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
    
    # Проверяем наличие обработчиков
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

# Секретный путь для вебхука
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "pavdanf")
logger.info(f"🔑 Секрет: {WEBHOOK_SECRET}")

@app.route(f'/{WEBHOOK_SECRET}', methods=['POST'])
def webhook():
    """Обработчик вебхука - ФИНАЛЬНАЯ ВЕРСИЯ"""
    logger.info("📩 Получен POST запрос")
    
    # Проверяем, что бот инициализирован
    if application is None or Update is None:
        logger.error("❌ Бот не инициализирован")
        return 'OK', 200
    
    try:
        # Получаем данные от Telegram
        json_string = request.get_data().decode('utf-8')
        logger.info(f"📦 Данные получены, длина: {len(json_string)}")
        
        # Парсим update
        update_data = json.loads(json_string)
        update = Update.de_json(update_data, application.bot)
        
        # Используем asyncio.run() для простоты и надежности
        # Он создает новый loop и гарантированно его закрывает
        logger.info("🔄 Запускаем обработку update...")
        asyncio.run(application.process_update(update))
        
        logger.info("✅ Update обработан успешно")
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
        "update_imported": Update is not None,
        "handlers_count": handlers,
        "webhook_secret": WEBHOOK_SECRET
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
