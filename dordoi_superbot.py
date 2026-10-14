import asyncio
import logging
import urllib.parse
import html
from datetime import date
import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
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

# Поддержка DefaultBotProperties для aiogram >= 3.5
try:
    from aiogram.client.default import DefaultBotProperties
    HAS_DEFAULT_PROPS = True
except ImportError:
    HAS_DEFAULT_PROPS = False

# ==============================================================================
# ТОКЕН БОТА: Укажите токен, полученный от @BotFather в Telegram
# ВНИМАНИЕ: В данном коде НЕТ рекламы, спама и принудительных подписок на каналы!
# ==============================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8867783468:AAHWN6srbzEIUgPpwrVg0PcWu4GFjnFuc5Y")

logging.basicConfig(level=logging.INFO)

# Инициализация бота с обязательным ParseMode.HTML для корректного отображения <b>, <i>, <code>
if HAS_DEFAULT_PROPS:
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
else:
    bot = Bot(token=BOT_TOKEN, parse_mode="HTML")

dp = Dispatcher(storage=MemoryStorage())

# --- БЕЗОПАСНАЯ ОТПРАВКА HTML (ГАРАНТИРУЕТ, ЧТО <b> НИКОГДА НЕ ВЫЙДЕТ СЫРЫМ ТЕКСТОМ) ---
async def send_html(target, text: str, reply_markup=None, disable_preview=True):
    """
    Безопасно отправляет сообщение с HTML-форматированием.
    Если Telegram возвращает ошибку синтаксиса HTML (например, в деталях заказа были спецсимволы < > &),
    функция автоматически очищает теги и доставляет сообщение адресату.
    """
    try:
        if isinstance(target, types.Message):
            return await target.answer(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_preview
            )
        elif isinstance(target, types.CallbackQuery):
            return await target.message.answer(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_preview
            )
        elif isinstance(target, int):
            return await bot.send_message(
                target,
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_preview
            )
    except Exception as e:
        logging.warning(f"HTML send failed ({e}), sending clean fallback text")
        # Очистка тегов во избежание падения бота
        clean = (
            text.replace("<b>", "").replace("</b>", "")
            .replace("<i>", "").replace("</i>", "")
            .replace("<code>", "").replace("</code>", "")
            .replace("<em>", "").replace("</em>", "")
        )
        if isinstance(target, types.Message):
            return await target.answer(clean, reply_markup=reply_markup, disable_web_page_preview=disable_preview)
        elif isinstance(target, types.CallbackQuery):
            return await target.message.answer(clean, reply_markup=reply_markup, disable_web_page_preview=disable_preview)
        elif isinstance(target, int):
            return await bot.send_message(target, clean, reply_markup=reply_markup, disable_web_page_preview=disable_preview)

async def edit_html(call: types.CallbackQuery, text: str, reply_markup=None, disable_preview=True):
    """Безопасное редактирование сообщения в CallbackQuery с ParseMode.HTML"""
    try:
        return await call.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_preview
        )
    except Exception as e:
        logging.warning(f"edit_html fallback ({e})")
        clean = (
            text.replace("<b>", "").replace("</b>", "")
            .replace("<i>", "").replace("</i>", "")
            .replace("<code>", "").replace("</code>", "")
        )
        try:
            return await call.message.edit_text(clean, reply_markup=reply_markup, disable_web_page_preview=disable_preview)
        except Exception:
            pass

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

# --- БАЗА ДАННЫХ SQLITE С НАДЕЖНЫМ УЧЕТОМ УЧАСТНИКОВ И ТАЧКИСТОВ ---
async def init_db():
    async with aiosqlite.connect("dordoi_master.db") as db:
        # Таблица пользователей (с гарантированным сохранением роли, телефона, статуса онлайн)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                username TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                role TEXT DEFAULT 'seller', -- seller, porter, food, supplies, cargo
                sector TEXT DEFAULT '',      -- сектор рынка, где сейчас тачкист/работник
                lang TEXT DEFAULT 'ru',
                is_active INTEGER DEFAULT 1, -- 1 = на смене (онлайн), 0 = оффлайн
                is_demo INTEGER DEFAULT 0,   -- 1 = демо-участник, 0 = реальный человек из Telegram
                daily_posts_count INTEGER DEFAULT 0,
                last_post_date TEXT DEFAULT '',
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Миграция: убедимся что колонка is_demo существует
        try:
            await db.execute("ALTER TABLE users ADD COLUMN is_demo INTEGER DEFAULT 0")
        except Exception:
            pass

        # Заказы (Тачка, Еда, Упаковка, Карго)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_type TEXT,            -- porter, food, supplies, cargo
                seller_id INTEGER,
                seller_name TEXT,
                seller_phone TEXT,
                market_sector TEXT,
                container_num TEXT,
                details TEXT,
                details_translated TEXT,
                executor_id INTEGER DEFAULT NULL,
                status TEXT DEFAULT 'pending', -- pending, taken, completed
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Товары рынка (Оптовая доска с верификацией контейнера и защитой от спама)
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
                photo_file_id TEXT DEFAULT NULL,
                is_verified INTEGER DEFAULT 1,
                reports_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        try:
            await db.execute("ALTER TABLE products ADD COLUMN photo_file_id TEXT")
        except Exception:
            pass

        # Аренда (Контейнеры на Дордое и жилье рядом)
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

        # Вакансии и найм персонала
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

        # Жалобы на спам и мошенничество
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

        # Пометить старые демо-аккаунты как is_demo = 1
        await db.execute("""
            UPDATE users SET is_demo = 1 WHERE user_id IN (900101, 900102, 900103, 900104, 900105, 900106)
        """)

        # Базовые ориентировочные контакты служб рынка (с флагом is_demo = 1, чтобы не слать им бот-сообщения)
        await db.execute("""
            INSERT OR IGNORE INTO users (user_id, full_name, username, phone, role, sector, lang, is_active, is_demo)
            VALUES 
            (900101, 'Азамат (Тачка #14)', 'azamat_dordoi', '+996700112233', 'porter', 'Джунхай / 中海', 'ky', 1, 1),
            (900102, 'Кубаныч (Тачка #28)', 'kubanych_cart', '+996555445566', 'porter', 'Европа / Europe', 'ru', 1, 1),
            (900103, 'Алишер (Тачка #42)', 'alisher_dordoi', '+996772889900', 'porter', 'Мурас-Спорт', 'ky', 1, 1),
            (900104, 'Кафе «Ак-Бата» (Плов, лагман)', 'dordoi_food_1', '+996550778899', 'food', 'Джунхай / 中海', 'ru', 1, 1),
            (900105, 'Упаковка «Мастер-Скотч» (Баулы, мешки)', 'dordoi_pack', '+996708443322', 'supplies', 'Алкан / Ак-Суу', 'ru', 1, 1),
            (900106, 'Карго «Транс-Азия» (Москва/Садовод)', 'cargo_dordoi', '+996770119955', 'cargo', 'Северная стоянка / 北停车场', 'ru', 1, 1)
        """)

        # Демо-товары
        async with db.execute("SELECT COUNT(*) FROM products") as cur:
            count = (await cur.fetchone())[0]
            if count == 0:
                await db.execute("""
                    INSERT INTO products (user_id, title, sector, container_num, category, price, currency, min_batch, description, phone, is_verified)
                    VALUES 
                    (1001, 'Платья женские трикотажные «Миди» (Made in KG)', 'Алкан / Ак-Суу', '14-проход, 88-контейнер', 'clothing', 850, 'KGS', 'от 1 серии (5 шт)', 'Собственный цех в Бишкеке. Плотный трикотаж рубчик. Идеально под Wildberries.', '+996702334455', 1),
                    (1002, 'Зимние пуховики оверсайз (Гуанчжоу)', 'Джунхай / 中海', '5-проход, 32-контейнер', 'clothing', 2200, 'KGS', 'от 10 шт (микс)', 'Прямой импорт из Гуанчжоу без посредников. Био-пух до -25°C.', '+996770889900', 1),
                    (1003, 'Кроссовки термо с эко-мехом (Мужские)', 'Мурас-Спорт', 'Ряд 3, 44-контейнер', 'shoes', 1100, 'KGS', 'от 1 коробки (8 пар)', 'Подошва ТЭП (не скользит), отправка на Северную стоянку день в день.', '+996555441122', 1)
                """)

        # Демо-аренда
        async with db.execute("SELECT COUNT(*) FROM real_estate") as cur:
            re_count = (await cur.fetchone())[0]
            if re_count == 0:
                await db.execute("""
                    INSERT INTO real_estate (user_id, re_type, title, location, price, currency, phone, description)
                    VALUES 
                    (1001, 'container', 'Аренда 2-эт. контейнера в секторе «Европа»', 'Сектор «Европа», Ряд Б, контейнер 38', 45000, 'KGS', '+996700998877', '1-й этаж витрины под бутик, 2-й этаж сухой склад со стеллажами.'),
                    (1002, 'container', 'Сдается контейнер под ткани в Джунхае', 'Сектор «Джунхай / 中海», 4-проход, 18-контейнер', 550, 'USD', '+996550123456', 'Центральный проход, высокий трафик покупателей швейных цехов.'),
                    (1003, 'housing', 'Сдается 2-комн. квартира рядом с Дордоем', 'Жилмассив «Дордой-1» (5 мин пешком)', 25000, 'KGS', '+996772445566', 'Все удобства, газ, мебель. Для торговцев или бригады реализаторов.')
                """)

        # Демо-вакансии
        async with db.execute("SELECT COUNT(*) FROM jobs") as cur:
            jobs_count = (await cur.fetchone())[0]
            if jobs_count == 0:
                await db.execute("""
                    INSERT INTO jobs (user_id, role, title, salary, schedule, phone, requirements)
                    VALUES 
                    (1001, 'seller', 'Требуется реализатор женской одежды со знанием языков', '40 000 – 70 000 сом (Оклад + %)', '08:00 – 16:30 (Вт–Вс)', '+996701556677', 'Опыт работы на Дордое, русский и кыргызский языки.'),
                    (1002, 'seamstress', 'Срочно требуются швеи в цех (Худи и платья)', '60 000 – 100 000 сом (Сдельно)', '08:00 – 18:00, стабильный объем', '+996552998811', 'Прямострочка, оверлок 4-нитка, обед за счет цеха.'),
                    (1003, 'loader', 'Грузчик / Фасовщик на склад карго', '2 000 – 3 500 сом в день', '07:00 – 15:00', '+996777223344', 'Северная стоянка Дордоя, ежедневная выплата.')
                """)

        await db.commit()

