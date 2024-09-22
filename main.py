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
    ContextTypes,
)
import uvicorn
from fastapi import FastAPI, Request
import asyncio
import aiohttp

# Настройка Google Sheets API
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
client = gspread.authorize(creds)

# Устанавливаем API-ключи OpenAI и Telegram токен напрямую в коде
openai.api_key = os.environ['sk-QeFVXulFFgfd07PE8jgkKqQkv-lWBUu1T7LSQDGkcxT3BlbkFJXkqfnG00x2jCjd-YwDCJEDx-9YajBpEdMQV4HMxkgA']
telegram_token = os.environ['6476507346:AAFs7OxBI6wDrigeYhblqRu948A8lfZsibk']

# Шаги для диалога
LANGUAGE, SERVICE_TYPE, WATER_TYPE, ADDRESS, PHONE, WATER_AMOUNT, ACCESSORIES, ACCESSORIES_CHOICE, FLOOR, FLOOR_NUMBER, ASK_DELIVERY, ASK_CONTINUE_ORDER, GENERAL = range(13)

# ID группы для отправки заказов
GROUP_CHAT_ID = '-4583041111'

# Настройка кастомной сессии
session = aiohttp.ClientSession(
    connector=aiohttp.TCPConnector(limit=10),
    timeout=aiohttp.ClientTimeout(total=30)
)

# Создание кастомного клиента
from telegram.request import AiohttpSession

custom_request = AiohttpSession(session)

# Инициализация бота с кастомной сессией
application = ApplicationBuilder().token(telegram_token).request(custom_request).build()

# Регистрация хендлеров
application.add_handler(CommandHandler('start', start))
application.add_handler(CommandHandler('call_ai', call_ai))
application.add_handler(order_conversation)

# Инициализация FastAPI приложения
app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello, world!"}

@app.post("/")
async def webhook(request: Request):
    try:
        json_data = await request.json()
        update = Update.de_json(json_data, application.bot)  # Создаем объект update из JSON данных
        await application.update_queue.put(update)  # Подаем update в очередь обработчика
    except Exception as e:
        print(f"Ошибка обработки вебхука: {e}")
    return {"status": "ok"}

# Функция для установки языка
async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_choice = update.message.text.strip().lower()
    print(f"[LOG] Вызов set_language с выбором: {user_choice}")  # Логируем вызов

    if user_choice == "старт розмови з vodo.ley":
        context.user_data['language'] = 'uk'
        context.user_data['prices'] = get_prices_from_sheet('uk')
        await update.message.reply_text("Мова встановлена на українську. Давайте розпочнемо!")
    elif user_choice == "старт разговора с vodo.ley":
        context.user_data['language'] = 'ru'
        context.user_data['prices'] = get_prices_from_sheet('ru')
        await update.message.reply_text("Язык установлен на русский. Давайте начнем!")
    else:
        await update.message.reply_text("Будь ласка, оберіть один із варіантів: Старт розмови з Vodo.Ley або Старт разговора с Vodo.Ley.")
        return LANGUAGE

    # Переход к выбору типа услуги
    if context.user_data['language'] == 'uk':
        await update.message.reply_text("Виберіть тип послуги: 1 - Доставка, 2 - Самовивіз.")
    else:
        await update.message.reply_text("Выберите тип услуги: 1 - Доставка, 2 - Самовывоз.")

    return SERVICE_TYPE

# Основная функция для запуска сервера и бота
async def main():
    # Создаем кастомную сессию aiohttp
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=10)) as session:
        # Инициализация Telegram бота с кастомной сессией
        application = (
            ApplicationBuilder()
            .token(telegram_token)
            .http_session(session)  # Используем http_session вместо session
            .build()
        )

        # Устанавливаем вебхук
        webhook_url = "vodo-ley-production.up.railway.app"
        try:
            webhook_info = await application.bot.get_webhook_info()
            if webhook_info.url != webhook_url:
                await application.bot.set_webhook(url=webhook_url)
                print("Вебхук успешно установлен.")
            else:
                print("Вебхук уже установлен.")
        except Exception as e:
            print(f"Ошибка при установке вебхука: {e}")

        # Добавляем хендлеры в бота
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('call_ai', call_ai))
        application.add_handler(order_conversation)

        # Запускаем бота и сервер FastAPI параллельно
        await application.start()  # Запускаем Telegram бота

# Обработчики команд и диалогов (пример функции start)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Добро пожаловать! Нажмите /call_ai, чтобы начать разговор с ИИ."
    )

async def call_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Вы подключены к искусственному интеллекту. Задайте ваш вопрос."
    )

# Функция для ограничения частоты запросов
def rate_limiter():
    print("[LOG] Ожидание 1 секунду перед отправкой следующего запроса...")
    time.sleep(1)  # Убедитесь, что задержка не блокирует основной поток

# Функция для получения последней доступной версии модели GPT
def get_latest_gpt_model():
    try:
        # Получаем список всех доступных моделей
        models = openai.Model.list()['data']
        
        # Ищем последние версии моделей, содержащие 'gpt'
        gpt_models = [model['id'] for model in models if 'gpt' in model['id']]
        
        # Сортируем модели по убыванию версии и возвращаем последнюю
        latest_model = sorted(gpt_models, reverse=True)[0]
        print(f"[LOG] Используется модель: {latest_model}")
        return latest_model
    except Exception as e:
        print(f"[ERROR] Не удалось получить последнюю версию модели: {e}")
        # Возвращаем дефолтную модель, если не удалось определить последнюю версию
        return "gpt-4"

