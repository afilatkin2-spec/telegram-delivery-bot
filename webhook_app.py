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

# Секретный путь для вебхука (должен совпадать с тем, что в setWebhook)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "pavdanf")

@app.route('/')
def index():
    """Главная страница"""
    return jsonify({
        "status": "running",
        "message": "Telegram bot is running on Railway!"
    })

@app.route('/health')
def health():
    """Проверка здоровья"""
    return jsonify({"status": "healthy"})

@app.route(f'/{WEBHOOK_SECRET}', methods=['POST'])
def webhook():
    """
    ОСНОВНОЙ ЭНДПОИНТ ДЛЯ ВЕБХУКОВ TELEGRAM
    ВАЖНО: methods=['POST'] обязателен!
    """
    # Логируем входящий запрос
    logger.info("📩 Получен POST запрос на webhook")
    
    # Проверяем метод запроса (на всякий случай)
    if request.method != 'POST':
        logger.error(f"❌ Неправильный метод: {request.method}")
        return jsonify({"error": "Method not allowed"}), 405
    
    try:
        # Получаем данные от Telegram
        json_string = request.get_data().decode('utf-8')
        
        if not json_string:
            logger.error("❌ Пустой запрос")
            return jsonify({"error": "Empty request"}), 400
        
        logger.info(f"📦 Получены данные: {json_string[:200]}...")
        
        # Проверяем инициализацию
        if application is None:
            logger.error("❌ application не инициализирован")
            return jsonify({"error": "Application not initialized"}), 500
        
        if Update is None:
            logger.error("❌ Update не импортирован")
            return jsonify({"error": "Update not imported"}), 500
        
        # Парсим обновление
        try:
            update_data = json.loads(json_string)
            update = Update.de_json(update_data, application.bot)
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга JSON: {e}")
            return jsonify({"error": f"Invalid JSON: {e}"}), 400
        
        # Запускаем асинхронную обработку в нашем loop
        global loop
        future = asyncio.run_coroutine_threadsafe(
            application.process_update(update), 
            loop
        )
        
        # Ждем результат (таймаут 30 секунд)
        try:
            future.result(timeout=30)
            logger.info("✅ Webhook обработан успешно")
        except asyncio.TimeoutError:
            logger.error("❌ Таймаут обработки")
            return jsonify({"error": "Processing timeout"}), 500
        except Exception as e:
            logger.error(f"❌ Ошибка обработки: {e}")
            return jsonify({"error": f"Processing error: {e}"}), 500
        
        # ВАЖНО: Telegram ожидает ответ "OK" со статусом 200
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        return jsonify({"error": f"Internal error: {e}"}), 500

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    """Установка вебхука (вызвать один раз)"""
    try:
        if application is None:
            return jsonify({"error": "Application not initialized"}), 500
        
        # Получаем домен из запроса
        railway_url = request.host
        webhook_url = f"https://{railway_url}/{WEBHOOK_SECRET}"
        
        logger.info(f"🔄 Устанавливаем вебхук на: {webhook_url}")
        
        # Запускаем асинхронную установку
        global loop
        future = asyncio.run_coroutine_threadsafe(
            application.bot.set_webhook(
                url=webhook_url,
                allowed_updates=['message', 'callback_query', 'edited_message'],
                max_connections=40,
                drop_pending_updates=True
            ),
            loop
        )
        
        success = future.result(timeout=10)
        
        if success:
            logger.info(f"✅ Вебхук установлен на {webhook_url}")
            return jsonify({
                "success": True,
                "message": f"Webhook установлен на {webhook_url}"
            })
        else:
            logger.error("❌ Не удалось установить вебхук")
            return jsonify({"error": "Failed to set webhook"}), 400
            
    except Exception as e:
        logger.error(f"❌ Ошибка установки вебхука: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/webhook_info', methods=['GET'])
def webhook_info():
    """Информация о текущем вебхуке"""
    try:
        if application is None:
            return jsonify({"error": "Application not initialized"}), 500
        
        global loop
        future = asyncio.run_coroutine_threadsafe(
            application.bot.get_webhook_info(),
            loop
        )
        info = future.result(timeout=10)
        
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
def delete_webhook():
    """Удаление вебхука"""
    try:
        if application is None:
            return jsonify({"error": "Application not initialized"}), 500
        
        global loop
        future = asyncio.run_coroutine_threadsafe(
            application.bot.delete_webhook(drop_pending_updates=True),
            loop
        )
        success = future.result(timeout=10)
        
        if success:
            logger.info("✅ Вебхук удален")
            return jsonify({"success": True, "message": "Webhook deleted"})
        else:
            return jsonify({"error": "Failed to delete webhook"}), 400
            
    except Exception as e:
        logger.error(f"❌ Ошибка удаления: {e}")
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
        "python_version": sys.version,
        "flask_app": "running"
    })

# Для локального запуска
if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
