# DoorAIn — заметки для следующих сессий работы

Язык: пользовательская часть и документация — русский; идентификаторы — английский. Режим Ponytail `full`: минимум кода и зависимостей, без универсальных фреймворков; но не ценой авторизации, валидации, истории редакций, восстановления данных и тестов.

## Команды

```bash
# backend (uv, Python 3.12)
cd backend && uv sync && uv run pytest                 # 76+ тестов, SQLite; на PostgreSQL: DOORAIN_TEST_DATABASE_URL=postgresql+psycopg://…  uv run pytest
uv run ruff check app tests && uv run mypy app
uv run alembic revision --autogenerate -m "…"          # только против PostgreSQL 17; затем alembic check
uv run python -m app.cli export-openapi --out ../frontend/openapi.json
# frontend (pnpm 12, Node 24)
cd frontend && pnpm install && pnpm typecheck && pnpm lint && pnpm test && pnpm build
pnpm gen:api                                           # openapi.json → src/lib/api-types.ts
pnpm e2e                                               # Playwright: поднимает backend/app/devserver.py (тестовые провайдеры, SQLite)
# стек
scripts/doorain.ps1|sh  init | doctor | prepare | start | stop | create-owner | backup | restore | export-bundle | import-bundle
DOORAIN_EXTRA_COMPOSE=tests/docker/compose.drill.yaml WITH_ML=0 scripts/doorain.ps1 start   # проверочный стенд без моделей
python evals/run_eval.py --user owner --split holdout   # DOORAIN_EVAL_PASSWORD в окружении
```

## Инварианты (не нарушать)

* Единственный владелец; регистрации/setup-endpoint нет; пароль только интерактивно; секреты не в Git; production отклоняет слабую конфигурацию.
* Любой изменяющий запрос — cookie-сессия + `X-CSRF-Token` + проверка Origin; владелец объекта проверяется в каждом маршруте.
* PostgreSQL и файлы — источник истины; Qdrant восстанавливаем. Редакции неизменяемы; цитаты хранят снимок реквизитов и выдержки.
* Ссылки, реквизиты и даты подставляет сервер; модель выбирает только выданные `[C#]`; непроверенное заменяется «Недостаточно данных». Облачного fallback нет.
* Риск без нормативного основания не создаётся; S ≥ 3 только при источнике последствий; P≥4 — только при фактах пользователя; бонус P однократный и только за новый независимый факт; P=5 — только при «продолжающейся» ситуации. Повтор/retry/перефразирование P не повышают.
* Сбой аналитики не портит проверенный ответ и не блокирует сессию; retry без дублей.
* `internal: true` сеть; наружу только `web`; api/worker/БД/Ollama не публикуются. Restore — только в новые volumes.
* Тесты работают на TEST-провайдерах (`providers/testing.py`); их нельзя выдавать за проверку качества RAG. UI/PDF маркируют тестовый режим и демо-данные.

## Ловушки

* `.env` НЕ редактируйте вручную ради секретов в репозитории; `scripts init` генерирует значения.
* После смены compose-сети выполняйте `docker compose down` (без `-v`) + `up`: иначе пропадают DNS-алиасы сервисов.
* PowerShell 5.1: `.ps1` с кириллицей сохраняйте в UTF-8 **с BOM**; `$var:` в строках пишите `${var}:`.
* TypeScript закреплён на 5.9 (см. docs/decisions.md); react-table — v8.
* Мутируя `Message`/`GenerationRun`, помните о `session.version` и SSE-событиях (`job_events`).
* Пороги отказа (`DOORAIN_MIN_RERANK_SCORE`) не откалиброваны, пока не выполнена калибровка на `split=calibration` (docs/evaluation.md).

Подробности — `docs/` (architecture, decisions, security, risk-methodology, knowledge-base, deployment, internet-access, backup-restore, evaluation, design-system, progress).
