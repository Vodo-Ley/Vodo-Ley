import openai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ContextTypes,
)
from time import sleep
import re
import os
import threading
import requests
import time
import asyncio

# Настройка Google Sheets API
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
client = gspread.authorize(creds)

# Устанавливаем API-ключи OpenAI и Telegram токен напрямую в коде
openai.api_key = "sk-QeFVXulFFgfd07PE8jgkKqQkv-lWBUu1T7LSQDGkcxT3BlbkFJXkqfnG00x2jCjd-YwDCJEDx-9YajBpEdMQV4HMxkgA"
telegram_token = "6476507346:AAFs7OxBI6wDrigeYhblqRu948A8lfZsibk"

# Шаги для диалога
LANGUAGE, SERVICE_TYPE, WATER_TYPE, ADDRESS, PHONE, WATER_AMOUNT, ACCESSORIES, ACCESSORIES_CHOICE, FLOOR, FLOOR_NUMBER, ASK_DELIVERY, ASK_CONTINUE_ORDER, GENERAL = range(13)

# ID группы для отправки заказов
GROUP_CHAT_ID = '-4583041111'

# Определение основной функции main
async def main():
    print("Запуск бота...")

    # Инициализация приложения Telegram
    application = ApplicationBuilder().token(telegram_token).connect_timeout(30).build()

    # Добавление ConversationHandler
    print("Добавление ConversationHandler...")
    application.add_handler(order_conversation)
    print("ConversationHandler добавлен.")

    # Добавление командного обработчика для вызова AI
    print("Добавление обработчика для команды /call_ai...")
    application.add_handler(CommandHandler('call_ai', call_ai))
    print("CommandHandler для /call_ai добавлен.")

    # Добавление обработчика для повторного заказа
    print("Добавление обработчика для повторного заказа...")
    application.add_handler(CallbackQueryHandler(repeat_order, pattern='repeat_order'))
    print("CallbackQueryHandler добавлен.")

    # Добавление универсального обработчика для всех текстовых сообщений
    print("Добавление универсального обработчика для всех текстовых сообщений...")
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_gpt_response))
    print("Универсальный обработчик для всех текстовых сообщений добавлен.")

    # Удаление вебхука перед запуском поллинга
    await application.bot.delete_webhook(drop_pending_updates=True)
    print("Webhook удален. Запуск поллинга...")

    # Запуск бота с поллингом
    await application.run_polling(drop_pending_updates=True)
    print("Бот запущен и ожидает сообщений.")

# Финальные уведомления без экранирования
FINAL_NOTIFICATION_UK_RAW = (
    "Замовлення на доставку день-день приймаються до 16:00\n"
    "Ми знаходимося за адресою Шевченка 29А\n"
    "Графік роботи пункта розлива води 08:30-19:00\n"
    "Наш номер телефона - 0672807573 Viber, Telegram\n"
    "Ми завершуємо наш діалог, для відновлення чату клацніть /start\n"
    "Ми раді Вам та хочемо надати бонус від нас, клацніть /call_ai та до Вас підключиться ШІ допоможе у всіх цікавлячих Вас питаннях."
)

FINAL_NOTIFICATION_RU_RAW = (
    "Заказы на доставку день-день принимаются до 16:00\n"
    "Мы находимся по адресу Шевченка 29А\n"
    "График работы пункта разлива воды 08:30-19:00\n"
    "Наш номер телефона - 0672807573 Viber, Telegram\n"
    "Мы завершаем наш диалог, для восстановления чата нажмите /start\n"
    "Мы рады Вам и хотим предоставить бонус от нас, нажмите /call_ai и к Вам подключится ИИ поможет во всех интересующих Вас вопросах."
)

# Функция для отправки финального уведомления с правильным экранированием
def escape_markdown(text):
    escape_chars = r'_[]()~`>#+-=|{}!\\.'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

# Обработка команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['prices'] = get_prices_from_sheet('uk')

    start_keyboard = ReplyKeyboardMarkup([
        ["Старт розмови з Vodo.Ley"], 
        ["Старт разговора с Vodo.Ley"]
    ], one_time_keyboard=True)

    await update.message.reply_text(
        "Вітаємо! Оберіть мову та розпочніть розмову, натиснувши на відповідну кнопку:",
        reply_markup=start_keyboard
    )
    return LANGUAGE

