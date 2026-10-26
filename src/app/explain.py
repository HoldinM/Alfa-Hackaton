"""Объяснение решения простыми словами: почему банк одобрил, предложил другое или отказал.

Как это устроено:
1. facts() собирает факты решения из ответа ML: решение, условия, ставку, причины, проверки.
   Это единственное, что знает языковая модель. Решение принимает ML, а не языковая модель.
2. Если задан LLM_URL, факты уходят в локальную языковую модель через Ollama
   (по умолчанию Qwen2.5-7B-Instruct — 7,6 млрд параметров, лицензия Apache 2.0).
3. Проверка: каждое число в ответе модели должно встречаться в фактах.
   Если модель выдумала число, ответ не показываем и берём шаблонный текст.
4. Если LLM_URL не задан или модель недоступна — шаблонное объяснение из тех же фактов.
   В ответе всегда указано, кто написал текст: source = "llm" или "template".
"""

from __future__ import annotations

import logging
import re

import httpx

from .settings import settings

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Ты помощник банка. Объясни предпринимателю решение по его заявке на кредит. "
    "Пиши по-русски, просто, без канцелярита, 4–7 предложений. "
    "Используй только факты из сообщения пользователя. Не придумывай чисел, условий и причин. "
    "Числа переписывай точно так же, как они написаны в фактах. "
    "Скажи: какое решение, какие факторы на него повлияли и почему, "
    "из чего сложилась ставка, и что можно сделать дальше. "
    "Не обещай одобрение и не давай советов, которых нет в фактах."
)


# ---------------- форматирование чисел (одинаково для фактов и шаблона) ----------------

def _rub(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ") + " ₽"


def _pct(x: float, digits: int = 1) -> str:
    s = f"{x * 100:.{digits}f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") + "%"


def _pp(x: float) -> str:
    return f"{x:g}".replace(".", ",") + " п.п."


# ---------------- 1. факты ----------------

def facts(result: dict, company_name: str) -> list[str]:
    """Факты решения строками. Их видит модель, из них же строится шаблон."""
    lines = [f"Компания: {company_name}", f"Решение банка: {result['decision_label']}"]
    req = result.get("request") or {}
    if req:
        lines.append(f"Запрос клиента: {_rub(req['requested_amount'])} на {req['term_months']} мес., "
                     f"цель: {req.get('purpose_label') or req.get('purpose')}")
    lines.append(f"Сообщение системы: {result['client_message']}")

    risk = result.get("risk") or {}
    if risk.get("grade"):
        lines.append(f"Оценка риска: грейд {risk['grade']} (шкала A–E, A — самый надёжный), "
                     f"балл {risk['score']}, вероятность дефолта {_pct(risk['pd'])}")

    o = result.get("offer")
    if o:
        lines.append(f"Предложение: {o['product_name']}, {_rub(o['amount'])} на {o['term_months']} мес.")
        if o.get("rate") is not None:
            lines.append(f"Ставка: {_pct(o['rate'])} годовых = базовая ставка продукта "
                         f"{_pct(o['base_rate'])} + надбавка за риск {_pp(o['risk_premium_pp'])}")
        if o.get("monthly_payment") is not None:
            lines.append(f"Платёж в месяц: {_rub(o['monthly_payment'])}")
        if o.get("overpayment") is not None:
            lines.append(f"Переплата за весь срок: {_rub(o['overpayment'])}")
        if o.get("dscr") is not None:
            lines.append(f"Денежный поток покрывает платёж в {str(o['dscr']).replace('.', ',')} раза "
                         f"(банку нужно не меньше 1,25)")
        if o.get("comment"):
            lines.append(f"Комментарий к предложению: {o['comment']}")

    for r in result.get("reasons", []):
        mark = {"positive": "в плюс", "negative": "в минус"}.get(r["impact"], "нейтрально")
        line = f"Фактор ({mark}): {r['text']}"
        if r.get("advice"):
            line += f". Что сделать: {r['advice']}"
        lines.append(line)
    for c in result.get("checks", []):
        if c["status"] != "passed":
            state = "не пройдена" if c["status"] == "failed" else "внимание"
            lines.append(f"Проверка «{c['name']}»: {state}" + (f", {c['details']}" if c["details"] else ""))
    for flag in result.get("manual_review_flags", []):
        lines.append(f"Нужна ручная проверка: {flag}")
    for m in result.get("missing_data", []):
        lines.append(f"Не хватает данных: {m['label']} — {m['why']}"
                     + (f". Можно иначе: {m['alternative']}" if m.get("alternative") else ""))
    for a in result.get("advice", []):
        lines.append(f"Совет: {a}")
    return lines


# ---------------- 2. шаблонное объяснение ----------------

