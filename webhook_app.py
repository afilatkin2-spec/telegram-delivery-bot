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

# --- Простая синхронная обработка ---

@app.route('/' + WEBHOOK_SECRET, methods=['POST'])
def webhook():
    """Обработчик вебхука"""
    logger.info("📩 Получен POST запрос на webhook")
    
    if request.method != 'POST':
        return jsonify({"error": "Method not allowed"}), 405
    
    if application is None or Update is None:
        logger.error("❌ Бот не инициализирован")
        return jsonify({"error": "Bot not initialized"}), 500
    
    try:
        json_string = request.get_data().decode('utf-8')
        logger.info(f"📦 Получены данные")
        
        update_data = json.loads(json_string)
        update = Update.de_json(update_data, application.bot)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(application.process_update(update))
            logger.info("✅ Webhook обработан успешно")
        finally:
            loop.close()
        
        return 'OK', 200
        
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
        
        # Прямой запрос к Telegram API
        import subprocess
        import urllib.parse
        
        # Альтернативный способ без requests
        api_url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
        params = urllib.parse.urlencode({
            "url": webhook_url,
            "drop_pending_updates": "true"
        })
        
        # Используем curl если requests не работает
        cmd = f"curl -s '{api_url}?{params}'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get('ok'):
                logger.info(f"✅ Вебхук установлен")
                return jsonify({"success": True, "result": data})
        
        return jsonify({"error": "Failed to set webhook"}), 400
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/webhook_info', methods=['GET'])
def webhook_info():
    """Информация о вебхуке"""
    try:
        # Используем curl для запроса
        import subprocess
        import urllib.parse
        
        api_url = f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo"
        cmd = f"curl -s '{api_url}'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            return jsonify(json.loads(result.stdout))
        else:
            return jsonify({"error": "Failed to get webhook info"}), 400
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/delete_webhook', methods=['GET'])
def delete_webhook():
    """Удаление вебхука"""
    try:
        import subprocess
        import urllib.parse
        
        api_url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook"
        params = urllib.parse.urlencode({"drop_pending_updates": "true"})
        
        cmd = f"curl -s '{api_url}?{params}'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            return jsonify(json.loads(result.stdout))
        else:
            return jsonify({"error": "Failed to delete webhook"}), 400
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
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
