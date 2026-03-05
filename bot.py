import logging
import re
import sys
from difflib import SequenceMatcher
from typing import Optional, Dict, Any
from datetime import datetime

# Проверка версии Python
if sys.version_info >= (3, 12):
    print(f"⚠️ Внимание: Вы используете Python {sys.version_info.major}.{sys.version_info.minor}")

try:
    from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, ConversationHandler
    import telegram
    print(f"✅ python-telegram-bot версия: {telegram.__version__}")
except ImportError as e:
    print(f"❌ Ошибка импорта telegram: {e}")
    print("Установите: pip install python-telegram-bot==20.7")
    sys.exit(1)

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from google.auth.exceptions import GoogleAuthError

# ========== НАСТРОЙКИ ==========
TOKEN = "8221169246:AAFtryjOLkI2_ADQvZK5rvXLcJrgsJYnmX8"
CHAT_ID = "-4615357290"  # Оставляем как есть, с минусом
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1-0CLwe15mNEHf81-bUVhVG0IJIIMF6PtvKfSDSh10xs/edit"
SHEET_NAME = "Города"
REPORT_SHEET_NAME = "Отчётность"

# Состояния для ConversationHandler
ADDRESS, CONTACT = range(2)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальные переменные
cities_list = []
request_counter = 1
user_requests: Dict[int, Dict[str, Any]] = {}
google_client = None
report_sheet = None
user_states: Dict[int, bool] = {}  # Словарь для отслеживания, видел ли пользователь инструкцию
temp_request_data: Dict[int, Dict[str, Any]] = {}  # Временное хранение данных заявки

# Создаем application как глобальную переменную
application = None


# ========== РАБОТА С GOOGLE SHEETS ==========
def init_google_sheets():
    """Инициализация подключения к Google Sheets и загрузка списка городов"""
    global cities_list, google_client, report_sheet
    
    try:
        import os
        current_dir = os.path.dirname(os.path.abspath(__file__))
        creds_path = os.path.join(current_dir, 'credentials.json')
        
        # Для Railway - проверяем, есть ли credentials в переменных окружения
        if not os.path.exists(creds_path) and os.getenv('GOOGLE_CREDS_JSON'):
            import json
            logger.info("Загружаем credentials из переменных окружения")
            creds_dict = json.loads(os.getenv('GOOGLE_CREDS_JSON'))
            with open(creds_path, 'w') as f:
                json.dump(creds_dict, f)
        
        logger.info(f"Поиск credentials.json в: {creds_path}")
        
        if not os.path.exists(creds_path):
            logger.error(f"❌ Файл credentials.json не найден по пути: {creds_path}")
            return False
        
        scope = ["https://spreadsheets.google.com/feeds", 
                 "https://www.googleapis.com/auth/drive",
                 "https://www.googleapis.com/auth/spreadsheets"]
        
        creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
        google_client = gspread.authorize(creds)
        
        # Получаем email сервисного аккаунта для отладки
        with open(creds_path, 'r') as f:
            import json
            creds_data = json.load(f)
            service_email = creds_data.get('client_email', 'Не найден')
            logger.info(f"✅ Сервисный аккаунт: {service_email}")
            logger.info(f"⚠️ ВАЖНО: Добавьте этот email в редакторы таблицы!")
        
        # Открываем таблицу по URL
        logger.info(f"Открываем таблицу: {SPREADSHEET_URL}")
        spreadsheet = google_client.open_by_url(SPREADSHEET_URL)
        logger.info(f"✅ Таблица открыта: {spreadsheet.title}")
        
        # Загружаем города
        sheet = spreadsheet.worksheet(SHEET_NAME)
        all_data = sheet.get_all_values()
        
        start_row = 1 if all_data and all_data[0][0].lower() in ['регион', 'область'] else 0
        
        cities_list = []
        for row in all_data[start_row:]:
            if len(row) >= 2 and row[1].strip():
                cities_list.append({
                    'region': row[0].strip(),
                    'city': row[1].strip()
                })
        
        logger.info(f"✅ Загружено {len(cities_list)} городов из листа '{SHEET_NAME}'")
        
        # Настраиваем лист отчетности
        setup_report_sheet(spreadsheet)
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка при загрузке из Google Sheets: {e}")
        return False