def _list(prefix: str, items: list[str]) -> str:
    """«Префикс: пункт; пункт.» — без двойных точек и с маленькой буквы."""
    items = [re.sub(r"\s*\([a-z_, ]+\)", "", t).strip() for t in dict.fromkeys(items) if t]
    items = [t[0].lower() + t[1:] if t[:2] != t[:2].upper() else t for t in items]
    text = f"{prefix}: " + "; ".join(items)
    return text if text.endswith(".") else text + "."


def template_text(result: dict, company_name: str) -> str:
    parts = [f"Решение по заявке: {result['decision_label'].lower()}. {result['client_message']}"]
    risk = result.get("risk") or {}
    if risk.get("grade"):
        parts.append(f"Модель оценила риск компании на грейд {risk['grade']} по шкале от A до E "
                     f"(вероятность дефолта {_pct(risk['pd'])}).")
    pos = [r["text"] for r in result.get("reasons", []) if r["impact"] == "positive"]
    neg = [r for r in result.get("reasons", []) if r["impact"] == "negative"]
    if pos:
        parts.append(_list("В плюс сыграло", pos))
    if neg:
        parts.append(_list("В минус", [r["text"] for r in neg]))
    failed = [c for c in result.get("checks", []) if c["status"] == "failed"]
    if failed:
        parts.append(_list("Не пройдены проверки", [
            c["name"] + (f" ({c['details']})" if c["details"] else "") for c in failed]))
    missing = result.get("missing_data", [])
    if missing:
        parts.append(_list("Чтобы принять решение, нужно", [
            m["label"] + (f" ({m['alternative']})" if m.get("alternative") else "") for m in missing]))
    o = result.get("offer")
    if o and o.get("rate") is not None:
        prem = (f"плюс {_pp(o['risk_premium_pp'])} за риск" if o["risk_premium_pp"]
                else "без надбавки за риск")
        parts.append(f"Предложение: {_rub(o['amount'])} на {o['term_months']} мес. "
                     f"Ставка {_pct(o['rate'])} годовых: базовая ставка продукта "
                     f"{_pct(o['base_rate'])} {prem}. Платёж {_rub(o['monthly_payment'])} в месяц.")
    todo = [r["advice"] for r in neg if r.get("advice")] + list(result.get("advice", []))
    if todo:
        parts.append(_list("Что можно сделать", todo))
    return " ".join(parts)


# ---------------- 3. проверка чисел ----------------

_NUM = re.compile(r"\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")


def _numbers(text: str) -> set[str]:
    out = set()
    for m in _NUM.findall(text):
        n = re.sub(r"[   ]", "", m).replace(",", ".")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n)
    return out


def unknown_numbers(text: str, fact_lines: list[str]) -> set[str]:
    """Числа из текста модели, которых нет в фактах. Пустое множество — текст прошёл проверку."""
    allowed = _numbers("\n".join(fact_lines)) | {str(i) for i in range(1, 11)}
    return _numbers(text) - allowed


# ---------------- 4. вызов модели ----------------

async def _ask_llm(fact_lines: list[str], system_prompt: str = SYSTEM_PROMPT) -> str:
    async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
        r = await client.post(f"{settings.llm_url.rstrip('/')}/api/chat", json={
            "model": settings.llm_model,
            "stream": False,
            "options": {"temperature": 0.2},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Факты решения:\n- " + "\n- ".join(fact_lines)},
            ],
        })
        r.raise_for_status()
        return r.json()["message"]["content"].strip()


async def _write(fact_lines: list[str], template: str, system_prompt: str) -> dict:
    """Текст от модели, если она подключена и не выдумала чисел. Иначе — шаблон."""
    fallback = {"text": template, "source": "template", "model": None, "facts": fact_lines}
    if not settings.llm_url:
        return {**fallback, "note": "Языковая модель не подключена (LLM_URL не задан)"}
    try:
        text = await _ask_llm(fact_lines, system_prompt)
    except Exception as e:  # сеть, таймаут, модель не скачана — объяснение всё равно будет
        log.warning("LLM недоступна: %s", e)
        return {**fallback, "note": "Языковая модель недоступна, показано шаблонное объяснение"}
    bad = unknown_numbers(text, fact_lines)
    if not text or bad:
        log.warning("Ответ LLM отклонён, числа не из фактов: %s", sorted(bad))
        return {**fallback, "note": "Ответ модели не прошёл проверку чисел, показано шаблонное объяснение"}
    return {"text": text, "source": "llm", "model": settings.llm_model, "facts": fact_lines,
            "note": None}


async def explain(result: dict, company_name: str) -> dict:
    """Объяснение для клиента. Всегда возвращает текст: от модели или шаблонный."""
    return await _write(facts(result, company_name), template_text(result, company_name),
                        SYSTEM_PROMPT)


# ---------------- 5. заключение для аналитика банка (клиент его не видит) ----------------

