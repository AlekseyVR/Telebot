import subprocess

import psutil
import datetime
import os
import platform
import urllib.request
import urllib.error


def get_uptime():
    """Возвращает время работы системы без перезагрузки"""
    boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
    now = datetime.datetime.now()
    uptime = now - boot_time
    # Форматируем, убирая микросекунды
    return str(uptime).split('.')[0]


def get_cpu_info():
    """Возвращает % загрузки процессора"""
    # interval=0.5 нужен, чтобы psutil успел замерить загрузку (иначе выдаст 0)
    cpu_percent = psutil.cpu_percent(interval=0.5)
    return cpu_percent


def get_ram_info():
    """Возвращает данные об оперативной памяти (GB и %)"""
    ram = psutil.virtual_memory()
    total_gb = round(ram.total / (1024 ** 3), 2)
    used_gb = round(ram.used / (1024 ** 3), 2)
    return used_gb, total_gb, ram.percent


def get_disk_info():
    """Возвращает информацию о дисках C и D"""
    report = ""
    # Проверяем диски C и D (для Windows)
    for drive in ['C:\\', 'D:\\']:
        if os.path.exists(drive):
            usage = psutil.disk_usage(drive)
            total_gb = round(usage.total / (1024 ** 3), 2)
            free_gb = round(usage.free / (1024 ** 3), 2)
            percent = usage.percent
            report += f"💾 Диск {drive} {free_gb} GB свободно из {total_gb} GB ({percent}%)\n"

    # Если запуск на Linux (опционально, на будущее)
    if platform.system() == "Linux":
        usage = psutil.disk_usage('/')
        free_gb = round(usage.free / (1024 ** 3), 2)
        report += f"💾 Диск /: {free_gb} GB свободно ({usage.percent}%)\n"

    return report.strip()



def check_ping(host="8.8.8.8"):
    # Windows использует '-n', Linux/Mac используют '-c'
    param = "-n" if platform.system().lower() == "windows" else "-c"
    command = ["ping", param, "1", host]
    try:
        # Выполняем команду скрыто, ждем максимум 3 секунды
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
        if result.returncode == 0:
            return f"🟢 Online ({host})"
        else:
            return f"🔴 Offline ({host})"
    except Exception:
        return f"🔴 Ошибка пинга ({host})"


def check_http_status(url):
    """Проверяет доступность WEB-ресурса и ищет блокировки"""
    try:
        # Маскируемся под браузер, так как некоторые API блокируют "голых" ботов
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=5) as response:
            # Если дошли сюда, значит статус 200-299
            return "🟢 OK (Доступ есть)"

    except urllib.error.HTTPError as e:
        # Именно здесь мы ловим блокировки
        if e.code == 403:
            return "🔴 ЗАБЛОКИРОВАН (403 Forbidden)"
        elif e.code == 429:
            return "🟡 ЛИМИТ (429 Too Many Requests)"
        elif e.code == 401 or e.code == 404:
            # 401/404 для API часто значит, что сам сервис жив, просто мы стучимся без ключа/не туда. Это нормально для проверки.
            return f"🟢 OK (API отвечает: {e.code})"
        else:
            return f"🔴 Ошибка сервера (HTTP {e.code})"

    except urllib.error.URLError:
        return "🔴 Недоступен (Нет связи)"
    except Exception as e:
        return f"🔴 Ошибка ({str(e)})"


def get_raw_process_status(process_list):
    """Возвращает словарь {имя_процесса: True/False}"""
    if not process_list:
        return {}

    status_dict = {p: False for p in process_list}

    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            name = proc.info['name'].lower() if proc.info['name'] else ""
            cmdline = " ".join(proc.info['cmdline']).lower() if proc.info['cmdline'] else ""

            for target in process_list:
                target_lower = target.lower()
                if target_lower in name or target_lower in cmdline:
                    status_dict[target] = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return status_dict


def check_processes(process_list):
    """Возвращает красивую строку для отчета Telegram"""
    status_dict = get_raw_process_status(process_list)
    if not status_dict:
        return "🤷‍♂️ Список процессов пуст"

    report = ""
    for p, is_alive in status_dict.items():
        if is_alive:
            report += f"✅ {p}: Работает\n"
        else:
            report += f"❌ {p}: НЕ НАЙДЕН\n"
    return report.strip()


def generate_system_report(config):
    uptime = get_uptime()
    cpu = get_cpu_info()
    ram_used, ram_total, ram_percent = get_ram_info()
    disks = get_disk_info()

    # Достаем список процессов из конфига
    processes_to_watch = config.get("processes_to_watch", [])
    process_status = check_processes(processes_to_watch)

    # Динамический пинг
    ping_report = ""
    for name, host in config.get("ping_hosts", {}).items():
        ping_report += f"📡 {name}: {check_ping(host)}\n"

    # Проверка HTTP блокировок и API
    http_report = ""
    for name, url in config.get("http_hosts", {}).items():
        # Умная подстановка ключей из .env
        if "{GEMINI_API_KEY}" in url:
            api_key = os.getenv("GEMINI_API_KEY", "")
            if not api_key:
                http_report += f"🔗 {name}: 🔴 Ошибка (Ключ не найден в .env)\n"
                continue
            url = url.replace("{GEMINI_API_KEY}", api_key)

        http_report += f"🔗 {name}: {check_http_status(url)}\n"

    cpu_icon = "🔴" if cpu > 85 else "🟢"
    ram_icon = "🔴" if ram_percent > 85 else "🟢"

    report = (
        f"🖥 <b>Статус Сервера</b>\n"
        f"⏱ <b>Uptime:</b> {uptime}\n\n"
        f"{cpu_icon} <b>CPU:</b> {cpu}%\n"
        f"{ram_icon} <b>RAM:</b> {ram_used} / {ram_total} GB ({ram_percent}%)\n\n"
        f"--- 🌐 Сеть (Ping) ---\n"
        f"{ping_report}\n"
        f"--- 🛡 API & Доступы ---\n"
        f"{http_report}\n"
        f"--- 💾 Диски ---\n"
        f"{disks}\n\n"
        f"--- 🐕 Watchdog ---\n"
        f"{process_status}"
    )
    return report