# --- ФУНКЦИЯ ДЛЯ ГАРАНТИРОВАННОГО СОХРАНЕНИЯ УЧАСТНИКА (UPSERT) ---
async def upsert_user(
    user_id: int,
    full_name: str,
    username: str = "",
    role: str = None,
    sector: str = None,
    phone: str = None,
    lang: str = None,
    is_active: int = 1,
    is_demo: int = 0
):
    """
    Надежное сохранение профиля пользователя в SQLite.
    Гарантирует, что роль, сектор и телефон сохраняются мгновенно без сбросов.
    """
    clean_name = full_name or f"Участник #{user_id}"
    clean_username = username or ""
    
    async with aiosqlite.connect("dordoi_master.db") as db:
        # Проверяем существующую запись
        async with db.execute("SELECT role, sector, phone, lang FROM users WHERE user_id = ?", (user_id,)) as cur:
            existing = await cur.fetchone()
            
        if not existing:
            # Новый пользователь
            new_role = role or 'seller'
            new_sector = sector or ''
            new_phone = phone or ''
            new_lang = lang or 'ru'
            await db.execute("""
                INSERT INTO users (user_id, full_name, username, phone, role, sector, lang, is_active, is_demo, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (user_id, clean_name, clean_username, new_phone, new_role, new_sector, new_lang, is_active, is_demo))
        else:
            # Обновление
            up_role = role if role is not None else existing[0]
            up_sector = sector if sector is not None else existing[1]
            up_phone = phone if phone is not None else existing[2]
            up_lang = lang if lang is not None else existing[3]
            
            await db.execute("""
                UPDATE users SET
                    full_name = ?,
                    username = CASE WHEN ? != '' THEN ? ELSE username END,
                    role = ?,
                    sector = ?,
                    phone = CASE WHEN ? != '' THEN ? ELSE phone END,
                    lang = ?,
                    is_active = ?,
                    is_demo = ?,
                    last_seen = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (clean_name, clean_username, clean_username, up_role, up_sector, up_phone, up_phone, up_lang, is_active, is_demo, user_id))
            
        await db.commit()

# --- СЛОВАРИ И ЛОКАЛИЗАЦИЯ (RU / KY / ZH) ---
I18N = {
    'ky': {
        'welcome': "👋 <b>Дордой базарынын ыкчам платформасына кош келиңиз!</b>\nКеректүү кызматты же бөлүмдү тандаңыз:",
        'btn_porter': "🛒 Тачка чакыруу / Жүк",
        'btn_food': "🍲 Тамак-аш / Түшкү тамак",
        'btn_supplies': "📦 Скотч, мүшөк, баул",
        'btn_cargo': "🚛 Карго чакыруу (РФ / КЗ)",
        'btn_market': "🛍️ Дүң товарлар (Базар)",
        'btn_realestate': "🏠 Ижара (Контейнер / Үй)",
        'btn_jobs': "💼 Жумуш / Вакансиялар",
        'btn_rates': "💱 Валюта курстары & Карго",
        'btn_active_porters': "🛒 Тачкисттер онлайн",
        'btn_all_members': "👥 Базардын бардык катышуучулары",
        'btn_worker_feed': "📋 Буйрутмалар лентасы",
        'btn_worker': "⚙️ Мен аткаруучумун (Жумушчу)",
        'btn_lang': "🌐 Тилди алмаштыруу",
        'choose_sector': "📍 Базардын кайсы секторундасыз? Секторду тандаңыз:",
        'enter_loc': "Өтмөк (катар) жана контейнер номерин жазыңыз:\n(Мисалы: <i>3-проход, 45-контейнер</i>)",
        'enter_phone': "Байланыш номериңизди жөнөтүңүз же жазыңыз (+996 700 123456):",
        'order_created': "✅ <b>Буйрутма кабыл алынды!</b> Жакын арадагы аткаруучуларга билдирүү кетти.",
        'order_taken': "✅ <b>Сиз буйрутманы алдыңыз!</b> Кардар менен байланышыңыз.",
        'order_already_taken': "❌ Бул буйрутманы башка бирөө алып койду!",
        'notify_seller': "🔔 <b>Сиздин буйрутмаңыз кабыл алынды!</b>\n\nАткаруучу: <b>{name}</b>\nТел: <b>{phone}</b>\nЗаказ #{id}",
        'btn_send_contact': "📱 Номерди жөнөтүү",
        'btn_post_product_clip': "📸 Товар чыгаруу (Скрепка 📎)",
        'switch_seller': "🛍 Сатуучу режимине өтүү"
    },
    'ru': {
        'welcome': "👋 <b>Добро пожаловать в единую систему рынка «Дордой»!</b>\nВыберите нужный раздел или услугу:",
        'btn_porter': "🛒 Вызвать тачку / Поиск",
        'btn_food': "🍲 Заказать еду в контейнер",
        'btn_supplies': "📦 Скотч, мешки, баулы",
        'btn_cargo': "🚛 Вызвать Карго (РФ / КЗ)",
        'btn_market': "🛍️ Товары Дордоя (Опт)",
        'btn_realestate': "🏠 Аренда (Контейнеры / Жилье)",
        'btn_jobs': "💼 Вакансии / Найм персонала",
        'btn_rates': "💱 Курсы валют Дордой & Карго",
        'btn_active_porters': "🛒 Тачкисты на смене (Онлайн)",
        'btn_all_members': "👥 Все участники рынка онлайн",
        'btn_worker_feed': "📋 Свежие заказы / Лента",
        'btn_worker': "⚙️ Я исполнитель (Работник)",
        'btn_lang': "🌐 Сменить язык",
        'choose_sector': "📍 В каком вы секторе? Выберите сектор рынка:",
        'enter_loc': "Укажите проход (ряд) и номер контейнера:\n(Например: <i>3-проход, 45-контейнер</i>)",
        'enter_phone': "Отправьте ваш контактный номер (+996 700 123456):",
        'order_created': "✅ <b>Заявка принята!</b> Все исполнители в секторе оповещены.",
        'order_taken': "✅ <b>Вы взяли этот заказ!</b> Свяжитесь с заказчиком.",
        'order_already_taken': "❌ Этот заказ уже забрал другой исполнитель!",
        'notify_seller': "🔔 <b>Ваш заказ принят исполнителем!</b>\n\nИсполнитель: <b>{name}</b>\nТел: <b>{phone}</b>\nЗаказ #{id}",
        'btn_send_contact': "📱 Отправить контакт",
        'btn_post_product_clip': "📸 Выложить товар (Скрепка 📎)",
        'switch_seller': "🛍 Режим покупателя / продавца"
    },
    'zh': {
        'welcome': "👋 <b>欢迎使用多尔多伊市场（Dordoi）综合服务与批发平台！</b>\n请选择您需要的服务：",
        'btn_porter': "🛒 叫板车 / 查找搬运工",
        'btn_food': "🍲 订餐 / 送餐到集装箱",
        'btn_supplies': "📦 胶带、编织袋、打包用品",
        'btn_cargo': "🚛 叫物流货运 (发俄罗斯/哈萨克)",
        'btn_market': "🛍️ 市场批发货源 (防骗认证)",
        'btn_realestate': "🏠 集装箱租赁与周边租房",
        'btn_jobs': "💼 市场招聘与招工 (营业员/缝纫工)",
        'btn_rates': "💱 多尔多伊现钞汇率与货运计算",
        'btn_active_porters': "🛒 在岗板车工人列表",
        'btn_all_members': "👥 市场所有在线服务人员",
        'btn_worker_feed': "📋 最新待接订单",
        'btn_worker': "⚙️ 我是服务人员 (接单模式)",
        'btn_lang': "🌐 切换语言 / Language",
        'choose_sector': "📍 请选择您所在的市场区域：",
        'enter_loc': "请输入通道号和集装箱号：\n（例如：<i>3通道，45号集装箱</i>）",
        'enter_phone': "请输入您的联系电话（例如 +996 700 123456）：",
        'order_created': "✅ <b>订单已发布！</b> 附近的工人已收到提醒，稍后联系您。",
        'order_taken': "✅ <b>您已成功接单！</b> 请联系客户。",
        'order_already_taken': "❌ 抱歉，该订单已被其他人员抢先接走！",
        'notify_seller': "🔔 <b>已有工人接单并前往！</b>\n\n工人：<b>{name}</b>\n电话：<b>{phone}</b>\n订单编号 #{id}",
        'btn_send_contact': "📱 发送我的电话号码",
        'btn_post_product_clip': "📸 上传商品（回形针📎）",
        'switch_seller': "🛍 切换为商户模式"
    }
}