# Обработчик ответа GPT
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

    # Получаем последнюю версию модели
    model = get_latest_gpt_model()

    try:
        rate_limiter()  # Ожидание перед отправкой запроса

        # Логирование отправляемого запроса
        print(f"[LOG] Отправка запроса в OpenAI: model='{model}', system_prompt='{system_prompt}', user_input='{user_input}'")
        
        response = openai.ChatCompletion.create(
            model=model,  # Используем последнюю версию модели
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            max_tokens=300,  # Увеличиваем количество токенов для более полного ответа
            n=1
        )
        print("[LOG] Ответ от GPT получен: ", response)  # Логирование полного ответа

        # Извлекаем ответ и проверяем, является ли он обрезанным
        answer = response['choices'][0]['message']['content'].strip()
        print(f"[LOG] Полный ответ ИИ: {answer}")

        # Проверяем, обрезан ли ответ
        if len(answer.split()) < 50 and not answer.endswith("."):
            answer += " (Ответ был обрезан. Пожалуйста, уточните ваш вопрос, если нужно продолжение.)"
        else:
            answer = answer  # Оставляем как есть, если ответ выглядит полным

        await update.message.reply_text(answer)
        print("[LOG] Ответ пользователю отправлен.")
    except openai.error.OpenAIError as e:
        error_message = f"Произошла ошибка при получении ответа: {e}"
        print(f"[ERROR] Ошибка при запросе к GPT: {error_message}")
        await update.message.reply_text(error_message)
    except Exception as e:
        print(f"[ERROR] Неизвестная ошибка: {e}")
        await update.message.reply_text("Произошла ошибка при обработке вашего вопроса. Пожалуйста, попробуйте еще раз.")

    # Остаемся в состоянии GENERAL для дальнейшего общения
    print("[LOG] Ожидание следующего вопроса в состоянии GENERAL.")
    return GENERAL

async def handle_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Основной код для обработки команд или сообщений
        # Здесь вы можете добавить логику обработки сообщений, команд или любых других данных из update
        if update.message:  # Если это сообщение
            if update.message.text:
                print(f"[LOG] Получено сообщение: {update.message.text}")
                # Обработка команд или сообщений
                # Например, если команда /start, вызываем соответствующую функцию
                if update.message.text == '/start':
                    await start(update, context)
                elif update.message.text == '/call_ai':
                    await call_ai(update, context)
                else:
                    # Если это не команда, обрабатываем как текстовое сообщение
                    await handle_gpt_response(update, context)
            else:
                print("[LOG] Получено сообщение без текста.")
        
        elif update.callback_query:  # Если это callback-запрос (нажатие на кнопки InlineKeyboard)
            print(f"[LOG] Получен callback-запрос с данными: {update.callback_query.data}")
            await handle_callback_query(update.callback_query, context)
        
        else:
            print("[LOG] Неизвестный тип update.")

    except Exception as e:
        print(f"[ERROR] Ошибка в асинхронной функции: {e}")

# Пример обработчика callback-запросов (если используется InlineKeyboard)
async def handle_callback_query(callback_query, context):
    try:
        # Обработка данных из callback-запроса
        if callback_query.data == 'repeat_order':
            await repeat_order(callback_query, context)
        else:
            await callback_query.answer("Неизвестный запрос.")
    except Exception as e:
        print(f"[ERROR] Ошибка при обработке callback-запроса: {e}")

async def log_state_on_each_message(update: Update, context):
    state = context.user_data.get('state')
    print(f"[LOG] Сообщение пользователя: {update.message.text}")
    print(f"[LOG] Текущее состояние перед обработкой: {state}")
    return await handle_gpt_response(update, context)

# Сообщения на разных языках
MESSAGES = {
    'uk': {
        'choose_language': "Виберіть мову: 1 - Українська, 2 - Русский.",
        'service_type': "Виберіть тип послуги: 1 - Доставка, 2 - Самовивіз.",
        'water_type': "Оберіть тип води: 1 - Очищена, 2 - Мінеральна.",
        'address': "Будь ласка, вкажіть адресу доставки.",
        'phone': "Будь ласка, вкажіть ваш номер телефону.",
        'water_amount': "Скільки літрів води ви хочете замовити?",
        'accessories': "Хочете додати аксесуари? 1 - Так, 2 - Ні.",
        'floor': "Оберіть варіант доставки: 1 - Поверх, 2 - Приватний будинок.\n(Якщо обрано поверх, введіть номер поверху)"
    },
    'ru': {
        'choose_language': "Выберите язык: 1 - Украинский, 2 - Русский.",
        'service_type': "Выберите тип услуги: 1 - Доставка, 2 - Самовывоз.",
        'water_type': "Выберите тип воды: 1 - Очищенная, 2 - Минеральная.",
        'address': "Пожалуйста, укажите адрес доставки.",
        'phone': "Пожалуйста, укажите ваш номер телефона.",
        'water_amount': "Сколько литров воды вы хотите заказать?",
        'accessories': "Хотите добавить аксессуары? 1 - Да, 2 - Нет.",
        'floor': "Выберите вариант доставки: 1 - Этаж, 2 - Частный дом.\n(Если выбран этаж, введите номер этажа)"
    }
}

# Получение сообщения на языке пользователя
def get_message(user_data, message_key):
    language = user_data.get('language', 'uk')
    return MESSAGES[language].get(message_key, "")

# Функция для нормализации типа воды
def normalize_water_type(water_type, language):
    if language == 'uk':
        if water_type in ['1', 'очищена', 'очищенна', 'очищена вода']:
            return 'очищена'
        elif water_type in ['2', 'мінеральна', 'мінеральна вода']:
            return 'мінеральна'
    else:
        if water_type in ['1', 'очищенная', 'очищенная вода']:
            return 'очищенная'
        elif water_type in ['2', 'минеральная', 'минеральная вода']:
            return 'минеральная'
    return None