def setup_report_sheet(spreadsheet):
    """Проверяет или создает лист отчетности"""
    global report_sheet
    
    try:
        try:
            report_sheet = spreadsheet.worksheet(REPORT_SHEET_NAME)
            logger.info(f"✅ Лист '{REPORT_SHEET_NAME}' найден")
            
            # Проверяем, есть ли заголовок для контакта
            headers = report_sheet.row_values(1)
            expected_headers = ["Номер заявки", "Ник отправителя", "Время создания", "Адрес доставки", "Контакт клиента", "Ник кто забрал", "Время взятия"]
            
            if len(headers) < len(expected_headers):
                # Обновляем заголовки если нужно
                logger.info(f"Обновляем заголовки в листе '{REPORT_SHEET_NAME}'")
                report_sheet.update('A1:G1', [expected_headers])
            
        except gspread.WorksheetNotFound:
            logger.info(f"Создаем новый лист '{REPORT_SHEET_NAME}'")
            report_sheet = spreadsheet.add_worksheet(title=REPORT_SHEET_NAME, rows=1000, cols=20)
            headers = ["Номер заявки", "Ник отправителя", "Время создания", "Адрес доставки", "Контакт клиента", "Ник кто забрал", "Время взятия"]
            report_sheet.append_row(headers)
            logger.info(f"✅ Создан новый лист '{REPORT_SHEET_NAME}' с заголовками")
        
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка при настройке листа отчетности: {e}")
        return False


def save_request_to_sheet(request_number: int, request_data: Dict):
    """Сохраняет данные заявки в лист отчетности"""
    global report_sheet
    
    if report_sheet is None:
        logger.error(f"❌ Лист отчетности не инициализирован")
        return False
    
    try:
        row_data = [
            request_number,
            request_data.get('username', ''),
            request_data.get('created_at', ''),
            request_data.get('address', ''),
            request_data.get('contact', ''),
            request_data.get('taken_by_username', ''),
            request_data.get('taken_at', '')
        ]
        
        logger.info(f"Сохраняем данные заявки №{request_number}: {row_data}")
        result = report_sheet.append_row(row_data, value_input_option='USER_ENTERED')
        
        if result:
            logger.info(f"✅ Данные заявки №{request_number} сохранены в лист '{REPORT_SHEET_NAME}'")
            return True
        else:
            return False
        
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении заявки №{request_number}: {e}")
        return False


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def normalize_text(text: str) -> str:
    """Нормализация текста для сравнения"""
    text = text.lower()
    text = ' '.join(text.split())
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\b(г|гор|город|пос|поселок|деревня|д|сел|село|область|рн|район)\b', '', text)
    return text.strip()


def find_matching_city(address: str, threshold: float = 0.75) -> Optional[dict]:
    """Поиск совпадения адреса с городом из списка"""
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
    """Получение следующего номера заявки"""
    global request_counter
    current = request_counter
    request_counter += 1
    return current


