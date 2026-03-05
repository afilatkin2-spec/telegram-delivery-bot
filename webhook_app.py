from flask import Flask, request
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
    logger.info("✅ Event loop инициализирован")
    return loop

# Инициализируем loop
init_loop()

# Импортируем всё необходимое из bot.py
try:
    # Сначала импортируем сам модуль bot
    import bot
    
    # Затем получаем нужные объекты
    application = bot.application
    TOKEN = bot.TOKEN
    logger.info("✅ Бот успешно импортирован из bot.py")
    
    # Импортируем Update отдельно
    from telegram import Update
    logger.info("✅ Update успешно импортирован из telegram")
    
except ImportError as e:
    logger.error(f"❌ Ошибка при импорте: {e}")
    application = None
    Update = None
    
except AttributeError as e:
    logger.error(f"❌ Ошибка доступа к атрибуту: {e}")
    application = None
    Update = None

# Секретный путь для вебхука
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "telegram-webhook-secret")

def async_route(f):
    """Декоратор для асинхронных route"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        global loop
        try:
            if loop.is_closed():
                logger.warning("⚠️ Loop был закрыт, создаем новый")
                loop = init_loop()
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
        try:
            json_string = request.get_data().decode('utf-8')
            logger.info(f"📩 Получен webhook: {json_string[:100]}...")
            
            # Проверяем наличие необходимых объектов
            if application is None:
                logger.error("❌ application не инициализирован")
                return 'Error: application not initialized', 500
            
            if Update is None:
                logger.error("❌ Update не импортирован")
                return 'Error: Update not imported', 500
            
            # Создаем update объект
            update = Update.de_json(json.loads(json_string), application.bot)
            
            # Обрабатываем обновление
            await application.process_update(update)
            logger.info("✅ Webhook обработан успешно")
            
            return 'OK', 200
        except Exception as e:
            logger.error(f"❌ Ошибка обработки вебхука: {e}")
            return f'Error: {e}', 500
    return 'OK', 200

@app.route('/set_webhook', methods=['GET'])
@async_route
async def set_webhook():
    """Установка вебхука"""
    try:
        if application is None:
            return "❌ application не инициализирован", 500
        
        railway_url = os.getenv("RAILWAY_PUBLIC_DOMAIN")
        if not railway_url:
            railway_url = request.host
        
        webhook_url = f"https://{railway_url}/{WEBHOOK_SECRET}"
        logger.info(f"🔄 Устанавливаем вебхук на: {webhook_url}")
        
        # Удаляем старый вебхук
        await application.bot.delete_webhook()
        
        # Устанавливаем новый
        success = await application.bot.set_webhook(
            url=webhook_url,
            allowed_updates=['message', 'callback_query', 'edited_message', 'channel_post']
        )
        
        if success:
            info = await application.bot.get_webhook_info()
            logger.info(f"✅ Webhook установлен: {info}")
            return f"✅ Webhook установлен на {webhook_url}", 200
        else:
            return "❌ Ошибка установки вебхука", 400
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return f"❌ Ошибка: {e}", 500

@app.route('/debug', methods=['GET'])
def debug():
    """Отладочная информация"""
    info = {
        "application_exists": application is not None,
        "update_exists": Update is not None,
        "loop_exists": loop is not None,
        "loop_closed": loop.is_closed() if loop else None,
        "webhook_secret": WEBHOOK_SECRET,
        "bot_imported": 'bot' in sys.modules
    }
    return json.dumps(info), 200

if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
