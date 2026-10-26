"""Формат запросов и ответов API бэкенда (из этих классов строится Swagger)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

PurposeCode = Literal["cash_gap", "working_capital", "contract", "equipment", "expansion",
                      "real_estate", "refinance", "other"]
ProductCode = Literal["OVERDRAFT", "EXPRESS", "WORKING_CAPITAL", "EQUIPMENT", "INVESTMENT"]


def _digits_inn(v: str) -> str:
    v = v.strip()
    if not v.isdigit() or len(v) not in (10, 12):
        raise ValueError("ИНН — 10 цифр для ООО или 12 цифр для ИП")
    return v


# ---------------- запросы ----------------

IndustryCode = Literal["trade", "food", "construction", "it", "manufacturing", "transport",
                       "services", "agro"]


class CompanyIn(BaseModel):
    """Своя компания: данные вводит сам пользователь (своя синтетика вместо моков реестров)."""
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, max_length=255, examples=["ООО «Моя пекарня»"])
    legal_form: Literal["IP", "OOO"]
    industry: IndustryCode
    egrul_status: Literal["active", "liquidating", "liquidated", "bankruptcy"] = "active"
    business_age_months: int = Field(ge=0, le=1200, description="Сколько месяцев работает бизнес")
    annual_revenue: float = Field(gt=0, description="Выручка за год, ₽")
    net_margin: float = Field(ge=-1, le=1, description="Чистая прибыль / выручка, доля")
    revenue_trend: float = Field(0, ge=-1, le=5, description="Изменение выручки к прошлому году, доля")
    revenue_volatility: float = Field(0.3, ge=0, le=5, description="Колебания оборотов по месяцам")
    existing_debt: float = Field(0, ge=0, description="Текущий долг по кредитам, ₽")
    existing_monthly_payments: float = Field(0, ge=0, description="Платежи по текущим кредитам в месяц, ₽")
    bki_max_overdue_days_12m: int = Field(0, ge=0, le=3650)
    bki_overdue_count_12m: int = Field(0, ge=0, le=1000)
    bki_inquiries_3m: int = Field(0, ge=0, le=1000)
    tax_arrears: bool = False
    mass_address: bool = False
    director_changes_12m: int = Field(0, ge=0, le=50)


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inn: Optional[str] = Field(None, examples=["7756405021"],
                               description="ИНН. Для своей компании можно не указывать — сгенерируем")
    company: Optional[CompanyIn] = Field(None, description="Своя компания вместо данных из реестров")
    purpose: PurposeCode = Field(examples=["equipment"])
    purpose_text: Optional[str] = Field(None, max_length=2000,
                                        description="Цель своими словами (как ввёл клиент)")
    product_code: Optional[ProductCode] = Field(None, description="Не задан — ML подберёт сам")
    requested_amount: float = Field(gt=0, le=1_000_000_000, examples=[5_000_000])
    term_months: int = Field(ge=1, le=120, examples=[36])
    consent_bki: bool = Field(False, description="Согласие на запрос кредитной истории")
    annual_revenue: Optional[float] = Field(None, gt=0, description="Выручка за год со слов клиента")
    net_margin: Optional[float] = Field(None, ge=-1, le=1, description="Рентабельность, доля")

    @field_validator("inn")
    @classmethod
    def _check_inn(cls, v: Optional[str]) -> Optional[str]:
        return _digits_inn(v) if v else None


class ProvideInfo(BaseModel):
    """Дозагрузка данных по заявке в статусе «Нужны данные»."""
    model_config = ConfigDict(extra="forbid")

    consent_bki: Optional[bool] = None
    statement_csv: Optional[str] = Field(None, max_length=5_000_000)
    statement_filename: Optional[str] = Field(None, max_length=255)
    annual_revenue: Optional[float] = Field(None, gt=0)
    net_margin: Optional[float] = Field(None, ge=-1, le=1)


class AcceptOffer(BaseModel):
    offer_index: int = Field(0, ge=0, description="Номер варианта из списка offers")


class FeedbackIn(BaseModel):
    """Ответ клиента: понятно ли, почему банк принял такое решение."""
    decision_clear: bool
    comment: Optional[str] = Field(None, max_length=2000)


class AnalystDecision(BaseModel):
    approve: bool
    comment: str = Field(min_length=3, max_length=2000)


class RecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inn: Optional[str] = None
    company: Optional[CompanyIn] = None
    purpose: Optional[PurposeCode] = None
    purpose_text: Optional[str] = Field(None, max_length=2000)
    requested_amount: float = Field(gt=0, le=1_000_000_000)
    term_months: int = Field(ge=1, le=120)


# ---------------- ответы ----------------

class EventOut(BaseModel):
    from_status: Optional[str]
    to_status: str
    to_status_label: str
    actor: str
    comment: Optional[str]
    created_at: datetime


class AssessmentOut(BaseModel):
    """Результат ML по заявке — ровно то, что нужно экрану."""
    decision: str
    decision_label: str
    client_message: str
    risk: Optional[dict]
    offer: Optional[dict]
    offers: list[dict]
    reasons: list[dict]
    advice: list[str]
    missing_data: list[dict]
    checks: list[dict]
    notes: list[str]
    requires_manual_review: bool
    manual_review_flags: list[str]
    features: Optional[dict] = Field(None, description="Признаки, на которых считала модель")
    explanation: Optional[dict] = Field(None, description="Объяснение простыми словами, если уже запрошено")
    model_version: str
    policy_version: str
    assessed_at: datetime


class ExplanationOut(BaseModel):
    """Объяснение решения простыми словами."""
    text: str
    source: Literal["llm", "template"] = Field(description="llm — написала языковая модель, "
                                                           "template — шаблон из фактов решения")
    model: Optional[str] = Field(None, description="Какая языковая модель писала текст")
    note: Optional[str] = Field(None, description="Почему показан шаблон вместо ИИ")
    facts: list[str] = Field(description="Факты решения — всё, что видела модель")
    decision: str = Field(description="К какому решению относится объяснение")


class DocumentOut(BaseModel):
    id: int
    kind: str
    filename: Optional[str]
    created_at: datetime


class ApplicationOut(BaseModel):
    id: int
    inn: str
    company_name: str
    own_company: bool = Field(False, description="Данные компании ввёл сам пользователь")
    purpose: str
    purpose_label: Optional[str]
    purpose_text: Optional[str]
    product_code: Optional[str]
    requested_amount: float
    term_months: int
    consent_bki: bool
    status: str
    status_label: str
    status_hint: str
    actions: list[str] = Field(description="Что клиент может сделать сейчас")
    accepted_offer: Optional[dict]
    feedback: Optional[dict] = Field(None, description="Последний ответ клиента о понятности решения")
    assessment: Optional[AssessmentOut] = Field(description="Последнее решение ML")
    assessments_count: int
    documents: list[DocumentOut]
    events: list[EventOut]
    created_at: datetime
    updated_at: datetime


class ApplicationShort(BaseModel):
    id: int
    inn: str
    company_name: str
    product_code: Optional[str]
    requested_amount: float
    term_months: int
    status: str
    status_label: str
    grade: Optional[str]
    score: Optional[int]
    requires_manual_review: bool
    created_at: datetime
    updated_at: datetime


class ErrorOut(BaseModel):
    error: str
    message: str
    detail: Any = None
