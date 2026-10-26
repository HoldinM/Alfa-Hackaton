"""Сквозной тест интерфейса в браузере (Playwright).

Нужен запущенный сервер, поэтому по умолчанию тест пропускается. Запуск:
    docker compose up -d
    E2E_BASE_URL=http://localhost:8000 uv run pytest tests/test_ui.py
"""

import os

import pytest

BASE = os.getenv("E2E_BASE_URL")
pytestmark = pytest.mark.skipif(not BASE, reason="задайте E2E_BASE_URL, чтобы запустить UI-тест")


def test_client_gets_decision_and_accepts_offer(page):
    from playwright.sync_api import expect

    page.goto(BASE + "/")
    expect(page).to_have_title("Кредитный кабинет предпринимателя")

    # 1. компания из демо-списка
    page.select_option("#demo", "7756405021")
    expect(page.locator("#companyCard")).to_contain_text("Пекарня")

    # 2. задача своими словами
    page.fill("#purposeText", "Хотим купить новую печь для пекарни")
    page.fill("#amount", "5000000")
    page.fill("#term", "36")
    page.click("#findProducts")

    # 3. первый подходящий продукт
    expect(page.locator("#purposeGuess")).to_contain_text("оборудование")
    page.locator("#products .product button").first.click()

    # 4. согласие и отправка
    page.check("#consent")
    page.click("#submitApp")

    # 5. решение ML и принятие условий
    expect(page.locator(".sheet .verdict")).to_have_text("Одобрено")
    page.click("[data-accept='0']")
    page.click("#signBtn")
    expect(page.locator(".sheet .verdict")).to_have_text("Кредит выдан")


def test_own_company_and_explanation(page):
    from playwright.sync_api import expect

    page.goto(BASE + "/")
    page.click("#tabOwn")
    page.fill("#ownName", "ООО «Тестовая пекарня»")
    page.select_option("#ownIndustry", "food")
    page.fill("#ownRevenue", "40000000")
    page.fill("#ownMargin", "12")
    page.click("#paneOwn button[type=submit]")
    expect(page.locator("#companyCard")).to_contain_text("свои данные")

    page.fill("#purposeText", "Купить новую печь")
    page.fill("#amount", "3000000")
    page.fill("#term", "36")
    page.click("#findProducts")
    page.locator("#step-product button[data-i]").first.click()
    expect(page.locator("#manualFin")).to_be_hidden()  # выручка уже введена в форме компании
    page.check("#consent")
    page.click("#submitApp")
    expect(page.locator(".verdict")).to_have_text("Одобрено")
    expect(page.locator(".sheet .terms").first).to_contain_text("базовая")

    page.click("#explainBtn")
    expect(page.locator(".explain-text")).to_be_visible()
    # техническую пометку («модель не подключена») клиент не видит
    expect(page.locator(".explain-text")).not_to_contain_text("LLM_URL")