SECTORS = [
    "Европа / Europe", "Кербен / Kerben", "Мурас-Спорт", 
    "Джунхай / 中海", "Алкан / Ак-Суу", "Оберон / Oberon", 
    "Восток / 东方", "Северная стоянка / 北停车场"
]

# --- FSM СОСТОЯНИЯ ---
class OrderFlow(StatesGroup):
    order_type = State()
    sector = State()
    location = State()
    details = State()
    contact = State()

class WorkerRegisterFlow(StatesGroup):
    role = State()
    sector = State()
    phone = State()

class ProductPostFlow(StatesGroup):
    title = State()
    sector = State()
    container = State()
    price = State()
    min_batch = State()
    phone = State()

class ProductClipFlow(StatesGroup):
    photo = State()
    caption = State()

async def get_user_lang(user_id: int) -> str:
    async with aiosqlite.connect("dordoi_master.db") as db:
        async with db.execute("SELECT lang FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 'ru'

def get_main_menu(lang='ru', role='seller'):
    t = I18N.get(lang, I18N['ru'])
    if role == 'seller':
        kb = [
            [KeyboardButton(text=t['btn_post_product_clip'])],
            [KeyboardButton(text=t['btn_porter']), KeyboardButton(text=t['btn_food'])],
            [KeyboardButton(text=t['btn_supplies']), KeyboardButton(text=t['btn_cargo'])],
            [KeyboardButton(text=t['btn_market']), KeyboardButton(text=t['btn_realestate'])],
            [KeyboardButton(text=t['btn_jobs']), KeyboardButton(text=t['btn_rates'])],
            [KeyboardButton(text=t['btn_active_porters']), KeyboardButton(text=t['btn_all_members'])],
            [KeyboardButton(text=t['btn_worker']), KeyboardButton(text=t['btn_lang'])]
        ]
    else:
        kb = [
            [KeyboardButton(text="🟢 На смене (Онлайн) / Иштеп жатам")],
            [KeyboardButton(text=t['btn_worker_feed']), KeyboardButton(text=t['btn_active_porters'])],
            [KeyboardButton(text=t['btn_all_members']), KeyboardButton(text=t['switch_seller'])],
            [KeyboardButton(text=t['btn_lang'])]
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

# --- ХЕНДЛЕРЫ КОМАНД ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Регистрируем пользователя сразу в БД со статусом реального участника (is_demo = 0)
    await upsert_user(
        user_id=message.from_user.id,
        full_name=message.from_user.full_name or "Пользователь",
        username=message.from_user.username or "",
        is_demo=0
    )
    await send_html(message, "Тилди тандаңыз / Выберите язык / 请选择语言:", reply_markup=get_lang_kb())

@dp.message(F.text.in_([I18N['ky']['btn_lang'], I18N['ru']['btn_lang'], I18N['zh']['btn_lang'], "🌐 Тил / Язык", "/lang"]))
async def cmd_lang(message: types.Message):
    await send_html(message, "Тилди тандаңыз / Выберите язык / 请选择语言:", reply_markup=get_lang_kb())

@dp.callback_query(F.data.startswith("lang_"))
async def set_lang(call: types.CallbackQuery):
    lang = call.data.split("_")[1]
    await upsert_user(
        user_id=call.from_user.id,
        full_name=call.from_user.full_name or "Пользователь",
        username=call.from_user.username or "",
        lang=lang,
        is_demo=0
    )
    try:
        await call.message.delete()
    except Exception:
        pass
        
    t = I18N[lang]
    # Проверяем роль
    async with aiosqlite.connect("dordoi_master.db") as db:
        async with db.execute("SELECT role FROM users WHERE user_id = ?", (call.from_user.id,)) as cur:
            row = await cur.fetchone()
            current_role = row[0] if row else 'seller'
            
    await send_html(call, t['welcome'], reply_markup=get_main_menu(lang, current_role))

# ==============================================================================
# РЕГИСТРАЦИЯ И ОТОБРАЖЕНИЕ ИСПОЛНИТЕЛЕЙ (МГНОВЕННОЕ ВКЛЮЧЕНИЕ В БАЗУ В 1 КЛИК)
# ==============================================================================
@dp.message(F.text.in_([I18N['ky']['btn_worker'], I18N['ru']['btn_worker'], I18N['zh']['btn_worker'], "/worker"]))
async def role_selection(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Тачкист / Жүк ташуу / 板车", callback_data="role_porter")],
        [InlineKeyboardButton(text="🍲 Общепит / Ашкана / 订餐", callback_data="role_food")],
        [InlineKeyboardButton(text="📦 Упаковка / Скотч, мешки / 耗材", callback_data="role_supplies")],
        [InlineKeyboardButton(text="🚛 Карго логистика (РФ/КЗ) / 货运", callback_data="role_cargo")]
    ])
    await send_html(
        message,
        "⚙️ <b>Кем вы работаете на рынке «Дордой»?</b>\n"
        "Нажмите специальность — <b>вы сразу начнете получать заказы и отображаться в списке онлайн</b>:",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("role_"))
async def set_worker_role(call: types.CallbackQuery, state: FSMContext):
    role = call.data.replace("role_", "")
    role_titles = {
        'porter': '🛒 Тачкист (Жүк ташуу)',
        'food': '🍲 Общепит / Ашкана',
        'supplies': '📦 Упаковка и расходники',
        'cargo': '🚛 Карго логистика'
    }
    
    # КРИТИЧЕСКИ ВАЖНО: Регистрируем пользователя КАК ИСПОЛНИТЕЛЯ МГНОВЕННО!
    # Больше не нужно ждать подтверждения телефона — телефон и сектор можно настроить следом,
    # но тачкист УЖЕ В БАЗЕ ДАННЫХ И ВИДЕН ВСЕМ!
    await upsert_user(
        user_id=call.from_user.id,
        full_name=call.from_user.full_name or "Работник Дордоя",
        username=call.from_user.username or "",
        role=role,
        is_active=1,
        is_demo=0
    )
    
    await state.update_data(role=role)
    await state.set_state(WorkerRegisterFlow.sector)
    
    lang = await get_user_lang(call.from_user.id)
    
    # Отправляем подтверждение и новое главное меню для исполнителя
    await send_html(
        call,
        f"🎉 <b>ВЫ УСПЕШНО ЗАРЕГИСТРИРОВАНЫ КАК {role_titles.get(role, role).upper()}!</b>\n\n"
        f"🟢 <b>Статус: НА СМЕНЕ (ОНЛАЙН)</b>\n"
        f"Теперь вас видят все покупатели и торговцы при поиске тачкистов и участников рынка!\n\n"
        f"📍 <b>Укажите ваш сектор рынка</b> (чтобы первыми получать близкие заказы):",
        reply_markup=get_sectors_kb("worksec_")
    )
    # Обновляем основную клавиатуру внизу
    await send_html(
        call.from_user.id,
        "📋 <i>Используйте кнопки внизу для просмотра свежих заказов или перехода в режим торговца.</i>",
        reply_markup=get_main_menu(lang, role)
    )

@dp.callback_query(F.data.startswith("worksec_"), WorkerRegisterFlow.sector)
async def process_worker_sector(call: types.CallbackQuery, state: FSMContext):
    sector = call.data.replace("worksec_", "")
    await state.update_data(sector=sector)
    await state.set_state(WorkerRegisterFlow.phone)
    
    # Обновляем сектор в БД
    await upsert_user(
        user_id=call.from_user.id,
        full_name=call.from_user.full_name or "Работник Дордоя",
        username=call.from_user.username or "",
        sector=sector,
        is_active=1,
        is_demo=0
    )
    
    lang = await get_user_lang(call.from_user.id)
    t = I18N[lang]
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t['btn_send_contact'], request_contact=True)],
            [KeyboardButton(text="➡️ Пропустить ввод телефона")]
        ],
        resize_keyboard=True
    )
    await edit_html(
        call,
        f"📍 Сектор закреплен: <b>{html.escape(sector)}</b>\n\n"
        f"📱 Отправьте ваш контактный номер телефона / WhatsApp (нажмите кнопку внизу или введите 0700123456):",
        reply_markup=None
    )
    await send_html(call.from_user.id, "📱 Отправьте контакт или нажмите «Пропустить»:", reply_markup=kb)

