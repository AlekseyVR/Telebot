import os
import io
import signal
import datetime
import telebot
import threading
import time
from dotenv import load_dotenv
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from models.config import CONFIG, reload_config
from utils.system_monitor import (
    generate_system_report,
    get_raw_process_status,
    get_resource_usage,
    get_tcp_status,
    tail_file,
)
from utils.logger import logger


# 1. Loading environment and config variables
load_dotenv()
BOT_TOKEN: str | None = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    bot_not_found = "❌ Ошибка: BOT_TOKEN не найден в файле .env"
    logger.error(bot_not_found)
    exit(bot_not_found)


# 2. Bot initialization
bot = telebot.TeleBot(BOT_TOKEN)

BOT_START_TIME: float = time.time()
_bg_heartbeat: float = 0.0  # время последнего цикла фонового монитора


# Eligibility Verification Assist Function
def is_admin(user_id: int) -> bool:
    return user_id in CONFIG.admins


# Full access check (admin rights + optional group-only mode)
def access_denied_ids(user_id: int, chat_id: int) -> str | None:
    """Returns a denial message if access is denied, otherwise None."""
    if not is_admin(user_id):
        return "⛔ У вас нет доступа к этому боту."
    if (CONFIG.enable_group_only_mode
            and CONFIG.target_chat_id != 0
            and chat_id != CONFIG.target_chat_id):
        return "⛔ Бот принимает команды только в настроенной группе."
    return None


def access_denied(message: Message) -> str | None:
    return access_denied_ids(message.from_user.id, message.chat.id)


# 3. Basic command handler
def _menu_keyboard() -> InlineKeyboardMarkup:
    """Инлайн-меню быстрых действий."""
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📊 Статус", callback_data="status"),
        InlineKeyboardButton("📁 Логи", callback_data="logs"),
        InlineKeyboardButton("🔄 Перезагрузка", callback_data="reboot"),
        InlineKeyboardButton("🔁 Reload", callback_data="reload"),
    )
    return keyboard


@bot.message_handler(commands=['start'])
def send_welcome(message: Message) -> None:
    denied: str | None = access_denied(message)
    if denied:
        if not is_admin(message.from_user.id):
            # Output the ID to the console so that you can copy it to CONFIG (config.json)
            logger.warning(f"Попытка доступа (start) от неавторизованного пользователя! ID: {message.from_user.id}")
        bot.reply_to(message, denied)
        return

    bot.reply_to(message,
                 "👋 Привет! Я твой бот-монитор. Авторизация успешна.\n\n"
                 "Используй кнопки ниже или команды из /help.",
                 reply_markup=_menu_keyboard())

@bot.message_handler(commands=['help'])
def send_help(message: Message) -> None:
    denied: str | None = access_denied(message)
    if denied:
        bot.reply_to(message, denied)
        return
    help_text: str = (
        "🛠 <b>Руководство по Server Monitor Bot</b>\n\n"
        "📊 <b>/status</b> — Сформировать и прислать текущий срез состояния сервера:\n"
        "  • Загрузка процессора (CPU) и памяти (RAM).\n"
        "  • Свободное место на дисках.\n"
        "  • Статус API (Telegram, Gemini), Пинг и TCP-порты.\n"
        "  • Состояние запущенных процессов (Watchdog) с CPU/RAM.\n\n"
        "📁 <b>/getlogs [N]</b> — Запросить файлы логов из <code>config.json</code>. Без аргумента — весь файл, <code>/getlogs 200</code> — последние 200 строк.\n\n"
        "🏓 <b>/ping</b> — Проверить, что бот жив: uptime и статус фонового монитора.\n\n"
        "🔄 <b>/reboot</b> — Удаленная перезагрузка сервера. <i>Требует подтверждения: после команды отправьте <code>/reboot confirm</code> в течение 30 секунд.</i>\n\n"
        "🔁 <b>/reload</b> — Перечитать <code>config.json</code> без перезапуска бота.\n\n"
        "⚙️ <i>Примечание: Автоматические проверки (алерты об упавших скриптах, портах, превышении порогов CPU/RAM/дисков и тихие ежечасные отчеты) работают в фоне и не требуют ввода команд.</i>"
    )
    bot.reply_to(message, help_text, parse_mode='HTML', reply_markup=_menu_keyboard())