# Функция для отображения ассортимента продукции
def format_product_list(prices, language):
    product_list = []
    if language == 'uk':
        product_list.append("Асортимент продукції:")
    else:
        product_list.append("Ассортимент продукции:")
    
    for water_type, details in prices['water'].items():
        if language == 'uk':
            product_list.append(f"{water_type.capitalize()} - Доставка: {details['delivery']} грн/л, Самовивіз: {details['pickup']} грн/л")
        else:
            product_list.append(f"{water_type.capitalize()} - Доставка: {details['delivery']} грн/л, Самовывоз: {details['pickup']} грн/л")
    
    if prices['accessories']:
        if language == 'uk':
            product_list.append("\nДоступні аксесуари:")
        else:
            product_list.append("\nДоступные аксессуары:")
        
        for accessory in prices['accessories']:
            if language == 'uk':
                product_list.append(f"{accessory['name']} - Доставка: {accessory['delivery']} грн, Самовивіз: {accessory['pickup']} грн")
            else:
                product_list.append(f"{accessory['name']} - Доставка: {accessory['delivery']} грн, Самовывоз: {accessory['pickup']} грн")

    return "\n".join(product_list)

# Функция для обработки выбора типа услуги
async def handle_service_type(update: Update, context):
    service_type = update.message.text.strip()
    language = context.user_data.get('language', 'uk')

    prices_water = context.user_data['prices']['water']

    if service_type == '1':  # Доставка
        context.user_data['service_type'] = 'delivery'
        water_type = context.user_data.get('water_type', None)
        if water_type:
            previous_service_type = context.user_data.get('previous_service_type', 'pickup')
            if previous_service_type == 'pickup':
                context.user_data['water_cost_per_liter'] = prices_water[water_type]['delivery']
                await update.message.reply_text("Ціна на воду оновлена на доставку.")
            context.user_data['previous_service_type'] = 'delivery'

        try:
            water_cleaned = find_in_dict_with_case(prices_water, 'очищена' if language == 'uk' else 'очищенная')
            water_mineral = find_in_dict_with_case(prices_water, 'мінеральна' if language == 'uk' else 'минеральная')

            if language == 'uk':
                await update.message.reply_text(
                    f"Ціни на доставку:\n"
                    f"Очищена вода - {water_cleaned['delivery']} грн за літр.\n"
                    f"Мінеральна вода - {water_mineral['delivery']} грн за літр.\n"
                )
            else:
                await update.message.reply_text(
                    f"Цены на доставку:\n"
                    f"Очищенная вода - {water_cleaned['delivery']} грн за литр.\n"
                    f"Минеральная вода - {water_mineral['delivery']} грн за литр.\n"
                )

            accessories_message = format_product_list(context.user_data['prices'], language)
            await update.message.reply_text(accessories_message)

            if language == 'uk':
                await update.message.reply_text("Продовжуємо замовлення? 1 - Так, 2 - Ні.")
            else:
                await update.message.reply_text("Продолжаем заказ? 1 - Да, 2 - Нет.")
            
            return ASK_CONTINUE_ORDER

        except KeyError as e:
            await update.message.reply_text(str(e))
        return ASK_CONTINUE_ORDER

    elif service_type == '2':  # Самовывоз
        context.user_data['service_type'] = 'pickup'
        water_type = context.user_data.get('water_type', None)
        if water_type:
            previous_service_type = context.user_data.get('previous_service_type', 'delivery')
            if previous_service_type == 'delivery':
                context.user_data['water_cost_per_liter'] = prices_water[water_type]['pickup']
                await update.message.reply_text("Ціна на воду оновлена на самовивіз.")
            context.user_data['previous_service_type'] = 'pickup'

        try:
            water_cleaned = find_in_dict_with_case(prices_water, 'очищена' if language == 'uk' else 'очищенная')
            water_mineral = find_in_dict_with_case(prices_water, 'мінеральна' if language == 'uk' else 'минеральная')

            if language == 'uk':
                await update.message.reply_text(
                    f"Ціни на самовивіз:\n"
                    f"Очищена вода - {water_cleaned['pickup']} грн за літр.\n"
                    f"Мінеральна вода - {water_mineral['pickup']} грн за літр.\n"
                    f"\n"
                    f"Ціна на доставку:\n"
                    f"Очищена вода - {water_cleaned['delivery']} грн за літр.\n"
                    f"Мінеральна вода - {water_mineral['delivery']} грн за літр.\n"
                )
            else:
                await update.message.reply_text(
                    f"Цены на самовывоз:\n"
                    f"Очищенная вода - {water_cleaned['pickup']} грн за литр\n"
                    f"Минеральная вода - {water_mineral['pickup']} грн за литр.\n"
                    f"\n"
                    f"Цены на доставку:\n"
                    f"Очищенная вода - {water_cleaned['delivery']} грн за литр\n"
                    f"Минеральная вода - {water_mineral['delivery']} грн за литр.\n"
                )

            accessories_message = format_product_list(context.user_data['prices'], language)
            await update.message.reply_text(accessories_message)

            if language == 'uk':
                await update.message.reply_text("Продовжуємо замовлення? 1 - Так, 2 - Ні.")
            else:
                await update.message.reply_text("Продолжаем заказ? 1 - Да, 2 - Нет.")

            return ASK_CONTINUE_ORDER

        except KeyError as e:
            await update.message.reply_text(str(e))
        return ASK_CONTINUE_ORDER

    else:
        await update.message.reply_text(get_message(context.user_data, 'service_type'))
        return SERVICE_TYPE

    # Функция для обработки продолжения заказа
