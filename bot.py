##
import logging
import re
import sys
import os
import json
import asyncio
from difflib import SequenceMatcher
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

# Минимальная проверка версии Python
if sys.version_info >= (3, 12):
    print("⚠️ Python 3.12+ может иметь ограничения")

# Импорты Telegram
try:
    from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, ConversationHandler
    import telegram
    print(f"✅ python-telegram-bot: {telegram.__version__}")
except ImportError as e:
    print(f"❌ Ошибка: {e}")
    print("Установите: pip install python-telegram-bot==20.7")
    sys.exit(1)

# Импорты Google Sheets
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
except ImportError as e:
    print(f"❌ Ошибка: {e}")
    print("Установите: pip install gspread oauth2client")
    sys.exit(1)

# ========== НАСТРОЙКИ ==========
TOKEN = os.getenv("TOKEN", "8221169246:AAFtryjOLkI2_ADQvZK5rvXLcJrgsJYnmX8")
CHAT_ID = os.getenv("CHAT_ID", "-4615357290")
SPREADSHEET_URL = os.getenv("SPREADSHEET_URL", "https://docs.google.com/spreadsheets/d/1-0CLwe15mNEHf81-bUVhVG0IJIIMF6PtvKfSDSh10xs/edit")
SHEET_NAME = os.getenv("SHEET_NAME", "Города")
REPORT_SHEET_NAME = os.getenv("REPORT_SHEET_NAME", "Отчётность")

# Состояния для ConversationHandler
ADDRESS, CONTACT = range(2)

# Статусы заявок
REQUEST_STATUS_CREATED = "создана"
REQUEST_STATUS_ASSIGNED = "назначен вп"
REQUEST_STATUS_EXPIRED = "просрочена"
REQUEST_STATUS_CANCELLED = "отказ партнёра"

# Таймаут заявки (в минутах)
REQUEST_TIMEOUT_MINUTES = 10

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Глобальные переменные
cities_list = []
request_counter = 1
user_requests: Dict[int, Dict[str, Any]] = {}
google_client = None
report_sheet = None
user_states: Dict[int, bool] = {}
temp_request_data: Dict[int, Dict[str, Any]] = {}
request_row_numbers: Dict[int, int] = {}
application = None


# ========== РАБОТА С GOOGLE SHEETS ==========
def init_google_sheets():
    """Инициализация Google Sheets"""
    global cities_list, google_client, report_sheet
    
    try:
        # Путь к credentials.json
        creds_path = 'credentials.json'
        
        # Для Railway - загружаем из переменной окружения
        if not os.path.exists(creds_path) and os.getenv('GOOGLE_CREDS_JSON'):
            logger.info("Загружаем credentials из переменных окружения")
            creds_dict = json.loads(os.getenv('GOOGLE_CREDS_JSON'))
            with open(creds_path, 'w') as f:
                json.dump(creds_dict, f)
        
        if not os.path.exists(creds_path):
            logger.error("❌ Файл credentials.json не найден")
            return False
        
        # Авторизация
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
        google_client = gspread.authorize(creds)
        
        # Получаем email сервисного аккаунта
        with open(creds_path, 'r') as f:
            service_email = json.load(f).get('client_email', 'Не найден')
            logger.info(f"✅ Сервисный аккаунт: {service_email}")
        
        # Открываем таблицу
        spreadsheet = google_client.open_by_url(SPREADSHEET_URL)
        logger.info(f"✅ Таблица: {spreadsheet.title}")
        
        # Загружаем города
        sheet = spreadsheet.worksheet(SHEET_NAME)
        all_data = sheet.get_all_values()
        
        start_row = 1 if all_data and all_data[0][0].lower() in ['регион', 'область'] else 0
        
        cities_list = []
        for row in all_data[start_row:]:
            if len(row) >= 2 and row[1].strip():
                cities_list.append({'region': row[0].strip(), 'city': row[1].strip()})
        
        logger.info(f"✅ Загружено {len(cities_list)} городов")
        
        # Настраиваем лист отчетности
        setup_report_sheet(spreadsheet)
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка Google Sheets: {e}")
        return False


