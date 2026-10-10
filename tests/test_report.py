import utils.system_monitor as sm


def _patch_report_deps(monkeypatch, http_enabled):
    monkeypatch.setattr(sm, "get_uptime", lambda: "0:00:01")
    monkeypatch.setattr(sm, "get_cpu_info", lambda: 10.0)
    monkeypatch.setattr(sm, "get_ram_info", lambda: (4.0, 16.0, 25.0))
    monkeypatch.setattr(sm, "get_disk_info", lambda: "💾 Диск C:\\ 100 GB свободно")
    monkeypatch.setattr(sm, "check_processes", lambda pl: "✅ SmartNutri Bot: Работает")
    monkeypatch.setattr(sm, "check_ping", lambda host="": "🟢 Online")
    monkeypatch.setattr(sm, "check_http_status", lambda url: "🟢 OK")
    monkeypatch.setattr(sm.CONFIG, "enable_http_checks", http_enabled)
    monkeypatch.setattr(sm.CONFIG, "ping_hosts", {"Google": "8.8.8.8"})
    monkeypatch.setattr(sm.CONFIG, "http_hosts", {"Gemini API": "https://example.com"})
    monkeypatch.setattr(sm.CONFIG, "processes_to_watch", {"bot.py": "SmartNutri Bot"})


def test_report_has_no_http_section_when_disabled(monkeypatch):
    _patch_report_deps(monkeypatch, False)
    report = sm.generate_system_report()
    assert "API & Доступы" not in report


def test_report_has_http_section_when_enabled(monkeypatch):
    _patch_report_deps(monkeypatch, True)
    report = sm.generate_system_report()
    assert "API & Доступы" in report
    assert "Gemini API" in report