async def handle_continue_order(update: Update, context):
    user_input = update.message.text.strip()
    language = context.user_data.get('language', 'uk')

    if user_input == '1':  # Продолжаем заказ
        # Переход к выбору типа воды
        if language == 'uk':
            await update.message.reply_text("Оберіть тип води: 1 - Очищена, 2 - Мінеральна.")
        else:
            await update.message.reply_text("Выберите тип воды: 1 - Очищенная, 2 - Минеральная.")
        
        return WATER_TYPE  # Переход к выбору воды

    elif user_input == '2':  # Завершаем заказ
        if language == 'uk':
            await update.message.reply_text("Дякуємо за звернення! Для нового замовлення натисніть /start.")
        else:
            await update.message.reply_text("Спасибо за обращение! Для нового заказа нажмите /start.")

        return ConversationHandler.END

    else:
        if language == 'uk':
            await update.message.reply_text("Неправильний вибір. Виберіть 1 - Так або 2 - Ні.")
        else:
            await update.message.reply_text("Неправильный выбор. Выберите 1 - Да или 2 - Нет.")

        return ASK_CONTINUE_ORDER  # Повторяем вопрос о продолжении заказа

# Функция для обработки вопроса о доставке после самовывоза
async def handle_ask_delivery(update: Update, context):
    user_input = update.message.text.strip()
    language = context.user_data.get('language', 'uk')

    if user_input == '1':  # Пользователь выбрал доставку
        context.user_data['service_type'] = 'delivery'
        if language == 'uk':
            await update.message.reply_text("Ви обрали доставку. Продовжуємо замовлення.")
        else:
            await update.message.reply_text("Вы выбрали доставку. Продолжаем заказ.")

        # Переходим к выбору воды
        if language == 'uk':
            await update.message.reply_text("Оберіть тип води: 1 - Очищена, 2 - Мінеральна.")
        else:
            await update.message.reply_text("Выберите тип воды: 1 - Очищенная, 2 - Минеральная.")

        return WATER_TYPE  # Переход к выбору воды

    elif user_input == '2':  # Пользователь отказался от доставки
        if language == 'uk':
            await update.message.reply_text("Дякуємо за звернення! Для початку нового замовлення натисніть /start.")
        else:
            await update.message.reply_text("Спасибо за обращение! Для начала нового заказа нажмите /start.")

        return ConversationHandler.END  # Завершаем разговор

    else:
        if language == 'uk':
            await update.message.reply_text("Неправильний вибір. Виберіть 1 (Так) або 2 (Ні).")
        else:
            await update.message.reply_text("Неправильный выбор. Выберите 1 (Да) или 2 (Нет).")
        return ASK_DELIVERY  # Повторяем вопрос о доставке
  
# Функция для обработки выбора воды и пересчета по тарифу
async def handle_water_type(update: Update, context):
    user_input = update.message.text.strip()
    language = context.user_data.get('language', 'uk')

    prices_water = context.user_data['prices']['water']
    service_type = 'delivery'  # Всегда пересчитываем по тарифу доставки

    if user_input == '1':
        context.user_data['water_type'] = 'очищена' if language == 'uk' else 'очищенная'
    elif user_input == '2':
        context.user_data['water_type'] = 'мінеральна' if language == 'uk' else 'минеральная'
    else:
        if language == 'uk':
            await update.message.reply_text("Неправильний вибір. Виберіть 1 (Очищена) або 2 (Мінеральна).")
        else:
            await update.message.reply_text("Неправильный выбор. Выберите 1 (Очищенная) или 2 (Минеральная).")
        return WATER_TYPE

    # После выбора воды рассчитываем цену по тарифу доставки
    water_type = context.user_data['water_type']
    water_cost_per_liter = prices_water[water_type]['delivery']  # Всегда тариф для доставки
    context.user_data['water_cost_per_liter'] = water_cost_per_liter

    if language == 'uk':
        await update.message.reply_text(f"Вартість {water_type} води за тарифом доставки: {water_cost_per_liter} грн за літр.")
        await update.message.reply_text("Введіть кількість літрів води, яку ви хочете замовити.")
    else:
        await update.message.reply_text(f"Стоимость {water_type} воды по тарифу доставки: {water_cost_per_liter} грн за литр.")
        await update.message.reply_text("Введите количество литров воды, которое вы хотите заказать.")
    
    return WATER_AMOUNT  # Переход к выбору количества воды

# Функция для вычисления стоимости заказа
def calculate_costs(user_data):
    #Вычисляет стоимость воды, аксессуаров и общую стоимость."""
    water_cost_per_liter = user_data['water_cost_per_liter']
    water_total_cost = float(user_data['water_amount']) * water_cost_per_liter
    accessories_cost = sum(item['cost'] for item in user_data.get('selected_accessories', []))
    
    # Определяем стоимость подъема на этаж
    floor = user_data.get('floor', '1')
    
    # Проверяем, если floor - строка "Приватний будинок" или "Частный дом"
    if floor.lower() in ['приватний будинок', 'частный дом']:
        floor_cost = 0  # Для частного дома подъем на этаж не требуется
    else:
        try:
            floor_cost = calculate_floor_cost(int(floor))  # Используем нашу функцию для расчета стоимости
        except ValueError:
            floor_cost = 0  # На случай неверного ввода значения
            
    total_cost = water_total_cost + accessories_cost + floor_cost
    return water_total_cost, accessories_cost, floor_cost, total_cost

