import sys
import random
import logging
import asyncio
from telethon import TelegramClient
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError, PhoneNumberInvalidError, FloodWaitError
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.exceptions import Unauthorized
import qrcode
import os

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

EMOJIS = ["🙂", "🙃", "😉", "😊", "😇", "🤗", "😎", "🤩", "🤔", "😺"]
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
API_TOKEN = os.environ['API_TOKEN']
# API_ID = 20121768
# API_HASH = '5d579eeab57590fd3e68c6e68ba1249c'
# API_TOKEN = os.environ['7725000275:AAGfzf_M0sj8RqQEKKsg6sUUybxBpG0A_tA']

class UserState:
    def __init__(self):
        self.clients = {}  # phone -> {'client': client, 'user': user}
        self.selected_chats = []
        self.messages = []
        self.delay = 60
        self.repeats = 1
        self.stop_flag = False
        self.spam_tasks = []

class TelegramSpammer:
    def __init__(self):
        self.clients = {}
        self.user_states = {}
        self.bot_sessions = {}
        self.templates = {}

async def connect_account(self, phone, user_id, qr_callback=None, error_callback=None):
    if not phone.startswith('+'):
        if error_callback:
            await error_callback(f"Invalid phone format: {phone}")
        logger.error(f"Invalid phone format: {phone}")
        return False
    try:
        if phone in self.clients:
            client = self.clients[phone]
        else:
            client = TelegramClient(MemorySession(), API_ID, API_HASH)
            self.clients[phone] = client
        await client.connect()
        if not await client.is_user_authorized():
            qr_login = await client.qr_login()
            qr = qrcode.QRCode()
            qr.add_data(qr_login.url)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white")
            qr_path = f"qr_{phone}.png"
            try:
                qr_img.save(qr_path)
                if qr_callback:
                    await qr_callback(qr_path)
            except Exception as e:
                if error_callback:
                    await error_callback(f"Failed to save QR code: {e}")
                logger.error(f"Failed to save QR code for {phone}: {e}")
                return False
            try:
                await qr_login.wait(timeout=60)
            except SessionPasswordNeededError:
                if error_callback:
                    await error_callback("2FA password required")
                logger.error(f"2FA password required for {phone}")
                return False
            except asyncio.TimeoutError:
                if error_callback:
                    await error_callback("QR login timeout")
                logger.error(f"QR login timeout for {phone}")
                return False
            except PhoneNumberInvalidError:
                if error_callback:
                    await error_callback("Invalid phone number")
                logger.error(f"Invalid phone number: {phone}")
                return False
            finally:
                if os.path.exists(qr_path):
                    os.remove(qr_path)
        user = await client.get_me()
        if user_id not in self.user_states:
            self.user_states[user_id] = UserState()
        self.user_states[user_id].clients[phone] = {'client': client, 'user': user}
        logger.info(f"Account {phone} connected successfully for user {user_id}")
        return True
    except Exception as e:
        if error_callback:
            await error_callback(f"Failed to connect: {e}")
        logger.error(f"Failed to connect {phone}: {e}")
        return False


    async def load_chats(self, client, phone):
        chats = []
        try:
            async for dialog in client.iter_dialogs():
                if dialog.is_group or dialog.is_channel:
                    chats.append(dialog)
        except Exception as e:
            logger.error(f"Failed to load chats for {phone}: {e}")
        return chats

    async def send_message_to_chat(self, client, phone, chat, messages):
        try:
            if not client.is_connected():
                await client.connect()
                logger.warning(f"Client {phone} was disconnected, reconnected.")
            participants = await client.get_participants(chat, limit=10)
            mentions = [f"[{EMOJIS[i]}](tg://user?id={u.id})" for i, u in enumerate(participants) if u and u.id]
            text = random.choice(messages) + "\n\n" + " ".join(mentions)
            await client.send_message(chat, text, parse_mode='Markdown')
            logger.info(f"Message sent to {chat.name} using client {phone}")
        except Exception as e:
            logger.error(f"Error sending to {chat.name} using client {phone}: {e}")

    async def spam_for_account(self, client, phone, chats, user_id):
        user_state = self.user_states[user_id]
        for _ in range(user_state.repeats):
            if user_state.stop_flag:
                break
            for chat in chats:
                if user_state.stop_flag:
                    break
                try:
                    await asyncio.sleep(user_state.delay)
                    await self.send_message_to_chat(client, phone, chat, user_state.messages)
                except FloodWaitError as e:
                    logger.warning(f"Flood wait for {e.seconds} seconds for client {phone}")
                    await asyncio.sleep(e.seconds + 5)
                except Exception as e:
                    logger.error(f"Error in {chat.name} for client {phone}: {e}")
        logger.info(f"Spam cycle completed for client {phone}")

    async def start_spam(self, user_id):
        user_state = self.user_states.get(user_id, UserState())
        if not user_state.messages:
            logger.error(f"No messages provided for user {user_id}")
            return False
        if not user_state.selected_chats:
            logger.error(f"No chats selected for user {user_id}")
            return False
        if not user_state.clients:
            logger.error(f"No accounts selected for user {user_id}")
            return False
        user_state.stop_flag = False
        tasks = []
        for phone, data in user_state.clients.items():
            task = asyncio.create_task(self.spam_for_account(data['client'], phone, user_state.selected_chats, user_id))
            user_state.spam_tasks.append(task)
            tasks.append(task)
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(f"Spam completed for user {user_id}")
        return True

    def stop_spam(self, user_id):
        user_state = self.user_states.get(user_id, UserState())
        user_state.stop_flag = True
        for task in user_state.spam_tasks:
            if isinstance(task, asyncio.Task):
                task.cancel()
        user_state.spam_tasks = []
        logger.info(f"Spam stopped for user {user_id}")

    def get_chat_list(self, user_id):
        unique_chat_names = set()
        user_state = self.user_states.get(user_id, UserState())
        for phone, data in user_state.clients.items():
            loop = asyncio.get_event_loop()
            chats = loop.run_until_complete(self.load_chats(data['client'], phone))
            for chat in chats:
                unique_chat_names.add(chat.name)
        return sorted(list(unique_chat_names))

    def select_chats(self, names, user_id):
        user_state = self.user_states.get(user_id, UserState())
        user_state.selected_chats = []
        for phone, data in user_state.clients.items():
            loop = asyncio.get_event_loop()
            chats = loop.run_until_complete(self.load_chats(data['client'], phone))
            for chat in chats:
                if chat.name in names:
                    user_state.selected_chats.append(chat)
        user_state.selected_chats = list(set(user_state.selected_chats))
        logger.info(f"User {user_id} selected {len(user_state.selected_chats)} chats.")

    def set_messages(self, messages, user_id):
        if user_id not in self.user_states:
            self.user_states[user_id] = UserState()
        self.user_states[user_id].messages = messages
        logger.info(f"Messages set for user {user_id}: {messages}")

    def set_delay(self, delay, user_id):
        if user_id not in self.user_states:
            self.user_states[user_id] = UserState()
        self.user_states[user_id].delay = delay
        logger.info(f"Delay set to {delay} seconds for user {user_id}")

    def set_repeats(self, repeats, user_id):
        if user_id not in self.user_states:
            self.user_states[user_id] = UserState()
        self.user_states[user_id].repeats = repeats
        logger.info(f"Repeats set to {repeats} for user {user_id}")

    def get_status(self, user_id):
        user_state = self.user_states.get(user_id, UserState())
        active_accounts_count = len(user_state.clients)
        return (f"Messages: {len(user_state.messages)}, "
                f"Chats: {len(user_state.selected_chats)}, "
                f"Delay: {user_state.delay} sec, "
                f"Repeats: {user_state.repeats}, "
                f"Active accounts: {active_accounts_count}")

