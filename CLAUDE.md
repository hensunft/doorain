# DoorAIn — заметки для следующих сессий работы

Язык: пользовательская часть и документация — русский; идентификаторы — английский. Режим Ponytail `full`: минимум кода и зависимостей, без универсальных фреймворков; но не ценой авторизации, валидации, истории редакций, восстановления данных и тестов.

## Команды

```bash
# backend (uv, Python 3.12)
cd backend && uv sync && uv run pytest                 # 179 тестов, SQLite; на PostgreSQL: DOORAIN_TEST_DATABASE_URL=postgresql+psycopg://…  uv run pytest
uv run ruff check app tests && uv run mypy app
uv run alembic revision --autogenerate -m "…"          # только против PostgreSQL 17; затем alembic check
uv run python -m app.cli export-openapi --out ../frontend/openapi.json
# frontend (pnpm 12, Node 24)
cd frontend && pnpm install && pnpm typecheck && pnpm lint && pnpm test && pnpm build
pnpm gen:api                                           # openapi.json → src/lib/api-types.ts
pnpm e2e                                               # Playwright: поднимает backend/app/devserver.py (тестовые провайдеры, SQLite)
# стек
scripts/doorain.ps1|sh  init | doctor | prepare | start | stop | create-owner | backup | restore | export-bundle | import-bundle
python -m app.cli invite --note "для кого"             # код приглашения (регистрация только по нему); list-users
python -m app.cli kb doctor | search "<q>" --debug | add <файл|url> --license … | list | update | reindex | eval
python knowledge_base/fetch_pravo.py --tier start      # ручная загрузка НПА с pravo.gov.ru (вне рантайма)
DOORAIN_EXTRA_COMPOSE=tests/docker/compose.drill.yaml WITH_ML=0 scripts/doorain.ps1 start   # проверочный стенд без моделей
python evals/run_eval.py --user owner --split holdout   # DOORAIN_EVAL_PASSWORD в окружении
```

## Инварианты (не нарушать)