# Обновленная функция для отображения ассортимента аксессуаров
def format_accessories_list(user_data, language):
    accessories = user_data.get('selected_accessories', [])
    if not accessories:
        return "Без аксесуарів" if language == 'uk' else "Без аксессуаров"
    
    # Проверяем, что каждый элемент в списке является словарем
    if isinstance(accessories, list) and all(isinstance(item, dict) for item in accessories):
        return ', '.join(f"{item['name']} x{item['quantity']}" for item in accessories)
    else:
        return "Некорректные данные аксесуаров" if language == 'uk' else "Некорректные данные аксессуаров"

# Исправленная функция для отображения полного списка ассортимента аксессуаров
def format_accessories_list_detailed(accessories, language):
    message = "Доступні аксесуари:\n" if language == 'uk' else "Доступные аксессуары:\n"
    if isinstance(accessories, list) and all(isinstance(item, dict) for item in accessories):
        for i, accessory in enumerate(accessories, start=1):
            message += f"{i}. {accessory['name']} - {accessory['delivery']} грн\n"
        message += "0. Не хочу аксесуари" if language == 'uk' else "0. Не хочу аксессуары"
    else:
        message += "Некорректные данные аксесуаров" if language == 'uk' else "Некорректные данные аксессуаров"
    return message

async def handle_address(update: Update, context):
    user_input = update.message.text.strip()
    language = context.user_data.get('language', 'uk')

    # Сохраняем адрес в данные пользователя
    context.user_data['address'] = user_input

    # Переход к следующему шагу — запрос номера телефона
    if language == 'uk':
        await update.message.reply_text("Будь ласка, введіть ваш номер телефону.")
    else:
        await update.message.reply_text("Пожалуйста, введите ваш номер телефона.")

    return PHONE  # Переход к следующему этапу — вводу номера телефона

async def handle_phone(update: Update, context):
    phone = update.message.text.strip()
    
    # Проверяем, что номер телефона состоит только из цифр
    if not phone.isdigit():
        language = context.user_data.get('language', 'uk')
        if language == 'uk':
            await update.message.reply_text("Будь ласка, введіть дійсний номер телефону, який містить тільки цифри.")
        else:
            await update.message.reply_text("Пожалуйста, введите действительный номер телефона, состоящий только из цифр.")
        return PHONE  # Возвращаемся к этапу ввода телефона

    # Сохраняем номер телефона в данные пользователя
    context.user_data['phone'] = phone

    # Переходим к следующему шагу — выбор этажности
    language = context.user_data.get('language', 'uk')
    if language == 'uk':
        await update.message.reply_text("Вкажіть варіант доставки: 1 - Поверх, 2 - Приватний будинок.")
    else:
        await update.message.reply_text("Укажите вариант доставки: 1 - Этаж, 2 - Частный дом.")

    return FLOOR  # Переход к следующему этапу — выбор этажности

async def handle_water_amount(update: Update, context):
    user_input = update.message.text.strip()
    language = context.user_data.get('language', 'uk')

    # Проверяем, что введено число
    if not user_input.isdigit():
        if language == 'uk':
            await update.message.reply_text("Будь ласка, введіть кількість літрів води (тільки цифри).")
        else:
            await update.message.reply_text("Пожалуйста, введите количество литров воды (только цифры).")
        return WATER_AMOUNT  # Возвращаемся на этап ввода количества воды

    context.user_data['water_amount'] = int(user_input)

    # Переходим к следующему шагу — ввод адреса
    if language == 'uk':
        await update.message.reply_text("Будь ласка, введіть адресу доставки.")
    else:
        await update.message.reply_text("Пожалуйста, введите адрес доставки.")

    return ADDRESS  # Переход к следующему этапу — вводу адреса

# Функция для расчета стоимости за подъем на этаж
def calculate_floor_cost(floor):
    try:
        floor_number = int(floor)
        if floor_number == 1:
            return 0  # Первый этаж бесплатно
        elif floor_number == 2:
            return 20  # Второй этаж 20 грн
        elif floor_number == 3:
            return 30  # Третий этаж 30 грн
        elif floor_number == 4:
            return 40  # Четвертый этаж 40 грн
        elif floor_number == 5:
            return 50  # Пятый этаж 50 грн
        else:
            # Если этаж выше 5, можно сделать фиксированную стоимость или по формуле
            return 50 + (floor_number - 5) * 10  # Для каждого следующего этажа после пятого
    except ValueError:
        return 0  # Для частного дома или некорректного ввода стоимость подъема 0 грн

# Функция для обработки выбора этажности
async def handle_floor(update: Update, context):
    user_input = update.message.text.strip()
    language = context.user_data.get('language', 'uk')

    # Сохранение этажности
    if user_input == '1':  # Если выбран этаж
        if language == 'uk':
            await update.message.reply_text("Введіть номер поверху (наприклад, 1 для першого поверху).")
        else:
            await update.message.reply_text("Введите номер этажа (например, 1 для первого этажа).")
        return FLOOR_NUMBER  # Переход к вводу номера этажа

    elif user_input == '2':  # Если выбран частный дом
        context.user_data['floor'] = 'Приватний будинок' if language == 'uk' else 'Частный дом'
        context.user_data['floor_cost'] = 0  # Для частного дома стоимость подъема 0 грн
        
        # Переход к следующему шагу — предложению аксессуаров
        return await handle_accessories_offer(update, context)

    else:
        if language == 'uk':
            await update.message.reply_text("Неправильний вибір. Виберіть 1 або 2.")
        else:
            await update.message.reply_text("Неправильный выбор. Выберите 1 или 2.")
        return FLOOR  # Повторяем запрос