# Bot setup
storage = MemoryStorage()
bot_sessions = {}
templates = {}

class Form(StatesGroup):
    CONNECT = State()
    PASSWORD = State()
    SELECT_CHATS = State()
    MESSAGES = State()
    DELAY = State()
    REPEATS = State()
    SELECT_ACCOUNT = State()
    RENAME = State()
    TEMPLATE = State()

def get_main_menu():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📱 Add account", callback_data="connect"),
        InlineKeyboardButton("👤 Manage accounts", callback_data="manage_accounts"),
        InlineKeyboardButton("💬 Show chats", callback_data="chats"),
        InlineKeyboardButton("✅ Select chats", callback_data="select_chats"),
        InlineKeyboardButton("✍️ Set messages", callback_data="messages"),
        InlineKeyboardButton("📋 Message templates", callback_data="templates"),
        InlineKeyboardButton("⏳ Set delay", callback_data="delay"),
        InlineKeyboardButton("🔁 Set repeats", callback_data="repeats"),
        InlineKeyboardButton("🚀 Start spam", callback_data="select_account_for_spam"),
        InlineKeyboardButton("🛑 Stop", callback_data="stop"),
        InlineKeyboardButton("📊 Show status", callback_data="status")
    )
    return keyboard

def get_account_selection_menu(user_id):
    keyboard = InlineKeyboardMarkup(row_width=1)
    if user_id in bot_sessions and bot_sessions[user_id]:
        for phone, data in bot_sessions[user_id].items():
            name = data.get('name', phone)
            mark = "✅" if phone in spammer.user_states.get(user_id, UserState()).clients else ""
            keyboard.add(InlineKeyboardButton(f"{mark} Account: {name}", callback_data=f"toggle_spam_account_{phone}"))
    keyboard.add(InlineKeyboardButton("🚀 Start with selected", callback_data="start_selected_accounts_spam"))
    keyboard.add(InlineKeyboardButton("⬅ Back", callback_data="back_from_account_selection"))
    return keyboard

