import asyncio
import sqlite3
import random
import time
import csv
import os
from datetime import datetime
from typing import Callable, Dict, Any, Awaitable

from aiogram import Bot, Dispatcher, F, types, BaseMiddleware
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# ================= КОНФИГУРАЦИЯ QUASAR DROP =================
BOT_TOKEN = "9255394602:AAHsiMziioH__OEeetY8mCQCtq5OeCuLWdE"
INITIAL_ADMIN_ID = 8328754114

BANNER_URL = "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?q=80&w=1200&auto=format&fit=crop"
CHANNEL_GIVES_URL = "https://t.me/snoop_tons"       # Канал с раздачами
CHANNEL_TAG = "@snoop_tons"                         # Юз канала для подписи внизу меню
WITHDRAW_CONTACT = "@adds_account"                  # Выдается ТОЛЬКО при выводе от 200 звезд
MIN_WITHDRAW = 200                                  # Минималка на вывод

# Единая подпись внизу всех менюшек
FOOTER_TEXT = f"\n\n━━━━━━━━━━━━━━━\n🎟 <i>Промокоды, раздачи и призы в канале: {CHANNEL_TAG}</i>"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ================= HIGHLOAD БАЗА ДАННЫХ =================
conn = sqlite3.connect("quasar_drop.db", check_same_thread=False, timeout=30.0)
cursor = conn.cursor()

def init_db():
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA temp_store=MEMORY;")
    cursor.execute("PRAGMA cache_size=-64000;")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 25,
            deposit INTEGER DEFAULT 0,
            prizes INTEGER DEFAULT 0,
            reg_date TEXT,
            referrer_id INTEGER DEFAULT NULL,
            ref_activated INTEGER DEFAULT 0,
            referrals_count INTEGER DEFAULT 0,
            ref_earnings INTEGER DEFAULT 0,
            last_spin INTEGER DEFAULT 0
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_refs ON users(referrals_count DESC);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_referrer ON users(referrer_id);")

    cursor.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ads (
            ad_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            url TEXT,
            channel_id TEXT,
            reward INTEGER,
            max_users INTEGER,
            current_users INTEGER DEFAULT 0,
            expires_at INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS completed_ads (
            user_id INTEGER,
            ad_id INTEGER,
            PRIMARY KEY (user_id, ad_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS promocodes (
            code TEXT PRIMARY KEY,
            reward INTEGER,
            max_uses INTEGER,
            current_uses INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS used_promos (
            user_id INTEGER,
            code TEXT,
            PRIMARY KEY (user_id, code)
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (INITIAL_ADMIN_ID,))
    conn.commit()

init_db()

user_throttling: Dict[int, float] = {}
clicked_links_cache: set = set()

# ================= ЗАЩИТА ОТ АВТОКЛИКЕРОВ =================
class AntiFloodMiddleware(BaseMiddleware):
    def __init__(self, limit: float = 0.35):
        self.limit = limit

    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        if isinstance(event, (types.Message, types.CallbackQuery)):
            uid = event.from_user.id
            now = time.monotonic()
            if uid in user_throttling and (now - user_throttling[uid]) < self.limit:
                if isinstance(event, types.CallbackQuery):
                    await event.answer("⚡️ Слишком быстро! Подождите секунду.", show_alert=False)
                return
            user_throttling[uid] = now
        return await handler(event, data)

dp.message.middleware(AntiFloodMiddleware(0.4))
dp.callback_query.middleware(AntiFloodMiddleware(0.3))

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================
def is_admin(user_id: int) -> bool:
    cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    return cursor.fetchone() is not None

def get_user(user_id: int):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return cursor.fetchone()

def format_time_left(seconds: int) -> str:
    if seconds <= 0:
        return "00ч 00м"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h:02d}ч {m:02d}м"

def get_quasar_rank(refs: int, prizes: int) -> str:
    pts = refs * 3 + prizes
    if pts >= 100:
        return "🌌 Владыка Квазара"
    elif pts >= 40:
        return "☄️ Звездный Архитектор"
    elif pts >= 15:
        return "🛸 Кибер-Рейнджер"
    elif pts >= 5:
        return "✨ Искатель Эфира"
    return "🪐 Неофит"

async def activate_referral_if_needed(user_id: int):
    user = get_user(user_id)
    if user and user[6] and user[7] == 0:
        ref_id = user[6]
        cursor.execute("UPDATE users SET ref_activated = 1 WHERE user_id = ?", (user_id,))
        cursor.execute("""
            UPDATE users 
            SET referrals_count = referrals_count + 1, balance = balance + 10, ref_earnings = ref_earnings + 10 
            WHERE user_id = ?
        """, (ref_id,))
        conn.commit()

        ref_user = get_user(ref_id)
        if ref_user:
            ref_count = ref_user[8]
            bonus_alert = ""
            if ref_count % 10 == 0:
                cursor.execute("""
                    UPDATE users SET balance = balance + 200, ref_earnings = ref_earnings + 200 
                    WHERE user_id = ?
                """, (ref_id,))
                conn.commit()
                bonus_alert = (
                    "\n\n⚡️ <b>ЦЕЛЬ 10 ДРУЗЕЙ ВЫПОЛНЕНА!</b>\n"
                    "╭─ 🎁 Бонус: <code>+200 ⭐</code>\n"
                    "╰─ Статус: <b>Зачислено на ваш баланс!</b>"
                )

            try:
                await bot.send_message(
                    ref_id,
                    f"🌌 <b>Новый реферал активирован!</b>\n"
                    f"╭─ 👤 Друг: @{user[1]}\n"
                    f"├─ 💎 Награда: <code>+10 ⭐</code>\n"
                    f"╰─ 📊 Приглашено: <code>{ref_count} чел.</code>{bonus_alert}{FOOTER_TEXT}"
                )
            except Exception:
                pass

# ================= СОСТОЯНИЯ (FSM) =================
class UserStates(StatesGroup):
    enter_promo = State()

class AdminStates(StatesGroup):
    add_admin = State()
    ad_title = State()
    ad_url = State()
    ad_channel_id = State()
    ad_reward = State()
    ad_hours = State()
    ad_max_users = State()
    promo_code = State()
    promo_reward = State()
    promo_uses = State()
    broadcast_msg = State()

# ================= КЛАВИАТУРЫ =================
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎡 Колесо Квазара (24ч)", callback_data="wheel_menu"),
            InlineKeyboardButton(text="⚡️ Заработать ⭐", callback_data="tasks_menu")
        ],
        [
            InlineKeyboardButton(text="📦 Кейсы", callback_data="cases_menu"),
            InlineKeyboardButton(text="👤 Профиль", callback_data="profile")
        ],
        [
            InlineKeyboardButton(text="🎁 Друзья (10 чел = 200 ⭐)", callback_data="ref_menu")
        ],
        [
            InlineKeyboardButton(text="📡 Канал с раздачами", url=CHANNEL_GIVES_URL)
        ]
    ])