def _run_status(chat_id: int) -> None:
    """Собирает и отправляет срез состояния сервера."""
    msg: Message = bot.send_message(chat_id, "⏳ Собираю данные о системе...")
    try:
        report: str = generate_system_report()
        bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id,
                              text=report, parse_mode='HTML')
    except Exception as e:
        bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id,
                              text=f"❌ Ошибка при сборе данных: {e}")


@bot.message_handler(commands=['status'])
def send_status(message: Message) -> None:
    # Verification of rights (admin + group-only mode)
    denied: str | None = access_denied(message)
    if denied:
        bot.reply_to(message, denied)
        return
    _run_status(message.chat.id)


@bot.message_handler(commands=['ping'])
def ping_command(message: Message) -> None:
    denied: str | None = access_denied(message)
    if denied:
        bot.reply_to(message, denied)
        return

    bot_uptime = str(datetime.timedelta(seconds=int(time.time() - BOT_START_TIME)))

    if _bg_heartbeat:
        last_beat_age = time.time() - _bg_heartbeat
        if last_beat_age > CONFIG.intervals.watchdog_check_sec * 3:
            bg_status = f"⚠️ фоновый монитор не отвечает ({int(last_beat_age)} сек)"
        else:
            bg_status = f"🟢 фоновый монитор активен (последний цикл {int(last_beat_age)} сек назад)"
    else:
        bg_status = "⏳ фоновый монитор ещё не запускался"

    bot.reply_to(message, f"🏓 <b>Pong!</b>\n⏱ Uptime бота: {bot_uptime}\n{bg_status}", parse_mode='HTML')


def _run_getlogs(chat_id: int, tail_lines: int = 0) -> None:
    """Отправляет файлы логов (или их хвост) в чат."""
    msg: Message = bot.send_message(chat_id, "📁 Ищу файлы логов, указанные в конфиге...")

    log_files: dict[str, str] = CONFIG.log_files

    # If the dictionary is empty
    if not log_files:
        bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id,
                              text="🤷‍♂️ В файле config.json не указаны пути к логам (блок log_files).")
        return

    # Go through the dictionary and send files
    files_sent: int = 0
    for name, path in log_files.items():
        if os.path.exists(path):
            try:
                if tail_lines > 0:
                    content = tail_file(path, tail_lines)
                    buf = io.BytesIO(content)
                    buf.name = f"{name}_tail.log"
                    bot.send_document(chat_id, buf, caption=f"📄 {name} (последние {tail_lines} строк)")
                else:
                    # Open the file in binary mode 'rb' to send
                    with open(path, 'rb') as document:
                        bot.send_document(chat_id, document, caption=f"📄 {name}")
                files_sent += 1
            except Exception as e:
                bot.send_message(chat_id, f"❌ Не удалось прочитать {name}: {e}")
        else:
            bot.send_message(chat_id, f"⚠️ Файл не найден: {name}\nПроверьте путь: <code>{path}</code>",
                             parse_mode='HTML')

    # Closing Message
    if files_sent > 0:
        bot.send_message(chat_id, f"✅ Отправка логов завершена. Передано файлов: {files_sent}.")
    else:
        bot.send_message(chat_id, "❌ Ни один файл логов не был отправлен (не найдены или ошибка доступа).")


