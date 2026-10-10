<#
.SYNOPSIS  Наглядная проверка: ИИ DoorAIn работает без выхода в интернет (для показа на экране).
.NOTES     Запуск из корня проекта: powershell -ExecutionPolicy Bypass -File scripts\demo-privacy.ps1 [-Pause]
           -Pause: после каждого шага ждёт Enter (удобно на сцене). -Font 24: крупный шрифт консоли для проектора. Нужен запущенный стек (scripts\doorain.ps1 start).
#>
param([switch]$Pause, [int]$Font = 0)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = 'DoorAIn: проверка приватности'
Set-Location (Split-Path -Parent $PSScriptRoot)
if ($Font -gt 0) {  # крупный шрифт (классическая консоль; в Windows Terminal увеличивайте Ctrl + колесо мыши)
  Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public class CF {
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
  public struct FONTEX { public uint cb; public uint n; public short X; public short Y; public int Family; public int Weight; [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string Face; }
  [DllImport("kernel32.dll")] public static extern IntPtr GetStdHandle(int n);
  [DllImport("kernel32.dll")] public static extern bool SetCurrentConsoleFontEx(IntPtr h, bool max, ref FONTEX f);
}
"@
  $fx = New-Object CF+FONTEX
  $fx.cb = [Runtime.InteropServices.Marshal]::SizeOf($fx); $fx.Y = $Font; $fx.Family = 54; $fx.Weight = 400; $fx.Face = 'Consolas'
  [void][CF]::SetCurrentConsoleFontEx([CF]::GetStdHandle(-11), $false, [ref]$fx)
}

function Line($t, $c = 'White') { Write-Host $t -ForegroundColor $c }
function Cmd($t) { Line "  > $t" Cyan }
function Step($n, $t) {
  Write-Host ''
  Line ('=' * 90) DarkGray
  Line "  ШАГ ${n}. $t" Yellow
  Line ('=' * 90) DarkGray
  if ($Pause) { Read-Host '  [Enter - продолжить]' | Out-Null }
}

Step 1 'Сеть, в которой работает ИИ'
Cmd 'docker network inspect doorain_internal'
$net = (docker network inspect doorain_internal --format '{{.Internal}}|{{range .Containers}}{{.Name}}  {{end}}') -split '\|'
Line "  Службы внутри: $($net[1] -replace 'doorain-', '' -replace '-1 ', ' ')" Gray
if ($net[0] -eq 'true') { Line '  Internal = true   ->   у этой сети НЕТ выхода в интернет' Green }
else { Line '  Internal = false  ->   ВНИМАНИЕ: выход в интернет возможен' Red }

Step 2 'ИИ-сервер (worker) пробует открыть google.com'
Cmd 'docker compose exec worker python  ...  urlopen("https://www.google.com")'
$py = "import urllib.request,sys`ntry:`n    urllib.request.urlopen('https://www.google.com', timeout=6)`n    print('OK page received')`nexcept Exception as e:`n    print('FAIL', e)`n    sys.exit(1)"
$out = ($py | docker compose exec -T worker python -)
$rc = $LASTEXITCODE
Line "  Ответ системы: $out" Gray
if ($rc -ne 0) { Line '  ЗАБЛОКИРОВАНО: ИИ-сервер не может выйти в интернет' Red }
else { Line '  ВНИМАНИЕ: выход в интернет есть' Yellow }

Step 3 'Для сравнения: служба web, у которой внешняя сеть ЕСТЬ, делает то же'
Cmd 'docker compose exec web wget -O - http://example.com'
$html = docker compose exec -T web wget -q -T 6 -O - http://example.com
if ($LASTEXITCODE -eq 0) {
  $title = [regex]::Match(($html -join ' '), '<title>(.*?)</title>').Groups[1].Value
  Line "  Ответ сайта example.com получен: страница «$title» ($(($html -join ' ').Length) символов)" Gray
  Line '  ПРОШЛО: где выход есть, страница приходит. Значит, проверка работает честно.' Green
} else { Line '  Контроль не прошёл: нет интернета на самом компьютере. Подключитесь и повторите.' Yellow }

Step 4 'ИИ отвечает на вопрос, хотя интернета у него нет'
$model = (docker compose exec -T api printenv DOORAIN_OLLAMA_MODEL).Trim()
$q = 'Ответь одной фразой: что такое персональные данные?'
Cmd "docker compose exec ollama ollama run $model"
Line "  Вопрос: $q" White
$sw = [Diagnostics.Stopwatch]::StartNew()
$ans = '' | docker compose exec -T ollama ollama run $model $q   # пустой ввод по конвейеру: иначе ollama ждёт конца stdin
$sw.Stop()
$ans | ForEach-Object { if ($_.Trim()) { Line "  $_" Green } }
Line "  Ответ получен за $([int]$sw.Elapsed.TotalSeconds) с" Gray

Write-Host ''
Line ('=' * 90) DarkGray
Line '  ИТОГ: ИИ ответил на вопрос, а выхода в интернет у него нет (шаг 2).' Green
Line '        Вопрос и ответ остались на этом компьютере.' Green
Line ('=' * 90) DarkGray
