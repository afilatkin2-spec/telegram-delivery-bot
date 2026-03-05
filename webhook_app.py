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

# Пытаемся импортировать requests
try:
    import requests
    REQUESTS_AVAILABLE = True
    logger.info("✅ Библиотека requests успешно импортирована")
except ImportError:
    REQUESTS_AVAILABLE = False
    logger.error("❌ Библиотека requests не установлена. Добавьте 'requests==2.31.0' в requirements.txt")

# Создаем Flask приложение
app = Flask(__name__)

# Импортируем бота и необходимые классы
try:
    import bot
    from telegram import Update
    application = bot.application
    TOKEN = bot.TOKEN
    logger.info("✅ Бот успешно импортирован")
except Exception as e:
    logger.error(f"❌ Ошибка при импорте: {e}")
    application = None
    Update = None

# Секретный путь для вебхука
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "pavdanf")
logger.info(f"🔑 Используется секрет вебхука: {WEBHOOK_SECRET}")

# Флаг инициализации
_initialized = False

async def ensure_initialized():
    """Гарантирует, что application инициализирован"""
    global _initialized
    if not _initialized and application:
        await application.initialize()
        _initialized = True
        logger.info("✅ Application инициализирован")

# --- Простая синхронная обработка ---

@app.route(f'/{WEBHOOK_SECRET}', methods=['POST'])
def webhook():
    """Обработчик вебхука"""
    logger.info(f"📩 Получен POST запрос на webhook по пути: /{WEBHOOK_SECRET}")
    
    if request.method != 'POST':
        logger.error(f"❌ Неправильный метод: {request.method}")
        return jsonify({"error": "Method not allowed"}), 405
    
    if application is None or Update is None:
        logger.error("❌ Бот не инициализирован")
        return jsonify({"error": "Bot not initialized"}), 500
    
    try:
        json_string = request.get_data().decode('utf-8')
        logger.info(f"📦 Получены данные: {json_string[:200]}...")
        
        update_data = json.loads(json_string)
        update = Update.de_json(update_data, application.bot)
        
        # Создаем и запускаем асинхронную задачу
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Сначала инициализируем application
            loop.run_until_complete(ensure_initialized())
            # Затем обрабатываем update
            loop.run_until_complete(application.process_update(update))
            logger.info("✅ Webhook обработан успешно")
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке update: {e}")
            raise
        finally:
            loop.close()
        
        return 'OK', 200
        
    except json.JSONDecodeError as e:
        logger.error(f"❌ Ошибка парсинга JSON: {e}")
        return jsonify({"error": f"Invalid JSON: {e}"}), 400
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    """Установка вебхука"""
    if not REQUESTS_AVAILABLE:
        return jsonify({
            "error": "Библиотека requests не установлена",
            "solution": "Добавьте 'requests==2.31.0' в requirements.txt и перезапустите деплой"
        }), 500
    
    try:
        railway_url = request.host
        webhook_url = f"https://{railway_url}/{WEBHOOK_SECRET}"
        logger.info(f"🔄 Устанавливаем вебхук на: {webhook_url}")
        
        # Инициализируем application перед установкой вебхука
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(ensure_initialized())
        finally:
            loop.close()
        
        # Используем requests для запроса
        api_url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
        params = {
            "url": webhook_url,
            "drop_pending_updates": True,
            "allowed_updates": json.dumps(['message', 'callback_query', 'edited_message'])
        }
        
        response = requests.get(api_url, params=params, timeout=30)
        data = response.json()
        
        if data.get('ok'):
            logger.info(f"✅ Вебхук установлен на {webhook_url}")
            return jsonify({"success": True, "result": data})
        else:
            logger.error(f"❌ Ошибка установки вебхука: {data}")
            return jsonify({"error": data}), 400
        
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Ошибка запроса: {e}")
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/webhook_info', methods=['GET'])
def webhook_info():
    """Информация о вебхуке"""
    try:
        api_url = f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo"
        response = requests.get(api_url, timeout=30)
        return jsonify(response.json())
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/delete_webhook', methods=['GET'])
def delete_webhook():
    """Удаление вебхука"""
    try:
        api_url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook"
        params = {"drop_pending_updates": True}
        response = requests.get(api_url, params=params, timeout=30)
        return jsonify(response.json())
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/init', methods=['GET'])
def force_init():
    """Принудительная инициализация"""
    global _initialized
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(ensure_initialized())
            return jsonify({
                "success": True,
                "initialized": _initialized,
                "application_exists": application is not None
            })
        finally:
            loop.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/test_webhook', methods=['GET', 'POST'])
def test_webhook():
    """Тестовый эндпоинт для проверки"""
    if request.method == 'POST':
        return jsonify({
            "method": "POST",
            "data": request.get_data().decode('utf-8'),
            "headers": dict(request.headers)
        })
    return jsonify({
        "method": "GET",
        "message": "Send POST request to test webhook",
        "webhook_url": f"/{WEBHOOK_SECRET}"
    })

@app.route('/debug')
def debug():
    """Отладочная информация"""
    return jsonify({
        "bot_imported": 'bot' in sys.modules,
        "application_exists": application is not None,
        "update_exists": Update is not None,
        "webhook_secret": WEBHOOK_SECRET,
        "webhook_path": f"/{WEBHOOK_SECRET}",
        "requests_available": REQUESTS_AVAILABLE,
        "initialized": _initialized,
        "python_version": sys.version,
        "routes": [str(rule) for rule in app.url_map.iter_rules()]
    })

@app.route('/')
def index():
    return jsonify({
        "status": "running",
        "message": "Telegram bot is running on Railway!",
        "webhook_path": f"/{WEBHOOK_SECRET}"
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
