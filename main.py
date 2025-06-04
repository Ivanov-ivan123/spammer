
import sys
import random
import logging
import asyncio
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QSpinBox, QMessageBox, QInputDialog,
    QListWidget, QListWidgetItem, QAbstractItemView, QHBoxLayout, QScrollArea, QCheckBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
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
import qasync

# Логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

EMOJIS = ["🙂", "🙃", "😉", "😊", "😇", "🤗", "😎", "🤩", "🤔", "😺"]
API_ID = 20121768
API_HASH = '5d579eeab57590fd3e68c6e68ba1249c'
API_TOKEN = '7725000275:AAGfzf_M0sj8RqQEKKsg6sUUybxBpG0A_tA'

class UserState:
    def __init__(self):
        self.clients = {}  # phone -> {'client': client, 'user': user}
        self.selected_chats = []
        self.messages = []
        self.delay = 60
        self.repeats = 1  # Количество повторов по умолчанию
        self.stop_flag = False
        self.spam_tasks = []  # Храним asyncio.Task

class AccountUI(QWidget):
    def __init__(self, title):
        super().__init__()
        self.title = title
        self.select_checkbox = QCheckBox("Использовать для рассылки")
        self.select_checkbox.setToolTip("Отметьте для спама с этого аккаунта")
        self.select_checkbox.setEnabled(False)
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("Введите номер телефона")
        self.connect_button = QPushButton("📱 Подключить (QR-код)")
        self.status_label = QLabel("Статус: Не подключен")
        self.status_label.setFont(QFont("Arial", 10))
        self.chat_list = QListWidget()
        self.chat_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.chat_list.setMaximumHeight(200)
        self.layout = QVBoxLayout()
        for w in [self.select_checkbox, self.phone_input, self.connect_button, self.status_label, self.chat_list]:
            self.layout.addWidget(w)
        self.setLayout(self.layout)
        self.client = None

    def set_connected(self):
        self.status_label.setText("Статус: Подключен ✅")
        self.connect_button.setEnabled(False)
        self.select_checkbox.setEnabled(True)