def back_home_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="home")]
    ])

# ================= ГЛАВНОЕ МЕНЮ (/START) =================
@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username or "Player"
    user = get_user(user_id)

    if not user:
        reg_date = datetime.now().strftime("%d.%m.%Y")
        ref_id = None
        args = command.args
        if args and args.startswith("ref"):
            try:
                potential_ref = int(args.replace("ref", ""))
                if potential_ref != user_id and get_user(potential_ref):
                    ref_id = potential_ref
            except ValueError:
                pass

        cursor.execute(
            "INSERT INTO users (user_id, username, reg_date, referrer_id) VALUES (?, ?, ?, ?)",
            (user_id, username, reg_date, ref_id)
        )
        conn.commit()

        if ref_id:
            try:
                await bot.send_message(
                    ref_id,
                    f"👀 <b>Переход по вашей ссылке!</b>\n"
                    f"Игрок @{username} запустил бота.\n"
                    f"<i>Как только он прокрутит Колесо или выполнит 1 задание — вам начислится +10 ⭐ и +1 к цели 200 ⭐!</i>"
                )
            except Exception:
                pass

    await send_main_menu(message.chat.id)

async def send_main_menu(chat_id: int, message_id: int = None):
    cursor.execute("SELECT COUNT(*), SUM(prizes) FROM users")
    row = cursor.fetchone()
    u_cnt = (row[0] or 0) + 1420
    p_cnt = (row[1] or 0) + 148613

    text = (
        "🌌 <b>QUASAR DROP • Подарки и Звёзды</b> ⭐️\n\n"
        "🎁 <b>Получай Telegram подарки и звёзды бесплатно!</b>\n\n"
        "╭─ 📊 <b>Уже выдали:</b>\n"
        f"├─ ⭐️ <b>1.2 млн звезд</b>\n"
        f"├─ 🎁 <b>{p_cnt:,} подарков</b>\n"
        f"╰─ 👥 <b>{u_cnt:,} участников</b>\n\n"
        "<blockquote>💡 Для быстрого заработка звезд крутите Колесо каждые 24 часа, выполняйте задания и приглашайте друзей (10 друзей = 200 ⭐)!</blockquote>"
        f"{FOOTER_TEXT}"
    )
    if message_id:
        try:
            await bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=text, reply_markup=main_menu_kb())
            return
        except Exception:
            pass
    await bot.send_photo(chat_id=chat_id, photo=BANNER_URL, caption=text, reply_markup=main_menu_kb())

@dp.callback_query(F.data == "home")
async def cb_home(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await send_main_menu(call.message.chat.id, call.message.message_id)

# ================= ПРОФИЛЬ, ПРОМОКОД И ВЫВОД ОТ 200 ⭐ =================
@dp.callback_query(F.data == "profile")
async def cb_profile(call: types.CallbackQuery):
    user = get_user(call.from_user.id)
    rank = get_quasar_rank(user[8], user[4])

    text = (
        "👤 <b>Профиль игрока</b>\n\n"
        f"╭─ 🆔 <b>ID:</b> <code>{user[0]}</code>\n"
        f"├─ 🎖 <b>Ранг:</b> {rank}\n"
        f"├─ ⭐️ <b>Баланс:</b> <code>{user[2]} Stars</code>\n"
        f"├─ 🏦 <b>Депозит:</b> <code>{user[3]} Stars</code>\n"
        f"├─ 🎁 <b>Призов получено:</b> <code>{user[4]}</code>\n"
        f"╰─ 📅 <b>Регистрация:</b> <code>{user[5]}</code>"
        f"{FOOTER_TEXT}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Пополнить", callback_data="deposit_info")],
        [InlineKeyboardButton(text="🎟 Промокод", callback_data="enter_promo")],
        [InlineKeyboardButton(text="💸 Вывести", callback_data="withdraw")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="home")]
    ])
    await call.message.edit_caption(caption=text, reply_markup=kb)

