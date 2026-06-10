"""
Kimlik doğrulama
GET  /login  → form
POST /login  → cookie set → /dashboard
GET  /logout → cookie sil → /login
POST /logout → cookie sil → /login
"""

import os

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

import auth as auth_module
from auth import COOKIE_NAME, COOKIE_DOMAIN, ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token, redirect_app_url_for, get_current_user
from database import get_db
from models import User
from templates_config import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse, name="login_get")
async def login_get(request: Request, db: Session = Depends(get_db)):
    user = auth_module.get_current_user_optional(request, db)
    if user:
        # Satış/operasyon rolü ise işlerini event'te yapar → event'e yönlendir
        target = redirect_app_url_for(user)
        return RedirectResponse(url=target or "/dashboard", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None, "current_user": None},
    )


@router.post("/login", name="login_post")
async def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = auth_module.authenticate_user(db, email, password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request,
             "error": "E-posta adresi veya şifre hatalı.",
             "current_user": None,
             "email_value": email},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token = create_access_token(data={
        "sub": str(user.id),
        "is_admin": user.is_admin,
    })
    _is_production = os.environ.get("ENVIRONMENT", "").lower() == "production"
    # Satış/operasyon rolü ise giriş sonrası event'e yönlendir (cookie .miceapp.net
    # domaininde set edildiği için event'te de geçerli olur)
    target = redirect_app_url_for(user)
    response = RedirectResponse(url=target or "/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        path="/",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        secure=_is_production,
        domain=COOKIE_DOMAIN,
    )
    return response


@router.get("/logout", name="logout_get")
@router.post("/logout", name="logout_post")
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key=COOKIE_NAME, path="/", domain=COOKIE_DOMAIN)
    return response


@router.post("/switch-company", name="switch_company")
async def switch_company(
    request: Request,
    company_id: str = Form(""),
    current_user: User = Depends(get_current_user),
):
    """super_admin aktif şirketi değiştirir (active_company cookie).
    company_id boş → Tüm Şirketler (konsolide)."""
    if current_user.role != "super_admin":
        raise HTTPException(status_code=403)
    _is_production = os.environ.get("ENVIRONMENT", "").lower() == "production"
    _ref = request.headers.get("referer") or ""
    back = _ref if _ref.startswith("http") else "/dashboard"
    response = RedirectResponse(url=back, status_code=status.HTTP_302_FOUND)
    cid = (company_id or "").strip()
    if cid:
        response.set_cookie(
            key="active_company", value=cid, httponly=True, path="/",
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60, samesite="lax",
            secure=_is_production, domain=COOKIE_DOMAIN,
        )
    else:
        response.delete_cookie(key="active_company", path="/", domain=COOKIE_DOMAIN)
    return response


@router.get("/demo", name="demo_login")
async def demo_login(db: Session = Depends(get_db)):
    """Demo hesabına otomatik giriş — 1 saatlik oturum."""
    demo_user = db.query(User).filter(
        User.email == "demo@miceapp.net", User.active == True  # noqa: E712
    ).first()
    if not demo_user:
        raise HTTPException(
            status_code=404,
            detail="Demo hesap henüz hazır değil. Lütfen daha sonra tekrar deneyin.",
        )
    _is_production = os.environ.get("ENVIRONMENT", "").lower() == "production"
    token = create_access_token({"sub": str(demo_user.id), "is_admin": demo_user.is_admin})
    resp = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    resp.set_cookie(
        key=COOKIE_NAME, value=token, httponly=True,
        max_age=3600, samesite="lax", secure=_is_production,
        domain=COOKIE_DOMAIN,
    )
    return resp
