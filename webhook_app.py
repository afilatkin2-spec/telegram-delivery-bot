from flask import Flask, request, jsonify
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
    logger.info("✅ Event loop инициализирован")
    return loop

# Инициализируем loop
init_loop()

# Импортируем бота
try:
    import bot
    from telegram import Update
    
    application = bot.application
    TOKEN = bot.TOKEN
    
    logger.info("✅ Бот успешно импортирован из bot.py")
    logger.info("✅ Update успешно импортирован из telegram")
    
except Exception as e:
    logger.error(f"❌ Ошибка при импорте: {e}")
    application = None
    Update = None

# Секретный путь для вебхука
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "pavdanf")

@app.route('/')
def index():
    return jsonify({
        "status": "running",
        "message": "Telegram bot is running on Railway!"
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

@app.route(f'/{WEBHOOK_SECRET}', methods=['POST'])
def webhook():
    """Основной эндпоинт для вебхуков Telegram"""
    try:
        # Получаем данные от Telegram
        json_string = request.get_data().decode('utf-8')
        logger.info(f"📩 Получен webhook запрос")
        
        if application is None:
            logger.error("❌ application не инициализирован")
            return jsonify({"error": "application not initialized"}), 500
        
        if Update is None:
            logger.error("❌ Update не импортирован")
            return jsonify({"error": "Update not imported"}), 500
        
        # Создаем update и обрабатываем
        update = Update.de_json(json.loads(json_string), application.bot)
        
        # Запускаем асинхронную обработку
        global loop
        future = asyncio.run_coroutine_threadsafe(
            application.process_update(update), 
            loop
        )
        future.result(timeout=5)  # Ждем до 5 секунд
        
        logger.info("✅ Webhook обработан успешно")
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки вебхука: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    """Установка вебхука"""
    try:
        if application is None:
            return jsonify({"error": "application not initialized"}), 500
        
        railway_url = request.host
        webhook_url = f"https://{railway_url}/{WEBHOOK_SECRET}"
        
        logger.info(f"🔄 Устанавливаем вебхук на: {webhook_url}")
        
        # Запускаем асинхронную установку
        global loop
        future = asyncio.run_coroutine_threadsafe(
            application.bot.set_webhook(
                url=webhook_url,
                allowed_updates=['message', 'callback_query', 'edited_message']
            ),
            loop
        )
        success = future.result(timeout=5)
        
        if success:
            return jsonify({
                "success": True,
                "message": f"Webhook установлен на {webhook_url}"
            })
        else:
            return jsonify({"error": "Failed to set webhook"}), 400
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/webhook_info', methods=['GET'])
def webhook_info():
    """Информация о вебхуке"""
    try:
        if application is None:
            return jsonify({"error": "application not initialized"}), 500
        
        global loop
        future = asyncio.run_coroutine_threadsafe(
            application.bot.get_webhook_info(),
            loop
        )
        info = future.result(timeout=5)
        
        return jsonify({
            "url": info.url,
            "has_custom_certificate": info.has_custom_certificate,
            "pending_update_count": info.pending_update_count,
            "max_connections": info.max_connections,
            "allowed_updates": info.allowed_updates
        })
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/debug')
def debug():
    """Отладочная информация"""
    return jsonify({
        "application_exists": application is not None,
        "update_exists": Update is not None,
        "loop_exists": loop is not None,
        "loop_closed": loop.is_closed() if loop else None,
        "webhook_secret": WEBHOOK_SECRET,
        "bot_imported": 'bot' in sys.modules,
        "pending_updates": 12  # из вашего getWebhookInfo
    })

# Для локального запуска
if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
