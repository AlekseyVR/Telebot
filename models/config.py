import json

from pydantic import BaseModel, Field

class IntervalsConfig(BaseModel):
    watchdog_check_sec: int = 60
    silent_report_sec: int = 3600
    planned_restart_sec: int = 0

class AppConfig(BaseModel):
    admins: list[int] = Field(default_factory=list)
    target_chat_id: int = 0
    enable_group_only_mode: bool = True
    intervals: IntervalsConfig = Field(default_factory=IntervalsConfig)
    ping_hosts: dict[str, str] = Field(default_factory=dict)
    http_hosts: dict[str, str] = Field(default_factory=dict)
    processes_to_watch: list[str] = Field(default_factory=list)
    log_files: dict[str, str] = Field(default_factory=dict)

# Global init
try:
    with open("config.json", "r", encoding="utf-8") as f:
        _raw_json = json.load(f)
        # Глобальная переменная, которую мы будем импортировать везде
        CONFIG = AppConfig(**_raw_json)
except FileNotFoundError:
    print("⚠️ Файл config.json не найден. Используются настройки по умолчанию.")
    CONFIG = AppConfig()