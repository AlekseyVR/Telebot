import os
import json
import telebot
import threading
import time
from dotenv import load_dotenv
from telebot.types import Message
from typing import Any

from utils.system_monitor import generate_system_report, get_raw_process_status

# 1. Loading environment and config variables
load_dotenv()
BOT_TOKEN: str | None = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    exit("❌ Ошибка: BOT_TOKEN не найден в файле .env")

with open("config.json", "r", encoding="utf-8") as f:
    config: dict[str, Any] = json.load(f)

ADMINS: list[int] = config.get("admins", [])

# 2. Bot initialization
bot = telebot.TeleBot(BOT_TOKEN)


# Eligibility Verification Assist Function
def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


# 3. Basic command handler
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message: Message) -> None:
    user_id: int = message.from_user.id

    if not is_admin(user_id):
        bot.reply_to(message, "⛔ У вас нет доступа к этому боту.")
        # Output the ID to the console so that you can copy it to config.json
        print(f"Попытка доступа от неавторизованного пользователя! ID: {user_id}")
        return

    bot.reply_to(message, "✅ Авторизация успешна! Серверный мониторинг готов к работе.\n\n"
                          "Доступные команды:\n"
                          "/status - Статус системы\n"
                          "/getlogs - Получить логи\n"
                          "/reboot - Перезагрузка сервера")


@bot.message_handler(commands=['status'])
def send_status(message: Message) -> None:
    user_id: int = message.from_user.id

    # Verification of rights
    if not is_admin(user_id):
        bot.reply_to(message, "⛔ У вас нет доступа к этой команде.")
        return

    # We inform the user that we have started collecting data
    msg: Message = bot.reply_to(message, "⏳ Собираю данные о системе...")

    try:
        # Generate a report by passing a config with process settings
        report: str = generate_system_report(config)
        # Edit the message, replacing "Collecting data..." on the finished report
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id,
                              text=report, parse_mode='HTML')
    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id,
                              text=f"❌ Ошибка при сборе данных: {e}")


@bot.message_handler(commands=['getlogs'])
def send_logs(message: Message) -> None:
    user_id: int = message.from_user.id

    # Strict rights check (logs are confidential information)
    if not is_admin(user_id):
        bot.reply_to(message, "⛔ У вас нет доступа к этой команде.")
        return

    msg: Message = bot.reply_to(message, "📁 Ищу файлы логов, указанные в конфиге...")

    log_files: dict[str, str] = config.get("log_files", {})

    # If the dictionary is empty
    if not log_files:
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id,
                              text="🤷‍♂️ В файле config.json не указаны пути к логам (блок log_files).")
        return

    # Go through the dictionary and send files
    files_sent: int = 0
    for name, path in log_files.items():
        if os.path.exists(path):
            try:
                # Open the file in binary mode 'rb' to send
                with open(path, 'rb') as document:
                    bot.send_document(message.chat.id, document, caption=f"📄 {name}")
                files_sent += 1
            except Exception as e:
                bot.send_message(message.chat.id, f"❌ Не удалось прочитать {name}: {e}")
        else:
            bot.send_message(message.chat.id, f"⚠️ Файл не найден: {name}\nПроверьте путь: <code>{path}</code>",
                             parse_mode='HTML')

    # Closing Message
    if files_sent > 0:
        bot.send_message(message.chat.id, f"✅ Отправка логов завершена. Передано файлов: {files_sent}.")
    else:
        bot.send_message(message.chat.id, "❌ Ни один файл логов не был отправлен (не найдены или ошибка доступа).")


def background_loop() -> None:
    print("🔄 Фоновый мониторинг запущен...")

    intervals: dict[str, int] = config.get("intervals", {})
    watchdog_sec: int = intervals.get("watchdog_check_sec", 60)
    report_sec: int = intervals.get("silent_report_sec", 3600)

    # Determine where to send reports (group or personal account of the first admin)
    target_chat_id: int = config.get("target_chat_id", 0)
    if target_chat_id == 0 and ADMINS:
        target_chat_id = ADMINS[0]

    processes: list[str] = config.get("processes_to_watch", [])

    last_report_time: float = time.time()
    dead_processes_memory: set[str] = set()  # Memory so that the bot does not spam alerts

    while True:
        current_time: float = time.time()

        # --- 1. WATCHDOG (Emergency Checks) ---
        if processes:
            status_dict: dict[str, bool] = get_raw_process_status(processes)
            for proc_name, is_alive in status_dict.items():

                # If the process has crashed and we haven't written about it yet
                if not is_alive and proc_name not in dead_processes_memory:
                    dead_processes_memory.add(proc_name)
                    alert_msg: str = f"⚠️ <b>ВНИМАНИЕ!</b>\nПроцесс <code>{proc_name}</code> упал или не найден!"
                    try:
                        bot.send_message(target_chat_id, alert_msg, parse_mode='HTML')
                    except Exception as e:
                        print(f"Ошибка алерта: {e}")

                # If the process is running again and was on the list of dead (you restarted it)
                elif is_alive and proc_name in dead_processes_memory:
                    dead_processes_memory.remove(proc_name)
                    ok_msg: str = f"✅ <b>ОТБОЙ ТРЕВОГИ!</b>\nПроцесс <code>{proc_name}</code> снова в строю!"
                    try:
                        bot.send_message(target_chat_id, ok_msg, parse_mode='HTML')
                    except Exception as e:
                        pass

        # --- 2. SILENT REPORT ---
        if current_time - last_report_time >= report_sec:
            try:
                report: str = generate_system_report(config)
                # disable_notification=True makes the message "silent"
                bot.send_message(target_chat_id, f"🕒 <b>Плановый отчет</b>\n\n{report}",
                                 parse_mode='HTML', disable_notification=True)
                last_report_time = current_time
            except Exception as e:
                print(f"Ошибка планового отчета: {e}")

        # Sleep until the next Watchdog check
        time.sleep(watchdog_sec)


@bot.message_handler(commands=['reboot'])
def reboot_server(message: Message) -> None:
    user_id: int = message.from_user.id

    # Strict Entitlement Verification
    if not is_admin(user_id):
        bot.reply_to(message, "⛔ У вас нет прав на выполнение этой команды.")
        # Logging a brazen attempt
        print(f"⚠️ Попытка перезагрузки от неавторизованного ID: {user_id}")
        return

    # Get the admin username for the report
    admin_name: str = message.from_user.username or message.from_user.first_name

    # Sending a farewell message
    bot.reply_to(message,
                 f"🔄 <b>Внимание!</b>\nАдминистратор @{admin_name} инициировал перезагрузку сервера.\n\nПерезагрузка через 5 секунд...",
                 parse_mode='HTML')

    # Give the bot 2 seconds to ensure that the message goes to the Telegram server
    time.sleep(2)

    try:
        # Execute the Windows system command (shutdown: /r - reboot, /t 5 - timer 5 sec)
        os.system("shutdown /r /t 5")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка при попытке перезагрузки: {e}")


# 4. Running the bot
if __name__ == "__main__":
    print("🤖 Бот запущен и ожидает команд...")

    # Running a background loop in a parallel thread
    # daemon=True means that the thread will terminate itself when we close the script
    bg_thread: threading.Thread = threading.Thread(target=background_loop, daemon=True)
    bg_thread.start()

    bot.infinity_polling()