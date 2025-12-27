import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardButton, \
    InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)
import mysql.connector
from mysql.connector import Error

import mysql.connector

# --- НАСТРОЙКИ ---

# Настройка логирования для отладки
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для разных диалогов (регистрация и вызов)
(FIO, PHONE, EMPLOYEE_TYPE, WORKER_TYPE, GENERAL_ROOM_QUESTION, PERSONAL_ROOM_QUESTION, ROOM_NUMBER,
 SELECT_WORKER_FOR_CALL, AWAIT_CUSTOM_ROOM, PROBLEM_DESCRIPTION, SUPPORT_MESSAGE) = range(
    11)  # Добавлено новое состояние для техподдержки

# --- ДАННЫЕ ДЛЯ ПОДКЛЮЧЕНИЯ ---
DB_HOST = "localhost"
DB_PORT = 3306
DB_NAME = "school_bot"
DB_USER = "root"
DB_PASS = "DiMaks0716"
TELEGRAM_BOT_TOKEN = "8471682186:AAHFH1zOm-uf4qXC7RtYnJkVS1LSUE4yfmE"

YOUR_CHAT_ID = 1189006256###########хардкод(((
TEAMMATE_CHAT_ID = 104944184

# Глобальный словарь для хранения активных вызовов
active_calls = {}


# --- РАБОТА С БАЗОЙ ДАННЫХ (MySQL) ---

def get_db_connection():
    """Устанавливает безопасное соединение с базой данных."""
    try:
        connection = mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )
        logger.info("Успешное подключение к MySQL")
        return connection
    except Error as e:
        logger.error(f"Ошибка подключения к MySQL: {e}")
        logger.error(f"Параметры подключения: host={DB_HOST}, port={DB_PORT}, db={DB_NAME}, user={DB_USER}")
        return None


def get_worker_chat_ids_by_type(worker_type_name: str) -> list[int]:
    """Получает telegram_chat_id работников по названию их специальности."""
    connection = get_db_connection()
    chat_ids = []
    if not connection:
        return chat_ids

    try:
        cursor = connection.cursor(buffered=True)
        query = """
            SELECT emp.telegram_chat_id 
            FROM employees emp
            JOIN worker_types wt ON emp.worker_type_id = wt.id
            WHERE wt.name = %s
        """
        cursor.execute(query, (worker_type_name,))
        results = cursor.fetchall()
        chat_ids = [row[0] for row in results]
        logger.info(f"Найдены работники с ID {chat_ids} для специальности '{worker_type_name}'")
    except Error as e:
        logger.error(f"Ошибка MySQL при поиске работников: {e}")
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()
    return chat_ids


def get_user_info(chat_id: int) -> dict | None:
    """Получает информацию о пользователе (роль, кабинет, ФИО) из БД."""
    connection = get_db_connection()
    if not connection: return None
    try:
        cursor = connection.cursor(dictionary=True, buffered=True)
        query = """
            SELECT et.name as role, emp.assigned_room, emp.full_name, emp.telegram_username
            FROM employees emp
            JOIN employee_types et ON emp.employee_type_id = et.id
            WHERE emp.telegram_chat_id = %s
        """
        cursor.execute(query, (chat_id,))
        user_info = cursor.fetchone()
        return user_info
    except Error as e:
        logger.error(f"Ошибка получения информации о пользователе: {e}")
        return None
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()