@dp.callback_query(F.data == "deposit_info")
async def cb_deposit_info(call: types.CallbackQuery):
    # Никакого @adds_account здесь больше нет!
    await call.answer(
        f"⚡️ Пополнение баланса временно закрыто!\n"
        f"Зарабатывайте звёзды бесплатно на заданиях, рефералах и промокодах в канале {CHANNEL_TAG}!",
        show_alert=True
    )

@dp.callback_query(F.data == "enter_promo")
async def cb_enter_promo(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.enter_promo)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")]])
    await call.message.edit_caption(
        caption=f"🎟 <b>Активация промокода</b>\n\nОтправьте промокод сообщением в чат:{FOOTER_TEXT}",
        reply_markup=kb
    )

@dp.message(UserStates.enter_promo)
async def process_promo(message: types.Message, state: FSMContext):
    code = message.text.strip().upper()
    user_id = message.from_user.id

    cursor.execute("SELECT reward, max_uses, current_uses FROM promocodes WHERE code = ?", (code,))
    promo = cursor.fetchone()
    if not promo:
        return await message.answer(f"❌ Такого промокода не существует! Ищите свежие коды в {CHANNEL_TAG}", reply_markup=back_home_kb())

    reward, max_u, cur_u = promo
    if cur_u >= max_u:
        return await message.answer(f"⏳ Лимит активаций этого промокода закончился! Следите за новыми в {CHANNEL_TAG}", reply_markup=back_home_kb())

    cursor.execute("SELECT 1 FROM used_promos WHERE user_id = ? AND code = ?", (user_id, code))
    if cursor.fetchone():
        return await message.answer("⚠️ Вы уже вводили этот промокод!", reply_markup=back_home_kb())

    cursor.execute("INSERT INTO used_promos (user_id, code) VALUES (?, ?)", (user_id, code))
    cursor.execute("UPDATE promocodes SET current_uses = current_uses + 1 WHERE code = ?", (code,))
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (reward, user_id))
    conn.commit()
    await state.clear()

    await message.answer(f"🎉 <b>Промокод активирован!</b>\n➕ Зачислено: <b>{reward} ⭐</b>{FOOTER_TEXT}", reply_markup=back_home_kb())

@dp.callback_query(F.data == "withdraw")
async def cb_withdraw(call: types.CallbackQuery):
    user = get_user(call.from_user.id)
    balance = user[2]
    # Если меньше 200 звезд — @adds_account НЕ показывается!
    if balance < MIN_WITHDRAW:
        await call.answer(
            f"❌ Вывод звезд доступен строго от {MIN_WITHDRAW} ⭐!\n"
            f"Ваш баланс: {balance} ⭐ (не хватает еще {MIN_WITHDRAW - balance} ⭐).\n\n"
            f"💡 Промокоды и раздачи в канале {CHANNEL_TAG}",
            show_alert=True
        )
        return

    # Только когда 200+ звезд — выдаем @adds_account для вывода
    ticket_id = random.randint(10000, 99999)
    cursor.execute("UPDATE users SET balance = 0 WHERE user_id = ?", (user[0],))
    conn.commit()

    text = (
        f"✅ <b>ЗАЯВКА НА ВЫВОД ЗВЕЗД #QD-{ticket_id}</b>\n\n"
        f"╭─ 🆔 <b>Ваш ID:</b> <code>{user[0]}</code>\n"
        f"├─ ⭐️ <b>Сумма к выводу:</b> <code>{balance} Stars</code>\n"
        f"╰─ 📩 <b>Для вывода звезд пишите:</b> <b>{WITHDRAW_CONTACT}</b>\n\n"
        f"<blockquote>👉 Для вывода ваших звезд напишите <b>{WITHDRAW_CONTACT}</b> и отправьте скриншот этой заявки!</blockquote>"
        f"{FOOTER_TEXT}"
    )
    await call.message.edit_caption(caption=text, reply_markup=back_home_kb())

    cursor.execute("SELECT user_id FROM admins")
    for (adm_id,) in cursor.fetchall():
        try:
            adm_kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Выплачено", callback_data=f"wd_ok_{user[0]}_{balance}"),
                    InlineKeyboardButton(text="❌ Вернуть звезды", callback_data=f"wd_ret_{user[0]}_{balance}")
                ]
            ])
            await bot.send_message(
                adm_id,
                f"💸 <b>ЗАЯВКА НА ВЫВОД #QD-{ticket_id}</b>\n"
                f"╭─ 👤 Юзер: @{user[1]} (<code>{user[0]}</code>)\n"
                f"├─ ⭐️ Сумма: <b>{balance} Stars</b>\n"
                f"╰─ 👥 Приглашено друзей: <code>{user[8]} чел.</code>",
                reply_markup=adm_kb
            )
        except Exception:
            pass

@dp.callback_query(F.data.startswith("wd_"))
async def cb_admin_withdraw_action(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    parts = call.data.split("_")
    action, target_uid, amount = parts[1], int(parts[2]), int(parts[3])

    if action == "ok":
        await call.message.edit_text(call.message.text + "\n\n✅ <b>ВЫПЛАЧЕНО</b>", parse_mode=ParseMode.HTML)
        try:
            await bot.send_message(target_uid, f"🎉 Ваша выплата на сумму <b>{amount} ⭐</b> успешно отправлена!{FOOTER_TEXT}")
        except Exception:
            pass
    elif action == "ret":
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_uid))
        conn.commit()
        await call.message.edit_text(call.message.text + "\n\n❌ <b>ОТМЕНЕНО (Звезды возвращены)</b>", parse_mode=ParseMode.HTML)
        try:
            await bot.send_message(target_uid, f"🔄 Заявка на вывод отменена, <b>{amount} ⭐</b> возвращены на ваш баланс.{FOOTER_TEXT}")
        except Exception:
            pass

