import telebot
from telebot import types
import sqlite3, random, threading, time, os, shutil, json, re
from datetime import datetime, date, timedelta

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "PLACEHOLDER_TOKEN")
bot = telebot.TeleBot(TOKEN)
DB_PATH = "seal_life.db"
BACKUP_DIR = "backups"
MAX_SEALS = 5
FISHING_COOLDOWN_MIN = 10
MAX_CLAN_MEMBERS = 20
CLAN_DUNGEON_MIN_LEVEL = 4
CLAN_DUNGEON_FLOORS = 10
PLAY_COOLDOWN_MIN = 15
BABY_GROW_DAYS = 3

# ==================== БЭКАП И МИГРАЦИИ ====================
def backup_db():
    if not os.path.exists(DB_PATH): return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bp = os.path.join(BACKUP_DIR, f"seal_life_{ts}.db")
    shutil.copy2(DB_PATH, bp)
    bks = sorted([os.path.join(BACKUP_DIR,f) for f in os.listdir(BACKUP_DIR) if f.endswith(".db")], key=os.path.getmtime)
    for o in bks[:-10]: os.remove(o)
    return bp

def get_db_version(conn):
    c = conn.cursor()
    try:
        c.execute("SELECT value FROM _meta WHERE key='schema_version'")
        r = c.fetchone()
        return int(r[0]) if r else 0
    except sqlite3.OperationalError: return 0

def set_db_version(conn, v):
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("INSERT OR REPLACE INTO _meta (key,value) VALUES ('schema_version',?)", (str(v),))
    conn.commit()

def migration_1(c):
    c.execute("""CREATE TABLE IF NOT EXISTS players (
        user_id INTEGER PRIMARY KEY, username TEXT, display_name TEXT, photo_path TEXT,
        fishnets INTEGER DEFAULT 100, faction TEXT, faction_rep INTEGER DEFAULT 0, fish_cooldown TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS seals (
        seal_id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, name TEXT,
        health INTEGER DEFAULT 100, max_health INTEGER DEFAULT 100, mood INTEGER DEFAULT 80,
        satiety INTEGER DEFAULT 80, strength INTEGER DEFAULT 10, defense INTEGER DEFAULT 5,
        level INTEGER DEFAULT 1, exp INTEGER DEFAULT 0, is_baby INTEGER DEFAULT 0, born_at TEXT,
        equipped_weapon TEXT, equipped_armor TEXT, equipped_helmet TEXT, equipped_shield TEXT,
        equipped_accessory TEXT, work_cooldown TEXT, play_cooldown TEXT, photo_path TEXT,
        work_cooldown_min INTEGER DEFAULT 0
    )""")
    c.execute("CREATE TABLE IF NOT EXISTS marriages (marriage_id INTEGER PRIMARY KEY AUTOINCREMENT, seal1_id INTEGER, seal2_id INTEGER, player1_id INTEGER, player2_id INTEGER, created_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS inventory (inv_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, item_name TEXT, item_type TEXT, quantity INTEGER DEFAULT 1)")
    c.execute("CREATE TABLE IF NOT EXISTS daily_quests (quest_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, quest_type TEXT, quest_target INTEGER, quest_progress INTEGER DEFAULT 0, quest_reward INTEGER, date TEXT, claimed INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS dungeon_runs (run_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, seal_id INTEGER, current_floor INTEGER DEFAULT 1, active INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS trade_offers (offer_id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, item_name TEXT, item_type TEXT, price INTEGER, created_at TEXT, active INTEGER DEFAULT 1)")
    c.execute("CREATE TABLE IF NOT EXISTS votes (vote_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, event_type TEXT, vote TEXT, date TEXT, UNIQUE(user_id, date))")
    c.execute("CREATE TABLE IF NOT EXISTS active_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, effect TEXT, expires_at TEXT, active INTEGER DEFAULT 1)")

def migration_2(c):
    c.execute("CREATE TABLE IF NOT EXISTS seal_skills (skill_id INTEGER PRIMARY KEY AUTOINCREMENT, seal_id INTEGER, skill_name TEXT, skill_effect TEXT, acquired_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS duels (duel_id INTEGER PRIMARY KEY AUTOINCREMENT, challenger_id INTEGER, opponent_id INTEGER, challenger_seal_id INTEGER, opponent_seal_id INTEGER, status TEXT DEFAULT 'pending', winner_id INTEGER, reward INTEGER, created_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS quest_chains (chain_id INTEGER PRIMARY KEY, name TEXT, story TEXT, steps_json TEXT, reward_json TEXT, reward_fishnets INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS player_quest_chains (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chain_id INTEGER, current_step INTEGER DEFAULT 0, step_progress INTEGER DEFAULT 0, completed INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS clans (clan_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, emblem TEXT, leader_id INTEGER, created_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS clan_members (id INTEGER PRIMARY KEY AUTOINCREMENT, clan_id INTEGER, user_id INTEGER, joined_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS clan_dungeons (id INTEGER PRIMARY KEY AUTOINCREMENT, clan_id INTEGER, current_floor INTEGER DEFAULT 1, active INTEGER DEFAULT 0, started_by INTEGER)")
    chains = [
        (1,"Потерянный компас","Старый мудрый тюлень потерял компас во время шторма.",
         json.dumps([{"type":"dungeon_floor","target":3,"desc":"Дойдите до 3-го этажа подземелья"},{"type":"battle_count","target":2,"desc":"Победите 2 боссов"},{"type":"craft_item","target":1,"desc":"Скрафтите 1 предмет"}]),
         json.dumps({"item":"Компас мудреца 🧭","type":"accessory"}),200),
        (2,"Тайна глубин","Древняя табличка говорит о сокровище на дне океана.",
         json.dumps([{"type":"dungeon_complete","target":1,"desc":"Пройдите 1 подземелье полностью"},{"type":"reach_level","target":10,"desc":"Достигните 10 уровня"}]),
         json.dumps({"item":"Амулет глубин 🌊","type":"accessory"}),500),
        (3,"Король арены","Станьте легендой среди тюленей!",
         json.dumps([{"type":"duel_win","target":3,"desc":"Победите 3 игроков в дуэлях"},{"type":"battle_count","target":5,"desc":"Победите 5 боссов"}]),
         json.dumps({"item":"Корона чемпиона 👑","type":"accessory"}),1000),
    ]
    c.executemany("INSERT OR REPLACE INTO quest_chains VALUES (?,?,?,?,?,?)", chains)

