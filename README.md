# DoorAIn («Дориан»)

Локальный ИИ-агент по **праву высоких технологий**: ответы по закрытой базе знаний с проверяемыми источниками → накопительный **цифровой портрет** сессии (граф вопросов, норм и связей) → объяснимая **таблица рисков** и действия. Обработка (LLM, embeddings, reranking, поиск, PDF) и хранение выполняются на вашем сервере; доступ к результатам — по HTTPS с обязательным входом владельца.

> Ответы носят информационный характер и не заменяют профессиональную юридическую помощь. Методика оценки рисков экспериментальная и не проверена юристом.

## Быстрый старт (Windows + Docker Desktop, GPU NVIDIA — по желанию)

```powershell
scripts\doorain.ps1 init                 # .env со случайными секретами
scripts\doorain.ps1 doctor               # проверка ОС/Docker/памяти/диска/GPU/конфигурации
scripts\doorain.ps1 prepare -Gpu         # один раз, нужен интернет: образы и модели
scripts\doorain.ps1 start -Gpu           # http://127.0.0.1:8080
scripts\doorain.ps1 create-owner owner   # пароль вводится интерактивно
```

Пользователи добавляются по коду приглашения (публичной регистрации нет):

```powershell
docker compose -p doorain exec api python -m app.cli invite --note "Иван"
```

Затем «База знаний» → импорт проверенных документов (`docs/knowledge-base.md`). Linux/Bash: `scripts/doorain.sh` (те же команды, флаги `--gpu`, `--internet`). Подробно: `docs/deployment.md`.

Разработка: `cd backend && uv sync && uv run pytest`; `cd frontend && pnpm install && pnpm test && pnpm build`. Команды и инварианты — `CLAUDE.md`.

## Что внутри

React 19 + TypeScript (strict) + Vite + Tailwind 4 · FastAPI + SQLAlchemy 2 + Alembic · PostgreSQL 17 · Qdrant (dense+sparse) · Ollama · BGE-M3 + компактный cross-encoder (CPU) · worker с durable-заданиями в PostgreSQL · Caddy · Docker Compose.

```text
frontend/   UI (features/workspace: чат, граф React Flow, риски TanStack Table, источник)
backend/    API, worker, сервисы rag/ingestion/risks/portrait/exports, миграции, тесты, prompts
infra/      Dockerfile, Caddyfile, models.lock.json (ревизии моделей, digest образов)
scripts/    doorain.ps1 / doorain.sh: init, doctor, prepare, start, stop, backup, restore, bundle
evals/      датасет (74 кейса, calibration/holdout), раннер, шаблон экспертной разметки
knowledge_base/ манифест корпуса (слои, лицензии) и ручная загрузка НПА с pravo.gov.ru
tests/      e2e (Playwright), docker (стенд проверки)
docs/       product, architecture, decisions, security, access, risk-methodology, knowledge-base,
            deployment, internet-access, backup-restore, evaluation, design-system, skills-used, progress
```

## Статус готовности

Что реально проверено, а что нет — в **[docs/progress.md](docs/progress.md)** (таблица проверок и список невыполненного). Коротко: логика приложения, безопасность, PDF, UI, миграции на PostgreSQL 17, стек в Docker, backup→restore drill и изоляция сети проверены автоматически; качество ответов на **реальном юридическом корпусе и эксперт-валидация** требуют вашего корпуса и юриста; внешний доступ по HTTPS требует вашего домена и публичного IP.

Лицензии сторонних компонентов: Inter (SIL OFL, `frontend/public/fonts`), DejaVu (`backend/app/assets/fonts`), BGE-M3 (MIT), mmarco-mMiniLMv2 (Apache-2.0); лицензию модели Ollama проверьте по карточке перед загрузкой.
