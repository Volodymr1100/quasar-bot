import asyncio
import csv
import io
import logging
import os
import random
import sqlite3
import time
from datetime import datetime

from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

# =====================================================================
# ⚙️ НАСТРОЙКИ БОТА
# =====================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_БОТА")
RAW_ADMINS = os.getenv("ADMIN_IDS", "123456789")
ADMIN_IDS = [int(x.strip()) for x in RAW_ADMINS.split(",") if x.strip().isdigit()]

WEBAPP_URL = os.getenv("RENDER_EXTERNAL_URL", "https://quasar-bot-ngoj.onrender.com")

REF_REWARD_STARS = 25
DB_PATH = "quasar_drop.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


# =====================================================================
# 🔤 СИСТЕМА СМЕНЫ ШРИФТА БОТА ("ДЛЯ ВОРКА") + PREMIUM УКРАШЕНИЯ
# =====================================================================
FONT_MAPS = {
    "mono": str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
        "𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿",
    ),
    "bold": str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
        "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭𝗮𝗯𝗰𝗱𝚎𝚏𝗴𝚑𝚒𝚓𝗸𝚕𝗺𝗻𝚘𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵",
    ),
    "double": str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
        "𝔸𝔹ℂ𝔻𝔼𝔽𝔾ℍ𝕀𝕁𝕂𝕃𝕄ℕ𝕆ℙℚℝ𝕊𝕋𝕌𝕍𝕎𝕏𝕐ℤ𝕒𝕓𝕔𝕕𝖊𝖋𝖌𝖍𝖎𝖏𝖐𝖑𝖒𝖓𝖔𝖕𝖖𝖗𝖘𝖙𝖚𝖛𝖜𝖝𝖞𝖟𝟘𝟙𝕚𝕛𝜜𝜝𝜞𝜟",
    ),
}

CYRILLIC_SMALLCAPS = str.maketrans(
    "абвгдежзийклмнопрстуфхцчшщъыьэюя",
    "ᴀʙʙгдᴇжзийклмнопрстуфхцчшщъыьэюя",
)


def get_font_mode() -> str:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'font_mode'").fetchone()
        return row[0] if row else "normal"


def style_text(text: str) -> str:
    mode = get_font_mode()
    if mode == "normal":
        return text

    parts = text.split("<")
    out = []
    for i, part in enumerate(parts):
        if i == 0:
            out.append(_transform_chunk(part, mode))
        else:
            if ">" in part:
                tag, rest = part.split(">", 1)
                out.append(f"<{tag}>{_transform_chunk(rest, mode)}")
            else:
                out.append(f"<{part}")
    return "".join(out)


def _transform_chunk(chunk: str, mode: str) -> str:
    if "http://" in chunk or "https://" in chunk or "t.me/" in chunk:
        return chunk
    if mode in FONT_MAPS:
        chunk = chunk.translate(FONT_MAPS[mode])
    if mode == "smallcaps":
        chunk = chunk.translate(CYRILLIC_SMALLCAPS)
    return chunk


