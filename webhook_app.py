from flask import Flask, request
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

app = Flask(__name__)

# Импортируем бота и сразу инициализируем
try:
    from bot import create_application
    from telegram import Update
    import telegram.ext
    
    logger.info("🔄 Создаем и инициализируем application...")
    
    # Создаем application через нашу функцию
    application = create_application()
    
    # ВАЖНО: ЯВНО ИНИЦИАЛИЗИРУЕМ
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(application.initialize())
    loop.close()
    
    logger.info("✅ Application успешно создан и инициализирован")
    
except Exception as e:
    logger.error(f"❌ Ошибка при создании application: {e}")
    application = None

# Секретный путь для вебхука
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "telegram-webhook-secret")

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
def webhook():
    """Основной эндпоинт для вебхуков Telegram"""
    if request.method == 'POST':
        try:
            json_string = request.get_data().decode('utf-8')
            update = Update.de_json(json.loads(json_string), application.bot)
            
            # Создаем новый event loop для каждого запроса
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Проверяем, инициализирован ли application
                if not hasattr(application, '_initialized'):
                    logger.info("🔄 Инициализируем application...")
                    loop.run_until_complete(application.initialize())
                    application._initialized = True
                
                # Обрабатываем обновление
                loop.run_until_complete(application.process_update(update))
            finally:
                loop.close()
            
            return 'OK', 200
        except Exception as e:
            logger.error(f"❌ Ошибка обработки вебхука: {e}")
            return 'Error', 500
    return 'OK', 200

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    """Эндпоинт для установки вебхука"""
    try:
        railway_url = os.getenv("RAILWAY_PUBLIC_DOMAIN")
        if not railway_url:
            railway_url = request.host
            logger.info(f"Домен из запроса: {railway_url}")
        
        webhook_url = f"https://{railway_url}/{WEBHOOK_SECRET}"
        logger.info(f"Устанавливаем вебхук на: {webhook_url}")
        
        # Создаем новый event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Проверяем инициализацию
            if not hasattr(application, '_initialized'):
                logger.info("🔄 Инициализируем application...")
                loop.run_until_complete(application.initialize())
                application._initialized = True
            
            # Устанавливаем вебхук
            success = loop.run_until_complete(application.bot.set_webhook(url=webhook_url))
            
            if success:
                # Получаем информацию о вебхуке
                webhook_info = loop.run_until_complete(application.bot.get_webhook_info())
                logger.info(f"✅ Webhook info: {webhook_info}")
                return f"✅ Webhook установлен на {webhook_url}", 200
            else:
                return "❌ Ошибка установки вебхука", 400
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return f"❌ Ошибка: {e}", 500

@app.route('/reinit', methods=['GET'])
def reinit():
    """Принудительная переинициализация"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        loop.run_until_complete(application.initialize())
        application._initialized = True
        
        loop.close()
        return "✅ Application переинициализирован", 200
    except Exception as e:
        return f"❌ Ошибка: {e}", 500

if __name__ == '__main__':
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
