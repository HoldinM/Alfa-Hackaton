"""Вход для сотрудников банка: кабинет аналитика, метрики и /api/v1/bank/*.

Клиент видит только свой кабинет. Раздел банка открывается после входа по паролю сотрудника.
Пароль задаётся переменной окружения BANK_PASSWORD (для демо — значение по умолчанию из .env.example).

После входа сервер выдаёт подписанный токен: «срок действия.подпись».
Подпись — HMAC-SHA256 с секретом SESSION_SECRET, поэтому подделать токен без секрета нельзя.
Токен лежит в cookie (для страниц) и подходит как заголовок Authorization: Bearer (для API и Postman).
В настоящем банке вместо общего пароля — учётные записи сотрудников через систему входа банка.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .settings import settings

COOKIE = "bank_session"
TTL_SECONDS = 12 * 60 * 60  # рабочий день аналитика

_bearer = HTTPBearer(auto_error=False, description="Токен из POST /api/v1/bank/login")


class StaffAuthRequired(Exception):
    """Нет входа сотрудника банка (HTTP 401)."""


def _sign(payload: str) -> str:
    return hmac.new(settings.session_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    expires = str(int(time.time()) + TTL_SECONDS)
    return f"{expires}.{_sign('analyst:' + expires)}"


def token_is_valid(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    expires, signature = token.split(".", 1)
    if not expires.isdigit() or int(expires) < time.time():
        return False
    return hmac.compare_digest(signature, _sign("analyst:" + expires))


def password_is_valid(password: str) -> bool:
    return secrets.compare_digest(password.encode(), settings.bank_password.encode())


def is_staff(request: Request, creds: HTTPAuthorizationCredentials | None = None) -> bool:
    token = creds.credentials if creds else request.cookies.get(COOKIE)
    return token_is_valid(token)


async def require_staff(request: Request,
                        creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    """Зависимость для API банка: без входа — 401."""
    if not is_staff(request, creds):
        raise StaffAuthRequired()