# =====================================================================
# 🗄 БАЗА ДАННЫХ SQLITE
# =====================================================================
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                stars INTEGER DEFAULT 50,
                invited_by INTEGER DEFAULT 0,
                ref_verified INTEGER DEFAULT 0,
                refs_count INTEGER DEFAULT 0,
                nft_won TEXT DEFAULT NULL,
                sub_case_claimed INTEGER DEFAULT 0,
                joined_at INTEGER
            )
        """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS ads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                url TEXT,
                channel_id TEXT,
                reward INTEGER DEFAULT 10,
                hours INTEGER DEFAULT 0,
                limit_users INTEGER DEFAULT 0,
                current_users INTEGER DEFAULT 0,
                created_at INTEGER,
                is_main_tgk INTEGER DEFAULT 0
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS completed_ads (
                user_id INTEGER,
                ad_id INTEGER,
                PRIMARY KEY (user_id, ad_id)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('font_mode', 'normal')")
        conn.commit()


def get_user(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()


def register_user(user_id: int, username: str, first_name: str, invited_by: int = 0):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        existing = c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not existing:
            if invited_by == user_id:
                invited_by = 0
            c.execute(
                """
                INSERT INTO users (user_id, username, first_name, stars, invited_by, ref_verified, refs_count, joined_at)
                VALUES (?, ?, ?, 50, ?, 0, 0, ?)
                """,
                (user_id, username or "", first_name or "User", invited_by, int(time.time())),
            )
            conn.commit()
            return True
        return False


def get_active_ads(only_main_tgk: bool = False):
    now = int(time.time())
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM ads").fetchall()
        active = []
        for r in rows:
            if r["hours"] > 0 and (now - r["created_at"]) > r["hours"] * 3600:
                continue
            if r["limit_users"] > 0 and r["current_users"] >= r["limit_users"]:
                continue
            if only_main_tgk and r["is_main_tgk"] == 0:
                continue
            active.append(r)
        return active


async def check_user_subscriptions(user_id: int, only_main: bool = False) -> list:
    ads = get_active_ads(only_main_tgk=only_main)
    unsubscribed = []
    for ad in ads:
        ch_id = (ad["channel_id"] or "").strip()
        if ch_id and ch_id.lower() != "нет":
            try:
                member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
                if member.status in ("left", "kicked"):
                    unsubscribed.append(ad)
            except Exception:
                pass
    return unsubscribed


async def try_verify_referral(user_id: int):
    user = get_user(user_id)
    if not user or user["ref_verified"] == 1 or user["invited_by"] == 0:
        return

    unsub = await check_user_subscriptions(user_id, only_main=False)
    if len(unsub) > 0:
        return

    inviter_id = user["invited_by"]
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET ref_verified = 1 WHERE user_id = ?", (user_id,))
        c.execute(
            "UPDATE users SET refs_count = refs_count + 1, stars = stars + ? WHERE user_id = ?",
            (REF_REWARD_STARS, inviter_id),
        )
        conn.commit()

    inviter = get_user(inviter_id)
    if inviter:
        try:
            msg_text = (
                f'<tg-emoji emoji-id="5461151367559141950">🎉</tg-emoji> <b>НОВЫЙ ПОДТВЕРЖДЕННЫЙ РЕФЕРАЛ!</b>\n\n'
                f"┌ 👤 Друг: <b>{user['first_name']}</b> подписался на ТГК!\n"
                f"├ ⭐ Награда: <b>+{REF_REWARD_STARS} Stars</b>\n"
                f"├ 👥 Всего друзей: <b>{inviter['refs_count']} чел.</b>\n"
                f"└ 🎁 До вывода NFT: <b>{max(0, 25 - inviter['refs_count'])} друз.</b>"
            )
            await bot.send_message(inviter_id, style_text(msg_text))
        except Exception:
            pass


# =====================================================================
# 🎛 КЛАВИАТУРЫ И МЕНЮ
# =====================================================================
def main_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    webapp_roulette_url = f"{WEBAPP_URL.rstrip('/')}/case?user_id={user_id}"
    buttons = [
        [
            InlineKeyboardButton(
                text="🎰 Открыть NFT-Рулетку (Mini-App)",
                web_app=WebAppInfo(url=webapp_roulette_url),
            )
        ],
        [
            InlineKeyboardButton(text="💎 NFT Кейс (Гарант)", callback_data="menu_nft_case"),
            InlineKeyboardButton(text="🎁 Кейс за Подписки", callback_data="menu_sub_case"),
        ],
        [
            InlineKeyboardButton(text="⭐ Заработать Звезды", callback_data="menu_earn"),
            InlineKeyboardButton(text="👥 Пригласить Друзей", callback_data="menu_refs"),
        ],
        [
            InlineKeyboardButton(text="👛 Мой Профиль", callback_data="menu_profile"),
            InlineKeyboardButton(text="📤 Вывод Звезд / NFT", callback_data="menu_withdraw"),
        ],
    ]
    if user_id in ADMIN_IDS:
        buttons.append(
            [InlineKeyboardButton(text="👑 АДМИН-ПАНЕЛЬ (/admins)", callback_data="admin_panel")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад в главное меню", callback_data="back_home")]]
    )


def main_menu_text(user) -> str:
    nft_status = user["nft_won"] if user["nft_won"] else "Не выбит (Открой NFT Кейс!)"
    text = (
        f'<tg-emoji emoji-id="5368324170671202286">🌌</tg-emoji> <b>QUASAR DROP • PREMIUM STARS & NFT</b> <tg-emoji emoji-id="5427009714745517609">✨</tg-emoji>\n'
        f"<i>Добро пожаловать в элитный дроп-бот подарков и Telegram Stars!</i>\n\n"
        f'┌ <tg-emoji emoji-id="5373012449597335010">🆔</tg-emoji> Ваш ID: <code>{user["user_id"]}</code>\n'
        f'├ <tg-emoji emoji-id="5438496463044752972">⭐</tg-emoji> Баланс: <b>{user["stars"]:,} Stars</b>\n'
        f'├ <tg-emoji emoji-id="5372926953978341366">👥</tg-emoji> Подтвержденных друзей: <b>{user["refs_count"]} чел.</b>\n'
        f'└ <tg-emoji emoji-id="5463071033256748994">🖼</tg-emoji> Ваш NFT в инвентаре: <b>{nft_status}</b>\n\n'
        f"👇 <b>Выберите нужный раздел на клавиатуре ниже:</b>"
    )
    return style_text(text)


# =====================================================================
# 🚀 ОБРАБОТЧИКИ
# =====================================================================
@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    user_id = message.from_user.id
    args = command.args
    invited_by = int(args) if (args and args.isdigit()) else 0

    register_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        invited_by=invited_by,
    )

    unsub = await check_user_subscriptions(user_id)
    if unsub:
        kb = []
        for idx, ad in enumerate(unsub, 1):
            kb.append([InlineKeyboardButton(text=f"📢 {idx}. Подписаться: {ad['title']}", url=ad["url"])])
        kb.append([InlineKeyboardButton(text="✅ Я подписался • Проверить", callback_data="check_start_subs")])
        sub_text = (
            f"🚀 <b>ДОСТУП К QUASAR DROP</b>\n\n"
            f"┌ ⚠️ Для защиты от ботов и получения бонуса <b>+50 ⭐</b>\n"
            f"└ подпишитесь на наши спонсорские каналы ниже:\n\n"
            f"<i>Реферал также засчитывается другу только после вашей подписки!</i>"
        )
        await message.answer(style_text(sub_text), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        return

    await try_verify_referral(user_id)
    user = get_user(user_id)
    await message.answer(main_menu_text(user), reply_markup=main_menu_kb(user_id))


@router.callback_query(F.data == "check_start_subs")
async def cb_check_start_subs(call: CallbackQuery):
    unsub = await check_user_subscriptions(call.from_user.id)
    if unsub:
        await call.answer("❌ Вы подписались не на все каналы! Подпишитесь и нажмите снова.", show_alert=True)
        return

    await try_verify_referral(call.from_user.id)
    user = get_user(call.from_user.id)
    await call.message.edit_text(main_menu_text(user), reply_markup=main_menu_kb(call.from_user.id))


@router.callback_query(F.data == "back_home")
async def cb_back_home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await try_verify_referral(call.from_user.id)
    user = get_user(call.from_user.id)
    await call.message.edit_text(main_menu_text(user), reply_markup=main_menu_kb(call.from_user.id))


NFT_DROPS = [
    {"name": "Snoop Dogg NFT 🐕", "price": "6.49 TON", "rarity": "Legendary"},
    {"name": "Swag Bag NFT 🎒", "price": "6.45 TON", "rarity": "Mythical"},
    {"name": "Liberty Figure NFT 🗽", "price": "6.00 TON", "rarity": "Immortal"},
]


@router.callback_query(F.data == "menu_nft_case")
async def cb_nft_case(call: CallbackQuery):
    user = get_user(call.from_user.id)
    webapp_url = f"{WEBAPP_URL.rstrip('/')}/case?user_id={call.from_user.id}"

    if not user["nft_won"]:
        text = (
            f"💎 <b>NFT КЕЙС (100% ГАРАНТ ДРОП)</b>\n"
            f"<i>Приглашай друзей, открывай бесплатный кейс и забирай эксклюзивный Telegram NFT!</i>\n\n"
            f"📦 <b>Что падает из кейса (3 коллекции):</b>\n"
            f"┌ 🐕 <b>Snoop Dogg</b> — <code>6.49 TON</code>\n"
            f"├ 🎒 <b>Swag Bag</b> — <code>6.45 TON</code>\n"
            f"└ 🗽 <b>Liberty Figure</b> — <code>6.00 TON</code>\n\n"
            f"🔥 <b>Шанс выпадения NFT: 100% (Гарант!)</b>\n"
            f"👇 Нажми <b>«Крутить бесплатно»</b> прямо в боте или открой 3D-рулетку:"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🟡 Крутить бесплатно (В боте)", callback_data="spin_nft_guaranteed")],
                [InlineKeyboardButton(text="🎰 Крутить в Mini-App Рулетке", web_app=WebAppInfo(url=webapp_url))],
                [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_home")],
            ]
        )
    else:
        refs = user["refs_count"]
        need = max(0, 25 - refs)
        progress_bar = "🟩" * min(10, int((refs / 25) * 10)) + "⬛" * (10 - min(10, int((refs / 25) * 10)))
        text = (
            f"💎 <b>ВАШ ВЫИГРАННЫЙ NFT В ИНВЕНТАРЕ!</b>\n\n"
            f"┌ 🎁 Подарок: <b>{user['nft_won']}</b>\n"
            f"├ 📌 Статус: <b>Ожидает отправки в профиль</b>\n"
            f"├ 👥 Условие бесплатного вывода: <b>25 друзей</b>\n"
            f"├ 📊 Ваш прогресс: <b>{refs} / 25 чел.</b>\n"
            f"└ {progress_bar} (Осталось позвать: <b>{need} чел.</b>)\n\n"
            f"⚠️ <i>Важно: друг засчитывается только тогда, когда перейдет по вашей ссылке и подпишется на наш ТГК!</i>"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📤 Вывести NFT в профиль", callback_data="withdraw_nft_now")],
                [InlineKeyboardButton(text="👥 Моя реферальная ссылка", callback_data="menu_refs")],
                [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_home")],
            ]
        )
    await call.message.edit_text(style_text(text), reply_markup=kb)


@router.callback_query(F.data == "spin_nft_guaranteed")
async def cb_spin_nft(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if user["nft_won"]:
        await call.answer("У вас уже выбит гарантированный NFT! Переходим к выводу.", show_alert=True)
        await cb_nft_case(call)
        return

    await call.message.edit_text(style_text("🎰 <b>Крутим NFT Кейс...</b>\n\n<code>[ 🗽 | 🐕 | 🎒 ]</code> ⏳"))
    await asyncio.sleep(1.2)
    won = random.choice(NFT_DROPS)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE users SET nft_won = ? WHERE user_id = ?",
            (f"{won['name']} ({won['price']})", call.from_user.id),
        )
        conn.commit()

    refs = user["refs_count"]
    need = max(0, 25 - refs)
    text = (
        f"🎉 <b>ПОЗДРАВЛЯЕМ! ВАМ ВЫПАЛ ГАРАНТ NFT!</b>\n\n"
        f"┌ 🏆 Дроп: <b>{won['name']}</b>\n"
        f"├ 💎 Оценка на маркете: <b>{won['price']}</b>\n"
        f"├ 🌟 Редкость: <b>{won['rarity']}</b>\n"
        f"└ 🔒 Для моментального вывода в ваш Telegram: <b>пригласите 25 друзей (Осталось: {need})</b>!"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 Забрать NFT себе", callback_data="withdraw_nft_now")],
            [InlineKeyboardButton(text="👥 Пригласить друзей", callback_data="menu_refs")],
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_home")],
        ]
    )
    await call.message.edit_text(style_text(text), reply_markup=kb)


@router.callback_query(F.data == "withdraw_nft_now")
async def cb_withdraw_nft_now(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if not user["nft_won"]:
        await call.answer("❌ Сначала выбейте NFT в кейсе!", show_alert=True)
        return

    if user["refs_count"] < 25:
        need = 25 - user["refs_count"]
        await call.answer(
            f"❌ Для вывода {user['nft_won']} нужно пригласить 25 друзей!\n"
            f"У вас сейчас: {user['refs_count']} из 25.\n"
            f"Позовите ещё {need} чел. (они должны подписаться на ТГК)!",
            show_alert=True,
        )
        return

    await call.answer("✅ Заявка на отправку NFT создана! Ожидайте передачу подарка.", show_alert=True)


SUB_CASE_ITEMS = [
    ("🧸 Подарок «Мишка» (15 ⭐)", 15),
    ("💝 Подарок «Сердце» (15 ⭐)", 15),
    ("🌹 Подарок «Роза» (25 ⭐)", 25),
    ("🎂 Подарок «Торт» (50 ⭐)", 50),
    ("🏆 Кубок Премиум (100 ⭐)", 100),
    ("🗽 Эксклюзив Liberty NFT (Бонус 250 ⭐)", 250),
]


@router.callback_query(F.data == "menu_sub_case")
async def cb_sub_case(call: CallbackQuery):
    ads = get_active_ads()
    user = get_user(call.from_user.id)

    kb = []
    for idx, ad in enumerate(ads, 1):
        kb.append([InlineKeyboardButton(text=f"📢 Спонсор #{idx}: {ad['title']}", url=ad["url"])])

    kb.append([InlineKeyboardButton(text="🎁 Проверить подписки и Открыть Кейс!", callback_data="open_sub_case")])
    kb.append([InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_home")])

    text = (
        f"🎁 <b>КЕЙС ЗА ПОДПИСКИ НА СПОНСОРОВ</b>\n\n"
        f"┌ 🧸 <b>Возможный дроп:</b> от Мишки (15 ⭐) до <b>Liberty NFT</b>!\n"
        f"├ 📋 <b>Условие открытия:</b> Подписаться на <b>всех</b> активных спонсоров ниже ({len(ads)} шт.)\n"
        f"└ ⚡ <b>Статус кейса:</b> {'✅ Доступен к открытию' if user['sub_case_claimed'] == 0 else '🔄 Уже открыт (доступен повтор за новых спонсоров)'}\n\n"
        f"👇 <b>Подпишитесь на все каналы ниже и жмите кнопку открытия:</b>"
    )
    await call.message.edit_text(style_text(text), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data == "open_sub_case")
async def cb_open_sub_case(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if user["sub_case_claimed"] == 1:
        await call.answer("❌ Вы уже открывали Кейс за подписки! Дождитесь обновления списка спонсоров.", show_alert=True)
        return

    unsub = await check_user_subscriptions(call.from_user.id, only_main=False)
    if unsub:
        names = ", ".join([a["title"] for a in unsub])
        await call.answer(f"❌ Вы не подписались на спонсоров: {names}!", show_alert=True)
        return

    weights = [35, 30, 18, 10, 5, 2]
    prize_name, stars_bonus = random.choices(SUB_CASE_ITEMS, weights=weights, k=1)[0]

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE users SET stars = stars + ?, sub_case_claimed = 1 WHERE user_id = ?",
            (stars_bonus, call.from_user.id),
        )
        conn.commit()

    await try_verify_referral(call.from_user.id)
    text = (
        f"🎉 <b>КЕЙС ЗА ПОДПИСКИ УСПЕШНО ОТКРЫТ!</b>\n\n"
        f"┌ 🎁 Вам выпал предмет: <b>{prize_name}</b>\n"
        f"├ ⭐ Зачислено на баланс: <b>+{stars_bonus} Stars</b>\n"
        f"└ 💼 Спасибо за подписку на всех спонсоров!"
    )
    await call.message.edit_text(style_text(text), reply_markup=back_home_kb())


@router.callback_query(F.data == "menu_withdraw")
async def cb_withdraw_menu(call: CallbackQuery):
    user = get_user(call.from_user.id)
    stars = user["stars"]
    refs = user["refs_count"]

    text = (
        f"📤 <b>ЦЕНТР ВЫВОДА TELEGRAM STARS & NFT</b>\n\n"
        f"┌ ⭐ Ваш баланс: <b>{stars:,} Stars</b>\n"
        f"├ 💎 Минимальная сумма вывода: <b>1,000 Stars</b>\n"
        f"├ 👥 Подтвержденных рефералов: <b>{refs} чел.</b>\n"
        f"└ 🖼 Выигранный NFT: <b>{user['nft_won'] or 'Нет'}</b>\n\n"
        f"👇 <b>Выберите, что хотите вывести:</b>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Вывести Звезды (От 1000 ⭐)", callback_data="do_withdraw_stars")],
            [InlineKeyboardButton(text="💎 Вывести NFT (За 25 друзей)", callback_data="withdraw_nft_now")],
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_home")],
        ]
    )
    await call.message.edit_text(style_text(text), reply_markup=kb)


@router.callback_query(F.data == "do_withdraw_stars")
async def cb_do_withdraw_stars(call: CallbackQuery):
    user = get_user(call.from_user.id)
    stars = user["stars"]
    refs = user["refs_count"]

    if stars < 1000:
        need_stars = 1000 - stars
        msg = (
            f"❌ <b>НЕДОСТАТОЧНО ЗВЕЗД ДЛЯ ВЫВОДА!</b>\n\n"
            f"┌ ⭐ Минимальный вывод: <b>1,000 Stars</b>\n"
            f"├ 👛 У вас сейчас: <b>{stars} Stars</b>\n"
            f"└ 📈 Осталось накопить: <b>{need_stars} Stars</b>\n\n"
            f"💡 <i>Выполняйте задания спонсоров и приглашайте друзей (+{REF_REWARD_STARS} ⭐ за друга)!</i>"
        )
        await call.message.edit_text(style_text(msg), reply_markup=back_home_kb())
        return

    if refs < 10:
        need_first_stage = 10 - refs
        msg = (
            f"⚠️ <b>ПОДТВЕРЖДЕНИЕ АКТИВНОСТИ АККАУНТА (ШАГ 1/2)</b>\n\n"
            f"┌ ✅ Баланс <b>{stars:,} Stars</b> готов к отправке!\n"
            f"├ 🔒 Для защиты от мультиаккаунтов <b>позовите ещё {need_first_stage} человек для вывода!</b>\n"
            f"└ 📊 Приглашено сейчас: <b>{refs} / 10 чел.</b>\n\n"
            f"<i>Друзья обязательно должны подписаться на наш ТГК при входе в бота!</i>"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="👥 Получить ссылку для приглашения", callback_data="menu_refs")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_withdraw")],
            ]
        )
        await call.message.edit_text(style_text(msg), reply_markup=kb)
        return

    if refs < 30:
        need_second_stage = 30 - refs
        msg = (
            f"🔥 <b>ФИНАЛЬНЫЙ ЭТАП ПЕРЕД ВЫПЛАТОЙ (ШАГ 2/2)</b>\n\n"
            f"┌ 🎉 Первые 10 друзей успешно подтверждены!\n"
            f"├ 🚀 <b>Осталось позвать последние {need_second_stage} человек для автоматического вывода {stars:,} Stars!</b>\n"
            f"└ 📊 Общий прогресс: <b>{refs} / 30 чел. (Финальные 20)</b>\n\n"
            f"💎 <i>Как только счётчик достигнет 30, выплата уйдет вам моментально!</i>"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="👥 Пригласить оставшихся друзей", callback_data="menu_refs")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_withdraw")],
            ]
        )
        await call.message.edit_text(style_text(msg), reply_markup=kb)
        return

    await call.answer("✅ Ваша заявка поставлена в очередь на выплату администратором!", show_alert=True)


@router.callback_query(F.data == "menu_earn")
async def cb_menu_earn(call: CallbackQuery):
    ads = get_active_ads()
    user_id = call.from_user.id

    with sqlite3.connect(DB_PATH) as conn:
        done_rows = conn.execute("SELECT ad_id FROM completed_ads WHERE user_id = ?", (user_id,)).fetchall()
        done_ids = {r[0] for r in done_rows}

    available_ads = [a for a in ads if a["id"] not in done_ids]
    if not available_ads:
        text = (
            f"⭐ <b>ЗАДАНИЯ НА ЗВЕЗДЫ</b>\n\n"
            f"┌ ✅ Вы выполнили все доступные задания на данный момент!\n"
            f"└ 👥 Приглашайте друзей и получайте по <b>+{REF_REWARD_STARS} ⭐</b> за каждого!"
        )
        await call.message.edit_text(style_text(text), reply_markup=back_home_kb())
        return

    kb = []
    for ad in available_ads:
        kb.append(
            [
                InlineKeyboardButton(
                    text=f"➕ {ad['title']} (+{ad['reward']} ⭐)",
                    callback_data=f"view_ad_{ad['id']}",
                )
            ]
        )
    kb.append([InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_home")])

    text = (
        f"⭐ <b>ДОСТУПНЫЕ ЗАДАНИЯ ({len(available_ads)} шт.)</b>\n\n"
        f"┌ 📌 Выберите задание ниже, перейдите по ссылке\n"
        f"└ и нажмите <b>«Проверить выполнение»</b> для получения Stars!"
    )
    await call.message.edit_text(style_text(text), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("view_ad_"))
async def cb_view_ad(call: CallbackQuery):
    ad_id = int(call.data.split("_")[-1])
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        ad = conn.execute("SELECT * FROM ads WHERE id = ?", (ad_id,)).fetchone()

    if not ad:
        await call.answer("Задание уже завершено!", show_alert=True)
        return

    text = (
        f"📌 <b>ЗАДАНИЕ: {ad['title']}</b>\n\n"
        f"┌ 🔗 Ссылка: {ad['url']}\n"
        f"├ ⭐ Награда: <b>+{ad['reward']} Stars</b>\n"
        f"└ 👥 Осталось мест: <b>{ad['limit_users'] - ad['current_users'] if ad['limit_users'] > 0 else 'Без лимита'}</b>\n\n"
        f"1️⃣ Перейдите по кнопке ниже и подпишитесь/запустите.\n"
        f"2️⃣ Вернитесь сюда и нажмите <b>«Проверить и забрать +{ad['reward']} ⭐»</b>."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Перейти к выполнению", url=ad["url"])],
            [InlineKeyboardButton(text=f"✅ Проверить (+{ad['reward']} ⭐)", callback_data=f"claim_ad_{ad['id']}")],
            [InlineKeyboardButton(text="🔙 К списку заданий", callback_data="menu_earn")],
        ]
    )
    await call.message.edit_text(style_text(text), reply_markup=kb)


@router.callback_query(F.data.startswith("claim_ad_"))
async def cb_claim_ad(call: CallbackQuery):
    ad_id = int(call.data.split("_")[-1])
    user_id = call.from_user.id

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        ad = conn.execute("SELECT * FROM ads WHERE id = ?", (ad_id,)).fetchone()
        already = conn.execute(
            "SELECT 1 FROM completed_ads WHERE user_id = ? AND ad_id = ?", (user_id, ad_id)
        ).fetchone()

    if not ad or already:
        await call.answer("❌ Вы уже получили награду за это задание!", show_alert=True)
        return

    ch_id = (ad["channel_id"] or "").strip()
    if ch_id and ch_id.lower() != "нет":
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status in ("left", "kicked"):
                await call.answer("❌ Вы еще не подписались на канал! Подпишитесь и повторите.", show_alert=True)
                return
        except Exception:
            pass

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR IGNORE INTO completed_ads (user_id, ad_id) VALUES (?, ?)", (user_id, ad_id))
        conn.execute("UPDATE ads SET current_users = current_users + 1 WHERE id = ?", (ad_id,))
        conn.execute("UPDATE users SET stars = stars + ? WHERE user_id = ?", (ad["reward"], user_id))
        conn.commit()

    await try_verify_referral(user_id)
    await call.answer(f"🎉 Начислено +{ad['reward']} Stars!", show_alert=True)
    await cb_menu_earn(call)


@router.callback_query(F.data == "menu_refs")
async def cb_menu_refs(call: CallbackQuery):
    user = get_user(call.from_user.id)
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={call.from_user.id}"

    text = (
        f"👥 <b>ПАРТНЕРСКАЯ ПРОГРАММА QUASAR DROP</b>\n\n"
        f"┌ 🔗 <b>Ваша личная ссылка:</b>\n"
        f"├ <code>{ref_link}</code>\n"
        f"├ ⭐ Награда за каждого друга: <b>+{REF_REWARD_STARS} Stars</b>\n"
        f"├ ✅ Подтвержденных рефералов: <b>{user['refs_count']} чел.</b>\n"
        f"└ 💎 До вывода Гарант NFT: <b>{max(0, 25 - user['refs_count'])} чел.</b>\n\n"
        f"⚠️ <b>ВАЖНОЕ ПРАВИЛО:</b>\n"
        f"<i>Реферал засчитывается ТОЛЬКО тогда, когда ваш друг перешел по ссылке И подписался на наш обязательный ТГК!</i>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📨 Отправить ссылку другу",
                    url=f"https://t.me/share/url?url={ref_link}&text=Забирай%20бесплатный%20NFT%20и%20Telegram%20Stars!",
                )
            ],
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_home")],
        ]
    )
    await call.message.edit_text(style_text(text), reply_markup=kb)


@router.callback_query(F.data == "menu_profile")
async def cb_menu_profile(call: CallbackQuery):
    user = get_user(call.from_user.id)
    dt = datetime.fromtimestamp(user["joined_at"]).strftime("%d.%m.%Y %H:%M")
    text = (
        f"👛 <b>ЛИЧНЫЙ КАБИНЕТ ПОЛЬЗОВАТЕЛЯ</b>\n\n"
        f"┌ 👤 Имя: <b>{user['first_name']}</b>\n"
        f"├ 🆔 ID: <code>{user['user_id']}</code>\n"
        f"├ ⭐ Баланс: <b>{user['stars']:,} Stars</b>\n"
        f"├ 👥 Приглашено друзей (с ТГК): <b>{user['refs_count']} чел.</b>\n"
        f"├ 🖼 Выбитый NFT: <b>{user['nft_won'] or 'Не выбит'}</b>\n"
        f"├ 🎁 Кейс за подписки: <b>{'Открыт ✅' if user['sub_case_claimed'] else 'Доступен 🔓'}</b>\n"
        f"└ 📅 Регистрация: <code>{dt}</code>"
    )
    await call.message.edit_text(style_text(text), reply_markup=back_home_kb())


# =====================================================================
# 👑 АДМИН-ПАНЕЛЬ
# =====================================================================
class AdminStates(StatesGroup):
    ad_title = State()
    ad_url = State()
    ad_check = State()
    ad_reward = State()
    ad_hours = State()
    ad_limit = State()

    dm_user_id = State()
    dm_text = State()

    broadcast_text = State()


def admin_kb() -> InlineKeyboardMarkup:
    mode = get_font_mode().upper()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Поставить рекламу (Часы / Уч. / Реф)", callback_data="adm_add_ad")],
            [InlineKeyboardButton(text="📊 Список рекламы (Прогресс / Удалить)", callback_data="adm_list_ads")],
            [InlineKeyboardButton(text="✉️ Написать челу лично в боте", callback_data="adm_dm_user")],
            [InlineKeyboardButton(text=f"🔤 Сменить шрифт для ворка [{mode}]", callback_data="adm_toggle_font")],
            [
                InlineKeyboardButton(text="📢 Рассылка всем", callback_data="adm_broadcast"),
                InlineKeyboardButton(text="📥 Выгрузить БД (.csv)", callback_data="adm_export_db"),
            ],
            [InlineKeyboardButton(text="🔙 В меню бота", callback_data="back_home")],
        ]
    )


def get_admin_stats_text() -> str:
    with sqlite3.connect(DB_PATH) as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active_refs = conn.execute("SELECT COUNT(*) FROM users WHERE ref_verified = 1").fetchone()[0]
        total_stars = conn.execute("SELECT COALESCE(SUM(stars), 0) FROM users").fetchone()[0]
    active_ads = len(get_active_ads())
    font_mode = get_font_mode()

    text = (
        f"👑 <b>АДМИН-ПАНЕЛЬ QUASAR DROP (/admins)</b>\n\n"
        f"┌ 👥 Всего пользователей: <b>{total_users} чел.</b>\n"
        f"├ 🔥 Активных рефералов (с ТГК): <b>{active_refs} чел.</b>\n"
        f"├ ⭐ Звезд на балансах: <b>{total_stars:,} Stars</b>\n"
        f"├ 📢 Активной рекламы: <b>{active_ads} шт.</b>\n"
        f"└ 🔤 Текущий шрифт бота: <code>{font_mode}</code>"
    )
    return style_text(text)


@router.message(Command("admins"))
async def cmd_admins(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer(
            f"⚠️ Ваш Telegram ID: <code>{message.from_user.id}</code>.\n"
            f"Добавьте его в переменную окружения <code>ADMIN_IDS</code> на Render, чтобы открыть админку."
        )
        return
    await message.answer(get_admin_stats_text(), reply_markup=admin_kb())


@router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    await state.clear()
    await call.message.edit_text(get_admin_stats_text(), reply_markup=admin_kb())


@router.callback_query(F.data == "adm_toggle_font")
async def cb_adm_toggle_font(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    modes = ["normal", "mono", "bold", "double", "smallcaps"]
    current = get_font_mode()
    next_mode = modes[(modes.index(current) + 1) % len(modes)]

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE settings SET value = ? WHERE key = 'font_mode'", (next_mode,))
        conn.commit()

    await call.answer(f"🔤 Шрифт бота изменен на: {next_mode.upper()}", show_alert=True)
    await call.message.edit_text(get_admin_stats_text(), reply_markup=admin_kb())


@router.callback_query(F.data == "adm_dm_user")
async def cb_adm_dm_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(AdminStates.dm_user_id)
    await call.message.edit_text(
        "✉️ <b>ЛИЧНОЕ СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЮ</b>\n\n"
        "Введите <b>Telegram ID</b> пользователя, которому хотите написать от имени бота:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")]]
        ),
    )


@router.message(AdminStates.dm_user_id)
async def step_dm_user_id(message: Message, state: FSMContext):
    if not message.text or not message.text.strip().isdigit():
        await message.answer("❌ Введите корректный числовой ID пользователя!")
        return
    await state.update_data(target_id=int(message.text.strip()))
    await state.set_state(AdminStates.dm_text)
    await message.answer(
        "📝 Теперь отправьте <b>текст сообщения</b>, который нужно доставить этому пользователю:"
    )


@router.message(AdminStates.dm_text)
async def step_dm_send(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data["target_id"]
    await state.clear()

    try:
        dm_formatted = (
            f"📩 <b>СООБЩЕНИЕ ОТ АДМИНИСТРАЦИИ QUASAR DROP:</b>\n\n"
            f"{message.html_text}\n\n"
            f"<i>Вы можете ответить на это сообщение прямо в чате или следовать инструкциям выше.</i>"
        )
        await bot.send_message(target_id, style_text(dm_formatted))
        await message.answer(
            f"✅ Сообщение успешно доставлено пользователю <code>{target_id}</code>!",
            reply_markup=admin_kb(),
        )
    except Exception as e:
        await message.answer(
            f"❌ Не удалось отправить сообщение пользователю <code>{target_id}</code> (возможно, он заблокировал бота).\nОшибка: {e}",
            reply_markup=admin_kb(),
        )


@router.callback_query(F.data == "adm_add_ad")
async def cb_adm_add_ad(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(AdminStates.ad_title)
    await call.message.edit_text(
        "1️⃣ <b>Название рекламы / канала:</b>\n(Например: <code>Neroov Music</code>):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")]]
        ),
    )


@router.message(AdminStates.ad_title)
async def step_ad_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AdminStates.ad_url)
    await message.answer("2️⃣ <b>Отправьте ссылку на канал или бота:</b>\n(Например: <code>https://t.me/+pKYve...</code>):")


@router.message(AdminStates.ad_url)
async def step_ad_url(message: Message, state: FSMContext):
    await state.update_data(url=message.text.strip())
    await state.set_state(AdminStates.ad_check)
    await message.answer(
        "3️⃣ <b>Проверка подписки:</b>\n"
        "• Если это ТГК, где бот админ (нужно для засчитывания рефералов и Кейса за подписки) — скиньте <code>@username</code> канала или его ID (<code>-100...</code>).\n"
        "• Если это реф. ссылка на бота или ссылка по заявкам без проверки — напишите: <code>нет</code>"
    )


@router.message(AdminStates.ad_check)
async def step_ad_check(message: Message, state: FSMContext):
    await state.update_data(channel_id=message.text.strip())
    await state.set_state(AdminStates.ad_reward)
    await message.answer("4️⃣ <b>Сколько звезд (⭐) давать за выполнение?</b> (Например: <code>10</code>):")


@router.message(AdminStates.ad_reward)
async def step_ad_reward(message: Message, state: FSMContext):
    val = int(message.text.strip()) if message.text.strip().isdigit() else 10
    await state.update_data(reward=val)
    await state.set_state(AdminStates.ad_hours)
    await message.answer("5️⃣ <b>На сколько часов ставим рекламу?</b>\n(Например: <code>24</code>, или <code>0</code> — без ограничения по времени):")


@router.message(AdminStates.ad_hours)
async def step_ad_hours(message: Message, state: FSMContext):
    val = int(message.text.strip()) if message.text.strip().isdigit() else 0
    await state.update_data(hours=val)
    await state.set_state(AdminStates.ad_limit)
    await message.answer("6️⃣ <b>Лимит по участникам: сколько человек должны выполнить?</b>\n(Например: <code>300</code>, или <code>0</code> — без лимита):")


@router.message(AdminStates.ad_limit)
async def step_ad_limit(message: Message, state: FSMContext):
    limit_users = int(message.text.strip()) if message.text.strip().isdigit() else 0
    data = await state.get_data()
    await state.clear()

    is_main = 1 if data["channel_id"].lower() != "нет" else 0
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO ads (title, url, channel_id, reward, hours, limit_users, current_users, created_at, is_main_tgk)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                data["title"],
                data["url"],
                data["channel_id"],
                data["reward"],
                data["hours"],
                limit_users,
                int(time.time()),
                is_main,
            ),
        )
        conn.execute("UPDATE users SET sub_case_claimed = 0")
        conn.commit()

    summary = (
        f"✅ <b>Реклама успешно поставлена!</b>\n\n"
        f"┌ 📌 Название: <b>{data['title']}</b>\n"
        f"├ 🔗 Ссылка: {data['url']}\n"
        f"├ ⭐ Награда: <b>+{data['reward']} ⭐</b>\n"
        f"├ ⏳ На часов: <b>{data['hours'] if data['hours'] > 0 else 'Без лимита'}</b>\n"
        f"└ 👥 Лимит уч.: <b>{limit_users if limit_users > 0 else 'Без лимита'}</b>"
    )
    await message.answer(style_text(summary), reply_markup=admin_kb())


@router.callback_query(F.data == "adm_list_ads")
async def cb_adm_list_ads(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    ads = get_active_ads()
    if not ads:
        await call.answer("Активной рекламы сейчас нет!", show_alert=True)
        return

    kb = []
    text_lines = ["📊 <b>АКТИВНАЯ РЕКЛАМА И СПОНСОРЫ:</b>\n"]
    for ad in ads:
        lim = f"{ad['current_users']}/{ad['limit_users']}" if ad["limit_users"] > 0 else f"{ad['current_users']}/∞"
        text_lines.append(f"• <b>{ad['title']}</b> — Выполнено: <code>{lim}</code> (Проверка: <code>{ad['channel_id']}</code>)")
        kb.append([InlineKeyboardButton(text=f"🗑 Удалить: {ad['title']} ({lim})", callback_data=f"del_ad_{ad['id']}")])

    kb.append([InlineKeyboardButton(text="🔙 Назад в админку", callback_data="admin_panel")])
    await call.message.edit_text("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("del_ad_"))
async def cb_del_ad(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    ad_id = int(call.data.split("_")[-1])
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM ads WHERE id = ?", (ad_id,))
        conn.commit()
    await call.answer("🗑 Реклама удалена!", show_alert=True)
    await cb_adm_list_ads(call)


@router.callback_query(F.data == "adm_broadcast")
async def cb_adm_broadcast(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(AdminStates.broadcast_text)
    await call.message.edit_text(
        "📢 <b>РАССЫЛКА ВСЕМ ПОЛЬЗОВАТЕЛЯМ</b>\n\nОтправьте текст, который получат все пользователи бота:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")]]
        ),
    )


@router.message(AdminStates.broadcast_text)
async def step_broadcast_send(message: Message, state: FSMContext):
    await state.clear()
    with sqlite3.connect(DB_PATH) as conn:
        users = conn.execute("SELECT user_id FROM users").fetchall()

    sent = 0
    for (uid,) in users:
        try:
            await bot.send_message(uid, style_text(message.html_text))
            sent += 1
            await asyncio.sleep(0.04)
        except Exception:
            pass

    await message.answer(f"✅ Рассылка завершена! Доставлено: <b>{sent}</b> чел.", reply_markup=admin_kb())


@router.callback_query(F.data == "adm_export_db")
async def cb_adm_export_db(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT user_id, username, first_name, stars, refs_count, nft_won, joined_at FROM users"
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["user_id", "username", "first_name", "stars", "refs_count", "nft_won", "joined_at"])
    writer.writerows(rows)

    file_bytes = output.getvalue().encode("utf-8-sig")
    doc = BufferedInputFile(file_bytes, filename="quasar_users.csv")
    await call.message.answer_document(doc, caption="📥 Выгрузка базы пользователей QUASAR DROP")
    await call.answer()


# =====================================================================
# 🌐 MINI-APP HTML
# =====================================================================
MINI_APP_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>NFT Кейс • QUASAR DROP</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
    body { background: radial-gradient(circle at top, #2c2208 0%, #0d0d0f 48%, #09090b 100%); color: #fff; min-height: 100vh; padding: 20px 16px 40px; overflow-x: hidden; }
    .header { margin-bottom: 18px; }
    .header h1 { font-size: 28px; font-weight: 800; letter-spacing: -0.5px; }
    .header p { color: #8c8c96; font-size: 14px; margin-top: 4px; line-height: 1.35; }
    .roulette-wrap { position: relative; margin: 22px 0; padding: 18px 0; overflow: hidden; }
    .pointer-top { width: 0; height: 0; border-left: 9px solid transparent; border-right: 9px solid transparent; border-top: 13px solid #f7b928; margin: 0 auto 10px; filter: drop-shadow(0 0 8px #f7b928); }
    .pointer-bottom { width: 0; height: 0; border-left: 9px solid transparent; border-right: 9px solid transparent; border-bottom: 13px solid #f7b928; margin: 10px auto 0; filter: drop-shadow(0 0 8px #f7b928); }
    .track-container { width: 100%; overflow: hidden; position: relative; }
    .track { display: flex; gap: 14px; transition: transform 4.2s cubic-bezier(0.12, 0.8, 0.18, 1); will-change: transform; }
    .item-card { min-width: 145px; height: 155px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.09); border-radius: 22px; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 14px; flex-shrink: 0; box-shadow: inset 0 1px 0 rgba(255,255,255,0.1); }
    .item-card .emoji-art { font-size: 64px; filter: drop-shadow(0 8px 16px rgba(0,0,0,0.5)); margin-bottom: 12px; }
    .item-card .title { font-size: 14px; font-weight: 700; color: #f1f1f5; }
    .spin-btn { width: 100%; background: linear-gradient(90deg, #ffdf40 0%, #f5a623 100%); color: #111; font-weight: 800; font-size: 17px; border: none; border-radius: 999px; padding: 17px; cursor: pointer; box-shadow: 0 8px 25px rgba(245, 166, 35, 0.35); transition: transform 0.15s ease, opacity 0.2s; }
    .spin-btn:active { transform: scale(0.98); }
    .spin-btn:disabled { opacity: 0.55; cursor: not-allowed; }
    .sub-hint { text-align: center; color: #7c7c85; font-size: 13px; margin-top: 10px; line-height: 1.35; }
    .drops-header { display: flex; justify-content: space-between; align-items: center; margin: 28px 0 14px; }
    .drops-header h2 { font-size: 18px; font-weight: 800; }
    .drops-header span { font-size: 13px; color: #7c7c85; }
    .drops-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
    .drop-box { border-radius: 18px; padding: 10px; position: relative; display: flex; flex-direction: column; align-items: center; text-align: center; }
    .drop-box.green { background: linear-gradient(160deg, #27a376 0%, #17382e 100%); }
    .drop-box.orange { background: linear-gradient(160deg, #b87b64 0%, #3d2520 100%); }
    .drop-box.pink { background: linear-gradient(160deg, #c9467d 0%, #3b1728 100%); }
    .ton-badge { align-self: flex-start; background: rgba(0,0,0,0.45); border-radius: 99px; padding: 3px 8px; font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; gap: 4px; margin-bottom: 6px; }
    .drop-box .big-icon { font-size: 46px; margin: 6px 0 10px; }
    .drop-box .d-name { font-size: 12px; font-weight: 700; width: 100%; text-align: left; }
    .drop-box .d-sub { font-size: 10px; color: rgba(255,255,255,0.6); width: 100%; text-align: left; }
    .modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.82); backdrop-filter: blur(8px); align-items: center; justify-content: center; padding: 20px; z-index: 99; }
    .modal-card { background: #18181c; border: 1px solid rgba(255,215,0,0.3); border-radius: 26px; padding: 24px 20px; text-align: center; max-width: 340px; width: 100%; box-shadow: 0 20px 50px rgba(0,0,0,0.8); }
    .modal-card .win-icon { font-size: 74px; margin-bottom: 12px; }
    .modal-card h3 { font-size: 22px; font-weight: 800; color: #ffca28; margin-bottom: 8px; }
    .modal-card p { font-size: 14px; color: #b5b5be; line-height: 1.45; margin-bottom: 18px; }
</style>
</head>
<body>
    <div class="header">
        <h1>NFT Кейс</h1>
        <p>Приглашай друзей, открывай бесплатный кейс и получай подарки.</p>
    </div>
    <div class="roulette-wrap">
        <div class="pointer-top"></div>
        <div class="track-container">
            <div class="track" id="rouletteTrack"></div>
        </div>
        <div class="pointer-bottom"></div>
    </div>
    <button class="spin-btn" id="spinBtn" onclick="spinRoulette()">Крутить бесплатно</button>
    <div class="sub-hint">Гарантированный дроп NFT! Вывод открывается за приглашение 25 друзей в бота.</div>
    <div class="drops-header">
        <h2>Что может выпасть</h2>
        <span>3 коллекции</span>
    </div>
    <div class="drops-grid">
        <div class="drop-box green">
            <div class="ton-badge">💎 6.49</div>
            <div class="big-icon">🐕</div>
            <div class="d-name">Snoop Dogg</div>
            <div class="d-sub">Коллекция</div>
        </div>
        <div class="drop-box orange">
            <div class="ton-badge">💎 6.45</div>
            <div class="big-icon">🎒</div>
            <div class="d-name">Swag Bag</div>
            <div class="d-sub">Коллекция</div>
        </div>
        <div class="drop-box pink">
            <div class="ton-badge">💎 6</div>
            <div class="big-icon">🗽</div>
            <div class="d-name">Liberty Figure</div>
            <div class="d-sub">Коллекция</div>
        </div>
    </div>
    <div class="modal" id="winModal">
        <div class="modal-card">
            <div class="win-icon" id="winIcon">🐕</div>
            <h3 id="winTitle">Snoop Dogg NFT</h3>
            <p>Подарок зарезервирован за вашим аккаунтом! Пригласите <b>25 друзей</b> в бота (с подпиской на ТГК), чтобы моментально вывести NFT в свой профиль.</p>
            <button class="spin-btn" onclick="closeAndReturn()">Забрать в боте</button>
        </div>
    </div>
<script>
    const tg = window.Telegram.WebApp;
    tg.expand();
    const items = [
        { name: "Liberty Figure", icon: "🗽", price: "6.00 TON" },
        { name: "Snoop Dogg", icon: "🐕", price: "6.49 TON" },
        { name: "Swag Bag", icon: "🎒", price: "6.45 TON" }
    ];
    const track = document.getElementById('rouletteTrack');
    const totalCards = 35;
    const winIndex = 27;
    let winningItem = items[Math.floor(Math.random() * items.length)];
    for (let i = 0; i < totalCards; i++) {
        const it = (i === winIndex) ? winningItem : items[i % items.length];
        const card = document.createElement('div');
        card.className = 'item-card';
        card.innerHTML = `<div class="emoji-art">${it.icon}</div><div class="title">${it.name}</div>`;
        track.appendChild(card);
    }
    async function spinRoulette() {
        const btn = document.getElementById('spinBtn');
        btn.disabled = true;
        btn.innerText = "Крутим...";
        const cardWidth = 159;
        const centerOffset = (window.innerWidth / 2) - (145 / 2) - 16;
        const targetX = -(winIndex * cardWidth) + centerOffset;
        track.style.transform = `translateX(${targetX}px)`;
        const params = new URLSearchParams(window.location.search);
        const uid = params.get("user_id") || (tg.initDataUnsafe?.user?.id) || 0;
        try {
            await fetch(`/api/spin_nft?user_id=${uid}&nft=${encodeURIComponent(winningItem.name + ' (' + winningItem.price + ')')}`);
        } catch (e) {}
        setTimeout(() => {
            document.getElementById('winIcon').innerText = winningItem.icon;
            document.getElementById('winTitle').innerText = winningItem.name + " (" + winningItem.price + ")";
            document.getElementById('winModal').style.display = 'flex';
        }, 4400);
    }
    function closeAndReturn() {
        tg.close();
    }
</script>
</body>
</html>
"""


