"""Настройки приложения. Всё, что зависит от окружения, читается из переменных окружения."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Подключение к БД. В docker-compose хост — db, локально — localhost.
    database_url: str = "postgresql+asyncpg://alfa_user:alfa_password@localhost:5432/alfa_credit_db"
    # Печатать SQL-запросы в лог (для отладки)
    sql_echo: bool = False
    # Создавать таблицы при старте без миграций (только для тестов и быстрых демо)
    auto_create_tables: bool = False
    # С каких адресов фронтенд может обращаться к API
    cors_origins: str = "*"
    # Пароль для входа сотрудников банка в кабинет аналитика и метрики (демо)
    bank_password: str = "alfa-analyst"
    # Секрет для подписи токена входа. В настоящем запуске задайте свой длинный случайный
    session_secret: str = "dev-secret-change-me"
    # Языковая модель для объяснения решений (Ollama). Пусто — шаблонное объяснение без ИИ.
    llm_url: str = ""
    # Модель в Ollama: Qwen2.5-7B-Instruct (7,6 млрд параметров, Apache 2.0)
    llm_model: str = "qwen2.5:7b-instruct"
    # Сколько секунд ждать ответа модели
    llm_timeout: float = 60.0


settings = Settings()
