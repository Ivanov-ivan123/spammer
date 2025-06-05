import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty
import random
from typing import Dict, List

# ===== НАСТРОЙКИ ===== #
# ЗАМЕНИТЕ ЭТИ ДАННЫЕ НА СВОИ!
# API_TOKEN = '7136878943:AAHAKaLe0X1ky4J0we7Y3iQeATmYoUOQ2Wo'  # Получить у @BotFather
# API_ID = 10622852             # Получить на my.telegram.org
# API_HASH = 'b92d19a058e1df6b820c44821a140da2'    # Получить на my.telegram.org
# ADMIN_ID = 585870031         # Ваш ID в Telegram (можно узнать у @userinfobot)

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
API_TOKEN = os.getenv("API_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
# ===================== #

# Настройка логгирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Создаем папку для сессий, если ее нет
os.makedirs('sessions', exist_ok=True)

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Эмодзи для скрытой отметки
EMOJI_LIST = ['👀', '🤖', '✨', '🌟', '💫', '⚡', '🔥', '💥', '🕵️', '🔍', '🔎']

# Структуры данных для хранения информации
users_data = {}      # Данные пользователей
active_spams = {}    # Активные рассылки
user_clients = {}    # Telethon клиенты пользователей

# Класс для хранения состояний
class Form(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_password = State()
    waiting_for_message = State()
    waiting_for_delay = State()
    waiting_for_chats = State()

# Класс для хранения данных пользователя
class UserData:
    def __init__(self):
        self.user_id = None
        self.username = None
        self.first_name = None
        self.last_name = None
        self.chats = []
        self.selected_chats = []
        self.message = None
        self.delay = 60  # дефолтная задержка в секундах
        self.is_active = False
        self.phone = None
        self.telethon_session = None
        self.telethon_client = None

# ===== ОСНОВНЫЕ ФУНКЦИИ ===== #

async def get_user_chats(user_id: int) -> List[Dict]:
    """Получаем список чатов пользователя через Telethon"""
    if user_id not in user_clients or not user_clients[user_id].is_connected():
        return []
    
    try:
        client = user_clients[user_id]
        chats = []
        
        result = await client(GetDialogsRequest(
            offset_date=None,
            offset_id=0,
            offset_peer=InputPeerEmpty(),
            limit=200,
            hash=0
        ))
        
        for chat in result.chats:
            if hasattr(chat, 'title') and (hasattr(chat, 'megagroup') and chat.megagroup):
                chats.append({
                    "id": chat.id,
                    "title": chat.title,
                    "type": "supergroup",
                    "access_hash": chat.access_hash
                })
        
        return chats
    except Exception as e:
        logger.error(f"Ошибка получения чатов для пользователя {user_id}: {e}")
        return []

async def send_message_as_user(user_id: int, chat_id: int, message_text: str) -> bool:
    """Отправляем сообщение от имени пользователя"""
    if user_id not in user_clients or not user_clients[user_id].is_connected():
        return False
    
    try:
        client = user_clients[user_id]

        random_emoji = random.choice(EMOJI_LIST)
        mention_link = random_emoji

        try:
            participants = await client.get_participants(chat_id, limit=50)
            if participants:
                random_user = random.choice(participants)
                mention_link = f"[{random_emoji}](tg://user?id={random_user.id})"
        except Exception as e:
            logger.warning(f"Не удалось получить участников чата {chat_id}: {e}")

        full_message = f"{message_text}\n\n{mention_link}"

    # НЕ меняем chat_id
        try:
            chat = await client.get_entity(chat_id)
        except Exception:
            chat = chat_id  # fallback — просто id, если не нашёл

        await client.send_message(chat, full_message, parse_mode='markdown')

        return True

    except Exception as e:
        import traceback
        logger.error(f"Ошибка отправки сообщения от пользователя {user_id} в чат {chat_id}: {e}")
        logger.error(traceback.format_exc())
        return False


        
        # full_message = f"{message_text}\n\n{mention_link}"
        # await client.send_message(chat_id, full_message, parse_mode='markdown')
        # return True
    # except Exception as e:
    #     # Добавляем случайный эмодзи и упоминание
    #     random_emoji = random.choice(EMOJI_LIST)
    #     # full_message = f"{message_text}\n\n{random_emoji} {mention}"
    #     mention_link = f"[{random_emoji} {random_user.first_name or ''}](tg://user?id={random_user.id})"
    #     full_message = f"{message_text}\n\n{mention_link}"
    #     full_message = str(full_message)
        
    #     await client.send_message(chat_id, full_message, parse_mode='markdown')
    #     return True
    
    # except Exception as e:
    #     import traceback
    #     logger.error(f"Ошибка отправки сообщения от пользователя {user_id} в чат {chat_id}: {e}")
    #     logger.error(traceback.format_exc())
    #     return False

def create_chats_keyboard(chats: List[Dict], selected_chats: List[int] = []) -> InlineKeyboardMarkup:
    """Создаем клавиатуру с выбором чатов"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    for chat in chats:
        chat_id = chat['id']
        chat_title = chat['title']
        prefix = "✅ " if chat_id in selected_chats else ""
        keyboard.add(InlineKeyboardButton(
            text=f"{prefix}{chat_title}",
            callback_data=f"chat_{chat_id}"
        ))
    keyboard.add(InlineKeyboardButton("🚀 Начать рассылку", callback_data="start_spam"))
    keyboard.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
    return keyboard

def create_main_menu() -> InlineKeyboardMarkup:
    """Создаем главное меню"""
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📝 Мои рассылки", callback_data="my_spams"),
        InlineKeyboardButton("⚙️ Настройки", callback_data="settings")
    )
    keyboard.add(
        InlineKeyboardButton("❓ Помощь", callback_data="help"),
        InlineKeyboardButton("📢 О боте", callback_data="about")
    )
    return keyboard

async def spam_task(user_id: int):
    """Задача для выполнения рассылки"""
    if user_id not in users_data:
        return
    
    user_data = users_data[user_id]
    
    while user_data.is_active:
        try:
            for chat_id in user_data.selected_chats:
                if not user_data.is_active:
                    break
                
                
                try:
                    success = await send_message_as_user(user_id, chat_id, user_data.message)
                    if not success:
                        logger.error(f"Не удалось отправить сообщение в чат {chat_id} для пользователя {user_id}")
                except Exception as e:
                    logger.error(f"Ошибка отправки в чат {chat_id}: {e}")
                
                await asyncio.sleep(1)  # Задержка между сообщениями
            
            if user_data.is_active:
                await asyncio.sleep(user_data.delay)  # Основная задержка
        except Exception as e:
            logger.error(f"Ошибка в задаче рассылки для пользователя {user_id}: {e}")
            await asyncio.sleep(10)

# ===== ОБРАБОТЧИКИ КОМАНД ===== #

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    
    if user_id not in users_data:
        users_data[user_id] = UserData()
        users_data[user_id].user_id = user_id
        users_data[user_id].username = message.from_user.username
        users_data[user_id].first_name = message.from_user.first_name
        users_data[user_id].last_name = message.from_user.last_name
        users_data[user_id].telethon_session = f"sessions/{user_id}.session"
        
        await Form.waiting_for_phone.set()
        await message.answer(
            "👋 Добро пожаловать в бота-рассыльщика!\n\n"
            "Для работы требуется авторизация вашего аккаунта Telegram.\n"
            "Отправьте ваш номер телефона в формате +79123456789:",
            reply_markup=types.ReplyKeyboardRemove()
        )
        
        try:
            await bot.send_message(
                ADMIN_ID,
                f"Новый пользователь: @{message.from_user.username}\n"
                f"ID: {user_id}\n"
                f"Имя: {message.from_user.full_name}"
            )
        except:
            pass
    else:
        await message.answer(
            "Главное меню:",
            reply_markup=create_main_menu()
        )

@dp.message_handler(state=Form.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    """Обработчик ввода номера телефона"""
    user_id = message.from_user.id
    phone = message.text
    
    if not phone.startswith('+'):
        await message.answer("❌ Неверный формат номера. Введите номер в формате +79123456789:")
        return
    
    users_data[user_id].phone = phone
    
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH, device_model="BotSpammer")
        await client.connect()
        
        sent_code = await client.send_code_request(phone)
        await state.update_data(
            phone_code_hash=sent_code.phone_code_hash,
            session=client.session.save(),
            phone=phone
        )
        await Form.waiting_for_code.set()
        
        await message.answer(
            "📲 Код подтверждения отправлен. Введите код в формате 1-2-3-4-5:",
            reply_markup=types.ReplyKeyboardRemove()
        )
    except Exception as e:
        logger.error(f"Ошибка отправки кода на {phone}: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}. Попробуйте снова /start")
        await state.finish()

@dp.message_handler(state=Form.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    """Обработчик ввода кода подтверждения"""
    user_id = message.from_user.id
    code = message.text.replace('-', '')
    
    if not code.isdigit() or len(code) != 5:
        await message.answer("❌ Неверный формат кода. Введите 5 цифр в формате 1-2-3-4-5:")
        return
    
    data = await state.get_data()
    session_str = data.get('session')
    phone = data.get('phone')
    phone_code_hash = data.get('phone_code_hash')
    
    try:
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await client.connect()
        
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except Exception as e:
            if "two-steps" in str(e):
                await state.update_data(session=client.session.save())
                await Form.waiting_for_password.set()
                await message.answer("🔐 Введите пароль двухэтапной аутентификации:")
                return
            raise e
        
        session_path = f"sessions/{user_id}.session"
        with open(session_path, "w") as f:
            f.write(client.session.save())

        # try:
        #     await client.sign_in(
        #         phone=users_data[user_id].phone,
        #         code=code,
        #         phone_code_hash=phone_code_hash
        #     )
        # except Exception as e:
        #     if "two-steps" in str(e):
        #         await Form.waiting_for_password.set()
        #         await message.answer("🔐 Введите пароль двухэтапной аутентификации:")
        #         return
        #     else:
        #         raise e
        
        user_clients[user_id] = client
        users_data[user_id].telethon_client = client
        users_data[user_id].chats = await get_user_chats(user_id)
        
        await state.finish()
        await message.answer(
            "✅ Авторизация успешна! Теперь вы можете начать рассылку.",
            reply_markup=create_main_menu()
        )
    except Exception as e:
        logger.error(f"Ошибка входа пользователя {user_id}: {e}")
        await message.answer(f"❌ Ошибка авторизации: {str(e)}. Попробуйте снова /start")
        await state.finish()

@dp.message_handler(state=Form.waiting_for_password)
async def process_password(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    password = message.text
    data = await state.get_data()
    session_str = data.get('session')

    try:
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await client.connect()

        await client.sign_in(password=password)

        # Успешная авторизация — сохраняем!
        session_path = f"sessions/{user_id}.session"
        with open(session_path, "w") as f:
            f.write(client.session.save())

        user_clients[user_id] = client
        users_data[user_id].telethon_client = client
        users_data[user_id].chats = await get_user_chats(user_id)

        await state.finish()
        await message.answer("✅ Авторизация успешна! Теперь вы можете начать рассылку.",
                            reply_markup=create_main_menu())

    except Exception as e:
        logger.error(f"Ошибка входа с паролем для {user_id}: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}. Попробуйте снова /start")
        await state.finish()

@dp.callback_query_handler(lambda c: c.data == 'my_spams')
async def process_my_spams(callback_query: types.CallbackQuery):
    """Обработчик кнопки 'Мои рассылки'"""
    user_id = callback_query.from_user.id
    if user_id not in users_data:
        await bot.answer_callback_query(callback_query.id, "Сначала зарегистрируйтесь через /start")
        return
    
    user_data = users_data[user_id]
    
    status = "🟢 Активна" if user_data.is_active else "🔴 Неактивна"
    button = InlineKeyboardButton("🛑 Остановить", callback_data="stop_spam") if user_data.is_active else InlineKeyboardButton("🚀 Начать новую", callback_data="new_spam")
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(button)
    keyboard.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
    
    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text=f"📊 Ваша рассылка:\n\n"
             f"📝 Сообщение: {user_data.message or 'Не задано'}\n"
             f"⏱ Задержка: {user_data.delay} сек.\n"
             f"📌 Чаты: {len(user_data.selected_chats)}\n"
             f"🔧 Статус: {status}",
        reply_markup=keyboard
    )
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == 'new_spam')
async def process_new_spam(callback_query: types.CallbackQuery):
    """Обработчик кнопки 'Новая рассылка'"""
    user_id = callback_query.from_user.id
    if user_id not in users_data:
        await bot.answer_callback_query(callback_query.id, "Сначала зарегистрируйтесь через /start")
        return
    
    users_data[user_id].selected_chats = []
    
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("📝 Ввести сообщение", callback_data="enter_message"))
    keyboard.add(InlineKeyboardButton("◀️ Назад", callback_data="my_spams"))
    
    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text="📝 Создание новой рассылки:\n\n"
             "1. Введите сообщение для рассылки\n"
             "2. Выберите чаты\n"
             "3. Установите задержку\n"
             "4. Запустите рассылку",
        reply_markup=keyboard
    )
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == 'enter_message')
async def process_enter_message(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Ввести сообщение'"""
    await Form.waiting_for_message.set()
    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text="✍️ Введите сообщение для рассылки:"
    )
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(state=Form.waiting_for_message)
async def process_message_input(message: types.Message, state: FSMContext):
    """Обработчик ввода сообщения для рассылки"""
    user_id = message.from_user.id
    if user_id not in users_data:
        await state.finish()
        return await message.answer("Сначала зарегистрируйтесь через /start")
    
    users_data[user_id].message = message.text
    await state.finish()
    
    await Form.waiting_for_chats.set()
    users_data[user_id].chats = await get_user_chats(user_id)
    
    if not users_data[user_id].chats:
        await message.answer("❌ У вас нет доступных чатов для рассылки.")
        return
    
    keyboard = create_chats_keyboard(users_data[user_id].chats)
    await message.answer(
        "✅ Сообщение сохранено. Выберите чаты для рассылки:",
        reply_markup=keyboard
    )

@dp.callback_query_handler(lambda c: c.data.startswith('chat_'), state=Form.waiting_for_chats)
async def process_chat_selection(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора чатов"""
    user_id = callback_query.from_user.id
    if user_id not in users_data:
        await bot.answer_callback_query(callback_query.id, "Ошибка: пользователь не найден")
        return
    
    chat_id = int(callback_query.data.split('_')[1])
    user_data = users_data[user_id]
    
    if chat_id in user_data.selected_chats:
        user_data.selected_chats.remove(chat_id)
    else:
        user_data.selected_chats.append(chat_id)
    
    keyboard = create_chats_keyboard(user_data.chats, user_data.selected_chats)
    await bot.edit_message_reply_markup(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        reply_markup=keyboard
    )
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == 'start_spam', state=Form.waiting_for_chats)
async def process_start_spam(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Начать рассылку'"""
    user_id = callback_query.from_user.id
    if user_id not in users_data:
        await bot.answer_callback_query(callback_query.id, "Ошибка: пользователь не найден")
        return
    
    user_data = users_data[user_id]
    
    if not user_data.selected_chats:
        await bot.answer_callback_query(callback_query.id, "Выберите хотя бы один чат!")
        return
    
    if not user_data.message:
        await bot.answer_callback_query(callback_query.id, "Сообщение не задано!")
        return
    
    await state.finish()
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("30 сек", callback_data="delay_30"),
        InlineKeyboardButton("1 мин", callback_data="delay_60"),
        InlineKeyboardButton("5 мин", callback_data="delay_300")
    )
    keyboard.add(InlineKeyboardButton("Другое", callback_data="custom_delay"))
    
    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text="⏱ Укажите задержку между сообщениями:",
        reply_markup=keyboard
    )
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith('delay_') or c.data == 'custom_delay', state='*')
async def process_delay_selection(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора задержки"""
    user_id = callback_query.from_user.id
    if user_id not in users_data:
        await bot.answer_callback_query(callback_query.id, "Ошибка: пользователь не найден")
        return
    
    if callback_query.data == 'custom_delay':
        await bot.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            text="⌛ Введите задержку в секундах (минимум 10):"
        )
        await bot.answer_callback_query(callback_query.id)
        return
    
    delay = int(callback_query.data.split('_')[1])
    users_data[user_id].delay = delay
    
    await start_spamming(user_id, callback_query.message.message_id, callback_query.message.chat.id)
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(state=Form.waiting_for_delay)
async def process_custom_delay(message: types.Message, state: FSMContext):
    """Обработчик ввода кастомной задержки"""
    user_id = message.from_user.id
    if user_id not in users_data:
        await state.finish()
        return await message.answer("Сначала зарегистрируйтесь через /start")
    
    try:
        delay = int(message.text)
        if delay < 10:
            raise ValueError("Задержка должна быть не менее 10 секунд")
        
        users_data[user_id].delay = delay
        await state.finish()
        
        await start_spamming(user_id)
        await message.answer(f"✅ Рассылка запущена с задержкой {delay} секунд")
    except ValueError as e:
        await message.answer(f"❌ Ошибка: {str(e)}. Введите число секунд (минимум 10):")

async def start_spamming(user_id: int, message_id: int = None, chat_id: int = None):
    """Запускаем рассылку"""
    if user_id not in users_data:
        return
    
    user_data = users_data[user_id]
    user_data.is_active = True
    
    if user_id in active_spams:
        active_spams[user_id].cancel()
    
    task = asyncio.create_task(spam_task(user_id))
    active_spams[user_id] = task
    
    if message_id and chat_id:
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🛑 Остановить", callback_data="stop_spam"))
        
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=f"🚀 Рассылка запущена!\n\n"
                 f"📝 Сообщение: {user_data.message}\n"
                 f"⏱ Задержка: {user_data.delay} сек.\n"
                 f"📌 Чаты: {len(user_data.selected_chats)}\n\n"
                 f"Для остановки нажмите кнопку ниже.",
            reply_markup=keyboard
        )
    else:
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🛑 Остановить", callback_data="stop_spam"))
        
        await bot.send_message(
            chat_id=user_id,
            text=f"🚀 Рассылка запущена!\n\n"
                 f"📝 Сообщение: {user_data.message}\n"
                 f"⏱ Задержка: {user_data.delay} сек.\n"
                 f"📌 Чаты: {len(user_data.selected_chats)}\n\n"
                 f"Для остановки нажмите кнопку ниже.",
            reply_markup=keyboard
        )

@dp.callback_query_handler(lambda c: c.data == 'stop_spam')
async def process_stop_spam(callback_query: types.CallbackQuery):
    """Обработчик остановки рассылки"""
    user_id = callback_query.from_user.id
    if user_id not in users_data:
        await bot.answer_callback_query(callback_query.id, "Ошибка: пользователь не найден")
        return
    
    user_data = users_data[user_id]
    user_data.is_active = False
    
    if user_id in active_spams:
        active_spams[user_id].cancel()
        del active_spams[user_id]
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🚀 Начать новую", callback_data="new_spam"))
    keyboard.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
    
    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text="🛑 Рассылка остановлена.",
        reply_markup=keyboard
    )
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == 'back_to_menu')
async def process_back_to_menu(callback_query: types.CallbackQuery):
    """Обработчик возврата в меню"""
    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text="Главное меню:",
        reply_markup=create_main_menu()
    )
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == 'help')
async def process_help(callback_query: types.CallbackQuery):
    """Обработчик кнопки 'Помощь'"""
    help_text = (
        "📖 Помощь по боту-рассыльщику:\n\n"
        "1. Для начала работы нажмите /start\n"
        "2. В разделе 'Мои рассылки' создайте новую рассылку\n"
        "3. Введите сообщение для рассылки\n"
        "4. Выберите чаты\n"
        "5. Установите задержку\n"
        "6. Нажмите 'Начать рассылку'\n\n"
        "🛑 Для остановки нажмите соответствующую кнопку\n\n"
        "⚠️ Не злоупотребляйте рассылкой"
    )
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
    
    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text=help_text,
        reply_markup=keyboard
    )
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == 'about')
async def process_about(callback_query: types.CallbackQuery):
    """Обработчик кнопки 'О боте'"""
    about_text = (
        "🤖 Бот-рассыльщик\n\n"
        "Отправляет сообщения в ваши чаты с заданной задержкой.\n\n"
        "Особенности:\n"
        "- Отправка от вашего имени\n"
        "- Настройка задержки\n"
        "- Выбор нескольких чатов\n"
        "- Простое управление\n"
        "- Разработчик @mxpon\n\n"
        "Версия: 1.0"
    )
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
    
    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text=about_text,
        reply_markup=keyboard
    )
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == 'settings')
async def process_settings(callback_query: types.CallbackQuery):
    """Обработчик кнопки 'Настройки'"""
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
    
    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text="⚙️ Настройки:\n\n"
            "Нет доступных настроек.\n",
        reply_markup=keyboard
    )
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler()
async def any_message(message: types.Message):
    """Обработчик любых других сообщений"""
    await message.answer(
        "Используйте меню для управления ботом:",
        reply_markup=create_main_menu()
    )

# ===== ЗАПУСК БОТА ===== #

async def on_startup(dp):
    """Действия при запуске бота"""
    try:
        await bot.send_message(ADMIN_ID, "🤖 Бот запущен!")
    except:
        pass

async def on_shutdown(dp):
    """Действия при остановке бота"""
    # Отключаем всех клиентов Telethon
    for user_id, client in user_clients.items():
        try:
            if client.is_connected():
                await client.disconnect()
        except:
            pass
    
    # Останавливаем все рассылки
    for user_id in users_data:
        users_data[user_id].is_active = False
    
    try:
        await bot.send_message(ADMIN_ID, "🛑 Бот выключен")
    except:
        pass
    
    await dp.storage.close()
    await dp.storage.wait_closed()

    

if __name__ == '__main__':
    # Установите pip install telethon aiogram
    executor.start_polling(dp, on_startup=on_startup, on_shutdown=on_shutdown, skip_updates=True)


# import logging
# import asyncio
# import qrcode
# import os
# import random
# from aiogram.utils import semaphore
# from telethon import TelegramClient
# from telethon.sessions import MemorySession
# from telethon.errors import SessionPasswordNeededError, PhoneNumberInvalidError, FloodWaitError
# from aiogram import Bot, Dispatcher, types
# from aiogram.contrib.fsm_storage.memory import MemoryStorage
# from aiogram.dispatcher import FSMContext
# from aiogram.dispatcher.filters.state import State, StatesGroup
# from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
# from aiogram.utils.exceptions import Unauthorized

# # Logging setup
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)

# EMOJIS = ["🙂", "🙃", "😉", "😊", "😇", "🤗", "😎", "🤩", "🤔", "😺"]



# # print("API_ID:", os.getenv("API_ID"))
# # print("API_HASH:", os.getenv("API_HASH"))
# # print("API_TOKEN:", os.getenv("API_TOKEN"))
# # API_TOKEN = '7725000275:AAGfzf_M0sj8RqQEKKsg6sUUybxBpG0A_tA'
# # API_ID = '20121768'
# # API_HASH = '5d579eeab57590fd3e68c6e68ba1249c'
# API_ID = int(os.getenv("API_ID"))
# API_HASH = os.getenv("API_HASH")
# API_TOKEN = os.getenv("API_TOKEN")

# class UserState:
#     def __init__(self):
#         self.clients = {}
#         self.selected_chats = []
#         self.messages = []
#         self.delay = 60
#         self.repeats = 1
#         self.stop_flag = False
#         self.spam_tasks = []

# class TelegramSpammer:
#     def __init__(self):
#         self.clients = {}
#         self.user_states = {}

#     async def send_message_to_chat(self, client: TelegramClient, phone: str, chat, messages: list):
#         try:
#             if not client.is_connected():
#                 await client.connect()
#                 logger.warning(f"Client {phone} was disconnected, reconnected.")
#             participants = await client.get_participants(chat, limit=10)
#             mentions = [f"[{EMOJIS[i]}](tg://user?id={u.id})" for i, u in enumerate(participants) if u and u.id]
#             text = random.choice(messages) + "\n\n" + " ".join(mentions)
#             await client.send_message(chat, text, parse_mode='Markdown')
#             logger.info(f"Message sent to {chat.name} using client {phone}")
#         except Exception as e:
#             logger.error(f"Error sending to {chat.name} using client {phone}: {e}")

#     async def spam_for_account(self, client, phone, chats, user_id):
#         user_state = self.user_states[user_id]
#         for _ in range(user_state.repeats):
#             if user_state.stop_flag:
#                 break
#             for chat in chats:
#                 if user_state.stop_flag:
#                     break
#                 try:
#                     await asyncio.sleep(user_state.delay)
#                     sem = semaphore.Semaphore(5)
#                 except FloodWaitError as e:
#                     logger.warning(f"Flood wait for {e.seconds} seconds for client {phone}")
#                     wait_time = min(e.seconds, 86400) + 5
#                     await asyncio.sleep(wait_time)
#                 except Exception as e:
#                     logger.error(f"Error in {chat.name} for client {phone}: {e}")
#         logger.info(f"Spam cycle completed for client {phone}")

#     async def run_tasks(self, tasks, user_id):
#         try:
#             await asyncio.gather(*tasks, return_exceptions=True)
#         except Exception as e:
#             logger.error(f"Error running tasks for user {user_id}: {e}")
#         logger.info(f"All bot-initiated spam tasks completed for user {user_id}.")

#     async def start_spam_from_bot(self, clients_to_use, user_id):
#         if user_id not in self.user_states:
#             self.user_states[user_id] = UserState()
#         user_state = self.user_states[user_id]
#         if not user_state.messages:
#             logger.error(f"Cannot start spam for user {user_id}: no messages set.")
#             return False
#         if not user_state.selected_chats:
#             logger.error(f"Cannot start spam for user {user_id}: no chats selected.")
#             return False
#         user_state.stop_flag = False
#         tasks = []
#         for client_data in clients_to_use:
#             task = asyncio.create_task(self.spam_for_account(client_data['client'], client_data['phone'], user_state.selected_chats, user_id))
#             tasks.append(task)
#         if not tasks:
#             logger.error(f"No spamming tasks created for user {user_id}.")
#             return False
#         await self.run_tasks(tasks, user_id)
#         return True

#     async def connect_account_bot(self, client, phone, user_id, name=None):
#         try:
#             user = await client.get_me()
#             self.clients[phone] = client
#             if user_id not in self.user_states:
#                 self.user_states[user_id] = UserState()
#             self.user_states[user_id].clients[phone] = {'client': client, 'user': user}
#             logger.info(f"Bot connected new account for {phone}")
#         except Exception as e:
#             logger.error(f"Error connecting bot account {phone} for user {user_id}: {e}")

# # Bot setup
# storage = MemoryStorage()
# bot_sessions = {}
# templates = {}

# class Form(StatesGroup):
#     CONNECT = State()
#     PASSWORD = State()
#     SELECT_CHATS = State()
#     MESSAGES = State()
#     DELAY = State()
#     REPEATS = State()
#     SELECT_ACCOUNT = State()
#     RENAME = State()
#     TEMPLATE = State()

# def get_main_menu():
#     keyboard = InlineKeyboardMarkup(row_width=2)
#     keyboard.add(
#         InlineKeyboardButton("📱 Добавить аккаунт", callback_data="connect"),
#         InlineKeyboardButton("👤 Управление аккаунтами", callback_data="manage_accounts"),
#         InlineKeyboardButton("💬 Показать чаты", callback_data="chats"),
#         InlineKeyboardButton("✅ Выбрать чаты", callback_data="select_chats"),
#         InlineKeyboardButton("✍️ Написать сообщения", callback_data="messages"),
#         InlineKeyboardButton("📋 Шаблоны сообщений", callback_data="templates"),
#         InlineKeyboardButton("⏳ Установить задержку", callback_data="delay"),
#         InlineKeyboardButton("🔁 Установить повторы", callback_data="repeats"),
#         InlineKeyboardButton("🚀 Начать рассылку", callback_data="select_account_for_spam"),
#         InlineKeyboardButton("🛑 Остановить", callback_data="stop"),
#         InlineKeyboardButton("📊 Показать статус", callback_data="status")
#     )
#     return keyboard

# def get_account_selection_menu(user_id):
#     keyboard = InlineKeyboardMarkup(row_width=1)
#     if user_id in bot_sessions and bot_sessions[user_id]:
#         for phone, data in bot_sessions[user_id].items():
#             name = data.get('name', phone)
#             mark = "✅" if phone in window.user_states.get(user_id, UserState()).clients else ""
#             keyboard.add(InlineKeyboardButton(f"{mark} Аккаунт: {name}", callback_data=f"toggle_spam_account_{phone}"))
#     keyboard.add(InlineKeyboardButton("🚀 Запустить с выбранных", callback_data="start_selected_accounts_spam"))
#     keyboard.add(InlineKeyboardButton("⬅ Назад", callback_data="back_from_account_selection"))
#     return keyboard

# def get_manage_menu(user_id):
#     keyboard = InlineKeyboardMarkup(row_width=1)
#     if user_id in bot_sessions:
#         for phone, data in bot_sessions[user_id].items():
#             name = data.get('name', phone)
#             keyboard.add(
#                 InlineKeyboardButton(f"{name}: Переименовать", callback_data=f"rename_{phone}"),
#                 InlineKeyboardButton(f"{name}: Удалить", callback_data=f"delete_{phone}")
#             )
#     keyboard.add(InlineKeyboardButton("⬅ Назад", callback_data="back"))
#     return keyboard

# def get_template_menu(user_id):
#     keyboard = InlineKeyboardMarkup(row_width=1)
#     if user_id in templates and templates[user_id]:
#         for name in sorted(templates[user_id].keys()):
#             keyboard.add(InlineKeyboardButton(f"Шаблон: {name}", callback_data=f"use_template_{name}"))
#     keyboard.add(
#         InlineKeyboardButton("➕ Создать новый шаблон", callback_data="new_template"),
#         InlineKeyboardButton("⬅ Назад", callback_data="back")
#     )
#     return keyboard

# async def validate_bot_token(bot):
#     try:
#         await bot.get_me()
#         logger.info("Bot token validated successfully.")
#         return True
#     except Unauthorized as e:
#         logger.critical(f"Invalid bot token: {e}")
#         return False
#     except Exception as e:
#         logger.error(f"Error validating bot token: {e}")
#         return False

# window = TelegramSpammer()
# bot_polling_task = None

# async def start_bot_polling():
#     global bot_polling_task
#     bot = Bot(token=API_TOKEN)
#     dp = Dispatcher(bot, storage=MemoryStorage())

#     @dp.message_handler(commands=['start', 'help'])
#     async def start(message: types.Message):
#         text = (
#             "👋 *Рассылка в Telegram*\n"
#             "Бот для рассылки сообщений.\n"
#             "1. Добавь аккаунт через QR-код.\n"
#             "2. Выбери чаты и сообщения.\n"
#             "3. Укажи повторы и запусти рассылку!"
#         )
#         sent_msg = await message.answer(text, reply_markup=get_main_menu(), parse_mode="Markdown")
#         try:
#             await sent_msg.pin()
#         except Exception as e:
#             logger.error(f"Failed to pin message: {e}")

#     @dp.callback_query_handler(lambda c: c.data == "connect")
#     async def connect_button(callback_query: types.CallbackQuery):
#         await Form.CONNECT.set()
#         await callback_query.message.answer(
#             "📱 Введите номер телефона.\nПример: +79991234567\nМы отправим QR-код.",
#             reply_markup=get_main_menu()
#         )
#         await callback_query.answer()

#     @dp.message_handler(state=Form.CONNECT)
#     async def process_connect(message: types.Message, state: FSMContext):
#         phone = message.text.strip()
#         user_id = message.from_user.id
#         if not phone.startswith('+') or len(phone) < 10:
#             await message.reply("❌ Неверный формат. Пример: +79991234567.", reply_markup=get_main_menu())
#             logger.error(f"Invalid phone format: {phone}")
#             return
#         try:
#             client = TelegramClient(MemorySession(), API_ID, API_HASH)
#             await client.connect()
#             if await client.is_user_authorized():
#                 if user_id not in bot_sessions:
#                     bot_sessions[user_id] = {}
#                 bot_sessions[user_id][phone] = {'client': client, 'name': phone}
#                 await window.connect_account_bot(client, phone, user_id)
#                 await state.finish()
#                 await message.reply("✅ Аккаунт подключен!", reply_markup=get_main_menu())
#                 logger.info(f"Account {phone} already authorized for user {user_id}")
#                 return
#             qr_login = await client.qr_login()
#             qr = qrcode.QRCode()
#             qr.add_data(qr_login.url)
#             qr.make(fit=True)
#             qr_img = qr.make_image(fill_color="black", back_color="white")
#             qr_path = f"qr_{phone}.png"
#             try:
#                 qr_img.save(qr_path)
#             except Exception as e:
#                 await message.reply(f"❌ Ошибка создания QR-кода: {e}", reply_markup=get_main_menu())
#                 logger.error(f"Failed to save QR code for {phone}: {e}")
#                 await state.finish()
#                 return
#             try:
#                 with open(qr_path, 'rb') as f:
#                     await message.reply_photo(f, caption=f"📱 Отсканируйте QR-код для {phone} в Telegram.")
#                 await qr_login.wait(timeout=60)
#                 if user_id not in bot_sessions:
#                     bot_sessions[user_id] = {}
#                 bot_sessions[user_id][phone] = {'client': client, 'name': phone}
#                 await window.connect_account_bot(client, phone, user_id)
#                 await state.finish()
#                 await message.reply("✅ Аккаунт подключен!", reply_markup=get_main_menu())
#                 logger.info(f"Account {phone} connected via QR for user {user_id}")
#             except SessionPasswordNeededError:
#                 await Form.PASSWORD.set()
#                 async with state.proxy() as data:
#                     data['client'] = client
#                     data['phone'] = phone
#                 await message.reply("🔒 Введите пароль 2FA:", reply_markup=get_main_menu())
#             except asyncio.TimeoutError:
#                 await message.reply("❌ Время ожидания QR-кода истекло.", reply_markup=get_main_menu())
#                 logger.error(f"QR login timeout for {phone} for user {user_id}")
#                 await state.finish()
#             except PhoneNumberInvalidError:
#                 await message.reply("❌ Неверный номер телефона.", reply_markup=get_main_menu())
#                 logger.error(f"Invalid phone number: {phone} for user {user_id}")
#                 await state.finish()
#             finally:
#                 if os.path.exists(qr_path):
#                     os.remove(qr_path)
#         except Exception as e:
#             await message.reply(f"❌ Ошибка QR-кода: {e}", reply_markup=get_main_menu())
#             logger.error(f"QR login error for {phone} for user {user_id}: {e}")
#             await state.finish()

#     @dp.message_handler(state=Form.PASSWORD)
#     async def process_password(message: types.Message, state: FSMContext):
#         user_id = message.from_user.id
#         async with state.proxy() as data:
#             client = data.get('client')
#             phone = data.get('phone')
#         if not client or not phone:
#             await message.reply("❌ Сессия не найдена.", reply_markup=get_main_menu())
#             logger.error(f"Session not found for 2FA for user {user_id}")
#             await state.finish()
#             return
#         password = message.text.strip()
#         try:
#             await client.sign_in(password=password)
#             if user_id not in bot_sessions:
#                 bot_sessions[user_id] = {}
#             bot_sessions[user_id][phone] = {'client': client, 'name': phone}
#             await window.connect_account_bot(client, phone, user_id)
#             await state.finish()
#             await message.reply("✅ Аккаунт подключен!", reply_markup=get_main_menu())
#             logger.info(f"Account {phone} connected with 2FA for user {user_id}")
#         except Exception as e:
#             await message.reply(f"❌ Ошибка входа: {e}", reply_markup=get_main_menu())
#             logger.error(f"2FA login error for {phone} for user {user_id}: {e}")
#             await state.finish()

#     @dp.callback_query_handler(lambda c: c.data == "manage_accounts")
#     async def manage_accounts_button(callback_query: types.CallbackQuery):
#         user_id = callback_query.from_user.id
#         if user_id not in bot_sessions or not bot_sessions[user_id]:
#             await callback_query.message.answer("❌ Нет аккаунтов.", reply_markup=get_main_menu())
#         else:
#             await callback_query.message.answer("👤 Управление аккаунтами:", reply_markup=get_manage_menu(user_id))
#         await callback_query.answer()

#     @dp.callback_query_handler(lambda c: c.data.startswith("rename_"))
#     async def rename_button(callback_query: types.CallbackQuery, state: FSMContext):
#         phone = callback_query.data.replace("rename_", "")
#         await Form.RENAME.set()
#         await callback_query.message.answer(f"✏️ Введите новое имя для {phone}:", reply_markup=get_main_menu())
#         async with state.proxy() as data:
#             data['phone_to_rename'] = phone
#         await callback_query.answer()

#     @dp.message_handler(state=Form.RENAME)
#     async def process_rename(message: types.Message, state: FSMContext):
#         user_id = message.from_user.id
#         new_name = message.text.strip()
#         async with state.proxy() as data:
#             phone = data.get('phone_to_rename')
#         if phone and user_id in bot_sessions and phone in bot_sessions[user_id]:
#             bot_sessions[user_id][phone]['name'] = new_name
#             await message.reply(f"✅ Аккаунт {phone} теперь называется: {new_name}", reply_markup=get_main_menu())
#             logger.info(f"Account {phone} renamed to {new_name} for user {user_id}")
#         else:
#             await message.reply("❌ Не удалось переименовать аккаунт.", reply_markup=get_main_menu())
#             logger.error(f"Failed to rename account for user {user_id}, phone {phone}")
#         await state.finish()

#     @dp.callback_query_handler(lambda c: c.data.startswith("delete_"))
#     async def delete_button(callback_query: types.CallbackQuery):
#         phone = callback_query.data.replace("delete_", "")
#         user_id = callback_query.from_user.id
#         if user_id in bot_sessions and phone in bot_sessions[user_id]:
#             client_to_delete = bot_sessions[user_id][phone]['client']
#             try:
#                 await client_to_delete.disconnect()
#                 logger.info(f"Client {phone} disconnected.")
#             except Exception as e:
#                 logger.warning(f"Error disconnecting client {phone}: {e}")
#             del bot_sessions[user_id][phone]
#             if user_id in window.user_states and phone in window.user_states[user_id].clients:
#                 del window.user_states[user_id].clients[phone]
#             await callback_query.message.answer(f"🗑 Аккаунт {phone} удален.", reply_markup=get_main_menu())
#             logger.info(f"Account {phone} deleted for user {user_id}")
#         else:
#             await callback_query.message.answer("❌ Аккаунт не найден.", reply_markup=get_main_menu())
#             logger.error(f"Attempted to delete non-existent account {phone} for user {user_id}")
#         await callback_query.answer()

#     @dp.callback_query_handler(lambda c: c.data == "chats")
#     async def show_chats_button(callback_query: types.CallbackQuery):
#         user_id = callback_query.from_user.id
#         if user_id in bot_sessions:
#             chat_names = []
#             for phone, data in bot_sessions[user_id].items():
#                 client = data['client']
#                 try:
#                     async for dialog in client.iter_dialogs():
#                         if dialog.is_group or dialog.is_channel:
#                             chat_names.append(dialog.name)
#                 except Exception as e:
#                     logger.error(f"Failed to load chats for account {phone}: {e}")
#             if chat_names:
#                 response = "💬 Доступные чаты:\n" + "\n".join(chat_names)
#             else:
#                 response = "❌ Нет доступных чатов. Подключите аккаунт(ы)."
#         else:
#             response = "❌ Нет доступных чатов. Подключите аккаунт(ы)."
#         await callback_query.message.answer(response, reply_markup=get_main_menu())
#         await callback_query.answer()

#     @dp.callback_query_handler(lambda c: c.data == "select_chats")
#     async def select_chats_button(callback_query: types.CallbackQuery, state: FSMContext):
#         user_id = callback_query.from_user.id
#         if user_id not in bot_sessions or not bot_sessions[user_id]:
#             await callback_query.message.answer("❌ Нет доступных чатов.", reply_markup=get_main_menu())
#             await callback_query.answer()
#             return
#         available_chats = []
#         for phone, data in bot_sessions[user_id].items():
#             client = data['client']
#             try:
#                 async for dialog in client.iter_dialogs():
#                     if dialog.is_group or dialog.is_channel:
#                         available_chats.append(dialog.name)
#             except Exception as e:
#                 logger.error(f"Failed to load chats for account {phone}: {e}")
#         if not available_chats:
#             await callback_query.message.answer("❌ Нет доступных чатов.", reply_markup=get_main_menu())
#             await callback_query.answer()
#             return
#         chat_map = {str(idx): chat_name for idx, chat_name in enumerate(available_chats)}
#         async with state.proxy() as data:
#             data['chat_map'] = chat_map
#             data['selected_chat_names'] = []
#         keyboard = InlineKeyboardMarkup(row_width=1)
#         for idx, chat_name in chat_map.items():
#             keyboard.add(InlineKeyboardButton(chat_name, callback_data=f"chat_select_{idx}"))
#         keyboard.add(InlineKeyboardButton("✅ Готово", callback_data="finish_chat"))
#         await Form.SELECT_CHATS.set()
#         await callback_query.message.answer("✅ Выберите чаты:", reply_markup=keyboard)
#         await callback_query.answer()

#     @dp.callback_query_handler(lambda c: c.data.startswith("chat_select_"), state=Form.SELECT_CHATS)
#     async def toggle_chat_selection(callback_query: types.CallbackQuery, state: FSMContext):
#         idx = callback_query.data.replace("chat_select_", "")
#         async with state.proxy() as data:
#             chat_map = data.get('chat_map', {})
#             selected_chat_names = data.get('selected_chat_names', [])
#             if idx in chat_map:
#                 chat_name = chat_map[idx]
#                 if chat_name in selected_chat_names:
#                     selected_chat_names.remove(chat_name)
#                     mark = ""
#                 else:
#                     selected_chat_names.append(chat_name)
#                     mark = "✅ "
#                 data['selected_chat_names'] = selected_chat_names
#             else:
#                 logger.error(f"Invalid chat index: {idx}")
#                 await callback_query.answer("❌ Ошибка: чат не найден.")
#                 return
#         keyboard = InlineKeyboardMarkup(row_width=1)
#         for idx_map, chat_name in chat_map.items():
#             current_mark = "✅ " if chat_name in selected_chat_names else ""
#             keyboard.add(InlineKeyboardButton(f"{current_mark}{chat_name}", callback_data=f"chat_select_{idx_map}"))
#         keyboard.add(InlineKeyboardButton("✅ Готово", callback_data="finish_chat"))
#         await callback_query.message.edit_reply_markup(reply_markup=keyboard)
#         await callback_query.answer(f"{mark}{chat_name}")

#     @dp.callback_query_handler(lambda c: c.data == "finish_chat", state=Form.SELECT_CHATS)
#     async def finalize_chat_selection(callback_query: types.CallbackQuery, state: FSMContext):
#         user_id = callback_query.from_user.id
#         async with state.proxy() as data:
#             final_selected_chat_names = data.get('selected_chat_names', [])
#         if final_selected_chat_names:
#             if user_id not in window.user_states:
#                 window.user_states[user_id] = UserState()
#             window.user_states[user_id].selected_chats = final_selected_chat_names
#             await callback_query.message.answer(f"✅ Выбрано {len(final_selected_chat_names)} чатов.", reply_markup=get_main_menu())
#             logger.info(f"Bot selected {len(final_selected_chat_names)} chats for user {user_id}")
#         else:
#             if user_id in window.user_states:
#                 window.user_states[user_id].selected_chats = []
#             await callback_query.message.answer("❌ Чаты не выбраны.", reply_markup=get_main_menu())
#             logger.info(f"No chats selected by user {user_id}")
#         await state.finish()
#         await callback_query.answer()

#     @dp.callback_query_handler(lambda c: c.data == "messages")
#     async def messages_button(callback_query: types.CallbackQuery):
#         await Form.MESSAGES.set()
#         await callback_query.message.answer("✍️ Введите сообщения, каждое с новой строки:", reply_markup=get_main_menu())
#         await callback_query.answer()

#     @dp.message_handler(state=Form.MESSAGES)
#     async def process_messages(message: types.Message, state: FSMContext):
#         user_id = message.from_user.id
#         messages = [m.strip() for m in message.text.splitlines() if m.strip()]
#         if messages:
#             if user_id not in window.user_states:
#                 window.user_states[user_id] = UserState()
#             window.user_states[user_id].messages = messages
#             await message.reply(f"✅ Сохранено {len(messages)} сообщений.", reply_markup=get_main_menu())
#             logger.info(f"Messages set for user {user_id}: {messages}")
#         else:
#             await message.reply("❌ Сообщения не были введены.", reply_markup=get_main_menu())
#             logger.warning(f"No messages provided by user {user_id}")
#         await state.finish()

#     @dp.callback_query_handler(lambda c: c.data == "delay")
#     async def delay_button(callback_query: types.CallbackQuery):
#         await Form.DELAY.set()
#         user_id = callback_query.from_user.id
#         delay = window.user_states.get(user_id, UserState()).delay
#         await callback_query.message.answer(f"⏳ Введите задержку (секунд, текущая: {delay}):", reply_markup=get_main_menu())
#         await callback_query.answer()

#     @dp.message_handler(state=Form.DELAY)
#     async def process_delay(message: types.Message, state: FSMContext):
#         user_id = message.from_user.id
#         try:
#             delay = int(message.text.strip())
#             if 1 <= delay <= 600:
#                 if user_id not in window.user_states:
#                     window.user_states[user_id] = UserState()
#                 window.user_states[user_id].delay = delay
#                 await message.reply(f"✅ Задержка установлена на {delay} секунд.", reply_markup=get_main_menu())
#                 logger.info(f"Delay set to {delay} seconds for user {user_id}")
#             else:
#                 await message.reply("❌ Задержка должна быть от 1 до 600 секунд.", reply_markup=get_main_menu())
#                 logger.warning(f"Invalid delay input: {delay} by user {user_id}")
#         except ValueError:
#             await message.reply("❌ Неверный формат. Введите число.", reply_markup=get_main_menu())
#             logger.warning(f"Non-numeric delay input: {message.text} by user {user_id}")
#         await state.finish()

#     @dp.callback_query_handler(lambda c: c.data == "repeats")
#     async def repeats_button(callback_query: types.CallbackQuery):
#         await Form.REPEATS.set()
#         user_id = callback_query.from_user.id
#         repeats = window.user_states.get(user_id, UserState()).repeats
#         await callback_query.message.answer(f"🔁 Введите количество повторов (текущее: {repeats}):", reply_markup=get_main_menu())
#         await callback_query.answer()

#     @dp.message_handler(state=Form.REPEATS)
#     async def process_repeats(message: types.Message, state: FSMContext):
#         user_id = message.from_user.id
#         try:
#             repeats = int(message.text.strip())
#             if 1 <= repeats <= 100:
#                 if user_id not in window.user_states:
#                     window.user_states[user_id] = UserState()
#                 window.user_states[user_id].repeats = repeats
#                 await message.reply(f"✅ Установлено {repeats} повторов.", reply_markup=get_main_menu())
#                 logger.info(f"Repeats set to {repeats} for user {user_id}")
#             else:
#                 await message.reply("❌ Повторы должны быть от 1 до 100.", reply_markup=get_main_menu())
#                 logger.warning(f"Invalid repeats input: {repeats} by user {user_id}")
#         except ValueError:
#             await message.reply("❌ Неверный формат. Введите число.", reply_markup=get_main_menu())
#             logger.warning(f"Non-numeric repeats input: {message.text} by user {user_id}")
#         await state.finish()

#     @dp.callback_query_handler(lambda c: c.data == "select_account_for_spam")
#     async def select_account_for_spam_button(callback_query: types.CallbackQuery):
#         user_id = callback_query.from_user.id
#         if user_id not in bot_sessions or not bot_sessions[user_id]:
#             await callback_query.message.answer("❌ Нет аккаунтов.", reply_markup=get_main_menu())
#         else:
#             await Form.SELECT_ACCOUNT.set()
#             await callback_query.message.answer("✅ Выберите аккаунты для рассылки:", reply_markup=get_account_selection_menu(user_id))
#         await callback_query.answer()

#     @dp.callback_query_handler(lambda c: c.data.startswith("toggle_spam_account_"), state=Form.SELECT_ACCOUNT)
#     async def toggle_spam_account(callback_query: types.CallbackQuery):
#         phone = callback_query.data.replace("toggle_spam_account_", "")
#         user_id = callback_query.from_user.id
#         if user_id not in window.user_states:
#             window.user_states[user_id] = UserState()
#         if phone in window.user_states[user_id].clients:
#             del window.user_states[user_id].clients[phone]
#             await callback_query.answer(f"Аккаунт {phone} снят с рассылки.")
#         else:
#             if user_id in bot_sessions and phone in bot_sessions[user_id]:
#                 window.user_states[user_id].clients[phone] = bot_sessions[user_id][phone]
#                 await callback_query.answer(f"Аккаунт {phone} выбран для рассылки.")
#             else:
#                 await callback_query.answer(f"Аккаунт {phone} не найден.")
#                 logger.warning(f"Attempted to select non-existent account {phone} for user {user_id}")
#         await callback_query.message.edit_reply_markup(reply_markup=get_account_selection_menu(user_id))

#     @dp.callback_query_handler(lambda c: c.data == "start_selected_accounts_spam", state=Form.SELECT_ACCOUNT)
#     async def start_selected_accounts_spam(callback_query: types.CallbackQuery, state: FSMContext):
#         user_id = callback_query.from_user.id
#         clients_to_use = [{'client': data['client'], 'phone': phone} for phone, data in window.user_states.get(user_id, UserState()).clients.items()]
#         if not clients_to_use:
#             await callback_query.message.answer("❌ Не выбрано ни одного аккаунта.", reply_markup=get_main_menu())
#             logger.warning(f"User {user_id} attempted to start spam without accounts.")
#             await state.finish()
#             await callback_query.answer()
#             return

#         await callback_query.answer("🚀 Рассылка началась!")

#         success = await window.start_spam_from_bot(clients_to_use, user_id)
#         if success:
#             await callback_query.message.answer("🚀 Рассылка началась!", reply_markup=get_main_menu())
#             logger.info(f"Bot-initiated spam started for user {user_id}")
#         else:
#             await callback_query.message.answer("❌ Не удалось начать рассылку.", reply_markup=get_main_menu())
#             logger.error(f"Failed to start spam for user {user_id}")
#         await state.finish()

#     @dp.callback_query_handler(lambda c: c.data == "stop")
#     async def stop_button(callback_query: types.CallbackQuery):
#         user_id = callback_query.from_user.id
#         if user_id in window.user_states:
#             window.user_states[user_id].stop_flag = True
#             for phone, data in window.user_states[user_id].clients.items():
#                 try:
#                     await data['client'].disconnect()
#                 except Exception as e:
#                     logger.error(f"Error disconnecting {phone}: {e}")
#             window.user_states[user_id].spam_tasks = []
#             await callback_query.message.answer("🛑 Рассылка остановлена.", reply_markup=get_main_menu())
#             logger.info(f"Spam stopped for user {user_id}")
#         else:
#             await callback_query.message.answer("❌ Нет активной рассылки.", reply_markup=get_main_menu())
#             logger.info(f"No active spam for user {user_id}")
#         await callback_query.answer()

#     @dp.callback_query_handler(lambda c: c.data == "status")
#     async def status_button(callback_query: types.CallbackQuery):
#         user_id = callback_query.from_user.id
#         user_state = window.user_states.get(user_id, UserState())
#         active_accounts_count = len(user_state.clients)
#         status_text = (f"Сообщений: {len(user_state.messages)}, "
#                     f"Чатов: {len(user_state.selected_chats)}, "
#                     f"Задержка: {user_state.delay} сек., "
#                     f"Повторов: {user_state.repeats}, "
#                     f"Активных аккаунтов: {active_accounts_count}")
#         await callback_query.message.answer(f"📊 Статус:\n{status_text}", reply_markup=get_main_menu())
#         await callback_query.answer()

#     @dp.callback_query_handler(lambda c: c.data == "templates")
#     async def templates_button(callback_query: types.CallbackQuery):
#         user_id = callback_query.from_user.id
#         if user_id not in templates or not templates[user_id]:
#             await callback_query.message.answer("📋 Нет шаблонов.", reply_markup=get_template_menu(user_id))
#         else:
#             template_list = "\n".join(f"{i+1}. {name}" for i, name in enumerate(sorted(templates[user_id].keys())))
#             await callback_query.message.answer(f"📋 Шаблоны:\n{template_list}", reply_markup=get_template_menu(user_id))
#         await callback_query.answer()

#     @dp.callback_query_handler(lambda c: c.data == "new_template")
#     async def new_template_button(callback_query: types.CallbackQuery):
#         await Form.TEMPLATE.set()
#         await callback_query.message.answer(
#             "📋 Введите шаблон:\nПервая строка — название шаблона.\nОстальные строки — сообщения.",
#             reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅ Отмена", callback_data="back"))
#         )
#         await callback_query.answer()

#     @dp.message_handler(state=Form.TEMPLATE)
#     async def process_new_template(message: types.Message, state: FSMContext):
#         user_id = message.from_user.id
#         lines = [m.strip() for m in message.text.splitlines() if m.strip()]
#         if len(lines) < 2:
#             await message.reply("❌ Шаблон должен содержать название и сообщение.", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅ Отмена", callback_data="back")))
#             return
#         template_name = lines[0]
#         template_messages = lines[1:]
#         if user_id not in templates:
#             templates[user_id] = {}
#         if template_name in templates[user_id]:
#             await message.reply(f"❌ Шаблон '{template_name}' уже существует.", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅ Отмена", callback_data="back")))
#             return
#         templates[user_id][template_name] = template_messages
#         await state.finish()
#         await message.reply(f"✅ Шаблон '{template_name}' сохранен.", reply_markup=get_main_menu())
#         logger.info(f"Template '{template_name}' saved for user {user_id}")

#     @dp.callback_query_handler(lambda c: c.data.startswith("use_template_"))
#     async def use_template_button(callback_query: types.CallbackQuery):
#         template_name = callback_query.data.replace("use_template_", "")
#         user_id = callback_query.from_user.id
#         if user_id in templates and template_name in templates[user_id]:
#             messages = templates[user_id][template_name]
#             if user_id not in window.user_states:
#                 window.user_states[user_id] = UserState()
#             window.user_states[user_id].messages = messages
#             await callback_query.message.answer(f"✅ Загружен шаблон '{template_name}'.", reply_markup=get_main_menu())
#             logger.info(f"Template '{template_name}' loaded for user {user_id}")
#         else:
#             await callback_query.message.answer("❌ Шаблон не найден.", reply_markup=get_main_menu())
#             logger.error(f"Template {template_name} not found for user {user_id}")
#         await callback_query.answer()

#     @dp.callback_query_handler(lambda c: c.data == "back" or c.data == "back_from_account_selection", state="*")
#     async def back_button(callback_query: types.CallbackQuery, state: FSMContext):
#         await state.finish()
#         await callback_query.message.answer("⬅ Главное меню:", reply_markup=get_main_menu())
#         await callback_query.answer()

#     try:
#         if not await validate_bot_token(bot):
#             logger.critical("Invalid bot token.")
#             return
#         logger.info("Starting Telegram bot polling...")
#         bot_polling_task = asyncio.create_task(dp.start_polling())
#         await bot_polling_task
#     except asyncio.CancelledError:
#         logger.info("Bot polling task cancelled.")
#     except Exception as e:
#         logger.critical(f"Error in bot polling: {e}")

# if __name__ == "__main__":
#     asyncio.run(start_bot_polling())