def get_manage_menu(user_id):
    keyboard = InlineKeyboardMarkup(row_width=1)
    if user_id in bot_sessions:
        for phone, data in bot_sessions[user_id].items():
            name = data.get('name', phone)
            keyboard.add(
                InlineKeyboardButton(f"{name}: Rename", callback_data=f"rename_{phone}"),
                InlineKeyboardButton(f"{name}: Delete", callback_data=f"delete_{phone}")
            )
    keyboard.add(InlineKeyboardButton("⬅ Back", callback_data="back"))
    return keyboard

def get_template_menu(user_id):
    keyboard = InlineKeyboardMarkup(row_width=1)
    if user_id in templates and templates[user_id]:
        for name in sorted(templates[user_id].keys()):
            keyboard.add(InlineKeyboardButton(f"Template: {name}", callback_data=f"use_template_{name}"))
    keyboard.add(
        InlineKeyboardButton("➕ Create new template", callback_data="new_template"),
        InlineKeyboardButton("⬅ Back", callback_data="back")
    )
    return keyboard

async def validate_bot_token(bot):
    try:
        await bot.get_me()
        logger.info("Bot token validated successfully.")
        return True
    except Unauthorized as e:
        logger.critical(f"Invalid bot token: {e}")
        return False
    except Exception as e:
        logger.error(f"Error validating bot token: {e}")
        return False

spammer = TelegramSpammer()