class TelegramSpammer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Рассылка в Telegram")
        self.resize(1100, 750)
        self.accounts = []
        self.clients = {}
        self.user_states = {}
        self.accounts_widget = QWidget()
        self.accounts_layout = QHBoxLayout(self.accounts_widget)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.accounts_widget)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(300)
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.scroll_area)
        self.add_account_button = QPushButton("➕ Новый аккаунт")
        main_layout.addWidget(self.add_account_button)
        self.add_account()
        main_layout.addWidget(QLabel("Сообщения для рассылки:"))
        self.message_box = QTextEdit()
        self.message_box.setPlaceholderText("Пример:\nВакансия программиста!\nЗвоните в Telegram!")
        main_layout.addWidget(self.message_box)
        settings_layout = QHBoxLayout()
        delay_layout = QHBoxLayout()
        delay_layout.addWidget(QLabel("Задержка (секунд):"))
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(30, 600)
        self.delay_spin.setValue(60)
        delay_layout.addWidget(self.delay_spin)
        repeats_layout = QHBoxLayout()
        repeats_layout.addWidget(QLabel("Повторов:"))
        self.repeats_spin = QSpinBox()
        self.repeats_spin.setRange(1, 100)
        self.repeats_spin.setValue(1)
        repeats_layout.addWidget(self.repeats_spin)
        settings_layout.addLayout(delay_layout)
        settings_layout.addLayout(repeats_layout)
        main_layout.addLayout(settings_layout)
        buttons_layout = QHBoxLayout()
        self.start_button = QPushButton("🚀 Начать рассылку")
        self.start_button.setEnabled(False)
        self.stop_button = QPushButton("🛑 Стоп")
        self.stop_button.setEnabled(False)
        self.reset_button = QPushButton("🗑 Сбросить")
        buttons_layout.addWidget(self.start_button)
        buttons_layout.addWidget(self.stop_button)
        buttons_layout.addWidget(self.reset_button)
        main_layout.addLayout(buttons_layout)
        self.reset_button.clicked.connect(self.reset_all)
        self.start_button.clicked.connect(self.start_spam)
        self.stop_button.clicked.connect(self.stop_spam)
        self.add_account_button.clicked.connect(self.add_account)
        self.setLayout(main_layout)

    def add_account(self):
        account_ui = AccountUI(f"Аккаунт {len(self.accounts) + 1}")
        account_ui.connect_button.clicked.connect(lambda: asyncio.ensure_future(self.connect_account(account_ui)))
        self.accounts.append(account_ui)
        self.accounts_layout.addWidget(account_ui)

    async def connect_account(self, account_ui: AccountUI):
        phone = account_ui.phone_input.text().strip()
        if not phone.startswith('+'):
            QMessageBox.warning(self, "Ошибка", "Введите номер с кодом страны, например, +79991234567.")
            logger.error(f"Invalid phone format: {phone}")
            return
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
                except Exception as e:
                    QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить QR-код: {e}")
                    logger.error(f"Failed to save QR code for {phone}: {e}")
                    return
                QMessageBox.information(self, "QR-код", f"QR-код сохранён как {qr_path}. Отсканируйте в Telegram.")
                try:
                    await qr_login.wait(timeout=60)
                except SessionPasswordNeededError:
                    pwd, ok = QInputDialog.getText(self, "Пароль 2FA", f"Введите пароль 2FA для {phone}:")
                    if ok and pwd:
                        await client.sign_in(password=pwd)
                    else:
                        QMessageBox.warning(self, "Ошибка", "Пароль 2FA обязателен.")
                        logger.error(f"2FA password not provided for {phone}")
                        return
                except asyncio.TimeoutError:
                    QMessageBox.warning(self, "Ошибка", "Время ожидания QR-кода истекло.")
                    logger.error(f"QR login timeout for {phone}")
                    return
                except PhoneNumberInvalidError:
                    QMessageBox.warning(self, "Ошибка", "Неверный номер телефона.")
                    logger.error(f"Invalid phone number: {phone}")
                    return
                finally:
                    if os.path.exists(qr_path):
                        os.remove(qr_path)
            account_ui.client = client
            account_ui.set_connected()
            await self.load_chats(account_ui)
            self.check_ready()
            QMessageBox.information(self, "Успех", f"Аккаунт {phone} подключен! ✅")
            logger.info(f"Account {phone} connected successfully")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось подключить: {e}")
            logger.error(f"Failed to connect {phone}: {e}")

    async def load_chats(self, account_ui: AccountUI):
        account_ui.chat_list.clear()
        try:
            async for dialog in account_ui.client.iter_dialogs():
                if dialog.is_group or dialog.is_channel:
                    item = QListWidgetItem(dialog.name)
                    item.setData(Qt.UserRole, dialog)
                    account_ui.chat_list.addItem(item)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить чаты: {e}")
            logger.error(f"Failed to load chats for account {account_ui.phone_input.text()}: {e}")

    def check_ready(self):
        if any(acc.client and acc.select_checkbox.isEnabled() for acc in self.accounts):
            self.start_button.setEnabled(True)

    def stop_spam(self):
        for user_id in self.user_states:
            self.user_states[user_id].stop_flag = True
            for task in self.user_states[user_id].spam_tasks:
                if isinstance(task, asyncio.Task):
                    task.cancel()
            self.user_states[user_id].spam_tasks = []
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        logger.info("Spam stopped for all users")

    def reset_all(self):
        for user_id in self.user_states:
            self.user_states[user_id].stop_flag = True
            for task in self.user_states[user_id].spam_tasks:
                if isinstance(task, asyncio.Task):
                    task.cancel()
            self.user_states[user_id].selected_chats = []
            self.user_states[user_id].messages = []
            self.user_states[user_id].repeats = 1
            self.user_states[user_id].spam_tasks = []
        self.message_box.clear()
        self.delay_spin.setValue(60)
        self.repeats_spin.setValue(1)
        for acc in self.accounts:
            acc.client = None
            acc.status_label.setText("Статус: Не подключен")
            acc.connect_button.setEnabled(True)
            acc.chat_list.clear()
            acc.select_checkbox.setChecked(False)
            acc.select_checkbox.setEnabled(False)
        self.clients.clear()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        QMessageBox.information(self, "Сброс", "Все настройки сброшены! ✅")
        logger.info("All settings reset")

    async def send_message_to_chat(self, client: TelegramClient, phone: str, chat, messages: list):
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

    async def start_spam(self):
        messages = [m.strip() for m in self.message_box.toPlainText().splitlines() if m.strip()]
        delay = self.delay_spin.value()
        repeats = self.repeats_spin.value()
        selected_accounts = [acc for acc in self.accounts if acc.client and acc.select_checkbox.isChecked()]
        if not messages:
            QMessageBox.warning(self, "Ошибка", "Введите сообщения для рассылки.")
            logger.error("No messages provided for spam")
            return
        if not selected_accounts:
            QMessageBox.warning(self, "Ошибка", "Выберите хотя бы один аккаунт для рассылки.")
            logger.error("No accounts selected for spam")
            return
        has_selected_chats = False
        for account_ui in selected_accounts:
            if account_ui.chat_list.selectedItems():
                has_selected_chats = True
                break
        if not has_selected_chats:
            QMessageBox.warning(self, "Ошибка", "Выберите чаты для рассылки.")
            logger.error("No chats selected")
            return
        self.stop_button.setEnabled(True)
        self.start_button.setEnabled(False)
        tasks = []
        for account_ui in selected_accounts:
            chats = [item.data(Qt.UserRole) for item in account_ui.chat_list.selectedItems()]
            if chats:
                user_id = "UI"
                if user_id not in self.user_states:
                    self.user_states[user_id] = UserState()
                self.user_states[user_id].messages = messages
                self.user_states[user_id].delay = delay
                self.user_states[user_id].repeats = repeats
                self.user_states[user_id].stop_flag = False
                task = asyncio.create_task(self.spam_for_account(account_ui.client, account_ui.phone_input.text(), chats, user_id))
                self.user_states[user_id].spam_tasks.append(task)
                tasks.append(task)
        await asyncio.gather(*tasks, return_exceptions=True)
        if not self.user_states.get("UI", UserState()).stop_flag:
            QMessageBox.information(self, "Готово", "Рассылка завершена! ✅")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

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

    def get_chat_list(self):
        unique_chat_names = set()
        for acc in self.accounts:
            if acc.client:
                for i in range(acc.chat_list.count()):
                    unique_chat_names.add(acc.chat_list.item(i).text())
        return sorted(list(unique_chat_names))

    def select_chats(self, names, user_id="UI"):
        if user_id not in self.user_states:
            self.user_states[user_id] = UserState()
        self.user_states[user_id].selected_chats = []
        for acc in self.accounts:
            if acc.client:
                acc.chat_list.clearSelection()
                for i in range(acc.chat_list.count()):
                    item = acc.chat_list.item(i)
                    if item.text() in names:
                        item.setSelected(True)
                        self.user_states[user_id].selected_chats.append(item.data(Qt.UserRole))
        self.user_states[user_id].selected_chats = list(set(self.user_states[user_id].selected_chats))
        logger.info(f"User {user_id} selected {len(self.user_states[user_id].selected_chats)} chats.")

    def set_messages(self, messages, user_id="UI"):
        if user_id not in self.user_states:
            self.user_states[user_id] = UserState()
        self.user_states[user_id].messages = messages
        if user_id == "UI":
            self.message_box.setText("\n".join(messages))

    def set_delay(self, delay, user_id="UI"):
        if user_id not in self.user_states:
            self.user_states[user_id] = UserState()
        self.user_states[user_id].delay = delay
        if user_id == "UI":
            self.delay_spin.setValue(delay)

    def set_repeats(self, repeats, user_id="UI"):
        if user_id not in self.user_states:
            self.user_states[user_id] = UserState()
        self.user_states[user_id].repeats = repeats
        if user_id == "UI":
            self.repeats_spin.setValue(repeats)

    def get_status(self, user_id="UI"):
        user_state = self.user_states.get(user_id, UserState())
        active_accounts_count = sum(1 for acc in self.accounts if acc.client and acc.select_checkbox.isChecked())
        return (f"Сообщений: {len(user_state.messages)}, "
                f"Чатов: {len(user_state.selected_chats)}, "
                f"Задержка: {user_state.delay} сек., "
                f"Повторов: {user_state.repeats}, "
                f"Активных аккаунтов: {active_accounts_count}")

    async def start_spam_from_bot(self, clients_to_use, user_id):
        if user_id not in self.user_states:
            self.user_states[user_id] = UserState()
        user_state = self.user_states[user_id]
        if not user_state.messages:
            logger.error(f"Cannot start spam for user {user_id}: no messages set.")
            return False
        if not user_state.selected_chats:
            logger.error(f"Cannot start spam for user {user_id}: no chats selected.")
            return False
        user_state.stop_flag = False
        tasks = []
        for client_data in clients_to_use:
            task = asyncio.create_task(self.spam_for_account(client_data['client'], client_data['phone'], user_state.selected_chats, user_id))
            user_state.spam_tasks.append(task)
            tasks.append(task)
        if not tasks:
            logger.error(f"No spamming tasks created for user {user_id}.")
            return False
        asyncio.create_task(self.run_tasks(tasks, user_id))
        logger.info(f"Bot-initiated spam started for user {user_id} with {len(tasks)} accounts.")
        return True

    async def run_tasks(self, tasks, user_id):
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"Error running tasks for user {user_id}: {e}")
        logger.info(f"All bot-initiated spam tasks completed for user {user_id}.")

    async def connect_account_bot(self, client, phone, user_id, name=None):
        try:
            user = await client.get_me()
            self.clients[phone] = client
            if user_id not in self.user_states:
                self.user_states[user_id] = UserState()
            self.user_states[user_id].clients[phone] = {'client': client, 'user': user}
            existing_account_ui = None
            for acc in self.accounts:
                if acc.phone_input.text() == phone:
                    existing_account_ui = acc
                    break
            if existing_account_ui:
                existing_account_ui.client = client
                existing_account_ui.set_connected()
                await self.load_chats(existing_account_ui)
                self.check_ready()
                logger.info(f"Bot re-connected existing UI account for {phone}")
            else:
                self.add_account()
                new_account_ui = self.accounts[-1]
                new_account_ui.phone_input.setText(phone)
                new_account_ui.client = client
                new_account_ui.set_connected()
                await self.load_chats(new_account_ui)
                self.check_ready()
                logger.info(f"Bot connected new UI account for {phone}")
        except Exception as e:
            logger.error(f"Error connecting bot account {phone} for user {user_id}: {e}")