# Функция для обработки номера этажа с учетом расчета стоимости
async def handle_floor_number(update: Update, context):
    floor = update.message.text.strip()
    language = context.user_data.get('language', 'uk')

    # Проверяем, что пользователь ввел корректный номер этажа
    if floor.isdigit():
        context.user_data['floor'] = floor
        floor_cost = calculate_floor_cost(floor)
        context.user_data['floor_cost'] = floor_cost

        if language == 'uk':
            await update.message.reply_text(f"Ви ввели {floor} поверх. Вартість підйому: {floor_cost} грн.")
        else:
            await update.message.reply_text(f"Вы ввели {floor} этаж. Стоимость подъема: {floor_cost} грн.")
        
        # Переход к предложению аксессуаров
        return await handle_accessories_offer(update, context)
    else:
        if language == 'uk':
            await update.message.reply_text("Будь ласка, введіть коректний номер поверху.")
        else:
            await update.message.reply_text("Пожалуйста, введите правильный номер этажа.")
        return FLOOR_NUMBER

def format_order_summary(user_data, water_total_cost, accessories_cost, floor_cost, total_cost):
    language = user_data['language']
    accessories_str = format_accessories_list(user_data, language)

    # Подготавливаем данные для экранирования
    service_type = 'Доставка' if user_data['service_type'] == 'delivery' else 'Самовивіз' if language == 'uk' else 'Самовывоз'
    water_type = user_data['water_type'].capitalize()
    address = user_data['address']
    phone = user_data['phone']
    floor = user_data['floor']
    water_amount = str(user_data['water_amount'])
    water_total_cost_str = f"{water_total_cost:.1f}"
    accessories_str = accessories_str
    floor_cost_str = f"{floor_cost}"
    total_cost_str = f"{total_cost:.1f}"

    # Формируем строку заказа без экранирования
    if language == 'uk':
        order_summary = (
            f"*Нове замовлення:*\n"
            f"Тип послуги: *{service_type}*\n"
            f"Тип води: *{water_type}*\n"
            f"Адреса: *{address}*\n"
            f"Номер телефону: *{phone}*\n"
            f"Кількість води: *{water_amount} л*\n"
            f"Вартість води: *{water_total_cost_str} грн*\n"
            f"Аксесуари: *{accessories_str}*\n"
            f"Поверх/Тип будинку: *{floor}*\n"
            f"Вартість підйому: *{floor_cost_str} грн*\n"
            f"Загальна вартість: *{total_cost_str} грн*\n"
        )
    else:
        order_summary = (
            f"*Новый заказ:*\n"
            f"Тип услуги: *{service_type}*\n"
            f"Тип воды: *{water_type}*\n"
            f"Адрес: *{address}*\n"
            f"Номер телефона: *{phone}*\n"
            f"Количество воды: *{water_amount} л*\n"
            f"Стоимость воды: *{water_total_cost_str} грн*\n"
            f"Аксессуары: *{accessories_str}*\n"
            f"Этаж/Тип дома: *{floor}*\n"
            f"Стоимость подъема: *{floor_cost_str} грн*\n"
            f"Общая стоимость: *{total_cost_str} грн*\n"
        )

    # Логирование для отладки
    print("Сформированный заказ:", order_summary)

    return order_summary

