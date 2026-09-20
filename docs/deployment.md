# Развёртывание

Docker Compose v2 — основной способ. Он фиксирует окружение приложения, но **не заменяет** драйвер GPU, WSL2, сеть, домен и резервное копирование.

## Требования

| Компонент | Windows (основной путь) | Linux (переносимый вариант — не проверялся на этой машине) |
|---|---|---|
| ОС / CPU | Windows 10/11 x86-64 | Linux x86-64 |
| Docker | Docker Desktop, Linux containers, WSL2 | Docker Engine + Compose plugin |
| GPU (необязательно) | NVIDIA + актуальный драйвер Windows (для WSL2) | драйвер + NVIDIA Container Toolkit |
| RAM / диск | 16 GB / ≥ 25 GB свободно (образы ≈ 3 GB, модели ≈ 6 GB) | то же |

Скрипты `scripts/doorain.ps1` (PowerShell) и `scripts/doorain.sh` (Bash) делают одно и то же. Ниже — PowerShell; для Linux замените флаги `-Gpu` на `--gpu` и т. д.

## Первый запуск (нужен интернет один раз)

```powershell
scripts\doorain.ps1 init            # создаёт .env со случайными секретами (существующий не трогает)
scripts\doorain.ps1 doctor          # ОС, Docker, память, диск, GPU, конфигурация, публикуемые порты
scripts\doorain.ps1 prepare -Gpu    # сборка образов + загрузка моделей (HF по закреплённым ревизиям, Ollama)
scripts\doorain.ps1 start -Gpu      # без build/pull: --no-build --pull never --wait
scripts\doorain.ps1 create-owner owner   # интерактивный ввод пароля (≥ 12 символов)
```

Откройте `http://127.0.0.1:8080`, войдите, перейдите в **«База знаний»** и импортируйте документы (`knowledge-base.md`).
`doctor -Deep` на запущенном стеке проверяет реальный inference (`ollama ps` покажет GPU/CPU), отсутствие внешней сети у worker и ответ API.

Ежедневный старт/остановка: `scripts\doorain.ps1 start` / `stop` (тома сохраняются; `down -v` вручную удаляет данные — скрипт этого не делает).

**Чистый старт (данные приложения — с нуля, модели сохраняются).** Владельца можно создать только один раз, поэтому после проверочных прогонов (учётная запись `smoke`, демо-данные) выполните вручную: `scripts\doorain.ps1 stop`, затем `docker volume rm doorain_pgdata doorain_data doorain_qdrant doorain_qdrant_snapshots`, затем `start` и `create-owner`. Тома `doorain_models` и `doorain_ollama` (загруженные модели) не удаляются — повторная загрузка не потребуется. Удаление необратимо: сначала `backup`, если в данных есть что-то нужное.

## Профили compose

| Файл | Назначение |
|---|---|
| `compose.yaml` | CPU, все сервисы, локальный адрес `127.0.0.1:8080`, сеть `internal` без выхода наружу |
| `compose.nvidia.yaml` | GPU-резервирование для Ollama |
| `compose.internet.yaml` | Caddy на 80/443, домен, TLS, production-параметры (см. `internet-access.md`) |
| `compose.native-ollama.yaml` | Запасной вариант: Ollama на хосте (`host.docker.internal`). Worker получает сеть с выходом на host — включайте осознанно, проверьте `OLLAMA_HOST` и брандмауэр |
| `compose.prepare.yaml` | Только для `prepare`: загрузка моделей в volumes через сеть `edge` |

Сервисы: `web` (Caddy + собранный UI), `api`, `worker`, `migrate` (одноразово, тот же образ), `postgres`, `qdrant`, `ollama`. Постоянные volumes: `pgdata`, `qdrant`, `qdrant_snapshots`, `data` (документы/экспорты), `models` (HF), `ollama`, `caddy_data`, `caddy_config`.

## Память и WSL2 (Windows)

Docker Desktop использует WSL2; по умолчанию VM получает до половины RAM (на 16 GB ≈ 8 GB). Ориентир для этого профиля — **8 GB** для WSL2 и запас Windows. Предлагаемый (не применяется автоматически) `%UserProfile%\.wslconfig`:

```diff
+ [wsl2]
+ memory=8GB
+ swap=4GB
```

Изменение действует на **все** WSL-дистрибутивы и применяется после `wsl --shutdown`. Мониторьте фактический пик (`docker stats`, диспетчер задач); постоянный swap thrashing — нерабочий профиль. Лимиты контейнеров заданы в `compose.yaml` (api 1 GB, worker 4 GB, postgres 768 MB, qdrant 768 MB).

Параметры модели: `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `num_ctx=4096`; BGE-M3 — CPU fp32, batch 2. Увеличение контекста до 8192 — только после измерения VRAM/RAM.

## Смена модели

1. В `.env`: `DOORAIN_OLLAMA_MODEL=<tag>`; загрузите модель при наличии интернета: `prepare`.
2. `scripts\doorain.ps1 start` (worker перечитает конфигурацию при пересоздании: `docker compose up -d worker`).
3. Сравните кандидатов последовательно (`evals/run_eval.py`); смена **embedding-модели или версии чанкинга** требует новой generation («Переиндексировать»); до этого поиск заблокирован (`index_incompatible`).

## Автозапуск и питание

* Контейнеры имеют `restart: unless-stopped`; включите автозапуск Docker Desktop с Windows и вход в учётную запись — иначе после перезагрузки сервис не поднимется (Docker Desktop зависит от пользовательской сессии). Для автономного сервера предпочтителен Linux + Docker Engine.
* Сон и гибернация останавливают сервис: настройте план электропитания сами (скрипты настройки питания не меняют). Для ноутбука-сервера держите питание от сети (GPU-профиль при работе от батареи троттлится).
* Обновление: пересоберите образы (`prepare`), выполните `backup`, затем `start`. Сертификаты Caddy продлевает автоматически (том `caddy_data` должен сохраняться).

## Наблюдаемые особенности

* При изменении сетевой конфигурации Compose (например, после обновления `compose.yaml`) выполните `docker compose down` (без `-v`) и `up`: иначе контейнеры могут потерять DNS-алиасы сервисов.
* `ollama` образ ≈ 3.5 GB (сжатый); модель `qwen3:4b-instruct-2507-q4_K_M` ≈ 2.5 GB; BGE-M3 ≈ 2.3 GB; reranker ≈ 0.5 GB.