# Бот
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
        InlineKeyboardButton("📱 Добавить аккаунт", callback_data="connect"),
        InlineKeyboardButton("👤 Управление аккаунтами", callback_data="manage_accounts"),
        InlineKeyboardButton("💬 Показать чаты", callback_data="chats"),
        InlineKeyboardButton("✅ Выбрать чаты", callback_data="select_chats"),
        InlineKeyboardButton("✍️ Написать сообщения", callback_data="messages"),
        InlineKeyboardButton("📋 Шаблоны сообщений", callback_data="templates"),
        InlineKeyboardButton("⏳ Установить задержку", callback_data="delay"),
        InlineKeyboardButton("🔁 Установить повторы", callback_data="repeats"),
        InlineKeyboardButton("🚀 Начать рассылку", callback_data="select_account_for_spam"),
        InlineKeyboardButton("🛑 Остановить", callback_data="stop"),
        InlineKeyboardButton("📊 Показать статус", callback_data="status")
    )
    return keyboard

def get_account_selection_menu(user_id):
    keyboard = InlineKeyboardMarkup(row_width=1)
    if user_id in bot_sessions and bot_sessions[user_id]:
        for phone, data in bot_sessions[user_id].items():
            name = data.get('name', phone)
            mark = "✅" if phone in window.user_states.get(user_id, UserState()).clients else ""
            keyboard.add(InlineKeyboardButton(f"{mark} Аккаунт: {name}", callback_data=f"toggle_spam_account_{phone}"))
    keyboard.add(InlineKeyboardButton("🚀 Запустить с выбранных", callback_data="start_selected_accounts_spam"))
    keyboard.add(InlineKeyboardButton("⬅ Назад", callback_data="back_from_account_selection"))
    return keyboard