async def main():
    bot = Bot(token=API_TOKEN)
    dp = Dispatcher(bot, storage=MemoryStorage())

    @dp.message_handler(commands=['start', 'help'])
    async def start(message: types.Message):
        text = (
            "👋 *Telegram Spammer*\n"
            "Bot for sending messages.\n"
            "1. Add an account via QR code.\n"
            "2. Select chats and messages.\n"
            "3. Set repeats and start spamming!"
        )
        sent_msg = await message.answer(text, reply_markup=get_main_menu(), parse_mode="Markdown")
        try:
            await sent_msg.pin()
        except Exception as e:
            logger.error(f"Failed to pin message: {e}")

    @dp.callback_query_handler(lambda c: c.data == "connect")
    async def connect_button(callback_query: types.CallbackQuery):
        await Form.CONNECT.set()
        await callback_query.message.answer(
            "📱 Enter phone number.\nExample: +79991234567\nWe'll send a QR code.",
            reply_markup=get_main_menu()
        )
        await callback_query.answer()

    @dp.message_handler(state=Form.CONNECT)
    async def process_connect(message: types.Message, state: FSMContext):
        phone = message.text.strip()
        user_id = message.from_user.id
        if not phone.startswith('+') or len(phone) < 10:
            await message.reply("❌ Invalid format. Example: +79991234567.", reply_markup=get_main_menu())
            logger.error(f"Invalid phone format: {phone}")
            return
        async def qr_callback(qr_path):
            with open(qr_path, 'rb') as f:
                await message.reply_photo(f, caption=f"📱 Scan QR code for {phone} in Telegram.")
        async def error_callback(error):
            await message.reply(f"❌ Error: {error}", reply_markup=get_main_menu())
        success = await spammer.connect_account(phone, user_id, qr_callback, error_callback)
        if success:
            if user_id not in bot_sessions:
                bot_sessions[user_id] = {}
            bot_sessions[user_id][phone] = {'client': spammer.clients[phone], 'name': phone}
            await state.finish()
            await message.reply("✅ Account connected!", reply_markup=get_main_menu())
            logger.info(f"Account {phone} connected for user {user_id}")

    @dp.callback_query_handler(lambda c: c.data == "manage_accounts")
    async def manage_accounts_button(callback_query: types.CallbackQuery):
        user_id = callback_query.from_user.id
        if user_id not in bot_sessions or not bot_sessions[user_id]:
            await callback_query.message.answer("❌ No accounts.", reply_markup=get_main_menu())
        else:
            await callback_query.message.answer("👤 Manage accounts:", reply_markup=get_manage_menu(user_id))
        await callback_query.answer()

    @dp.callback_query_handler(lambda c: c.data.startswith("rename_"))
    async def rename_button(callback_query: types.CallbackQuery, state: FSMContext):
        phone = callback_query.data.replace("rename_", "")
        await Form.RENAME.set()
        await callback_query.message.answer(f"✏️ Enter new name for {phone}:", reply_markup=get_main_menu())
        async with state.proxy() as data:
            data['phone_to_rename'] = phone
        await callback_query.answer()

    @dp.message_handler(state=Form.RENAME)
    async def process_rename(message: types.Message, state: FSMContext):
        user_id = message.from_user.id
        new_name = message.text.strip()
        async with state.proxy() as data:
            phone = data.get('phone_to_rename')
        if phone and user_id in bot_sessions and phone in bot_sessions[user_id]:
            bot_sessions[user_id][phone]['name'] = new_name
            await message.reply(f"✅ Account {phone} renamed to: {new_name}", reply_markup=get_main_menu())
            logger.info(f"Account {phone} renamed to {new_name} for user {user_id}")
        else:
            await message.reply("❌ Failed to rename account.", reply_markup=get_main_menu())
            logger.error(f"Failed to rename account for user {user_id}, phone {phone}")
        await state.finish()

    @dp.callback_query_handler(lambda c: c.data.startswith("delete_"))
    async def delete_button(callback_query: types.CallbackQuery):
        phone = callback_query.data.replace("delete_", "")
        user_id = callback_query.from_user.id
        if user_id in bot_sessions and phone in bot_sessions[user_id]:
            client_to_delete = bot_sessions[user_id][phone]['client']
            try:
                await client_to_delete.disconnect()
                logger.info(f"Client {phone} disconnected.")
            except Exception as e:
                logger.warning(f"Error disconnecting client {phone}: {e}")
            del bot_sessions[user_id][phone]
            if user_id in spammer.user_states and phone in spammer.user_states[user_id].clients:
                del spammer.user_states[user_id].clients[phone]
            if phone in spammer.clients:
                del spammer.clients[phone]
            await callback_query.message.answer(f"🗑 Account {phone} deleted.", reply_markup=get_main_menu())
            logger.info(f"Account {phone} deleted for user {user_id}")
        else:
            await callback_query.message.answer("❌ Account not found.", reply_markup=get_main_menu())
            logger.error(f"Attempted to delete non-existent account {phone} for user {user_id}")
        await callback_query.answer()

    @dp.callback_query_handler(lambda c: c.data == "chats")
    async def show_chats_button(callback_query: types.CallbackQuery):
        user_id = callback_query.from_user.id
        chat_names = spammer.get_chat_list(user_id)
        if chat_names:
            response = "💬 Available chats:\n" + "\n".join(chat_names)
        else:
            response = "❌ No chats available. Connect account(s)."
        await callback_query.message.answer(response, reply_markup=get_main_menu())
        await callback_query.answer()

    @dp.callback_query_handler(lambda c: c.data == "select_chats")
    async def select_chats_button(callback_query: types.CallbackQuery, state: FSMContext):
        user_id = callback_query.from_user.id
        available_chats = spammer.get_chat_list(user_id)
        if not available_chats:
            await callback_query.message.answer("❌ No chats available.", reply_markup=get_main_menu())
            await callback_query.answer()
            return
        chat_map = {str(idx): chat_name for idx, chat_name in enumerate(available_chats)}
        async with state.proxy() as data:
            data['chat_map'] = chat_map
            data['selected_chat_names'] = []
        keyboard = InlineKeyboardMarkup(row_width=1)
        for idx, chat_name in chat_map.items():
            keyboard.add(InlineKeyboardButton(chat_name, callback_data=f"chat_select_{idx}"))
        keyboard.add(InlineKeyboardButton("✅ Done", callback_data="finish_chat"))
        await Form.SELECT_CHATS.set()
        await callback_query.message.answer("✅ Select chats:", reply_markup=keyboard)
        await callback_query.answer()

    @dp.callback_query_handler(lambda c: c.data.startswith("chat_select_"), state=Form.SELECT_CHATS)
    async def toggle_chat_selection(callback_query: types.CallbackQuery, state: FSMContext):
        idx = callback_query.data.replace("chat_select_", "")
        async with state.proxy() as data:
            chat_map = data.get('chat_map', {})
            selected_chat_names = data.get('selected_chat_names', [])
            if idx in chat_map:
                chat_name = chat_map[idx]
                if chat_name in selected_chat_names:
                    selected_chat_names.remove(chat_name)
                    mark = ""
                else:
                    selected_chat_names.append(chat_name)
                    mark = "✅ "
                data['selected_chat_names'] = selected_chat_names
            else:
                logger.error(f"Invalid chat index: {idx}")
                await callback_query.answer("❌ Error: chat not found.")
                return
        keyboard = InlineKeyboardMarkup(row_width=1)
        for idx_map, chat_name in chat_map.items():
            current_mark = "✅ " if chat_name in selected_chat_names else ""
            keyboard.add(InlineKeyboardButton(f"{current_mark}{chat_name}", callback_data=f"chat_select_{idx_map}"))
        keyboard.add(InlineKeyboardButton("✅ Done", callback_data="finish_chat"))
        await callback_query.message.edit_reply_markup(reply_markup=keyboard)
        await callback_query.answer(f"{mark}{chat_name}")

    @dp.callback_query_handler(lambda c: c.data == "finish_chat", state=Form.SELECT_CHATS)
    async def finalize_chat_selection(callback_query: types.CallbackQuery, state: FSMContext):
        user_id = callback_query.from_user.id
        async with state.proxy() as data:
            final_selected_chat_names = data.get('selected_chat_names', [])
        if final_selected_chat_names:
            spammer.select_chats(final_selected_chat_names, user_id)
            await callback_query.message.answer(f"✅ Selected {len(final_selected_chat_names)} chats.", reply_markup=get_main_menu())
            logger.info(f"Bot selected {len(final_selected_chat_names)} chats for user {user_id}")
        else:
            spammer.select_chats([], user_id)
            await callback_query.message.answer("❌ No chats selected.", reply_markup=get_main_menu())
            logger.info(f"No chats selected by user {user_id}")
        await state.finish()
        await callback_query.answer()

    @dp.callback_query_handler(lambda c: c.data == "messages")
    async def messages_button(callback_query: types.CallbackQuery):
        await Form.MESSAGES.set()
        await callback_query.message.answer("✍️ Enter messages, one per line:", reply_markup=get_main_menu())
        await callback_query.answer()

    @dp.message_handler(state=Form.MESSAGES)
    async def process_messages(message: types.Message, state: FSMContext):
        user_id = message.from_user.id
        messages = [m.strip() for m in message.text.splitlines() if m.strip()]
        if messages:
            spammer.set_messages(messages, user_id)
            await message.reply(f"✅ Saved {len(messages)} messages.", reply_markup=get_main_menu())
            logger.info(f"Messages set for user {user_id}: {messages}")
        else:
            await message.reply("❌ No messages provided.", reply_markup=get_main_menu())
            logger.warning(f"No messages provided by user {user_id}")
        await state.finish()

    @dp.callback_query_handler(lambda c: c.data == "delay")
    async def delay_button(callback_query: types.CallbackQuery):
        await Form.DELAY.set()
        user_id = callback_query.from_user.id
        delay = spammer.user_states.get(user_id, UserState()).delay
        await callback_query.message.answer(f"⏳ Enter delay (seconds, current: {delay}):", reply_markup=get_main_menu())
        await callback_query.answer()

    @dp.message_handler(state=Form.DELAY)
    async def process_delay(message: types.Message, state: FSMContext):
        user_id = message.from_user.id
        try:
            delay = int(message.text.strip())
            if 30 <= delay <= 600:
                spammer.set_delay(delay, user_id)
                await message.reply(f"✅ Delay set to {delay} seconds.", reply_markup=get_main_menu())
                logger.info(f"Delay set to {delay} seconds for user {user_id}")
            else:
                await message.reply("❌ Delay must be between 30 and 600 seconds.", reply_markup=get_main_menu())
                logger.warning(f"Invalid delay input: {delay} by user {user_id}")
        except ValueError:
            await message.reply("❌ Invalid format. Enter a number.", reply_markup=get_main_menu())
            logger.warning(f"Non-numeric delay input: {message.text} by user {user_id}")
        await state.finish()

    @dp.callback_query_handler(lambda c: c.data == "repeats")
    async def repeats_button(callback_query: types.CallbackQuery):
        await Form.REPEATS.set()
        user_id = callback_query.from_user.id
        repeats = spammer.user_states.get(user_id, UserState()).repeats
        await callback_query.message.answer(f"🔁 Enter number of repeats (current: {repeats}):", reply_markup=get_main_menu())
        await callback_query.answer()

    @dp.message_handler(state=Form.REPEATS)
    async def process_repeats(message: types.Message, state: FSMContext):
        user_id = message.from_user.id
        try:
            repeats = int(message.text.strip())
            if 1 <= repeats <= 100:
                spammer.set_repeats(repeats, user_id)
                await message.reply(f"✅ Set {repeats} repeats.", reply_markup=get_main_menu())
                logger.info(f"Repeats set to {repeats} for user {user_id}")
            else:
                await message.reply("❌ Repeats must be between 1 and 100.", reply_markup=get_main_menu())
                logger.warning(f"Invalid repeats input: {repeats} by user {user_id}")
        except ValueError:
            await message.reply("❌ Invalid format. Enter a number.", reply_markup=get_main_menu())
            logger.warning(f"Non-numeric repeats input: {message.text} by user {user_id}")
        await state.finish()

    @dp.callback_query_handler(lambda c: c.data == "select_account_for_spam")
    async def select_account_for_spam_button(callback_query: types.CallbackQuery):
        user_id = callback_query.from_user.id
        if user_id not in bot_sessions or not bot_sessions[user_id]:
            await callback_query.message.answer("❌ No accounts.", reply_markup=get_main_menu())
        else:
            await Form.SELECT_ACCOUNT.set()
            await callback_query.message.answer("✅ Select accounts for spamming:", reply_markup=get_account_selection_menu(user_id))
        await callback_query.answer()

    @dp.callback_query_handler(lambda c: c.data.startswith("toggle_spam_account_"), state=Form.SELECT_ACCOUNT)
    async def toggle_spam_account(callback_query: types.CallbackQuery):
        phone = callback_query.data.replace("toggle_spam_account_", "")
        user_id = callback_query.from_user.id
        if user_id not in spammer.user_states:
            spammer.user_states[user_id] = UserState()
        if phone in spammer.user_states[user_id].clients:
            del spammer.user_states[user_id].clients[phone]
            await callback_query.answer(f"Account {phone} removed from spam.")
        else:
            if user_id in bot_sessions and phone in bot_sessions[user_id]:
                spammer.user_states[user_id].clients[phone] = bot_sessions[user_id][phone]
                await callback_query.answer(f"Account {phone} selected for spam.")
            else:
                await callback_query.answer(f"Account {phone} not found.")
                logger.warning(f"Attempted to select non-existent account {phone} for user {user_id}")
        await callback_query.message.edit_reply_markup(reply_markup=get_account_selection_menu(user_id))

    @dp.callback_query_handler(lambda c: c.data == "start_selected_accounts_spam", state=Form.SELECT_ACCOUNT)
    async def start_selected_accounts_spam(callback_query: types.CallbackQuery, state: FSMContext):
        user_id = callback_query.from_user.id
        success = await spammer.start_spam(user_id)
        if success:
            await callback_query.message.answer("🚀 Spam started!", reply_markup=get_main_menu())
            logger.info(f"Spam started for user {user_id}")
        else:
            await callback_query.message.answer("❌ Failed to start spam.", reply_markup=get_main_menu())
            logger.error(f"Failed to start spam for user {user_id}")
        await state.finish()
        await callback_query.answer()

    @dp.callback_query_handler(lambda c: c.data == "stop")
    async def stop_button(callback_query: types.CallbackQuery):
        user_id = callback_query.from_user.id
        spammer.stop_spam(user_id)
        await callback_query.message.answer("🛑 Spam stopped.", reply_markup=get_main_menu())
        await callback_query.answer()

    @dp.callback_query_handler(lambda c: c.data == "status")
    async def status_button(callback_query: types.CallbackQuery):
        user_id = callback_query.from_user.id
        status_text = spammer.get_status(user_id)
        await callback_query.message.answer(f"📊 Status:\n{status_text}", reply_markup=get_main_menu())
        await callback_query.answer()

    @dp.callback_query_handler(lambda c: c.data == "templates")
    async def templates_button(callback_query: types.CallbackQuery):
        user_id = callback_query.from_user.id
        if user_id not in templates or not templates[user_id]:
            await callback_query.message.answer("📋 No templates.", reply_markup=get_template_menu(user_id))
        else:
            template_list = "\n".join(f"{i+1}. {name}" for i, name in enumerate(sorted(templates[user_id].keys())))
            await callback_query.message.answer(f"📋 Templates:\n{template_list}", reply_markup=get_template_menu(user_id))
        await callback_query.answer()

    @dp.callback_query_handler(lambda c: c.data == "new_template")
    async def new_template_button(callback_query: types.CallbackQuery):
        await Form.TEMPLATE.set()
        await callback_query.message.answer(
            "📋 Enter template:\nFirst line — template name.\nOther lines — messages.",
            reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅ Cancel", callback_data="back"))
        )
        await callback_query.answer()

    @dp.message_handler(state=Form.TEMPLATE)
    async def process_new_template(message: types.Message, state: FSMContext):
        user_id = message.from_user.id
        lines = [m.strip() for m in message.text.splitlines() if m.strip()]
        if len(lines) < 2:
            await message.reply("❌ Template must have a name and message.", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅ Cancel", callback_data="back")))
            return
        template_name = lines[0]
        template_messages = lines[1:]
        if user_id not in templates:
            templates[user_id] = {}
        if template_name in templates[user_id]:
            await message.reply(f"❌ Template '{template_name}' already exists.", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅ Cancel", callback_data="back")))
            return
        templates[user_id][template_name] = template_messages
        await state.finish()
        await message.reply(f"✅ Template '{template_name}' saved.", reply_markup=get_main_menu())
        logger.info(f"Template '{template_name}' saved for user {user_id}")

    @dp.callback_query_handler(lambda c: c.data.startswith("use_template_"))
    async def use_template_button(callback_query: types.CallbackQuery):
        template_name = callback_query.data.replace("use_template_", "")
        user_id = callback_query.from_user.id
        if user_id in templates and template_name in templates[user_id]:
            messages = templates[user_id][template_name]
            spammer.set_messages(messages, user_id)
            await callback_query.message.answer(f"✅ Loaded template '{template_name}'.", reply_markup=get_main_menu())
            logger.info(f"Template '{template_name}' loaded for user {user_id}")
        else:
            await callback_query.message.answer("❌ Template not found.", reply_markup=get_main_menu())
            logger.error(f"Template {template_name} not found for user {user_id}")
        await callback_query.answer()

    @dp.callback_query_handler(lambda c: c.data == "back" or c.data == "back_from_account_selection", state="*")
    async def back_button(callback_query: types.CallbackQuery, state: FSMContext):
        await state.finish()
        await callback_query.message.answer("⬅ Main menu:", reply_markup=get_main_menu())
        await callback_query.answer()

    try:
        if not await validate_bot_token(bot):
            logger.critical("Invalid bot token.")
            return
        logger.info("Starting Telegram bot polling...")
        await dp.start_polling()
    except Exception as e:
        logger.critical(f"Error in bot polling: {e}")
    finally:
        for phone, client in list(spammer.clients.items()):
            try:
                await client.disconnect()
                logger.info(f"Client {phone} disconnected.")
            except Exception as e:
                logger.warning(f"Error disconnecting client {phone}: {e}")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Application shutdown by user.")
    finally:
        loop.close()