ANALYST_PROMPT = (
    "Ты помощник кредитного аналитика банка. По фактам решения напиши заключение для аналитика: "
    "почему выдача кредита обоснована для банка или почему нет. "
    "Структура: 1) вывод и рекомендация системы; 2) аргументы за выдачу; 3) риски; "
    "4) что проверить вручную. Профессиональный язык, коротко, 5–10 предложений или пунктов. "
    "Используй только факты из сообщения. Не придумывай чисел, причин и условий. "
    "Числа переписывай точно так же, как в фактах. Не меняй рекомендацию системы."
)

RECOMMENDATION = {
    "APPROVE": "выдать на запрошенных условиях",
    "COUNTER_OFFER": "выдать на изменённых условиях (меньше сумма или дольше срок), чтобы платёж был посильным",
    "ALTERNATIVE_PRODUCT": "выдать другой продукт: запрошенный не подходит по условиям",
    "MANUAL_REVIEW": "решение за аналитиком: скоринг допускает выдачу, но есть признаки для ручной проверки",
    "REQUEST_INFO": "не принимать решение до получения данных",
    "DECLINE": "не выдавать",
}

_FEATURES = {  # признак модели → подпись и формат для заключения
    "business_age_months": ("Срок бизнеса", lambda v: f"{v:g} мес."),
    "net_margin": ("Рентабельность", _pct),
    "revenue_trend": ("Динамика выручки к прошлому году", _pct),
    "revenue_volatility": ("Колебания оборотов", lambda v: f"{v:g}".replace(".", ",")),
    "debt_to_revenue": ("Текущий долг / выручка", _pct),
    "loan_to_revenue": ("Запрос / выручка", _pct),
    "dscr": ("DSCR на запрошенную сумму", lambda v: f"{v:g}".replace(".", ",")),
    "bki_max_overdue_days_12m": ("Макс. просрочка в БКИ за 12 мес.", lambda v: f"{v:g} дн."),
    "bki_overdue_count_12m": ("Число просрочек за 12 мес.", lambda v: f"{v:g}"),
    "bki_inquiries_3m": ("Запросы в БКИ за 3 мес.", lambda v: f"{v:g}"),
    "director_changes_12m": ("Смены директора за 12 мес.", lambda v: f"{v:g}"),
    "tax_arrears": ("Налоговый долг", lambda v: "есть" if v == "yes" else "нет"),
    "mass_address": ("Массовый адрес", lambda v: "да" if v == "yes" else "нет"),
}


def analyst_facts(result: dict, company_name: str) -> list[str]:
    lines = facts(result, company_name)
    lines.insert(2, f"Рекомендация системы: {RECOMMENDATION.get(result['decision'], result['decision_label'])}")
    feats = result.get("features") or {}
    for key, (label, f) in _FEATURES.items():
        if feats.get(key) is not None:
            lines.append(f"Показатель: {label} — {f(feats[key])}")
    source = {"fns_reporting": "бухотчётность (ФНС)", "statement": "выписка по счёту",
              "client": "со слов клиента"}.get(result.get("financials_source"), result.get("financials_source"))
    if source:
        lines.append(f"Источник финансовых данных: {source}")
    lines.append(f"Версия модели: {result.get('model_version')}, политика: {result.get('policy_version')}")
    return lines


def analyst_template(result: dict, company_name: str) -> str:
    risk = result.get("risk") or {}
    parts = [f"Вывод системы: {result['decision_label'].lower()}. "
             f"Рекомендация: {RECOMMENDATION.get(result['decision'], '—')}."]
    if risk.get("grade"):
        parts.append(f"Риск: грейд {risk['grade']}, PD {_pct(risk['pd'])}, балл {risk['score']}.")
    o = result.get("offer")
    if o and o.get("dscr") is not None:
        parts.append(f"Условия: {_rub(o['amount'])} на {o['term_months']} мес. под {_pct(o['rate'])}, "
                     f"платёж {_rub(o['monthly_payment'])}; DSCR {str(o['dscr']).replace('.', ',')} "
                     f"при минимуме 1,25.")
    pos = [r["text"] for r in result.get("reasons", []) if r["impact"] == "positive"]
    neg = [r["text"] for r in result.get("reasons", []) if r["impact"] == "negative"]
    parts.append(_list("За выдачу", pos) if pos else "За выдачу: сильных положительных факторов модель не выделила.")
    risks = neg + [c["name"] + (f" ({c['details']})" if c["details"] else "")
                   for c in result.get("checks", []) if c["status"] != "passed"]
    parts.append(_list("Риски", risks) if risks else "Риски: проверки пройдены, отрицательных факторов нет.")
    flags = result.get("manual_review_flags", [])
    parts.append(_list("Проверить вручную", flags) if flags else "Признаков для ручной проверки нет.")
    return "\n".join(parts)  # каждый блок с новой строки: аналитику так быстрее читать


async def explain_for_analyst(result: dict, company_name: str) -> dict:
    """Заключение для аналитика банка. Тот же принцип: модель или шаблон, числа сверяются."""
    return await _write(analyst_facts(result, company_name), analyst_template(result, company_name),
                        ANALYST_PROMPT)