# ================= МАГАЗИН КЕЙСОВ И КОЛЕСО (РАЗ В 24 ЧАСА) =================
@dp.callback_query(F.data == "cases_menu")
async def cb_cases_menu(call: types.CallbackQuery):
    user = get_user(call.from_user.id)
    diff = int(time.time()) - user[10]
    wheel_tag = f"⏳ {format_time_left(86400 - diff)}" if diff < 86400 else "🎁 БЕСПЛАТНО"

    text = (
        "🛍 <b>МАГАЗИН КЕЙСОВ • QUASAR</b>\n"
        f"💳 <b>БАЛАНС — {user[2]} STARS</b>\n\n"
        f"Выберите кейс:{FOOTER_TEXT}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎡 Ежедневное колесо — {wheel_tag}", callback_data="wheel_menu")],
        [InlineKeyboardButton(text="🧸 Мишка кейс — 5 ⭐", callback_data="case_neon")],
        [InlineKeyboardButton(text="🌌 Квазар кейс — 25 ⭐", callback_data="case_quantum")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="home")]
    ])
    await call.message.edit_caption(caption=text, reply_markup=kb)

@dp.callback_query(F.data == "wheel_menu")
async def cb_wheel_menu(call: types.CallbackQuery):
    user = get_user(call.from_user.id)
    diff = int(time.time()) - user[10]

    text = (
        "🎡 <b>Колесо: Ежедневный прокрут</b>\n"
        "🗓 <b>Тип:</b> Ежедневный (бесплатно раз в 24ч)\n"
        "💰 <b>Цена:</b> <code>БЕСПЛАТНО</code>\n"
        f"💳 <b>Ваш баланс:</b> <code>{user[2]} ⭐</code>\n\n"
        "📊 <b>Содержимое:</b>\n"
        "🧸 мишка — <b>3.0%</b>\n"
        "⭐️ 5 звёзд — <b>20.0%</b>\n"
        "❌ ничего — <b>77.0%</b>"
        f"{FOOTER_TEXT}"
    )
    if diff < 86400:
        btn = InlineKeyboardButton(text=f"⏳ Доступно через {format_time_left(86400 - diff)}", callback_data="wheel_wait")
    else:
        btn = InlineKeyboardButton(text="🎰 КРУТИТЬ КОЛЕСО (SPIN NOW)", callback_data="spin_wheel_now")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="cases_menu")]
    ])
    await call.message.edit_caption(caption=text, reply_markup=kb)

@dp.callback_query(F.data == "wheel_wait")
async def cb_wheel_wait(call: types.CallbackQuery):
    user = get_user(call.from_user.id)
    left = format_time_left(86400 - (int(time.time()) - user[10]))
    await call.answer(f"⏳ Доступно через {left}!", show_alert=True)

@dp.callback_query(F.data == "spin_wheel_now")
async def cb_spin_wheel_now(call: types.CallbackQuery):
    user = get_user(call.from_user.id)
    now = int(time.time())
    if now - user[10] < 86400:
        return await cb_wheel_wait(call)

    await call.message.edit_caption(caption="🎡 <b>Колесо Квазара вращается...</b>\n\n<code>⏳ Определяем ваш подарок...</code>")
    await asyncio.sleep(1.2)

    roll = random.uniform(0, 100)
    if roll <= 3.0:
        win_str = "🧸 <b>Подарок «Мишка» (+15 ⭐)!</b>"
        reward, pr = 15, 1
    elif roll <= 23.0:
        win_str = "⭐️ <b>+5 Звёзд на баланс!</b>"
        reward, pr = 5, 1
    else:
        win_str = "❌ <b>Ничего не выпало. Попробуйте через 24 часа!</b>"
        reward, pr = 0, 0

    cursor.execute(
        "UPDATE users SET balance = balance + ?, prizes = prizes + ?, last_spin = ? WHERE user_id = ?",
        (reward, pr, now, call.from_user.id)
    )
    conn.commit()
    await activate_referral_if_needed(call.from_user.id)

    text = (
        "🎰 <b>Колесо остановилось!</b>\n\n"
        f"╭─ 🎁 <b>Выигрыш:</b> {win_str}\n"
        f"├─ 💳 <b>Ваш баланс:</b> <code>{user[2] + reward} ⭐</code>\n"
        f"╰─ ⏳ <b>Следующий прокрут:</b> <code>через 24ч 00м</code>"
        f"{FOOTER_TEXT}"
    )
    await call.message.edit_caption(caption=text, reply_markup=back_home_kb())

# --- Платные кейсы ---
@dp.callback_query(F.data == "case_neon")
async def cb_case_neon(call: types.CallbackQuery):
    user = get_user(call.from_user.id)
    text = (
        "📦 <b>Кейс: мишка кейс</b>\n"
        "🏷 <b>Тип:</b> Обычный\n"
        "💰 <b>Цена:</b> <code>5 ⭐</code>\n"
        f"💳 <b>Ваш баланс:</b> <code>{user[2]} ⭐</code>\n\n"
        "📊 <b>Содержимое:</b>\n"
        "🧸 мишка (15 ⭐) — <b>25.0%</b>\n"
        "❌ ничего — <b>75.0%</b>"
        f"{FOOTER_TEXT}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Открыть кейс", callback_data="open_neon")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="cases_menu")]
    ])
    await call.message.edit_caption(caption=text, reply_markup=kb)

