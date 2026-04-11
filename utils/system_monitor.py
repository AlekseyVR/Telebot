import subprocess
import psutil
import datetime
import time
import os
import platform
import urllib.request
import urllib.error
from models.config import CONFIG


def get_uptime() -> str:
    """Returns system uptime without rebooting"""
    boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
    now = datetime.datetime.now()
    uptime = now - boot_time
    # Formatting by removing microseconds
    return str(uptime).split('.')[0]


def get_cpu_info() -> float:
    """Returns % CPU Usage"""
    # interval=0.5 is needed so that psutil has time to measure the load (otherwise it will return 0)
    cpu_percent = psutil.cpu_percent(interval=0.5)
    return cpu_percent


def get_ram_info() -> tuple[float, float, float]:
    """Returns RAM data (used_gb, total_gb, percent)"""
    ram = psutil.virtual_memory()
    total_gb = round(ram.total / (1024 ** 3), 2)
    used_gb = round(ram.used / (1024 ** 3), 2)
    return used_gb, total_gb, ram.percent


def get_disk_info() -> str:
    """Returns information about the C and D drives"""
    report = ""
    # Checking the C and D drives (for Windows)
    for drive in ['C:\\', 'D:\\']:
        if os.path.exists(drive):
            usage = psutil.disk_usage(drive)
            total_gb = round(usage.total / (1024 ** 3), 2)
            free_gb = round(usage.free / (1024 ** 3), 2)
            percent = usage.percent
            report += f"💾 Диск {drive} {free_gb} GB свободно из {total_gb} GB ({percent}%)\n"

    # If running on Linux (optional, for the future)
    if platform.system() == "Linux":
        usage = psutil.disk_usage('/')
        free_gb = round(usage.free / (1024 ** 3), 2)
        report += f"💾 Диск /: {free_gb} GB свободно ({usage.percent}%)\n"

    return report.strip()


def check_ping(host: str = "8.8.8.8") -> str:
    # Windows uses '-n', Linux/Mac uses '-c'
    param = "-n" if platform.system().lower() == "windows" else "-c"
    command = ["ping", param, "1", host]
    try:
        # Execute the command covertly, wait a maximum of 3 seconds
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
        if result.returncode == 0:
            return f"🟢 Online ({host})"
        else:
            return f"🔴 Offline ({host})"
    except Exception:
        return f"🔴 Ошибка пинга ({host})"


def check_http_status(url: str) -> str:
    """Checks the availability of the web resource and looks for locks"""
    try:
        # Masquerading as a browser, as some APIs block "naked" bots
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=5) as response:
            #  If you got here, then the status is 200-299
            return "🟢 OK (Доступ есть)"

    except urllib.error.HTTPError as e:
        # This is where we catch blockages
        if e.code == 403:
            return "🔴 ЗАБЛОКИРОВАН (403 Forbidden)"
        elif e.code == 429:
            return "🟡 ЛИМИТ (429 Too Many Requests)"
        elif e.code == 401 or e.code == 404:
            # A 401/404 for an API often means that the service itself is alive,
            # it's just that we're knocking without a key/in the wrong place. This is normal to check.
            return f"🟢 OK (API отвечает: {e.code})"
        else:
            return f"🔴 Ошибка сервера (HTTP {e.code})"

    except urllib.error.URLError:
        return "🔴 Недоступен (Нет связи)"
    except Exception as e:
        return f"🔴 Ошибка ({str(e)})"


def get_raw_process_status(process_list: list[str]) -> dict[str, dict]:
    """Returns {process_name: {'is_alive': bool, 'uptime': str}}"""
    if not process_list:
        return {}
    status_dict = {p: {"is_alive": False, "uptime": ""} for p in process_list}

    for proc in psutil.process_iter(['name', 'cmdline', 'create_time']):
        try:
            name = proc.info['name'].lower() if proc.info['name'] else ""
            cmdline = " ".join(proc.info['cmdline']).lower() if proc.info['cmdline'] else ""

            for target in process_list:
                target_lower = target.lower()
                if target_lower in name or target_lower in cmdline:
                    create_time = proc.info['create_time']
                    uptime_seconds = int(time.time() - create_time)
                    uptime_str = str(datetime.timedelta(seconds=uptime_seconds))
                    status_dict[target] = {"is_alive": True, "uptime": uptime_str}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return status_dict


def check_processes(process_list: list[str]) -> str:
    """Returns a nice string for the Telegram report"""
    status_dict = get_raw_process_status(process_list)
    if not status_dict:
        return "🤷‍♂️ Список процессов пуст"

    report = ""
    for p, info in status_dict.items():
        if info["is_alive"]:
            # ДОБАВИЛИ вывод аптайма
            report += f"✅ {p}: Работает (⏱ {info['uptime']})\n"
        else:
            report += f"❌ {p}: НЕ НАЙДЕН\n"
    return report.strip()


def generate_system_report() -> str:
    uptime = get_uptime()
    cpu = get_cpu_info()
    ram_used, ram_total, ram_percent = get_ram_info()
    disks = get_disk_info()

    # Taking out the list of processes from the config
    process_status = check_processes(CONFIG.processes_to_watch)

    # Dynamic Ping
    ping_report = ""
    for name, host in CONFIG.ping_hosts.items():
        ping_report += f"📡 {name}: {check_ping(host)}\n"

    # Checking HTTP Locks and APIs
    http_report = ""
    for name, url in CONFIG.http_hosts.items():
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
