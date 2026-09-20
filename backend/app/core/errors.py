"""Единый формат ошибок: code, message, details?, request_id. Без stack trace наружу."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("doorain.errors")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None, headers: dict[str, str] | None = None):
        self.status, self.code, self.message, self.details, self.headers = status, code, message, details, headers or {}


def not_found(what: str = "Объект") -> ApiError:
    return ApiError(404, "not_found", f"{what} не найден")


def _body(request: Request, code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details, "request_id": getattr(request.state, "request_id", None)}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(_body(request, exc.code, exc.message, exc.details), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _val(request: Request, exc: RequestValidationError) -> JSONResponse:
        det = [{"loc": [str(x) for x in e.get("loc", [])], "msg": e.get("msg", "")} for e in exc.errors()]
        return JSONResponse(_body(request, "validation_error", "Некорректные данные запроса", det), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        msg = {404: "Не найдено", 405: "Метод не поддерживается"}.get(exc.status_code, "Ошибка запроса")
        return JSONResponse(_body(request, f"http_{exc.status_code}", msg), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _any(request: Request, exc: Exception) -> JSONResponse:
        rid = getattr(request.state, "request_id", str(uuid.uuid4()))
        log.error("unhandled error request_id=%s type=%s", rid, type(exc).__name__, exc_info=exc)
        return JSONResponse(_body(request, "internal_error", "Внутренняя ошибка сервера"), status_code=500)