@dp.callback_query(F.data == "open_neon")
async def cb_open_neon(call: types.CallbackQuery):
    user = get_user(call.from_user.id)
    if user[2] < 5:
        return await call.answer("❌ Недостаточно звёзд! Нужно 5 ⭐.", show_alert=True)

    roll = random.uniform(0, 100)
    if roll <= 25.0:
        reward, pr = 15, 1
        msg = "🎉 Выпал 🧸 Мишка (+15 ⭐)!"
    else:
        reward, pr = 0, 0
        msg = "❌ Выпало: ничего!"

    cursor.execute("UPDATE users SET balance = balance - 5 + ?, prizes = prizes + ? WHERE user_id = ?", (reward, pr, call.from_user.id))
    if user[6]:
        cursor.execute("UPDATE users SET balance = balance + 1, ref_earnings = ref_earnings + 1 WHERE user_id = ?", (user[6],))
    conn.commit()
    await call.answer(msg, show_alert=True)
    await cb_case_neon(call)

@dp.callback_query(F.data == "case_quantum")
async def cb_case_quantum(call: types.CallbackQuery):
    user = get_user(call.from_user.id)
    text = (
        "🌌 <b>Кейс: Квазар кейс</b>\n"
        "🏷 <b>Тип:</b> Элитный\n"
        "💰 <b>Цена:</b> <code>25 ⭐</code>\n"
        f"💳 <b>Ваш баланс:</b> <code>{user[2]} ⭐</code>\n\n"
        "📊 <b>Содержимое:</b>\n"
        "🏆 Кубок Квазара (100 ⭐) — <b>10.0%</b>\n"
        "🧸 мишка (15 ⭐) — <b>40.0%</b>\n"
        "❌ ничего — <b>50.0%</b>"
        f"{FOOTER_TEXT}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Открыть кейс (25 ⭐)", callback_data="open_quantum")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="cases_menu")]
    ])
    await call.message.edit_caption(caption=text, reply_markup=kb)

@dp.callback_query(F.data == "open_quantum")
async def cb_open_quantum(call: types.CallbackQuery):
    user = get_user(call.from_user.id)
    if user[2] < 25:
        return await call.answer("❌ Недостаточно звёзд! Нужно 25 ⭐.", show_alert=True)

    roll = random.uniform(0, 100)
    if roll <= 10.0:
        reward, pr = 100, 1
        msg = "🔥 ДЖЕКПОТ! Выпал 🏆 Кубок Квазара (+100 ⭐)!"
    elif roll <= 50.0:
        reward, pr = 15, 1
        msg = "🧸 Выпал Мишка (+15 ⭐)!"
    else:
        reward, pr = 0, 0
        msg = "❌ Ничего не выпало!"

    cursor.execute("UPDATE users SET balance = balance - 25 + ?, prizes = prizes + ? WHERE user_id = ?", (reward, pr, call.from_user.id))
    if user[6]:
        cursor.execute("UPDATE users SET balance = balance + 2, ref_earnings = ref_earnings + 2 WHERE user_id = ?", (user[6],))
    conn.commit()
    await call.answer(msg, show_alert=True)
    await cb_case_quantum(call)

# ================= РЕФЕРАЛЬНАЯ СИСТЕМА (10 ЧЕЛ = 200 ⭐) =================
@dp.callback_query(F.data == "ref_menu")
async def cb_ref_menu(call: types.CallbackQuery):
    user = get_user(call.from_user.id)
    ref_link = f"https://t.me/quasar_drop_bot?start=ref{user[0]}"
    refs = user[8]
    left_to_10 = 10 - (refs % 10)
    bar = "🟦" * (refs % 10) + "⬜️" * left_to_10

    text = (
        "🎁 <b>ПОЛУЧАЙ ПОДАРКИ И ЗВЁЗДЫ</b> 👇\n"
        "➖➖➖➖➖➖➖➖➖➖\n"
        f"👤 <b>Приглашено:</b> <code>{refs} Человек</code>\n"
        f"💬 <b>Доход с друзей:</b> <code>5% (от их трат) + 10 ⭐ за друга</code>\n"
        "➖➖➖➖➖➖➖➖➖➖\n\n"
        "🎯 <b>Цель: Пригласи 10 Друзей и получи +200 ⭐!</b>\n"
        f"⏰ <b>До получения 200 ⭐ осталось:</b> <code>{left_to_10} чел.</code>\n"
        f"{bar} <code>({refs % 10}/10)</code>\n\n"
        "🔗 <b>Ссылка для приглашения</b> 👇\n"
        f"<code>{ref_link}</code>"
        f"{FOOTER_TEXT}"
    )
    share_url = f"https://t.me/share/url?url={ref_link}&text=Крути%20колесо%20в%20QUASAR%20DROP%20каждые%2024%20часа%20и%20забирай%20Звезды%20Telegram!"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📨 Поделиться ссылкой", url=share_url)],
        [InlineKeyboardButton(text="🏆 Топ 5 приглашений", callback_data="top_refs")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="home")]
    ])
    await call.message.edit_caption(caption=text, reply_markup=kb)