async def handle_ping(request: web.Request):
    return web.Response(text="QUASAR DROP BOT IS ALIVE 24/7!", status=200)


async def handle_webapp_case(request: web.Request):
    return web.Response(text=MINI_APP_HTML, content_type="text/html")


async def handle_api_spin(request: web.Request):
    user_id = request.query.get("user_id", "0")
    nft_name = request.query.get("nft", "Snoop Dogg NFT (6.49 TON)")
    if user_id.isdigit() and int(user_id) > 0:
        uid = int(user_id)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE users SET nft_won = COALESCE(nft_won, ?) WHERE user_id = ?", (nft_name, uid))
            conn.commit()
    return web.json_response({"ok": True})


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/case", handle_webapp_case)
    app.router.add_get("/api/spin_nft", handle_api_spin)

    port = int(os.environ.get("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"🌐 Web server & Mini-App started on port {port}")


async def main():
    init_db()
    await start_web_server()
    
    # 🛑 ЖЕСТКИЙ СБРОС ВСЕХ КОНФЛИКТОВ И ОЧЕРЕДЕЙ НА СТОРОНЕ TELEGRAM
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("🧹 Старые вебхуки и зависшие запросы успешно удалены!")
    except Exception as e:
        logging.warning(f"⚠️ Не удалось удалить вебхук: {e}")

    logging.info("🚀 QUASAR DROP Bot запущен!")
    
    # Запускаем поллинг с принудительным сбросом старых апдейтов
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")