# Функция для вывода полного заказа после выбора аксессуаров
async def handle_order_summary(update, context):
    user_data = context.user_data
    language = user_data['language']
    water_total_cost, accessories_cost, floor_cost, total_cost = calculate_costs(user_data)
    order_summary = format_order_summary(user_data, water_total_cost, accessories_cost, floor_cost, total_cost)
    context.user_data['last_order'] = {
        'order_summary': order_summary,
        'final_notification': FINAL_NOTIFICATION_UK_RAW if language == 'uk' else FINAL_NOTIFICATION_RU_RAW
    }

    # Логирование для отладки перед экранированием
    print("Сформированный заказ до экранирования:", order_summary)

    # Используем экранирование для Markdown
    escaped_order_summary = escape_markdown(order_summary)

    # Логирование после экранирования
    print("Сформированный заказ после экранирования:", escaped_order_summary)

    # Попробуем отправить сообщение пользователю с минимальным экранированием
    try:
        await update.message.reply_text(escaped_order_summary, parse_mode='Markdown')
    except telegram.error.BadRequest as e:
        print(f"Ошибка отправки сообщения: {e}")
        # Если ошибка повторяется, отправим сообщение без экранирования
        try:
            await update.message.reply_text(order_summary)
        except telegram.error.BadRequest as e:
            print(f"Ошибка при отправке сообщения без экранирования: {e}")
            await update.message.reply_text("Произошла ошибка при отправке сообщения. Пожалуйста, проверьте текст на наличие запрещенных символов.")
        return

    # Отправка сообщения в группу с минимальным экранированием
    try:
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=escaped_order_summary, parse_mode='Markdown')
    except telegram.error.BadRequest as e:
        print(f"Ошибка отправки сообщения в группу: {e}")
        # Если ошибка повторяется, отправим сообщение без экранирования
        try:
            await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=order_summary)
        except telegram.error.BadRequest as e:
            print(f"Ошибка при отправке сообщения в группу без экранирования: {e}")
            await update.message.reply_text("Произошла ошибка при отправке сообщения в группу. Пожалуйста, проверьте текст на наличие запрещенных символов.")
        return

    # Отправка финального уведомления
    final_notification = context.user_data['last_order']['final_notification']

    # Отправка финального уведомления пользователю
    try:
        await update.message.reply_text(final_notification)
    except telegram.error.BadRequest as e:
        print(f"Ошибка отправки финального уведомления: {e}")
        await update.message.reply_text("Произошла ошибка при отправке финального уведомления.")

    # Восстановим кнопку "Повторить заказ"
    keyboard = [
        [InlineKeyboardButton("Повторити замовлення" if language == 'uk' else "Повторить заказ", callback_data='repeat_order')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await update.message.reply_text("Если вы хотите повторить заказ, нажмите на кнопку ниже:", reply_markup=reply_markup)
    except telegram.error.BadRequest as e:
        print(f"Ошибка отправки кнопки повторного заказа: {e}")
        await update.message.reply_text("Произошла ошибка при отправке кнопки повторного заказа.")

    return ConversationHandler.END

# Вызов подробного списка аксессуаров в функции `handle_accessories_offer`:
async def handle_accessories_offer(update: Update, context):
    accessories_list = context.user_data['prices']['accessories']
    language = context.user_data.get('language', 'uk')
    
    accessories_message = format_accessories_list_detailed(accessories_list, language)
    await update.message.reply_text(accessories_message)
    
    if language == 'uk':
        await update.message.reply_text("Виберіть аксесуар і кількість, наприклад: 1 2 (помпа механічна, 2 шт) або введіть 0, щоб пропустити.")
    else:
        await update.message.reply_text("Выберите аксессуар и количество, например: 1 2 (механическая помпа, 2 шт) или введите 0, чтобы пропустить.")
    
    return ACCESSORIES_CHOICE  # Переход к выбору аксессуаров

# Функция для обработки выбора аксессуаров
async def handle_accessories_choice(update: Update, context):
    user_input = update.message.text.strip()
    language = context.user_data.get('language', 'uk')

    # Если пользователь ввел 0, пропускаем выбор аксессуаров и переходим к следующему этапу
    if user_input == '0':
        if language == 'uk':
            await update.message.reply_text("Аксесуари не вибрані. Продовжуємо замовлення.")
        else:
            await update.message.reply_text("Аксессуары не выбраны. Продолжаем заказ.")
        
        # Переход к следующему шагу - финализация заказа
        return await handle_order_summary(update, context)

    # Проверяем, что пользователь ввел корректный формат (номер аксессуара и количество)
    try:
        accessory_index, quantity = map(int, user_input.split())
    except ValueError:
        # Если ввод не соответствует формату, повторяем запрос
        if language == 'uk':
            await update.message.reply_text("Неправильний формат. Виберіть аксесуар і кількість, або введіть 0, щоб пропустити.")
        else:
            await update.message.reply_text("Неправильный формат. Выберите аксессуар и количество, или введите 0, чтобы пропустить.")
        return ACCESSORIES_CHOICE

    # Проверяем, что номер аксессуара существует в списке
    accessories_list = context.user_data['prices']['accessories']
    
    if 1 <= accessory_index <= len(accessories_list):
        selected_accessory = accessories_list[accessory_index - 1]
        accessory_cost = selected_accessory['delivery'] * quantity

        # Проверяем наличие выбранного количества аксессуара
        if quantity > 0:
            # Добавляем выбранный аксессуар в данные пользователя
            if 'selected_accessories' not in context.user_data:
                context.user_data['selected_accessories'] = []

            context.user_data['selected_accessories'].append({
                'name': selected_accessory['name'],
                'quantity': quantity,
                'cost': accessory_cost
            })

            if language == 'uk':
                await update.message.reply_text(f"Ви вибрали {selected_accessory['name']} у кількості {quantity} шт. Загальна вартість: {accessory_cost} грн.")
            else:
                await update.message.reply_text(f"Вы выбрали {selected_accessory['name']} в количестве {quantity} шт. Общая стоимость: {accessory_cost} грн.")
            
            # Предлагаем пользователю выбрать еще аксессуары или продолжить заказ
            if language == 'uk':
                await update.message.reply_text("Введіть номер наступного аксесуара і кількість, або введіть 0, щоб закінчити вибір аксесуарів.")
            else:
                await update.message.reply_text("Введите номер следующего аксессуара и количество, или введите 0, чтобы закончить выбор аксессуаров.")
        else:
            if language == 'uk':
                await update.message.reply_text("Будь ласка, введіть кількість більше нуля або введіть 0, щоб пропустити.")
            else:
                await update.message.reply_text("Пожалуйста, введите количество больше нуля или введите 0, чтобы пропустить.")

        return ACCESSORIES_CHOICE
    else:
        # Если аксессуар не существует, повторяем запрос
        if language == 'uk':
            await update.message.reply_text("Неправильний вибір. Виберіть аксесуар і кількість, або введіть 0, щоб пропустити.")
        else:
            await update.message.reply_text("Неправильный выбор. Выберите аксессуар и количество, или введите 0, чтобы пропустить.")
        return ACCESSORIES_CHOICE

# Функция для обработки пропуска шага при выборе 0
async def skip_accessories(update, context):
    language = context.user_data.get('language', 'uk')
    if language == 'uk':
        await update.message.reply_text("Аксесуари не вибрані. Продовжуємо замовлення.")
    else:
        await update.message.reply_text("Аксессуары не выбраны. Продолжаем заказ.")

    # Переход к следующему шагу - финализация заказа
    return await handle_order_summary(update, context)

# Функция для поиска ключей с учетом регистра
def find_in_dict_with_case(dictionary, key):
    key_lower = key.lower()
    key_upper = key.capitalize()

    if key_lower in dictionary:
        return dictionary[key_lower]
    elif key_upper in dictionary:
        return dictionary[key_upper]
    else:
        raise KeyError(f"Ключ '{key}' не найден ни в нижнем, ни в верхнем регистре")

# Добавляем логирование состояний для всех состояний
def log_current_state(context, state_name):
    print(f"[LOG] Текущее состояние: {state_name}")
    print(f"[LOG] Данные пользователя: {context.user_data}")

async def repeat_order(update: Update, context):
    query = update.callback_query
    await query.answer()
    last_order = context.user_data.get('last_order')

    if not last_order:
        await query.edit_message_text("Последний заказ не найден.")
        return
    
    order_summary = last_order['order_summary']
    
    # Логирование перед отправкой сообщения
    print("Повтор заказа перед отправкой:", order_summary)

    # Отправляем сообщение пользователю с минимальным экранированием (Markdown)
    try:
        await context.bot.send_message(chat_id=query.message.chat_id, text=order_summary, parse_mode='Markdown')
    except telegram.error.BadRequest as e:
        print(f"Ошибка отправки сообщения: {e}")
        # Если ошибка повторяется, отправим сообщение без экранирования
        try:
            await context.bot.send_message(chat_id=query.message.chat_id, text=order_summary)
        except telegram.error.BadRequest as e:
            print(f"Ошибка при отправке сообщения без экранирования: {e}")
            await query.edit_message_text("Произошла ошибка при отправке сообщения. Пожалуйста, проверьте текст на наличие запрещенных символов.")
        return
    
    # Отправляем сообщение в группу с минимальным экранированием (Markdown)
    try:
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=order_summary, parse_mode='Markdown')
    except telegram.error.BadRequest as e:
        print(f"Ошибка отправки сообщения в группу: {e}")
        # Если ошибка повторяется, отправим сообщение без экранирования
        try:
            await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=order_summary)
        except telegram.error.BadRequest as e:
            print(f"Ошибка при отправке сообщения в группу без экранирования: {e}")
            await query.edit_message_text("Произошла ошибка при отправке сообщения в группу. Пожалуйста, проверьте текст на наличие запрещенных символов.")
        return
    
    # Отправляем информационное сообщение пользователю
    final_notification = last_order['final_notification']
    try:
        await context.bot.send_message(chat_id=query.message.chat_id, text=final_notification)
    except telegram.error.BadRequest as e:
        print(f"Ошибка отправки финального уведомления: {e}")
        await query.edit_message_text("Произошла ошибка при отправке финального уведомления.")

    # Восстанавливаем кнопку "Повторить заказ"
    keyboard = [
        [InlineKeyboardButton("Повторити замовлення" if context.user_data['language'] == 'uk' else "Повторить заказ", callback_data='repeat_order')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await context.bot.send_message(chat_id=query.message.chat_id, text="Если вы хотите повторить заказ, нажмите на кнопку ниже:", reply_markup=reply_markup)
    except telegram.error.BadRequest as e:
        print(f"Ошибка отправки кнопки повторного заказа: {e}")
        await query.edit_message_text("Произошла ошибка при отправке кнопки повторного заказа.")

# Функция для ограничения частоты запросов
def rate_limiter():
    print("[LOG] Ожидание 1 секунду перед отправкой следующего запроса...")
    sleep(1)  # Убедитесь, что задержка не блокирует основной поток

# Обновленный метод для логирования состояния пользователя на каждом этапе
def log_current_state(context, state_name):
    print(f"[LOG] Текущее состояние: {state_name}")
    print(f"[LOG] Данные пользователя: {context.user_data}")
    
# Обновленная функция для отправки финального уведомления с правильным экранированием
async def send_final_notification(update, context):
    language = context.user_data.get('language', 'uk')
    final_notification_raw = FINAL_NOTIFICATION_UK_RAW if language == 'uk' else FINAL_NOTIFICATION_RU_RAW
    
    # Экранируем только перед отправкой
    final_notification = escape_markdown_v2(final_notification_raw)
    await update.message.reply_text(final_notification, parse_mode='MarkdownV2')
    
# Функция для получения прайсов из Google Sheets с учетом языка
def get_prices_from_sheet(language):
    try:
        sheet = client.open('Прайс-лист').sheet1
        data = sheet.get_all_records()

        prices = {'water': {}, 'accessories': []}
        name_column = 'Название (укр)' if language == 'uk' else 'Название (рус)'

        def parse_price(value):
            try:
                return float(str(value).replace(',', '.'))
            except ValueError:
                return 0.0

        for row in data:
            item_type = row['Тип'].lower()
            if item_type == 'water':
                water_name = row[name_column].strip().lower()
                prices['water'][water_name] = {
                    'delivery': parse_price(row['Доставка']),
                    'pickup': parse_price(row['Самовывоз'])
                }
            elif item_type in ['pump', 'container']:
                prices['accessories'].append({
                    'name': row[name_column].strip(),
                    'delivery': parse_price(row['Доставка']),
                    'pickup': parse_price(row['Самовывоз'])
                })

        return prices

    except Exception as e:
        return None

# Увеличиваем количество соединений в пуле
application = ApplicationBuilder().token(telegram_token).session(session).build()

# Добавление обработчиков
application.add_handler(order_conversation)  # Обработчик диалога
application.add_handler(CommandHandler('call_ai', call_ai))  # Обработчик команды /call_ai
application.add_handler(CommandHandler('start', start))  # Обработчик команды /start

# Определяем диалоговые хендлеры
order_conversation = ConversationHandler(
    entry_points=[CommandHandler('start', start)],
    states={
        LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_language)],
        GENERAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_gpt_response)],
    },
    fallbacks=[CommandHandler('start', start), CommandHandler('call_ai', call_ai)],
    per_message=False,
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    asyncio.run(server.serve())