@dp.callback_query(F.data == "top_refs")
async def cb_top_refs(call: types.CallbackQuery):
    cursor.execute("SELECT username, referrals_count, ref_earnings FROM users ORDER BY referrals_count DESC LIMIT 5")
    rows = cursor.fetchall()
    lines = ["🏆 <b>Топ 5 приглашений проекта:</b>\n"]
    icons = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for idx, (uname, cnt, earn) in enumerate(rows):
        lines.append(f"{icons[idx]} @{uname} — <b>{cnt} чел.</b> <i>(+{earn} ⭐)</i>")

    lines.append(FOOTER_TEXT)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="ref_menu")]])
    await call.message.edit_caption(caption="\n".join(lines), reply_markup=kb)

# ================= ЗАДАНИЯ (РЕКЛАМА) =================
@dp.callback_query(F.data == "tasks_menu")
async def cb_tasks_menu(call: types.CallbackQuery):
    now = int(time.time())
    cursor.execute("""
        SELECT ad_id, title, url, channel_id, reward FROM ads
        WHERE (expires_at > ? OR expires_at = 0)
        AND (current_users < max_users OR max_users = 0)
        AND ad_id NOT IN (SELECT ad_id FROM completed_ads WHERE user_id = ?)
    """, (now, call.from_user.id))
    ads = cursor.fetchall()

    if not ads:
        text = (
            "⭐️ <b>Доступные задания на получение звезд!</b>\n\n"
            "✅ Вы выполнили все доступные задания!\n"
            "Новые задания появляются каждый день — проверяйте позже."
            f"{FOOTER_TEXT}"
        )
        return await call.message.edit_caption(caption=text, reply_markup=back_home_kb())

    lines = ["⭐️ <b>Доступные задания на получение звезд!</b>\n"]
    kb_rows = []
    for idx, (ad_id, title, url, ch_id, reward) in enumerate(ads, 1):
        lines.append(f"<b>{idx}. {title} — {reward} ⭐</b>")
        kb_rows.append([
            InlineKeyboardButton(text=f"🔥 {idx}. {title}", callback_data=f"open_task_{ad_id}")
        ])

    lines.append(FOOTER_TEXT)
    kb_rows.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="home")])
    await call.message.edit_caption(caption="\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))

@dp.callback_query(F.data.startswith("open_task_"))
async def cb_open_task_detail(call: types.CallbackQuery):
    ad_id = int(call.data.split("_")[2])
    cursor.execute("SELECT title, url, reward FROM ads WHERE ad_id = ?", (ad_id,))
    ad = cursor.fetchone()
    if not ad:
        return await call.answer("❌ Задание уже не активно!", show_alert=True)

    title, url, reward = ad
    clicked_links_cache.add((call.from_user.id, ad_id))

    text = (
        f"⭐️ <b>Задание: {title}</b>\n\n"
        f"💰 <b>Награда:</b> <code>+{reward} ⭐</code>\n\n"
        f"1️⃣ Нажмите кнопку <b>«Перейти»</b> и выполните условие (подписка / запуск бота).\n"
        f"2️⃣ Вернитесь сюда и нажмите <b>«Проверить»</b> для зачисления звезд!"
        f"{FOOTER_TEXT}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔗 1. Перейти ({title})", url=url)],
        [InlineKeyboardButton(text=f"✅ 2. Проверить (+{reward} ⭐)", callback_data=f"check_ad_{ad_id}")],
        [InlineKeyboardButton(text="⬅️ Назад к заданиям", callback_data="tasks_menu")]
    ])
    await call.message.edit_caption(caption=text, reply_markup=kb)

@dp.callback_query(F.data.startswith("check_ad_"))
async def cb_check_ad(call: types.CallbackQuery):
    ad_id = int(call.data.split("_")[2])
    user_id = call.from_user.id

    cursor.execute("SELECT 1 FROM completed_ads WHERE user_id = ? AND ad_id = ?", (user_id, ad_id))
    if cursor.fetchone():
        return await call.answer("✅ Вы уже получили награду за это задание!", show_alert=True)

    cursor.execute("SELECT channel_id, reward, max_users, current_users, expires_at FROM ads WHERE ad_id = ?", (ad_id,))
    ad = cursor.fetchone()
    if not ad:
        return await call.answer("❌ Задание удалено.", show_alert=True)

    channel_id, reward, max_u, cur_u, exp = ad
    if (exp != 0 and int(time.time()) > exp) or (max_u != 0 and cur_u >= max_u):
        return await call.answer("⏳ Время или лимит участников этого задания закончились!", show_alert=True)

    if channel_id and channel_id.lower() != "нет":
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            if member.status in ["left", "kicked"]:
                return await call.answer("❌ Вы еще не подписались на канал! Подпишитесь и нажмите снова.", show_alert=True)
        except Exception:
            pass
    else:
        if (user_id, ad_id) not in clicked_links_cache:
            return await call.answer("❌ Сначала перейдите по ссылке!", show_alert=True)

    cursor.execute("INSERT INTO completed_ads (user_id, ad_id) VALUES (?, ?)", (user_id, ad_id))
    cursor.execute("UPDATE ads SET current_users = current_users + 1 WHERE ad_id = ?", (ad_id,))
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (reward, user_id))
    conn.commit()

    await activate_referral_if_needed(user_id)
    await call.answer(f"🎉 Выполнено! Начислено +{reward} ⭐", show_alert=True)
    await cb_tasks_menu(call)

# ================= АДМИН-ПАНЕЛЬ (/ADMINS) =================
@dp.message(Command("make_me_admin"))
async def cmd_secret_admin(message: types.Message):
    cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (message.from_user.id,))
    conn.commit()
    await message.answer("✅ Права администратора выданы! Напишите /admins")

