from models.config import AppConfig


def test_defaults():
    cfg = AppConfig()
    assert cfg.enable_http_checks is False
    assert cfg.enable_group_only_mode is True
    assert cfg.cpu_alert_percent == 85
    assert cfg.ram_alert_percent == 85
    assert cfg.disk_alert_percent == 90
    assert cfg.disks_to_watch == []
    assert cfg.processes_to_watch == {}


def test_legacy_process_list_is_normalized_to_dict():
    cfg = AppConfig(processes_to_watch=["bot.py", "nginx.exe"])
    assert cfg.processes_to_watch == {"bot.py": "bot.py", "nginx.exe": "nginx.exe"}


def test_process_dict_with_aliases_is_kept():
    cfg = AppConfig(processes_to_watch={"bot.py": "SmartNutri Bot"})
    assert cfg.processes_to_watch == {"bot.py": "SmartNutri Bot"}
