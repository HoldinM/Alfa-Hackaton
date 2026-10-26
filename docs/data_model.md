# Модель данных

Решение хранит данные в PostgreSQL в 6 таблицах. Схему создают миграции
`migrations/versions/0001_initial.py` … `0005_analyst_explanation.py`, описание в коде — `src/app/models.py`.

```mermaid
erDiagram
  companies ||--o{ applications : "подаёт"
  applications ||--o{ assessments : "оценивается ML"
  applications ||--o{ application_events : "меняет статус"
  applications ||--o{ documents : "получает документы"
  applications ||--o{ feedback : "получает отзыв клиента"

  companies {
    int id PK
    varchar inn UK "ИНН, 10 или 12 цифр"
    varchar name
    varchar legal_form "IP или OOO"
    varchar industry
    timestamptz created_at
  }
  applications {
    int id PK
    int company_id FK
    varchar purpose "код цели кредита"
    text purpose_text "цель словами клиента"
    varchar product_code "выбранный продукт"
    numeric requested_amount
    int term_months
    bool consent_bki
    json company_profile "своя компания: данные ввёл пользователь"
    json client_financials "выручка и рентабельность от клиента"
    varchar status "текущий статус заявки"
    json accepted_offer "принятый вариант условий"
    timestamptz created_at
    timestamptz updated_at
  }
  assessments {
    int id PK
    int application_id FK
    varchar decision "решение ML"
    varchar next_status
    int score "балл"
    float pd "вероятность дефолта"
    varchar grade "A-E"
    bool requires_manual_review
    varchar model_version
    varchar policy_version
    int duration_ms "время решения ML"
    json result "полный ответ ML"
    json explanation "объяснение простыми словами для клиента"
    json analyst_explanation "заключение для аналитика, клиенту не отдаётся"
    timestamptz created_at
  }
  application_events {
    int id PK
    int application_id FK
    varchar from_status
    varchar to_status
    varchar actor "client, system, analyst"
    text comment
    timestamptz created_at
  }
  documents {
    int id PK
    int application_id FK
    varchar kind "bank_statement"
    varchar filename
    text content
    timestamptz created_at
  }
  feedback {
    int id PK
    int application_id FK
    varchar status "статус решения, на которое ответил клиент"
    bool decision_clear "понятно ли решение"
    text comment
    timestamptz created_at
  }
```

## Таблицы

| Таблица | Что хранит | Когда появляется запись |
|---|---|---|
| `companies` | компания-заявитель: ИНН, название, форма, отрасль | при первой заявке компании; данные берутся из мока ЕГРЮЛ |
| `applications` | заявка: что просит клиент и текущий статус; для своей компании — введённые данные (`company_profile`) | клиент нажал «Отправить заявку» |
| `assessments` | каждый прогон заявки через ML: решение, балл, грейд, полный ответ модели; объяснение простыми словами (`explanation`) | при подаче заявки и после каждой дозагрузки данных; `explanation` — когда клиент нажал «Объяснить» |
| `application_events` | история статусов: из какого в какой, кто и почему | при каждой смене статуса |
| `documents` | документы клиента (выписка по счёту) | клиент загрузил выписку |
| `feedback` | ответ клиента «понятно ли, почему банк так решил» | клиент ответил на вопрос под решением |

## Почему так

- **Оценок у заявки может быть несколько.** Например, сначала «нужны данные», а после выписки — «одобрено». Старые оценки не перезаписываются, поэтому видно, как менялось решение.
- **История статусов — отдельная таблица.** Так всегда понятно, кто перевёл заявку (клиент, система или аналитик), когда и с каким комментарием. Это нужно для аудита.
- **Полный ответ ML хранится в `assessments.result`.** Экран показывает решение ровно таким, каким его выдала модель в тот момент, даже если модель потом обновится. Ключевые поля (балл, PD, грейд, версия модели) вынесены в колонки для поиска и отчётов.
- **Своя компания хранится в заявке (`applications.company_profile`).** При дозагрузке данных заявка пересчитывается на тех же введённых цифрах. В `companies` для неё только ИНН и название.
- **Объяснение привязано к оценке (`assessments.explanation`).** Новое решение — новое объяснение. Внутри: текст, кто написал (`llm` или `template`), модель и список фактов, которые видела модель. Заключение для аналитика лежит в отдельной колонке `analyst_explanation`, чтобы клиентский API его не отдавал.
- **Суммы — `numeric(14, 2)`,** а не дробные числа: деньги не должны терять копейки при округлении.
- **Удаление каскадное:** при удалении заявки удаляются её оценки, история и документы.

## Что лежит в `assessments.result`

Ответ ML-модуля по схеме `AssessResponse` (`src/credit_ml/schemas.py`). Главные поля:

| Поле | Содержание |
|---|---|
| `decision`, `decision_label` | решение: APPROVE, COUNTER_OFFER, ALTERNATIVE_PRODUCT, REQUEST_INFO, MANUAL_REVIEW, DECLINE |
| `offer`, `offers` | предложенные условия: продукт, сумма, срок, ставка, платёж, DSCR |
| `risk` | балл, вероятность дефолта, грейд |
| `reasons`, `advice` | причины решения и советы клиенту |
| `checks` | результат каждой проверки (статус в ЕГРЮЛ, БКИ, стоп-факторы, скоринг, DSCR) |
| `missing_data` | каких данных не хватает |
| `manual_review_flags` | почему нужна ручная проверка |
| `features` | признаки, на которых считала модель |

Статусы заявки и переходы между ними — в README, раздел «Статусы заявки».