# Обработка выбора кнопки и автоматическое определение языка
async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_choice = update.message.text.strip().lower()
    print(f"[LOG] Вызов set_language с выбором: {user_choice}")

    if user_choice == "старт розмови з vodo.ley":
        context.user_data['language'] = 'uk'
        context.user_data['prices'] = get_prices_from_sheet('uk')
        await update.message.reply_text(
            "Мова встановлена на українську. Давайте розпочнемо!",
        )
    elif user_choice == "старт разговора с vodo.ley":
        context.user_data['language'] = 'ru'
        context.user_data['prices'] = get_prices_from_sheet('ru')
        await update.message.reply_text(
            "Язык установлен на русский. Давайте начнем!",
        )
    else:
        await update.message.reply_text("Будь ласка, оберіть один із варіантів: Старт розмови з Vodo.Ley або Старт разговора с Vodo.Ley.")
        return LANGUAGE

    if context.user_data['language'] == 'uk':
        await update.message.reply_text("Виберіть тип послуги: 1 - Доставка, 2 - Самовивіз.")
    else:
        await update.message.reply_text("Выберите тип услуги: 1 - Доставка, 2 - Самовывоз.")
    
    return SERVICE_TYPE

async def call_ai(update: Update, context):
    print("[LOG] Команда /call_ai вызвана.")
    language = context.user_data.get('language', 'uk')
    print(f"[LOG] Язык для ИИ: {language}")

    if language == 'uk':
        welcome_message = "Привіт! Я штучний інтелект і готовий допомогти вам. Ви можете задати будь-яке питання, і я спробую дати вам відповідь."
    else:
        welcome_message = "Здравствуйте! Я искусственный интеллект и готов помочь вам. Вы можете задать любой вопрос, и я постараюсь вам помочь."

    try:
        print("[LOG] Отправка приветственного сообщения...")
        await update.message.reply_text(welcome_message)
        print("[LOG] Приветственное сообщение отправлено.")
    except Exception as e:
        print(f"[ERROR] Ошибка при отправке приветственного сообщения: {e}")

    context.user_data['state'] = GENERAL
    print("[LOG] Переход в состояние GENERAL.")
    return GENERAL

def set_user_state(context, state):
    context.user_data['state'] = state
    print(f"[LOG] Установлено состояние: {state}")

def get_latest_gpt_model():
    try:
        models = openai.Model.list()['data']
        gpt_models = [model['id'] for model in models if 'gpt' in model['id']]
        latest_model = sorted(gpt_models, reverse=True)[0]
        print(f"[LOG] Используется модель: {latest_model}")
        return latest_model
    except Exception as e:
        print(f"[ERROR] Не удалось получить последнюю версию модели: {e}")
        return "gpt-4"

async def handle_gpt_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("[LOG] Обработчик handle_gpt_response вызван.")
    state = context.user_data.get('state', 'UNKNOWN')
    print(f"[LOG] Текущее состояние: {state}")
    print(f"[LOG] Входящее сообщение: {update.message.text}")

    if state != GENERAL:
        print("[ERROR] Сообщение пришло в неверное состояние.")
        await update.message.reply_text("Произошла ошибка состояния. Пожалуйста, начните с команды /start.")
        return
    
    user_input = update.message.text.strip()
    language = context.user_data.get('language', 'uk')
    print(f"[LOG] Отправка запроса в GPT с текстом: {user_input}")
    system_prompt = (
        "Ви — корисний асистент, який допомагає користувачам українською мовою. Будь ласка, відповідайте коротко і чітко."
        if language == 'uk' 
        else "Вы — полезный ассистент, который помогает пользователям на русском языке. Пожалуйста, отвечайте кратко и по делу."
    )

    model = get_latest_gpt_model()

    try:
        rate_limiter()

        print(f"[LOG] Отправка запроса в OpenAI: model='{model}', system_prompt='{system_prompt}', user_input='{user_input}'")
        
        response = openai.ChatCompletion.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            max_tokens=300,
            n=1
        )
        print("[LOG] Ответ от GPT получен: ", response)

        answer = response['choices'][0]['message']['content'].strip()
        print(f"[LOG] Полный ответ ИИ: {answer}")

        if len(answer.split()) < 50 and not answer.endswith("."):
            answer += " (Ответ был обрезан. Пожалуйста, уточните ваш вопрос, если нужно продолжение.)"
        else:
            answer = answer

        await update.message.reply_text(answer)
        print("[LOG] Ответ пользователю отправлен.")
    except openai.error.OpenAIError as e:
        error_message = f"Произошла ошибка при получении ответа: {e}"
        print(f"[ERROR] Ошибка при запросе к GPT: {error_message}")
        await update.message.reply_text(error_message)
    except Exception as e:
        print(f"[ERROR] Неизвестная ошибка: {e}")
        await update.message.reply_text("Произошла ошибка при обработке вашего вопроса. Пожалуйста, попробуйте еще раз.")

    print("[LOG] Ожидание следующего вопроса в состоянии GENERAL.")
    return GENERAL