@dp.message(WorkerRegisterFlow.phone)
async def process_worker_phone(message: types.Message, state: FSMContext):
    phone = ""
    if message.contact:
        phone = message.contact.phone_number
    elif message.text and "Пропустить" not in message.text:
        phone = message.text.strip()
        
    data = await state.get_data()
    role = data.get('role', 'porter')
    sector = data.get('sector', 'Джунхай / 中海')
    
    # Сохраняем в базу со статусом онлайн
    await upsert_user(
        user_id=message.from_user.id,
        full_name=message.from_user.full_name or "Работник Дордоя",
        username=message.from_user.username or "",
        role=role,
        sector=sector,
        phone=phone,
        is_active=1,
        is_demo=0
    )
    
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    
    phone_display = phone if phone else "Не указан (связь через Telegram @)"
    await send_html(
        message,
        f"✅ <b>ПРОФИЛЬ ПОЛНОСТЬЮ НАСТРОЕН!</b>\n\n"
        f"👔 Специальность: <b>{role.upper()}</b>\n"
        f"📍 Сектор: <b>{html.escape(sector)}</b>\n"
        f"📞 Номер: <b>{html.escape(phone_display)}</b>\n"
        f"🟢 <b>Статус: НА СМЕНЕ</b>\n\n"
        f"Все новые заказы торговцев будут приходить вам со звуком и кнопкой «Взять заказ».",
        reply_markup=get_main_menu(lang, role)
    )

# --- БЫСТРЫЕ КОМАНДЫ ДЛЯ ТЕСТИРОВАНИЯ ---
@dp.message(Command("porter"))
async def cmd_quick_porter(message: types.Message):
    """Быстрая команда мгновенно сделать текущий аккаунт тачкистом для тестов"""
    await upsert_user(
        user_id=message.from_user.id,
        full_name=message.from_user.full_name or "Тачкист",
        username=message.from_user.username or "",
        role='porter',
        sector='Джунхай / 中海',
        phone='+996 700 000111',
        is_active=1,
        is_demo=0
    )
    lang = await get_user_lang(message.from_user.id)
    await send_html(
        message,
        "🛒 <b>ВЫ МГНОВЕННО АКТИВИРОВАНЫ КАК ТАЧКИСТ!</b>\n"
        "Статус: 🟢 <i>На смене (Онлайн)</i>. Проверьте с первого телефона — теперь ваш профиль отображается в списке!",
        reply_markup=get_main_menu(lang, 'porter')
    )

@dp.message(Command("my_profile"), Command("whoami"))
async def cmd_whoami(message: types.Message):
    """Показывает текущий статус и роль аккаунта"""
    user_id = message.from_user.id
    async with aiosqlite.connect("dordoi_master.db") as db:
        async with db.execute("SELECT role, sector, phone, is_active FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            
    if not row:
        await send_html(message, "Вы не зарегистрированы. Отправьте /start")
        return
        
    role, sector, phone, is_act = row
    status_str = "🟢 На смене (Онлайн)" if is_act else "🔴 Оффлайн"
    await send_html(
        message,
        f"👤 <b>ВАШ ТЕКУЩИЙ ПРОФИЛЬ:</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👔 Роль: <b>{role.upper()}</b>\n"
        f"📍 Сектор: <b>{html.escape(sector or 'Не выбран')}</b>\n"
        f"📞 Телефон: <b>{html.escape(phone or 'Не указан')}</b>\n"
        f"📶 Статус: {status_str}"
    )

# --- ПЕРЕКЛЮЧЕНИЕ ОБРАТНО В РЕЖИМ ТОРГОВЦА ---
@dp.message(F.text.in_([I18N['ky']['switch_seller'], I18N['ru']['switch_seller'], I18N['zh']['switch_seller'], "/seller"]))
async def switch_back_to_seller(message: types.Message):
    lang = await get_user_lang(message.from_user.id)
    await upsert_user(
        user_id=message.from_user.id,
        full_name=message.from_user.full_name or "Пользователь",
        username=message.from_user.username or "",
        role='seller'
    )
    await send_html(
        message,
        "🛍 <b>Вы переключились в режим торговца / заказчика!</b>\n"
        "Теперь вы можете вызывать тачку, заказывать еду, упаковку и карго.",
        reply_markup=get_main_menu(lang, 'seller')
    )

# ==============================================================================
# СПИСОК ТАЧКИСТОВ И ВСЕХ УЧАСТНИКОВ РЫНКА ОНЛАЙН (РЕШАЕТ ПРОБЛЕМУ "НЕ ОТОБРАЖАЕТ")
# ==============================================================================
@dp.message(F.text.in_([
    I18N['ky']['btn_active_porters'], I18N['ru']['btn_active_porters'], I18N['zh']['btn_active_porters'],
    "🛒 Тачкисты на смене", "👥 Список тачкистов", "👥 Тачкисты онлайн", "/porters"
]))
async def show_active_porters(message: types.Message):
    """
    Отображает реальных тачкистов (Phone 2) в первую очередь,
    с контактными данными, сектором и кнопками прямого звонка / вызова.
    """
    async with aiosqlite.connect("dordoi_master.db") as db:
        # Сначала реальные пользователи Telegram (is_demo = 0), затем дежурные
        async with db.execute("""
            SELECT user_id, full_name, phone, sector, username, is_demo, last_seen 
            FROM users 
            WHERE role = 'porter' AND is_active = 1 
            ORDER BY is_demo ASC, last_seen DESC LIMIT 15
        """) as cur:
            rows = await cur.fetchall()

    text = "🛒 <b>ТАЧКИСТЫ НА СМЕНЕ (РЫНОК «ДОРДОЙ» ОНЛАЙН):</b>\n\n"
    
    if not rows:
        text += "⚠️ Сейчас на смене нет свободных тачкистов.\nНажмите «🛒 Вызвать тачку», чтобы опубликовать заявку, и дежурные получат сигнал!"
    else:
        real_count = sum(1 for r in rows if r[5] == 0)
        text += f"🟢 <i>Сейчас на смене: <b>{len(rows)} тачкистов</b> (из них {real_count} подтвержденных онлайн в Telegram)</i>\n\n"
        
        for idx, r in enumerate(rows, 1):
            u_id, name, phone, sec, username, is_demo, last_seen = r
            clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "") if phone else ""
            sec_str = f" · Сектор: <b>{html.escape(sec)}</b>" if sec else ""
            user_tag = f" (@{username})" if username else ""
            demo_badge = " [ДЕЖУРНЫЙ]" if is_demo == 1 else " [🟢 ЖИВОЙ ОНЛАЙН]"
            
            text += (
                f"{idx}. 👤 <b>{html.escape(name)}</b>{demo_badge}{user_tag}{sec_str}\n"
                f"   📞 <b>{html.escape(phone or 'Связь через Telegram')}</b>\n"
            )
            if clean_phone:
                text += f"   💬 WhatsApp: https://wa.me/{clean_phone}\n\n"
            elif username:
                text += f"   💬 Telegram: https://t.me/{username}\n\n"
            else:
                text += "\n"

    text += "<i>💡 Чтобы вызвать тачку к своему контейнеру, нажмите кнопку ниже:</i>"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Вызвать тачку к своему контейнеру", callback_data="fast_call_porter")],
        [InlineKeyboardButton(text="👥 Показать ВСЕХ участников рынка", callback_data="filter_members_all")]
    ])
    await send_html(message, text, reply_markup=kb, disable_preview=True)

