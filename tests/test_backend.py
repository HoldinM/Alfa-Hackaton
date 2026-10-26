"""Тесты бэкенда: связь с ML, машина статусов, история, ошибки.

Каждый тест проходит путь так же, как клиент в кабинете: через HTTP API.
"""

import pytest

API = "/api/v1"


def submit(client, company, **extra):
    body = {"inn": company["inn"], "consent_bki": True, **company["demo_request"], **extra}
    r = client.post(f"{API}/applications", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------- служебное и справочники ----------------

def test_health_reports_db_and_model(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["database"] is True
    assert body["ml_model"].startswith("msb-scorecard")


def test_pages_render(client):
    assert 'id="creditForm"' not in client.get("/").text  # старая форма удалена
    assert 'id="submitApp"' in client.get("/").text
    assert 'id="rows"' in client.get("/bank").text
    assert client.get("/static/cabinet.js").status_code == 200


def test_reference(client):
    assert {p["code"] for p in client.get(f"{API}/reference/products").json()} >= {"EXPRESS", "EQUIPMENT"}
    assert len(client.get(f"{API}/reference/purposes").json()) == 8


def test_company_card(client, demo):
    r = client.get(f"{API}/companies/{demo['approve']['inn']}")
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert client.get(f"{API}/companies/7701234567").status_code == 404


def test_recommendations_from_text(client, demo):
    r = client.post(f"{API}/recommendations", json={
        "inn": demo["approve"]["inn"], "purpose_text": "купить новую печь для пекарни",
        "requested_amount": 5_000_000, "term_months": 36})
    assert r.status_code == 200
    body = r.json()
    assert body["purpose"]["purpose"] == "equipment"
    assert body["recommendations"][0]["product_code"] == "EQUIPMENT"
    assert body["prescore"]["approval_chance"] == "высокий"


# ---------------- главное: решение приходит из ML ----------------

EXPECTED_STATUS = {
    "approve": "OFFER_READY",
    "counter_offer": "COUNTER_OFFER",
    "request_info": "INFO_REQUESTED",
    "manual_review": "MANUAL_REVIEW",
    "decline_stop": "DECLINED",
    "decline_risk": "DECLINED",
    "alternative_product": "ALTERNATIVE_OFFER",
}


@pytest.mark.parametrize("scenario", list(EXPECTED_STATUS))
def test_each_demo_scenario_gets_ml_decision(client, demo, scenario):
    app = submit(client, demo[scenario])
    assert app["status"] == EXPECTED_STATUS[scenario]
    assert app["assessment"]["decision"] == demo[scenario]["expected_decision"]
    assert app["assessment"]["model_version"].startswith("msb-scorecard")
    # история: создана клиентом → решение системы
    assert [e["to_status"] for e in app["events"]] == ["SUBMITTED", app["status"]]
    assert app["events"][1]["actor"] == "system"


def test_decline_shows_real_reasons_not_placeholders(client, demo):
    app = submit(client, demo["decline_risk"])
    texts = [r["text"] for r in app["assessment"]["reasons"]]
    assert any("Просрочки" in t for t in texts)
    assert app["assessment"]["risk"]["grade"] == "E"


def test_same_application_reloads_from_db(client, demo):
    app = submit(client, demo["counter_offer"])
    again = client.get(f"{API}/applications/{app['id']}").json()
    assert again["assessment"]["offers"] == app["assessment"]["offers"]
    assert again["status"] == "COUNTER_OFFER"


# ---------------- полный путь заявки ----------------

def test_offer_accept_and_sign(client, demo):
    app = submit(client, demo["counter_offer"])
    offer = app["assessment"]["offers"][0]
    app = client.post(f"{API}/applications/{app['id']}/accept", json={"offer_index": 0}).json()
    assert app["status"] == "OFFER_ACCEPTED"
    assert app["accepted_offer"]["amount"] == offer["amount"]
    assert app["actions"] == ["sign", "cancel"]
    app = client.post(f"{API}/applications/{app['id']}/sign").json()
    assert app["status"] == "ISSUED"
    assert app["actions"] == []


def test_info_requested_then_statement_rescored(client, demo):
    app = submit(client, demo["request_info"])
    assert app["assessment"]["missing_data"][0]["field"] == "statement_csv"
    csv = client.get(f"{API}/companies/{demo['request_info']['inn']}/demo-statement").text
    app = client.post(f"{API}/applications/{app['id']}/info",
                      json={"statement_csv": csv, "statement_filename": "vypiska.csv"}).json()
    assert app["status"] == "OFFER_READY"
    assert app["assessments_count"] == 2
    assert app["documents"][0]["filename"] == "vypiska.csv"
    assert [e["to_status"] for e in app["events"]] == [
        "SUBMITTED", "INFO_REQUESTED", "SUBMITTED", "OFFER_READY"]


def test_missing_consent_then_consent_given(client, demo):
    app = submit(client, demo["approve"], consent_bki=False)
    assert app["status"] == "INFO_REQUESTED"
    app = client.post(f"{API}/applications/{app['id']}/info", json={"consent_bki": True}).json()
    assert app["status"] == "OFFER_READY"


def test_analyst_approves_manual_review(client, demo):
    app = submit(client, demo["manual_review"])
    queue = client.get(f"{API}/bank/applications", params={"status": "MANUAL_REVIEW"}).json()
    assert app["id"] in [a["id"] for a in queue]
    r = client.post(f"{API}/bank/applications/{app['id']}/decision",
                    json={"approve": True, "comment": "Адрес проверен"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "OFFER_READY"
    assert body["events"][-1]["actor"] == "analyst"
    # после одобрения клиент может принять предварительные условия
    assert client.post(f"{API}/applications/{app['id']}/accept",
                       json={"offer_index": 0}).json()["status"] == "OFFER_ACCEPTED"


def test_history_by_inn(client, demo):
    inn = demo["alternative_product"]["inn"]
    submit(client, demo["alternative_product"])
    rows = client.get(f"{API}/applications", params={"inn": inn}).json()
    assert rows and all(r["inn"] == inn for r in rows)


# ---------------- ошибки и запреты ----------------

def test_cannot_accept_declined(client, demo):
    app = submit(client, demo["decline_stop"])
    r = client.post(f"{API}/applications/{app['id']}/accept", json={"offer_index": 0})
    assert r.status_code == 409
    assert r.json()["error"] == "invalid_action"


def test_cannot_cancel_issued(client, demo):
    app = submit(client, demo["approve"])
    client.post(f"{API}/applications/{app['id']}/accept", json={"offer_index": 0})
    client.post(f"{API}/applications/{app['id']}/sign")
    assert client.post(f"{API}/applications/{app['id']}/cancel").status_code == 409


def test_cancel_open_application(client, demo):
    app = submit(client, demo["approve"])
    body = client.post(f"{API}/applications/{app['id']}/cancel").json()
    assert body["status"] == "CANCELLED"


def test_analyst_only_for_manual_review(client, demo):
    app = submit(client, demo["approve"])
    r = client.post(f"{API}/bank/applications/{app['id']}/decision",
                    json={"approve": False, "comment": "Тест"})
    assert r.status_code == 409


def test_wrong_offer_index(client, demo):
    app = submit(client, demo["approve"])
    assert client.post(f"{API}/applications/{app['id']}/accept",
                       json={"offer_index": 5}).status_code == 409


def test_bad_statement_rejected_and_nothing_saved(client, demo):
    app = submit(client, demo["request_info"])
    r = client.post(f"{API}/applications/{app['id']}/info", json={"statement_csv": "foo;bar\n1;2\n"})
    assert r.status_code == 422
    again = client.get(f"{API}/applications/{app['id']}").json()
    assert again["status"] == "INFO_REQUESTED" and again["documents"] == []


@pytest.mark.parametrize("body,code", [
    ({"inn": "123", "purpose": "other", "requested_amount": 1, "term_months": 1}, 422),
    ({"inn": "7756405021", "purpose": "other", "requested_amount": -5, "term_months": 12}, 422),
    ({"inn": "7756405021", "purpose": "lambo", "requested_amount": 5, "term_months": 12}, 422),
    ({"inn": "7701234567", "purpose": "other", "requested_amount": 1_000_000, "term_months": 12}, 404),
])
def test_invalid_requests(client, body, code):
    r = client.post(f"{API}/applications", json=body)
    assert r.status_code == code
    assert "message" in r.json()


def test_unknown_application(client):
    assert client.get(f"{API}/applications/999999").status_code == 404


# ---------------- отзывы и метрики ----------------

def test_feedback_once_per_decision(client, demo):
    app = submit(client, demo["decline_risk"])
    r = client.post(f"{API}/applications/{app['id']}/feedback",
                    json={"decision_clear": False, "comment": "Не понял про грейд"})
    assert r.status_code == 200
    assert r.json()["feedback"] == {"decision_clear": False, "status": "DECLINED"}
    again = client.post(f"{API}/applications/{app['id']}/feedback", json={"decision_clear": True})
    assert again.status_code == 409


def test_ml_decision_time_is_recorded(client, demo):
    submit(client, demo["approve"])
    m = client.get(f"{API}/bank/metrics").json()
    timing = {x["key"]: x for g in m["groups"] for x in g["metrics"]}["ml_decision_time"]
    assert timing["value"] is not None and timing["value"] >= 0


def test_metrics_reflect_scenarios(client, demo):
    # к этому моменту тесты выше прошли все сценарии: выдачу, дозагрузку, аналитика, отказы
    approve = submit(client, demo["approve"])
    client.post(f"{API}/applications/{approve['id']}/feedback", json={"decision_clear": True})
    m = client.get(f"{API}/bank/metrics").json()
    assert m["applications_total"] > 0
    metrics = {x["key"]: x for g in m["groups"] for x in g["metrics"]}
    for key in ("offer_rate", "acceptance_rate", "issue_rate", "saved_from_decline",
                "info_completion", "decision_clarity", "auto_decision_rate",
                "analyst_approval_rate", "manual_review_time", "time_to_issue"):
        assert metrics[key]["value"] is not None, key
        assert metrics[key]["formula"] and metrics[key]["why"]
    assert 0 < metrics["saved_from_decline"]["value"] < 1
    assert metrics["decision_clarity"]["value"] < 1  # был ответ «нет»
    assert sum(d["count"] for d in m["decisions"]) == m["applications_total"]
    assert client.get("/metrics").status_code == 200


# ---------------- своя компания: данные вводит пользователь ----------------

OWN = {
    "name": "ООО «Моя пекарня»", "legal_form": "OOO", "industry": "food",
    "business_age_months": 48, "annual_revenue": 40_000_000, "net_margin": 0.12,
    "revenue_trend": 0.1,
}


def own_body(**extra):
    return {"company": {**OWN, **extra.pop("company", {})}, "purpose": "equipment",
            "requested_amount": 3_000_000, "term_months": 36, "consent_bki": True, **extra}


def test_own_company_without_inn_gets_synthetic_inn(client):
    r = client.post(f"{API}/applications", json=own_body())
    assert r.status_code == 201, r.text
    app = r.json()
    assert app["own_company"] is True
    assert app["company_name"] == "ООО «Моя пекарня»"
    assert len(app["inn"]) == 10 and app["inn"].isdigit()
    assert app["assessment"]["decision"] in {"APPROVE", "COUNTER_OFFER", "ALTERNATIVE"}
    assert app["assessment"]["offer"]["rate"] is not None
    # история по сгенерированному ИНН находит заявку
    rows = client.get(f"{API}/applications", params={"inn": app["inn"]}).json()
    assert [x["id"] for x in rows] == [app["id"]]


def test_own_company_data_changes_decision(client):
    good = client.post(f"{API}/applications", json=own_body()).json()
    bad = client.post(f"{API}/applications", json=own_body(
        company={"bki_max_overdue_days_12m": 120})).json()
    assert good["status"] != "DECLINED"
    assert bad["status"] == "DECLINED"
    liquidating = client.post(f"{API}/applications", json=own_body(
        company={"egrul_status": "liquidating"})).json()
    assert liquidating["status"] == "DECLINED"


def test_own_company_invalid_inn(client):
    r = client.post(f"{API}/applications", json=own_body(inn="1234567890"))
    assert r.status_code == 422
    assert "ИНН" in r.json()["message"]


def test_own_company_bad_values_rejected(client):
    assert client.post(f"{API}/applications",
                       json=own_body(company={"annual_revenue": -5})).status_code == 422
    assert client.post(f"{API}/applications",
                       json=own_body(company={"secret": 1})).status_code == 422


def test_need_inn_or_company(client):
    r = client.post(f"{API}/applications", json={
        "purpose": "equipment", "requested_amount": 1_000_000, "term_months": 12})
    assert r.status_code in (409, 422)


def test_recommendations_for_own_company(client):
    r = client.post(f"{API}/recommendations", json={
        "company": OWN, "purpose": "equipment", "requested_amount": 3_000_000, "term_months": 36})
    assert r.status_code == 200, r.text
    recs = r.json()["recommendations"]
    assert any(p["eligible"] for p in recs)
    assert all("estimated_overpayment" in p for p in recs if p["eligible"])


def test_industries_reference(client):
    codes = {i["code"] for i in client.get(f"{API}/reference/industries").json()}
    assert {"food", "it", "trade"} <= codes


# ---------------- объяснение решения простыми словами (ИИ или шаблон) ----------------

import json as _json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from app import explain as explainer
from app.settings import settings as app_settings


class FakeOllama:
    """Мини-сервер с тем же API, что у Ollama (/api/chat). Настоящую модель в тестах не качаем."""

    def __init__(self, answer: str):
        outer = self
        self.answer = answer
        self.requests: list[dict] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = _json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"path": self.path, **body})
                data = _json.dumps({"message": {"role": "assistant", "content": outer.answer}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def llm(monkeypatch):
    servers = []

    def start(answer):
        s = FakeOllama(answer)
        servers.append(s)
        monkeypatch.setattr(app_settings, "llm_url", s.url)
        return s
    yield start
    for s in servers:
        s.close()


def test_explain_without_llm_uses_template(client, demo, monkeypatch):
    monkeypatch.setattr(app_settings, "llm_url", "")
    app = submit(client, demo["decline_stop"])
    r = client.post(f"{API}/applications/{app['id']}/explain")
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["source"] == "template" and e["model"] is None and e["note"]
    assert e["decision"] == "DECLINE"
    assert "Не пройдены проверки" in e["text"]
    # сохраняется в заявке и не пересчитывается
    assert client.get(f"{API}/applications/{app['id']}").json()["assessment"]["explanation"]["text"] == e["text"]


def test_explain_with_llm(client, demo, llm):
    answer = ("Банк одобрил кредит: 5 000 000 ₽ на 36 мес. Ставка 18% — это базовая ставка "
              "продукта, надбавки за риск нет, потому что у компании грейд A.")
    fake = llm(answer)
    app = submit(client, demo["approve"])
    e = client.post(f"{API}/applications/{app['id']}/explain").json()
    assert e["source"] == "llm" and e["model"] == app_settings.llm_model
    assert e["text"] == answer
    sent = fake.requests[0]
    assert sent["path"] == "/api/chat" and sent["stream"] is False
    assert "Ставка: 18% годовых" in sent["messages"][1]["content"]
    # второй раз модель не вызываем — берём сохранённое
    client.post(f"{API}/applications/{app['id']}/explain")
    assert len(fake.requests) == 1


def test_explain_rejects_invented_numbers(client, demo, llm):
    llm("Банк одобрил кредит под 7% годовых, переплата всего 150 000 ₽.")
    app = submit(client, demo["approve"])
    e = client.post(f"{API}/applications/{app['id']}/explain").json()
    assert e["source"] == "template"
    assert "проверку чисел" in e["note"]


def test_explain_when_llm_down(client, demo, monkeypatch):
    monkeypatch.setattr(app_settings, "llm_url", "http://127.0.0.1:9")  # там никто не слушает
    monkeypatch.setattr(app_settings, "llm_timeout", 2.0)
    app = submit(client, demo["counter_offer"])
    e = client.post(f"{API}/applications/{app['id']}/explain").json()
    assert e["source"] == "template" and "недоступна" in e["note"]


def test_explain_unknown_application(client):
    assert client.post(f"{API}/applications/999999/explain").status_code == 404


def test_number_guard():
    facts = ["Ставка: 19% годовых", "Платёж в месяц: 505 487 ₽", "вероятность дефолта 1,2%"]
    assert explainer.unknown_numbers("Ставка 19%, платёж 505 487 ₽, риск 1,2%", facts) == set()
    assert explainer.unknown_numbers("Ставка 12%", facts) == {"12"}
    assert explainer.unknown_numbers("Есть 3 причины", facts) == set()  # мелкие счётные числа можно


# ---------------- заключение для аналитика банка (клиент его не видит) ----------------

def test_analyst_explanation_template(client, demo, monkeypatch):
    monkeypatch.setattr(app_settings, "llm_url", "")
    app = submit(client, demo["manual_review"])
    r = client.post(f"{API}/bank/applications/{app['id']}/explain")
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["source"] == "template" and e["decision"] == "MANUAL_REVIEW"
    assert "Рекомендация" in e["text"] and "Проверить вручную" in e["text"]
    assert any(f.startswith("Показатель: DSCR") for f in e["facts"])


def test_analyst_explanation_hidden_from_client(client, demo, monkeypatch):
    monkeypatch.setattr(app_settings, "llm_url", "")
    app = submit(client, demo["approve"])
    analyst = client.post(f"{API}/bank/applications/{app['id']}/explain").json()
    seen = client.get(f"{API}/applications/{app['id']}").text
    assert analyst["text"] not in seen and "Рекомендация системы" not in seen
    # клиентское объяснение — отдельное и без заключения для банка
    own = client.post(f"{API}/applications/{app['id']}/explain").json()
    assert own["text"] != analyst["text"]
    assert not any("Рекомендация системы" in f for f in own["facts"])


def test_analyst_explanation_with_llm(client, demo, llm):
    answer = ("Рекомендация: выдать на запрошенных условиях. Грейд A, DSCR 2,41 при минимуме 1,25. "
              "Рисков по проверкам нет.")
    fake = llm(answer)
    app = submit(client, demo["approve"])
    e = client.post(f"{API}/bank/applications/{app['id']}/explain").json()
    assert e["source"] == "llm" and e["text"] == answer
    assert "кредитного аналитика" in fake.requests[0]["messages"][0]["content"]
    client.post(f"{API}/bank/applications/{app['id']}/explain")
    assert len(fake.requests) == 1  # сохранено, второй раз модель не вызывается


def test_analyst_explanation_unknown(client):
    assert client.post(f"{API}/bank/applications/999999/explain").status_code == 404


# ---------------- раздел банка закрыт от клиента ----------------

@pytest.fixture
def anon(client):
    """Тот же сервер, но без входа сотрудника — как обычный клиент."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, follow_redirects=False)


def test_bank_api_requires_login(anon, demo):
    for method, path in (("GET", "/bank/applications"), ("GET", "/bank/metrics"),
                         ("POST", "/bank/applications/1/explain"),
                         ("POST", "/bank/applications/1/decision")):
        r = anon.request(method, API + path, json={"approve": True, "comment": "ок, проверено"})
        assert r.status_code == 401, path
        assert r.json()["error"] == "unauthorized"


def test_bank_pages_redirect_to_login(anon):
    for page in ("/bank", "/metrics"):
        r = anon.get(page)
        assert r.status_code == 303 and r.headers["location"] == f"/bank/login?next={page}"
    assert 'id="loginForm"' in anon.get("/bank/login").text


def test_login_wrong_password(anon):
    assert anon.post(f"{API}/bank/login", json={"password": "123"}).status_code == 401


def test_login_token_works_as_bearer(anon):
    token = anon.post(f"{API}/bank/login", json={"password": "alfa-analyst"}).json()["token"]
    anon.cookies.clear()
    r = anon.get(f"{API}/bank/applications", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    forged = token.split(".")[0] + ".deadbeef"
    assert anon.get(f"{API}/bank/applications",
                    headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_logout(anon):
    anon.post(f"{API}/bank/login", json={"password": "alfa-analyst"})
    assert anon.get(f"{API}/bank/applications").status_code == 200
    anon.post(f"{API}/bank/logout")
    anon.cookies.clear()
    assert anon.get(f"{API}/bank/applications").status_code == 401


def test_client_page_has_no_bank_links(anon):
    html = anon.get("/").text
    assert 'href="/bank"' not in html and 'href="/metrics"' not in html and 'href="/docs"' not in html


# ---------------- регрессии: сумма больше запроса и флаги мимо аналитика ----------------

def test_offer_never_exceeds_requested_amount(client, demo):
    r = client.post(f"{API}/applications", json={
        "inn": demo["manual_review"]["inn"], "consent_bki": True, "purpose": "working_capital",
        "product_code": "WORKING_CAPITAL", "requested_amount": 132_423, "term_months": 32})
    app = r.json()
    offers = (app["assessment"] or {}).get("offers") or []
    assert all(o["amount"] <= 132_423 for o in offers)
    assert app["status"] == "DECLINED"
    assert any("минимальн" in x["text"].lower() for x in app["assessment"]["reasons"])


def test_recommendations_do_not_raise_amount(client, demo):
    recs = client.post(f"{API}/recommendations", json={
        "inn": demo["approve"]["inn"], "purpose": "working_capital",
        "requested_amount": 132_423, "term_months": 32}).json()["recommendations"]
    assert all(p["suggested_amount"] <= 132_423 for p in recs)
    assert not any(p["eligible"] and p["product_code"] == "WORKING_CAPITAL" for p in recs)


def test_flags_go_to_analyst_even_with_other_terms(client, demo):
    # СтройМонтаж (массовый адрес) просит больше, чем посильно: раньше уходило клиенту
    # как «другие условия» мимо аналитика
    r = client.post(f"{API}/applications", json={
        "inn": demo["manual_review"]["inn"], "consent_bki": True, "purpose": "working_capital",
        "product_code": "WORKING_CAPITAL", "requested_amount": 30_000_000, "term_months": 12})
    app = r.json()
    assert app["status"] == "MANUAL_REVIEW"
    assert "Предварительное решение" in app["assessment"]["reasons"][0]["text"]
    decided = client.post(f"{API}/bank/applications/{app['id']}/decision",
                          json={"approve": True, "comment": "Адрес проверен"}).json()
    assert decided["status"] == "OFFER_READY"
    assert decided["assessment"]["offers"][0]["amount"] < 30_000_000