async def repeat_order(update: Update, context):
    query = update.callback_query
    await query.answer()
    last_order = context.user_data.get('last_order')

    if not last_order:
        await query.edit_message_text("Последний заказ не найден.")
        return
    
    order_summary = last_order['order_summary']
    
    print("Повтор заказа перед отправкой:", order_summary)

    try:
        await context.bot.send_message(chat_id=query.message.chat_id, text=order_summary, parse_mode='Markdown')
    except telegram.error.BadRequest as e:
        print(f"Ошибка отправки сообщения: {e}")
        try:
            await context.bot.send_message(chat_id=query.message.chat_id, text=order_summary)
        except telegram.error.BadRequest as e:
            print(f"Ошибка при отправке сообщения без экранирования: {e}")
            await query.edit_message_text("Произошла ошибка при отправке сообщения. Пожалуйста, проверьте текст на наличие запрещенных символов.")
        return
    
    try:
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=order_summary, parse_mode='Markdown')
    except telegram.error.BadRequest as e:
        print(f"Ошибка отправки сообщения в группу: {e}")
        try:
            await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=order_summary)
        except telegram.error.BadRequest as e:
            print(f"Ошибка при отправке сообщения в группу без экранирования: {e}")
            await query.edit_message_text("Произошла ошибка при отправке сообщения в группу. Пожалуйста, проверьте текст на наличие запрещенных символов.")
        return
    
    final_notification = last_order['final_notification']
    try:
        await context.bot.send_message(chat_id=query.message.chat_id, text=final_notification)
    except telegram.error.BadRequest as e:
        print(f"Ошибка отправки финального уведомления: {e}")
        await query.edit_message_text("Произошла ошибка при отправке финального уведомления.")

    keyboard = [
        [InlineKeyboardButton("Повторити замовлення" if context.user_data['language'] == 'uk' else "Повторить заказ", callback_data='repeat_order')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await context.bot.send_message(chat_id=query.message.chat_id, text="Если вы хотите повторить заказ, нажмите на кнопку ниже:", reply_markup=reply_markup)
    except telegram.error.BadRequest as e:
        print(f"Ошибка отправки кнопки повторного заказа: {e}")
        await query.edit_message_text("Произошла ошибка при отправке кнопки повторного заказа.")

order_conversation = ConversationHandler(
    entry_points=[CommandHandler('start', start)],
    states={
        LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_language)],
        SERVICE_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_service_type)],
        WATER_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_water_type)],
        ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_address)],
        PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone)],
        WATER_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_water_amount)],
        ACCESSORIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_accessories_offer)],
        ACCESSORIES_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_accessories_choice)],
        FLOOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_floor)],
        FLOOR_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_floor_number)],
        ASK_DELIVERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ask_delivery)],
        ASK_CONTINUE_ORDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_continue_order)],
        GENERAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_gpt_response)],
    },
    fallbacks=[CommandHandler('start', start), CommandHandler('call_ai', call_ai)],
    per_message=False
)

# Основной блок запуска бота
if __name__ == '__main__':
    print("Запуск бота...")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            print("Event loop уже запущен. Используем существующий loop.")
            loop.create_task(main())
        else:
            print("Запускаем новый event loop.")
            loop.run_until_complete(main())
    except RuntimeError:
        print("Создаем новый event loop.")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