# --- КАТАЛОГ ВСЕХ УЧАСТНИКОВ РЫНКА (ОБЩЕПИТ, КАРГО, УПАКОВКА, ТАЧКИСТЫ) ---
@dp.message(F.text.in_([
    I18N['ky']['btn_all_members'], I18N['ru']['btn_all_members'], I18N['zh']['btn_all_members'],
    "👥 Все участники", "👥 Участники", "/members", "/participants"
]))
async def show_all_members_menu(message: types.Message):
    await render_members_catalog(message, filter_role="all")

@dp.callback_query(F.data.startswith("filter_members_"))
async def callback_filter_members(call: types.CallbackQuery):
    filter_role = call.data.replace("filter_members_", "")
    await render_members_catalog(call, filter_role=filter_role)
    await call.answer()

async def render_members_catalog(target, filter_role="all"):
    """Универсальный рендер участников рынка с фильтрацией по ролям"""
    role_titles = {
        'all': 'Все участники и службы',
        'porter': '🛒 Тачкисты (Жүк ташуу)',
        'food': '🍲 Общепит и доставка еды',
        'supplies': '📦 Упаковка и расходники',
        'cargo': '🚛 Карго логистика (РФ/КЗ)',
        'seller': '🛍 Торговцы / Оптовики'
    }

    async with aiosqlite.connect("dordoi_master.db") as db:
        if filter_role == "all":
            query = """
                SELECT user_id, full_name, role, phone, sector, username, is_demo 
                FROM users 
                WHERE is_active = 1 
                ORDER BY is_demo ASC, last_seen DESC LIMIT 20
            """
            params = ()
        else:
            query = """
                SELECT user_id, full_name, role, phone, sector, username, is_demo 
                FROM users 
                WHERE role = ? AND is_active = 1 
                ORDER BY is_demo ASC, last_seen DESC LIMIT 20
            """
            params = (filter_role,)
            
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()

    text = f"👥 <b>АКТИВНЫЕ УЧАСТНИКИ РЫНКА «ДОРДОЙ» ОНЛАЙН:</b>\n"
    text += f"<i>Категория: <b>{role_titles.get(filter_role, filter_role)}</b> ({len(rows)} найдено)</i>\n\n"

    if not rows:
        text += "⚠️ В данной категории пока нет активных участников онлайн."
    else:
        role_icons = {
            'porter': '🛒 Тачка',
            'food': '🍲 Еда',
            'supplies': '📦 Упаковка',
            'cargo': '🚛 Карго',
            'seller': '🛍 Торговец'
        }
        for idx, r in enumerate(rows, 1):
            u_id, name, r_role, phone, sec, username, is_demo = r
            clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "") if phone else ""
            r_icon = role_icons.get(r_role, '⚙️ Служба')
            sec_str = f" · 📍 {html.escape(sec)}" if sec else ""
            user_tag = f" (@{username})" if username else ""
            badge = " [🟢 ОНЛАЙН]" if is_demo == 0 else ""
            
            text += (
                f"{idx}. <b>{html.escape(name)}</b>{badge}\n"
                f"   👔 {r_icon}{sec_str}\n"
                f"   📞 {html.escape(phone or 'Связь в Telegram')}{user_tag}\n"
            )
            if clean_phone:
                text += f"   💬 WhatsApp: https://wa.me/{clean_phone}\n\n"
            else:
                text += "\n"

    filter_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛒 Тачкисты", callback_data="filter_members_porter"),
            InlineKeyboardButton(text="🍲 Еда", callback_data="filter_members_food")
        ],
        [
            InlineKeyboardButton(text="📦 Упаковка", callback_data="filter_members_supplies"),
            InlineKeyboardButton(text="🚛 Карго", callback_data="filter_members_cargo")
        ],
        [
            InlineKeyboardButton(text="👥 Показать всех", callback_data="filter_members_all")
        ]
    ])

    if isinstance(target, types.CallbackQuery):
        await edit_html(target, text, reply_markup=filter_kb, disable_preview=True)
    else:
        await send_html(target, text, reply_markup=filter_kb, disable_preview=True)

# --- ЛЕНТА ЗАКАЗОВ ДЛЯ РАБОТНИКОВ (РЕШАЕТ ПРОБЛЕМУ "НЕ ВИЖУ ЗАКАЗОВ СО ВТОРОГО ТЕЛЕФОНА") ---
@dp.message(F.text.in_([
    I18N['ky']['btn_worker_feed'], I18N['ru']['btn_worker_feed'], I18N['zh']['btn_worker_feed'],
    "📋 Свежие заказы / Лента", "📋 Лента заказов", "/orders"
]))
async def show_worker_order_feed(message: types.Message):
    user_id = message.from_user.id
    async with aiosqlite.connect("dordoi_master.db") as db:
        async with db.execute("SELECT role FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            user_role = row[0] if row else 'porter'
            
        # Ищем открытые заказы
        filter_role = user_role if user_role in ['porter', 'food', 'supplies', 'cargo'] else 'porter'
        
        async with db.execute("""
            SELECT id, seller_name, seller_phone, market_sector, container_num, details, details_translated, created_at 
            FROM orders 
            WHERE order_type = ? AND status = 'pending' 
            ORDER BY id DESC LIMIT 5
        """, (filter_role,)) as cur:
            orders_list = await cur.fetchall()

    if not orders_list:
        await send_html(
            message,
            f"📋 <b>ЛЕНТА ЗАКАЗОВ ({filter_role.upper()}):</b>\n\n"
            f"🟢 Все текущие заказы в секторе уже разобраны!\n"
            f"Как только торговец оставит новую заявку, бот <b>мгновенно пришлет вам звуковое уведомление</b>.",
        )
        return

    await send_html(message, f"📋 <b>ОТКРЫТЫЕ ЗАКАЗЫ ДЛЯ ВАС ({len(orders_list)} шт.):</b>")
    
    for o in orders_list:
        o_id, s_name, s_phone, sector, location, details, translated, created_at = o
        clean_phone = s_phone.replace("+", "").replace(" ", "").replace("-", "") if s_phone else ""
        
        card_text = (
            f"🚨 <b>ЗАКАЗ #{o_id} ({filter_role.upper()})</b>\n\n"
            f"📍 <b>Сектор:</b> {html.escape(sector)}\n"
            f"🚪 <b>Место:</b> {html.escape(location)}\n"
            f"📝 <b>Груз/Заказ:</b> {html.escape(details)}\n"
            f"🔄 <b>Перевод:</b> {html.escape(translated)}\n"
            f"👤 <b>Заказчик:</b> {html.escape(s_name)}\n"
            f"📞 <b>Тел:</b> {html.escape(s_phone)}"
        )
        buttons = [[InlineKeyboardButton(text="✋ Взять заказ / 接单", callback_data=f"take_{o_id}")]]
        if clean_phone:
            buttons.append([InlineKeyboardButton(text="💬 WhatsApp заказчика", url=f"https://wa.me/{clean_phone}")])
            
        card_kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await send_html(message, card_text, reply_markup=card_kb)

# --- КНОПКА "Я НА СМЕНЕ" ---
@dp.message(F.text.startswith("🟢 На смене"), Command("shift"))
async def worker_on_shift_status(message: types.Message):
    user_id = message.from_user.id
    async with aiosqlite.connect("dordoi_master.db") as db:
        await db.execute("UPDATE users SET is_active = 1, is_demo = 0, last_seen = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
        await db.commit()
        
        async with db.execute("SELECT role, sector, phone FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            role = row[0] if row else 'porter'
            sector = row[1] if row and row[1] else 'Все сектора'
            phone = row[2] if row and row[2] else 'Не указан'
            
        async with db.execute("SELECT COUNT(*) FROM orders WHERE order_type = ? AND status = 'pending'", (role,)) as cur:
            pending_count = (await cur.fetchone())[0]

    await send_html(
        message,
        f"🟢 <b>ВЫ НА СМЕНЕ И ПРИНИМАЕТЕ ЗАКАЗЫ!</b>\n\n"
        f"👔 Специальность: <b>{role.upper()}</b>\n"
        f"📍 Сектор: <b>{html.escape(sector)}</b>\n"
        f"📞 Номер: <b>{html.escape(phone)}</b>\n"
        f"📦 Неразобранных заказов в ленте: <b>{pending_count} шт.</b>\n\n"
        f"⚡ Ваш профиль отображается всем торговцам в списке активных тачкистов!"
    )

# ==============================================================================
# СОЗДАНИЕ И РАССЫЛКА ЗАКАЗОВ (ТАЧКА, ЕДА, УПАКОВКА, КАРГО)
# ==============================================================================
@dp.message(F.text.in_([
    I18N['ky']['btn_porter'], I18N['ru']['btn_porter'], I18N['zh']['btn_porter'],
    "🛒 Вызвать тачку", "/call_porter"
]))
async def handle_call_porter_button(message: types.Message, state: FSMContext):
    """
    При вызове тачки сначала показывает список доступных тачкистов онлайн прямо сейчас,
    и кнопку мгновенно создать заказ к своему контейнеру!
    """
    async with aiosqlite.connect("dordoi_master.db") as db:
        async with db.execute("""
            SELECT full_name, phone, sector, username, is_demo 
            FROM users 
            WHERE role = 'porter' AND is_active = 1 
            ORDER BY is_demo ASC, last_seen DESC LIMIT 5
        """) as cur:
            active_porters = await cur.fetchall()

    text = "🛒 <b>ВЫЗОВ ТАЧКИСТА НА РЫНКЕ «ДОРДОЙ»</b>\n\n"
    if active_porters:
        text += f"🟢 <b>Сейчас на смене доступно: {len(active_porters)} тачкистов!</b>\n"
        for idx, p in enumerate(active_porters, 1):
            name, phone, sec, username, is_demo = p
            badge = " [🟢 Онлайн]" if is_demo == 0 else ""
            clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "") if phone else ""
            text += f"{idx}. 👤 <b>{html.escape(name)}</b>{badge} ({html.escape(sec or 'Рынок')}) · {html.escape(phone or '@'+username)}\n"
        text += "\n"
        
    text += "📍 Выберите способ вызова:"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Создать заявку к своему контейнеру", callback_data="fast_call_porter")],
        [InlineKeyboardButton(text="👥 Посмотреть полный список тачкистов", callback_data="filter_members_porter")]
    ])
    await send_html(message, text, reply_markup=kb)

