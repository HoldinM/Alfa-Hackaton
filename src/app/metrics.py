"""Продуктовые метрики кредитного кабинета — считаются по данным из БД.

Каждая метрика отвечает на вопрос «нужно ли это пользователю и работает ли процесс».
Описание формул и того, как их читать, — в docs/metrics.md.

Для прототипа метрики считаются в Python по всем заявкам. При большом объёме
те же формулы переносятся в SQL-запросы или витрину данных.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from statistics import median

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import statuses as S
from .models import Application

OFFER = {S.OFFER_READY, S.COUNTER_OFFER, S.ALTERNATIVE_OFFER}
DECISION_LABELS = {
    "APPROVE": "Одобрено", "COUNTER_OFFER": "Другие условия", "ALTERNATIVE_PRODUCT": "Другой продукт",
    "REQUEST_INFO": "Нужны данные", "MANUAL_REVIEW": "Ручная проверка", "DECLINE": "Отказ",
}


# ---------------- форматирование ----------------

def _share(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _pct(v: float | None) -> str:
    return "нет данных" if v is None else f"{v * 100:.0f}%".replace(".", ",")


def _dur(seconds: float | None) -> str:
    if seconds is None:
        return "нет данных"
    if seconds < 1:
        return f"{seconds * 1000:.0f} мс"
    if seconds < 60:
        return f"{seconds:.1f} с".replace(".", ",")
    if seconds < 3600:
        return f"{seconds / 60:.0f} мин"
    if seconds < 86400:
        return f"{seconds / 3600:.1f} ч".replace(".", ",")
    return f"{seconds / 86400:.1f} дн".replace(".", ",")


def _med(values: list[float]) -> float | None:
    return round(median(values), 3) if values else None


def _secs(a: datetime, b: datetime) -> float:
    if (a.tzinfo is None) != (b.tzinfo is None):  # SQLite отдаёт время без пояса
        a, b = a.replace(tzinfo=None), b.replace(tzinfo=None)
    return max((b - a).total_seconds(), 0.0)


def _metric(key, label, value, display, formula, why):
    return {"key": key, "label": label, "value": value, "display": display,
            "formula": formula, "why": why}


# ---------------- расчёт ----------------

async def compute(db: AsyncSession) -> dict:
    q = select(Application).options(selectinload(Application.events),
                                    selectinload(Application.assessments),
                                    selectinload(Application.feedback))
    apps = (await db.execute(q)).scalars().all()
    total = len(apps)

    def reached(app, statuses) -> bool:
        return any(e.to_status in statuses for e in app.events)

    # --- путь клиента ---
    with_offer = [a for a in apps if reached(a, OFFER)]
    accepted = [a for a in with_offer if reached(a, {S.OFFER_ACCEPTED})]
    issued = [a for a in apps if reached(a, {S.ISSUED})]
    cancelled = [a for a in apps if a.status == S.CANCELLED]

    # --- польза решения ---
    decisions_ever = [{x.decision for x in a.assessments} for a in apps]
    would_decline = [d for d in decisions_ever if d & {"COUNTER_OFFER", "ALTERNATIVE_PRODUCT", "DECLINE"}]
    saved = [d for d in would_decline if d & {"COUNTER_OFFER", "ALTERNATIVE_PRODUCT"}]
    asked_info = [a for a in apps if reached(a, {S.INFO_REQUESTED})]
    gave_info, info_secs = [], []
    for a in asked_info:
        evs = a.events
        for i, e in enumerate(evs):
            if e.to_status == S.INFO_REQUESTED:
                nxt = next((x for x in evs[i + 1:] if x.to_status == S.SUBMITTED), None)
                if nxt:
                    gave_info.append(a)
                    info_secs.append(_secs(e.created_at, nxt.created_at))
                break
    fb = [f for a in apps for f in a.feedback]
    fb_decline = [f for f in fb if f.status == S.DECLINED]

    # --- скорость ---
    ml_ms = [x.duration_ms for a in apps for x in a.assessments if x.duration_ms is not None]
    manual_secs, analyst_approved, analyst_total = [], 0, 0
    for a in apps:
        for i, e in enumerate(a.events):
            if e.to_status == S.MANUAL_REVIEW:
                done = next((x for x in a.events[i + 1:] if x.actor == "analyst"), None)
                if done:
                    analyst_total += 1
                    analyst_approved += done.to_status == S.OFFER_READY
                    manual_secs.append(_secs(e.created_at, done.created_at))
    issue_secs = [_secs(a.created_at, next(e for e in a.events if e.to_status == S.ISSUED).created_at)
                  for a in issued]

    # --- нагрузка на банк ---
    manual_ever = [a for a in apps if reached(a, {S.MANUAL_REVIEW})]
    queue_now = sum(1 for a in apps if a.status == S.MANUAL_REVIEW)

    # --- модель ---
    last = [a.assessments[-1] for a in apps if a.assessments]
    decisions = Counter(x.decision for x in last)
    grades = Counter(x.grade for x in last if x.grade)
    pds = [x.pd for x in last if x.pd is not None]
    versions = sorted({x.model_version for a in apps for x in a.assessments})

    v = {
        "offer": _share(len(with_offer), total),
        "accept": _share(len(accepted), len(with_offer)),
        "issued": _share(len(issued), total),
        "cancel": _share(len(cancelled), total),
        "saved": _share(len(saved), len(would_decline)),
        "info": _share(len(gave_info), len(asked_info)),
        "clear": _share(sum(f.decision_clear for f in fb), len(fb)),
        "clear_decl": _share(sum(f.decision_clear for f in fb_decline), len(fb_decline)),
        "auto": _share(total - len(manual_ever), total),
        "analyst_ok": _share(analyst_approved, analyst_total),
    }
    ml_med = _med([m / 1000 for m in ml_ms])

    groups = [
        {"title": "Путь клиента", "metrics": [
            _metric("applications_total", "Заявок подано", total, str(total),
                    "число заявок", "Масштаб использования кабинета"),
            _metric("offer_rate", "Получили предложение денег", v["offer"], _pct(v["offer"]),
                    "заявки, получившие одобрение, другие условия или другой продукт / все заявки",
                    "Сколько клиентов кабинет довёл до реальных условий кредита"),
            _metric("acceptance_rate", "Приняли предложение", v["accept"], _pct(v["accept"]),
                    "заявки, где клиент принял условия / заявки с предложением",
                    "Подходят ли клиенту условия, которые мы предлагаем"),
            _metric("issue_rate", "Дошли до выдачи", v["issued"], _pct(v["issued"]),
                    "заявки в статусе «кредит выдан» / все заявки",
                    "Главная конверсия: от заявки до денег"),
            _metric("cancel_rate", "Отозвали заявку", v["cancel"], _pct(v["cancel"]),
                    "заявки, отозванные клиентом / все заявки",
                    "Рост показывает, где клиенты бросают процесс"),
        ]},
        {"title": "Польза для клиента", "metrics": [
            _metric("saved_from_decline", "Отказы, превращённые в предложение", v["saved"],
                    _pct(v["saved"]),
                    "заявки с контрпредложением или другим продуктом / они же + отказы",
                    "Сколько клиентов получили деньги на других условиях вместо простого отказа"),
            _metric("info_completion", "Дозагрузили данные после запроса", v["info"], _pct(v["info"]),
                    "заявки, где клиент дозагрузил данные / заявки, где их запросили",
                    "Понятно ли клиенту, чего не хватает, и может ли он это дать"),
            _metric("decision_clarity", "Решение понятно клиенту", v["clear"], _pct(v["clear"]),
                    "ответы «да» на вопрос «понятно, почему банк так решил?» / все ответы",
                    "Прямая оценка клиента: решает ли кабинет боль «непонятны причины»"),
            _metric("decline_clarity", "Причины отказа понятны", v["clear_decl"],
                    _pct(v["clear_decl"]), "то же только по отказам",
                    "Отказ — самое чувствительное решение, его понятность важнее всего"),
            _metric("feedback_count", "Ответов клиентов", len(fb), str(len(fb)),
                    "число ответов на вопрос о понятности", "Хватает ли ответов, чтобы доверять доле"),
        ]},
        {"title": "Скорость", "metrics": [
            _metric("ml_decision_time", "Время автоматического решения (медиана)", ml_med,
                    _dur(ml_med), "медиана времени работы ML по всем оценкам",
                    "Клиент получает ответ сразу, а не через дни"),
            _metric("info_turnaround", "Время на дозагрузку данных (медиана)", _med(info_secs),
                    _dur(_med(info_secs)), "от запроса данных до их загрузки клиентом",
                    "Долгая дозагрузка — сигнал, что запрос сформулирован непонятно"),
            _metric("manual_review_time", "Время ручной проверки (медиана)", _med(manual_secs),
                    _dur(_med(manual_secs)), "от попадания в очередь до решения аналитика",
                    "Сколько клиент ждёт человека"),
            _metric("time_to_issue", "От заявки до выдачи (медиана)", _med(issue_secs),
                    _dur(_med(issue_secs)), "от подачи заявки до статуса «кредит выдан»",
                    "Полное время пути клиента"),
        ]},
        {"title": "Нагрузка на банк", "metrics": [
            _metric("auto_decision_rate", "Решено без аналитика", v["auto"], _pct(v["auto"]),
                    "заявки, ни разу не попадавшие на ручную проверку / все заявки",
                    "Сколько работы автоматизировано"),
            _metric("manual_queue", "В очереди аналитика сейчас", queue_now, str(queue_now),
                    "заявки в статусе «на проверке у аналитика»", "Нужны ли ещё аналитики"),
            _metric("analyst_approval_rate", "Аналитик одобрил", v["analyst_ok"],
                    _pct(v["analyst_ok"]), "одобрения аналитика / все его решения",
                    "Если почти всё одобряется — правила ручной проверки слишком строгие"),
        ]},
        {"title": "Модель", "metrics": [
            _metric("mean_pd", "Средняя вероятность невозврата", round(sum(pds) / len(pds), 4) if pds else None,
                    _pct(sum(pds) / len(pds)) if pds else "нет данных",
                    "среднее PD по последним оценкам заявок",
                    "Резкий рост — сигнал, что изменился поток клиентов или модель устарела"),
        ]},
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "applications_total": total,
        "groups": groups,
        "decisions": [{"decision": k, "label": DECISION_LABELS.get(k, k), "count": c,
                       "share": _share(c, len(last))} for k, c in decisions.most_common()],
        "grades": [{"grade": g, "count": grades.get(g, 0), "share": _share(grades.get(g, 0), sum(grades.values()))}
                   for g in "ABCDE"],
        "model_versions": versions,
    }
