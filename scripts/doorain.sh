#!/usr/bin/env bash
# Управление DoorAIn (Linux/macOS/WSL/Git Bash). Поведение совпадает с scripts/doorain.ps1.
# Команды: init | doctor | prepare | start | stop | create-owner | backup | restore | export-bundle | import-bundle | logs
# Флаги:   --gpu --internet --native-ollama --project NAME --deep --encrypt --include-images --include-models --check-public
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CMD="${1:-help}"; shift || true
ARG=""; GPU=0; INTERNET=0; NATIVE=0; DEEP=0; ENCRYPT=0; INC_IMG=0; INC_MOD=0; CHECK_PUBLIC=0; PROJECT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --gpu) GPU=1;; --internet) INTERNET=1;; --native-ollama) NATIVE=1;; --deep) DEEP=1;; --encrypt) ENCRYPT=1;;
    --include-images) INC_IMG=1;; --include-models) INC_MOD=1;; --check-public) CHECK_PUBLIC=1;;
    --project) PROJECT="$2"; shift;;
    -*) echo "Неизвестный флаг $1" >&2; exit 2;;
    *) ARG="$1";;
  esac; shift
done

WARN=0; FAIL=0
ok()   { printf '\033[32m[ OK ]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[WARN]\033[0m %s\n' "$*"; WARN=$((WARN+1)); }
fail() { printf '\033[31m[FAIL]\033[0m %s\n' "$*"; FAIL=$((FAIL+1)); }

compose_args() {
  local a=(compose); [ -n "$PROJECT" ] && a+=(-p "$PROJECT"); a+=(-f compose.yaml)
  [ "$GPU" = 1 ] && a+=(-f compose.nvidia.yaml)
  [ "$INTERNET" = 1 ] && a+=(-f compose.internet.yaml)
  [ "$NATIVE" = 1 ] && a+=(-f compose.native-ollama.yaml)
  if [ -n "${DOORAIN_EXTRA_COMPOSE:-}" ]; then IFS=";" read -ra extra <<< "$DOORAIN_EXTRA_COMPOSE"; for x in "${extra[@]}"; do a+=(-f "$x"); done; fi
  printf '%s\n' "${a[@]}"
}
dc() { local a; mapfile -t a < <(compose_args); docker "${a[@]}" "$@"; }
env_value() { [ -f .env ] && grep -E "^$1=" .env | head -1 | cut -d= -f2- | tr -d '\r' || true; }
rand() { head -c "$1" /dev/urandom | base64 | tr -d '+/=\n' ; }

