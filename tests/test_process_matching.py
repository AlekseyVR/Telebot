import time

from utils.system_monitor import check_processes, get_raw_process_status


class _FakeProc:
    def __init__(self, name, cmdline, create_time, pid=9999, rss_mb=45.0):
        self.info = {"name": name, "cmdline": cmdline, "create_time": create_time}
        self.pid = pid
        self._rss_mb = rss_mb

    def cpu_times(self):
        class _T:
            user = 0.0
            system = 0.0
        return _T()

    def memory_info(self):
        class _M:
            rss = int(self._rss_mb * 1024 * 1024)
        return _M()


def test_process_found_by_name(monkeypatch):
    proc = _FakeProc("python.exe", ["python", "bot.py"], time.time() - 100)

    def fake_iter(attrs):
        return [proc]

    monkeypatch.setattr("utils.system_monitor.psutil.process_iter", fake_iter)
    status = get_raw_process_status({"bot.py": "SmartNutri Bot"})

    assert status["bot.py"]["is_alive"] is True
    assert status["bot.py"]["alias"] == "SmartNutri Bot"
    assert status["bot.py"]["uptime"]
    assert status["bot.py"]["rss_mb"] == 45.0
    assert status["bot.py"]["cpu_percent"] == 0.0  # первый замер — 0


def test_process_found_by_cmdline_substring(monkeypatch):
    proc = _FakeProc("node.exe", ["node", "C:\\app\\index.js"], time.time() - 50, pid=1234, rss_mb=12.5)

    def fake_iter(attrs):
        return [proc]

    monkeypatch.setattr("utils.system_monitor.psutil.process_iter", fake_iter)
    status = get_raw_process_status({"index.js": "API-сервер"})

    assert status["index.js"]["is_alive"] is True
    assert status["index.js"]["alias"] == "API-сервер"


def test_process_not_found(monkeypatch):
    def fake_iter(attrs):
        return []

    monkeypatch.setattr("utils.system_monitor.psutil.process_iter", fake_iter)
    status = get_raw_process_status({"missing.py": "Missing"})

    assert status["missing.py"]["is_alive"] is False
    assert status["missing.py"]["uptime"] == ""


def test_check_processes_uses_alias_and_resources(monkeypatch):
    proc = _FakeProc("python.exe", ["python", "bot.py"], time.time() - 10, pid=777, rss_mb=45.0)

    def fake_iter(attrs):
        return [proc]

    monkeypatch.setattr("utils.system_monitor.psutil.process_iter", fake_iter)
    out = check_processes({"bot.py": "SmartNutri Bot"})

    assert "SmartNutri Bot" in out
    assert "bot.py" not in out
    assert "RAM 45.0 MB" in out
