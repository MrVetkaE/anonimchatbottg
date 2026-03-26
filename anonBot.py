"""
АНОНИМНЫЙ БОТ — с защитой от спама
Люди пишут → ты читаешь и отвечаешь
"""

import telebot
import time
import os
import logging
import threading
import hashlib
from collections import defaultdict
from http.server import HTTPServer, BaseHTTPRequestHandler

# ══════════════════════════════════════════
#              НАСТРОЙКИ
# ══════════════════════════════════════════

BOT_TOKEN = os.environ.get("8592990429:AAFlsdyHOWExtHzAxO3VN2i8J7OeEr0ufOo")
ADMIN_ID = int(os.environ.get("5616217597"))

# Антиспам настройки
SPAM_LIMIT = 3              # Максимум сообщений...
SPAM_WINDOW = 10            # ...за N секунд → блок
BLOCK_TIME = 60             # Блокировка на 60 секунд (1 минута)
FLOOD_CHAR_LIMIT = 30       # Если >30 одинаковых символов подряд → спам
MAX_MSG_LENGTH = 1000       # Максимальная длина сообщения
DUPLICATE_WINDOW = 30       # Секунды для проверки дублей

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

start_time = time.time()

# Хранилища
message_map = {}                    # {bot_msg_id: user_id}
blocked_users = {}                  # {user_id: unblock_timestamp}
user_messages = defaultdict(list)   # {user_id: [timestamps]}
last_message_hash = {}              # {user_id: (hash, timestamp)} — для дублей


# ══════════════════════════════════════════
#         ВЕБ-СЕРВЕР (чтобы не засыпал)
# ══════════════════════════════════════════

class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            uptime = int(time.time() - start_time)
            self.wfile.write(f'{{"status":"ok","uptime":{uptime}}}'.encode())
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
        pass

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    logger.info(f"Веб-сервер запущен на порту {port}")
    server.serve_forever()


# ══════════════════════════════════════════
#              БОТ
# ══════════════════════════════════════════

bot = telebot.TeleBot(BOT_TOKEN)


# ══════════════════════════════════════════
#              ФУНКЦИИ АНТИСПАМА
# ══════════════════════════════════════════

def is_blocked(user_id: int) -> bool:
    """Проверяет, заблокирован ли пользователь."""
    if user_id in blocked_users:
        if time.time() < blocked_users[user_id]:
            return True
        else:
            del blocked_users[user_id]
    return False


def get_block_remaining(user_id: int) -> str:
    """Возвращает строку с оставшимся временем бана."""
    remaining = int(blocked_users[user_id] - time.time())
    return f"{remaining // 60}м {remaining % 60}с"


def check_spam(user_id: int) -> bool:
    """Проверка частоты сообщений (флуд)"""
    now = time.time()
    # Очищаем старые метки времени
    user_messages[user_id] = [t for t in user_messages[user_id] if now - t < SPAM_WINDOW]
    user_messages[user_id].append(now)
    
    if len(user_messages[user_id]) > SPAM_LIMIT:
        blocked_users[user_id] = now + BLOCK_TIME
        return True
    return False


def check_flood_chars(text: str) -> bool:
    """Проверка флуда одинаковыми символами (ааааа, !!!!!, #####)"""
    if not text or len(text) < 10:
        return False
    
    count = 1
    max_count = 1
    for i in range(1, len(text)):
        if text[i] == text[i - 1]:
            count += 1
            max_count = max(max_count, count)
        else:
            count = 1
    
    # Если более 30 одинаковых символов подряд
    if max_count >= FLOOD_CHAR_LIMIT:
        return True
    
    # Если более 70% текста — повторяющиеся символы
    total = len(text)
    if max_count > total * 0.7 and total > 20:
        return True
    
    return False


def check_duplicate(user_id: int, text: str) -> bool:
    """Проверка на отправку одного и того же сообщения"""
    now = time.time()
    msg_hash = hashlib.md5(text.lower().strip().encode()).hexdigest()
    
    if user_id in last_message_hash:
        prev_hash, prev_time = last_message_hash[user_id]
        if prev_hash == msg_hash and now - prev_time < DUPLICATE_WINDOW:
            return True
    
    last_message_hash[user_id] = (msg_hash, now)
    return False


def check_message_length(text: str) -> tuple:
    """Проверка длины сообщения"""
    if len(text) > MAX_MSG_LENGTH:
        return False, f"❌ Слишком длинное! Максимум {MAX_MSG_LENGTH} символов.\nТвоё: {len(text)} символов."
    if len(text) < 2:
        return False, "❌ Сообщение слишком короткое."
    return True, ""


# ══════════════════════════════════════════
#              КОМАНДЫ
# ══════════════════════════════════════════