@bot.message_handler(commands=['getlogs'])
def send_logs(message: Message) -> None:
    # Strict rights check (logs are confidential information)
    denied: str | None = access_denied(message)
    if denied:
        bot.reply_to(message, denied)
        return

    # Optional argument: /getlogs N -> последние N строк
    tail_lines: int = 0
    parts: list[str] = (message.text or "").strip().split()
    if len(parts) >= 2:
        try:
            tail_lines = int(parts[1])
        except ValueError:
            bot.reply_to(message, "❌ Неверный аргумент. Пример: /getlogs или /getlogs 200.")
            return
        if tail_lines < 0:
            bot.reply_to(message, "❌ Число строк должно быть положительным.")
            return

    _run_getlogs(message.chat.id, tail_lines)


# Cooldown-память алертов: ключ -> время последнего алерта
_alert_last_sent: dict[str, float] = {}


def _send_alert(key: str, chat_id: int, text: str) -> None:
    """Отправляет алерт с cooldown (подавляет повтор по тому же ключу)."""
    now = time.time()
    cooldown = CONFIG.alert_cooldown_sec
    if cooldown > 0 and now - _alert_last_sent.get(key, 0.0) < cooldown:
        return
    _alert_last_sent[key] = now
    try:
        bot.send_message(chat_id, text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка алерта: {e}")


def background_loop() -> None:
    global _bg_heartbeat
    logger.info("🔄 Фоновый мониторинг запущен...")

    script_start_time: float = time.time()  # НОВОЕ: Запоминаем время запуска
    # Determine where to send reports (group or personal account of the first admin)
    target_chat_id: int = CONFIG.target_chat_id
    if target_chat_id == 0 and CONFIG.admins:
        target_chat_id = CONFIG.admins[0]

    last_report_time: float = time.time()
    dead_processes_memory: set[str] = set()  # Memory so that the bot does not spam process alerts
    dead_tcp_memory: set[str] = set()  # Memory so that the bot does not spam TCP alerts
    resource_alerts_memory: dict[str, bool] = {}  # Memory so that the bot does not spam resource alerts

    while True:
        _bg_heartbeat = time.time()
        current_time: float = time.time()

        if CONFIG.intervals.planned_restart_sec > 0:  # --- 0. Planning restart
            if int(current_time - script_start_time) >= CONFIG.intervals.planned_restart_sec:
                logger.info(f"⏳ Прошло {int(CONFIG.intervals.planned_restart_sec / 60 / 60)} часов. Инициирую плановый рестарт...")
                # noinspection PyUnresolvedReferences
                os._exit(0)  # Hard reset script (Bat-file start it again)

        # --- 1. WATCHDOG (Emergency Checks) ---
        if CONFIG.processes_to_watch:
            status_dict: dict[str, dict] = get_raw_process_status(CONFIG.processes_to_watch)
            for proc_name, info in status_dict.items():
                alias: str = info.get("alias") or proc_name

                is_alive = info["is_alive"]
                # If the process has crashed and we haven't written about it yet
                if not is_alive and proc_name not in dead_processes_memory:
                    dead_processes_memory.add(proc_name)
                    _send_alert(f"proc:{proc_name}", target_chat_id,
                                f"⚠️ <b>ВНИМАНИЕ!</b>\nПроцесс <code>{alias}</code> упал или не найден!")

                # If the process is running again and was on the list of dead (you restarted it)
                elif is_alive and proc_name in dead_processes_memory:
                    dead_processes_memory.remove(proc_name)
                    _send_alert(f"proc:{proc_name}", target_chat_id,
                                f"✅ <b>ОТБОЙ ТРЕВОГИ!</b>\nПроцесс <code>{alias}</code> снова в строю!")

        # --- 1.2 TCP PORT CHECKS ---
        if CONFIG.tcp_hosts:
            tcp_status: dict[str, bool] = get_tcp_status()
            for name, alive in tcp_status.items():
                if not alive and name not in dead_tcp_memory:
                    dead_tcp_memory.add(name)
                    _send_alert(f"tcp:{name}", target_chat_id,
                                f"⚠️ <b>ВНИМАНИЕ!</b>\nTCP-порт <code>{name}</code> ({CONFIG.tcp_hosts[name]}) недоступен!")
                elif alive and name in dead_tcp_memory:
                    dead_tcp_memory.remove(name)
                    _send_alert(f"tcp:{name}", target_chat_id,
                                f"✅ <b>ОТБОЙ ТРЕВОГИ!</b>\nTCP-порт <code>{name}</code> снова доступен.")

        # --- 1.5 RESOURCE THRESHOLD ALERTS (CPU / RAM / Disk) ---
        try:
            resource = get_resource_usage()
        except Exception as e:
            logger.error(f"Ошибка сбора ресурсов: {e}")
            resource = None

        if resource is not None:
            resource_checks = [
                ("cpu", resource["cpu"], CONFIG.cpu_alert_percent, "CPU"),
                ("ram", resource["ram"], CONFIG.ram_alert_percent, "RAM"),
                ("disk", resource["disk_max"], CONFIG.disk_alert_percent, "Диск"),
            ]
            for key, value, threshold, label in resource_checks:
                was_alerted = resource_alerts_memory.get(key, False)
                if value >= threshold and not was_alerted:
                    resource_alerts_memory[key] = True
                    _send_alert(f"res:{key}", target_chat_id,
                                f"⚠️ <b>ВНИМАНИЕ!</b>\n{label} превысил порог: {value:.1f}% (порог {threshold}%).")
                elif value <= threshold - RESOURCE_HYSTERESIS_PERCENT and was_alerted:
                    resource_alerts_memory[key] = False
                    _send_alert(f"res:{key}", target_chat_id,
                                f"✅ <b>ОТБОЙ ТРЕВОГИ!</b>\n{label} вернулся в норму: {value:.1f}%.")

        # --- 2. SILENT REPORT ---
        if current_time - last_report_time >= CONFIG.intervals.silent_report_sec:
            try:
                report: str = generate_system_report()
                # disable_notification=True makes the message "silent"
                bot.send_message(target_chat_id, f"🕒 <b>Плановый отчет</b>\n\n{report}",
                                 parse_mode='HTML', disable_notification=True)
                last_report_time = current_time
            except Exception as e:
                logger.error(f"Ошибка планового отчета: {e}")

        # Sleep until the next Watchdog check
        time.sleep(CONFIG.intervals.watchdog_check_sec)


# Pending reboot confirmation (chat_id -> expiry timestamp)
_pending_reboot: dict[int, float] = {}
REBOOT_CONFIRM_WINDOW_SEC: int = 30
RESOURCE_HYSTERESIS_PERCENT: float = 5.0


def _run_reboot_request(chat_id: int) -> None:
    """Первый шаг /reboot: запрос подтверждения."""
    _pending_reboot[chat_id] = time.time() + REBOOT_CONFIRM_WINDOW_SEC
    bot.send_message(chat_id,
                     f"🔄 <b>Подтверждение перезагрузки</b>\n\n"
                     f"Вы запросили перезагрузку сервера.\n"
                     f"Отправьте <code>/reboot confirm</code> в течение {REBOOT_CONFIRM_WINDOW_SEC} секунд.",
                     parse_mode='HTML')


def _do_reboot(message: Message) -> None:
    admin_name: str = message.from_user.username or message.from_user.first_name
    bot.reply_to(message,
                 f"🔄 <b>Внимание!</b>\nАдминистратор @{admin_name} подтвердил перезагрузку.\n\nПерезагрузка через 5 секунд...",
                 parse_mode='HTML')
    # Даём боту 2 секунды, чтобы сообщение точно ушло на сервер Telegram
    time.sleep(2)
    try:
        # Windows: /r - reboot, /t 5 - таймер 5 секунд
        os.system("shutdown /r /t 5")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка при попытке перезагрузки: {e}")


def _run_reload(chat_id: int) -> None:
    try:
        reload_config()
    except Exception as e:
        logger.error(f"Ошибка /reload: {e}")
        bot.send_message(chat_id, f"❌ Не удалось перезагрузить конфиг: {e}")
        return
    logger.info("✅ Конфиг перезагружен.")
    bot.send_message(chat_id, "✅ Конфиг успешно перезагружен.")


@bot.message_handler(commands=['reload'])
def reload_config_command(message: Message) -> None:
    denied: str | None = access_denied(message)
    if denied:
        bot.reply_to(message, denied)
        return
    _run_reload(message.chat.id)


@bot.message_handler(commands=['reboot'])
def reboot_server(message: Message) -> None:
    # Strict Entitlement Verification (admin + group-only mode)
    denied: str | None = access_denied(message)
    if denied:
        if not is_admin(message.from_user.id):
            # Logging a brazen attempt
            logger.warning(f"⚠️ Попытка перезагрузки от неавторизованного ID: {message.from_user.id}")
        bot.reply_to(message, denied)
        return

    text: str = (message.text or "").strip().lower()
    parts: list[str] = text.split()

    # Second step: explicit confirmation
    if len(parts) >= 2 and parts[1] == "confirm":
        chat_id: int = message.chat.id
        expiry = _pending_reboot.get(chat_id)
        if expiry and time.time() <= expiry:
            _pending_reboot.pop(chat_id, None)
            _do_reboot(message)
        else:
            _pending_reboot.pop(chat_id, None)
            bot.reply_to(message, "⏳ Нет активной заявки на перезагрузку. Сначала отправьте /reboot.")
        return

    # First step: request confirmation
    _run_reboot_request(message.chat.id)


# Inline-menu callback handler
MENU_ACTIONS = {"status", "logs", "reboot", "reload"}


@bot.callback_query_handler(func=lambda call: call.data in MENU_ACTIONS)
def handle_menu(call) -> None:
    chat_id: int = call.message.chat.id
    denied: str | None = access_denied_ids(call.from_user.id, chat_id)
    if denied:
        bot.answer_callback_query(call.id, denied, show_alert=True)
        return

    bot.answer_callback_query(call.id)

    action = call.data
    if action == "status":
        _run_status(chat_id)
    elif action == "logs":
        _run_getlogs(chat_id)
    elif action == "reboot":
        _run_reboot_request(chat_id)
    elif action == "reload":
        _run_reload(chat_id)


# 4. Running the bot
_shutdown_event = threading.Event()


def _handle_shutdown(signum, frame) -> None:
    """Аккуратная остановка по SIGINT/SIGTERM."""
    logger.info(f"🛑 Получен сигнал {signum}, завершаю работу...")
    _shutdown_event.set()
    try:
        bot.stop_polling()
    except Exception as e:
        logger.error(f"Ошибка при остановке polling: {e}")


def run_polling() -> None:
    """Long polling с автоматическим переподключением и бэкоффом."""
    backoff: int = 1
    while not _shutdown_event.is_set():
        try:
            logger.info("🚀 Подключаюсь к Telegram API (long polling)...")
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except KeyboardInterrupt:
            logger.info("👋 Получен KeyboardInterrupt, завершаю работу.")
            break
        except Exception as e:
            if _shutdown_event.is_set():
                break
            logger.error(f"❌ Ошибка long polling: {e}. Повтор через {backoff} сек...")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
        else:
            backoff = 1  # нормальное завершение — сбрасываем бэкофф
    logger.info("🛑 Бот остановлен.")


if __name__ == "__main__":
    logger.info("🤖 Бот запущен и ожидает команд...")

    # Running a background loop in a parallel thread
    # daemon=True means that the thread will terminate itself when we close the script
    bg_thread: threading.Thread = threading.Thread(target=background_loop, daemon=True)
    bg_thread.start()

    # Обработка Ctrl+C / SIGTERM для аккуратного завершения
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_shutdown)
        except (ValueError, AttributeError, OSError):
            pass

    run_polling()