# Безопасность

Сервис рассчитан на публикацию в интернет одним владельцем. Защита входа обязательна и не отключается «для демо».

## Контроли и где они проверяются

| Область | Реализация | Проверка |
|---|---|---|
| Владелец | Только CLI `create-owner` (интерактивный пароль); публичной регистрации и setup-endpoint нет; второго владельца создать нельзя. Сброс — `reset-password` (отзывает все сессии). | `test_no_public_registration…`, `test_owner_can_only_be_created_once` |
| Пароли | Argon2id (argon2-cffi), случайная соль, `needs_rehash`; минимум 12 символов. | `test_password_is_argon2id_and_tokens_are_hashed` |
| Сессии | Случайный токен, в БД — SHA-256 хэш; cookie `HttpOnly`, `SameSite=Lax`, `Secure` и префикс `__Host-` в production; ротация при входе и смене пароля; logout и смена пароля отзывают сессии; SSE каждые 20 с перепроверяет доступ; PDF проверяет права при каждом скачивании. | `test_logout_revokes_server_side`, `test_change_password_revokes_all_other_sessions`, `test_export_pdf_content_snapshot_and_auth` |
| CSRF / Origin / Host | Токен `X-CSRF-Token` = HMAC(сессия); проверка `Origin` и `Sec-Fetch-Site` для изменяющих запросов (включая login, загрузки, logout); `TrustedHostMiddleware`; CORS отсутствует. | `test_csrf_required…`, `test_origin_check`, `test_host_header_checked` |
| Вход | Ошибка одинакова для неверного имени и пароля (в т. ч. время: фиктивный Argon2-хэш); лимиты по IP и аккаунту хранятся в БД (переживают рестарт); блокировка по аккаунту не действует на IP, откуда владелец уже входил (нельзя запереть владельца чужими попытками). | `test_login_rate_limit_persisted_in_db` |
| Прокси | `X-Forwarded-For` принимается только от Caddy (доверие по имени сервиса) и перезаписывается им; берётся крайний недоверенный адрес. | `test_client_ip_trusts_forwarded_header_only_from_trusted_proxy` |
| Объекты | Каждый запрос проверяет владельца; чужой/угаданный ID неотличим от несуществующего (404). | `test_object_ownership_isolation` |
| Заголовки | API: `nosniff`, `X-Frame-Options`, `no-store`, CSP `default-src 'none'`. UI: единая CSP (Caddy = приложение, сверяется тестом), HSTS, `Referrer-Policy: no-referrer`. `/docs` и OpenAPI отключены в production. | `test_security_headers…`, `test_caddy_csp_matches_app_csp`, e2e без нарушений CSP |
| Загрузки | Лимиты размера/страниц/символов, sniff по содержимому, безопасное имя, хранение вне публичной директории, защита от zip-bomb (DOCX), HTML — только экстрагированный текст без JS и внешних ресурсов, оригиналы отдаются как `attachment` + `nosniff`, предпросмотр — экранированный текст. Загрузки по URL нет (нет SSRF-поверхности). | `test_parsers…`, `test_docx_zip_bomb_rejected`, `test_upload_limits_and_safe_names` |
| LLM | Нет shell/файлов/HTTP/SQL; инструкции в источниках и вопросах — данные; ссылки, реквизиты и даты подставляет сервер; облачного fallback нет. | `test_unsupported_blocks_replaced…`, `test_risk_without_normative_basis_is_not_created` |
| Markdown | `react-markdown` с `skipHtml`, ссылки не активны, изображения не загружаются. | `components.test.tsx` |
| Контейнеры | Без `privileged`, без Docker socket, non-root (uid 10001), `cap_drop: ALL`, `no-new-privileges`; БД, Qdrant, Ollama, API не публикуются; сеть `internal: true`, во внешнюю сеть выходит только `web`. | `docker compose config`, проверка изоляции (`progress.md`) |
| Секреты | Только в `.env` (вне Git), `.env.example` пуст; production отказывается стартовать со слабым/placeholder-секретом, без `Secure`-cookie, с тестовыми провайдерами, с placeholder-доменом. | `test_production_guards`, `test_infra.py` |
| Логи/аудит | Аудит — в БД, только владельцу (`/runs/{id}/trace`); технические логи не содержат тела запросов, паролей и токенов. | ревью кода |

## Известные ограничения (честно)

* Нет MFA и WAF; общий rate limit запросов в памяти процесса (см. `decisions.md`).
* Caddy без плагина rate-limit; защита от перебора — на уровне приложения.
* Backup содержит хэш пароля и все данные — храните и передавайте как секрет (опция `-Encrypt`/`--encrypt` через gpg).
* Зависимости: `pip-audit`/`pnpm audit` — см. результаты в `progress.md`; автоматическое обновление не настроено.
* Skill'ы Strix (`api-security-testing` и др.) **не запускались**: им нужны Docker-образ Strix и внешний LLM — передача кода/данных наружу недопустима без отдельного решения владельца. Выполнены локальные проверки (тесты безопасности, `ruff S`, аудит зависимостей).