case "$CMD" in
  help) sed -n '2,4p' "${BASH_SOURCE[0]}";;

  init)
    if [ -f .env ]; then ok ".env уже существует — не перезаписываю"
    else
      sed -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rand 24)|" -e "s|^DOORAIN_SECRET_KEY=.*|DOORAIN_SECRET_KEY=$(rand 48)|" .env.example > .env
      chmod 600 .env; ok ".env создан со случайными секретами (в Git не попадает)"
    fi
    mkdir -p backups
    echo "Дальше: scripts/doorain.sh doctor ; prepare (нужен интернет) ; start ; create-owner <имя>";;

  doctor)
    echo "== Система"; echo "$(uname -srm); RAM: $(free -g 2>/dev/null | awk '/Mem:/{print $2" ГБ"}')"
    [ "$(uname -m)" = "x86_64" ] && ok "Архитектура x86-64" || fail "Нужна x86-64"
    free_gb=$(df -Pk "$ROOT" | awk 'NR==2{print int($4/1048576)}')
    [ "$free_gb" -lt 15 ] && warn "Свободно ${free_gb} ГБ: образы и модели занимают ~10–20 ГБ" || ok "Свободно на диске: ${free_gb} ГБ"
    echo "== Docker"
    command -v docker >/dev/null || { fail "Docker не найден"; exit 1; }
    docker info >/dev/null 2>&1 || { fail "Docker-демон недоступен"; exit 1; }
    ok "Docker $(docker version --format '{{.Server.Version}}'); Compose $(docker compose version --short)"
    echo "== Конфигурация"
    for k in POSTGRES_PASSWORD DOORAIN_SECRET_KEY; do [ -n "$(env_value $k)" ] && ok "$k задан" || fail "В .env не задан $k (scripts/doorain.sh init)"; done
    if [ "$INTERNET" = 1 ]; then d="$(env_value DOORAIN_DOMAIN)"; { [ -z "$d" ] || echo "$d" | grep -Eq 'example|your-domain'; } && fail "DOORAIN_DOMAIN не задан или placeholder" || ok "Домен: $d"; fi
    dc config --quiet >/dev/null 2>&1 && ok "compose config корректен" || fail "docker compose config: ошибка объединения файлов"
    pub=$(dc config --format json 2>/dev/null | python3 -c 'import json,sys; j=json.load(sys.stdin); print(" ".join(k for k,v in j["services"].items() if v.get("ports")))' 2>/dev/null || true)
    [ "$pub" = "web" ] && ok "Публикуется только web (Caddy)" || { [ -n "$pub" ] && fail "Порты публикуют: $pub"; }
    echo "== GPU"
    if command -v nvidia-smi >/dev/null; then nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
      docker info --format '{{json .Runtimes}}' | grep -q nvidia && ok "Docker видит runtime nvidia" || warn "Нет runtime nvidia: используйте CPU-профиль или установите NVIDIA Container Toolkit"
    else warn "nvidia-smi не найден: CPU-режим (медленно)"; fi
    if [ "$DEEP" = 1 ]; then
      echo "== Глубокая проверка (нужен запущенный стек)"
      probe() { printf '%s\n' "$2" | dc exec -T "$1" python -; }  # код передаётся через stdin
      probe api $'import urllib.request,sys\nsys.exit(0 if urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health/live", timeout=5).status==200 else 1)' && ok "API отвечает" || fail "API не отвечает"
      probe worker $'import urllib.request,sys\ntry:\n    urllib.request.urlopen("https://huggingface.co", timeout=5)\nexcept Exception:\n    sys.exit(0)\nprint("REACHABLE")\nsys.exit(1)' && ok "worker не имеет внешней сети" || fail "worker имеет выход в интернет (изоляция нарушена)"
      echo "Реальный inference (HTTP API Ollama из контейнера worker)…"
      probe worker $'import httpx,os\nr=httpx.post(os.environ["DOORAIN_OLLAMA_URL"]+"/api/generate", json={"model":os.environ["DOORAIN_OLLAMA_MODEL"],"prompt":"Reply with one word: yes","stream":False,"options":{"num_predict":8}}, timeout=600)\nr.raise_for_status()\nd=r.json()\nprint("response=%r eval_count=%s total_ms=%d" % (d.get("response","").strip()[:30], d.get("eval_count"), d.get("total_duration",0)//1000000))' && { ok "Модель отвечает"; dc exec -T ollama ollama ps; } || fail "Модель не ответила (выполните prepare)"
    fi    if [ "$CHECK_PUBLIC" = 1 ]; then echo "== Внешний адрес (явный запрос к api.ipify.org)"; echo "Публичный IP: $(curl -fsS --max-time 10 https://api.ipify.org || echo н/д); сверьте с WAN роутера (CGNAT?)"; fi
    echo; echo "Итог: ошибок $FAIL, предупреждений $WARN"; [ "$FAIL" -eq 0 ] || exit 1;;

  prepare)
    echo "Подготовка С ИНТЕРНЕТОМ: сборка образов и загрузка локальных моделей."
    [ -f .env ] || { echo "Сначала: scripts/doorain.sh init" >&2; exit 1; }
    dc build; dc pull postgres qdrant ollama
    dc -f compose.prepare.yaml --profile prepare run --rm fetch-hf-models
    dc -f compose.prepare.yaml --profile prepare run --rm pull-ollama-model
    ok "Готово. Дальше: start ; create-owner <имя>. Проверка изоляции: doctor --deep";;

  start)
    [ -f .env ] || { echo "Нет .env: scripts/doorain.sh init" >&2; exit 1; }
    dc up -d --no-build --pull never --wait
    port="$(env_value DOORAIN_HTTP_PORT)"; port="${port:-8080}"
    [ "$INTERNET" = 1 ] && ok "Запущено в интернет-режиме: https://$(env_value DOORAIN_DOMAIN)" || ok "Запущено: http://127.0.0.1:$port";;

  stop) dc stop; ok "Остановлено. Данные (volumes) сохранены.";;
  logs) dc logs --tail 200 -f;;

  create-owner)
    [ -n "$ARG" ] || { echo "Использование: doorain.sh create-owner <имя>" >&2; exit 2; }
    dc run --rm --no-deps api python -m app.cli create-owner --username "$ARG";;

  backup)
    id="$(date +%Y%m%d-%H%M%S)"; mkdir -p backups
    echo "Backup $id: останавливаю запись и активные задания…"
    dc exec -T api python -m app.ops backup-begin --id "$id"
    if dc exec -T postgres pg_dump -U doorain -Fc -f "/backups/$id.partial/db.dump" doorain && dc exec -T api python -m app.ops backup-finish --id "$id"; then :
    else dc exec -T api python -m app.ops backup-abort --id "$id" || true; echo "Backup не завершён (частичный набор удалён)" >&2; exit 1; fi
    if [ "$ENCRYPT" = 1 ]; then
      command -v gpg >/dev/null || { echo "Для --encrypt нужен gpg" >&2; exit 1; }
      tar -cf "backups/$id.tar" -C backups "$id"; gpg --symmetric --cipher-algo AES256 --output "backups/$id.tar.gpg" "backups/$id.tar"; rm "backups/$id.tar"
      ok "Зашифрованный архив: backups/$id.tar.gpg"
    fi
    ok "Backup готов: backups/$id. Он чувствителен: содержит хэш пароля и все данные.";;

  restore)
    [ -n "$ARG" ] || { echo "Использование: doorain.sh restore <backup-id> [--project имя]" >&2; exit 2; }
    [ -f "backups/$ARG/manifest.json" ] || { echo "Backup $ARG не найден или неполон" >&2; exit 1; }
    proj="${PROJECT:-doorain}"
    if [ -n "$(docker volume ls -q --filter "name=^${proj}_pgdata\$")" ]; then echo "Тома проекта '$proj' уже существуют: данные не перезаписываются. Укажите другой --project и DOORAIN_HTTP_PORT." >&2; exit 1; fi
    PROJECT="$proj"
    dc run --rm --no-deps api python -m app.ops verify --id "$ARG"
    dc up -d --no-build --pull never --wait postgres qdrant
    dc exec -T postgres pg_restore -U doorain -d doorain --no-owner --exit-on-error "/backups/$ARG/db.dump"
    dc run --rm --no-deps api python -m app.ops restore-verify --id "$ARG"
    dc up -d --no-build --pull never --wait
    ok "Восстановлено в проект '$proj'. Прежние web-сессии отозваны. Настройте домен/TLS на новом ПК.";;

  export-bundle)
    ts="$(date +%Y%m%d-%H%M%S)"; out="$ROOT/bundles/doorain-bundle-$ts"; mkdir -p "$out/docs"
    cp compose.yaml compose.nvidia.yaml compose.internet.yaml compose.native-ollama.yaml compose.prepare.yaml .env.example README.md "$out/"
    cp -r infra scripts "$out/"; cp docs/*.md "$out/docs/" 2>/dev/null || true
    if [ "$INC_IMG" = 1 ]; then
      imgs=(doorain/backend:0.1.0 doorain/web:0.1.0 $(python3 -c 'import json; d=json.load(open("infra/models.lock.json"))["images"]; print(" ".join(d[k] for k in ("postgres","qdrant","ollama")))'))
      docker save -o "$out/images.tar" "${imgs[@]}"
    fi
    if [ "$INC_MOD" = 1 ]; then
      for v in models ollama; do docker run --rm -v "${PROJECT:-doorain}_$v:/src:ro" -v "$out:/out" doorain/backend:0.1.0 tar -czf "/out/volume-$v.tar.gz" -C /src .; done
    fi
    (cd "$out" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum | sed 's|  \./|  |' > SHA256SUMS)
    printf 'Bundle DoorAIn %s\nСекреты (.env) и данные НЕ включены. Импорт: scripts/doorain import-bundle <каталог>.\n' "$ts" > "$out/README-BUNDLE.txt"
    ok "Bundle: $out";;

  import-bundle)
    [ -n "$ARG" ] || { echo "Использование: doorain.sh import-bundle <каталог>" >&2; exit 2; }
    b="$(cd "$ARG" && pwd)"; (cd "$b" && sha256sum -c --quiet SHA256SUMS) && ok "SHA-256 манифест проверен"
    [ -f "$b/images.tar" ] && docker load -i "$b/images.tar"
    for v in models ollama; do
      if [ -f "$b/volume-$v.tar.gz" ]; then vol="${PROJECT:-doorain}_$v"; docker volume create "$vol" >/dev/null
        docker run --rm -v "$vol:/dst" -v "$b:/in:ro" doorain/backend:0.1.0 tar -xzf "/in/volume-$v.tar.gz" -C /dst; fi
    done
    ok "Импорт завершён: build/pull/pip/npm install не выполнялись. Дальше: init ; start ; create-owner ; restore <id>";;

  *) echo "Неизвестная команда: $CMD" >&2; exit 2;;
esac