@dp.message(F.text.in_([
    I18N['ky']['btn_food'], I18N['ru']['btn_food'], I18N['zh']['btn_food'],
    I18N['ky']['btn_supplies'], I18N['ru']['btn_supplies'], I18N['zh']['btn_supplies'],
    I18N['ky']['btn_cargo'], I18N['ru']['btn_cargo'], I18N['zh']['btn_cargo']
]))
async def start_other_orders_flow(message: types.Message, state: FSMContext):
    text = message.text
    if text in [I18N['ky']['btn_food'], I18N['ru']['btn_food'], I18N['zh']['btn_food']]:
        order_type = 'food'
    elif text in [I18N['ky']['btn_supplies'], I18N['ru']['btn_supplies'], I18N['zh']['btn_supplies']]:
        order_type = 'supplies'
    else:
        order_type = 'cargo'

    lang = await get_user_lang(message.from_user.id)
    await state.update_data(order_type=order_type, lang=lang)
    await state.set_state(OrderFlow.sector)
    t = I18N[lang]
    await send_html(message, t['choose_sector'], reply_markup=get_sectors_kb("sec_"))

@dp.callback_query(F.data == "fast_call_porter")
async def fast_call_porter(call: types.CallbackQuery, state: FSMContext):
    lang = await get_user_lang(call.from_user.id)
    await state.update_data(order_type='porter', lang=lang)
    await state.set_state(OrderFlow.sector)
    t = I18N[lang]
    await send_html(call, t['choose_sector'], reply_markup=get_sectors_kb("sec_"))
    await call.answer()

@dp.callback_query(F.data.startswith("sec_"), OrderFlow.sector)
async def process_sector(call: types.CallbackQuery, state: FSMContext):
    sector = call.data.replace("sec_", "")
    await state.update_data(sector=sector)
    data = await state.get_data()
    lang = data['lang']
    t = I18N[lang]
    await state.set_state(OrderFlow.location)
    await edit_html(call, f"📍 <b>{html.escape(sector)}</b>\n\n{t['enter_loc']}")

@dp.message(OrderFlow.location)
async def process_location(message: types.Message, state: FSMContext):
    await state.update_data(location=message.text.strip())
    data = await state.get_data()
    order_type = data['order_type']

    prompts = {
        'porter': "Какой груз? Сколько баулов и куда везти?\n(Например: <i>3 больших баула на Северную стоянку</i>):",
        'food': "Что принести из еды?\n(Например: <i>2 плова, 3 самсы, 1 чай</i>):",
        'supplies': "Какие расходники нужны?\n(Например: <i>5 рулонов скотча, 10 мешков</i>):",
        'cargo': "Вес груза и город доставки?\n(Например: <i>300 кг трикотаж, на Москву</i>):"
    }
    await state.set_state(OrderFlow.details)
    await send_html(message, prompts[order_type])

@dp.message(OrderFlow.details)
async def process_details(message: types.Message, state: FSMContext):
    original_details = message.text.strip()
    await state.update_data(details=original_details)
    data = await state.get_data()
    lang = data['lang']
    t = I18N[lang]
    await state.set_state(OrderFlow.contact)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t['btn_send_contact'], request_contact=True)]],
        resize_keyboard=True
    )
    await send_html(message, t['enter_phone'], reply_markup=kb)

