import asyncio
import logging
import urllib.parse
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

BOT_TOKEN = "8867783468:AAGvaT3xOUGCfbY7pdSEsJMzaEo6rdVCacI"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- БЕСПЛАТНЫЙ АВТОПЕРЕВОДЧИК ТЕКСТА ---
async def translate_text(text: str, target_lang: str) -> str:
    """Переводит произвольный текст без API ключей через защищенный шлюз"""
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

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect("dordoi_master.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                phone TEXT,
                role TEXT DEFAULT 'seller', -- seller, porter, food, supplies, cargo
                lang TEXT DEFAULT 'ky',
                is_active INTEGER DEFAULT 1
            )
        """)
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
        await db.commit()

# --- СЛОВАРИ И ЛОКАЛИЗАЦИЯ (RU / KY / ZH) ---
I18N = {
    'ky': {
        'welcome': "👋 Дордой базарынын ыкчам кызматына кош келиңиз!\nКеректүү кызматты тандаңыз:",
        'btn_porter': "🛒 Тачка чакыруу",
        'btn_food': "🍲 Тамак-аш / Түшкү тамак",
        'btn_supplies': "📦 Скотч, мүшөк, баул",
        'btn_cargo': "🚛 Карго чакыруу (РФ / КЗ)",
        'btn_worker': "⚙️ Мен аткаруучумун (Жумушчу)",
        'btn_lang': "🌐 Тилди алмаштыруу",
        'choose_sector': "📍 Базардын кайсы секторундасыз? Секторду тандаңыз:",
        'enter_loc': "Өтмөк (катар) жана контейнер номерин жазыңыз:\n(Мисалы: <i>3-проход, 45-контейнер</i>)",
        'enter_details_porter': "Кандай жүк? Баул канча жана каякка жеткирилет?\n(Мисалы: <i>3 чоң баул, Түндүк стоянкага чейин</i>):",
        'enter_details_food': "Эмне тамак жана канча порция керек?\n(Мисалы: <i>2 лагман, 3 самса, 1 кара чай</i>):",
        'enter_details_supplies': "Кандай упаковка керек?\n(Мисалы: <i>5 скотч, 10 чоң кара мүшөк</i>):",
        'enter_details_cargo': "Жүктүн салмагы жана кайсы шаарга жөнөтүлөт?\n(Мисалы: <i>300 кг кийим, Москва шаарына</i>):",
        'enter_phone': "Байланыш номериңизди жөнөтүңүз же жазыңыз (0700123456):",
        'order_created': "✅ Буйрутма кабыл алынды! Жакын арадагы аткаруучуларга билдирүү кетти.",
        'order_taken': "✅ Сиз буйрутманы алдыңыз! Кардар менен байланышыңыз.",
        'order_already_taken': "❌ Бул буйрутманы башка бирөө алып койду!",
        'notify_seller': "🔔 <b>Сиздин буйрутмаңыз кабыл алынды!</b>\n\nАткаруучу: {name}\nТел: {phone}\nЗаказ #{id}",
        'btn_take': "✋ Буйрутманы алдым",
        'btn_send_contact': "📱 Номерди жөнөтүү",
        'switch_seller': "🛍 Сатуучу режимине өтүү"
    },
    'ru': {
        'welcome': "👋 Добро пожаловать в единый сервис рынка «Дордой»!\nВыберите нужную услугу:",
        'btn_porter': "🛒 Вызвать тачку",
        'btn_food': "🍲 Заказать еду / Обед",
        'btn_supplies': "📦 Скотч, мешки, баулы",
        'btn_cargo': "🚛 Вызвать Карго (РФ / КЗ)",
        'btn_worker': "⚙️ Я исполнитель (Работник)",
        'btn_lang': "🌐 Сменить язык",
        'choose_sector': "📍 В каком вы секторе? Выберите сектор рынка:",
        'enter_loc': "Укажите проход (ряд) и номер контейнера:\n(Например: <i>3-проход, 45-контейнер</i>)",
        'enter_details_porter': "Какой груз? Сколько баулов и куда везти?\n(Например: <i>3 больших баула на Северную стоянку</i>):",
        'enter_details_food': "Что принести из еды?\n(Например: <i>2 плова, 3 самсы, 1 зеленый чай</i>):",
        'enter_details_supplies': "Какие расходники нужны?\n(Например: <i>5 рулонов скотча, 10 мешков</i>):",
        'enter_details_cargo': "Вес груза и город доставки?\n(Например: <i>300 кг трикотаж, на Москву</i>):",
        'enter_phone': "Отправьте ваш контактный номер (0700123456):",
        'order_created': "✅ Заявка принята! Все исполнители в секторе оповещены.",
        'order_taken': "✅ Вы взяли этот заказ! Свяжитесь с заказчиком.",
        'order_already_taken': "❌ Этот заказ уже забрал другой исполнитель!",
        'notify_seller': "🔔 <b>Ваш заказ принят исполнителем!</b>\n\nИсполнитель: {name}\nТел: {phone}\nЗаказ #{id}",
        'btn_take': "✋ Взять заказ",
        'btn_send_contact': "📱 Отправить контакт",
        'switch_seller': "🛍 Режим покупателя / продавца"
    },
    'zh': {
        'welcome': "👋 欢迎使用多尔多伊市场（Dordoi）综合服务平台！\n请选择您需要的服务：",
        'btn_porter': "🛒 叫板车 / 货运工人",
        'btn_food': "🍲 订餐 / 叫外卖",
        'btn_supplies': "📦 胶带、编织袋、打包用品",
        'btn_cargo': "🚛 叫物流货运 (发俄罗斯/哈萨克)",
        'btn_worker': "⚙️ 我是服务人员 (接单模式)",
        'btn_lang': "🌐 切换语言 / Language",
        'choose_sector': "📍 请选择您所在的市场区域：",
        'enter_loc': "请输入通道号和集装箱号：\n（例如：<i>3通道，45号集装箱</i>）",
        'enter_details_porter': "货物数量及目的地？\n（例如：<i>3个大包，送到北停车场</i>）：",
        'enter_details_food': "需要点什么餐？\n（例如：<i>2份手抓饭，3个烤包子，1壶绿茶</i>）：",
        'enter_details_supplies': "需要哪些打包用品？\n（例如：<i>5卷胶带，10个大编织袋</i>）：",
        'enter_details_cargo': "货物重量及送达城市？\n（例如：<i>300公斤服装，发往莫斯科</i>）：",
        'enter_phone': "请输入您的联系电话（例如 0700123456）：",
        'order_created': "✅ 订单已发布！附近的工人已收到提醒，稍后联系您。",
        'order_taken': "✅ 您已成功接单！请联系客户。",
        'order_already_taken': "❌ 抱歉，该订单已被其他人员抢先接走！",
        'notify_seller': "🔔 <b>已有工人接单并前往！</b>\n\n工人：{name}\n电话：{phone}\n订单编号 #{id}",
        'btn_take': "✋ 我要接单",
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

async def get_user_lang(user_id: int) -> str:
    async with aiosqlite.connect("dordoi_master.db") as db:
        async with db.execute("SELECT lang FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 'ky'

def get_main_menu(lang='ky', role='seller'):
    t = I18N.get(lang, I18N['ky'])
    if role == 'seller':
        kb = [
            [KeyboardButton(text=t['btn_porter']), KeyboardButton(text=t['btn_food'])],
            [KeyboardButton(text=t['btn_supplies']), KeyboardButton(text=t['btn_cargo'])],
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

def get_sectors_kb():
    buttons = []
    row = []
    for s in SECTORS:
        row.append(InlineKeyboardButton(text=s, callback_data=f"sec_{s}"))
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
        "🎉 Катталдыңыз! Буйрутмалар ушул жакка түшөт.\nВы зарегистрированы! Заказы будут поступать сюда.\n注册成功！相关订单将直接推送给您。",
        reply_markup=get_main_menu(lang, role)
    )

@dp.message(F.text.in_([I18N['ky']['switch_seller'], I18N['ru']['switch_seller'], I18N['zh']['switch_seller']]))
async def switch_back_to_seller(message: types.Message):
    lang = await get_user_lang(message.from_user.id)
    async with aiosqlite.connect("dordoi_master.db") as db:
        await db.execute("UPDATE users SET role = 'seller' WHERE user_id = ?", (message.from_user.id,))
        await db.commit()
    await message.answer("Сиз сатуучу режимине өттүңүз. / Режим торговца. / 已切换为商户模式。", reply_markup=get_main_menu(lang, 'seller'))

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
    await message.answer(t['choose_sector'], reply_markup=get_sectors_kb())

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
    lang = data['lang']
    t = I18N[lang]
    order_type = data['order_type']

    prompts = {
        'porter': t['enter_details_porter'],
        'food': t['enter_details_food'],
        'supplies': t['enter_details_supplies'],
        'cargo': t['enter_details_cargo']
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
        f"🚨 <b>ЖАҢЫ ЗАКАЗ / НОВЫЙ ЗАКАЗ #{order_id}</b> ({title_ru} | {title_zh})\n\n"
        f"📍 <b>Сектор:</b> {sector}\n"
        f"🚪 <b>Орду / Место:</b> {location}\n"
        f"📝 <b>Текст (оригинал):</b> {raw_details}\n"
        f"🔄 <b>Перевод (RU):</b> {translated_details}\n"
        f"👤 <b>Заказчик:</b> {message.from_user.full_name}\n"
        f"📞 <b>Тел:</b> {phone}"
    )

    card_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✋ Мен алдым / Беру / 接单", callback_data=f"take_{order_id}")],
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
    await call.message.answer(f"✅ Заказ #{order_id} бекитилди / закреплен за вами!")

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
    print("🚀 Dordoi SuperBot запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