def get_manage_menu(user_id):
    keyboard = InlineKeyboardMarkup(row_width=1)
    if user_id in bot_sessions:
        for phone, data in bot_sessions[user_id].items():
            name = data.get('name', phone)
            keyboard.add(
                InlineKeyboardButton(f"{name}: Переименовать", callback_data=f"rename_{phone}"),
                InlineKeyboardButton(f"{name}: Удалить", callback_data=f"delete_{phone}")
            )
    keyboard.add(InlineKeyboardButton("⬅ Назад", callback_data="back"))
    return keyboard

def get_template_menu(user_id):
    keyboard = InlineKeyboardMarkup(row_width=1)
    if user_id in templates and templates[user_id]:
        for name in sorted(templates[user_id].keys()):
            keyboard.add(InlineKeyboardButton(f"Шаблон: {name}", callback_data=f"use_template_{name}"))
    keyboard.add(
        InlineKeyboardButton("➕ Создать новый шаблон", callback_data="new_template"),
        InlineKeyboardButton("⬅ Назад", callback_data="back")
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

window = None
bot_polling_task = None

def main():
    global window, bot_polling_task
    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = TelegramSpammer()
    window.show()

    async def start_bot_polling():
        global bot_polling_task
        bot = Bot(token=API_TOKEN)
        dp = Dispatcher(bot, storage=MemoryStorage())

        @dp.message_handler(commands=['start', 'help'])
        async def start(message: types.Message):
            text = (
                "👋 *Рассылка в Telegram*\n"
                "Бот для рассылки сообщений.\n"
                "1. Добавь аккаунт через QR-код.\n"
                "2. Выбери чаты и сообщения.\n"
                "3. Укажи повторы и запусти рассылку!"
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
                "📱 Введите номер телефона.\nПример: +79991234567\nМы отправим QR-код.",
                reply_markup=get_main_menu()
            )
            await callback_query.answer()

        @dp.message_handler(state=Form.CONNECT)
        async def process_connect(message: types.Message, state: FSMContext):
            phone = message.text.strip()
            user_id = message.from_user.id
            if not phone.startswith('+') or len(phone) < 10:
                await message.reply("❌ Неверный формат. Пример: +79991234567.", reply_markup=get_main_menu())
                logger.error(f"Invalid phone format: {phone}")
                return
            try:
                client = TelegramClient(MemorySession(), API_ID, API_HASH)
                await client.connect()
                if await client.is_user_authorized():
                    if user_id not in bot_sessions:
                        bot_sessions[user_id] = {}
                    bot_sessions[user_id][phone] = {'client': client, 'name': phone}
                    await window.connect_account_bot(client, phone, user_id)
                    await state.finish()
                    await message.reply("✅ Аккаунт подключен!", reply_markup=get_main_menu())
                    logger.info(f"Account {phone} already authorized for user {user_id}")
                    return
                qr_login = await client.qr_login()
                qr = qrcode.QRCode()
                qr.add_data(qr_login.url)
                qr.make(fit=True)
                qr_img = qr.make_image(fill_color="black", back_color="white")
                qr_path = f"qr_{phone}.png"
                try:
                    qr_img.save(qr_path)
                except Exception as e:
                    await message.reply(f"❌ Ошибка создания QR-кода: {e}", reply_markup=get_main_menu())
                    logger.error(f"Failed to save QR code for {phone}: {e}")
                    await state.finish()
                    return
                try:
                    with open(qr_path, 'rb') as f:
                        await message.reply_photo(f, caption=f"📱 Отсканируйте QR-код для {phone} в Telegram.")
                    await qr_login.wait(timeout=60)
                    if user_id not in bot_sessions:
                        bot_sessions[user_id] = {}
                    bot_sessions[user_id][phone] = {'client': client, 'name': phone}
                    await window.connect_account_bot(client, phone, user_id)
                    await state.finish()
                    await message.reply("✅ Аккаунт подключен!", reply_markup=get_main_menu())
                    logger.info(f"Account {phone} connected via QR for user {user_id}")
                except SessionPasswordNeededError:
                    await Form.PASSWORD.set()
                    async with state.proxy() as data:
                        data['client'] = client
                        data['phone'] = phone
                    await message.reply("🔒 Введите пароль 2FA:", reply_markup=get_main_menu())
                except asyncio.TimeoutError:
                    await message.reply("❌ Время ожидания QR-кода истекло.", reply_markup=get_main_menu())
                    logger.error(f"QR login timeout for {phone} for user {user_id}")
                    await state.finish()
                except PhoneNumberInvalidError:
                    await message.reply("❌ Неверный номер телефона.", reply_markup=get_main_menu())
                    logger.error(f"Invalid phone number: {phone} for user {user_id}")
                    await state.finish()
                finally:
                    if os.path.exists(qr_path):
                        os.remove(qr_path)
            except Exception as e:
                await message.reply(f"❌ Ошибка QR-кода: {e}", reply_markup=get_main_menu())
                logger.error(f"QR login error for {phone} for user {user_id}: {e}")
                await state.finish()

        @dp.message_handler(state=Form.PASSWORD)
        async def process_password(message: types.Message, state: FSMContext):
            user_id = message.from_user.id
            async with state.proxy() as data:
                client = data.get('client')
                phone = data.get('phone')
            if not client or not phone:
                await message.reply("❌ Сессия не найдена.", reply_markup=get_main_menu())
                logger.error(f"Session not found for 2FA for user {user_id}")
                await state.finish()
                return
            password = message.text.strip()
            try:
                await client.sign_in(password=password)
                if user_id not in bot_sessions:
                    bot_sessions[user_id] = {}
                bot_sessions[user_id][phone] = {'client': client, 'name': phone}
                await window.connect_account_bot(client, phone, user_id)
                await state.finish()
                await message.reply("✅ Аккаунт подключен!", reply_markup=get_main_menu())
                logger.info(f"Account {phone} connected with 2FA for user {user_id}")
            except Exception as e:
                await message.reply(f"❌ Ошибка входа: {e}", reply_markup=get_main_menu())
                logger.error(f"2FA login error for {phone} for user {user_id}: {e}")
                await state.finish()

        @dp.callback_query_handler(lambda c: c.data == "manage_accounts")
        async def manage_accounts_button(callback_query: types.CallbackQuery):
            user_id = callback_query.from_user.id
            if user_id not in bot_sessions or not bot_sessions[user_id]:
                await callback_query.message.answer("❌ Нет аккаунтов.", reply_markup=get_main_menu())
            else:
                await callback_query.message.answer("👤 Управление аккаунтами:", reply_markup=get_manage_menu(user_id))
            await callback_query.answer()

        @dp.callback_query_handler(lambda c: c.data.startswith("rename_"))
        async def rename_button(callback_query: types.CallbackQuery, state: FSMContext):
            phone = callback_query.data.replace("rename_", "")
            await Form.RENAME.set()
            await callback_query.message.answer(f"✏️ Введите новое имя для {phone}:", reply_markup=get_main_menu())
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
                await message.reply(f"✅ Аккаунт {phone} теперь называется: {new_name}", reply_markup=get_main_menu())
                logger.info(f"Account {phone} renamed to {new_name} for user {user_id}")
            else:
                await message.reply("❌ Не удалось переименовать аккаунт.", reply_markup=get_main_menu())
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
                if user_id in window.user_states and phone in window.user_states[user_id].clients:
                    del window.user_states[user_id].clients[phone]
                for acc_ui in window.accounts:
                    if acc_ui.phone_input.text() == phone:
                        acc_ui.client = None
                        acc_ui.status_label.setText("Статус: Не подключен")
                        acc_ui.connect_button.setEnabled(True)
                        acc_ui.chat_list.clear()
                        acc_ui.select_checkbox.setEnabled(False)
                        acc_ui.select_checkbox.setChecked(False)
                        break
                if phone in window.clients:
                    del window.clients[phone]
                await callback_query.message.answer(f"🗑 Аккаунт {phone} удален.", reply_markup=get_main_menu())
                logger.info(f"Account {phone} deleted for user {user_id}")
            else:
                await callback_query.message.answer("❌ Аккаунт не найден.", reply_markup=get_main_menu())
                logger.error(f"Attempted to delete non-existent account {phone} for user {user_id}")
            await callback_query.answer()

        @dp.callback_query_handler(lambda c: c.data == "chats")
        async def show_chats_button(callback_query: types.CallbackQuery):
            chat_names = window.get_chat_list()
            if chat_names:
                response = "💬 Доступные чаты:\n" + "\n".join(chat_names)
            else:
                response = "❌ Нет доступных чатов. Подключите аккаунт(ы)."
            await callback_query.message.answer(response, reply_markup=get_main_menu())
            await callback_query.answer()

        @dp.callback_query_handler(lambda c: c.data == "select_chats")
        async def select_chats_button(callback_query: types.CallbackQuery, state: FSMContext):
            available_chats = window.get_chat_list()
            user_id = callback_query.from_user.id
            if not available_chats:
                await callback_query.message.answer("❌ Нет доступных чатов.", reply_markup=get_main_menu())
                await callback_query.answer()
                return
            chat_map = {str(idx): chat_name for idx, chat_name in enumerate(available_chats)}
            async with state.proxy() as data:
                data['chat_map'] = chat_map
                data['selected_chat_names'] = []
            keyboard = InlineKeyboardMarkup(row_width=1)
            for idx, chat_name in chat_map.items():
                keyboard.add(InlineKeyboardButton(chat_name, callback_data=f"chat_select_{idx}"))
            keyboard.add(InlineKeyboardButton("✅ Готово", callback_data="finish_chat"))
            await Form.SELECT_CHATS.set()
            await callback_query.message.answer("✅ Выберите чаты:", reply_markup=keyboard)
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
                    await callback_query.answer("❌ Ошибка: чат не найден.")
                    return
            keyboard = InlineKeyboardMarkup(row_width=1)
            for idx_map, chat_name in chat_map.items():
                current_mark = "✅ " if chat_name in selected_chat_names else ""
                keyboard.add(InlineKeyboardButton(f"{current_mark}{chat_name}", callback_data=f"chat_select_{idx_map}"))
            keyboard.add(InlineKeyboardButton("✅ Готово", callback_data="finish_chat"))
            await callback_query.message.edit_reply_markup(reply_markup=keyboard)
            await callback_query.answer(f"{mark}{chat_name}")

        @dp.callback_query_handler(lambda c: c.data == "finish_chat", state=Form.SELECT_CHATS)
        async def finalize_chat_selection(callback_query: types.CallbackQuery, state: FSMContext):
            user_id = callback_query.from_user.id
            async with state.proxy() as data:
                final_selected_chat_names = data.get('selected_chat_names', [])
            if final_selected_chat_names:
                window.select_chats(final_selected_chat_names, user_id)
                await callback_query.message.answer(f"✅ Выбрано {len(final_selected_chat_names)} чатов.", reply_markup=get_main_menu())
                logger.info(f"Bot selected {len(final_selected_chat_names)} chats for user {user_id}")
            else:
                window.select_chats([], user_id)
                await callback_query.message.answer("❌ Чаты не выбраны.", reply_markup=get_main_menu())
                logger.info(f"No chats selected by user {user_id}")
            await state.finish()
            await callback_query.answer()

        @dp.callback_query_handler(lambda c: c.data == "messages")
        async def messages_button(callback_query: types.CallbackQuery):
            await Form.MESSAGES.set()
            await callback_query.message.answer("✍️ Введите сообщения, каждое с новой строкой:", reply_markup=get_main_menu())
            await callback_query.answer()

        @dp.message_handler(state=Form.MESSAGES)
        async def process_messages(message: types.Message, state: FSMContext):
            user_id = message.from_user.id
            messages = [m.strip() for m in message.text.splitlines() if m.strip()]
            if messages:
                window.set_messages(messages, user_id)
                await message.reply(f"✅ Сохранено {len(messages)} сообщений.", reply_markup=get_main_menu())
                logger.info(f"Messages set for user {user_id}: {messages}")
            else:
                await message.reply("❌ Сообщения не были введены.", reply_markup=get_main_menu())
                logger.warning(f"No messages provided by user {user_id}")
            await state.finish()

        @dp.callback_query_handler(lambda c: c.data == "delay")
        async def delay_button(callback_query: types.CallbackQuery):
            await Form.DELAY.set()
            user_id = callback_query.from_user.id
            delay = window.user_states.get(user_id, UserState()).delay
            await callback_query.message.answer(f"⏳ Введите задержку (секунд, текущая: {delay}):", reply_markup=get_main_menu())
            await callback_query.answer()

        @dp.message_handler(state=Form.DELAY)
        async def process_delay(message: types.Message, state: FSMContext):
            user_id = message.from_user.id
            try:
                delay = int(message.text.strip())
                if 30 <= delay <= 600:
                    window.set_delay(delay, user_id)
                    await message.reply(f"✅ Задержка установлена на {delay} секунд.", reply_markup=get_main_menu())
                    logger.info(f"Delay set to {delay} seconds for user {user_id}")
                else:
                    await message.reply("❌ Задержка должна быть от 30 до 600 секунд.", reply_markup=get_main_menu())
                    logger.warning(f"Invalid delay input: {delay} by user {user_id}")
            except ValueError:
                await message.reply("❌ Неверный формат. Введите число.", reply_markup=get_main_menu())
                logger.warning(f"Non-numeric delay input: {message.text} by user {user_id}")
            await state.finish()

        @dp.callback_query_handler(lambda c: c.data == "repeats")
        async def repeats_button(callback_query: types.CallbackQuery):
            await Form.REPEATS.set()
            user_id = callback_query.from_user.id
            repeats = window.user_states.get(user_id, UserState()).repeats
            await callback_query.message.answer(f"🔁 Введите количество повторов (текущее: {repeats}):", reply_markup=get_main_menu())
            await callback_query.answer()

        @dp.message_handler(state=Form.REPEATS)
        async def process_repeats(message: types.Message, state: FSMContext):
            user_id = message.from_user.id
            try:
                repeats = int(message.text.strip())
                if 1 <= repeats <= 100:
                    window.set_repeats(repeats, user_id)
                    await message.reply(f"✅ Установлено {repeats} повторов.", reply_markup=get_main_menu())
                    logger.info(f"Repeats set to {repeats} for user {user_id}")
                else:
                    await message.reply("❌ Повторы должны быть от 1 до 100.", reply_markup=get_main_menu())
                    logger.warning(f"Invalid repeats input: {repeats} by user {user_id}")
            except ValueError:
                await message.reply("❌ Неверный формат. Введите число.", reply_markup=get_main_menu())
                logger.warning(f"Non-numeric repeats input: {message.text} by user {user_id}")
            await state.finish()

        @dp.callback_query_handler(lambda c: c.data == "select_account_for_spam")
        async def select_account_for_spam_button(callback_query: types.CallbackQuery):
            user_id = callback_query.from_user.id
            if user_id not in bot_sessions or not bot_sessions[user_id]:
                await callback_query.message.answer("❌ Нет аккаунтов.", reply_markup=get_main_menu())
            else:
                await Form.SELECT_ACCOUNT.set()
                await callback_query.message.answer("✅ Выберите аккаунты для рассылки:", reply_markup=get_account_selection_menu(user_id))
            await callback_query.answer()

        @dp.callback_query_handler(lambda c: c.data.startswith("toggle_spam_account_"), state=Form.SELECT_ACCOUNT)
        async def toggle_spam_account(callback_query: types.CallbackQuery):
            phone = callback_query.data.replace("toggle_spam_account_", "")
            user_id = callback_query.from_user.id
            if user_id not in window.user_states:
                window.user_states[user_id] = UserState()
            if phone in window.user_states[user_id].clients:
                del window.user_states[user_id].clients[phone]
                await callback_query.answer(f"Аккаунт {phone} снят с рассылки.")
            else:
                if user_id in bot_sessions and phone in bot_sessions[user_id]:
                    window.user_states[user_id].clients[phone] = bot_sessions[user_id][phone]
                    await callback_query.answer(f"Аккаунт {phone} выбран для рассылки.")
                else:
                    await callback_query.answer(f"Аккаунт {phone} не найден.")
                    logger.warning(f"Attempted to select non-existent account {phone} for user {user_id}")
            await callback_query.message.edit_reply_markup(reply_markup=get_account_selection_menu(user_id))

        @dp.callback_query_handler(lambda c: c.data == "start_selected_accounts_spam", state=Form.SELECT_ACCOUNT)
        async def start_selected_accounts_spam(callback_query: types.CallbackQuery, state: FSMContext):
            user_id = callback_query.from_user.id
            clients_to_use = [{'client': data['client'], 'phone': phone} for phone, data in window.user_states.get(user_id, UserState()).clients.items()]
            if not clients_to_use:
                await callback_query.message.answer("❌ Не выбрано ни одного аккаунта.", reply_markup=get_main_menu())
                logger.warning(f"User {user_id} attempted to start spam without accounts.")
                await state.finish()
                await callback_query.answer()
                return
            success = await window.start_spam_from_bot(clients_to_use, user_id)
            if success:
                await callback_query.message.answer("🚀 Рассылка началась!", reply_markup=get_main_menu())
                logger.info(f"Bot-initiated spam started for user {user_id}")
            else:
                await callback_query.message.answer("❌ Не удалось начать рассылку.", reply_markup=get_main_menu())
                logger.error(f"Failed to start spam for user {user_id}")
            await state.finish()
            await callback_query.answer()

        @dp.callback_query_handler(lambda c: c.data == "stop")
        async def stop_button(callback_query: types.CallbackQuery):
            user_id = callback_query.from_user.id
            if user_id in window.user_states:
                window.user_states[user_id].stop_flag = True
                for task in window.user_states[user_id].spam_tasks:
                    if isinstance(task, asyncio.Task):
                        task.cancel()
                window.user_states[user_id].spam_tasks = []
                await callback_query.message.answer("🛑 Рассылка остановлена.", reply_markup=get_main_menu())
                logger.info(f"Spam stopped for user {user_id}")
            else:
                await callback_query.message.answer("❌ Нет активной рассылки.", reply_markup=get_main_menu())
                logger.info(f"No active spam for user {user_id}")
            await callback_query.answer()

        @dp.callback_query_handler(lambda c: c.data == "status")
        async def status_button(callback_query: types.CallbackQuery):
            user_id = callback_query.from_user.id
            status_text = window.get_status(user_id)
            await callback_query.message.answer(f"📊 Статус:\n{status_text}", reply_markup=get_main_menu())
            await callback_query.answer()

        @dp.callback_query_handler(lambda c: c.data == "templates")
        async def templates_button(callback_query: types.CallbackQuery):
            user_id = callback_query.from_user.id
            if user_id not in templates or not templates[user_id]:
                await callback_query.message.answer("📋 Нет шаблонов.", reply_markup=get_template_menu(user_id))
            else:
                template_list = "\n".join(f"{i+1}. {name}" for i, name in enumerate(sorted(templates[user_id].keys())))
                await callback_query.message.answer(f"📋 Шаблоны:\n{template_list}", reply_markup=get_template_menu(user_id))
            await callback_query.answer()

        @dp.callback_query_handler(lambda c: c.data == "new_template")
        async def new_template_button(callback_query: types.CallbackQuery):
            await Form.TEMPLATE.set()
            await callback_query.message.answer(
                "📋 Введите шаблон:\nПервая строка — название шаблона.\nОстальные строки — сообщения.",
                reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅ Отмена", callback_data="back"))
            )
            await callback_query.answer()

        @dp.message_handler(state=Form.TEMPLATE)
        async def process_new_template(message: types.Message, state: FSMContext):
            user_id = message.from_user.id
            lines = [m.strip() for m in message.text.splitlines() if m.strip()]
            if len(lines) < 2:
                await message.reply("❌ Шаблон должен содержать название и сообщение.", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅ Отмена", callback_data="back")))
                return
            template_name = lines[0]
            template_messages = lines[1:]
            if user_id not in templates:
                templates[user_id] = {}
            if template_name in templates[user_id]:
                await message.reply(f"❌ Шаблон '{template_name}' уже существует.", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅ Отмена", callback_data="back")))
                return
            templates[user_id][template_name] = template_messages
            await state.finish()
            await message.reply(f"✅ Шаблон '{template_name}' сохранен.", reply_markup=get_main_menu())
            logger.info(f"Template '{template_name}' saved for user {user_id}")

        @dp.callback_query_handler(lambda c: c.data.startswith("use_template_"))
        async def use_template_button(callback_query: types.CallbackQuery):
            template_name = callback_query.data.replace("use_template_", "")
            user_id = callback_query.from_user.id
            if user_id in templates and template_name in templates[user_id]:
                messages = templates[user_id][template_name]
                window.set_messages(messages, user_id)
                await callback_query.message.answer(f"✅ Загружен шаблон '{template_name}'.", reply_markup=get_main_menu())
                logger.info(f"Template '{template_name}' loaded for user {user_id}")
            else:
                await callback_query.message.answer("❌ Шаблон не найден.", reply_markup=get_main_menu())
                logger.error(f"Template {template_name} not found for user {user_id}")
            await callback_query.answer()

        @dp.callback_query_handler(lambda c: c.data == "back" or c.data == "back_from_account_selection", state="*")
        async def back_button(callback_query: types.CallbackQuery, state: FSMContext):
            await state.finish()
            await callback_query.message.answer("⬅ Главное меню:", reply_markup=get_main_menu())
            await callback_query.answer()

        try:
            if not await validate_bot_token(bot):
                logger.critical("Invalid bot token.")
                QMessageBox.critical(None, "Ошибка", "Неверный токен бота.")
                return
            logger.info("Starting Telegram bot polling...")
            bot_polling_task = asyncio.create_task(dp.start_polling())
            await bot_polling_task
        except asyncio.CancelledError:
            logger.info("Bot polling task cancelled.")
        except Exception as e:
            logger.critical(f"Error in bot polling: {e}")
            QMessageBox.critical(None, "Ошибка", f"Ошибка в работе бота: {e}")

    try:
        asyncio.ensure_future(start_bot_polling())
        with loop:
            loop.run_forever()
    except Exception as e:
        logger.critical(f"Unexpected error: {e}")
        QMessageBox.critical(None, "Ошибка запуска", f"Ошибка: {e}")
    finally:
        if bot_polling_task:
            bot_polling_task.cancel()
            try:
                loop.run_until_complete(bot_polling_task)
            except asyncio.CancelledError:
                logger.info("Bot polling task cancelled.")
        for phone, client in list(window.clients.items()):
            try:
                loop.run_until_complete(client.disconnect())
                logger.info(f"Client {phone} disconnected.")
            except Exception as e:
                logger.warning(f"Error disconnecting client {phone}: {e}")
        if app:
            app.quit()
        logger.info("Application shutdown complete.")
        loop.close()

if __name__ == "__main__":
    main()
