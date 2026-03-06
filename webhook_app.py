from flask import Flask, request, jsonify
import json
import logging
import os
import sys
import asyncio

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

# Инициализируем application
if application:
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(application.initialize())
        loop.close()
        logger.info("✅ Application инициализирован")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации: {e}")

@app.route(f'/{WEBHOOK_SECRET}', methods=['POST'])
def webhook():
    """Обработчик вебхука"""
    logger.info("📩 Получен POST запрос")
    
    try:
        # Получаем данные
        json_string = request.get_data().decode('utf-8')
        logger.info(f"📦 Данные: {json_string[:200]}...")
        
        # Парсим update
        update_data = json.loads(json_string)
        update = Update.de_json(update_data, application.bot)
        
        # Создаем временный loop для обработки
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(application.process_update(update))
            logger.info("✅ Update обработан")
        finally:
            loop.close()
        
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return 'OK', 200  # Всегда возвращаем OK, даже при ошибке

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