@bot.message_handler(commands=["start"])
def cmd_start(message):
    if message.from_user.id == ADMIN_ID:
        bot.send_message(
            ADMIN_ID,
            "👋 *Бот запущен!*\n\n"
            "📌 *Команды:*\n"
            "/stats — статистика\n"
            "/ban ID [минуты] — заблокировать\n"
            "/unblock ID — разблокировать\n"
            "/blocked — список заблокированных\n\n"
            "📌 Чтобы ответить пользователю — нажми Reply на его сообщение",
            parse_mode="Markdown"
        )
    else:
        bot.send_message(
            message.chat.id,
            "👻 *Анонимный бот*\n\n"
            "Напиши любое сообщение — оно придёт анонимно.\n"
            "Никто не узнает, кто ты 🕶\n\n"
            "⚠️ *Антиспам:* не больше 3 сообщений за 10 секунд",
            parse_mode="Markdown"
        )


@bot.message_handler(commands=["stats"])
def cmd_stats(message):
    if message.from_user.id != ADMIN_ID:
        return
    uptime = int(time.time() - start_time)
    h, m = uptime // 3600, (uptime % 3600) // 60
    blocked_count = len([u for u, ts in blocked_users.items() if ts > time.time()])
    bot.send_message(
        ADMIN_ID,
        f"📊 *Статистика*\n\n"
        f"⏱ Аптайм: *{h}ч {m}м*\n"
        f"🚫 Заблокировано: *{blocked_count}*\n"
        f"📩 Получено сообщений: *{len(message_map)}*\n"
        f"✅ Статус: работает",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["ban"])
def cmd_ban(message):
    """Блокировка пользователя с указанием времени"""
    if message.from_user.id != ADMIN_ID:
        return
    
    parts = message.text.split()
    
    if len(parts) < 2:
        bot.send_message(
            ADMIN_ID,
            "❌ *Использование:*\n"
            "/ban ID [минуты]\n\n"
            "Примеры:\n"
            "/ban 123456789 — бан на 5 минут\n"
            "/ban 123456789 60 — бан на 60 минут",
            parse_mode="Markdown"
        )
        return
    
    try:
        user_id = int(parts[1])
        minutes = int(parts[2]) if len(parts) > 2 else 5
        
        if minutes <= 0:
            bot.send_message(ADMIN_ID, "❌ Время должно быть больше 0!")
            return
        
        blocked_users[user_id] = time.time() + minutes * 60
        
        # Уведомляем пользователя
        try:
            bot.send_message(
                user_id,
                f"🚫 *Вы заблокированы!*\n\n"
                f"Причина: нарушение правил\n"
                f"⏱ До разблокировки: *{minutes} минут*\n\n"
                f"Напишите позже 👋",
                parse_mode="Markdown"
            )
        except:
            pass
        
        bot.send_message(
            ADMIN_ID,
            f"🚫 *Пользователь заблокирован*\n\n"
            f"🆔 ID: `{user_id}`\n"
            f"⏱ Время: *{minutes} минут*",
            parse_mode="Markdown"
        )
        
    except ValueError:
        bot.send_message(ADMIN_ID, "❌ Неверный формат ID. Введите только цифры.")


@bot.message_handler(commands=["unblock"])
def cmd_unblock(message):
    """Разблокировка пользователя"""
    if message.from_user.id != ADMIN_ID:
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(ADMIN_ID, "❌ Использование: /unblock ID")
        return
    
    try:
        user_id = int(parts[1])
        
        if user_id in blocked_users:
            del blocked_users[user_id]
            bot.send_message(
                ADMIN_ID,
                f"✅ Пользователь `{user_id}` разблокирован.",
                parse_mode="Markdown"
            )
            try:
                bot.send_message(user_id, "✅ *Вы разблокированы!* Можете снова писать.", parse_mode="Markdown")
            except:
                pass
        else:
            bot.send_message(ADMIN_ID, "❓ Пользователь не в блоке.")
            
    except ValueError:
        bot.send_message(ADMIN_ID, "❌ Неверный ID.")


@bot.message_handler(commands=["blocked"])
def cmd_blocked(message):
    """Список заблокированных"""
    if message.from_user.id != ADMIN_ID:
        return
    
    now = time.time()
    active = {uid: ts for uid, ts in blocked_users.items() if ts > now}
    
    if not active:
        bot.send_message(ADMIN_ID, "✅ Нет заблокированных пользователей.")
        return
    
    text = "🚫 *Заблокированные пользователи:*\n\n"
    for uid, until in active.items():
        rem = int(until - now)
        text += f"• `{uid}` — ещё {rem // 60}м {rem % 60}с\n"
    
    bot.send_message(ADMIN_ID, text, parse_mode="Markdown")


# ══════════════════════════════════════════
#              ОТВЕТЫ АДМИНА
# ══════════════════════════════════════════

@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.reply_to_message is not None)
def admin_reply(message):
    original_msg_id = message.reply_to_message.message_id
    
    if original_msg_id not in message_map:
        bot.send_message(ADMIN_ID, "❓ Получатель не найден. Сообщение слишком старое.")
        return
    
    target_user_id = message_map[original_msg_id]
    
    # Проверка, не заблокирован ли пользователь
    if is_blocked(target_user_id):
        bot.send_message(
            ADMIN_ID,
            f"❌ Нельзя ответить! Пользователь `{target_user_id}` заблокирован.\n"
            f"Осталось: {get_block_remaining(target_user_id)}",
            parse_mode="Markdown"
        )
        return
    
    try:
        bot.send_message(target_user_id, f"📨 *Ответ:*\n\n{message.text}", parse_mode="Markdown")
        bot.send_message(ADMIN_ID, "✅ Ответ отправлен!")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Ошибка отправки: {e}")


