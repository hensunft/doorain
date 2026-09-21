# Архитектура DoorAIn

Модульный монолит в одном репозитории. PostgreSQL и файлы документов — источник истины; Qdrant — **восстанавливаемый** поисковый индекс.

```text
Удалённый браузер ── HTTPS ──► Caddy (static UI + /api proxy, SSE без буферизации)
                                   │ внутренняя сеть Docker (internal: true)
                                   ▼
                                FastAPI ─── PostgreSQL 17: данные, задания, события, аудит
                                   ▲              ▲
                                   │              │
                                worker ───────────┘  (один процесс, одна тяжёлая задача за раз)
                                   ├── Ollama: локальная LLM
                                   ├── BGE-M3 (dense+sparse) + cross-encoder reranker (CPU)
                                   ├── Qdrant: индекс фрагментов
                                   └── файлы: оригиналы, нормализованный текст, PDF-экспорты
```

## Ответственность модулей (`backend/app`)

| Модуль | Роль |
|---|---|
| `api/` | REST под `/api/v1` + SSE. Все маршруты (кроме `health/live` и `auth/login`) требуют cookie-сессию; изменяющие — CSRF-токен. Владелец объекта проверяется в каждом запросе. |
| `auth/`, `core/security.py` | Один владелец, Argon2id, серверные сессии (в БД хэш токена), троттлинг входа в БД, доверие прокси по имени сервиса. |
| `db/` | SQLAlchemy 2, 31 таблица, Alembic (`migrations/0001`). JSONB — снимки/метаданные, связи — FK. Каскадное удаление сессии на уровне БД. |
| `services/ingestion` | Парсеры TXT/MD/HTML/PDF/DOCX → нормализация → чанкинг (статья→часть→пункт; учебник по разделам) → метаданные → неизменяемые редакции → `CorpusGeneration` (manifest, embeddings, контрольный поиск, атомарная активация) → сравнение редакций. |
| `services/rag` | Один запуск = путь сообщения: классификация → retrieval (dense+sparse RRF, точные статьи, rerank, бюджет токенов) → генерация блоками с серверной проверкой ссылок/цитат → финальная проверка → аналитика по JSON Schema. |
| `services/risks` | Шкала P×S, дедупликация по `(тип, сценарий, семейство нормы)`, однократный бонус P, снятие/повторное открытие, история. |
| `services/portrait` | Граф/хронология в PostgreSQL, раскладка для PDF. |
| `services/exports` | Снимок сессии → ReportLab PDF «Правовой слепок сессии» (без реплик; граф векторно по колонкам, матрица 5 × 5, основания из цитат ответов; цвета — `app/config/print.yaml`). |
| `providers/` | Границы с моделями: `ollama.py`, `embeddings.py` (BGE-M3, reranker), `vectorstore.py` (Qdrant), `testing.py` (**заглушки для тестов, маркируются в UI**). Облачного fallback нет. |
| `worker/` | Очередь заданий (`SELECT … FOR UPDATE SKIP LOCKED`), lease/heartbeat, повторы, отмена. |
| `ops.py` | Backup/restore/maintenance/загрузка моделей/smoke внутри образа. |

## Путь одного сообщения

1. `POST /sessions/{id}/messages` → идемпотентный `client_request_id`, фиксируются `session_version`, `as_of_date`, `corpus_generation`; `202 + run_id`. Одновременно в сессии — один run (`409 run_in_progress`).
2. Worker: health модели → классификация (JSON Schema, многотемная, без жёсткого фильтра) → поиск в **закреплённой** generation по редакциям, действующим на `as_of_date`.
3. Проверка достаточности (порог rerank + лексическая опора). Иначе — конкретный отказ (`out_of_scope`, `corpus_empty`, `revision_unavailable`, `insufficient_grounds`, `index_incompatible`).
4. Сервер присваивает `citation_id`; модель ссылается только на выданные маркеры `[C1]…`. Абзацы проверяются по мере генерации: неизвестный маркер, утверждение без ссылки, прямая цитата, которой нет в источнике → замена блока «Недостаточно данных». Финальная лексическая проверка может заменить блок событием `answer_block_replaced`.
5. `answer_completed` несёт канонический ответ и заменяет клиентский буфер. Отдельным вызовом — аналитика (JSON Schema, максимум один корректирующий повтор), затем одна транзакция: факты → риски → граф.
6. События (`status`, `answer_delta`, `answer_block_replaced`, `answer_completed`, `analysis_started`, `portrait_updated`, `risk_updated`, `completed|failed|cancelled`) хранятся в `job_events`; SSE отдаёт replay по `Last-Event-ID`; при потере — `snapshot`.

## Corpus generation

`CorpusGeneration` = неизменяемый manifest редакций (`generation_revisions`) + `embedding_fingerprint` (модель/ревизия/размерность/нормализация/prefix/max_length/версия чанкинга). Коллекция Qdrant — на fingerprint; фильтр поиска — по `revision_id` из manifest, поэтому неизменившиеся чанки не пересчитываются (`chunk_index`). Активная generation переключается атомарно после контрольного поиска; run закреплён за своей generation. Несовпадение fingerprint приложения и generation блокирует поиск (`index_incompatible`) до переиндексации.

## Надёжность

* Задания переживают рестарт: lease 90 с, heartbeat, до 3 попыток, идемпотентные ключи.
* Отказ worker посреди run: повторный запуск чистит частичные цитаты; `analysis_failed` не уничтожает проверенный ответ и не блокирует сессию; `POST /runs/{id}/analysis/retry` не создаёт дублей.
* Отмена и обрыв SSE различаются: закрытие вкладки не отменяет run.
