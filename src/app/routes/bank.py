"""API сотрудника банка: очередь заявок и решение по ручной проверке."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import auth, metrics, services
from ..database import get_db
from ..schemas import AnalystDecision, ApplicationOut, ApplicationShort, ExplanationOut
from .client import ERRORS

# Все методы банка — только после входа сотрудника
router = APIRouter(prefix="/bank", tags=["Кабинет аналитика"],
                   dependencies=[Depends(auth.require_staff)])
# Вход и выход — без проверки (иначе войти было бы невозможно)
login_router = APIRouter(prefix="/bank", tags=["Кабинет аналитика"])


class LoginIn(BaseModel):
    password: str


@login_router.post("/login", summary="Вход сотрудника банка: токен в cookie и в ответе",
                   responses={401: {"description": "Неверный пароль"}})
async def login(body: LoginIn, response: Response):
    if not auth.password_is_valid(body.password):
        raise auth.StaffAuthRequired("Неверный пароль")
    token = auth.make_token()
    response.set_cookie(auth.COOKIE, token, max_age=auth.TTL_SECONDS, httponly=True, samesite="lax")
    return {"token": token, "token_type": "bearer", "expires_in": auth.TTL_SECONDS}


@login_router.post("/logout", summary="Выход сотрудника банка")
async def logout(response: Response):
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@router.get("/applications", response_model=list[ApplicationShort],
            summary="Все заявки (фильтр по статусу, например MANUAL_REVIEW)")
async def queue(status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    return await services.list_applications(db, status=status)


@router.post("/applications/{app_id}/decision", response_model=ApplicationOut, responses=ERRORS,
             summary="Решение аналитика по заявке на ручной проверке")
async def decide(app_id: int, body: AnalystDecision, db: AsyncSession = Depends(get_db)):
    return await services.analyst_decide(db, app_id, body)


@router.post("/applications/{app_id}/explain", response_model=ExplanationOut, responses=ERRORS,
             summary="Заключение для аналитика: почему банк выдаёт кредит или нет (ИИ или шаблон). "
                     "Клиент его не видит")
async def explain(app_id: int, db: AsyncSession = Depends(get_db)):
    return await services.explain_for_analyst(db, app_id)


@router.get("/metrics", summary="Продуктовые метрики: путь клиента, польза, скорость, нагрузка")
async def product_metrics(db: AsyncSession = Depends(get_db)):
    return await metrics.compute(db)
