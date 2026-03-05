from flask import Flask, request
import json
import logging
import os
import sys
import asyncio
from functools import wraps

# Настройка логирования
logging.basicConfig(
    format='%(asime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Глобальный event loop (один на всё приложение)
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
    logger.info("✅ Event loop инициализирован")
    return loop

# Инициализируем loop сразу при загрузке
init_loop()

# Импортируем бота
try:
    from bot import create_application
    from telegram import Update
    
    logger.info("🔄 Создаем и инициализируем application...")
    
    # Создаем application
    application = create_application()
    
    # Инициализируем application в нашем loop
    loop.run_until_complete(application.initialize())
    logger.info("✅ Application успешно создан и инициализирован")
    
except Exception as e:
    logger.error(f"❌ Ошибка при создании application: {e}")
    application = None

# Секретный путь для вебхука
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "telegram-webhook-secret")

def async_route(f):
    """Декоратор для асинхронных route"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        global loop
        try:
            # Проверяем, что loop жив
            if loop.is_closed():
                logger.warning("⚠️ Loop был закрыт, создаем новый")
                loop = init_loop()
            # Запускаем асинхронную функцию в нашем loop
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
        logger.info(f"Домен из запроса: {railway_url}")
    
    webhook_url = f"https://{railway_url}/{WEBHOOK_SECRET}"
    logger.info(f"Устанавливаем вебхук на: {webhook_url}")
    
    # Устанавливаем вебхук
    success = await application.bot.set_webhook(
        url=webhook_url,
        allowed_updates=['message', 'callback_query']
    )
    
    if success:
        # Получаем информацию о вебхуке
        webhook_info = await application.bot.get_webhook_info()
        logger.info(f"✅ Webhook info: {webhook_info}")
        
        # Также устанавливаем команды для меню
        await application.bot.set_my_commands([
            ('start', 'Запустить бота'),
            ('status', 'Показать активные заявки')
        ])
        
        return f"✅ Webhook установлен на {webhook_url}", 200
    else:
        return "❌ Ошибка установки вебхука", 400

@app.route('/reset', methods=['GET'])
@async_route
async def reset():
    """Полный сброс"""
    await application.bot.delete_webhook()
    await application.initialize()
    return "✅ Бот перезапущен", 200

@app.route('/loop_status', methods=['GET'])
def loop_status():
    """Проверка статуса loop"""
    global loop
    return json.dumps({
        "loop_exists": loop is not None,
        "loop_closed": loop.is_closed() if loop else None
    }), 200

if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