def setup_report_sheet(spreadsheet):
    """Настройка листа отчетности"""
    global report_sheet
    
    try:
        try:
            report_sheet = spreadsheet.worksheet(REPORT_SHEET_NAME)
            logger.info(f"✅ Лист '{REPORT_SHEET_NAME}' найден")
            
            # Проверяем заголовки
            headers = report_sheet.row_values(1)
            expected = ["Номер заявки", "Ник отправителя", "Время создания", "Адрес доставки", "Контакт клиента", "Ник кто забрал", "Время взятия", "Статус"]
            
            if len(headers) < len(expected):
                report_sheet.update('A1:H1', [expected])
                logger.info("✅ Заголовки обновлены")
            
        except gspread.WorksheetNotFound:
            logger.info(f"Создаем лист '{REPORT_SHEET_NAME}'")
            report_sheet = spreadsheet.add_worksheet(title=REPORT_SHEET_NAME, rows=1000, cols=20)
            headers = ["Номер заявки", "Ник отправителя", "Время создания", "Адрес доставки", "Контакт клиента", "Ник кто забрал", "Время взятия", "Статус"]
            report_sheet.append_row(headers)
            logger.info("✅ Лист создан")
        
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка настройки: {e}")
        return False


def save_request_to_sheet(request_number: int, request_data: Dict):
    """Сохраняет заявку в таблицу"""
    global report_sheet, request_row_numbers
    
    if not report_sheet:
        return False
    
    try:
        row_data = [
            request_number,
            request_data.get('username', ''),
            request_data.get('created_at', ''),
            request_data.get('address', ''),
            request_data.get('contact', ''),
            '', '', REQUEST_STATUS_CREATED
        ]
        
        result = report_sheet.append_row(row_data, value_input_option='USER_ENTERED')
        
        if result:
            all_rows = report_sheet.get_all_values()
            request_row_numbers[request_number] = len(all_rows)
            logger.info(f"✅ Заявка №{request_number} сохранена")
            return True
        return False
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения: {e}")
        return False