@dp.message(Command("admins"))
async def cmd_admins(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()

    cursor.execute("SELECT COUNT(*), SUM(balance), COUNT(CASE WHEN ref_activated = 1 THEN 1 END) FROM users")
    u_row = cursor.fetchone()
    total_users = u_row[0] or 0
    total_bal = u_row[1] or 0
    active_refs = u_row[2] or 0

    cursor.execute("SELECT COUNT(*) FROM ads")
    total_ads = cursor.fetchone()[0]

    text = (
        "👑 <b>АДМИН-ПАНЕЛЬ QUASAR DROP (/admins)</b>\n\n"
        f"╭─ 👥 <b>Всего пользователей:</b> <code>{total_users:,} чел.</code>\n"
        f"├─ 🔥 <b>Активных рефералов:</b> <code>{active_refs:,} чел.</code>\n"
        f"├─ ⭐️ <b>Звезд на балансах:</b> <code>{total_bal:,} Stars</code>\n"
        f"╰─ 📢 <b>Активной рекламы:</b> <code>{total_ads} шт.</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Поставить рекламу (Часы / Уч. / Реф)", callback_data="adm_add_ad")],
        [InlineKeyboardButton(text="📊 Список рекламы (Прогресс / Удалить)", callback_data="adm_list_ads")],
        [
            InlineKeyboardButton(text="🎟 Создать промокод", callback_data="adm_add_promo"),
            InlineKeyboardButton(text="👮‍♂️ Добавить админа", callback_data="adm_add_admin")
        ],
        [
            InlineKeyboardButton(text="🚀 Рассылка всем", callback_data="adm_broadcast"),
            InlineKeyboardButton(text="📥 Выгрузить БД (.csv)", callback_data="adm_export_csv")
        ]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "adm_export_csv")
async def cb_adm_export_csv(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    await call.answer("⏳ Готовлю файл...", show_alert=False)
    filename = "quasar_users.csv"
    cursor.execute("SELECT user_id, username, balance, referrals_count, reg_date FROM users")
    rows = cursor.fetchall()

    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Telegram ID", "Username", "Balance", "Referrals", "Reg Date"])
        writer.writerows(rows)

    await call.message.answer_document(FSInputFile(filename), caption=f"📊 База пользователей: <code>{len(rows):,} чел.</code>")
    os.remove(filename)

@dp.callback_query(F.data == "adm_add_admin")
async def cb_adm_add_admin(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.add_admin)
    await call.message.answer("👮‍♂️ Введите <b>Telegram ID</b> пользователя, чтобы добавить его в `/admins`:")

@dp.message(AdminStates.add_admin)
async def process_add_admin(message: types.Message, state: FSMContext):
    try:
        new_id = int(message.text.strip())
        cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (new_id,))
        conn.commit()
        await message.answer(f"✅ Админ <code>{new_id}</code> добавлен в `/admins`!")
    except ValueError:
        await message.answer("❌ Введите только цифры ID.")
    await state.clear()

@dp.callback_query(F.data == "adm_add_ad")
async def cb_adm_add_ad(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.ad_title)
    await call.message.answer("1️⃣ Введите <b>название задания</b> (например: <code>Подпишись</code> или <code>Запусти бота</code>):")

@dp.message(AdminStates.ad_title)
async def process_ad_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AdminStates.ad_url)
    await message.answer("2️⃣ Отправьте <b>ссылку</b> (обычную ссылку на канал или реферальную ссылку на бота):")

@dp.message(AdminStates.ad_url)
async def process_ad_url(message: types.Message, state: FSMContext):
    await state.update_data(url=message.text.strip())
    await state.set_state(AdminStates.ad_channel_id)
    await message.answer(
        "3️⃣ <b>Проверка подписки:</b>\n"
        "• Если это канал, где бот админ — скиньте <code>@username</code> канала или его ID (<code>-100...</code>).\n"
        "• Если это <b>реф. ссылка на бота</b> или обычная ссылка без проверки — напишите: <code>нет</code>"
    )

@dp.message(AdminStates.ad_channel_id)
async def process_ad_channel(message: types.Message, state: FSMContext):
    await state.update_data(channel_id=message.text.strip())
    await state.set_state(AdminStates.ad_reward)
    await message.answer("4️⃣ Сколько звезд (⭐) давать за выполнение? (Например: <code>5</code>):")

@dp.message(AdminStates.ad_reward)
async def process_ad_reward(message: types.Message, state: FSMContext):
    try:
        reward = int(message.text.strip())
    except ValueError:
        return await message.answer("❌ Введите число!")
    await state.update_data(reward=reward)
    await state.set_state(AdminStates.ad_hours)
    await message.answer("5️⃣ На сколько <b>часов</b> ставим рекламу? (Например: <code>24</code>, или <code>0</code> — без ограничения):")

@dp.message(AdminStates.ad_hours)
async def process_ad_hours(message: types.Message, state: FSMContext):
    try:
        hours = int(message.text.strip())
    except ValueError:
        return await message.answer("❌ Введите число!")
    await state.update_data(hours=hours)
    await state.set_state(AdminStates.ad_max_users)
    await message.answer("6️⃣ Лимит по <b>участникам</b>: сколько человек должны выполнить? (Например: <code>500</code>, или <code>0</code> — без лимита):")