async def save_employee_data(update: Update, context: ContextTypes.DEFAULT_TYPE, assigned_room: str,
                             is_room_fixed: bool):
    """Сохраняет данные нового пользователя в базу."""
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor(buffered=True)
            user_data = context.user_data
            chat_id = update.effective_chat.id
            username = update.effective_user.username
            query = """
                INSERT INTO employees 
                (employee_type_id, worker_type_id, full_name, phone, assigned_room, is_room_fixed, telegram_chat_id, telegram_username, telegram_tag)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query, (
                user_data['employee_type_id'], user_data.get('worker_type_id'), user_data['full_name'],
                user_data['phone'],
                assigned_room, is_room_fixed, chat_id, username, f"@{username}" if username else None
            ))
            connection.commit()
            logger.info(f"Пользователь {user_data['full_name']} (ID: {chat_id}) успешно зарегистрирован.")
        except Error as e:
            logger.error(f"Ошибка MySQL при сохранении данных: {e}")
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()


# --- БЛОК РЕГИСТРАЦИИ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает диалог: регистрацию для новых или меню для старых."""
    user_info = get_user_info(update.effective_chat.id)
    if user_info:
        await update.message.reply_text("Вы уже зарегистрированы. Показываю главное меню.")
        await show_main_menu(update, context)
        return ConversationHandler.END

    await update.message.reply_text(
        "Добро пожаловать! Для начала работы нужно зарегистрироваться.\n\nПожалуйста, введите ваше ФИО:")
    return FIO


