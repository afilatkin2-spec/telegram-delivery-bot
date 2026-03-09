from flask import Flask, request, jsonify
import json
import logging
import os
import sys
import asyncio
from functools import wraps

# Настройка логирования - ИСПРАВЛЕНО: asime -> asctime
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
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
    logger.info("✅ Глобальный event loop инициализирован")
    return loop

# Инициализируем loop сразу при загрузке
init_loop()

# Импортируем бота - ИСПРАВЛЕНО: импортируем application напрямую
try:
    import bot
    from telegram import Update
    application = bot.application
    TOKEN = bot.TOKEN
    logger.info("✅ Бот импортирован")
except Exception as e:
    logger.error(f"❌ Ошибка при импорте: {e}")
    application = None
    Update = None

# Секретный путь для вебхука
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "pavdanf")
logger.info(f"🔑 Секрет: {WEBHOOK_SECRET}")

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
            logger.error(f"❌ Ошибка в async_route: {e}")
            return jsonify({"error": str(e)}), 500
    return wrapper

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
@async_route
async def webhook():
    """Основной эндпоинт для вебхуков Telegram"""
    logger.info("📩 Получен POST запрос на webhook")
    
    if application is None or Update is None:
        logger.error("❌ Бот не инициализирован")
        return jsonify({"error": "Bot not initialized"}), 200
    
    try:
        json_string = request.get_data().decode('utf-8')
        logger.info(f"📦 Данные получены, длина: {len(json_string)}")
        
        update_data = json.loads(json_string)
        update = Update.de_json(update_data, application.bot)
        
        # Обрабатываем обновление
        await application.process_update(update)
        
        logger.info("✅ Webhook обработан успешно")
        return 'OK', 200
        
    except json.JSONDecodeError as e:
        logger.error(f"❌ Ошибка парсинга JSON: {e}")
        return jsonify({"error": "Invalid JSON"}), 200
    except Exception as e:
        logger.error(f"❌ Ошибка обработки вебхука: {e}")
        return jsonify({"error": str(e)}), 200

@app.route('/set_webhook', methods=['GET'])
@async_route
async def set_webhook():
    """Эндпоинт для установки вебхука"""
    if application is None:
        return jsonify({"error": "Bot not initialized"}), 500
    
    try:
        railway_url = request.host
        webhook_url = f"https://{railway_url}/{WEBHOOK_SECRET}"
        logger.info(f"🔄 Устанавливаем вебхук на: {webhook_url}")
        
        # Устанавливаем вебхук
        success = await application.bot.set_webhook(
            url=webhook_url,
            allowed_updates=['message', 'callback_query', 'edited_message'],
            drop_pending_updates=True
        )
        
        if success:
            webhook_info = await application.bot.get_webhook_info()
            logger.info(f"✅ Webhook установлен: {webhook_url}")
            return jsonify({
                "success": True,
                "message": f"Webhook установлен на {webhook_url}",
                "info": {
                    "url": webhook_info.url,
                    "pending_updates": webhook_info.pending_update_count
                }
            })
        else:
            logger.error("❌ Ошибка установки вебхука")
            return jsonify({"error": "Failed to set webhook"}), 400
            
    except Exception as e:
        logger.error(f"❌ Ошибка установки вебхука: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/webhook_info', methods=['GET'])
@async_route
async def webhook_info():
    """Информация о вебхуке"""
    if application is None:
        return jsonify({"error": "Bot not initialized"}), 500
    
    try:
        info = await application.bot.get_webhook_info()
        return jsonify({
            "url": info.url,
            "has_custom_certificate": info.has_custom_certificate,
            "pending_update_count": info.pending_update_count,
            "last_error_date": info.last_error_date,
            "last_error_message": info.last_error_message,
            "max_connections": info.max_connections,
            "allowed_updates": info.allowed_updates
        })
    except Exception as e:
        logger.error(f"❌ Ошибка получения информации: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/delete_webhook', methods=['GET'])
@async_route
async def delete_webhook():
    """Удаление вебхука"""
    if application is None:
        return jsonify({"error": "Bot not initialized"}), 500
    
    try:
        success = await application.bot.delete_webhook(drop_pending_updates=True)
        if success:
            logger.info("✅ Вебхук удален")
            return jsonify({"success": True, "message": "Webhook deleted"})
        else:
            return jsonify({"error": "Failed to delete webhook"}), 400
    except Exception as e:
        logger.error(f"❌ Ошибка удаления вебхука: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/debug')
def debug():
    """Отладочная информация"""
    import sys
    return jsonify({
        "bot_imported": 'bot' in sys.modules,
        "application_exists": application is not None,
        "update_exists": Update is not None,
        "webhook_secret": WEBHOOK_SECRET,
        "loop_exists": loop is not None,
        "loop_closed": loop.is_closed() if loop else None,
        "python_version": sys.version
    })

@app.route('/loop_status')
def loop_status():
    """Проверка статуса loop"""
    global loop
    return jsonify({
        "loop_exists": loop is not None,
        "loop_closed": loop.is_closed() if loop else None
    })

if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
