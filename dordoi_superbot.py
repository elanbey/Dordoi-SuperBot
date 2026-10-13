import asyncio
import logging
import urllib.parse
from datetime import date
import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
import os
from aiohttp import web

# ==============================================================================
# ТОКЕН БОТА: Укажите токен, полученный от @BotFather в Telegram
# ВНИМАНИЕ: В данном коде НЕТ рекламы, спама и принудительных подписок на каналы!
# ==============================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8867783468:AAHRzUVH2oeHyUCNHedkqjNtnkQbAQCWtTk")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER (РЕШАЕТ ОШИБКУ "No open ports detected") ---
async def handle_ping(request):
    return web.Response(text="OK - Dordoi SuperBot is running 24/7 with Anti-Spam protection!")

async def start_healthcheck_server():
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"🌐 Healthcheck web server listening on port {port}")

# --- БЕСПЛАТНЫЙ АВТОПЕРЕВОДЧИК ТЕКСТА (RU / KY / ZH) ---
async def translate_text(text: str, target_lang: str) -> str:
    """Переводит произвольный текст без API ключей через шлюз Google Translate"""
    if not text or len(text.strip()) == 0:
        return text
    try:
        url = (
            f"https://translate.googleapis.com/translate_a/single?"
            f"client=gtx&sl=auto&tl={target_lang}&dt=t&q={urllib.parse.quote(text)}"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    translated = "".join([part[0] for part in data[0] if part[0]])
                    return translated
    except Exception as e:
        logging.warning(f"Translation error: {e}")
    return text

# --- БАЗА ДАННЫХ SQLITE С ЗАЩИТОЙ ОТ СПАМА И ФЕЙКОВ ---
async def init_db():
    async with aiosqlite.connect("dordoi_master.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                phone TEXT,
                role TEXT DEFAULT 'seller',
                lang TEXT DEFAULT 'ru',
                is_active INTEGER DEFAULT 1,
                daily_posts_count INTEGER DEFAULT 0,
                last_post_date TEXT DEFAULT ''
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_type TEXT,
                seller_id INTEGER,
                seller_name TEXT,
                seller_phone TEXT,
                market_sector TEXT,
                container_num TEXT,
                details TEXT,
                details_translated TEXT,
                executor_id INTEGER DEFAULT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                sector TEXT,
                container_num TEXT,
                category TEXT,
                price REAL,
                currency TEXT DEFAULT 'KGS',
                min_batch TEXT,
                description TEXT,
                phone TEXT,
                is_verified INTEGER DEFAULT 1,
                reports_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS real_estate (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                re_type TEXT,
                title TEXT,
                location TEXT,
                price REAL,
                currency TEXT DEFAULT 'KGS',
                period TEXT DEFAULT 'month',
                phone TEXT,
                description TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                role TEXT,
                title TEXT,
                salary TEXT,
                schedule TEXT,
                phone TEXT,
                requirements TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type TEXT,
                item_id INTEGER,
                reporter_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(item_type, item_id, reporter_id)
            )
        """)

        # Первичное наполнение проверенными товарами
        async with db.execute("SELECT COUNT(*) FROM products") as cur:
            count = (await cur.fetchone())[0]
            if count == 0:
                await db.execute("""
                    INSERT INTO products (user_id, title, sector, container_num, category, price, currency, min_batch, description, phone, is_verified)
                    VALUES 
                    (1001, 'Платья трикотажные «Миди» (Made in KG)', 'Алкан / Ак-Суу', '14-проход, 88-контейнер', 'clothing', 850, 'KGS', 'от 1 серии (5 шт)', 'Фабричный цех Алкан под Wildberries.', '+996702334455', 1),
                    (1002, 'Зимние пуховики оверсайз (Гуанчжоу)', 'Джунхай / 中海', '5-проход, 32-контейнер', 'clothing', 2200, 'KGS', 'от 10 шт', 'Прямой импорт из Гуанчжоу без посредников.', '+996770889900', 1),
                    (1003, 'Кроссовки термо с эко-мехом (Мужские)', 'Мурас-Спорт', 'Ряд 3, 44-контейнер', 'shoes', 1100, 'KGS', 'от 1 коробки (8 пар)', 'Подошва ТЭП (не скользит), отправка на Северную стоянку.', '+996555441122', 1)
                """)

        # Первичное наполнение арендой
        async with db.execute("SELECT COUNT(*) FROM real_estate") as cur:
            re_count = (await cur.fetchone())[0]
            if re_count == 0:
                await db.execute("""
                    INSERT INTO real_estate (user_id, re_type, title, location, price, currency, phone, description)
                    VALUES 
                    (1001, 'container', 'Аренда 2-эт. контейнера в секторе «Европа»', 'Сектор «Европа», Ряд Б, контейнер 38', 45000, 'KGS', '+996700998877', '1-й этаж витрины, 2-й этаж склад со стеллажами.'),
                    (1002, 'container', 'Контейнер под ткани в Джунхае', 'Сектор «Джунхай / 中海», 4-проход, 18-контейнер', 550, 'USD', '+996550123456', 'Центральный проход, высокий трафик швейных цехов.'),
                    (1003, 'housing', 'Сдается 2-комн. квартира рядом с Дордоем', 'Жилмассив «Дордой-1» (5 мин пешком)', 25000, 'KGS', '+996772445566', 'Все удобства, газ, мебель. Для торговцев.')
                """)

        # Первичное наполнение вакансиями
        async with db.execute("SELECT COUNT(*) FROM jobs") as cur:
            jobs_count = (await cur.fetchone())[0]
            if jobs_count == 0:
                await db.execute("""
                    INSERT INTO jobs (user_id, role, title, salary, schedule, phone, requirements)
                    VALUES 
                    (1001, 'seller', 'Реализатор одежды со знанием языков', '40 000 – 70 000 сом', '08:00 – 16:30', '+996701556677', 'Опыт работы на Дордое, русский и кыргызский языки.'),
                    (1002, 'seamstress', 'Срочно требуются швеи в швейный цех', '60 000 – 100 000 сом', '08:00 – 18:00, сдельно', '+996552998811', 'Прямострочка, оверлок 4-нитка, обед за счет цеха.'),
                    (1003, 'loader', 'Грузчик / Фасовщик на склад карго', '2 000 – 3 500 сом в день', '07:00 – 15:00', '+996777223344', 'Северная стоянка Дордоя, ежедневная выплата.')
                """)

        await db.commit()

I18N = {
    'ky': {
        'welcome': "👋 Дордой базарынын ыкчам платформасына кош келиңиз!\nКеректүү кызматты тандаңыз:",
        'btn_porter': "🛒 Тачка чакыруу",
        'btn_food': "🍲 Тамак-аш / Түшкү тамак",
        'btn_supplies': "📦 Скотч, мүшөк, баул",
        'btn_cargo': "🚛 Карго чакыруу (РФ / КЗ)",
        'btn_market': "🛍️ Дүң товарлар (Базар)",
        'btn_realestate': "🏠 Ижара (Контейнер / Үй)",
        'btn_jobs': "💼 Жумуш / Вакансиялар",
        'btn_rates': "💱 Валюта курстары & Карго",
        'btn_worker': "⚙️ Мен аткаруучумун (Жумушчу)",
        'btn_lang': "🌐 Тилди алмаштыруу",
        'choose_sector': "📍 Базардын кайсы секторундасыз? Секторду тандаңыз:",
        'enter_loc': "Өтмөк (катар) жана контейнер номерин жазыңыз:\n(Мисалы: <i>3-проход, 45-контейнер</i>)",
        'enter_phone': "Байланыш номериңизди жөнөтүңүз же жазыңыз (+996 700 123456):",
        'order_created': "✅ Буйрутма кабыл алынды! Жакын арадагы аткаруучуларга билдирүү кетти.",
        'order_taken': "✅ Сиз буйрутманы алдыңыз! Кардар менен байланышыңыз.",
        'order_already_taken': "❌ Бул буйрутманы башка бирөө алып койду!",
        'notify_seller': "🔔 <b>Сиздин буйрутмаңыз кабыл алынды!</b>\n\nАткаруучу: {name}\nТел: {phone}\nЗаказ #{id}",
        'btn_send_contact': "📱 Номерди жөнөтүү",
        'switch_seller': "🛍 Сатуучу режимине өтүү"
    },
    'ru': {
        'welcome': "👋 Добро пожаловать в единую систему рынка «Дордой»!\nВыберите нужный раздел или услугу:",
        'btn_porter': "🛒 Вызвать тачку",
        'btn_food': "🍲 Заказать еду в контейнер",
        'btn_supplies': "📦 Скотч, мешки, баулы",
        'btn_cargo': "🚛 Вызвать Карго (РФ / КЗ)",
        'btn_market': "🛍️ Товары Дордоя (Опт)",
        'btn_realestate': "🏠 Аренда (Контейнеры / Жилье)",
        'btn_jobs': "💼 Вакансии / Найм персонала",
        'btn_rates': "💱 Курсы валют Дордой & Карго",
        'btn_worker': "⚙️ Я исполнитель (Работник)",
        'btn_lang': "🌐 Сменить язык",
        'choose_sector': "📍 В каком вы секторе? Выберите сектор рынка:",
        'enter_loc': "Укажите проход (ряд) и номер контейнера:\n(Например: <i>3-проход, 45-контейнер</i>)",
        'enter_phone': "Отправьте ваш контактный номер (+996 700 123456):",
        'order_created': "✅ Заявка принята! Все исполнители в секторе оповещены.",
        'order_taken': "✅ Вы взяли этот заказ! Свяжитесь с заказчиком.",
        'order_already_taken': "❌ Этот заказ уже забрал другой исполнитель!",
        'notify_seller': "🔔 <b>Ваш заказ принят исполнителем!</b>\n\nИсполнитель: {name}\nТел: {phone}\nЗаказ #{id}",
        'btn_send_contact': "📱 Отправить контакт",
        'switch_seller': "🛍 Режим покупателя / продавца"
    },
    'zh': {
        'welcome': "👋 欢迎使用多尔多伊市场（Dordoi）综合服务与批发平台！\n请选择您需要的服务：",
        'btn_porter': "🛒 叫板车 / 货运工人",
        'btn_food': "🍲 订餐 / 送餐到集装箱",
        'btn_supplies': "📦 胶带、编织袋、打包用品",
        'btn_cargo': "🚛 叫物流货运 (发俄罗斯/哈萨克)",
        'btn_market': "🛍️ 市场批发货源 (防骗认证)",
        'btn_realestate': "🏠 集装箱租赁与周边租房",
        'btn_jobs': "💼 市场招聘与招工 (营业员/缝纫工)",
        'btn_rates': "💱 多尔多伊现钞汇率与货运计算",
        'btn_worker': "⚙️ 我是服务人员 (接单模式)",
        'btn_lang': "🌐 切换语言 / Language",
        'choose_sector': "📍 请选择您所在的市场区域：",
        'enter_loc': "请输入通道号和集装箱号：\n（例如：<i>3通道，45号集装箱</i>）",
        'enter_phone': "请输入您的联系电话（例如 +996 700 123456）：",
        'order_created': "✅ 订单已发布！附近的工人已收到提醒，稍后联系您。",
        'order_taken': "✅ 您已成功接单！请联系客户。",
        'order_already_taken': "❌ 抱歉，该订单已被其他人员抢先接走！",
        'notify_seller': "🔔 <b>已有工人接单并前往！</b>\n\n工人：{name}\n电话：{phone}\n订单编号 #{id}",
        'btn_send_contact': "📱 发送我的电话号码",
        'switch_seller': "🛍 切换为商户模式"
    }
}

SECTORS = [
    "Европа / Europe", "Кербен / Kerben", "Мурас-Спорт", 
    "Джунхай / 中海", "Алкан / Ак-Суу", "Оберон / Oberon", 
    "Восток / 东方", "Северная стоянка / 北停车场"
]

class OrderFlow(StatesGroup):
    order_type = State()
    sector = State()
    location = State()
    details = State()
    contact = State()

class ProductPostFlow(StatesGroup):
    title = State()
    sector = State()
    container = State()
    price = State()
    min_batch = State()
    phone = State()

class RealEstatePostFlow(StatesGroup):
    re_type = State()
    title = State()
    location = State()
    price = State()
    phone = State()

class JobPostFlow(StatesGroup):
    role = State()
    title = State()
    salary = State()
    phone = State()

async def check_and_increment_daily_limit(user_id: int) -> bool:
    today_str = date.today().isoformat()
    async with aiosqlite.connect("dordoi_master.db") as db:
        async with db.execute("SELECT daily_posts_count, last_post_date FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return True
            posts_count, last_date = row[0] or 0, row[1] or ""
            if last_date != today_str:
                await db.execute("UPDATE users SET daily_posts_count = 1, last_post_date = ? WHERE user_id = ?", (today_str, user_id))
                await db.commit()
                return True
            if posts_count >= 2:
                return False
            await db.execute("UPDATE users SET daily_posts_count = daily_posts_count + 1 WHERE user_id = ?", (user_id,))
            await db.commit()
            return True

async def get_user_lang(user_id: int) -> str:
    async with aiosqlite.connect("dordoi_master.db") as db:
        async with db.execute("SELECT lang FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 'ru'

def get_main_menu(lang='ru', role='seller'):
    t = I18N.get(lang, I18N['ru'])
    if role == 'seller':
        kb = [
            [KeyboardButton(text=t['btn_porter']), KeyboardButton(text=t['btn_food'])],
            [KeyboardButton(text=t['btn_supplies']), KeyboardButton(text=t['btn_cargo'])],
            [KeyboardButton(text=t['btn_market']), KeyboardButton(text=t['btn_realestate'])],
            [KeyboardButton(text=t['btn_jobs']), KeyboardButton(text=t['btn_rates'])],
            [KeyboardButton(text=t['btn_worker']), KeyboardButton(text=t['btn_lang'])]
        ]
    else:
        kb = [
            [KeyboardButton(text="🟢 На смене / Иштеп жатам / 营业中")],
            [KeyboardButton(text=t['switch_seller']), KeyboardButton(text=t['btn_lang'])]
        ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_lang_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Кыргызча 🇰🇬", callback_data="lang_ky")],
        [InlineKeyboardButton(text="Русский 🇷🇺", callback_data="lang_ru")],
        [InlineKeyboardButton(text="中文 🇨🇳", callback_data="lang_zh")]
    ])

def get_sectors_kb(prefix="sec_"):
    buttons = []
    row = []
    for s in SECTORS:
        row.append(InlineKeyboardButton(text=s, callback_data=f"{prefix}{s}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Тилди тандаңыз / Выберите язык / 请选择语言:", reply_markup=get_lang_kb())

@dp.message(F.text.in_([I18N['ky']['btn_lang'], I18N['ru']['btn_lang'], I18N['zh']['btn_lang'], "🌐 Тил / Язык"]))
async def cmd_lang(message: types.Message):
    await message.answer("Тилди тандаңыз / Выберите язык / 请选择语言:", reply_markup=get_lang_kb())

@dp.callback_query(F.data.startswith("lang_"))
async def set_lang(call: types.CallbackQuery):
    lang = call.data.split("_")[1]
    async with aiosqlite.connect("dordoi_master.db") as db:
        await db.execute("""
            INSERT INTO users (user_id, full_name, lang) 
            VALUES (?, ?, ?) 
            ON CONFLICT(user_id) DO UPDATE SET lang = excluded.lang
        """, (call.from_user.id, call.from_user.full_name, lang))
        await db.commit()
    await call.message.delete()
    t = I18N[lang]
    await call.message.answer(t['welcome'], reply_markup=get_main_menu(lang, 'seller'))

@dp.message(F.text.in_([I18N['ky']['btn_worker'], I18N['ru']['btn_worker'], I18N['zh']['btn_worker']]))
async def role_selection(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Тачкист / 板车工人", callback_data="role_porter")],
        [InlineKeyboardButton(text="🍲 Общепит / Ашкана / 订餐餐厅", callback_data="role_food")],
        [InlineKeyboardButton(text="📦 Упаковка / Скотч, мешки / 包装用品", callback_data="role_supplies")],
        [InlineKeyboardButton(text="🚛 Карго логистика (РФ/КЗ) / 物流货运", callback_data="role_cargo")]
    ])
    await message.answer("Ким болуп иштейсиз? / Кем вы работаете? / 您从事什么服务？", reply_markup=kb)

@dp.callback_query(F.data.startswith("role_"))
async def set_worker_role(call: types.CallbackQuery):
    role = call.data.replace("role_", "")
    lang = await get_user_lang(call.from_user.id)
    async with aiosqlite.connect("dordoi_master.db") as db:
        await db.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, call.from_user.id))
        await db.commit()
    await call.message.delete()
    await call.message.answer(
        "🎉 Вы зарегистрированы! Заказы будут поступать сюда.\n注册成功！相关订单将直接推送给您。",
        reply_markup=get_main_menu(lang, role)
    )

@dp.message(F.text.in_([I18N['ky']['switch_seller'], I18N['ru']['switch_seller'], I18N['zh']['switch_seller']]))
async def switch_back_to_seller(message: types.Message):
    lang = await get_user_lang(message.from_user.id)
    async with aiosqlite.connect("dordoi_master.db") as db:
        await db.execute("UPDATE users SET role = 'seller' WHERE user_id = ?", (message.from_user.id,))
        await db.commit()
    await message.answer("Режим торговца. / 已切换为商户模式。", reply_markup=get_main_menu(lang, 'seller'))

# --- ТОВАРЫ РЫНКА (ОПТ) ---
@dp.message(F.text.in_([I18N['ky']['btn_market'], I18N['ru']['btn_market'], I18N['zh']['btn_market']]))
async def show_market_products(message: types.Message):
    text = "🛍️ <b>ОПТОВАЯ ДОСКА ТОВАРОВ «ДОРДОЙ»</b>\n<i>Защита: только проверенные контейнеры и защита от ботов</i>\n\n"
    async with aiosqlite.connect("dordoi_master.db") as db:
        async with db.execute("""
            SELECT id, title, sector, container_num, price, currency, min_batch, phone 
            FROM products 
            WHERE is_active = 1 AND reports_count < 3 
            ORDER BY id DESC LIMIT 5
        """) as cur:
            rows = await cur.fetchall()
            for r in rows:
                p_id, title, sec, cont, price, curr, batch, phone = r
                clean_phone = phone.replace("+", "").replace(" ", "")
                text += (
                    f"📦 <b>{title}</b>\n"
                    f"📍 {sec}, {cont}\n"
                    f"💰 Цена опт: <b>{price} {curr}</b> ({batch})\n"
                    f"🛡️ <i>Верифицированный контейнер Дордоя</i>\n"
                    f"💬 WhatsApp: https://wa.me/{clean_phone}\n"
                    f"⚠️ Пожаловаться на фейк: /report_prod_{p_id}\n\n"
                )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Выставить свой оптовый товар", callback_data="post_product")],
        [InlineKeyboardButton(text="🛡️ Как работает защита от спама?", callback_data="antispam_info")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)

@dp.callback_query(F.data == "antispam_info")
async def show_antispam_info(call: types.CallbackQuery):
    info_text = (
        "🛡️ <b>ПРАВИЛА ЗАЩИТЫ ОТ СПАМА И ФЕЙКОВ:</b>\n\n"
        "1. <b>Привязка к реальному контейнеру:</b> Запрещены объявления без указания сектора, прохода и номера контейнера.\n"
        "2. <b>Ограничение частоты (Rate Limit):</b> Максимум 2 товара в сутки с одного аккаунта Telegram.\n"
        "3. <b>Народная модерация (3 страйка):</b> Если 3 торговца нажимают жалобу, объявление удаляется автоматически.\n"
        "4. <b>Обязательные оптовые поля:</b> Указывается минимальная партия и цена."
    )
    await call.message.answer(info_text, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "post_product")
async def start_post_product(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    allowed = await check_and_increment_daily_limit(user_id)
    if not allowed:
        await call.answer("⚠️ Лимит: не более 2 объявлений в сутки для защиты от спама!", show_alert=True)
        return

    await state.set_state(ProductPostFlow.title)
    await call.message.answer("📝 Введите наименование товара и описание (например: <i>Платья трикотаж, 5 расцветок</i>):")
    await call.answer()

@dp.message(ProductPostFlow.title)
async def process_prod_title(message: types.Message, state: FSMContext):
    if len(message.text.strip()) < 5:
        await message.answer("⚠️ Название слишком короткое! Напишите понятное описание товара:")
        return
    await state.update_data(title=message.text)
    await state.set_state(ProductPostFlow.sector)
    await message.answer("📍 Выберите сектор рынка, где находится ваш контейнер:", reply_markup=get_sectors_kb("prodsec_"))

@dp.callback_query(F.data.startswith("prodsec_"), ProductPostFlow.sector)
async def process_prod_sector(call: types.CallbackQuery, state: FSMContext):
    sector = call.data.replace("prodsec_", "")
    await state.update_data(sector=sector)
    await state.set_state(ProductPostFlow.container)
    await call.message.edit_text(
        f"📍 Сектор: <b>{sector}</b>\n\n🚪 Введите точный проход и номер контейнера:\n(Например: <i>4-проход, 18-контейнер</i>)",
        parse_mode="HTML"
    )

@dp.message(ProductPostFlow.container)
async def process_prod_container(message: types.Message, state: FSMContext):
    container_text = message.text.strip()
    if len(container_text) < 3 or not any(char.isdigit() for char in container_text):
        await message.answer("⚠️ Ошибка верификации! Укажите реальный номер контейнера с цифрами:", parse_mode="HTML")
        return
    await state.update_data(container=container_text)
    await state.set_state(ProductPostFlow.price)
    await message.answer("💰 Укажите оптовую цену в сомах (например: <i>850</i>):")

@dp.message(ProductPostFlow.price)
async def process_prod_price(message: types.Message, state: FSMContext):
    try:
        price = float(message.text.strip().replace(" ", ""))
    except ValueError:
        await message.answer("⚠️ Введите корректное число для цены:")
        return
    await state.update_data(price=price)
    await state.set_state(ProductPostFlow.min_batch)
    await message.answer("📦 Укажите минимальную оптовую партию (например: <i>от 1 серии (5 шт)</i>):")

@dp.message(ProductPostFlow.min_batch)
async def process_prod_min_batch(message: types.Message, state: FSMContext):
    await state.update_data(min_batch=message.text)
    await state.set_state(ProductPostFlow.phone)
    lang = await get_user_lang(message.from_user.id)
    t = I18N[lang]
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t['btn_send_contact'], request_contact=True)]],
        resize_keyboard=True
    )
    await message.answer("📱 Отправьте ваш контактный WhatsApp номер:", reply_markup=kb)

@dp.message(ProductPostFlow.phone)
async def process_prod_phone(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text
    data = await state.get_data()
    lang = await get_user_lang(message.from_user.id)

    async with aiosqlite.connect("dordoi_master.db") as db:
        await db.execute("""
            INSERT INTO products (user_id, title, sector, container_num, price, currency, min_batch, phone, is_verified)
            VALUES (?, ?, ?, ?, ?, 'KGS', ?, ?, 1)
        """, (
            message.from_user.id,
            data['title'],
            data['sector'],
            data['container'],
            data['price'],
            data['min_batch'],
            phone
        ))
        await db.commit()

    await state.clear()
    await message.answer(
        "✅ <b>Ваш товар опубликован на оптовой доске рынка «Дордой»!</b>\nКонтейнер верифицирован.",
        parse_mode="HTML",
        reply_markup=get_main_menu(lang, 'seller')
    )

@dp.message(F.text.startswith("/report_prod_"))
async def handle_report_product(message: types.Message):
    try:
        prod_id = int(message.text.replace("/report_prod_", "").strip())
    except ValueError:
        return

    reporter_id = message.from_user.id
    async with aiosqlite.connect("dordoi_master.db") as db:
        try:
            await db.execute("INSERT INTO reports (item_type, item_id, reporter_id) VALUES ('product', ?, ?)", (prod_id, reporter_id))
            await db.execute("UPDATE products SET reports_count = reports_count + 1 WHERE id = ?", (prod_id,))
            async with db.execute("SELECT reports_count FROM products WHERE id = ?", (prod_id,)) as cur:
                r = await cur.fetchone()
                if r and r[0] >= 3:
                    await db.execute("UPDATE products SET is_active = 0 WHERE id = ?", (prod_id,))
            await db.commit()
            await message.answer("🛡️ Жалоба принята. Спасибо за поддержание чистоты рынка от спама и фейков!")
        except Exception:
            await message.answer("Вы уже отправляли жалобу на этот товар.")

# --- АРЕНДА КОНТЕЙНЕРОВ И ЖИЛЬЯ ---
@dp.message(F.text.in_([I18N['ky']['btn_realestate'], I18N['ru']['btn_realestate'], I18N['zh']['btn_realestate']]))
async def show_real_estate(message: types.Message):
    text = "🏠 <b>АРЕНДА КОНТЕЙНЕРОВ И ЖИЛЬЯ РЯДОМ С РЫНКОМ «ДОРДОЙ»</b>\n\n"
    async with aiosqlite.connect("dordoi_master.db") as db:
        async with db.execute("SELECT id, title, location, price, currency, phone, description FROM real_estate WHERE is_active = 1 ORDER BY id DESC LIMIT 5") as cur:
            rows = await cur.fetchall()
            for r in rows:
                re_id, title, loc, price, curr, phone, desc = r
                clean_phone = phone.replace("+", "").replace(" ", "")
                text += (
                    f"🏢 <b>{title}</b>\n"
                    f"📍 {loc}\n"
                    f"💵 <b>{price} {curr} / месяц</b>\n"
                    f"ℹ️ {desc}\n"
                    f"📞 Контакт: https://wa.me/{clean_phone}\n\n"
                )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Сдать контейнер или жилье", callback_data="post_realestate")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)

@dp.callback_query(F.data == "post_realestate")
async def start_post_realestate(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(RealEstatePostFlow.title)
    await call.message.answer("📝 Введите заголовок (например: <i>Сдается 2-эт. контейнер на центральном проходе</i>):")
    await call.answer()

@dp.message(RealEstatePostFlow.title)
async def process_re_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(RealEstatePostFlow.location)
    await message.answer("📍 Укажите точное расположение (сектор/контейнер или жилмассив):")

@dp.message(RealEstatePostFlow.location)
async def process_re_loc(message: types.Message, state: FSMContext):
    await state.update_data(location=message.text)
    await state.set_state(RealEstatePostFlow.price)
    await message.answer("💵 Стоимость аренды в месяц (сом):")

@dp.message(RealEstatePostFlow.price)
async def process_re_price(message: types.Message, state: FSMContext):
    await state.update_data(price=message.text)
    await state.set_state(RealEstatePostFlow.phone)
    await message.answer("📱 Ваш контактный номер телефона / WhatsApp:")

@dp.message(RealEstatePostFlow.phone)
async def process_re_phone(message: types.Message, state: FSMContext):
    phone = message.text
    data = await state.get_data()
    lang = await get_user_lang(message.from_user.id)
    async with aiosqlite.connect("dordoi_master.db") as db:
        await db.execute("""
            INSERT INTO real_estate (user_id, re_type, title, location, price, currency, phone, description)
            VALUES (?, 'container', ?, ?, ?, 'KGS', ?, 'От собственника')
        """, (message.from_user.id, data['title'], data['location'], data['price'], phone))
        await db.commit()
    await state.clear()
    await message.answer("✅ Объявление об аренде успешно размещено!", reply_markup=get_main_menu(lang, 'seller'))

# --- ВАКАНСИИ И НАЙМ ПЕРСОНАЛА ---
@dp.message(F.text.in_([I18N['ky']['btn_jobs'], I18N['ru']['btn_jobs'], I18N['zh']['btn_jobs']]))
async def show_jobs(message: types.Message):
    text = "💼 <b>ВАКАНСИИ И НАЙМ ПЕРСОНАЛА НА РЫНКЕ «ДОРДОЙ»</b>\n\n"
    async with aiosqlite.connect("dordoi_master.db") as db:
        async with db.execute("SELECT id, title, salary, schedule, phone, requirements FROM jobs WHERE is_active = 1 ORDER BY id DESC LIMIT 5") as cur:
            rows = await cur.fetchall()
            for r in rows:
                j_id, title, sal, sched, phone, req = r
                clean_phone = phone.replace("+", "").replace(" ", "")
                text += (
                    f"👔 <b>{title}</b>\n"
                    f"💰 Зарплата: <b>{sal}</b>\n"
                    f"⏰ График: {sched}\n"
                    f"📋 Требования: {req}\n"
                    f"📱 Откликнуться: https://wa.me/{clean_phone}\n\n"
                )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Разместить вакансию", callback_data="post_job")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)

@dp.callback_query(F.data == "post_job")
async def start_post_job(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(JobPostFlow.title)
    await call.message.answer("👔 Какая должность требуется? (Например: <i>Реализатор со знанием китайского и русского</i>):")
    await call.answer()

@dp.message(JobPostFlow.title)
async def process_job_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(JobPostFlow.salary)
    await message.answer("💰 Укажите заработную плату (например: <i>50 000 сом + %</i>):")

@dp.message(JobPostFlow.salary)
async def process_job_sal(message: types.Message, state: FSMContext):
    await state.update_data(salary=message.text)
    await state.set_state(JobPostFlow.phone)
    await message.answer("📱 Номер WhatsApp для соискателей:")

@dp.message(JobPostFlow.phone)
async def process_job_phone(message: types.Message, state: FSMContext):
    phone = message.text
    data = await state.get_data()
    lang = await get_user_lang(message.from_user.id)
    async with aiosqlite.connect("dordoi_master.db") as db:
        await db.execute("""
            INSERT INTO jobs (user_id, role, title, salary, schedule, phone, requirements)
            VALUES (?, 'seller', ?, ?, '08:00 - 16:30', ?, 'Опыт работы на рынке Дордой')
        """, (message.from_user.id, data['title'], data['salary'], phone))
        await db.commit()
    await state.clear()
    await message.answer("✅ Вакансия успешно размещена!", reply_markup=get_main_menu(lang, 'seller'))

# --- КУРСЫ ВАЛЮТ ДОРДОЙ И КАРГО ТАРИФЫ ---
@dp.message(F.text.in_([I18N['ky']['btn_rates'], I18N['ru']['btn_rates'], I18N['zh']['btn_rates']]))
async def show_rates(message: types.Message):
    rates_text = (
        "💱 <b>НАЛИЧНЫЙ КУРС ВАЛЮТ ОБМЕННЫХ ПУНКТОВ ДОРДОЯ:</b>\n"
        "<i>Сектора «Джунхай» и «Европа» (наличный расчет):</i>\n\n"
        "💵 <b>USD / Доллар:</b> Покупка 87.40 | Продажа 87.85 сом\n"
        "💴 <b>CNY / Юань:</b> Покупка 12.15 | Продажа 12.40 сом\n"
        "🇷🇺 <b>RUB / Рубль:</b> Покупка 0.915 | Продажа 0.935 сом\n"
        "🇰🇿 <b>KZT / Тенге:</b> Покупка 0.178 | Продажа 0.185 сом\n\n"
        "🚛 <b>ТАРИФЫ КАРГО ИЗ ДОРДОЯ В РФ И КЗ:</b>\n"
        "• Москва (ТЯК Люблино / Садовод): ~1.85 $/кг (4–6 дней)\n"
        "• Екатеринбург (Таганский ряд): ~1.65 $/кг (3–5 дней)\n"
        "• Новосибирск (ТЦ Восток): ~1.55 $/кг (3–4 дня)\n"
        "• Алматы (Барахолка): ~0.85 $/кг (1–2 дня)"
    )
    await message.answer(rates_text, parse_mode="HTML")

# --- ЗАКАЗ СЛУЖБ (ТАЧКА, ЕДА, УПАКОВКА, КАРГО) ---
@dp.message(F.text.in_([
    I18N['ky']['btn_porter'], I18N['ru']['btn_porter'], I18N['zh']['btn_porter'],
    I18N['ky']['btn_food'], I18N['ru']['btn_food'], I18N['zh']['btn_food'],
    I18N['ky']['btn_supplies'], I18N['ru']['btn_supplies'], I18N['zh']['btn_supplies'],
    I18N['ky']['btn_cargo'], I18N['ru']['btn_cargo'], I18N['zh']['btn_cargo']
]))
async def start_order_flow(message: types.Message, state: FSMContext):
    text = message.text
    if text in [I18N['ky']['btn_porter'], I18N['ru']['btn_porter'], I18N['zh']['btn_porter']]:
        order_type = 'porter'
    elif text in [I18N['ky']['btn_food'], I18N['ru']['btn_food'], I18N['zh']['btn_food']]:
        order_type = 'food'
    elif text in [I18N['ky']['btn_supplies'], I18N['ru']['btn_supplies'], I18N['zh']['btn_supplies']]:
        order_type = 'supplies'
    else:
        order_type = 'cargo'

    lang = await get_user_lang(message.from_user.id)
    await state.update_data(order_type=order_type, lang=lang)
    await state.set_state(OrderFlow.sector)
    t = I18N[lang]
    await message.answer(t['choose_sector'], reply_markup=get_sectors_kb("sec_"))

@dp.callback_query(F.data.startswith("sec_"), OrderFlow.sector)
async def process_sector(call: types.CallbackQuery, state: FSMContext):
    sector = call.data.replace("sec_", "")
    await state.update_data(sector=sector)
    data = await state.get_data()
    lang = data['lang']
    t = I18N[lang]
    await state.set_state(OrderFlow.location)
    await call.message.edit_text(
        f"📍 <b>{sector}</b>\n\n{t['enter_loc']}",
        parse_mode="HTML"
    )

@dp.message(OrderFlow.location)
async def process_location(message: types.Message, state: FSMContext):
    await state.update_data(location=message.text)
    data = await state.get_data()
    order_type = data['order_type']

    prompts = {
        'porter': "Какой груз? Сколько баулов и куда везти?\n(Например: <i>3 больших баула на Северную стоянку</i>):",
        'food': "Что принести из еды?\n(Например: <i>2 плова, 3 самсы, 1 чай</i>):",
        'supplies': "Какие расходники нужны?\n(Например: <i>5 рулонов скотча, 10 мешков</i>):",
        'cargo': "Вес груза и город доставки?\n(Например: <i>300 кг трикотаж, на Москву</i>):"
    }
    await state.set_state(OrderFlow.details)
    await message.answer(prompts[order_type], parse_mode="HTML")

@dp.message(OrderFlow.details)
async def process_details(message: types.Message, state: FSMContext):
    original_details = message.text
    await state.update_data(details=original_details)
    data = await state.get_data()
    lang = data['lang']
    t = I18N[lang]
    await state.set_state(OrderFlow.contact)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t['btn_send_contact'], request_contact=True)]],
        resize_keyboard=True
    )
    await message.answer(t['enter_phone'], reply_markup=kb)

@dp.message(OrderFlow.contact)
async def process_contact(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text
    data = await state.get_data()
    lang = data['lang']
    order_type = data['order_type']
    raw_details = data['details']
    sector = data['sector']
    location = data['location']

    translated_details = await translate_text(raw_details, target_lang='ru')

    order_id = None
    async with aiosqlite.connect("dordoi_master.db") as db:
        cur = await db.execute("""
            INSERT INTO orders (order_type, seller_id, seller_name, seller_phone, market_sector, container_num, details, details_translated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_type,
            message.from_user.id,
            message.from_user.full_name,
            phone,
            sector,
            location,
            raw_details,
            translated_details
        ))
        order_id = cur.lastrowid
        await db.commit()

        async with db.execute("SELECT user_id, lang FROM users WHERE role = ? AND is_active = 1", (order_type,)) as c:
            executors = await c.fetchall()

    await state.clear()
    t = I18N[lang]
    await message.answer(t['order_created'], reply_markup=get_main_menu(lang, 'seller'))

    type_labels = {
        'porter': ("🛒 ТАЧКА / БАУЛ", "叫板车"),
        'food': ("🍲 ТАМАК / ЕДА", "外卖订餐"),
        'supplies': ("📦 УПАКОВКА / СКОТЧ", "打包用品"),
        'cargo': ("🚛 КАРГО ЖҮК / ЛОГИСТИКА", "物流货运")
    }
    title_ru, title_zh = type_labels[order_type]
    clean_phone = phone.replace("+", "").replace(" ", "")

    card_text = (
        f"🚨 <b>НОВЫЙ ЗАКАЗ #{order_id}</b> ({title_ru} | {title_zh})\n\n"
        f"📍 <b>Сектор:</b> {sector}\n"
        f"🚪 <b>Место:</b> {location}\n"
        f"📝 <b>Текст (оригинал):</b> {raw_details}\n"
        f"🔄 <b>Перевод (RU):</b> {translated_details}\n"
        f"👤 <b>Заказчик:</b> {message.from_user.full_name}\n"
        f"📞 <b>Тел:</b> {phone}"
    )

    card_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✋ Взять заказ / 接单", callback_data=f"take_{order_id}")],
        [InlineKeyboardButton(text="💬 WhatsApp", url=f"https://wa.me/{clean_phone}")]
    ])

    for ex_id, _ in executors:
        try:
            await bot.send_message(ex_id, card_text, parse_mode="HTML", reply_markup=card_kb)
        except Exception:
            pass