@dp.message(OrderFlow.contact)
async def process_contact(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text.strip()
    data = await state.get_data()
    lang = data['lang']
    order_type = data['order_type']
    raw_details = data['details']
    sector = data['sector']
    location = data['location']

    # Автоперевод на русский язык для исполнителей
    translated_details = await translate_text(raw_details, target_lang='ru')

    order_id = None
    executors = []
    
    async with aiosqlite.connect("dordoi_master.db") as db:
        cur = await db.execute("""
            INSERT INTO orders (order_type, seller_id, seller_name, seller_phone, market_sector, container_num, details, details_translated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_type,
            message.from_user.id,
            message.from_user.full_name or "Торговец Дордоя",
            phone,
            sector,
            location,
            raw_details,
            translated_details
        ))
        order_id = cur.lastrowid
        await db.commit()

        # Ищем ВСЕХ РЕАЛЬНЫХ исполнителей онлайн (is_demo = 0)
        # Это исключает отправку несуществующим демо-ID, гарантируя доставку на реальные телефоны!
        async with db.execute("""
            SELECT user_id, full_name, username 
            FROM users 
            WHERE role = ? AND is_active = 1 AND is_demo = 0
        """, (order_type,)) as c:
            executors = await c.fetchall()

    await state.clear()
    
    type_labels = {
        'porter': ("🛒 ТАЧКА / БАУЛ", "叫板车"),
        'food': ("🍲 ТАМАК / ЕДА", "外卖订餐"),
        'supplies': ("📦 УПАКОВКА / СКОТЧ", "打包用品"),
        'cargo': ("🚛 КАРГО ЖҮК / ЛОГИСТИКА", "物流货运")
    }
    title_ru, title_zh = type_labels[order_type]
    clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "") if phone else ""

    # Текст карточки для исполнителя (все переменные экранированы через html.escape)
    card_text = (
        f"🚨 <b>НОВЫЙ ЗАКАЗ #{order_id}</b> ({title_ru} | {title_zh})\n\n"
        f"📍 <b>Сектор:</b> {html.escape(sector)}\n"
        f"🚪 <b>Место:</b> {html.escape(location)}\n"
        f"📝 <b>Груз/Детали:</b> {html.escape(raw_details)}\n"
        f"🔄 <b>Перевод (RU):</b> {html.escape(translated_details)}\n"
        f"👤 <b>Заказчик:</b> {html.escape(message.from_user.full_name or 'Торговец')}\n"
        f"📞 <b>Тел:</b> {html.escape(phone)}"
    )

    card_buttons = [[InlineKeyboardButton(text="✋ Взять заказ / 接单", callback_data=f"take_{order_id}")]]
    if clean_phone:
        card_buttons.append([InlineKeyboardButton(text="💬 WhatsApp заказчика", url=f"https://wa.me/{clean_phone}")])
    card_kb = InlineKeyboardMarkup(inline_keyboard=card_buttons)

    # Рассылаем всем реальным исполнителям
    sent_count = 0
    for ex_id, ex_name, ex_uname in executors:
        try:
            await send_html(ex_id, card_text, reply_markup=card_kb)
            sent_count += 1
            logging.info(f"✅ Заказ #{order_id} успешно доставлен тачкисту {ex_name} (ID: {ex_id})")
        except Exception as e:
            logging.warning(f"Не удалось отправить уведомление пользователю {ex_id}: {e}")

    # Сообщение заказчику
    if sent_count > 0:
        seller_confirm = (
            f"✅ <b>Заказ #{order_id} успешно опубликован!</b>\n\n"
            f"📍 <b>Место:</b> {html.escape(sector)}, {html.escape(location)}\n"
            f"📢 <b>Оповещено реальных тачкистов на смене: {sent_count} чел.</b>\n\n"
            f"🔔 Как только тачкист нажмет «Взять заказ», вам мгновенно поступит сообщение с его контактом."
        )
    else:
        seller_confirm = (
            f"✅ <b>Заказ #{order_id} принят и сохранен в ленту заказов!</b>\n\n"
            f"📍 <b>Место:</b> {html.escape(sector)}, {html.escape(location)}\n"
            f"ℹ️ Заказ доступен всем исполнителям в разделе «📋 Свежие заказы / Лента».\n"
            f"Вы также можете напрямую связаться с дежурными тачкистами в разделе «🛒 Тачкисты на смене»."
        )

    await send_html(message, seller_confirm, reply_markup=get_main_menu(lang, 'seller'))

# --- ВЗЯТИЕ ЗАКАЗА ИСПОЛНИТЕЛЕМ ---
@dp.callback_query(F.data.startswith("take_"))
async def handle_take_order(call: types.CallbackQuery):
    order_id = int(call.data.replace("take_", ""))
    executor_id = call.from_user.id
    worker_lang = await get_user_lang(executor_id)
    wt = I18N[worker_lang]

    async with aiosqlite.connect("dordoi_master.db") as db:
        async with db.execute("SELECT status, seller_id, seller_name, seller_phone, market_sector, container_num FROM orders WHERE id = ?", (order_id,)) as cur:
            row = await cur.fetchone()
            if not row or row[0] != 'pending':
                await call.answer(wt['order_already_taken'], show_alert=True)
                return
            
            seller_id, seller_name, seller_phone, sector, location = row[1], row[2], row[3], row[4], row[5]
            await db.execute("UPDATE orders SET status = 'taken', executor_id = ? WHERE id = ?", (executor_id, order_id))
            await db.commit()

    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
        
    await call.answer(wt['order_taken'])
    
    clean_seller_phone = seller_phone.replace("+", "").replace(" ", "").replace("-", "") if seller_phone else ""
    
    await send_html(
        call,
        f"✅ <b>Заказ #{order_id} успешно закреплен за вами!</b>\n\n"
        f"📍 <b>Куда идти:</b> {html.escape(sector)}, {html.escape(location)}\n"
        f"👤 <b>Заказчик:</b> {html.escape(seller_name)}\n"
        f"📞 <b>Телефон:</b> {html.escape(seller_phone)}\n\n"
        f"💬 WhatsApp заказчика: https://wa.me/{clean_seller_phone}",
        disable_preview=True
    )

    # Оповещаем торговца (заказчика)
    seller_lang = await get_user_lang(seller_id)
    st = I18N[seller_lang]
    seller_msg = (
        f"🔔 <b>Ваш заказ #{order_id} ПРИНЯТ ИСПОЛНИТЕЛЕМ!</b>\n\n"
        f"👤 Исполнитель: <b>{html.escape(call.from_user.full_name)}</b>\n"
        f"📱 Telegram: @{call.from_user.username or 'отсутствует'}\n\n"
        f"Исполнитель уже направляется к вашему контейнеру!"
    )
    try:
        await send_html(seller_id, seller_msg)
    except Exception as e:
        logging.warning(f"Не удалось оповестить заказчика {seller_id}: {e}")

# ==============================================================================
# ОПТОВЫЕ ТОВАРЫ, АРЕНДА, ВАКАНСИИ, КУРСЫ ВАЛЮТ
# ==============================================================================
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
                clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "") if phone else ""
                text += (
                    f"📦 <b>{html.escape(title)}</b>\n"
                    f"📍 {html.escape(sec)}, {html.escape(cont)}\n"
                    f"💰 Цена опт: <b>{price} {curr}</b> ({html.escape(batch)})\n"
                    f"🛡️ <i>Верифицированный контейнер Дордоя</i>\n"
                    f"💬 WhatsApp: https://wa.me/{clean_phone}\n"
                    f"⚠️ Пожаловаться: /report_prod_{p_id}\n\n"
                )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡️ Как работает защита от спама?", callback_data="antispam_info")]
    ])
    await send_html(message, text, reply_markup=kb, disable_preview=True)

@dp.callback_query(F.data == "antispam_info")
async def show_antispam_info(call: types.CallbackQuery):
    info_text = (
        "🛡️ <b>ПРАВИЛА ЗАЩИТЫ ОТ СПАМА И ФЕЙКОВ:</b>\n\n"
        "1. <b>Привязка к реальному контейнеру:</b> Запрещены объявления без указания сектора, прохода и номера контейнера.\n"
        "2. <b>Ограничение частоты (Rate Limit):</b> Максимум 2 товара в сутки с одного аккаунта Telegram.\n"
        "3. <b>Народная модерация (3 страйка):</b> Если 3 торговца нажимают жалобу, объявление удаляется автоматически.\n"
        "4. <b>Обязательные оптовые поля:</b> Указывается минимальная партия и цена."
    )
    await send_html(call, info_text)
    await call.answer()

@dp.message(F.text.in_([I18N['ky']['btn_realestate'], I18N['ru']['btn_realestate'], I18N['zh']['btn_realestate']]))
async def show_real_estate(message: types.Message):
    text = "🏠 <b>АРЕНДА КОНТЕЙНЕРОВ И ЖИЛЬЯ РЯДОМ С РЫНКОМ «ДОРДОЙ»</b>\n\n"
    async with aiosqlite.connect("dordoi_master.db") as db:
        async with db.execute("SELECT id, title, location, price, currency, phone, description FROM real_estate WHERE is_active = 1 ORDER BY id DESC LIMIT 5") as cur:
            rows = await cur.fetchall()
            for r in rows:
                re_id, title, loc, price, curr, phone, desc = r
                clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "") if phone else ""
                text += (
                    f"🏢 <b>{html.escape(title)}</b>\n"
                    f"📍 {html.escape(loc)}\n"
                    f"💵 <b>{price} {curr} / месяц</b>\n"
                    f"ℹ️ {html.escape(desc)}\n"
                    f"📞 Контакт: https://wa.me/{clean_phone}\n\n"
                )
    await send_html(message, text, disable_preview=True)

@dp.message(F.text.in_([I18N['ky']['btn_jobs'], I18N['ru']['btn_jobs'], I18N['zh']['btn_jobs']]))
async def show_jobs(message: types.Message):
    text = "💼 <b>ВАКАНСИИ И НАЙМ ПЕРСОНАЛА НА РЫНКЕ «ДОРДОЙ»</b>\n\n"
    async with aiosqlite.connect("dordoi_master.db") as db:
        async with db.execute("SELECT id, title, salary, schedule, phone, requirements FROM jobs WHERE is_active = 1 ORDER BY id DESC LIMIT 5") as cur:
            rows = await cur.fetchall()
            for r in rows:
                j_id, title, sal, sched, phone, req = r
                clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "") if phone else ""
                text += (
                    f"👔 <b>{html.escape(title)}</b>\n"
                    f"💰 Зарплата: <b>{html.escape(sal)}</b>\n"
                    f"⏰ График: {html.escape(sched)}\n"
                    f"📋 Требования: {html.escape(req)}\n"
                    f"📱 Откликнуться: https://wa.me/{clean_phone}\n\n"
                )
    await send_html(message, text, disable_preview=True)

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
    await send_html(message, rates_text)

# ==============================================================================
# ЗАГРУЗКА ТОВАРОВ ЧЕРЕЗ СКРЕПКУ TELEGRAM (ФОТО + ПОДПИСЬ)
# Сделано максимально понятно и просто для людей на базаре «Дордой»
# ==============================================================================
@dp.message(F.photo)
async def handle_photo_clip(message: types.Message, state: FSMContext):
    """
    Прямая отправка товара через скрепку Telegram 📎!
    Торговец делает фото товара на телефон или выбирает из галереи
    и отправляет с короткой подписью (название, цена, контейнер).
    """
    photo = message.photo[-1]
    file_id = photo.file_id
    caption = (message.caption or "").strip()
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    t = I18N.get(lang, I18N['ru'])

    # Профиль торговца
    async with aiosqlite.connect("dordoi_master.db") as db:
        async with db.execute("SELECT sector, phone FROM users WHERE user_id = ?", (user_id,)) as cur:
            user_profile = await cur.fetchone()

    default_sector = user_profile[0] if user_profile and user_profile[0] else "Рынок «Дордой»"
    default_phone = user_profile[1] if user_profile and user_profile[1] else (f"@{message.from_user.username}" if message.from_user.username else "+996 700 000000")

    if caption:
        title = caption.split("\n")[0][:60]
        import re
        price_match = re.search(r'(\d+[\s\d]*)\s*(сом|kgs|руб|rub|\$|usd|юан|cny)?', caption, re.IGNORECASE)
        price = float(price_match.group(1).replace(" ", "")) if price_match else 1000.0

        async with aiosqlite.connect("dordoi_master.db") as db:
            cur = await db.execute("""
                INSERT INTO products (user_id, title, sector, container_num, category, price, currency, min_batch, description, phone, photo_file_id, is_verified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                user_id,
                title,
                default_sector,
                "Указан в описании",
                "clothing",
                price,
                "KGS",
                "Оптом",
                caption,
                default_phone,
                file_id
            ))
            await db.commit()

        success_text = (
            f"✅ <b>ТОВАР УСПЕШНО РАЗМЕЩЕН ЧЕРЕЗ СКРЕПКУ 📎!</b>\n\n"
            f"📸 <b>{html.escape(title)}</b>\n"
            f"💰 Оптовая цена: <b>{price:g} KGS</b>\n"
            f"📍 Сектор: <b>{html.escape(default_sector)}</b>\n"
            f"📞 Связь: <b>{html.escape(default_phone)}</b>\n\n"
            f"📝 Описание: <i>{html.escape(caption)}</i>\n\n"
            f"⚡ <i>Товар мгновенно опубликован на оптовой доске для всех покупателей из Кыргызстана, России и Казахстана!</i>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛍️ Посмотреть товары на рынке", callback_data="show_all_market")],
            [InlineKeyboardButton(text="📸 Выложить еще фото", callback_data="clip_guide")]
        ])
        await send_html(message, success_text, reply_markup=kb)
    else:
        await state.update_data(photo_file_id=file_id, sector=default_sector, phone=default_phone)
        await state.set_state(ProductClipFlow.caption)
        prompt_text = (
            "📸 <b>Отличное фото товара получено через скрепку!</b>\n\n"
            "Теперь отправьте в ответном сообщении пару простых слов:\n"
            "• <b>Название и оптовую цену</b>\n"
            "• <b>Номер ряда и контейнера</b>\n\n"
            "<i>(Например: Джинсы турция 950 сом, ряд 4 конт 18, от 1 серии)</i>"
        )
        await send_html(message, prompt_text)

