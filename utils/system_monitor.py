import subprocess
import psutil
import datetime
import time
import os
import platform
import socket
import urllib.request
import urllib.error
from collections import deque
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


def _resolve_disks() -> list[str]:
    """Возвращает диски для проверки: из конфига или автоопределение."""
    if CONFIG.disks_to_watch:
        return list(CONFIG.disks_to_watch)

    detected: list[str] = []
    for part in psutil.disk_partitions(all=False):
        mountpoint = part.mountpoint
        # Пропускаем CD-ROM (на Windows отмечен как 'cdrom' в opts)
        if platform.system() == "Windows" and part.opts and "cdrom" in part.opts.lower():
            continue
        try:
            psutil.disk_usage(mountpoint)
            detected.append(mountpoint)
        except (OSError, PermissionError):
            continue
    return detected


def get_disk_info() -> str:
    """Возвращает отчёт о свободном месте на отслеживаемых дисках."""
    report = ""
    for drive in _resolve_disks():
        try:
            usage = psutil.disk_usage(drive)
        except (OSError, PermissionError):
            continue
        total_gb = round(usage.total / (1024 ** 3), 2)
        free_gb = round(usage.free / (1024 ** 3), 2)
        report += f"💾 Диск {drive} {free_gb} GB свободно из {total_gb} GB ({usage.percent}%)\n"
    return report.strip()


def get_max_disk_percent() -> float:
    """Максимальная заполненность среди отслеживаемых дисков (%)."""
    percents = []
    for drive in _resolve_disks():
        try:
            percents.append(psutil.disk_usage(drive).percent)
        except (OSError, PermissionError):
            continue
    return max(percents) if percents else 0.0


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


def tail_file(path: str, n: int) -> bytes:
    """Возвращает последние n строк файла как bytes (память ограничена)."""
    if n <= 0:
        return b""
    with open(path, "rb") as f:
        lines = deque(f, maxlen=n)
    return b"".join(lines)


def _parse_host_port(target: str) -> tuple[str, int]:
    """Разбирает строку 'host:port'."""
    host, _, port_str = target.rpartition(":")
    if not host or not port_str:
        raise ValueError(f"Неверный формат адреса: {target}")
    return host, int(port_str)


def is_tcp_open(target: str) -> bool:
    """Проверяет доступность TCP-порта. target: 'host:port'."""
    try:
        host, port = _parse_host_port(target)
    except (ValueError, TypeError):
        return False
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except Exception:
        return False


def get_tcp_status() -> dict[str, bool]:
    """Возвращает {имя: доступен} для всех tcp_hosts из конфига."""
    return {name: is_tcp_open(target) for name, target in CONFIG.tcp_hosts.items()}


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


# Кэш для расчёта CPU процесса: pid -> (prev_time, prev_cpu_seconds)
_proc_cpu_cache: dict[int, tuple[float, float]] = {}


def _get_proc_cpu_percent(proc) -> float:
    """CPU процесса в % (по дельте cpu_times между вызовами). Первый замер = 0."""
    try:
        pid = proc.pid
        now = time.time()
        cpu_times = proc.cpu_times()
        total = cpu_times.user + cpu_times.system
        prev = _proc_cpu_cache.get(pid)
        _proc_cpu_cache[pid] = (now, total)
        if prev is None:
            return 0.0
        prev_time, prev_total = prev
        dt = now - prev_time
        if dt <= 0:
            return 0.0
        return min(100.0, max(0.0, (total - prev_total) / dt * 100.0))
    except Exception:
        return 0.0


def _get_proc_rss_mb(proc) -> float:
    """RSS процесса в МБ."""
    try:
        return round(proc.memory_info().rss / (1024 ** 2), 1)
    except Exception:
        return 0.0


def get_raw_process_status(process_list: dict[str, str]) -> dict[str, dict]:
    """Returns {pattern: {'is_alive', 'uptime', 'alias', 'cpu_percent', 'rss_mb'}}"""
    if not process_list:
        return {}
    status_dict = {
        pattern: {"is_alive": False, "uptime": "", "alias": alias or pattern, "cpu_percent": 0.0, "rss_mb": 0.0}
        for pattern, alias in process_list.items()
    }

    for proc in psutil.process_iter(['name', 'cmdline', 'create_time']):
        try:
            name = proc.info['name'].lower() if proc.info['name'] else ""
            cmdline = " ".join(proc.info['cmdline']).lower() if proc.info['cmdline'] else ""

            for pattern, alias in process_list.items():
                pattern_lower = pattern.lower()
                if pattern_lower in name or pattern_lower in cmdline:
                    create_time = proc.info['create_time']
                    uptime_seconds = int(time.time() - create_time)
                    uptime_str = str(datetime.timedelta(seconds=uptime_seconds))
                    status_dict[pattern] = {
                        "is_alive": True,
                        "uptime": uptime_str,
                        "alias": alias or pattern,
                        "cpu_percent": _get_proc_cpu_percent(proc),
                        "rss_mb": _get_proc_rss_mb(proc),
                    }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Чистим кэш от pid, которые больше не существуют
    for pid in list(_proc_cpu_cache.keys()):
        if not psutil.pid_exists(pid):
            del _proc_cpu_cache[pid]

    return status_dict


def check_processes(process_list: dict[str, str]) -> str:
    """Returns a nice string for the Telegram report"""
    status_dict = get_raw_process_status(process_list)
    if not status_dict:
        return "🤷‍♂️ Список процессов пуст"

    report = ""
    for pattern, info in status_dict.items():
        alias = info["alias"]
        if info["is_alive"]:
            cpu = info.get("cpu_percent", 0.0)
            rss = info.get("rss_mb", 0.0)
            report += f"✅ {alias}: Работает (⏱ {info['uptime']}, CPU {cpu:.1f}%, RAM {rss:.1f} MB)\n"
        else:
            report += f"❌ {alias}: НЕ НАЙДЕН\n"
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

    # Dynamic TCP port checks
    tcp_report = ""
    for name, target in CONFIG.tcp_hosts.items():
        status = "🟢 Доступен" if is_tcp_open(target) else "🔴 Недоступен"
        tcp_report += f"🔌 {name}: {status} ({target})\n"

    # Checking HTTP Locks and APIs (only if the toggle is enabled in config)
    http_report = ""
    if CONFIG.enable_http_checks:
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
    )

    if CONFIG.tcp_hosts:
        report += f"--- 🔌 TCP-порты ---\n{tcp_report}\n"

    if CONFIG.enable_http_checks:
        report += f"--- 🛡 API & Доступы ---\n{http_report}\n"

    report += (
        f"--- 💾 Диски ---\n"
        f"{disks}\n\n"
        f"--- 🐕 Watchdog ---\n"
        f"{process_status}"
    )
    return report


def get_resource_usage() -> dict[str, float]:
    """Мгновенный снимок ресурсов для алертов (без блокирующих замеров)."""
    cpu = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory().percent
    return {
        "cpu": cpu,
        "ram": ram,
        "disk_max": get_max_disk_percent(),
    }