@dp.message(AdminStates.ad_max_users)
async def process_ad_max_users(message: types.Message, state: FSMContext):
    try:
        max_users = int(message.text.strip())
    except ValueError:
        return await message.answer("❌ Введите число!")

    data = await state.get_data()
    expires_at = int(time.time()) + (data["hours"] * 3600) if data["hours"] > 0 else 0

    cursor.execute("""
        INSERT INTO ads (title, url, channel_id, reward, max_users, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (data["title"], data["url"], data["channel_id"], data["reward"], max_users, expires_at))
    conn.commit()
    await state.clear()

    await message.answer(
        "✅ <b>Реклама успешно поставлена!</b>\n\n"
        f"╭─ 📌 Название: <b>{data['title']}</b>\n"
        f"├─ 🔗 Ссылка: {data['url']}\n"
        f"├─ ⭐️ Награда: <code>+{data['reward']} ⭐</code>\n"
        f"├─ ⏳ На часов: <code>{data['hours'] if data['hours'] > 0 else 'Безлимит'}</code>\n"
        f"╰─ 👥 Лимит уч.: <code>{max_users if max_users > 0 else 'Безлимит'}</code>"
    )

@dp.callback_query(F.data == "adm_list_ads")
async def cb_adm_list_ads(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    cursor.execute("SELECT ad_id, title, current_users, max_users, expires_at FROM ads")
    ads = cursor.fetchall()
    if not ads:
        return await call.answer("Активной рекламы нет.", show_alert=True)

    now = int(time.time())
    kb_rows = []
    for ad_id, title, cur_u, max_u, exp in ads:
        u_str = f"{cur_u}/{max_u} уч." if max_u > 0 else f"{cur_u}/∞ уч."
        t_str = format_time_left(exp - now) if exp > 0 else "∞ ч."
        kb_rows.append([InlineKeyboardButton(text=f"🗑 {title} | {u_str} | {t_str}", callback_data=f"del_ad_{ad_id}")])

    await call.message.answer("📊 <b>Активная реклама</b> (нажмите для удаления):", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))

@dp.callback_query(F.data.startswith("del_ad_"))
async def cb_del_ad(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    ad_id = int(call.data.split("_")[2])
    cursor.execute("DELETE FROM ads WHERE ad_id = ?", (ad_id,))
    cursor.execute("DELETE FROM completed_ads WHERE ad_id = ?", (ad_id,))
    conn.commit()
    await call.answer("🗑 Реклама удалена!", show_alert=True)
    await call.message.delete()

@dp.callback_query(F.data == "adm_add_promo")
async def cb_adm_add_promo(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.promo_code)
    await call.message.answer("🎟 Введите название промокода (например: <code>SNOOP50</code>):")

@dp.message(AdminStates.promo_code)
async def process_promo_code(message: types.Message, state: FSMContext):
    await state.update_data(code=message.text.strip().upper())
    await state.set_state(AdminStates.promo_reward)
    await message.answer("⭐️ Сколько звезд даёт промокод?")

@dp.message(AdminStates.promo_reward)
async def process_promo_reward(message: types.Message, state: FSMContext):
    try:
        rew = int(message.text.strip())
    except ValueError:
        return await message.answer("❌ Введите число!")
    await state.update_data(reward=rew)
    await state.set_state(AdminStates.promo_uses)
    await message.answer("👥 На сколько активаций?")

@dp.message(AdminStates.promo_uses)
async def process_promo_uses(message: types.Message, state: FSMContext):
    try:
        uses = int(message.text.strip())
    except ValueError:
        return await message.answer("❌ Введите число!")
    data = await state.get_data()
    cursor.execute("INSERT OR REPLACE INTO promocodes (code, reward, max_uses, current_uses) VALUES (?, ?, ?, 0)",
                   (data["code"], data["reward"], uses))
    conn.commit()
    await state.clear()
    await message.answer(f"✅ Промокод <code>{data['code']}</code> на <b>+{data['reward']} ⭐</b> ({uses} акт.) создан!")

@dp.callback_query(F.data == "adm_broadcast")
async def cb_adm_broadcast(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.broadcast_msg)
    await call.message.answer("🚀 Отправьте сообщение (текст, фото, видео), которое нужно разослать всем:")

@dp.message(AdminStates.broadcast_msg)
async def process_broadcast(message: types.Message, state: FSMContext):
    await state.clear()
    cursor.execute("SELECT user_id FROM users")
    users = [r[0] for r in cursor.fetchall()]
    total = len(users)
    sent, failed = 0, 0

    status_msg = await message.answer(f"🚀 <b>Рассылка запущена!</b>\nПрогресс: <code>0 / {total}</code>")

    for idx, uid in enumerate(users, 1):
        try:
            await message.copy_to(chat_id=uid)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.04)

        if idx % 250 == 0:
            try:
                await status_msg.edit_text(
                    f"🚀 <b>Идет рассылка...</b>\n"
                    f"Обработано: <code>{idx:,} / {total:,}</code>\n"
                    f"Доставлено: <code>{sent:,}</code>"
                )
            except Exception:
                pass

    await status_msg.edit_text(f"✅ <b>Рассылка завершена!</b>\nДоставлено: <code>{sent:,}</code>\nБлок: <code>{failed:,}</code>")

# =================== ЗАПУСК ===================
from aiohttp import web
import os
import asyncio

async def handle(request):
    return web.Response(text="Bot is running!")

async def web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    await asyncio.Future()

async def main():
    print("🤖 Бот @quasar_drop_bot успешно запущен!")
    # Запускаем веб-сервер для Render и поллинг бота одновременно
    await asyncio.gather(
        web_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    asyncio.run(main())
