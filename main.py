import os
import json
import telebot
import threading
import time
from dotenv import load_dotenv
from utils.system_monitor import generate_system_report, get_raw_process_status

# 1. Загрузка переменных окружения и конфига
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    exit("❌ Ошибка: BOT_TOKEN не найден в файле .env")

with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

ADMINS = config.get("admins", [])

# 2. Инициализация бота
bot = telebot.TeleBot(BOT_TOKEN)


# Вспомогательная функция проверки прав
def is_admin(user_id):
    return user_id in ADMINS


# 3. Базовый обработчик команд
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    user_id = message.from_user.id

    if not is_admin(user_id):
        bot.reply_to(message, "⛔ У вас нет доступа к этому боту.")
        # Выводим ID в консоль, чтобы ты мог скопировать его в config.json
        print(f"Попытка доступа от неавторизованного пользователя! ID: {user_id}")
        return

    bot.reply_to(message, "✅ Авторизация успешна! Серверный мониторинг готов к работе.\n\n"
                          "Доступные команды (пока в разработке):\n"
                          "/status - Статус системы\n"
                          "/getlogs - Получить логи")


@bot.message_handler(commands=['status'])
def send_status(message):
    user_id = message.from_user.id

    # Проверка прав
    if not is_admin(user_id):
        bot.reply_to(message, "⛔ У вас нет доступа к этой команде.")
        return

    # Сообщаем пользователю, что начали сбор данных
    msg = bot.reply_to(message, "⏳ Собираю данные о системе...")

    try:
        # Генерируем отчет, передавая конфиг с настройками процессов
        report = generate_system_report(config)
        # Редактируем сообщение, заменяя "Собираю данные..." на готовый отчет
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id,
                              text=report, parse_mode='HTML')
    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id,
                              text=f"❌ Ошибка при сборе данных: {e}")


@bot.message_handler(commands=['getlogs'])
def send_logs(message):
    user_id = message.from_user.id

    # Строгая проверка прав (логи - это конфиденциальная инфа)
    if not is_admin(user_id):
        bot.reply_to(message, "⛔ У вас нет доступа к этой команде.")
        return

    msg = bot.reply_to(message, "📁 Ищу файлы логов, указанные в конфиге...")

    log_files = config.get("log_files", {})

    # Если словарь пуст
    if not log_files:
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id,
                              text="🤷‍♂️ В файле config.json не указаны пути к логам (блок log_files).")
        return

    # Проходимся по словарю и отправляем файлы
    files_sent = 0
    for name, path in log_files.items():
        if os.path.exists(path):
            try:
                # Открываем файл в бинарном режиме 'rb' для отправки
                with open(path, 'rb') as document:
                    bot.send_document(message.chat.id, document, caption=f"📄 {name}")
                files_sent += 1
            except Exception as e:
                bot.send_message(message.chat.id, f"❌ Не удалось прочитать {name}: {e}")
        else:
            bot.send_message(message.chat.id, f"⚠️ Файл не найден: {name}\nПроверьте путь: <code>{path}</code>",
                             parse_mode='HTML')

    # Завершающее сообщение
    if files_sent > 0:
        bot.send_message(message.chat.id, f"✅ Отправка логов завершена. Передано файлов: {files_sent}.")
    else:
        bot.send_message(message.chat.id, "❌ Ни один файл логов не был отправлен (не найдены или ошибка доступа).")

def background_loop():
    print("🔄 Фоновый мониторинг запущен...")

    intervals = config.get("intervals", {})
    watchdog_sec = intervals.get("watchdog_check_sec", 60)
    report_sec = intervals.get("silent_report_sec", 3600)

    # Определяем, куда слать отчеты (группа или личка первого админа)
    target_chat_id = config.get("target_chat_id", 0)
    if target_chat_id == 0 and ADMINS:
        target_chat_id = ADMINS[0]

    processes = config.get("processes_to_watch", [])

    last_report_time = time.time()
    dead_processes_memory = set()  # Память, чтобы бот не спамил алертами

    while True:
        current_time = time.time()

        # --- 1. WATCHDOG (Экстренные проверки) ---
        if processes:
            status_dict = get_raw_process_status(processes)
            for proc_name, is_alive in status_dict.items():

                # Если процесс упал, и мы об этом еще не писали
                if not is_alive and proc_name not in dead_processes_memory:
                    dead_processes_memory.add(proc_name)
                    alert_msg = f"⚠️ <b>ВНИМАНИЕ!</b>\nПроцесс <code>{proc_name}</code> упал или не найден!"
                    try:
                        bot.send_message(target_chat_id, alert_msg, parse_mode='HTML')
                    except Exception as e:
                        print(f"Ошибка алерта: {e}")

                # Если процесс снова работает, а был в списке мертвых (ты его перезапустил)
                elif is_alive and proc_name in dead_processes_memory:
                    dead_processes_memory.remove(proc_name)
                    ok_msg = f"✅ <b>ОТБОЙ ТРЕВОГИ!</b>\nПроцесс <code>{proc_name}</code> снова в строю!"
                    try:
                        bot.send_message(target_chat_id, ok_msg, parse_mode='HTML')
                    except Exception as e:
                        pass

        # --- 2. SILENT REPORT (Плановые тихие отчеты) ---
        if current_time - last_report_time >= report_sec:
            try:
                report = generate_system_report(config)
                # disable_notification=True делает сообщение "тихим"
                bot.send_message(target_chat_id, f"🕒 <b>Плановый отчет</b>\n\n{report}",
                                 parse_mode='HTML', disable_notification=True)
                last_report_time = current_time
            except Exception as e:
                print(f"Ошибка планового отчета: {e}")

        # Спим до следующей проверки Watchdog
        time.sleep(watchdog_sec)


@bot.message_handler(commands=['reboot'])
def reboot_server(message):
    user_id = message.from_user.id

    # Строгая проверка прав
    if not is_admin(user_id):
        bot.reply_to(message, "⛔ У вас нет прав на выполнение этой команды.")
        # Логируем наглую попытку
        print(f"⚠️ Попытка перезагрузки от неавторизованного ID: {user_id}")
        return

    # Получаем юзернейм админа для отчета
    admin_name = message.from_user.username or message.from_user.first_name

    # Отправляем прощальное сообщение
    bot.reply_to(message,
                 f"🔄 <b>Внимание!</b>\nАдминистратор @{admin_name} инициировал перезагрузку сервера.\n\nПерезагрузка через 5 секунд...",
                 parse_mode='HTML')

    # Даем боту 2 секунды, чтобы сообщение гарантированно ушло на сервер Telegram
    time.sleep(2)

    try:
        # Выполняем системную команду Windows (shutdown: /r - reboot, /t 5 - таймер 5 сек)
        os.system("shutdown /r /t 5")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка при попытке перезагрузки: {e}")

# 4. Запуск бота
if __name__ == "__main__":
    print("🤖 Бот запущен и ожидает команд...")

    # Запускаем фоновый цикл в параллельном потоке
    # daemon=True означает, что поток завершится сам, когда мы закроем скрипт
    bg_thread = threading.Thread(target=background_loop, daemon=True)
    bg_thread.start()

    bot.infinity_polling()