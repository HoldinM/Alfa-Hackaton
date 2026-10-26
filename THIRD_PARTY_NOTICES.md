# Third-party notices

Перечень сторонних компонентов, моделей, данных и сервисов, которые использует решение,
и список смоделированных (поддельных) интеграций. Версии зафиксированы в `requirements.txt`
и `requirements-dev.txt`. Лицензии указаны по метаданным установленных пакетов.

## Смоделированные интеграции

Ни одна внешняя система банка или государства не вызывается. Все данные синтетические.

| Реальная система | Чем заменена | Где в коде |
|---|---|---|
| ЕГРЮЛ / ЕГРИП (статус компании, дата регистрации, ОКВЭД, руководитель) | мок по ИНН из `data/companies.json` | `src/credit_ml/mocks.py` |
| ФНС «Прозрачный бизнес», ГИР БО (налоговые долги, массовый адрес, отчётность) | тот же мок | `src/credit_ml/mocks.py` |
| Бюро кредитных историй (долги, просрочки, запросы) | тот же мок, выдаётся только при согласии клиента | `src/credit_ml/mocks.py` |
| Выписка по расчётному счёту | синтетические CSV в `data/statements/` | `src/credit_ml/statement.py` |
| Подписание договора и выдача денег | смена статуса заявки, без реальных операций | `src/app/services.py` |

## Модели и данные

| Компонент | Происхождение | Лицензия |
|---|---|---|
| Скоринговая модель `msb-scorecard 1.0.0` (`artifacts/model.joblib`) | обучена командой на синтетических данных | собственная разработка |
| Языковая модель **Qwen2.5-7B-Instruct** (тег Ollama `qwen2.5:7b-instruct`), 7,6 млрд параметров — в рамках ограничения кейса (не больше 120 млрд) | Alibaba Cloud, Qwen Team; не входит в репозиторий, Ollama скачивает её при первом запуске с `--profile ai` | Apache-2.0 |
| Обучающая выборка `data/train.csv` | сгенерирована скриптом `src/credit_ml/datagen.py` | собственная разработка |
| Демо-компании и выписки (`data/companies.json`, `data/statements/`) | сгенерированы тем же скриптом | собственная разработка |

LLM и платные внешние API не используются.

## Библиотеки для запуска (Python 3.13)

| Компонент | Версия | Лицензия | Назначение |
|---|---|---|---|
| fastapi | 0.161.1 | MIT | веб-фреймворк бэкенда |
| starlette | 1.9.0 | BSD-3-Clause | основа FastAPI |
| uvicorn | 0.54.0 | BSD-3-Clause | веб-сервер |
| pydantic | 2.14.1 | MIT | проверка данных запросов и ответов |
| pydantic-core | 2.50.1 | MIT | ядро pydantic |
| pydantic-settings | 2.16.1 | MIT | настройки из переменных окружения |
| python-dotenv | 1.2.4 | BSD-3-Clause | чтение файла .env |
| SQLAlchemy | 2.1.6 | MIT | работа с БД |
| asyncpg | 0.32.0 | Apache-2.0 | драйвер PostgreSQL |
| greenlet | 3.5.6 | MIT AND PSF-2.0 | асинхронный режим SQLAlchemy |
| alembic | 1.20.1 | MIT | миграции БД |
| Mako | 1.4.3 | MIT | шаблоны миграций Alembic |
| Jinja2 | 3.1.6 | BSD-3-Clause | HTML-шаблоны кабинета |
| MarkupSafe | 3.0.4 | BSD-3-Clause | экранирование в шаблонах |
| scikit-learn | 1.9.1 | BSD-3-Clause | логистическая регрессия, деревья, метрики |
| scipy | 1.18.1 | BSD-3-Clause | зависимость scikit-learn |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | вычисления |
| pandas | 3.1.0 | BSD-3-Clause | таблицы данных |
| joblib | 1.6.0 | BSD-3-Clause | сохранение и загрузка модели |
| threadpoolctl | 3.7.0 | BSD-3-Clause | зависимость scikit-learn |
| narwhals | 2.27.1 | MIT | зависимость scikit-learn |
| cloudpickle | 3.1.2 | BSD-3-Clause | зависимость joblib |
| anyio | 4.15.1 | MIT | асинхронный ввод-вывод |
| h11 | 0.16.0 | MIT | HTTP для uvicorn |
| click | 8.5.0 | BSD-3-Clause | командная строка uvicorn |
| idna | 3.20 | BSD-3-Clause | зависимость anyio |
| httpx | 0.28.1 | BSD-3-Clause | запросы к Ollama для ИИ-объяснения; тестовый клиент API |
| httpcore | 1.0.9 | BSD-3-Clause | зависимость httpx |
| certifi | 2026.10.19 | MPL-2.0 | сертификаты для httpx |
| annotated-doc | 0.0.5 | MIT | зависимость FastAPI |
| annotated-types | 0.8.0 | MIT | зависимость pydantic |
| typing-extensions | 4.16.0 | PSF-2.0 | зависимость pydantic и SQLAlchemy |
| typing-inspection | 0.4.4 | MIT | зависимость pydantic |
| opentelemetry-api | 1.45.1 | Apache-2.0 | зависимость FastAPI |
| python-dateutil | 3.0.0 | BSD (по метаданным пакета) | зависимость pandas |
| six | 1.17.0 | MIT | зависимость python-dateutil |
| tzdata | 2026.5 | Apache-2.0 | часовые пояса |

## Библиотеки только для разработки и тестов

| Компонент | Версия | Лицензия | Назначение |
|---|---|---|---|
| pytest | 9.1.1 | MIT | автотесты |
| aiosqlite | 0.21.0 | MIT | тесты на SQLite без PostgreSQL |
| playwright | 1.64.1 | Apache-2.0 | браузерный тест интерфейса |
| pytest-playwright | 0.10.0 | Apache-2.0 | интеграция Playwright с pytest |
| pandas-stubs | 3.0.5.260914 | BSD-3-Clause | подсказки типов pandas |
| types-pandas | 2.0.0 | в метаданных пакета не указана | подсказки типов pandas |
| matplotlib | 3.11.2 | PSF-based (Matplotlib License) | графики отчёта о модели; нужен только при переобучении, ставится отдельно |

## Инфраструктура и внешние ресурсы

| Компонент | Версия | Лицензия | Назначение |
|---|---|---|---|
| Docker-образ python | 3.13-slim | PSF-2.0 (Python) | среда запуска приложения |
| Docker-образ postgres | 15-alpine | PostgreSQL License | база данных |
| Docker-образ ollama/ollama | 0.9.0 | MIT | локальный запуск языковой модели (только с `--profile ai`) |
| Логотип Альфа-Будущее | — | принадлежит правообладателю | в репозиторий не входит; команда кладёт официальный файл в `src/app/static/brand/` |
| Шрифт Golos Text (Google Fonts) | — | SIL Open Font License 1.1 | шрифт кабинета; без интернета используется системный шрифт |
| Swagger UI (встроен в FastAPI, загружается браузером с CDN) | — | Apache-2.0 | страница `/docs` |
