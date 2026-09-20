<#
.SYNOPSIS  Управление DoorAIn (Windows/PowerShell). Поведение совпадает с scripts/doorain.sh.
.EXAMPLE   scripts\doorain.ps1 init ; doctor ; prepare ; start ; create-owner owner
.NOTES     Команды: init | doctor | prepare | start | stop | create-owner | backup | restore | export-bundle | import-bundle | logs
           Флаги:   -Gpu  -Internet  -NativeOllama  -Project <имя>  -Deep  -Encrypt  -IncludeImages  -IncludeModels
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0)][ValidateSet('init', 'doctor', 'prepare', 'start', 'stop', 'create-owner', 'backup', 'restore', 'export-bundle', 'import-bundle', 'logs', 'help')][string]$Command = 'help',
  [Parameter(Position = 1)][string]$Arg,
  [switch]$Gpu, [switch]$Internet, [switch]$NativeOllama, [switch]$Deep, [switch]$Encrypt, [switch]$IncludeImages, [switch]$IncludeModels, [switch]$CheckPublic,
  [string]$Project = ''
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Say($m) { Write-Host $m }
function Ok($m) { Write-Host "[ OK ] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[WARN] $m" -ForegroundColor Yellow; $script:warnings++ }
function Fail($m) { Write-Host "[FAIL] $m" -ForegroundColor Red; $script:failures++ }
$script:warnings = 0; $script:failures = 0

function Run([string]$exe, [string[]]$rest) {
  & $exe @rest
  if ($LASTEXITCODE -ne 0) { throw "Команда завершилась с кодом ${LASTEXITCODE}: $exe $($rest -join ' ')" }
}
function ComposeArgs {
  $a = @('compose')
  if ($Project) { $a += @('-p', $Project) }
  $a += @('-f', 'compose.yaml')
  if ($Gpu) { $a += @('-f', 'compose.nvidia.yaml') }
  if ($Internet) { $a += @('-f', 'compose.internet.yaml') }
  if ($NativeOllama) { $a += @('-f', 'compose.native-ollama.yaml') }
  if ($env:DOORAIN_EXTRA_COMPOSE) { foreach ($x in ($env:DOORAIN_EXTRA_COMPOSE -split ';')) { $a += @('-f', $x) } }  # проверочные оверрайды (CI/drill)
  return $a
}
function Compose([string[]]$rest) { $a = ComposeArgs; Run 'docker' ($a + $rest) }
function ComposeQuiet([string[]]$rest) { $a = ComposeArgs; & docker @a @rest; return $LASTEXITCODE }
function EnvValue([string]$k) {
  if (-not (Test-Path .env)) { return '' }
  $l = Select-String -Path .env -Pattern "^\s*$k=(.*)$" | Select-Object -First 1
  if ($l) { return $l.Matches[0].Groups[1].Value.Trim() } else { return '' }
}
function RandomSecret([int]$bytes = 32) {
  $b = New-Object byte[] $bytes; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
  return ([Convert]::ToBase64String($b) -replace '[+/=]', 'x')
}