# ══════════════════════════════════════════
#              ПРИЕМ СООБЩЕНИЙ
# ══════════════════════════════════════════

@bot.message_handler(func=lambda m: m.from_user.id != ADMIN_ID, content_types=["text"])
def receive_message(message):
    user_id = message.from_user.id
    text = message.text.strip()
    first_name = message.from_user.first_name

    # Пустое сообщение
    if not text:
        bot.send_message(message.chat.id, "❌ Пустое сообщение.")
        return
    
    # Проверка длины
    length_ok, length_msg = check_message_length(text)
    if not length_ok:
        bot.send_message(message.chat.id, length_msg)
        return
    
    # Проверка флуда одинаковыми символами
    if check_flood_chars(text):
        bot.send_message(
            message.chat.id,
            "🚫 *Сообщение отклонено!*\n\n"
            "Похоже на флуд (много одинаковых символов).\n"
            "Напишите нормальное сообщение.",
            parse_mode="Markdown"
        )
        logger.warning(f"Флуд символами от {user_id}")
        return
    
    # Проверка бана
    if is_blocked(user_id):
        remaining = get_block_remaining(user_id)
        bot.send_message(
            message.chat.id,
            f"🚫 *Вы заблокированы!*\n\n"
            f"⏱ Разблокировка через: *{remaining}*\n\n"
            f"Если считаете это ошибкой — напишите позже.",
            parse_mode="Markdown"
        )
        return
    
    # Проверка на дубликаты
    if check_duplicate(user_id, text):
        bot.send_message(
            message.chat.id,
            "🔁 *Повторное сообщение!*\n\n"
            "Вы уже отправляли это сообщение.\n"
            "Подождите немного.",
            parse_mode="Markdown"
        )
        return
    
    # Проверка на флуд (частота)
    if check_spam(user_id):
        bot.send_message(
            message.chat.id,
            f"🚫 *Слишком много сообщений!*\n\n"
            f"Вы отправляете сообщения слишком часто.\n"
            f"⏱ Блокировка на *{BLOCK_TIME // 60} минут*.",
            parse_mode="Markdown"
        )
        bot.send_message(
            ADMIN_ID,
            f"⚠️ *Антиспам сработал!*\n\n"
            f"👤 Пользователь: {first_name}\n"
            f"🆔 ID: `{user_id}`\n"
            f"🚫 Заблокирован на {BLOCK_TIME // 60} минут",
            parse_mode="Markdown"
        )
        return

    try:
        # Отправляем админу
        sent = bot.send_message(
            ADMIN_ID,
            f"📩 *Новое сообщение*\n\n"
            f"👤 *От:* {first_name}\n"
            f"🆔 *ID:* `{user_id}`\n"
            f"─────────────────\n"
            f"{text}",
            parse_mode="Markdown"
        )
        
        # Сохраняем связь сообщение → пользователь для ответа
        message_map[sent.message_id] = user_id
        
        # Чистим старые записи (оставляем последние 200)
        if len(message_map) > 200:
            oldest_keys = list(message_map.keys())[:-200]
            for key in oldest_keys:
                del message_map[key]
        
        # Подтверждение пользователю
        bot.send_message(message.chat.id, "✅ Сообщение отправлено!")
        logger.info(f"Сообщение от {user_id} ({first_name})")
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка. Попробуй позже.")


@bot.message_handler(
    func=lambda m: m.from_user.id != ADMIN_ID,
    content_types=["photo", "video", "audio", "document", "voice", "sticker", "animation"]
)
def handle_media(message):
    bot.send_message(message.chat.id, "📝 *Только текст!*\n\nНапиши сообщение словами.", parse_mode="Markdown")


# ══════════════════════════════════════════
#              ЗАПУСК
# ══════════════════════════════════════════

if __name__ == "__main__":
    # Запускаем веб-сервер в отдельном потоке
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    print("╔══════════════════════════════════════════════╗")
    print("║      🤖 Анонимный бот с защитой от спама     ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"👤 Admin ID: {ADMIN_ID}")
    print("🟢 Бот работает...")
    print("")
    print("📋 Настройки антиспама:")
    print(f"   • Максимум {SPAM_LIMIT} сообщений за {SPAM_WINDOW} сек → бан на {BLOCK_TIME // 60} мин")
    print(f"   • Блокировка дублей: {DUPLICATE_WINDOW} сек")
    print(f"   • Максимальная длина: {MAX_MSG_LENGTH} символов")

    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=10)
        except Exception as e:
            logger.error(f"Ошибка polling: {e}")
            time.sleep(5)