async def fio_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['full_name'] = update.message.text
    keyboard = [[KeyboardButton("Отправить мой номер телефона", request_contact=True)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("Спасибо! Теперь нажмите кнопку, чтобы поделиться номером телефона:",
                                    reply_markup=reply_markup)
    return PHONE


async def phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['phone'] = update.message.contact.phone_number

    types = ["Директор", "Учитель", "Завуч", "Рабочий"]
    keyboard = [[name] for name in types]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("Выберите вашу должность:", reply_markup=reply_markup)
    return EMPLOYEE_TYPE


async def employee_type_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        selected_type = update.message.text
        logger.info(f"Пользователь выбрал должность: {selected_type}")

        connection = get_db_connection()
        if not connection:
            await update.message.reply_text("Ошибка подключения к базе данных.")
            return ConversationHandler.END

        cursor = connection.cursor(buffered=True)
        cursor.execute("SELECT id FROM employee_types WHERE name = %s", (selected_type,))
        result = cursor.fetchone()

        if not result:
            logger.error(f"Тип сотрудника '{selected_type}' не найден в БД")
            await update.message.reply_text("Произошла ошибка, попробуйте снова.")
            cursor.close()
            connection.close()
            return ConversationHandler.END

        employee_type_id = result[0]
        context.user_data['employee_type_id'] = employee_type_id
        logger.info(f"ID типа сотрудника: {employee_type_id}")

        if selected_type == 'Рабочий':
            cursor.execute("SELECT name FROM worker_types")
            worker_types = [row[0] for row in cursor.fetchall()]
            keyboard = [[name] for name in worker_types]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text("Выберите вашу специальность:", reply_markup=reply_markup)
            cursor.close()
            connection.close()
            return WORKER_TYPE
        else:
            keyboard = [["Да", "Нет"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text("Есть ли у вас закрепленный кабинет?", reply_markup=reply_markup)
            cursor.close()
            connection.close()
            return PERSONAL_ROOM_QUESTION

    except Exception as e:
        logger.error(f"Ошибка в employee_type_input: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте снова /start")
        return ConversationHandler.END


async def worker_type_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    selected_worker_type = update.message.text
    connection = get_db_connection()
    cursor = connection.cursor(buffered=True)
    cursor.execute("SELECT id FROM worker_types WHERE name = %s", (selected_worker_type,))
    result = cursor.fetchone()
    if not result:
        await update.message.reply_text("Произошла ошибка, попробуйте снова.")
        return ConversationHandler.END

    context.user_data['worker_type_id'] = result[0]
    await save_employee_data(update, context, assigned_room=None, is_room_fixed=False)
    await update.message.reply_text("Регистрация завершена! Ваши данные сохранены.", reply_markup=ReplyKeyboardRemove())
    await show_main_menu(update, context)
    cursor.close()
    connection.close()
    return ConversationHandler.END


async def personal_room_question_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text.lower() == 'да':
        await update.message.reply_text("Введите номер вашего кабинета:", reply_markup=ReplyKeyboardRemove())
        return ROOM_NUMBER
    else:
        await save_employee_data(update, context, assigned_room=None, is_room_fixed=False)
        await update.message.reply_text("Регистрация завершена! Ваши данные сохранены.",
                                        reply_markup=ReplyKeyboardRemove())
        await show_main_menu(update, context)
        return ConversationHandler.END


async def room_number_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    room_number = update.message.text
    if len(room_number) > 10:
        await update.message.reply_text("Номер кабинета слишком длинный. Пожалуйста, введите корректный номер:")
        return ROOM_NUMBER

    await save_employee_data(update, context, assigned_room=room_number, is_room_fixed=True)
    await update.message.reply_text(f"Отлично! За вами закреплен кабинет №{room_number}.\nРегистрация завершена!",
                                    reply_markup=ReplyKeyboardRemove())
    await show_main_menu(update, context)
    return ConversationHandler.END


# --- ОСНОВНОЕ МЕНЮ И ВЫЗОВ РАБОТНИКОВ ---

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает главное меню в зависимости от роли пользователя."""
    user_info = get_user_info(update.effective_chat.id)
    if not user_info:
        await update.message.reply_text("Вы не зарегистрированы. Нажмите /start")
        return

    role = user_info.get('role')
    keyboard = []

    if role in ["Директор",'Учитель', 'Завуч']:
        keyboard = [
            ["Вызов в мой кабинет"],
            ["Вызов в спец. кабинет"],
            ["Вызов в определенный кабинет"],
            ["🛠 Техническая поддержка"]
        ]
    elif role == 'Рабочий':
    # keyboard = [["Просмотр активных вызовов"]]  # Можно добавить функционал для рабочих

    # Добавляем кнопку техподдержки для всех пользователей
        keyboard = [["🛠 Техническая поддержка"]]

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("Главное меню:", reply_markup=reply_markup)


async def call_to_my_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает вызов в кабинет, закрепленный за учителем."""
    user_info = get_user_info(update.effective_chat.id)
    if user_info and user_info.get('assigned_room'):
        context.user_data['call_room'] = user_info['assigned_room']
        await update.message.reply_text("Опишите проблему:")
        return PROBLEM_DESCRIPTION
    else:
        await update.message.reply_text("За вами не закреплен кабинет. Пожалуйста, введите номер кабинета для вызова:")
        return AWAIT_CUSTOM_ROOM


async def call_to_specific_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Новая функция: вызов в определенный кабинет с вводом номера."""
    await update.message.reply_text("Введите номер кабинета для вызова:")
    return AWAIT_CUSTOM_ROOM


async def call_to_special_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает инлайн-кнопки для выбора спец. кабинета."""
    keyboard = [
        [InlineKeyboardButton("Спортзал", callback_data='call_room_Спортзал'),
         InlineKeyboardButton("Актовый зал", callback_data='call_room_Актовый_зал')],
        [InlineKeyboardButton("Мед. кабинет", callback_data='call_room_Мед._кабинет'),
         InlineKeyboardButton("Каб. завучей", callback_data='call_room_Каб._завучей')],
        [InlineKeyboardButton("Учительская", callback_data='call_room_Учительская'),
         InlineKeyboardButton("Каб. директора", callback_data='call_room_директора')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите, куда нужен специалист:', reply_markup=reply_markup)


async def special_room_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатие на инлайн-кнопку спец. кабинета."""
    query = update.callback_query
    await query.answer()
    room_name = query.data.replace('call_room_', '')
    context.user_data['call_room'] = room_name
    await query.edit_message_text(text=f"Выбран кабинет: {room_name}. Теперь опишите проблему:")
    return PROBLEM_DESCRIPTION


async def custom_room_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ручной ввод номера кабинета."""
    context.user_data['call_room'] = update.message.text
    await update.message.reply_text("Опишите проблему:")
    return PROBLEM_DESCRIPTION


async def problem_description_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод описания проблемы."""
    context.user_data['problem_description'] = update.message.text
    return await start_call_process(update, context)


async def start_call_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Общая функция для начала вызова (спрашивает тип рабочего)."""
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(buffered=True)
        cursor.execute("SELECT name FROM worker_types")
        worker_types = [row[0] for row in cursor.fetchall()]
        keyboard = [[name] for name in worker_types]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        message_sender = update.message or update
        await message_sender.reply_text("Какого специалиста вызвать?", reply_markup=reply_markup)
        cursor.close()
        connection.close()
        return SELECT_WORKER_FOR_CALL


async def select_worker_for_call(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает диалог вызова и отправляет уведомление."""
    worker_type = update.message.text
    room = context.user_data.get('call_room')
    problem_description = context.user_data.get('problem_description', 'Не указано')
    user_info = get_user_info(update.effective_chat.id)
    teacher_name = user_info.get('full_name', 'Неизвестный учитель')
    teacher_username = user_info.get('telegram_username', 'Неизвестный пользователь')

    # Сохраняем информацию о вызове
    call_id = f"{room}_{worker_type}_{update.effective_chat.id}"
    active_calls[call_id] = {
        'room': room,
        'worker_type': worker_type,
        'problem_description': problem_description,
        'teacher_name': teacher_name,
        'teacher_username': teacher_username,
        'teacher_chat_id': update.effective_chat.id,
        'accepted_by': None
    }

    # Проверяем, есть ли работники этого типа
    chat_ids = get_worker_chat_ids_by_type(worker_type)

    if not chat_ids:
        # Если работников нет, сообщаем об этом пользователю
        await update.message.reply_text(
            f"❌ К сожалению, в настоящее время нет свободных работников типа '{worker_type}'. "
            f"Попробуйте вызвать другого специалиста или повторите запрос позже.",
            reply_markup=ReplyKeyboardRemove()
        )
        # Удаляем вызов из активных, так как он не может быть выполнен
        del active_calls[call_id]
        await show_main_menu(update, context)
        return ConversationHandler.END

    # Если работники есть, отправляем уведомления
    await update.message.reply_text(f"✅ Заявка принята! Вызываю {worker_type} в {room}.",
                                    reply_markup=ReplyKeyboardRemove())
    await notify_workers(context, room, worker_type, teacher_name, teacher_username, problem_description, call_id)
    await show_main_menu(update, context)
    return ConversationHandler.END


async def notify_workers(context: ContextTypes.DEFAULT_TYPE, room: str, worker_type: str, teacher_name: str,
                         teacher_username: str, problem_description: str, call_id: str):
    """Находит нужных работников в БД и отправляет им уведомления с кнопкой принятия."""
    chat_ids = get_worker_chat_ids_by_type(worker_type)

    if not chat_ids:
        logger.warning(f"В базе данных не найдено работников типа '{worker_type}' для уведомления.")
        return

    # Экранируем специальные символы Markdown
    def escape_markdown(text: str) -> str:
        if not text:
            return text
        # Экранируем символы, которые могут сломать Markdown
        escape_chars = r'_*[]()~`>#+-=|{}.!'
        return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

    message_text = (
        f"🔔 *Новая заявка\\!*\n\n"
        f"*Требуется:* `{escape_markdown(worker_type)}`\n"
        f"*Куда:* `{escape_markdown(room)}`\n"
        f"*Описание проблемы:* {escape_markdown(problem_description)}\n"
        f"*Вызвал\\(а\\):* {escape_markdown(teacher_name)} @{escape_markdown(teacher_username)}"
    )

    # Инициализируем словарь для хранения ID сообщений в active_calls
    active_calls[call_id]['notification_message_ids'] = {}

    for chat_id in chat_ids:
        try:
            # Создаем клавиатуру с кнопкой "Принять вызов"
            keyboard = [[InlineKeyboardButton("✅ Принять вызов", callback_data=f"accept_call_{call_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            message = await context.bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode='MarkdownV2',  # Используем MarkdownV2 для лучшего экранирования
                reply_markup=reply_markup
            )

            # Сохраняем message_id в глобальном словаре active_calls
            active_calls[call_id]['notification_message_ids'][chat_id] = message.message_id

        except Exception as e:
            logger.error(f"Не удалось отправить уведомление на chat_id {chat_id}: {e}")


async def accept_call_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатие кнопки 'Принять вызов'."""
    query = update.callback_query
    await query.answer()

    # Извлекаем ID вызова из callback_data
    call_id = query.data.replace('accept_call_', '')

    # Получаем информацию о вызове
    call_info = active_calls.get(call_id)
    if not call_info:
        await query.edit_message_text("❌ Этот вызов уже был принят или отменен.")
        return

    # Получаем информацию о работнике, который принимает вызов
    worker_info = get_user_info(update.effective_chat.id)
    worker_name = worker_info.get('full_name', 'Неизвестный работник')
    worker_username = worker_info.get('telegram_username', 'Неизвестный пользователь')

    # Экранируем специальные символы
    def escape_markdown(text: str) -> str:
        if not text:
            return text
        escape_chars = r'_*[]()~`>#+-=|{}.!'
        return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

    # Помечаем вызов как принятый
    call_info['accepted_by'] = {
        'name': worker_name,
        'username': worker_username,
        'chat_id': update.effective_chat.id
    }

    # Уведомляем учителя о принятии вызова (без Markdown форматирования)
    teacher_message = (
        f"✅ Ваш вызов принят!\n\n"
        f"Специалист: {worker_name} (@{worker_username})\n"
        f"Кабинет: {call_info['room']}\n"
        f"Проблема: {call_info['problem_description']}\n\n"
        f"Специалист уже в пути!"
    )

    try:
        await context.bot.send_message(
            chat_id=call_info['teacher_chat_id'],
            text=teacher_message,
            parse_mode=None  # Убираем Markdown полностью
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить учителя {call_info['teacher_chat_id']}: {e}")

    # Обновляем сообщение у работника, который принял вызов (без Markdown)
    await query.edit_message_text(
        text=f"✅ Вы приняли вызов!\n\nКабинет: {call_info['room']}\nПроблема: {call_info['problem_description']}",
        parse_mode=None  # Убираем Markdown
    )

    # Уведомляем остальных работников, что вызов уже принят
    await notify_call_accepted(context, call_id, worker_name)


async def notify_call_accepted(context: ContextTypes.DEFAULT_TYPE, call_id: str, accepted_worker_name: str):
    """Уведомляет остальных работников, что вызов уже принят путём редактирования сообщений."""
    call_info = active_calls.get(call_id)
    if not call_info:
        return

    # Получаем сохранённые данные о сообщениях из active_calls
    notification_message_ids = call_info.get('notification_message_ids', {})

    if not notification_message_ids:
        logger.warning(f"Не найдены данные о сообщениях для вызова {call_id}")
        return

    # Исключаем работника, который принял вызов
    if call_info['accepted_by']:
        accepted_chat_id = call_info['accepted_by']['chat_id']
        if accepted_chat_id in notification_message_ids:
            del notification_message_ids[accepted_chat_id]

    message_text = f"ℹ️ Вызов в {call_info['room']} уже принят работником {accepted_worker_name}."

    for chat_id, message_id in notification_message_ids.items():
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=message_text,
                parse_mode=None  # Убираем Markdown
            )
        except Exception as e:
            logger.error(f"Не удалось отредактировать сообщение у работника {chat_id}: {e}")

# --- ТЕХНИЧЕСКАЯ ПОДДЕРЖКА ---

async def start_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает диалог с технической поддержкой."""
    await update.message.reply_text(
        "🛠 Вы обратились в техническую поддержку. Опишите вашу проблему или вопрос, и мы постараемся помочь как можно скорее:",
        reply_markup=ReplyKeyboardRemove()
    )
    return SUPPORT_MESSAGE


async def support_message_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает сообщение для технической поддержки и пересылает его разработчикам."""
    user_message = update.message.text
    user_info = get_user_info(update.effective_chat.id)
    user_name = user_info.get('full_name', 'Неизвестный пользователь') if user_info else update.effective_user.full_name
    username = user_info.get('telegram_username',
                             'Неизвестный пользователь') if user_info else update.effective_user.username

    # Экранируем специальные символы Markdown
    def escape_markdown(text: str) -> str:
        if not text:
            return text
        # Экранируем символы, которые могут сломать Markdown
        escape_chars = r'_*[]()~`>#+-=|{}.!'
        return ''.join(f'\\{char}' if char in escape_chars else char for char in text)
    # Формируем сообщение для разработчиков
    support_message = (
        f"🛠 **НОВОЕ СООБЩЕНИЕ ТЕХПОДДЕРЖКИ**\n\n"
        f"**От:** {escape_markdown(user_name)} (@{escape_markdown(username)})\n"
        f"**ID пользователя:** {escape_markdown(str(update.effective_chat.id))}\n"
        f"**Сообщение:** {escape_markdown(user_message)}"
    )

    # Отправляем сообщение разработчикам
    developer_ids = [YOUR_CHAT_ID, TEAMMATE_CHAT_ID]
    for dev_id in developer_ids:
        try:
            await context.bot.send_message(
                chat_id=dev_id,
                text=support_message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение техподдержки разработчику {dev_id}: {e}")

    # Подтверждаем пользователю, что сообщение отправлено
    await update.message.reply_text(
        "✅ Ваше сообщение отправлено в техническую поддержку. Мы свяжемся с вами в ближайшее время.",
        reply_markup=ReplyKeyboardRemove()
    )

    # Возвращаем в главное меню
    await show_main_menu(update, context)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет любой диалог и возвращает в главное меню."""
    await update.message.reply_text("Действие отменено.", reply_markup=ReplyKeyboardRemove())
    await show_main_menu(update, context)
    return ConversationHandler.END


def main():
    """Основная функция для запуска бота."""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # --- ОБРАБОТЧИКИ ДИАЛОГОВ ---

    # Диалог для регистрации
    registration_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            FIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, fio_input)],
            PHONE: [MessageHandler(filters.CONTACT, phone_input)],
            EMPLOYEE_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, employee_type_input)],
            WORKER_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_type_input)],
            PERSONAL_ROOM_QUESTION: [MessageHandler(filters.Regex('^(Да|Нет)$'), personal_room_question_input)],
            ROOM_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, room_number_input)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    # Диалог для создания заявки на вызов
    call_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^Вызов в мой кабинет$"), call_to_my_room),
            MessageHandler(filters.Regex("^Вызов в определенный кабинет$"), call_to_specific_room),
            CallbackQueryHandler(special_room_callback, pattern='^call_room_')
        ],
        states={
            AWAIT_CUSTOM_ROOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, custom_room_input)],
            PROBLEM_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, problem_description_input)],
            SELECT_WORKER_FOR_CALL: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_worker_for_call)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    # Диалог для технической поддержки
    support_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🛠 Техническая поддержка$"), start_support)],
        states={
            SUPPORT_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, support_message_input)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(registration_handler)
    application.add_handler(call_handler)
    application.add_handler(support_handler)  # Добавляем обработчик техподдержки

    # Обработчик для кнопки "Принять вызов"
    application.add_handler(CallbackQueryHandler(accept_call_callback, pattern='^accept_call_'))

    # Отдельные обработчики для кнопок меню, которые не начинают диалог
    application.add_handler(CommandHandler("menu", show_main_menu))
    application.add_handler(MessageHandler(filters.Regex("^Вызов в спец. кабинет$"), call_to_special_room))
    application.add_handler(
        MessageHandler(filters.Regex("^Просмотр активных вызовов$"), show_main_menu))  # Заглушка для рабочих

    # Запускаем бота
    logger.info("Бот запускается...")
    application.run_polling()


if __name__ == '__main__':
    main()