* Два уровня доступа: `owner` (база знаний, админка, диагностика) и `user` (только свои сессии). Публичной саморегистрации нет — только код приглашения; пароль владельца вводится интерактивно; секреты не в Git; production отклоняет слабую конфигурацию и `SINGLE_USER_MODE`.
* Изоляция проверяется в запросе к БД (`session_of`), а не скрытием кнопок; чужой объект отдаёт 404. Владелец видит чужие сессии, только если включён `DOORAIN_OWNER_CAN_READ_USER_SESSIONS`, и каждый просмотр пишется в журнал.
* Любой изменяющий запрос — cookie-сессия + `X-CSRF-Token` + проверка Origin; владелец объекта проверяется в каждом маршруте.
* PostgreSQL и файлы — источник истины; Qdrant восстанавливаем. Редакции неизменяемы; цитаты хранят снимок реквизитов и выдержки.
* Ссылки, реквизиты и даты подставляет сервер; модель выбирает только выданные `[C#]`; непроверенное заменяется «Недостаточно данных». Облачного fallback нет.
* Риск закрывается только через проверку ответа (`POST /risks/{id}/closure`, `services/risks/closure.py`): прямой PATCH `resolved/not_applicable` → 409, обход — только владелец с `override` и записью в журнал; «закрыт» по умолчанию = «со слов пользователя».
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
* Вердикт классификатора «вне области» — мягкий: снимается нормами со скором ≥ порог + `DOORAIN_SCOPE_OVERRIDE_MIN_SCORE`. Жёсткий отказ остаётся ниже `порог − DOORAIN_PARTIAL_ANSWER_MARGIN`; между ними ответ идёт с явной оговоркой о неполноте оснований.
* Манифест корпуса — `knowledge_base/manifest.yaml`; документ без `license` не индексируется. Перечень НПА для администратора — `docs/npa-knowledge-base.md` (сами акты автоматически не загружаются).
* Синтетические акты (`tests/fixtures/demo`) — только при `provider_mode=test`; из рабочей базы выводятся `kb retire-demo` (архив оснований, без удаления сообщений).
* Блок «Со слов пользователя» — только утверждение с предметом из слов пользователя (`verify.fact_has_subject/fact_grounded`): «нет.» → уточнение, непроизнесённое → допущение.
* Регистрация: логин неизменяем; e-mail уникален без регистра, меняется только с текущим паролем и письмом не подтверждается; код приглашения погашается атомарным UPDATE. Реквизиты оператора — `backend/app/config/legal.yaml` (пустые — «не заполнено», не выдумывать).
* Разделитель зон — `features/workspace/Splitter.tsx` (модульный компонент: вложенный в рендер тип пересоздаёт DOM и теряет pointer capture).
* Узлы карты (`GraphView`): React Flow прячет (`visibility: hidden`) каждый новый объект узла без `measured` до повторного замера — курсор «проваливается» на фон, и наведение мерцает. Размеры берутся из `onNodesChange` (`sizes`), позиции при перетаскивании — оттуда же; проверка — e2e «карта: неподвижный курсор…».
* Визуальный язык: интерфейс — стекло (`.glass`/`.glass-strong`: навигация, панель сессии, вкладки, меню, подсказки, диалоги; размытие только через `--glass-filter`, стекло в стекло не вкладывать), правовое содержание — твёрдое (`.zone`: диалог, карта, риски, формы). Тёмные блоки `tokens.css` совпадают построчно (тест). Знак-дверь — `DoorMark` (inline SVG цветом темы), не `<img src="/favicon.svg">`: внешний SVG не видит токены и пропадает в тёмной теме. Шкала риска — камень → бронза → бордовый → тёплый красный; текст уровня — только `--risk-*-ink`. Светлые цвета из `print.yaml` в `tokens.css` — строго `#rrggbb`.
* Vitest с `css: false` отдаёт `?raw` для `.css` пустой строкой — приёмочные тесты стилей молча ничего не проверяли; `test.css.include` в `vite.config.ts` открывает `src/styles/`.
* Класс `.overline` совпадает с утилитой Tailwind (`text-decoration: overline`): снято правилом вне слоёв в конце `index.css`. Анимации всплывающих элементов не масштабируют (`translate`, не `scale`): e2e «минимализм…» меряет зоны нажатия ≥ 44 px прямо во время анимации.
* Подсказки P/S — одно окно на интерфейс: активный значок хранится в модуле `components/PsInfo.tsx` (`setActive`), а не в экземпляре; тест гонки — `PsInfo.test.tsx`.
* Пороги уровней и лимит рисков — `backend/app/config/risk.yaml` (уровни в БД пересчитываются при старте API); цвета PDF — `backend/app/config/print.yaml`, тест сверяет их с `tokens.css`. Уровень во frontend — только `data-level`, без инлайновых цветов.
* В PDF не должно быть реплик диалога: вопросы подписываются номерами (`test_export_pdf_content_snapshot_and_auth`).
* Дата «сегодня» во фронтенде — `todayISO()` (`src/lib/date.ts`): `toISOString()` даёт UTC и до 03:00 по Москве подставляет вчерашний срез.
* Раздвижка узлов карты (`separate`) идёт по размерам из `onNodesChange` (`sizes`) на каждой пересборке раскладки; новый или изменившийся замер вызывает пересборку (иначе мини-карта пустая, а раздвижка считает по оценочному `BOX`). Качание весов — CSS-переменные, не состояние React: перерисовка узлов на каждом кадре вернула бы мерцание.
* Модель — GigaChat 3.1 Lightning из GGUF (`infra/models.lock.json` → `gguf`, `infra/ollama/*.Modelfile`; `prepare` кладёт файл в хранилище Ollama со сверкой sha256). `ollama pull hf.co/…` в Ollama 0.34 не работает (перенаправление на CDN). Ollama берёт шаблон диалога из GGUF, а не из Modelfile; его вступление (~1070 токенов) — `DOORAIN_OLLAMA_TEMPLATE_TOKENS`. На 8 GB Docker модель идёт только с `-Gpu`.
* Панель портрета на узкой раскладке скрыта `display: none`, React Flow меряет её нулём: карта вписывается заново по `ResizeObserver` (`GraphView`), проверка — в e2e «адаптивность…».

Подробности — `docs/` (architecture, decisions, security, risk-methodology, knowledge-base, deployment, internet-access, backup-restore, evaluation, design-system, progress).
