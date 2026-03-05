from flask import Flask, request, jsonify
import json
import logging
import os
import sys
import asyncio
import traceback

# Настройка логирования
logging.basicConfig(
    format='%(asime)s - %(name)s - %(levelname)s - %(message)s',
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

# Инициализируем loop
init_loop()
logger.info("✅ Event loop инициализирован")

# Импортируем requests
try:
    import requests
    REQUESTS_AVAILABLE = True
    logger.info("✅ Библиотека requests импортирована")
except ImportError:
    REQUESTS_AVAILABLE = False
    logger.warning("⚠️ Библиотека requests не установлена")

# Импортируем бота
try:
    import bot
    from telegram import Update
    application = bot.application
    TOKEN = bot.TOKEN
    logger.info("✅ Бот успешно импортирован из bot.py")
except Exception as e:
    logger.error(f"❌ Ошибка при импорте бота: {e}")
    application = None
    Update = None
    TOKEN = None

# Секретный путь для вебхука
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "pavdanf")
logger.info(f"🔑 Используется секрет вебхука: {WEBHOOK_SECRET}")

# ИНИЦИАЛИЗИРУЕМ APPLICATION ПРИ ЗАПУСКЕ
if application:
    try:
        logger.info("🔄 Инициализация application...")
        loop = init_loop()
        loop.run_until_complete(application.initialize())
        logger.info("✅ Application успешно инициализирован")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации application: {e}")

@app.route(f'/{WEBHOOK_SECRET}', methods=['POST'])
def webhook():
    """Обработчик вебхука"""
    logger.info("📩 Получен POST запрос на webhook")
    
    # Проверяем базовые условия
    if request.method != 'POST':
        return jsonify({"error": "Method not allowed"}), 405
    
    if application is None or Update is None:
        logger.error("❌ Бот не инициализирован")
        return jsonify({"error": "Bot not initialized"}), 500
    
    try:
        # Получаем данные
        json_string = request.get_data().decode('utf-8')
        logger.info(f"📦 Получены данные от пользователя {json_string.find('username')}")
        
        # Парсим update
        update_data = json.loads(json_string)
        update = Update.de_json(update_data, application.bot)
        
        # Используем глобальный loop
        global loop
        if loop.is_closed():
            loop = init_loop()
        
        # Обрабатываем update
        future = asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
        future.result(timeout=30)  # Ждем до 30 секунд
        
        logger.info("✅ Webhook обработан успешно")
        return 'OK', 200
        
    except asyncio.TimeoutError:
        logger.error("❌ Таймаут обработки")
        return jsonify({"error": "Processing timeout"}), 500
    except json.JSONDecodeError as e:
        logger.error(f"❌ Ошибка парсинга JSON: {e}")
        return jsonify({"error": f"Invalid JSON: {e}"}), 400
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    """Установка вебхука"""
    if not REQUESTS_AVAILABLE:
        return jsonify({"error": "requests library not available"}), 500
    
    try:
        railway_url = request.host
        webhook_url = f"https://{railway_url}/{WEBHOOK_SECRET}"
        logger.info(f"🔄 Устанавливаем вебхук на: {webhook_url}")
        
        api_url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
        params = {
            "url": webhook_url,
            "drop_pending_updates": True,
            "allowed_updates": json.dumps(['message', 'callback_query', 'edited_message'])
        }
        
        response = requests.get(api_url, params=params, timeout=10)
        data = response.json()
        
        if data.get('ok'):
            logger.info(f"✅ Вебхук установлен")
            return jsonify({"success": True, "result": data})
        else:
            logger.error(f"❌ Ошибка установки: {data}")
            return jsonify({"error": data}), 400
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/webhook_info', methods=['GET'])
def webhook_info():
    """Информация о вебхуке"""
    if not REQUESTS_AVAILABLE:
        return jsonify({"error": "requests not available"}), 500
    
    try:
        api_url = f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo"
        response = requests.get(api_url, timeout=10)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/delete_webhook', methods=['GET'])
def delete_webhook():
    """Удаление вебхука"""
    if not REQUESTS_AVAILABLE:
        return jsonify({"error": "requests not available"}), 500
    
    try:
        api_url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook"
        params = {"drop_pending_updates": True}
        response = requests.get(api_url, params=params, timeout=10)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/force_init', methods=['GET'])
def force_init():
    """Принудительная инициализация"""
    try:
        global loop
        if loop.is_closed():
            loop = init_loop()
        
        loop.run_until_complete(application.initialize())
        return jsonify({"success": True, "message": "Application initialized"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/debug')
def debug():
    """Отладочная информация"""
    return jsonify({
        "bot_imported": 'bot' in sys.modules,
        "application_exists": application is not None,
        "update_exists": Update is not None,
        "webhook_secret": WEBHOOK_SECRET,
        "requests_available": REQUESTS_AVAILABLE,
        "loop_closed": loop.is_closed() if loop else None,
        "python_version": sys.version
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