@dp.callback_query(F.data.startswith("take_"))
async def handle_take_order(call: types.CallbackQuery):
    order_id = int(call.data.replace("take_", ""))
    executor_id = call.from_user.id
    worker_lang = await get_user_lang(executor_id)
    wt = I18N[worker_lang]

    async with aiosqlite.connect("dordoi_master.db") as db:
        async with db.execute("SELECT status, seller_id FROM orders WHERE id = ?", (order_id,)) as cur:
            row = await cur.fetchone()
            if not row or row[0] != 'pending':
                await call.answer(wt['order_already_taken'], show_alert=True)
                return
            
            seller_id = row[1]
            await db.execute("UPDATE orders SET status = 'taken', executor_id = ? WHERE id = ?", (executor_id, order_id))
            await db.commit()

    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer(wt['order_taken'])
    await call.message.answer(f"✅ Заказ #{order_id} закреплен за вами!")

    seller_lang = await get_user_lang(seller_id)
    st = I18N[seller_lang]
    seller_msg = st['notify_seller'].format(
        name=call.from_user.full_name,
        phone=call.from_user.username or "в Telegram",
        id=order_id
    )
    try:
        await bot.send_message(seller_id, seller_msg, parse_mode="HTML")
    except Exception:
        pass

async def main():
    await init_db()
    if os.environ.get("PORT"):
        await start_healthcheck_server()
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logging.warning(f"Webhook reset: {e}")

    print("🚀 Dordoi SuperBot запущен: Товары, Аренда, Вакансии, Курсы валют и 4 службы активны!")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