# ========== ФУНКЦИИ ДЛЯ КНОПОК ==========
def get_initial_keyboard():
    """Клавиатура при первом запуске - только одна кнопка"""
    keyboard = [
        [KeyboardButton("📋 Инструкция")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_main_keyboard():
    """Основная клавиатура с кнопкой заявки"""
    keyboard = [
        [KeyboardButton("📝 Оставить заявку")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_cancel_keyboard():
    """Клавиатура с кнопкой отмены"""
    keyboard = [
        [KeyboardButton("❌ Отменить")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_partner_chat_keyboard(request_number: int):
    """Inline-кнопки для заявки в чате партнеров"""
    keyboard = [
        [InlineKeyboardButton("✅ Забрать заявку", callback_data=f"accept_{request_number}")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ========== ИНСТРУКЦИЯ ==========
SIMPLE_INSTRUCTION = """
📋 *ИНСТРУКЦИЯ*

👤 *Для продающих партнёров:*
• Чтобы оставить заявку, нажмите кнопку «📝 Оставить заявку»
• Введите адрес клиента
• Укажите способ связи с клиентом
• Получите номер заявки
• Ожидайте, когда выдающий партнёр её заберёт

⚡️ *Для выдающих партнёров:*
• Кнопка «✅ Забрать заявку» появится в вашем региональном чате
• Нажмите её, чтобы принять заявку
• В личные сообщения придёт информация по доставке

✅ *Всё просто!* Нажмите «📝 Оставить заявку» для создания заявки
"""


# ========== ОБРАБОТЧИКИ ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start - первый запуск"""
    user_id = update.effective_user.id
    
    # Проверяем, что это личное сообщение, а не чат партнеров
    target_chat_id = int(CHAT_ID)
    if update.effective_chat.id == target_chat_id:
        # В чате партнеров команда /start не работает
        await update.message.reply_text(
            "❌ В этом чате доступна только команда /status"
        )
        return ConversationHandler.END
    
    # Проверяем, первый ли это запуск
    if user_id not in user_states:
        user_states[user_id] = False
        welcome_text = (
            "👋 Добро пожаловать!\n\n"
            "Я помогу продающим партнёрам оставлять заявки, "
            "а выдающим партнёрам — их забирать.\n\n"
            "Нажмите «📋 Инструкция» для быстрого ознакомления."
        )
        await update.message.reply_text(
            welcome_text,
            reply_markup=get_initial_keyboard()
        )
    else:
        # Если пользователь уже запускал бота, показываем основную клавиатуру
        welcome_text = (
            "👋 С возвращением!\n\n"
            "Нажмите «📝 Оставить заявку» для создания новой заявки."
        )
        await update.message.reply_text(
            welcome_text,
            reply_markup=get_main_keyboard()
        )
    
    return ConversationHandler.END


async def instruction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает инструкцию"""
    user_id = update.effective_user.id
    
    await update.message.reply_text(
        SIMPLE_INSTRUCTION,
        parse_mode='Markdown',
        reply_markup=get_main_keyboard()
    )
    user_states[user_id] = True
    
    return ConversationHandler.END


async def start_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса создания заявки - запрос адреса"""
    await update.message.reply_text(
        "Пожалуйста, введите адрес доставки (город, улицу):",
        reply_markup=get_cancel_keyboard()
    )
    return ADDRESS


async def handle_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка введенного адреса"""
    user_id = update.effective_user.id
    user_address = update.message.text
    
    # Сохраняем адрес во временные данные
    if user_id not in temp_request_data:
        temp_request_data[user_id] = {}
    temp_request_data[user_id]['address'] = user_address
    temp_request_data[user_id]['username'] = update.effective_user.username or f"user_{user_id}"
    
    # Проверяем, есть ли город в списке
    matched_city = find_matching_city(user_address)
    
    if matched_city:
        # Город найден - запрашиваем контакт
        await update.message.reply_text(
            "✅ Город найден!\n\n"
            "Теперь укажите способ связи с клиентом:\n"
            "(телефон, Telegram, любой другой контакт. Впишите конкретный номер или имя пользователя с социальных сетей)"
        )
        return CONTACT
    else:
        # Город не найден
        await update.message.reply_text(
            "❌ Адрес не найден. Отправьте клиенту анкету на доставку через СВК",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END


async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка введенного контакта и создание заявки"""
    user_id = update.effective_user.id
    user_contact = update.message.text
    target_chat_id = int(CHAT_ID)
    
    # Получаем данные из временного хранилища
    user_data = temp_request_data.get(user_id, {})
    user_address = user_data.get('address', '')
    username = user_data.get('username', f"user_{user_id}")
    
    # Создаем заявку
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
        'created_at': current_time,
        'status': 'new',
        'message_id': None
    }
    
    # Отправляем в чат партнеров с кнопкой
    chat_message = (
        f"📦 В вашем регионе есть новая заявка на доставку №{request_number}\n"
        f"📝 Адрес: {user_address}\n"
        f"👤 От партнёра: @{username}"
    )
    
    sent_message = await context.bot.send_message(
        chat_id=target_chat_id,
        text=chat_message,
        reply_markup=get_partner_chat_keyboard(request_number)
    )
    
    user_requests[request_number]['message_id'] = sent_message.message_id
    logger.info(f"   Сообщение в чат отправлено, ID: {sent_message.message_id}")
    
    # Подтверждение пользователю
    await update.message.reply_text(
        f"✅ Заявка №{request_number} отправлена, с вами свяжется партнёр.\n"
        f"Контакт клиента сохранён: {user_contact}\n\n"
        f"Если никто не свяжется в течение 10 минут, отправьте клиенту анкету на доставку через СВК",
        reply_markup=get_main_keyboard()
    )
    
    # Очищаем временные данные
    if user_id in temp_request_data:
        del temp_request_data[user_id]
    
    logger.info(f"✅ Создана заявка №{request_number} с контактом: {user_contact}")
    
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена создания заявки"""
    user_id = update.effective_user.id
    
    # Очищаем временные данные
    if user_id in temp_request_data:
        del temp_request_data[user_id]
    
    await update.message.reply_text(
        "❌ Создание заявки отменено",
        reply_markup=get_main_keyboard()
    )
    
    return ConversationHandler.END


async def handle_partner_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ОБРАБОТЧИК ТОЛЬКО ДЛЯ ЧАТА ПАРТНЕРОВ
    """
    target_chat_id = int(CHAT_ID)
    
    if update.effective_chat.id != target_chat_id:
        return
    
    logger.info("=" * 60)
    logger.info(f"🔵 СООБЩЕНИЕ В ЧАТЕ ПАРТНЕРОВ от @{update.effective_user.username}")
    
    # Проверяем, что это ответ на какое-то сообщение
    if update.message and update.message.reply_to_message:
        replied_message = update.message.reply_to_message
        partner = update.effective_user
        partner_username = partner.username or f"user_{partner.id}"
        partner_full_name = partner.full_name or partner_username
        
        logger.info(f"   Ответ на сообщение ID: {replied_message.message_id}")
        
        # Ищем заявку по ID сообщения
        found_request = None
        found_request_num = None
        
        for req_num, req_data in user_requests.items():
            message_id = req_data.get('message_id')
            if message_id == replied_message.message_id and req_data.get('status') == 'new':
                found_request = req_data
                found_request_num = req_num
                break
        
        if found_request and found_request_num:
            await accept_request(update, context, found_request, found_request_num, partner, partner_username, partner_full_name, target_chat_id)
        else:
            await update.message.reply_text(
                "❌ Эта заявка уже неактивна или была взята другим партнером"
            )
        
        logger.info("=" * 60)
        return
    
    # Если это просто текст в чате (не ответ и не команда)
    if update.message and update.message.text and not update.message.text.startswith('/'):
        await update.message.reply_text(
            "ℹ️ Чтобы забрать заявку:\n"
            "• Нажмите кнопку «✅ Забрать заявку» под сообщением\n"
            "• Или ответьте на сообщение с заявкой\n"
            "• Или используйте команду /take <номер>\n\n"
            "📋 Для просмотра активных заявок используйте /status"
        )
        logger.info("=" * 60)
        return


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на Inline-кнопки"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    target_chat_id = int(CHAT_ID)
    
    logger.info(f"🔘 Нажата кнопка: {data} от @{query.from_user.username}")
    
    if data.startswith("accept_"):
        request_number = int(data.split("_")[1])
        partner = query.from_user
        partner_username = partner.username or f"user_{partner.id}"
        partner_full_name = partner.full_name or partner_username
        
        if request_number in user_requests and user_requests[request_number]['status'] == 'new':
            req_data = user_requests[request_number]
            await accept_request(query, context, req_data, request_number, partner, partner_username, partner_full_name, target_chat_id)
        else:
            await query.edit_message_text(
                text=query.message.text + "\n\n❌ Заявка уже неактивна"
            )


async def accept_request(update_or_query, context, req_data, request_number, partner, partner_username, partner_full_name, target_chat_id):
    """Общая функция для принятия заявки"""
    
    # Партнер забирает заявку
    req_data['taken_by'] = partner_full_name
    req_data['taken_by_username'] = partner_username
    req_data['taken_by_id'] = partner.id
    req_data['status'] = 'taken'
    taken_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    req_data['taken_at'] = taken_at
    
    logger.info(f"✅ Партнер @{partner_username} забирает заявку №{request_number}")
    
    # 1. Если это нажатие на кнопку - просто убираем кнопку из сообщения
    if hasattr(update_or_query, 'edit_message_text'):
        await update_or_query.edit_message_text(
            text=update_or_query.message.text
        )
    
    # 2. Отправляем только одно сообщение в общий чат
    await context.bot.send_message(
        chat_id=target_chat_id,
        text=f"🔥 Выдающий партнёр @{partner_username} забрал заявку №{request_number}"
    )
    
    # 3. Отправляем личное сообщение партнеру с информацией по доставке
    try:
        delivery_info = (
            f"📬 Вы приняли заявку №{request_number}:\n\n"
            f"Инфо по доставке\n"
            f"   • Адрес: {req_data['address']}\n"
            f"   • Контакт клиента: {req_data.get('contact', 'Не указан')}\n\n"
            f"💬 Напишите партнёру @{req_data['username']} в личные сообщения для получения дополнительной информации"
        )
        
        await context.bot.send_message(
            chat_id=partner.id,
            text=delivery_info
        )
        logger.info(f"✅ Личное сообщение с информацией по доставке отправлено партнеру {partner.id}")
        
    except Exception as e:
        logger.error(f"❌ Не удалось отправить личное сообщение партнеру {partner.id}: {e}")
    
    # 4. Сохраняем данные в Google Sheets
    save_request_to_sheet(request_number, req_data)
    
    # 5. Отвечаем только если это reply (не кнопка)
    if hasattr(update_or_query, 'message') and not hasattr(update_or_query, 'edit_message_text'):
        await update_or_query.message.reply_text(
            f"✅ Вы взяли заявку №{request_number}. В личные сообщения придёт информация по доставке"
        )


async def accept_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /accept - альтернативный способ принять заявку (только в личке)"""
    target_chat_id = int(CHAT_ID)
    
    # Проверяем, что это личное сообщение, а не чат партнеров
    if update.effective_chat.id == target_chat_id:
        # В чате партнеров команда /accept не работает
        await update.message.reply_text(
            "❌ В этом чате используйте /take <номер> для принятия заявки"
        )
        return
    
    logger.info(f"🔵 Команда /accept от @{update.effective_user.username}")
    
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "❌ Использование: /accept <номер_заявки>\nПример: /accept 42"
        )
        return
    
    request_number = int(context.args[0])
    partner = update.effective_user
    partner_username = partner.username or f"user_{partner.id}"
    partner_full_name = partner.full_name or partner_username
    
    if request_number in user_requests and user_requests[request_number]['status'] == 'new':
        req_data = user_requests[request_number]
        await accept_request(update, context, req_data, request_number, partner, partner_username, partner_full_name, target_chat_id)
    else:
        await update.message.reply_text(
            f"❌ Заявка №{request_number} не найдена или уже взята"
        )


async def take_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /take - принять заявку по номеру прямо из чата (НОВАЯ КОМАНДА)"""
    target_chat_id = int(CHAT_ID)
    
    # Проверяем, что команда из чата партнеров
    if update.effective_chat.id != target_chat_id:
        await update.message.reply_text(
            "❌ Команда /take доступна только в чате партнеров"
        )
        return
    
    # Проверяем наличие номера заявки
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "❌ Использование: /take <номер_заявки>\n"
            "Пример: /take 1\n\n"
            "📋 Список активных заявок можно посмотреть через /status"
        )
        return
    
    request_number = int(context.args[0])
    partner = update.effective_user
    partner_username = partner.username or f"user_{partner.id}"
    partner_full_name = partner.full_name or partner_username
    
    # Ищем заявку
    if request_number in user_requests and user_requests[request_number]['status'] == 'new':
        req_data = user_requests[request_number]
        
        # Принимаем заявку
        await accept_request(update, context, req_data, request_number, partner, 
                           partner_username, partner_full_name, target_chat_id)
        
        logger.info(f"✅ Заявка №{request_number} принята через /take партнером @{partner_username}")
        
    else:
        await update.message.reply_text(
            f"❌ Заявка №{request_number} не найдена или уже взята"
        )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status - показать активные заявки"""
    target_chat_id = int(CHAT_ID)
    
    # Команда доступна везде, но в чате партнеров показывает активные заявки
    active_requests = [f"№{num} - {data['address']} - @{data['username']} - Контакт: {data.get('contact', 'Не указан')}" 
                       for num, data in user_requests.items() 
                       if data['status'] == 'new']
    
    if active_requests:
        await update.message.reply_text(
            "📋 Активные заявки:\n" + "\n".join(active_requests)
        )
    else:
        await update.message.reply_text("📋 Нет активных заявок")


def create_application():
    """Создает и настраивает Application с обработчиками"""
    global application
    
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Преобразуем CHAT_ID в int с минусом
    partner_chat_id = int(CHAT_ID)
    
    # Создаем ConversationHandler для процесса создания заявки
    request_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Text("📝 Оставить заявку"), start_request)],
        states={
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Text("❌ Отменить"), handle_address)],
            CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Text("❌ Отменить"), handle_contact)],
        },
        fallbacks=[MessageHandler(filters.Text("❌ Отменить"), cancel)],
    )
    
    # 1. Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("accept", accept_command))
    application.add_handler(CommandHandler("take", take_command))  # НОВАЯ КОМАНДА
    application.add_handler(CommandHandler("status", status_command))
    
    # 2. Обработчик инструкции
    application.add_handler(MessageHandler(filters.Text("📋 Инструкция"), instruction))
    
    # 3. ConversationHandler для создания заявки
    application.add_handler(request_conv_handler)
    
    # 4. Обработчик нажатий на inline-кнопки
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # 5. Сообщения из чата партнеров
    application.add_handler(MessageHandler(
        filters.Chat(chat_id=partner_chat_id),
        handle_partner_chat
    ))
    
    # 6. Обработчик отмены (на случай если пользователь напишет "Отменить" вне диалога)
    application.add_handler(MessageHandler(
        filters.Text("❌ Отменить") & filters.ChatType.PRIVATE,
        cancel
    ))
    
    return application


# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
def main():
    """Запуск бота"""
    print("🔍 Запуск бота...")
    print(f"🐍 Python версия: {sys.version}")
    print(f"📦 telegram версия: {telegram.__version__}")
    print(f"📢 Чат партнеров ID: {CHAT_ID}")
    
    # Инициализируем Google Sheets
    if not init_google_sheets():
        logger.error("Не удалось загрузить данные из Google Sheets")
        print("❌ Ошибка загрузки городов из Google Sheets")
        print("\n💡 Решение:")
        print("1. Откройте файл credentials.json и скопируйте client_email")
        print("2. Откройте Google таблицу и нажмите 'Настройки доступа'")
        print("3. Добавьте этот email как редактора")
        print("4. Перезапустите бота\n")
        return
    
    try:
        # Создаем и настраиваем приложение
        app = create_application()
        
        logger.info("✅ Бот инициализирован")
        print("🚀 Бот запущен! Нажмите Ctrl+C для остановки")
        print("📊 Маршрутизация:")
        print(f"   • Чат партнеров (ID: {int(CHAT_ID)}) → /status, /take и ответы на заявки")
        print("   • Личные сообщения → все функции")
        print("   • Inline-кнопки → handle_callback")
        print("   • Данные сохраняются в лист 'Отчётность' с контактом клиента")
        
        # Запускаем бота
        app.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()


# ========== ДЛЯ RAILWAY ==========
# Этот код выполняется при импорте модуля для вебхуков
if __name__ != '__main__':
    print("🔄 Загрузка бота для Railway (вебхуки)...")
    # Инициализируем Google Sheets
    init_google_sheets()
    # Создаем и настраиваем application
    application = create_application()
    print(f"✅ Бот загружен для Railway, application создан")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