def migration_3(c):
    try: c.execute("ALTER TABLE seals ADD COLUMN equipped_artifact TEXT")
    except sqlite3.OperationalError: pass
    try: c.execute("ALTER TABLE dungeon_runs ADD COLUMN current_monster INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass

def migration_4(c):
    try: c.execute("ALTER TABLE seals ADD COLUMN active_potion TEXT")
    except sqlite3.OperationalError: pass
    try: c.execute("ALTER TABLE seals ADD COLUMN potion_uses INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    c.execute("""CREATE TABLE IF NOT EXISTS item_enchantments (
        ench_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, item_name TEXT,
        enchantment TEXT, created_at TEXT
    )""")

def migration_5(c):
    c.execute("""CREATE TABLE IF NOT EXISTS topic_bindings (
        chat_id INTEGER PRIMARY KEY, message_thread_id INTEGER
    )""")

MIGRATIONS = [migration_1, migration_2, migration_3, migration_4, migration_5]

def run_migrations():
    backup_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    v = get_db_version(conn)
    for i in range(v, len(MIGRATIONS)):
        MIGRATIONS[i](c)
    set_db_version(conn, len(MIGRATIONS))
    conn.commit()
    conn.close()

# ==================== КОНСТАНТЫ ====================
SHOP_ITEMS = {
    "Апельсин 🍊": {"price": 15, "type": "food", "satiety": 25, "mood": 10},
    "Рыба 🐟": {"price": 10, "type": "food", "satiety": 20, "mood": 5},
    "Кальмар 🦑": {"price": 25, "type": "food", "satiety": 35, "mood": 15},
    "Мороженое 🍦": {"price": 20, "type": "food", "satiety": 15, "mood": 30},
    "Креветка 🦐": {"price": 18, "type": "food", "satiety": 22, "mood": 8},
    "Устрица 🦪": {"price": 30, "type": "food", "satiety": 40, "mood": 20},
    "Водоросли 🌿": {"price": 8, "type": "food", "satiety": 15, "mood": 3},
    "Аптечка 💊": {"price": 100, "type": "medkit", "heal": 50},
    "Бантик 🎀": {"price": 40, "type": "accessory"},
    "Шарф 🧣": {"price": 35, "type": "accessory"},
    "Корона 👑": {"price": 200, "type": "accessory"},
    "Очки 🕶️": {"price": 50, "type": "accessory"},
    "Цветок 🌸": {"price": 25, "type": "accessory"},
    "Морская звезда ⭐": {"price": 60, "type": "accessory"},
    "Жемчужное ожерелье 🫧": {"price": 120, "type": "accessory"},
    "Перо чайки 🪶": {"price": 30, "type": "accessory"},
    "Радужный пояс 🌈": {"price": 80, "type": "accessory"},
    "Пустая колба 🧪": {"price": 15, "type": "potion_base"},
}
ITEM_BONUSES = {
    "Костяной меч 🗡️": {"str": 5}, "Акулий клык 🦷": {"str": 8}, "Трезубец 🔱": {"str": 12}, "Китовый клинок 🐋": {"str": 15},
    "Ядовитый клинок ☠️": {"str": 10}, "Ядовитый дротик 🎯": {"str": 7},
    "Чешуйчатая броня 🐟": {"def": 5, "hp": 10}, "Панцирь краба 🦀": {"def": 8, "hp": 15},
    "Плетёная броня 🧵": {"def": 10, "hp": 25}, "Кракеновый панцирь 🐙": {"def": 15, "hp": 40},
    "Шлем из ракушек 🐚": {"def": 3, "hp": 10}, "Костяной шлем 💀": {"def": 5, "hp": 15}, "Корона из зубов 👑": {"def": 8, "hp": 20},
    "Ядовитый шлем ☠️": {"def": 4, "hp": 12},
    "Щит из чешуи 🐠": {"def": 5}, "Панцирный щит 🛡️": {"def": 8}, "Щит кракена 🦑": {"def": 12}, "Ядовитый щит ☠️": {"def": 7},
    "Ледяной клинок ❄️": {"str": 18}, "Огненный меч 🔥": {"str": 20}, "Коралловый меч 🪸": {"str": 16},
    "Ледяная броня ❄️": {"def": 18, "hp": 50}, "Огненная броня 🔥": {"def": 16, "hp": 55},
    "Морозный шлем 🧊": {"def": 10, "hp": 30}, "Пламенный шлем 🔥": {"def": 12, "hp": 25},
    "Ледяной щит ❄️": {"def": 15}, "Щит пламени 🔥": {"def": 16},
    "Молниевый клинок ⚡": {"str": 25}, "Призрачный меч 👻": {"str": 28}, "Кристальный клинок 💎": {"str": 22},
    "Молниевая броня ⚡": {"def": 22, "hp": 70}, "Призрачная броня 👻": {"def": 24, "hp": 65},
    "Громовой шлем ⚡": {"def": 15, "hp": 45}, "Призрачный шлем 👻": {"def": 16, "hp": 40},
    "Щит молний ⚡": {"def": 20}, "Призрачный щит 👻": {"def": 22},
    "Клинок дракона 🐉": {"str": 35}, "Буревой топор 🌪️": {"str": 38},
    "Драконья броня 🐉": {"def": 30, "hp": 100}, "Буревая броня 🌪️": {"def": 28, "hp": 110},
    "Драконий шлем 🐉": {"def": 20, "hp": 60}, "Шлем бури 🌪️": {"def": 18, "hp": 65},
    "Драконий щит 🐉": {"def": 28}, "Щит бури 🌪️": {"def": 26},
    "Меч Богов ⚔️": {"str": 50}, "Клинок Бездны 🌑": {"str": 55},
    "Броня Богов 🛡️": {"def": 45, "hp": 200}, "Броня Бездны 🌑": {"def": 50, "hp": 180},
    "Шлем Богов 👑": {"def": 30, "hp": 120}, "Шлем Бездны 🌑": {"def": 32, "hp": 110},
    "Щит Богов 🛡️": {"def": 40}, "Щит Бездны 🌑": {"def": 42},
}

ACCESSORY_BONUSES = {
    "Бантик 🎀": 10, "Шарф 🧣": 8, "Корона 👑": 20, "Очки 🕶️": 7, "Цветок 🌸": 5,
    "Компас мудреца 🧭": 25, "Амулет глубин 🌊": 22, "Корона чемпиона 👑": 30,
    "Морская звезда ⭐": 12, "Жемчужное ожерелье 🫧": 18, "Перо чайки 🪶": 6, "Радужный пояс 🌈": 14,
}

CRAFT_TIERS = ["common", "uncommon", "rare", "epic", "legendary"]
CRAFT_TIER_MULT = {"common": 1.0, "uncommon": 1.3, "rare": 1.6, "epic": 2.0, "legendary": 2.5}
CRAFT_TIER_LABEL = {"common": "Обычный", "uncommon": "Необычный", "rare": "Редкий", "epic": "Эпический", "legendary": "Легендарный"}

CRAFT_RECIPES = [
    {"name": "Костяной меч 🗡️", "type": "weapon", "tier": "common", "resources": {"Акулий зуб 🦈": 3}},
    {"name": "Акулий клык 🦷", "type": "weapon", "tier": "common", "resources": {"Акулий зуб 🦈": 5, "Чешуя 🐟": 2}},
    {"name": "Трезубец 🔱", "type": "weapon", "tier": "common", "resources": {"Щупальце 🐙": 4, "Акулий зуб 🦈": 3}},
    {"name": "Китовый клинок 🐋", "type": "weapon", "tier": "common", "resources": {"Китовый ус 🐋": 3, "Жемчуг 🫧": 1}},
    {"name": "Ядовитый клинок ☠️", "type": "weapon", "tier": "common", "resources": {"Жало 🐡": 3, "Акулий зуб 🦈": 2}},
    {"name": "Ядовитый дротик 🎯", "type": "weapon", "tier": "common", "resources": {"Жало 🐡": 2, "Чешуя 🐟": 3}},
    {"name": "Чешуйчатая броня 🐟", "type": "armor", "tier": "common", "resources": {"Чешуя 🐟": 4}},
    {"name": "Панцирь краба 🦀", "type": "armor", "tier": "common", "resources": {"Панцирь 🦀": 3}},
    {"name": "Плетёная броня 🧵", "type": "armor", "tier": "common", "resources": {"Щупальце 🐙": 3, "Чешуя 🐟": 2}},
    {"name": "Кракеновый панцирь 🐙", "type": "armor", "tier": "common", "resources": {"Щупальце 🐙": 5, "Жемчуг 🫧": 1}},
    {"name": "Шлем из ракушек 🐚", "type": "helmet", "tier": "common", "resources": {"Панцирь 🦀": 3, "Чешуя 🐟": 1}},
    {"name": "Костяной шлем 💀", "type": "helmet", "tier": "common", "resources": {"Акулий зуб 🦈": 3}},
    {"name": "Корона из зубов 👑", "type": "helmet", "tier": "common", "resources": {"Акулий зуб 🦈": 5, "Жемчуг 🫧": 1}},
    {"name": "Ядовитый шлем ☠️", "type": "helmet", "tier": "common", "resources": {"Жало 🐡": 3, "Чешуя 🐟": 2}},
    {"name": "Щит из чешуи 🐠", "type": "shield", "tier": "common", "resources": {"Чешуя 🐟": 4, "Панцирь 🦀": 1}},
    {"name": "Панцирный щит 🛡️", "type": "shield", "tier": "common", "resources": {"Панцирь 🦀": 4}},
    {"name": "Щит кракена 🦑", "type": "shield", "tier": "common", "resources": {"Щупальце 🐙": 3, "Панцирь 🦀": 2}},
    {"name": "Ядовитый щит ☠️", "type": "shield", "tier": "common", "resources": {"Жало 🐡": 4, "Панцирь 🦀": 2}},
    {"name": "Коралловый меч 🪸", "type": "weapon", "tier": "uncommon", "resources": {"Коралл 🪸": 4, "Акулий зуб 🦈": 2}},
    {"name": "Ледяной клинок ❄️", "type": "weapon", "tier": "uncommon", "resources": {"Ледяной кристалл 🧊": 3, "Чешуя 🐟": 3}},
    {"name": "Огненный меч 🔥", "type": "weapon", "tier": "uncommon", "resources": {"Огненный камень 🔥": 3, "Акулий зуб 🦈": 3}},
    {"name": "Ледяная броня ❄️", "type": "armor", "tier": "uncommon", "resources": {"Ледяной кристалл 🧊": 4, "Панцирь 🦀": 2}},
    {"name": "Огненная броня 🔥", "type": "armor", "tier": "uncommon", "resources": {"Огненный камень 🔥": 4, "Чешуя 🐟": 3}},
    {"name": "Морозный шлем 🧊", "type": "helmet", "tier": "uncommon", "resources": {"Ледяной кристалл 🧊": 3, "Панцирь 🦀": 2}},
    {"name": "Пламенный шлем 🔥", "type": "helmet", "tier": "uncommon", "resources": {"Огненный камень 🔥": 3, "Акулий зуб 🦈": 2}},
    {"name": "Ледяной щит ❄️", "type": "shield", "tier": "uncommon", "resources": {"Ледяной кристалл 🧊": 3, "Панцирь 🦀": 2}},
    {"name": "Щит пламени 🔥", "type": "shield", "tier": "uncommon", "resources": {"Огненный камень 🔥": 3, "Панцирь 🦀": 2}},
    {"name": "Кристальный клинок 💎", "type": "weapon", "tier": "rare", "resources": {"Кристальный осколок 💎": 4, "Коралл 🪸": 2}},
    {"name": "Молниевый клинок ⚡", "type": "weapon", "tier": "rare", "resources": {"Грозовой камень ⚡": 4, "Ледяной кристалл 🧊": 2}},
    {"name": "Призрачный меч 👻", "type": "weapon", "tier": "rare", "resources": {"Призрачная эссенция 👻": 4, "Огненный камень 🔥": 2}},
    {"name": "Молниевая броня ⚡", "type": "armor", "tier": "rare", "resources": {"Грозовой камень ⚡": 5, "Ледяной кристалл 🧊": 3}},
    {"name": "Призрачная броня 👻", "type": "armor", "tier": "rare", "resources": {"Призрачная эссенция 👻": 5, "Огненный камень 🔥": 3}},
    {"name": "Громовой шлем ⚡", "type": "helmet", "tier": "rare", "resources": {"Грозовой камень ⚡": 3, "Кристальный осколок 💎": 1}},
    {"name": "Призрачный шлем 👻", "type": "helmet", "tier": "rare", "resources": {"Призрачная эессенция 👻": 3, "Кристальный осколок 💎": 1}},
    {"name": "Щит молний ⚡", "type": "shield", "tier": "rare", "resources": {"Грозовой камень ⚡": 3, "Панцирь 🦀": 3}},
    {"name": "Призрачный щит 👻", "type": "shield", "tier": "rare", "resources": {"Призрачная эссенция 👻": 3, "Панцирь 🦀": 3}},
    {"name": "Клинок дракона 🐉", "type": "weapon", "tier": "epic", "resources": {"Драконья чешуя 🐉": 5, "Грозовой камень ⚡": 3}},
    {"name": "Буревой топор 🌪️", "type": "weapon", "tier": "epic", "resources": {"Драконья чешуя 🐉": 5, "Огненный камень 🔥": 3}},
    {"name": "Драконья броня 🐉", "type": "armor", "tier": "epic", "resources": {"Драконья чешуя 🐉": 6, "Кристальный осколок 💎": 3}},
    {"name": "Буревая броня 🌪️", "type": "armor", "tier": "epic", "resources": {"Драконья чешуя 🐉": 6, "Грозовой камень ⚡": 3}},
    {"name": "Драконий шлем 🐉", "type": "helmet", "tier": "epic", "resources": {"Драконья чешуя 🐉": 4, "Кровь кракена 🩸": 2}},
    {"name": "Шлем бури 🌪️", "type": "helmet", "tier": "epic", "resources": {"Драконья чешуя 🐉": 4, "Тёмная эссенция 🌑": 2}},
    {"name": "Драконий щит 🐉", "type": "shield", "tier": "epic", "resources": {"Драконья чешуя 🐉": 4, "Кровь кракена 🩸": 2}},
    {"name": "Щит бури 🌪️", "type": "shield", "tier": "epic", "resources": {"Драконья чешуя 🐉": 4, "Тёмная эссенция 🌑": 2}},
    {"name": "Меч Богов ⚔️", "type": "weapon", "tier": "legendary", "resources": {"Слеза Посейдона 💧": 2, "Драконья чешуя 🐉": 5}},
    {"name": "Клинок Бездны 🌑", "type": "weapon", "tier": "legendary", "resources": {"Слеза Посейдона 💧": 2, "Тёмная эссенция 🌑": 5}},
    {"name": "Броня Богов 🛡️", "type": "armor", "tier": "legendary", "resources": {"Слеза Посейдона 💧": 3, "Драконья чешуя 🐉": 5}},
    {"name": "Броня Бездны 🌑", "type": "armor", "tier": "legendary", "resources": {"Слеза Посейдона 💧": 3, "Тёмная эссенция 🌑": 5}},
    {"name": "Шлем Богов 👑", "type": "helmet", "tier": "legendary", "resources": {"Слеза Посейдона 💧": 2, "Кровь кракена 🩸": 3}},
    {"name": "Шлем Бездны 🌑", "type": "helmet", "tier": "legendary", "resources": {"Слеза Посейдона 💧": 2, "Тёмная эссенция 🌑": 3}},
    {"name": "Щит Богов 🛡️", "type": "shield", "tier": "legendary", "resources": {"Слеза Посейдона 💧": 2, "Кровь кракена 🩸": 3}},
    {"name": "Щит Бездны 🌑", "type": "shield", "tier": "legendary", "resources": {"Слеза Посейдона 💧": 2, "Тёмная эссенция 🌑": 3}},
    {"name": "Зелье лечения 💚", "type": "potion", "tier": "common", "resources": {"Водоросли 🌿": 3, "Пустая колба 🧪": 1}, "effect": "heal", "value": 40},
    {"name": "Зелье силы 💪", "type": "potion", "tier": "common", "resources": {"Акулий зуб 🦈": 2, "Пустая колба 🧪": 1}, "effect": "str_boost", "value": 10, "duration": 5},
    {"name": "Зелье защиты 🛡️", "type": "potion", "tier": "common", "resources": {"Панцирь 🦀": 2, "Пустая колба 🧪": 1}, "effect": "def_boost", "value": 10, "duration": 5},
    {"name": "Зелье скорости 💨", "type": "potion", "tier": "uncommon", "resources": {"Жало 🐡": 3, "Пустая колба 🧪": 1}, "effect": "speed_boost", "value": 3, "duration": 3},
    {"name": "Зелье ярости 😤", "type": "potion", "tier": "uncommon", "resources": {"Кровь кракена 🩸": 1, "Огненный камень 🔥": 2, "Пустая колба 🧪": 1}, "effect": "rage", "value": 50, "duration": 3},
    {"name": "Зелье регенерации ♻️", "type": "potion", "tier": "rare", "resources": {"Кристальный осколок 💎": 2, "Водоросли 🌿": 3, "Пустая колба 🧪": 1}, "effect": "regen_potion", "value": 15, "duration": 5},
    {"name": "Зелье невидимости 👻", "type": "potion", "tier": "rare", "resources": {"Призрачная эссенция 👻": 3, "Пустая колба 🧪": 1}, "effect": "dodge_boost", "value": 30, "duration": 3},
    {"name": "Эликсир титана 🏔️", "type": "potion", "tier": "epic", "resources": {"Драконья чешуя 🐉": 2, "Кровь кракена 🩸": 2, "Пустая колба 🧪": 1}, "effect": "titan", "value": 25, "duration": 5},
    {"name": "Антидот 💊", "type": "potion", "tier": "common", "resources": {"Водоросли 🌿": 2, "Жало 🐡": 1, "Пустая колба 🧪": 1}, "effect": "antidote", "value": 0},
]

ENCHANTMENTS = {
    "Огненное зачарование 🔥": {"bonus_str": 5, "bonus_def": 0, "cost": {"Огненный камень 🔥": 3}},
    "Ледяное зачарование ❄️": {"bonus_str": 0, "bonus_def": 5, "cost": {"Ледяной кристалл 🧊": 3}},
    "Теневое зачарование 🌑": {"bonus_str": 3, "bonus_def": 3, "cost": {"Тёмная эссенция 🌑": 3}},
    "Кристальное зачарование 💎": {"bonus_str": 4, "bonus_def": 2, "cost": {"Кристальный осколок 💎": 3}},
    "Кровавое зачарование 🩸": {"bonus_str": 6, "bonus_def": 0, "cost": {"Кровь кракена 🩸": 2, "Жало 🐡": 2}},
    "Древнее зачарование 📜": {"bonus_str": 8, "bonus_def": 4, "cost": {"Слеза Посейдона 💧": 1, "Кристальный осколок 💎": 2}},
}

POTION_EFFECTS = {
    "heal": "Восстанавливает HP", "str_boost": "Бонус к силе", "def_boost": "Бонус к защите",
    "speed_boost": "Доп. атака", "rage": "+50% урон", "regen_potion": "Регенерация HP",
    "dodge_boost": "Шанс уклонения", "titan": "+25 стр и +25 защ", "antidote": "Снимает отравление",
}

ARTIFACTS = {
    "F": [{"name":"Ржавый ключ 🗝️","str":2,"def":1,"hp":5},{"name":"Старый компас 🧭","str":1,"def":2,"hp":5},{"name":"Обломок ракушки 🐚","str":2,"def":2,"hp":3}],
    "E": [{"name":"Медный амулет 🟤","str":4,"def":3,"hp":10},{"name":"Рыбацкий талисман 🎣","str":3,"def":4,"hp":12}],
    "D": [{"name":"Серебряный медальон 🥈","str":7,"def":5,"hp":20},{"name":"Коралловый браслет 🪸","str":6,"def":6,"hp":18}],
    "C": [{"name":"Жемчужина силы ⚪","str":12,"def":8,"hp":30},{"name":"Акулий талисман 🦈","str":10,"def":10,"hp":25}],
    "B": [{"name":"Кристалл глубин 💎","str":18,"def":12,"hp":50},{"name":"Раковина Левиафана 🐚","str":15,"def":15,"hp":45}],
    "A": [{"name":"Сердце океана 💙","str":28,"def":18,"hp":80},{"name":"Корона Морского Царя 👑","str":25,"def":20,"hp":75}],
    "S": [{"name":"Слеза Посейдона 💧","str":45,"def":30,"hp":150},{"name":"Трезубец Бездны 🔱","str":50,"def":25,"hp":120}],
}

CHEST_WEAPONS = {
    "F": [{"name":"Ржавый нож 🗡️","str":4},{"name":"Деревянный меч 🪵","str":5}],
    "E": [{"name":"Каменный топор 🪓","str":7},{"name":"Костяной клинок 🦴","str":8}],
    "D": [{"name":"Коралловый меч 🪸","str":11},{"name":"Осколочный клинок 💎","str":12}],
    "C": [{"name":"Ледяной клинок ❄️","str":16},{"name":"Огненный меч 🔥","str":18}],
    "B": [{"name":"Молниевый клинок ⚡","str":22},{"name":"Призрачный меч 👻","str":25}],
    "A": [{"name":"Клинок дракона 🐉","str":32},{"name":"Буревой топор 🌪️","str":35}],
    "S": [{"name":"Меч Богов ⚔️","str":50},{"name":"Клинок Бездны 🌑","str":55}],
}

CHEST_ARMOR = {
    "F": [{"name":"Тряпьё 🧣","def":3,"hp":5},{"name":"Кожаная броня 👕","def":4,"hp":8}],
    "E": [{"name":"Медная броня 🟤","def":6,"hp":15},{"name":"Костяная броня 🦴","def":7,"hp":12}],
    "D": [{"name":"Коралловая броня 🪸","def":10,"hp":25},{"name":"Акулья чешуя 🦈","def":12,"hp":20}],
    "C": [{"name":"Ледяная броня ❄️","def":15,"hp":40},{"name":"Огненная броня 🔥","def":14,"hp":45}],
    "B": [{"name":"Молниевая броня ⚡","def":20,"hp":60},{"name":"Призрачная броня 👻","def":22,"hp":55}],
    "A": [{"name":"Драконья броня 🐉","def":30,"hp":100},{"name":"Буревая броня 🌪️","def":28,"hp":110}],
    "S": [{"name":"Броня Богов 🛡️","def":45,"hp":200},{"name":"Броня Бездны 🌑","def":50,"hp":180}],
}

CHEST_CONTENTS = {
    "F": {"fishnets": (10, 30)}, "E": {"fishnets": (30, 60)}, "D": {"fishnets": (60, 120)},
    "C": {"fishnets": (120, 250)}, "B": {"fishnets": (250, 500)}, "A": {"fishnets": (500, 1000)}, "S": {"fishnets": (1000, 2000)},
}

RESOURCE_SELL_PRICES = {
    "Чешуя 🐟": 5, "Панцирь 🦀": 7, "Акулий зуб 🦈": 10, "Щупальце 🐙": 12,
    "Жемчуг 🫧": 25, "Китовый ус 🐋": 15, "Жало 🐡": 8,
    "Коралл 🪸": 15, "Ледяной кристалл 🧊": 20, "Огненный камень 🔥": 20,
    "Грозовой камень ⚡": 30, "Кристальный осколок 💎": 35, "Призрачная эссенция 👻": 35,
    "Драконья чешуя 🐉": 60, "Кровь кракена 🩸": 50, "Тёмная эссенция 🌑": 55,
    "Слеза Посейдона 💧": 120,
}

POTION_SELL_PRICES = {
    "Зелье лечения 💚": 30, "Зелье силы 💪": 40, "Зелье защиты 🛡️": 40,
    "Зелье скорости 💨": 60, "Зелье ярости 😤": 80, "Зелье регенерации ♻️": 100,
    "Зелье невидимости 👻": 100, "Эликсир титана 🏔️": 200, "Антидот 💊": 25,
}

RARITY_SELL_PRICES = {"F": 15, "E": 35, "D": 75, "C": 150, "B": 350, "A": 700, "S": 1500}

DUNGEON_FLOORS_CONFIG = [
    {"monsters": 2, "chest_rarity": "F", "hp_mult": 1.0, "str_mult": 1.0},
    {"monsters": 2, "chest_rarity": "F", "hp_mult": 1.3, "str_mult": 1.2},
    {"monsters": 3, "chest_rarity": "E", "hp_mult": 1.6, "str_mult": 1.4},
    {"monsters": 3, "chest_rarity": "D", "hp_mult": 2.0, "str_mult": 1.6},
    {"monsters": 3, "chest_rarity": "C", "hp_mult": 2.5, "str_mult": 1.8},
    {"monsters": 4, "chest_rarity": "C", "hp_mult": 3.0, "str_mult": 2.0},
    {"monsters": 4, "chest_rarity": "B", "hp_mult": 3.5, "str_mult": 2.2},
    {"monsters": 4, "chest_rarity": "A", "hp_mult": 4.0, "str_mult": 2.5},
    {"monsters": 5, "chest_rarity": "A", "hp_mult": 5.0, "str_mult": 3.0},
    {"monsters": 5, "chest_rarity": "S", "hp_mult": 6.0, "str_mult": 3.5},
]
DUNGEON_TOTAL_FLOORS = 10

ITEM_TYPES = {}
for _n, _i in SHOP_ITEMS.items(): ITEM_TYPES[_n] = _i["type"]
for _r in CRAFT_RECIPES:
    ITEM_TYPES[_r["name"]] = _r["type"]
    if "effect" in _r: ITEM_TYPES[_r["name"]] = "potion"
for _r in "FEDCBAS":
    ITEM_TYPES[f"Сундук [{_r}] 📦"] = "chest"
    for _a in ARTIFACTS.get(_r, []):
        _fn = f"{_a['name']} [{_r}]"
        ITEM_BONUSES[_fn] = {"str": _a.get("str",0), "def": _a.get("def",0), "hp": _a.get("hp",0)}
        ITEM_TYPES[_fn] = "artifact"
    for _w in CHEST_WEAPONS.get(_r, []):
        _fn = f"{_w['name']} [{_r}]"
        ITEM_BONUSES[_fn] = {"str": _w.get("str",0)}
        ITEM_TYPES[_fn] = "weapon"
    for _a in CHEST_ARMOR.get(_r, []):
        _fn = f"{_a['name']} [{_r}]"
        ITEM_BONUSES[_fn] = {"def": _a.get("def",0), "hp": _a.get("hp",0)}
        ITEM_TYPES[_fn] = "armor"
ITEM_TYPES.update({"Компас мудреца 🧭": "accessory", "Амулет глубин 🌊": "accessory", "Корона чемпиона 👑": "accessory"})
for _p in POTION_SELL_PRICES: ITEM_TYPES[_p] = "potion"

SEAL_SKILLS_POOL = [
    {"name": "Критический удар ⚡", "effect": "crit_15", "desc": "15% шанс двойного урона"},
    {"name": "Толстая кожа 🛡️", "effect": "dmg_reduce_10", "desc": "-10% получаемого урона"},
    {"name": "Вампиризм 🩸", "effect": "lifesteal_5", "desc": "Восстанавливает 5% урона"},
    {"name": "Уклонение 💨", "effect": "dodge_10", "desc": "10% шанс увернуться"},
    {"name": "Берсерк 😤", "effect": "berserk", "desc": "+50% урона при HP<30%"},
    {"name": "Регенерация 💚", "effect": "regen", "desc": "+5 HP/час"},
    {"name": "Шипы 🌵", "effect": "thorns", "desc": "Отражает 20% урона"},
    {"name": "Двойной удар ⚔️", "effect": "double_strike", "desc": "10% шанс 2 атаки"},
]

DUNGEON_MONSTERS = [
    {"name": "Фугу 🐡", "hp": 30, "str": 8, "def": 3, "drops": {"Жало 🐡": 0.7}},
    {"name": "Креветка-ниндзя 🦐", "hp": 35, "str": 9, "def": 8, "drops": {"Панцирь 🦀": 0.5, "Чешуя 🐟": 0.3}},
    {"name": "Акула 🦈", "hp": 50, "str": 12, "def": 5, "drops": {"Акулий зуб 🦈": 0.7}},
    {"name": "Морской змей 🐍", "hp": 60, "str": 15, "def": 6, "drops": {"Чешуя 🐟": 0.7}},
    {"name": "Кракен 🐙", "hp": 80, "str": 18, "def": 8, "drops": {"Щупальце 🐙": 0.7, "Жемчуг 🫧": 0.1}},
    {"name": "Лобстер 🦞", "hp": 40, "str": 10, "def": 10, "drops": {"Панцирь 🦀": 0.7}},
    {"name": "Кашалот 🐋", "hp": 120, "str": 20, "def": 12, "drops": {"Китовый ус 🐋": 0.6}},
    {"name": "Электрический скат ⚡", "hp": 55, "str": 14, "def": 4, "drops": {"Чешуя 🐟": 0.5, "Жало 🐡": 0.3}},
    {"name": "Гигантская медуза 🪼", "hp": 45, "str": 11, "def": 3, "drops": {"Жало 🐡": 0.6}},
    {"name": "Морской дьявол 😈", "hp": 90, "str": 16, "def": 9, "drops": {"Жемчуг 🫧": 0.3, "Чешуя 🐟": 0.4}},
    {"name": "Коралловый голем 🪸", "hp": 70, "str": 12, "def": 14, "drops": {"Коралл 🪸": 0.7}},
    {"name": "Ледяной краб 🧊", "hp": 65, "str": 14, "def": 10, "drops": {"Ледяной кристалл 🧊": 0.4, "Панцирь 🦀": 0.4}},
    {"name": "Огненный спрут 🔥", "hp": 75, "str": 16, "def": 6, "drops": {"Огненный камень 🔥": 0.4, "Щупальце 🐙": 0.3}},
    {"name": "Громовой скат ⚡", "hp": 60, "str": 18, "def": 5, "drops": {"Грозовой камень ⚡": 0.35, "Жало 🐡": 0.3}},
    {"name": "Призрачная медуза 👻", "hp": 50, "str": 13, "def": 8, "drops": {"Призрачная эссенция 👻": 0.35}},
    {"name": "Кристальный страж 💎", "hp": 85, "str": 15, "def": 16, "drops": {"Кристальный осколок 💎": 0.3}},
    {"name": "Дракончик 🐉", "hp": 100, "str": 22, "def": 12, "drops": {"Драконья чешуя 🐉": 0.3}},
    {"name": "Кровавый кракен 🩸", "hp": 90, "str": 20, "def": 10, "drops": {"Кровь кракена 🩸": 0.25}},
    {"name": "Теневой змей 🌑", "hp": 80, "str": 19, "def": 11, "drops": {"Тёмная эссенция 🌑": 0.25}},
    {"name": "Глубинный левиафан 🐋", "hp": 130, "str": 24, "def": 14, "drops": {"Слеза Посейдона 💧": 0.05, "Чешуя 🐟": 0.5}},
]

BOSSES = [
    {"name": "Краб-босс 🦀", "drops": {"Панцирь 🦀": 0.8, "Коралл 🪸": 0.3}},
    {"name": "Акула 🦈", "drops": {"Акулий зуб 🦈": 0.8, "Чешуя 🐟": 0.3}},
    {"name": "Осьминог 🐙", "drops": {"Щупальце 🐙": 0.8, "Жемчуг 🫧": 0.1}},
    {"name": "Морской ёжик 🦔", "drops": {"Жало 🐡": 0.8}},
    {"name": "Кашалот 🐋", "drops": {"Китовый ус 🐋": 0.7}},
    {"name": "Морской змей 🐍", "drops": {"Чешуя 🐟": 0.8}},
    {"name": "Гигантский краб 🦀", "drops": {"Панцирь 🦀": 0.8, "Жемчуг 🫧": 0.15}},
    {"name": "Электрический скат ⚡", "drops": {"Чешуя 🐟": 0.7, "Жало 🐡": 0.3, "Грозовой камень ⚡": 0.2}},
    {"name": "Глубинный монстр 🌑", "drops": {"Жемчуг 🫧": 0.4, "Щупальце 🐙": 0.5, "Тёмная эссенция 🌑": 0.15}},
    {"name": "Король креветок 🦐", "drops": {"Панцирь 🦀": 0.7, "Чешуя 🐟": 0.3, "Ледяной кристалл 🧊": 0.2}},
    {"name": "Огненный кракен 🔥", "drops": {"Огненный камень 🔥": 0.5, "Щупальце 🐙": 0.3, "Кровь кракена 🩸": 0.15}},
    {"name": "Ледяной левиафан 🧊", "drops": {"Ледяной кристалл 🧊": 0.5, "Чешуя 🐟": 0.3, "Кристальный осколок 💎": 0.1}},
    {"name": "Грозовой дракон ⚡", "drops": {"Грозовой камень ⚡": 0.5, "Драконья чешуя 🐉": 0.15}},
    {"name": "Призрачный король 👻", "drops": {"Призрачная эссенция 👻": 0.5, "Тёмная эссенция 🌑": 0.15}},
    {"name": "Древний кракен 🐙", "drops": {"Кровь кракена 🩸": 0.3, "Жемчуг 🫧": 0.3, "Слеза Посейдона 💧": 0.05}},
    {"name": "Повелитель глубин 🌑", "drops": {"Тёмная эссенция 🌑": 0.3, "Драконья чешуя 🐉": 0.15, "Слеза Посейдона 💧": 0.08}},
]

CLAN_DUNGEON_MONSTERS = [
    {"name": "Страж глубин 🌊", "hp": 200, "str": 25, "def": 15}, {"name": "Древний краб 🦀", "hp": 250, "str": 30, "def": 20},
    {"name": "Призрачная акула 👻", "hp": 300, "str": 35, "def": 18}, {"name": "Ледяной кальмар 🧊", "hp": 350, "str": 40, "def": 25},
    {"name": "Гигантский спрут 🐙", "hp": 400, "str": 45, "def": 22}, {"name": "Морской дракон 🐉", "hp": 500, "str": 55, "def": 30},
    {"name": "Бездонный левиафан 🐋", "hp": 600, "str": 60, "def": 35}, {"name": "Крашеный кракен 🦑", "hp": 700, "str": 70, "def": 40},
    {"name": "Древний бог морей 🔱", "hp": 800, "str": 80, "def": 45}, {"name": "Повелитель бездны 🌑", "hp": 1000, "str": 100, "def": 60},
]

JOBS = [
    {"name": "Рыболов 🎣", "desc": "Ловить рыбу", "reward_min": 20, "reward_max": 50, "cooldown_min": 30, "mood_cost": 5, "satiety_cost": 10},
    {"name": "Почтальон 📬", "desc": "Разносить почту", "reward_min": 30, "reward_max": 60, "cooldown_min": 45, "mood_cost": 8, "satiety_cost": 15},
    {"name": "Укротитель 🦭", "desc": "Укрощать морских зверей", "reward_min": 50, "reward_max": 100, "cooldown_min": 60, "mood_cost": 12, "satiety_cost": 20},
    {"name": "Водолаз 🤿", "desc": "Исследовать глубины", "reward_min": 40, "reward_max": 80, "cooldown_min": 50, "mood_cost": 10, "satiety_cost": 18},
    {"name": "Актёр 🎭", "desc": "Выступать в шоу", "reward_min": 35, "reward_max": 70, "cooldown_min": 40, "mood_cost": 6, "satiety_cost": 12},
]

FISH_TYPES = [
    {"name": "Малёк 🐤", "reward": (3, 8), "correct": "Подсечь!"}, {"name": "Окунь 🐟", "reward": (8, 15), "correct": "Подсечь!"},
    {"name": "Сёмга 🐠", "reward": (15, 25), "correct": "Ждать"}, {"name": "Золотая рыбка ✨", "reward": (30, 50), "correct": "Ждать"},
    {"name": "Краб 🦀", "reward": (10, 20), "correct": "Отпустить"},
]

DAILY_EVENTS = [
    {"event_type": "exp_boost", "effect": "1.5", "desc": "+50% к опыту!"},
    {"event_type": "shop_discount", "effect": "0.2", "desc": "Скидки 20% в магазине!"},
    {"event_type": "fishing_bonus", "effect": "2.0", "desc": "x2 рыбнеток за рыбалку!"},
]

FACTIONS = {
    "hunters": {"name": "Стая охотников 🎯", "desc": "Бонус за бои"},
    "fashion": {"name": "Клуб модников 💅", "desc": "Бонус к настроению"},
    "explorers": {"name": "Гильдия исследователей 🧭", "desc": "Бонус к опыту"},
}

RANDOM_ENCOUNTERS = [
    {"name": "Сундук на берегу! 📦", "type": "item", "chance": 0.12, "items": ["Чешуя 🐟", "Панцирь 🦀", "Акулий зуб 🦈", "Жемчуг 🫧", "Коралл 🪸", "Ледяной кристалл 🧊"]},
    {"name": "Злой краб! 🦀", "type": "battle", "chance": 0.10, "mood_cost": 10, "satiety_cost": 10, "drop": {"Панцирь 🦀": 0.5}},
    {"name": "Дружелюбный дельфин 🐬", "type": "hint", "chance": 0.08, "fishnet_reward": (10, 30)},
    {"name": "Затонувший корабль 🚢", "type": "fishnets", "chance": 0.06, "fishnet_reward": (30, 80)},
    {"name": "Морская ведьма 🧙‍♀️", "type": "item", "chance": 0.05, "items": ["Тёмная эссенция 🌑", "Кровь кракена 🩸", "Призрачная эссенция 👻"]},
    {"name": "Драконья пещера 🐉", "type": "item", "chance": 0.03, "items": ["Драконья чешуя 🐉", "Огненный камень 🔥"]},
]

QUEST_TEMPLATES = [
    {"type": "play", "target": 3, "reward": 30, "desc": "Поиграть 3 раза"}, {"type": "feed", "target": 3, "reward": 30, "desc": "Покормить 3 раза"},
    {"type": "battle", "target": 1, "reward": 40, "desc": "Победить 1 босса"}, {"type": "dungeon", "target": 1, "reward": 50, "desc": "Пройти 1 подземелье"},
    {"type": "shop", "target": 1, "reward": 20, "desc": "Купить 1 предмет"}, {"type": "work", "target": 1, "reward": 35, "desc": "Отправить на работу"},
    {"type": "craft", "target": 1, "reward": 25, "desc": "Скрафтить 1 предмет"}, {"type": "fish", "target": 1, "reward": 25, "desc": "Поймать 1 рыбу"},
    {"type": "potion", "target": 1, "reward": 30, "desc": "Сварить 1 зелье"}, {"type": "enchant", "target": 1, "reward": 40, "desc": "Зачаровать 1 предмет"},
]

CLAN_EMOJIS = ["🦭", "🐋", "🦈", "🐙", "🦀", "🦐", "🦑", "🐬", "🐳", "🐢"]

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def _safe_int(value, default=0):
    if value is None: return default
    try: return int(value)
    except (ValueError, TypeError): return default

def reg_step(chat_id, user_id, handler, *args):
    def wrapper(message):
        if message.from_user and message.from_user.id != user_id:
            bot.register_next_step_handler_by_chat_id(chat_id, wrapper)
            return
        handler(message, *args)
    bot.register_next_step_handler_by_chat_id(chat_id, wrapper)

def get_player(uid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM players WHERE user_id=?", (uid,)); r = c.fetchone(); conn.close(); return r

def get_seal(sid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM seals WHERE seal_id=?", (sid,)); r = c.fetchone(); conn.close()
    if r: check_baby_growth(sid)
    return r

def get_player_seals(uid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM seals WHERE owner_id=?", (uid,)); r = c.fetchall(); conn.close(); return r

def get_seal_count(uid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM seals WHERE owner_id=?", (uid,)); r = c.fetchone(); conn.close()
    return _safe_int(r[0]) if r else 0

def update_seal(sid, **kw):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    s = ", ".join([f"{k}=?" for k in kw]); v = list(kw.values()) + [sid]
    c.execute(f"UPDATE seals SET {s} WHERE seal_id=?", v); conn.commit(); conn.close()

def update_player(uid, **kw):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    s = ", ".join([f"{k}=?" for k in kw]); v = list(kw.values()) + [uid]
    c.execute(f"UPDATE players SET {s} WHERE user_id=?", v); conn.commit(); conn.close()

def add_fishnets(uid, amt):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("UPDATE players SET fishnets = COALESCE(fishnets, 0) + ? WHERE user_id=?", (amt, uid))
    conn.commit(); conn.close()

def get_fishnets(uid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT fishnets FROM players WHERE user_id=?", (uid,)); r = c.fetchone(); conn.close()
    return _safe_int(r[0]) if r else 0

def add_to_inv(uid, name, t, q=1):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT inv_id, quantity FROM inventory WHERE user_id=? AND item_name=?", (uid, name)); r = c.fetchone()
    if r: c.execute("UPDATE inventory SET quantity = quantity + ? WHERE inv_id=?", (q, r[0]))
    else: c.execute("INSERT INTO inventory (user_id, item_name, item_type, quantity) VALUES (?, ?, ?, ?)", (uid, name, t, q))
    conn.commit(); conn.close()

def get_inv(uid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM inventory WHERE user_id=? AND quantity > 0", (uid,)); r = c.fetchall(); conn.close(); return r

def get_item_qty(uid, name):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT quantity FROM inventory WHERE user_id=? AND item_name=?", (uid, name)); r = c.fetchone(); conn.close()
    return _safe_int(r[0]) if r else 0

def remove_from_inv(uid, name, q=1):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT inv_id, quantity FROM inventory WHERE user_id=? AND item_name=?", (uid, name)); r = c.fetchone()
    if r:
        nq = r[1] - q
        if nq <= 0: c.execute("DELETE FROM inventory WHERE inv_id=?", (r[0],))
        else: c.execute("UPDATE inventory SET quantity=? WHERE inv_id=?", (nq, r[0]))
        conn.commit()
    conn.close()

def get_sell_price(item_name):
    if item_name in SHOP_ITEMS: return int(SHOP_ITEMS[item_name]["price"] * 0.5)
    if item_name in RESOURCE_SELL_PRICES: return RESOURCE_SELL_PRICES[item_name]
    if item_name in POTION_SELL_PRICES: return POTION_SELL_PRICES[item_name]
    m = re.search(r'\[([A-Z])\]', item_name)
    if m and m.group(1) in RARITY_SELL_PRICES:
        return RARITY_SELL_PRICES[m.group(1)]
    for recipe in CRAFT_RECIPES:
        if recipe["name"] == item_name:
            total = sum(RESOURCE_SELL_PRICES.get(r, 5) * a for r, a in recipe["resources"].items())
            return int(total * 0.6)
    return 5

def exp_for_level(lvl):
    return lvl * 100 + (lvl - 1) * 50

def get_exp_mult():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT effect FROM active_events WHERE active=1 AND event_type='exp_boost' AND expires_at > ?", (now,)); r = c.fetchone(); conn.close()
    if r:
        try: return float(r[0])
        except ValueError: return 1.0
    return 1.0

def get_shop_disc():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT effect FROM active_events WHERE active=1 AND event_type='shop_discount' AND expires_at > ?", (now,)); r = c.fetchone(); conn.close()
    if r:
        try: return float(r[0])
        except ValueError: return 0.0
    return 0.0

def get_fish_bonus():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT effect FROM active_events WHERE active=1 AND event_type='fishing_bonus' AND expires_at > ?", (now,)); r = c.fetchone(); conn.close()
    if r:
        try: return float(r[0])
        except ValueError: return 1.0
    return 1.0

def get_seal_skills(sid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT skill_name, skill_effect FROM seal_skills WHERE seal_id=?", (sid,)); r = c.fetchall(); conn.close()
    return [{"name": row[0], "effect": row[1]} for row in r]

def uid_owner(sid):
    seal = get_seal(sid); return seal[1] if seal else 0

def check_levelup(sid):
    results = []
    while True:
        seal = get_seal(sid)
        if not seal or len(seal) < 11: break
        lvl = _safe_int(seal[9]); exp = _safe_int(seal[10]); needed = exp_for_level(lvl)
        if exp >= needed:
            nl = lvl + 1; ne = exp - needed
            hp_inc = random.randint(10, 20); new_max_hp = seal[4] + hp_inc
            update_seal(sid, level=nl, exp=ne, strength=seal[7]+random.randint(2,5), defense=seal[8]+random.randint(1,3), max_health=new_max_hp, health=new_max_hp)
            results.append(nl)
            if nl % 5 == 0:
                skill = random.choice(SEAL_SKILLS_POOL)
                conn = sqlite3.connect(DB_PATH); c = conn.cursor()
                c.execute("INSERT INTO seal_skills (seal_id, skill_name, skill_effect, acquired_at) VALUES (?, ?, ?, ?)", (sid, skill["name"], skill["effect"], datetime.now().isoformat()))
                conn.commit(); conn.close()
            uid = uid_owner(sid)
            if uid: update_quest_chain(uid, "reach_level", nl)
        else: break
    return results[-1] if results else False

def get_potion_info(potion_name):
    for r in CRAFT_RECIPES:
        if r["name"] == potion_name and r.get("effect"):
            return r
    return None

def apply_potion_to_seal(sid, potion_name):
    info = get_potion_info(potion_name)
    if not info: return "Неизвестное зелье!"
    seal = get_seal(sid)
    if not seal: return "Тюлень не найден!"
    eff = info["effect"]; val = info.get("value", 0)
    if eff == "heal":
        nh = min(seal[4], seal[3] + val)
        update_seal(sid, health=nh)
        return f"💚 +{val} HP! ({seal[3]}→{nh})"
    elif eff == "antidote":
        update_seal(sid, mood=min(100, seal[5] + 10))
        return f"💊 Отравление снято!"
    else:
        dur = info.get("duration", 3)
        update_seal(sid, active_potion=f"{eff}:{val}:{dur}", potion_uses=dur)
        return f"🧪 {potion_name} активно! Эффект: {POTION_EFFECTS.get(eff, '?')} на {dur} боёв"

def get_active_potion_mods(sid):
    seal = get_seal(sid)
    if not seal: return 0, 0, 0, 0, 0, 0
    ap = seal[23] if len(seal) > 23 else None
    if not ap: return 0, 0, 0, 0, 0, 0
    try:
        eff, val, _ = ap.split(":"); val = int(val)
    except: return 0, 0, 0, 0, 0, 0
    bs = bd = dd = rg = sp = tn = 0
    if eff == "str_boost": bs = val
    elif eff == "def_boost": bd = val
    elif eff == "dodge_boost": dd = val
    elif eff == "regen_potion": rg = val
    elif eff == "speed_boost": sp = 1
    elif eff == "rage": bs = val; bs = int(bs * 0.5)
    elif eff == "titan": bs = val; bd = val
    return bs, bd, dd, rg, sp, tn

def decrement_potion_use(sid):
    seal = get_seal(sid)
    if not seal: return
    uses = _safe_int(seal[24]) if len(seal) > 24 else 0
    if uses <= 1:
        update_seal(sid, active_potion=None, potion_uses=0)
    else:
        update_seal(sid, potion_uses=uses - 1)

def get_enchantment_for_item(uid, item_name):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT enchantment FROM item_enchantments WHERE user_id=? AND item_name=?", (uid, item_name)); r = c.fetchone(); conn.close()
    return r[0] if r else None

def can_enchant(uid, ench_name):
    ench = ENCHANTMENTS.get(ench_name)
    if not ench: return False
    return all(get_item_qty(uid, r) >= a for r, a in ench["cost"].items())

def do_enchant_item(uid, item_name, ench_name):
    ench = ENCHANTMENTS.get(ench_name)
    if not ench: return "Неизвестное зачарование!"
    if get_item_qty(uid, item_name) <= 0: return "Нет предмета!"
    if not can_enchant(uid, ench_name): return "Не хватает ресурсов!"
    for res, amt in ench["cost"].items(): remove_from_inv(uid, res, amt)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT ench_id FROM item_enchantments WHERE user_id=? AND item_name=?", (uid, item_name)); ex = c.fetchone()
    if ex:
        c.execute("UPDATE item_enchantments SET enchantment=? WHERE ench_id=?", (ench_name, ex[0]))
    else:
        c.execute("INSERT INTO item_enchantments (user_id,item_name,enchantment,created_at) VALUES (?,?,?,?)", (uid, item_name, ench_name, datetime.now().isoformat()))
    conn.commit(); conn.close()
    return f"✨ {item_name} зачарован: {ench_name}!"

def get_enchanted_stats(uid, item_name):
    ench_name = get_enchantment_for_item(uid, item_name)
    if not ench_name: return 0, 0
    ench = ENCHANTMENTS.get(ench_name, {})
    return ench.get("bonus_str", 0), ench.get("bonus_def", 0)

def get_effective_stats(sid):
    seal = get_seal(sid)
    if not seal: return 0, 0, 0
    base_str = _safe_int(seal[7]); base_def = _safe_int(seal[8]); base_hp = _safe_int(seal[4])
    uid = uid_owner(sid)
    slots = [seal[13], seal[14], seal[15], seal[16], seal[17]]
    if len(seal) > 22 and seal[22]: slots.append(seal[22])
    bs = bd = bh = 0
    for item_name in slots:
        if not item_name: continue
        if item_name in ITEM_BONUSES:
            b = ITEM_BONUSES[item_name]; bs += _safe_int(b.get("str",0)); bd += _safe_int(b.get("def",0)); bh += _safe_int(b.get("hp",0))
        if uid:
            es, ed = get_enchanted_stats(uid, item_name)
            bs += es; bd += ed
    ps, pd, _, _, _, _ = get_active_potion_mods(sid)
    bs += ps; bd += pd
    return base_str + bs, base_def + bd, base_hp + bh

def get_mood_bonus(sid):
    seal = get_seal(sid)
    if not seal or len(seal) < 18: return 0
    acc = seal[17]
    return _safe_int(ACCESSORY_BONUSES.get(acc, 0)) if acc else 0

def can_craft(uid, recipe): return all(get_item_qty(uid, r) >= a for r, a in recipe["resources"].items())

def get_craft_tier_label(recipe):
    tier = recipe.get("tier", "common")
    return CRAFT_TIER_LABEL.get(tier, "Обычный")

def get_faction_disc(uid):
    p = get_player(uid)
    if not p or len(p) < 7 or not p[5]: return 0.0
    rep = _safe_int(p[6])
    if rep >= 100: return 0.30
    elif rep >= 50: return 0.15
    elif rep >= 20: return 0.05
    return 0.0

def add_faction_rep(uid, amt):
    p = get_player(uid)
    if not p or len(p) < 7: return
    update_player(uid, faction_rep=_safe_int(p[6]) + amt)

def get_floor_monster(fl, mon_idx):
    base_idx = (fl - 1 + mon_idx) % len(DUNGEON_MONSTERS)
    m = DUNGEON_MONSTERS[base_idx].copy()
    config = DUNGEON_FLOORS_CONFIG[min(fl - 1, len(DUNGEON_FLOORS_CONFIG) - 1)]
    m["hp"] = int(m["hp"] * config["hp_mult"])
    m["str"] = int(m["str"] * config["str_mult"])
    m["def"] = int(m["def"] * (1 + (fl - 1) * 0.1))
    return m

def process_drops(uid, drops):
    d = []
    if not drops: return d
    for res, ch in drops.items():
        if random.random() < ch:
            q = random.randint(1, 2); add_to_inv(uid, res, "resource", q); d.append(f"{res} x{q}")
    return d

def get_married_ids():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT seal1_id FROM marriages UNION SELECT seal2_id FROM marriages")
    ids = set(r[0] for r in c.fetchall()); conn.close(); return ids

def get_seal_status(seal, married):
    if not seal: return "❓"
    if _safe_int(seal[11]) == 1: return "🍼"
    if _safe_int(seal[3]) <= 0: return "💀"
    mood = _safe_int(seal[5]); satiety = _safe_int(seal[6])
    if mood < 30 or satiety < 20: return "😴"
    if seal[0] in married: return "❤️"
    wc = seal[18]
    if wc:
        try:
            cm = _safe_int(seal[21]) if len(seal) > 21 else 30
            if datetime.now() - datetime.fromisoformat(wc) < timedelta(minutes=cm): return "💼"
        except: pass
    if mood >= 50 and satiety >= 50: return "🎮"
    return "🦭"

def check_baby_growth(sid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT is_baby, born_at FROM seals WHERE seal_id=?", (sid,))
    r = c.fetchone()
    if r and r[0] == 1 and r[1]:
        try:
            born = datetime.fromisoformat(r[1])
            if (datetime.now() - born).days >= BABY_GROW_DAYS:
                c.execute("UPDATE seals SET is_baby=0, strength=strength+5, defense=defense+3, max_health=max_health+20, health=max_health+20 WHERE seal_id=?", (sid,))
                conn.commit()
        except: pass
    conn.close()

def get_active_event_text():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT event_type FROM active_events WHERE active=1 AND expires_at > ?", (now,)); r = c.fetchone(); conn.close()
    if not r: return None
    for ev in DAILY_EVENTS:
        if ev["event_type"] == r[0]: return ev["desc"]
    return None

def get_todays_event():
    seed = int(date.today().strftime("%Y%m%d"))
    return random.Random(seed).choice(DAILY_EVENTS)

def check_vote_result():
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT vote, COUNT(*) FROM votes WHERE date=? GROUP BY vote", (today,)); rows = c.fetchall(); conn.close()
    y = n = 0
    for v, cnt in rows:
        if v == "yes": y = cnt
        elif v == "no": n = cnt
    return (y + n) >= 3 and y > n

def activate_event(et, eff):
    exp = datetime.now() + timedelta(hours=24)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("UPDATE active_events SET active=0 WHERE active=1")
    c.execute("INSERT INTO active_events (event_type, effect, expires_at, active) VALUES (?, ?, ?, 1)", (et, eff, exp.isoformat()))
    conn.commit(); conn.close()

def get_quest_chains():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM quest_chains"); r = c.fetchall(); conn.close(); return r

def get_player_chain(uid, chain_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM player_quest_chains WHERE user_id=? AND chain_id=?", (uid, chain_id)); r = c.fetchone(); conn.close(); return r

def update_quest_chain(uid, step_type, amount=1):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT id, chain_id, current_step, step_progress, completed FROM player_quest_chains WHERE user_id=? AND completed=0", (uid,))
    for pc_id, cid, cs, sp, comp in c.fetchall():
        c2 = conn.cursor()
        c2.execute("SELECT steps_json FROM quest_chains WHERE chain_id=?", (cid,)); chain = c2.fetchone()
        if not chain: continue
        try: steps = json.loads(chain[0])
        except json.JSONDecodeError: continue
        if cs < len(steps) and steps[cs]["type"] == step_type:
            if step_type in ("reach_level", "dungeon_floor"):
                ns = max(sp, amount)
            else:
                ns = sp + 1
            if ns >= steps[cs]["target"]:
                ns = 0; cs2 = cs + 1
                if cs2 >= len(steps): c2.execute("UPDATE player_quest_chains SET completed=1 WHERE id=?", (pc_id,))
                else: c2.execute("UPDATE player_quest_chains SET current_step=?, step_progress=0 WHERE id=?", (cs2, pc_id))
            else: c2.execute("UPDATE player_quest_chains SET step_progress=? WHERE id=?", (ns, pc_id))
    conn.commit(); conn.close()

def get_clan_by_user(uid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT clans.* FROM clans JOIN clan_members ON clans.clan_id=clan_members.clan_id WHERE clan_members.user_id=?", (uid,)); r = c.fetchone(); conn.close(); return r

def get_clan_members(cid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT user_id FROM clan_members WHERE clan_id=?", (cid,)); r = c.fetchall(); conn.close(); return [row[0] for row in r]

def trigger_encounter(uid):
    enc = random.choice(RANDOM_ENCOUNTERS)
    if random.random() > enc["chance"]: return None
    msg = f"✨ Случайное событие!\n{enc['name']}\n"
    if enc["type"] == "item":
        item = random.choice(enc["items"]); add_to_inv(uid, item, "resource", 1); msg += f"Получен предмет: {item}!"
    elif enc["type"] == "fishnets":
        r = random.randint(*enc["fishnet_reward"]); add_fishnets(uid, r); msg += f"Найдено 🐟{r}!"
    elif enc["type"] == "battle":
        seals = get_player_seals(uid)
        if seals:
            s = seals[0]
            new_mood = max(0, _safe_int(s[5]) - enc.get("mood_cost", 0))
            new_satiety = max(0, _safe_int(s[6]) - enc.get("satiety_cost", 0))
            update_seal(s[0], mood=new_mood, satiety=new_satiety)
            msg += "Тюлень потерял настроение и сытость!"
            if "drop" in enc:
                d = process_drops(uid, enc["drop"])
                if d: msg += f"\nНо добыча: {', '.join(d)}"
    elif enc["type"] == "hint":
        r = random.randint(*enc["fishnet_reward"]); add_fishnets(uid, r); msg += f"Дельфин подсказал секрет! 🐟{r}"
    return msg

def create_duel(cid, oid, csid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT INTO duels (challenger_id, opponent_id, challenger_seal_id, status, created_at) VALUES (?, ?, ?, 'pending', ?)", (cid, oid, csid, datetime.now().isoformat()))
    conn.commit(); did = c.lastrowid; conn.close(); return did

def get_duel(did):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM duels WHERE duel_id=?", (did,)); r = c.fetchone(); conn.close(); return r

def generate_daily_quests(uid):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM daily_quests WHERE user_id=? AND date=?", (uid, today))
    if c.fetchall(): conn.close(); return
    c.execute("DELETE FROM daily_quests WHERE user_id=? AND date!=?", (uid, today))
    for q in random.sample(QUEST_TEMPLATES, 3):
        c.execute("INSERT INTO daily_quests (user_id,quest_type,quest_target,quest_progress,quest_reward,date,claimed) VALUES (?,?,?,0,?,?,0)",
                  (uid, q["type"], q["target"], q["reward"], today))
    conn.commit(); conn.close()

def update_quest_progress(uid, qt, amt=1):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT quest_id,quest_progress,quest_target FROM daily_quests WHERE user_id=? AND quest_type=? AND date=? AND claimed=0", (uid, qt, today))
    for qid, prog, targ in c.fetchall():
        if prog < targ: c.execute("UPDATE daily_quests SET quest_progress=? WHERE quest_id=?", (min(targ, prog + amt), qid))
    conn.commit(); conn.close()

def get_daily_quests(uid):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM daily_quests WHERE user_id=? AND date=?", (uid, today)); r = c.fetchall(); conn.close(); return r

def get_chest_contents(rarity):
    if rarity in CHEST_CONTENTS:
        return random.randint(CHEST_CONTENTS[rarity]["fishnets"][0], CHEST_CONTENTS[rarity]["fishnets"][1])
    return 0

def get_artifact(rarity):
    if rarity in ARTIFACTS:
        return random.choice(ARTIFACTS[rarity])
    return None

def open_chest(uid, rarity):
    chest_name = f"Сундук [{rarity}] 📦"
    if get_item_qty(uid, chest_name) <= 0: return "Нет сундука!"
    remove_from_inv(uid, chest_name)
    fn_range = CHEST_CONTENTS.get(rarity, {"fishnets": (10, 30)})
    fishnets = random.randint(fn_range["fishnets"][0], fn_range["fishnets"][1])
    add_fishnets(uid, fishnets)
    msg = f"📦 Сундук [{rarity}] открыт!\n🐟 {fishnets}\n"
    roll = random.random()
    if roll < 0.25:
        art = random.choice(ARTIFACTS.get(rarity, []))
        fn = f"{art['name']} [{rarity}]"
        add_to_inv(uid, fn, "artifact", 1)
        msg += f"✨ Артефакт: {fn}\n"
    elif roll < 0.55:
        w = random.choice(CHEST_WEAPONS.get(rarity, []))
        fn = f"{w['name']} [{rarity}]"
        add_to_inv(uid, fn, "weapon", 1)
        msg += f"⚔️ Оружие: {fn}\n"
    elif roll < 0.80:
        a = random.choice(CHEST_ARMOR.get(rarity, []))
        fn = f"{a['name']} [{rarity}]"
        add_to_inv(uid, fn, "armor", 1)
        msg += f"🛡️ Броня: {fn}\n"
    return msg

# ==================== ПРИВЯЗКА К ТОПИКУ ====================
def get_topic_binding(chat_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT message_thread_id FROM topic_bindings WHERE chat_id=?", (chat_id,)); r = c.fetchone(); conn.close()
    return r[0] if r else None

def set_topic_binding(chat_id, thread_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO topic_bindings (chat_id, message_thread_id) VALUES (?, ?)", (chat_id, thread_id))
    conn.commit(); conn.close()

def remove_topic_binding(chat_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("DELETE FROM topic_bindings WHERE chat_id=?", (chat_id,))
    conn.commit(); conn.close()

# --- Monkey-patch: авто-отправка в привязанный топик ---
_orig_send_message = bot.send_message
_orig_send_photo = bot.send_photo

def _patched_send_message(chat_id, text, *args, **kwargs):
    tid = get_topic_binding(chat_id)
    if tid is not None and 'message_thread_id' not in kwargs:
        kwargs['message_thread_id'] = tid
    return _orig_send_message(chat_id, text, *args, **kwargs)

def _patched_send_photo(chat_id, photo, *args, **kwargs):
    tid = get_topic_binding(chat_id)
    if tid is not None and 'message_thread_id' not in kwargs:
        kwargs['message_thread_id'] = tid
    return _orig_send_photo(chat_id, photo, *args, **kwargs)

bot.send_message = _patched_send_message
bot.send_photo = _patched_send_photo

# ==================== ОБРАБОТЧИКИ ====================

# --- Фильтр: в группе с привязкой игнорируем сообщения не из привязанного топика ---
@bot.message_handler(func=lambda m: _is_not_from_bound_topic(m))
def _ignore_unbound_topic(message):
    pass

def _is_not_from_bound_topic(message):
    tid = get_topic_binding(message.chat.id)
    if tid is None:
        return False
    msg_tid = getattr(message, 'message_thread_id', None)
    return msg_tid != tid

@bot.message_handler(commands=['start'])
def cmd_start(message):
    uid = message.from_user.id; uname = message.from_user.username or message.from_user.first_name
    chat_id = message.chat.id
    p = get_player(uid)
    if not p:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("INSERT INTO players (user_id,username,display_name,fishnets) VALUES (?,?,?,100)", (uid, uname, uname))
        conn.commit(); conn.close()
        sn = random.choice(["Никифор","Плюха","Шлёпа","Бубль","Тюня","Фрэнк","Сэм"])
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("INSERT INTO seals (owner_id,name,health,max_health,mood,satiety,strength,defense,level,exp) VALUES (?,?,100,100,80,80,10,5,1,0)", (uid, sn))
        conn.commit(); conn.close()
        bot.send_message(chat_id, f"Добро пожаловать в Мир Тюленей! 🦭\n\nТюлень {sn} и 100 рыбнеток 🐟 ваши!")
    else:
        bot.send_message(chat_id, "С возвращением! 🦭")
    show_main_menu(chat_id)

@bot.message_handler(commands=['help'])
def cmd_help(message):
    chat_id = message.chat.id
    t = ("🦭 *Справка*\n\n*Основные:*\n/start /help /profile /gallery /setphoto /leaderboard\n"
         "/inventory — инвентарь и ресурсы\n/sell — продажа предметов\n\n"
         "*Тюлень:*\n🦭 Мой тюлень — карточка\n\n"
         "*Экономика:*\n/shop /craft /trade — биржа\n\n"
         "*Сражения:*\n/battle /dungeon /work /duel\n\n"
         "*Алхимия и магия:*\n/potion — варить зелья\n/enchant — зачарование\n\n"
         "*Активности:*\n/fish /vote /faction /marry /quests\n"
         "/questchain /clan\n\n"
         "*Топики:*\n/bindtopic — привязать бота к топику\n/unbindtopic — отвязать\n\n"
         "*Подземелье:* 10 этажей, сундуки и артефакты!\n"
         "*Тиры крафта:* 5 уровней (Обычный→Легендарный)\n"
         "*Зелья:* 9 видов (лечение, сила, защита, ярость и др.)\n"
         "*Зачарование:* 6 видов (огненное, ледяное, теневое и др.)\n"
         "*Регенерация:* +25 HP/час | Навык каждые 5 уровней\n"
         "*Тюленята:* растут через 3 дня")
    bot.send_message(chat_id, t, parse_mode='Markdown'); show_main_menu(chat_id)

def show_main_menu(chat_id):
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.add(types.KeyboardButton("🦭 Мой тюлень"), types.KeyboardButton("👤 Профиль"))
    m.add(types.KeyboardButton("🎒 Инвентарь"), types.KeyboardButton("🛒 Магазин"))
    m.add(types.KeyboardButton("⚔️ Бой"), types.KeyboardButton("🏰 Подземелье"))
    m.add(types.KeyboardButton("💼 Работа"), types.KeyboardButton("🔨 Крафт"))
    m.add(types.KeyboardButton("🧪 Зелья"), types.KeyboardButton("✨ Зачарование"))
    m.add(types.KeyboardButton("📋 Задания"), types.KeyboardButton("💍 Брак"))
    m.add(types.KeyboardButton("🎣 Рыбалка"), types.KeyboardButton("🏆 Лидеры"))
    m.add(types.KeyboardButton("📦 Биржа"), types.KeyboardButton("🏛 Фракции"))
    m.add(types.KeyboardButton("🤺 Дуэль"), types.KeyboardButton("📚 Цепочки"))
    m.add(types.KeyboardButton("🐋 Клан"), types.KeyboardButton("💰 Продажа"))
    bot.send_message(chat_id, "Выберите действие:", reply_markup=m)