@dp.message(ProductClipFlow.caption)
async def handle_photo_caption_step(message: types.Message, state: FSMContext):
    data = await state.get_data()
    file_id = data.get('photo_file_id')
    default_sector = data.get('sector', 'Рынок «Дордой»')
    default_phone = data.get('phone', '+996 700 000000')
    caption = message.text.strip()
    user_id = message.from_user.id

    title = caption.split("\n")[0][:60]
    import re
    price_match = re.search(r'(\d+[\s\d]*)\s*(сом|kgs|руб|rub|\$|usd|юан|cny)?', caption, re.IGNORECASE)
    price = float(price_match.group(1).replace(" ", "")) if price_match else 1000.0

    async with aiosqlite.connect("dordoi_master.db") as db:
        await db.execute("""
            INSERT INTO products (user_id, title, sector, container_num, category, price, currency, min_batch, description, phone, photo_file_id, is_verified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            user_id,
            title,
            default_sector,
            "Указан в описании",
            "clothing",
            price,
            "KGS",
            "Оптом",
            caption,
            default_phone,
            file_id
        ))
        await db.commit()

    await state.clear()
    success_text = (
        f"✅ <b>ТОВАР УСПЕШНО РАЗМЕЩЕН НА ОПТОВОЙ ДОСКЕ «ДОРДОЙ»!</b>\n\n"
        f"📸 <b>{html.escape(title)}</b>\n"
        f"💰 Оптовая цена: <b>{price:g} KGS</b>\n"
        f"📍 Сектор: <b>{html.escape(default_sector)}</b>\n"
        f"📞 Связь: <b>{html.escape(default_phone)}</b>\n\n"
        f"📝 Описание: <i>{html.escape(caption)}</i>\n\n"
        f"⚡ <i>Оптовики из Бишкека, РФ и Казахстана теперь видят ваш товар на витрине!</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍️ Посмотреть товары на рынке", callback_data="show_all_market")],
        [InlineKeyboardButton(text="📸 Выложить еще фото", callback_data="clip_guide")]
    ])
    await send_html(message, success_text, reply_markup=kb)

@dp.message(F.voice)
async def handle_voice_message(message: types.Message):
    """Поддержка голосовых сообщений для работников рынка"""
    await send_html(
        message,
        "🎙️ <b>Голосовое сообщение получено!</b>\n\n"
        "💡 <i>Совет: чтобы выложить товар на оптовую доску рынка, нажмите на значок <b>📎 Скрепка</b> внизу, прикрепите фото товара и напишите цену и номер ряда. Товар сразу увидят тысячи покупателей!</i>"
    )

@dp.message(F.text.in_([
    I18N['ky']['btn_post_product_clip'],
    I18N['ru']['btn_post_product_clip'],
    I18N['zh']['btn_post_product_clip'],
    "📸 Выложить товар (Скрепка 📎)", "/add_product", "/photo"
]))
async def handle_post_product_guide(message: types.Message):
    guide_text = (
        "📎 <b>КАК ЛЕГКО ВЫЛОЖИТЬ ТОВАР ЧЕРЕЗ СКРЕПКУ В TELEGRAM:</b>\n\n"
        "Вам не нужно учиться сложным программам или заполнять сайты!\n\n"
        "1️⃣ Нажмите на значок <b>📎 Скрепка</b> внизу экрана (где поле для ввода текста).\n"
        "2️⃣ Выберите или сфотографируйте товар прямо у контейнера.\n"
        "3️⃣ Добавьте короткую подпись: <b>название, цену и контейнер</b>\n"
        "<i>(Например: Джинсы турция 950 сом, ряд 4 конт 18)</i>.\n"
        "4️⃣ Нажмите кнопку «Отправить»!\n\n"
        "🚀 Товар сразу появится в каталоге оптовых товаров рынка «Дордой» для покупателей из Кыргызстана, России и Казахстана с прямым переходом в ваш WhatsApp!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍️ Посмотреть товары на доске", callback_data="show_all_market")]
    ])
    await send_html(message, guide_text, reply_markup=kb)

@dp.callback_query(F.data == "clip_guide")
async def callback_clip_guide(call: types.CallbackQuery):
    await handle_post_product_guide(call.message)
    await call.answer()

@dp.callback_query(F.data == "show_all_market")
async def callback_show_all_market(call: types.CallbackQuery):
    await show_market_products(call.message)
    await call.answer()

# --- ГЛАВНАЯ ТОЧКА ВХОДА ---
async def main():
    await init_db()
    if os.environ.get("PORT"):
        await start_healthcheck_server()
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logging.warning(f"Webhook reset: {e}")

    print("🚀 Dordoi SuperBot запущен: HTML-парсер активен, учёт тачкистов включен, 0% рекламы!")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