switch ($Command) {
  'help' { Get-Help $PSCommandPath -Full | Out-String | Write-Host }

  'init' {
    if (Test-Path .env) { Ok '.env уже существует — не перезаписываю'; }
    else {
      $t = Get-Content .env.example -Raw
      $t = $t -replace '(?m)^POSTGRES_PASSWORD=.*$', "POSTGRES_PASSWORD=$(RandomSecret 24)"
      $t = $t -replace '(?m)^DOORAIN_SECRET_KEY=.*$', "DOORAIN_SECRET_KEY=$(RandomSecret 48)"
      [IO.File]::WriteAllText((Join-Path $Root '.env'), $t, (New-Object Text.UTF8Encoding($false)))
      Ok '.env создан со случайными секретами (в Git не попадает)'
    }
    New-Item -ItemType Directory -Force backups | Out-Null
    Say 'Дальше: scripts\doorain.ps1 doctor ; prepare (нужен интернет) ; start ; create-owner <имя>'
  }

  'doctor' {
    Say '== Система'
    $os = Get-CimInstance Win32_OperatingSystem
    Say ("{0} {1} {2}; RAM {3:N1} ГБ (свободно {4:N1}); CPU {5}" -f $os.Caption, $os.Version, $os.OSArchitecture, ($os.TotalVisibleMemorySize / 1MB), ($os.FreePhysicalMemory / 1MB), (Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name))
    if ($os.OSArchitecture -notmatch '64') { Fail 'Нужна 64-разрядная ОС (x86-64)' } else { Ok 'Архитектура x86-64' }
    $free = (Get-PSDrive -Name (Split-Path -Qualifier $Root).TrimEnd(':')).Free / 1GB
    if ($free -lt 15) { Warn ("Свободно {0:N1} ГБ на диске проекта: образы и модели занимают ~10–20 ГБ" -f $free) } else { Ok ("Свободно на диске: {0:N1} ГБ" -f $free) }
    if (($os.TotalVisibleMemorySize / 1MB) -lt 15) { Warn 'Менее 16 ГБ RAM: профиль laptop-16gb-6gb не гарантирован' }
    Say '== Docker'
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Fail 'Docker не найден. Установите Docker Desktop (Linux containers, WSL2)'; break }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { Fail 'Docker-демон недоступен: запустите Docker Desktop'; break }
    Ok ("Docker {0}; Compose {1}" -f (docker version --format '{{.Server.Version}}'), (docker compose version --short))
    $mem = [math]::Round([double](docker info --format '{{.MemTotal}}') / 1GB, 1)
    if ($mem -lt 7) { Warn "Docker/WSL2 видит $mem ГБ RAM. Ориентир — 8 ГБ. Предлагаемый %UserProfile%\.wslconfig (НЕ применяется автоматически):`n  [wsl2]`n  memory=8GB`n  swap=4GB`n  Влияет на все WSL-дистрибутивы; применяется после 'wsl --shutdown'." } else { Ok "Память Docker/WSL2: $mem ГБ" }
    Say '== Конфигурация'
    foreach ($k in 'POSTGRES_PASSWORD', 'DOORAIN_SECRET_KEY') { if (-not (EnvValue $k)) { Fail "В .env не задан $k (scripts\doorain.ps1 init)" } else { Ok "$k задан" } }
    if ($Internet) {
      $d = EnvValue 'DOORAIN_DOMAIN'
      if (-not $d -or $d -match 'example|your-domain') { Fail 'DOORAIN_DOMAIN не задан или placeholder' } else { Ok "Домен: $d" }
    }
    $code = ComposeQuiet @('config', '--quiet')
    if ($code -ne 0) { Fail 'docker compose config: ошибка объединения файлов' } else { Ok 'compose config корректен' }
    $cfg = (ComposeArgs) + @('config', '--format', 'json')
    try {
      $j = (& docker @cfg) | ConvertFrom-Json
      $pub = @($j.services.PSObject.Properties | Where-Object { $_.Value.ports } | ForEach-Object { $_.Name })
      if (($pub | Where-Object { $_ -ne 'web' }).Count -gt 0) { Fail "Порты публикуют не только web: $($pub -join ', ')" } else { Ok 'Публикуется только web (Caddy)' }
      foreach ($s in 'api', 'worker', 'postgres', 'qdrant', 'ollama') { $nets = @($j.services.$s.networks.PSObject.Properties.Name); if ($nets -contains 'edge') { Fail "$s подключён к edge-сети" } }
    } catch { Warn 'Не удалось разобрать effective config' }
    Say '== GPU'
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
      Say (nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader)
      $rt = docker info --format '{{json .Runtimes}}'
      if ($rt -match 'nvidia') { Ok 'Docker видит runtime nvidia' } else { Warn 'Docker не видит runtime nvidia: GPU-профиль недоступен (используйте CPU)' }
    } else { Warn 'nvidia-smi не найден: работа в CPU-режиме (медленно)' }
    if ($Deep) {
      Say '== Глубокая проверка (нужен запущенный стек)'
      function Probe([string]$svc, [string]$code) { $a = ComposeArgs; $out = $code | & docker @a exec -T $svc python - ; $rc = $LASTEXITCODE; $out | ForEach-Object { Write-Host "    $_" }; return $rc }  # код — через stdin; вывод не смешивается с кодом возврата
      if ((Probe 'api' "import urllib.request,sys`nsys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=5).status==200 else 1)") -eq 0) { Ok 'API отвечает' } else { Fail 'API не отвечает' }
      if ((Probe 'worker' "import urllib.request,sys`ntry:`n    urllib.request.urlopen('https://huggingface.co', timeout=5)`nexcept Exception:`n    sys.exit(0)`nprint('REACHABLE')`nsys.exit(1)") -eq 0) { Ok 'worker не имеет внешней сети (изоляция internal)' } else { Fail 'worker имеет выход в интернет (изоляция нарушена)' }
      Say 'Реальный inference (HTTP API Ollama из контейнера worker)…'
      $infer = "import httpx,os,sys`nr=httpx.post(os.environ['DOORAIN_OLLAMA_URL']+'/api/generate', json={'model':os.environ['DOORAIN_OLLAMA_MODEL'],'prompt':'Reply with one word: yes','stream':False,'options':{'num_predict':8}}, timeout=600)`nr.raise_for_status()`nd=r.json()`nprint('response=%r eval_count=%s total_ms=%d' % (d.get('response','').strip()[:30], d.get('eval_count'), d.get('total_duration',0)//1000000))"
      if ((Probe 'worker' $infer) -eq 0) { Ok 'Модель отвечает'; Compose @('exec', '-T', 'ollama', 'ollama', 'ps') } else { Fail 'Модель не ответила (выполните prepare)' }
    }    if ($CheckPublic) {
      Say '== Внешний адрес (явный запрос к api.ipify.org)'
      try { $ip = (Invoke-RestMethod 'https://api.ipify.org' -TimeoutSec 10); Say "Публичный IP: $ip; сверьте с WAN-адресом роутера: если они различаются — вероятно CGNAT (см. docs/internet-access.md)" } catch { Warn 'Не удалось определить публичный IP' }
      $d = EnvValue 'DOORAIN_DOMAIN'; if ($d) { try { Say ("DNS {0}: {1}" -f $d, ((Resolve-DnsName $d -ErrorAction Stop | Where-Object { $_.IPAddress } | ForEach-Object IPAddress) -join ', ')) } catch { Warn "Домен $d не разрешается" } }
    }
    Say ("`nИтог: ошибок {0}, предупреждений {1}" -f $script:failures, $script:warnings)
    if ($script:failures) { exit 1 }
  }

  'prepare' {
    Say 'Подготовка С ИНТЕРНЕТОМ: сборка образов и загрузка локальных моделей. После неё стек работает автономно.'
    if (-not (Test-Path .env)) { throw 'Сначала: scripts\doorain.ps1 init' }
    Compose @('build')
    Compose @('pull', 'postgres', 'qdrant', 'ollama')
    $a = (ComposeArgs) + @('-f', 'compose.prepare.yaml', '--profile', 'prepare')
    Run 'docker' ($a + @('run', '--rm', 'fetch-hf-models'))
    Run 'docker' ($a + @('run', '--rm', 'pull-ollama-model'))
    Ok 'Готово. Дальше: start ; create-owner <имя> ; загрузка корпуса в интерфейсе. Проверка изоляции: doctor -Deep'
  }

  'start' {
    if (-not (Test-Path .env)) { throw 'Нет .env: scripts\doorain.ps1 init' }
    Compose @('up', '-d', '--no-build', '--pull', 'never', '--wait')  # без сборки и скачивания
    $port = EnvValue 'DOORAIN_HTTP_PORT'; if (-not $port) { $port = '8080' }
    if ($Internet) { Ok "Запущено в интернет-режиме: https://$(EnvValue 'DOORAIN_DOMAIN')" } else { Ok "Запущено: http://127.0.0.1:$port" }
  }

  'stop' { Compose @('stop'); Ok 'Остановлено. Данные (volumes) сохранены.' }

  'logs' { Compose @('logs', '--tail', '200', '-f') }

  'create-owner' {
    if (-not $Arg) { throw 'Использование: doorain.ps1 create-owner <имя>' }
    Compose @('run', '--rm', '--no-deps', 'api', 'python', '-m', 'app.cli', 'create-owner', '--username', $Arg)
  }

  'backup' {
    $id = Get-Date -Format 'yyyyMMdd-HHmmss'
    New-Item -ItemType Directory -Force backups | Out-Null
    Say "Backup ${id}: останавливаю запись и активные задания…"
    Compose @('exec', '-T', 'api', 'python', '-m', 'app.ops', 'backup-begin', '--id', $id)
    try {
      Compose @('exec', '-T', 'postgres', 'pg_dump', '-U', 'doorain', '-Fc', '-f', "/backups/$id.partial/db.dump", 'doorain')  # файл создаётся внутри контейнера
      Compose @('exec', '-T', 'api', 'python', '-m', 'app.ops', 'backup-finish', '--id', $id)
    } catch {
      ComposeQuiet @('exec', '-T', 'api', 'python', '-m', 'app.ops', 'backup-abort', '--id', $id) | Out-Null
      throw "Backup не завершён (частичный набор удалён): $_"
    }
    if ($Encrypt) {
      if (-not (Get-Command gpg -ErrorAction SilentlyContinue)) { throw 'Для -Encrypt нужен gpg' }
      Run 'tar' @('-cf', "backups/$id.tar", '-C', 'backups', $id)
      Run 'gpg' @('--symmetric', '--cipher-algo', 'AES256', '--output', "backups/$id.tar.gpg", "backups/$id.tar")
      Remove-Item "backups/$id.tar"; Ok "Зашифрованный архив: backups\$id.tar.gpg (расшифруйте gpg перед restore)"
    }
    Ok "Backup готов: backups\$id (manifest.json, db.dump, files.tar.gz, Qdrant snapshots). Backup — чувствителен: содержит хэш пароля и все данные."
  }

  'restore' {
    if (-not $Arg) { throw 'Использование: doorain.ps1 restore <backup-id> [-Project имя]  (восстановление всегда в НОВЫЕ volumes)' }
    $bdir = Join-Path $Root "backups/$Arg"
    if (-not (Test-Path "$bdir/manifest.json")) { throw "Backup $Arg не найден или неполон (нет manifest.json)" }
    $proj = if ($Project) { $Project } else { 'doorain' }
    $existing = docker volume ls -q --filter "name=^${proj}_pgdata$"
    if ($existing) { throw "Тома проекта '$proj' уже существуют: данные не перезаписываются. Укажите другой -Project (например doorain_restore) и другой DOORAIN_HTTP_PORT." }
    $Project = $proj
    try {
    Say "Проверка целостности backup…"
    Compose @('run', '--rm', '--no-deps', 'api', 'python', '-m', 'app.ops', 'verify', '--id', $Arg)
    Compose @('up', '-d', '--no-build', '--pull', 'never', '--wait', 'postgres', 'qdrant')
    Compose @('exec', '-T', 'postgres', 'pg_restore', '-U', 'doorain', '-d', 'doorain', '--no-owner', '--exit-on-error', "/backups/$Arg/db.dump")
    Compose @('run', '--rm', '--no-deps', 'api', 'python', '-m', 'app.ops', 'restore-verify', '--id', $Arg)
    Compose @('up', '-d', '--no-build', '--pull', 'never', '--wait')
    Ok "Восстановлено в проект '$proj'. Прежние web-сессии отозваны. Проверьте вход, настройте домен/TLS на новом ПК."
    } catch { Write-Host "Восстановление прервано: $_
Новые тома проекта '$proj' оставлены для анализа; прежние данные не затронуты. Для повторной попытки: docker compose -p $proj down -v" -ForegroundColor Red; exit 1 }
  }

  'export-bundle' {
    $ts = Get-Date -Format 'yyyyMMdd-HHmmss'
    $out = Join-Path $Root "bundles/doorain-bundle-$ts"
    New-Item -ItemType Directory -Force $out | Out-Null
    foreach ($f in 'compose.yaml', 'compose.nvidia.yaml', 'compose.internet.yaml', 'compose.native-ollama.yaml', 'compose.prepare.yaml', '.env.example', 'README.md') { Copy-Item $f $out }
    Copy-Item infra -Destination $out -Recurse; Copy-Item scripts -Destination $out -Recurse
    New-Item -ItemType Directory -Force "$out/docs" | Out-Null; Copy-Item docs/*.md "$out/docs" -ErrorAction SilentlyContinue
    if ($IncludeImages) {
      $imgs = @('doorain/backend:0.1.0', 'doorain/web:0.1.0') + @((Get-Content infra/models.lock.json -Raw | ConvertFrom-Json).images.PSObject.Properties | Where-Object { $_.Name -in 'postgres', 'qdrant', 'ollama' } | ForEach-Object { $_.Value })
      Say "docker save: $($imgs -join ', ')"; Run 'docker' (@('save', '-o', "$out/images.tar") + $imgs)
    }
    if ($IncludeModels) {
      foreach ($v in 'models', 'ollama') {
        $vol = "$(if ($Project) { $Project } else { 'doorain' })_$v"
        Run 'docker' @('run', '--rm', '-v', "${vol}:/src:ro", '-v', "${out}:/out", 'doorain/backend:0.1.0', 'tar', '-czf', "/out/volume-$v.tar.gz", '-C', '/src', '.')
      }
    }
    Get-ChildItem $out -Recurse -File | Where-Object { $_.Name -ne 'SHA256SUMS' } | ForEach-Object { '{0}  {1}' -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.FullName.Substring($out.Length + 1).Replace('\', '/') } | Set-Content -Encoding utf8 "$out/SHA256SUMS"
    "Bundle DoorAIn $ts`nСекреты (.env) и данные НЕ включены. Импорт: scripts/doorain import-bundle <каталог>. Затем init, start, create-owner, restore." | Set-Content -Encoding utf8 "$out/README-BUNDLE.txt"
    Ok "Bundle: $out"
  }

  'import-bundle' {
    if (-not $Arg) { throw 'Использование: doorain.ps1 import-bundle <каталог bundle>' }
    $b = (Resolve-Path $Arg).Path
    foreach ($l in Get-Content "$b/SHA256SUMS") { $h, $p = $l -split '  ', 2; if ((Get-FileHash "$b/$p" -Algorithm SHA256).Hash.ToLower() -ne $h) { throw "Контрольная сумма не совпала: $p" } }
    Ok 'SHA-256 манифест проверен'
    if (Test-Path "$b/images.tar") { Run 'docker' @('load', '-i', "$b/images.tar") }
    foreach ($v in 'models', 'ollama') {
      $f = "$b/volume-$v.tar.gz"
      if (Test-Path $f) {
        $vol = "$(if ($Project) { $Project } else { 'doorain' })_$v"
        Run 'docker' @('volume', 'create', $vol)
        Run 'docker' @('run', '--rm', '-v', "${vol}:/dst", '-v', "${b}:/in:ro", 'doorain/backend:0.1.0', 'tar', '-xzf', "/in/volume-$v.tar.gz", '-C', '/dst')
      }
    }
    Ok 'Импорт завершён: build/pull/pip/npm install не выполнялись. Дальше: init ; start ; create-owner ; restore <id>'
  }
}
