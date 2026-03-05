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

# --- Простая синхронная обработка для надежности ---

@app.route('/' + WEBHOOK_SECRET, methods=['POST'])
def webhook():
    """Обработчик вебхука (синхронный)"""
    logger.info("📩 Получен POST запрос на webhook")
    
    if request.method != 'POST':
        return jsonify({"error": "Method not allowed"}), 405
    
    # Проверяем, что бот инициализирован
    if application is None or Update is None:
        logger.error("❌ Бот не инициализирован")
        return jsonify({"error": "Bot not initialized"}), 500
    
    try:
        # Получаем данные от Telegram
        json_string = request.get_data().decode('utf-8')
        logger.info(f"📦 Получены данные")
        
        # Парсим обновление
        update_data = json.loads(json_string)
        update = Update.de_json(update_data, application.bot)
        
        # Создаем и запускаем асинхронную задачу
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(application.process_update(update))
        finally:
            loop.close()
        
        logger.info("✅ Webhook обработан успешно")
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    """Принудительная установка вебхука через Telegram API"""
    try:
        # Получаем текущий URL сервиса
        railway_url = request.host
        webhook_url = f"https://{railway_url}/{WEBHOOK_SECRET}"
        logger.info(f"🔄 Устанавливаем вебхук на: {webhook_url}")
        
        # Формируем запрос к Telegram API
        api_url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
        params = {
            "url": webhook_url,
            "allowed_updates": json.dumps(['message', 'callback_query', 'edited_message']),
            "drop_pending_updates": True
        }
        
        # Отправляем запрос (синхронно)
        import requests
        response = requests.get(api_url, params=params)
        result = response.json()
        
        if result.get('ok'):
            logger.info(f"✅ Вебхук успешно установлен через API")
            return jsonify({"success": True, "result": result})
        else:
            logger.error(f"❌ Ошибка API Telegram: {result}")
            return jsonify({"error": result}), 400
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/webhook_info', methods=['GET'])
def webhook_info():
    """Получение информации о вебхуке через Telegram API"""
    try:
        api_url = f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo"
        response = requests.get(api_url)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/delete_webhook', methods=['GET'])
def delete_webhook():
    """Удаление вебхука"""
    try:
        api_url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook"
        params = {"drop_pending_updates": True}
        response = requests.get(api_url, params=params)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/debug')
def debug():
    """Отладочная информация"""
    return jsonify({
        "bot_imported": 'bot' in sys.modules,
        "application_exists": application is not None,
        "update_exists": Update is not None,
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
