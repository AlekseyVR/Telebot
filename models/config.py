import json

from pydantic import BaseModel, Field, field_validator

class IntervalsConfig(BaseModel):
    watchdog_check_sec: int = 60
    silent_report_sec: int = 3600
    planned_restart_sec: int = 0

class AppConfig(BaseModel):
    admins: list[int] = Field(default_factory=list)
    target_chat_id: int = 0
    enable_group_only_mode: bool = True
    enable_http_checks: bool = False
    cpu_alert_percent: int = 85
    ram_alert_percent: int = 85
    disk_alert_percent: int = 90
    disks_to_watch: list[str] = Field(default_factory=list)
    tcp_hosts: dict[str, str] = Field(default_factory=dict)
    alert_cooldown_sec: int = 300
    intervals: IntervalsConfig = Field(default_factory=IntervalsConfig)
    ping_hosts: dict[str, str] = Field(default_factory=dict)
    http_hosts: dict[str, str] = Field(default_factory=dict)
    # pattern -> alias (display name): key is searched, value is shown
    processes_to_watch: dict[str, str] = Field(default_factory=dict)
    log_files: dict[str, str] = Field(default_factory=dict)

    @field_validator("processes_to_watch", mode="before")
    @classmethod
    def _normalize_processes(cls, value):
        # Backward compatibility: allow the old list format ["bot.py"]
        if isinstance(value, list):
            return {item: item for item in value}
        return value

# Global init
try:
    with open("config.json", "r", encoding="utf-8") as f:
        _raw_json = json.load(f)
        # Глобальная переменная, которую мы будем импортировать везде
        CONFIG = AppConfig(**_raw_json)
except FileNotFoundError:
    print("⚠️ Файл config.json не найден. Используются настройки по умолчанию.")
    CONFIG = AppConfig()


def reload_config() -> None:
    """Перечитывает config.json и обновляет глобальный CONFIG на месте.

    Все модули импортируют один и тот же объект CONFIG, поэтому мутация
    на месте сразу видна в обработчиках и фоновом цикле без рестарта.
    """
    with open("config.json", "r", encoding="utf-8") as f:
        _raw_json = json.load(f)
    new_config = AppConfig(**_raw_json)
    for field_name in new_config.model_fields:
        setattr(CONFIG, field_name, getattr(new_config, field_name))