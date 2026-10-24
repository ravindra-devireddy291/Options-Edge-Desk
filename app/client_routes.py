"""Client live routes. Identity is the signed BFF assertion, never a body field."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.assertion import read_assertion
from app.auth import require_api_key
from app.client_live import (
    decide,
    is_client_role,
    link_groww,
    login,
    me_live,
    register,
    roster,
    set_auto,
    stop_orders,
)
from app.schemas.envelope import err, ok

router = APIRouter(prefix="/api/v1/desk", dependencies=[Depends(require_api_key)])


class LoginBody(BaseModel):
    email: str
    password: str


class RegisterBody(BaseModel):
    full_name: str
    mobile: str
    totp_token: str
    totp_secret: str
    live_confirmed: bool


class LinkBody(BaseModel):
    totp_token: str
    totp_secret: str


class AutoBody(BaseModel):
    auto_mode: bool


class DecisionBody(BaseModel):
    edge_id: str = Field(min_length=1)
    decision: Literal["accept", "reject"]


def _caller(request: Request) -> tuple[str, str]:
    return read_assertion(request)


def _bad(exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=400, content=err(str(exc), code="invalid_request"))


@router.post("/auth/login")
def auth_login(body: LoginBody) -> JSONResponse:
    user = login(body.email, body.password)
    if not user:
        return JSONResponse(status_code=401, content=err("unknown login", code="unauthorized"))
    return JSONResponse(status_code=200, content=ok(user))


@router.get("/me/live")
def get_me_live(request: Request) -> JSONResponse:
    try:
        email, _role = _caller(request)
        return JSONResponse(status_code=200, content=ok(me_live(email)))
    except Exception as exc:
        return _bad(exc)


@router.get("/clients/live")
def get_clients_live(request: Request) -> JSONResponse:
    try:
        _email, role = _caller(request)
    except Exception as exc:
        return _bad(exc)
    if is_client_role(role):
        return JSONResponse(status_code=403, content=err("admin only", code="forbidden"))
    return JSONResponse(status_code=200, content=ok(roster()))


@router.post("/me/register")
def post_register(request: Request, body: RegisterBody) -> JSONResponse:
    try:
        email, _role = _caller(request)
        return JSONResponse(status_code=200, content=ok(register(email, body.model_dump())))
    except Exception as exc:
        return _bad(exc)


@router.post("/groww/link")
def post_link(request: Request, body: LinkBody) -> JSONResponse:
    try:
        email, _role = _caller(request)
        return JSONResponse(status_code=200, content=ok(link_groww(email, body.totp_token, body.totp_secret)))
    except Exception as exc:
        return _bad(exc)


@router.post("/me/auto")
def post_auto(request: Request, body: AutoBody) -> JSONResponse:
    try:
        email, _role = _caller(request)
        return JSONResponse(status_code=200, content=ok(set_auto(email, body.auto_mode)))
    except Exception as exc:
        return _bad(exc)


@router.post("/me/stop")
def post_stop(request: Request) -> JSONResponse:
    try:
        email, _role = _caller(request)
        return JSONResponse(status_code=200, content=ok(stop_orders(email)))
    except Exception as exc:
        return _bad(exc)


@router.post("/edges/decision")
def post_decision(request: Request, body: DecisionBody) -> JSONResponse:
    try:
        email, _role = _caller(request)
        return JSONResponse(status_code=200, content=ok(decide(email, body.edge_id, body.decision)))
    except Exception as exc:
        return _bad(exc)