def update_request_status(request_number: int, status: str, taken_by_username: str = None):
    """Обновляет статус заявки"""
    global report_sheet, request_row_numbers
    
    if not report_sheet:
        return False
    
    try:
        # Поиск строки
        row_number = request_row_numbers.get(request_number)
        
        if not row_number:
            all_rows = report_sheet.get_all_values()
            for i, row in enumerate(all_rows, start=1):
                if i > 1 and str(row[0]) == str(request_number):
                    row_number = i
                    request_row_numbers[request_number] = i
                    break
        
        if row_number:
            report_sheet.update(f'H{row_number}', status)
            
            if status == REQUEST_STATUS_ASSIGNED and taken_by_username:
                report_sheet.update(f'F{row_number}', taken_by_username)
                report_sheet.update(f'G{row_number}', datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            
            logger.info(f"✅ Статус заявки №{request_number} обновлен на '{status}'")
            return True
        
        logger.error(f"❌ Строка для заявки №{request_number} не найдена")
        return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка обновления статуса: {e}")
        return False


# ========== ФУНКЦИЯ ДЛЯ ПРОВЕРКИ ПРОСРОЧЕННЫХ ЗАЯВОК ==========
async def check_expired_requests(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет просроченные заявки и отправляет уведомления"""
    logger.info("🔍 Проверка просроченных заявок...")
    now = datetime.now()
    
    expired_requests = []
    
    for req_num, req_data in list(user_requests.items()):
        if req_data['status'] == REQUEST_STATUS_CREATED:
            created_at = datetime.strptime(req_data['created_at'], "%Y-%m-%d %H:%M:%S")
            age = now - created_at
            
            if age > timedelta(minutes=REQUEST_TIMEOUT_MINUTES):
                expired_requests.append((req_num, req_data))
    
    for req_num, req_data in expired_requests:
        logger.info(f"⏰ Заявка №{req_num} просрочена")
        
        # Обновляем статус
        req_data['status'] = REQUEST_STATUS_EXPIRED
        update_request_status(req_num, REQUEST_STATUS_EXPIRED)
        
        # Уведомление продающему партнёру
        try:
            if req_data.get('user_id'):
                await context.bot.send_message(
                    chat_id=req_data['user_id'],
                    text=(
                        f"⚠️ Заявка №{req_num} просрочена\n\n"
                        f"Никто не взял заявку в течение {REQUEST_TIMEOUT_MINUTES} минут.\n"
                        f"📝 Адрес: {req_data['address']}\n"
                        f"📞 Контакт: {req_data.get('contact', 'Не указан')}\n\n"
                        f"❌ Отправьте заявку в СВК"
                    )
                )
                logger.info(f"✅ Уведомление о просрочке отправлено @{req_data['username']}")
        except Exception as e:
            logger.error(f"❌ Ошибка уведомления о просрочке: {e}")
        
        # Уведомление в общий чат
        try:
            await context.bot.send_message(
                chat_id=int(CHAT_ID),
                text=(
                    f"⏰ Заявка №{req_num} закрыта\n"
                    f"📝 Адрес: {req_data['address']}\n"
                    f"👤 От: @{req_data['username']}\n"
                    f"❌ Причина: никто не взял в течение {REQUEST_TIMEOUT_MINUTES} минут"
                )
            )
            logger.info(f"✅ Уведомление о закрытии отправлено в чат")
        except Exception as e:
            logger.error(f"❌ Ошибка уведомления в чат: {e}")
        
        # Удаляем кнопку из сообщения в чате
        try:
            if req_data.get('message_id'):
                await context.bot.edit_message_text(
                    chat_id=int(CHAT_ID),
                    message_id=req_data['message_id'],
                    text=f"📦 Заявка №{req_num}\n📝 Адрес: {req_data['address']}\n👤 От: @{req_data['username']}\n\n❌ ЗАЯВКА ПРОСРОЧЕНА"
                )
        except Exception as e:
            logger.error(f"❌ Ошибка удаления кнопки: {e}")
    
    if expired_requests:
        logger.info(f"✅ Обработано {len(expired_requests)} просроченных заявок")


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def normalize_text(text: str) -> str:
    """Нормализация текста"""
    text = text.lower()
    text = ' '.join(text.split())
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\b(г|гор|город|пос|поселок|деревня|д|сел|село|область|рн|район)\b', '', text)
    return text.strip()


def find_matching_city(address: str, threshold: float = 0.75) -> Optional[dict]:
    """Поиск города"""
    if not cities_list:
        return None
    
    normalized_address = normalize_text(address)
    best_match = None
    best_ratio = 0
    
    for city_item in cities_list:
        normalized_city = normalize_text(city_item['city'])
        
        if normalized_city in normalized_address:
            return city_item
        
        if len(normalized_city) > 3 and normalized_city in normalized_address:
            return city_item
        
        ratio = SequenceMatcher(None, normalized_address, normalized_city).ratio()
        if ratio > best_ratio and ratio > threshold:
            best_ratio = ratio
            best_match = city_item
    
    return best_match


def get_next_request_number() -> int:
    """Номер заявки"""
    global request_counter
    current = request_counter
    request_counter += 1
    return current


# ========== КНОПКИ ==========
def get_initial_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("📋 Инструкция")]], resize_keyboard=True)

def get_main_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("📝 Оставить заявку")]], resize_keyboard=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("❌ Отменить")]], resize_keyboard=True)

def get_partner_chat_keyboard(request_number: int):
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Забрать заявку", callback_data=f"accept_{request_number}")]])

def get_cancel_request_keyboard(request_number: int):
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отказаться от заявки", callback_data=f"cancel_{request_number}")]])


# ========== ИНСТРУКЦИЯ ==========
SIMPLE_INSTRUCTION = """
📋 *ИНСТРУКЦИЯ*

👤 *Для продающих партнёров:*
• Нажмите «📝 Оставить заявку»
• Введите адрес клиента
• Укажите способ связи
• Получите номер заявки
• Ждите, когда заявку заберут
• Придёт уведомление о взятии
• Если за 10 мин никто не взял - отправьте в СВК

⚡️ *Для выдающих партнёров:*
• Кнопка «✅ Забрать заявку» в чате
• Нажмите, чтобы принять
• В личку придёт информация
• Продающий получит уведомление
• Если не можете выполнить - откажитесь в личном чате с ботом командой /my_requests

✅ Всё просто!
"""


# ========== ОБРАБОТЧИКИ ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start - начинаем с нуля"""
    import traceback
    logger.info("=" * 50)
    logger.info("🔥 ФУНКЦИЯ START ВЫЗВАНА!")
    
    user_id = update.effective_user.id
    target_chat_id = int(CHAT_ID)
    
    # Игнорируем сообщения из чата партнеров
    if update.effective_chat.id == target_chat_id:
        await update.message.reply_text("❌ В этом чате доступна только /status")
        return ConversationHandler.END
    
    try:
        # Сбрасываем состояние пользователя
        logger.info(f"🔄 Сбрасываем состояние пользователя {user_id}")
        
        # Удаляем из user_states, чтобы считался новым
        if user_id in user_states:
            del user_states[user_id]
            logger.info(f"✅ Удален user_states для {user_id}")
        
        # Очищаем временные данные, если есть
        if user_id in temp_request_data:
            del temp_request_data[user_id]
            logger.info(f"✅ Удалены temp_request_data для {user_id}")
        
        # Очищаем данные контекста
        if context.user_data:
            context.user_data.clear()
            logger.info(f"✅ Очищен context.user_data для {user_id}")
        
        # Показываем начальный экран
        logger.info(f"✅ Показываем начальный экран для пользователя {user_id}")
        
        await update.message.reply_text(
            "👋 Добро пожаловать!\n\nНажмите «📋 Инструкция» для начала работы",
            reply_markup=get_initial_keyboard()
        )
        
        logger.info(f"✅ /start обработан для пользователя {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка в start: {e}")
        logger.error(traceback.format_exc())
    
    logger.info("=" * 50)
    return ConversationHandler.END


async def instruction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает инструкцию"""
    user_id = update.effective_user.id
    logger.info(f"📋 ИНСТРУКЦИЯ вызвана для пользователя {user_id}")
    
    try:
        await update.message.reply_text(
            SIMPLE_INSTRUCTION, 
            parse_mode='Markdown', 
            reply_markup=get_main_keyboard()
        )
        user_states[user_id] = True
        logger.info(f"✅ Инструкция показана пользователю {user_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка в instruction: {e}")
    
    return ConversationHandler.END


async def start_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало создания заявки"""
    logger.info(f"📝 start_request вызван пользователем {update.effective_user.id}")
    await update.message.reply_text("Введите адрес доставки:", reply_markup=get_cancel_keyboard())
    return ADDRESS


async def handle_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка адреса"""
    user_id = update.effective_user.id
    user_address = update.message.text
    logger.info(f"📍 Обработка адреса от {user_id}: {user_address}")
    
    if user_id not in temp_request_data:
        temp_request_data[user_id] = {}
    temp_request_data[user_id]['address'] = user_address
    temp_request_data[user_id]['username'] = update.effective_user.username or f"user_{user_id}"
    
    if find_matching_city(user_address):
        await update.message.reply_text(
            "✅ Город найден!\n\nУкажите способ связи с клиентом:"
        )
        return CONTACT
    else:
        await update.message.reply_text(
            "❌ Адрес не найден. Отправьте клиенту анкету",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END


async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка контакта и создание заявки"""
    user_id = update.effective_user.id
    user_contact = update.message.text
    target_chat_id = int(CHAT_ID)
    
    user_data = temp_request_data.get(user_id, {})
    user_address = user_data.get('address', '')
    username = user_data.get('username', f"user_{user_id}")
    
    request_number = get_next_request_number()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    user_requests[request_number] = {
        'user_id': user_id,
        'username': username,
        'address': user_address,
        'contact': user_contact,
        'matched_city': find_matching_city(user_address),
        'taken_by': None,
        'taken_by_username': None,
        'taken_by_id': None,
        'created_at': current_time,
        'status': REQUEST_STATUS_CREATED,
        'message_id': None
    }
    
    save_request_to_sheet(request_number, user_requests[request_number])
    
    sent_message = await context.bot.send_message(
        chat_id=target_chat_id,
        text=f"📦 Новая заявка №{request_number}\n📝 Адрес: {user_address}\n👤 От: @{username}",
        reply_markup=get_partner_chat_keyboard(request_number)
    )
    
    user_requests[request_number]['message_id'] = sent_message.message_id
    
    await update.message.reply_text(
        f"✅ Заявка №{request_number} отправлена\nКонтакт: {user_contact}\n\nЕсли никто не свяжется за 10 минут, отправьте анкету",
        reply_markup=get_main_keyboard()
    )
    
    if user_id in temp_request_data:
        del temp_request_data[user_id]
    
    logger.info(f"✅ Заявка №{request_number} создана")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена"""
    user_id = update.effective_user.id
    if user_id in temp_request_data:
        del temp_request_data[user_id]
    await update.message.reply_text("❌ Отменено", reply_markup=get_main_keyboard())
    return ConversationHandler.END


async def handle_partner_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка чата партнеров"""
    target_chat_id = int(CHAT_ID)
    
    if update.effective_chat.id != target_chat_id:
        return
    
    logger.info(f"🔵 Сообщение от @{update.effective_user.username}")
    
    # Ответ на сообщение
    if update.message and update.message.reply_to_message:
        replied_message = update.message.reply_to_message
        partner = update.effective_user
        partner_username = partner.username or f"user_{partner.id}"
        
        for req_num, req_data in user_requests.items():
            if req_data.get('message_id') == replied_message.message_id and req_data.get('status') == REQUEST_STATUS_CREATED:
                await accept_request(update, context, req_data, req_num, partner, partner_username, partner.full_name or partner_username, target_chat_id)
                return
        
        await update.message.reply_text("❌ Заявка неактивна")
        return
    
    # Простой текст
    if update.message and update.message.text and not update.message.text.startswith('/'):
        await update.message.reply_text(
            "ℹ️ Забрать заявку:\n• Кнопка ✅\n• Ответ на сообщение\n• /take <номер>\n\n/status - список"
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка inline-кнопок"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    target_chat_id = int(CHAT_ID)
    
    if data.startswith("accept_"):
        request_number = int(data.split("_")[1])
        partner = query.from_user
        partner_username = partner.username or f"user_{partner.id}"
        
        if request_number in user_requests and user_requests[request_number]['status'] == REQUEST_STATUS_CREATED:
            await accept_request(query, context, user_requests[request_number], request_number, 
                               partner, partner_username, partner.full_name or partner_username, target_chat_id)
            await query.edit_message_text(text=query.message.text)
        else:
            await query.edit_message_text(text=query.message.text + "\n\n❌ Заявка неактивна")
    
    elif data.startswith("cancel_"):
        request_number = int(data.split("_")[1])
        partner = query.from_user
        
        if request_number in user_requests and user_requests[request_number]['status'] == REQUEST_STATUS_ASSIGNED:
            if user_requests[request_number].get('taken_by_id') == partner.id:
                await cancel_request(query, context, user_requests[request_number], request_number)
                await query.edit_message_text(text=query.message.text + "\n\n✅ Вы отказались от заявки")
            else:
                await query.edit_message_text(text=query.message.text + "\n\n❌ Это не ваша заявка")
        else:
            await query.edit_message_text(text=query.message.text + "\n\n❌ Заявка уже неактивна")


async def accept_request(update_or_query, context, req_data, request_number, partner, 
                        partner_username, partner_full_name, target_chat_id):
    """Принятие заявки"""
    
    req_data['taken_by'] = partner_full_name
    req_data['taken_by_username'] = partner_username
    req_data['taken_by_id'] = partner.id
    req_data['status'] = REQUEST_STATUS_ASSIGNED
    req_data['taken_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    logger.info(f"✅ @{partner_username} взял заявку №{request_number}")
    
    # Сообщение в чат
    await context.bot.send_message(
        chat_id=target_chat_id,
        text=f"🔥 Выдающий партнёр @{partner_username} забрал заявку №{request_number}"
    )
    
    # Информация партнеру
    try:
        await context.bot.send_message(
            chat_id=partner.id,
            text=(
                f"📬 Вы приняли заявку №{request_number}\n\n"
                f"Инфо по доставке\n"
                f"   • Адрес: {req_data['address']}\n"
                f"   • Контакт: {req_data.get('contact', 'Не указан')}\n\n"
                f"💬 Напишите @{req_data['username']} для деталей\n\n"
                f"Если не можете выполнить - используйте /my_requests для отказа"
            ),
            reply_markup=get_cancel_request_keyboard(request_number)
        )
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
    
    # Уведомление продающему
    try:
        if req_data.get('user_id'):
            await context.bot.send_message(
                chat_id=req_data['user_id'],
                text=(
                    f"📢 Заявка №{request_number}\n\n"
                    f"🔥 Партнёр @{partner_username} взял вашу заявку!\n\n"
                    f"📝 Адрес: {req_data['address']}\n"
                    f"📞 Контакт: {req_data.get('contact', 'Не указан')}\n\n"
                    f"💬 Свяжитесь: @{partner_username}"
                )
            )
    except Exception as e:
        logger.error(f"❌ Ошибка уведомления: {e}")
    
    # Обновление в таблице
    update_request_status(request_number, REQUEST_STATUS_ASSIGNED, partner_username)
    
    # Ответ, если это reply
    if hasattr(update_or_query, 'message') and not hasattr(update_or_query, 'edit_message_text'):
        await update_or_query.message.reply_text(
            f"✅ Вы взяли заявку №{request_number}. Информация в личке"
        )


async def accept_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /accept (только личка)"""
    target_chat_id = int(CHAT_ID)
    
    if update.effective_chat.id == target_chat_id:
        await update.message.reply_text("❌ Используйте /take")
        return
    
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ Использование: /accept <номер>")
        return
    
    request_number = int(context.args[0])
    partner = update.effective_user
    partner_username = partner.username or f"user_{partner.id}"
    
    if request_number in user_requests and user_requests[request_number]['status'] == REQUEST_STATUS_CREATED:
        await accept_request(update, context, user_requests[request_number], request_number,
                           partner, partner_username, partner.full_name or partner_username, target_chat_id)
    else:
        await update.message.reply_text(f"❌ Заявка №{request_number} не найдена")


async def take_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /take (только чат)"""
    target_chat_id = int(CHAT_ID)
    
    if update.effective_chat.id != target_chat_id:
        await update.message.reply_text("❌ /take только в чате")
        return
    
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ Использование: /take <номер>\n/status - список")
        return
    
    request_number = int(context.args[0])
    partner = update.effective_user
    partner_username = partner.username or f"user_{partner.id}"
    
    if request_number in user_requests and user_requests[request_number]['status'] == REQUEST_STATUS_CREATED:
        await accept_request(update, context, user_requests[request_number], request_number,
                           partner, partner_username, partner.full_name or partner_username, target_chat_id)
        logger.info(f"✅ /take {request_number} от @{partner_username}")
    else:
        await update.message.reply_text(f"❌ Заявка №{request_number} не найдена")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status"""
    active = [f"№{num} - {d['address']} - @{d['username']} - Контакт: {d.get('contact', '?')}" 
              for num, d in user_requests.items() if d['status'] == REQUEST_STATUS_CREATED]
    
    if active:
        await update.message.reply_text("📋 Активные заявки:\n" + "\n".join(active))
    else:
        await update.message.reply_text("📋 Нет активных заявок")


async def my_requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /my_requests - показать взятые заявки и возможность отказа"""
    user_id = update.effective_user.id
    
    my_active = []
    for req_num, req_data in user_requests.items():
        if req_data.get('taken_by_id') == user_id and req_data['status'] == REQUEST_STATUS_ASSIGNED:
            my_active.append((req_num, req_data))
    
    if not my_active:
        await update.message.reply_text("📋 У вас нет активных взятых заявок")
        return
    
    for req_num, req_data in my_active:
        keyboard = get_cancel_request_keyboard(req_num)
        await update.message.reply_text(
            f"📦 Заявка №{req_num}\n"
            f"📝 Адрес: {req_data['address']}\n"
            f"👤 Продающий: @{req_data['username']}\n"
            f"📞 Контакт: {req_data.get('contact', 'Не указан')}\n"
            f"⏰ Взята: {req_data.get('taken_at', 'Неизвестно')}",
            reply_markup=keyboard
        )


async def cancel_request(update_or_query, context, req_data, request_number):
    """Отказ от заявки"""
    
    req_data['status'] = REQUEST_STATUS_CANCELLED
    logger.info(f"❌ Партнёр @{req_data['taken_by_username']} отказался от заявки №{request_number}")
    
    # Обновляем статус в таблице
    update_request_status(request_number, REQUEST_STATUS_CANCELLED)
    
    # Уведомление продающему партнёру
    try:
        if req_data.get('user_id'):
            await context.bot.send_message(
                chat_id=req_data['user_id'],
                text=(
                    f"⚠️ Заявка №{request_number}\n\n"
                    f"Партнёр @{req_data['taken_by_username']} отказался от заявки.\n\n"
                    f"📝 Адрес: {req_data['address']}\n"
                    f"📞 Контакт: {req_data.get('contact', 'Не указан')}\n\n"
                    f"❌ Отправьте заявку в СВК"
                )
            )
            logger.info(f"✅ Уведомление об отказе отправлено @{req_data['username']}")
    except Exception as e:
        logger.error(f"❌ Ошибка уведомления об отказе: {e}")
    
    # Уведомление партнёру, который отказался
    try:
        await context.bot.send_message(
            chat_id=req_data['taken_by_id'],
            text=f"✅ Вы отказались от заявки №{request_number}"
        )
    except Exception as e:
        logger.error(f"❌ Ошибка подтверждения отказа: {e}")
    
    # Удаляем кнопку из сообщения в чате
    try:
        if req_data.get('message_id'):
            await context.bot.edit_message_text(
                chat_id=int(CHAT_ID),
                message_id=req_data['message_id'],
                text=f"📦 Заявка №{request_number}\n📝 Адрес: {req_data['address']}\n👤 От: @{req_data['username']}\n\n❌ ОТКАЗ ПАРТНЁРА @{req_data['taken_by_username']}"
            )
    except Exception as e:
        logger.error(f"❌ Ошибка обновления сообщения: {e}")


# ========== ФУНКЦИЯ СОЗДАНИЯ APPLICATION ==========
def create_application():
    """Создание приложения"""
    global application
    
    application = Application.builder().token(TOKEN).build()
    partner_chat_id = int(CHAT_ID)
    
    # Conversation для заявок
    request_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Text("📝 Оставить заявку"), start_request)],
        states={
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Text("❌ Отменить"), handle_address)],
            CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Text("❌ Отменить"), handle_contact)],
        },
        fallbacks=[MessageHandler(filters.Text("❌ Отменить"), cancel)],
    )
    
    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("accept", accept_command))
    application.add_handler(CommandHandler("take", take_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("my_requests", my_requests_command))
    
    # Обработчики
    application.add_handler(MessageHandler(filters.Text("📋 Инструкция"), instruction))
    application.add_handler(request_conv)
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.Chat(chat_id=partner_chat_id), handle_partner_chat))
    application.add_handler(MessageHandler(filters.Text("❌ Отменить") & filters.ChatType.PRIVATE, cancel))
    
    # Добавляем периодическую задачу для проверки просроченных заявок
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(check_expired_requests, interval=60, first=10)
        logger.info("✅ Запущена проверка просроченных заявок каждые 60 секунд")
    
    return application


# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
def main():
    """Запуск"""
    print("🚀 Запуск бота...")
    print(f"📦 python-telegram-bot: {telegram.__version__}")
    
    if not init_google_sheets():
        print("❌ Ошибка подключения к Google Sheets")
        return
    
    try:
        app = create_application()
        print("✅ Бот готов к работе")
        print("📊 Railway: автоматический режим")
        print("⏰ Проверка просроченных заявок: каждые 60 секунд")
        print("❌ Отказ от заявки: /my_requests в личном чате")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()


# ========== ДЛЯ RAILWAY ==========
if __name__ != '__main__':
    print("🔄 Загрузка для Railway...")
    init_google_sheets()
    application = create_application()
    
    # ВАЖНО: Инициализируем application для работы с вебхуками
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(application.initialize())
        print("✅ Application инициализирован")
    except Exception as e:
        print(f"❌ Ошибка инициализации: {e}")
    finally:
        loop.close()
    
    print("✅ Бот загружен")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
