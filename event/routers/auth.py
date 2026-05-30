"""
E-dem — Kimlik doğrulama router'ı
GET  /login          → Giriş formu
POST /login          → Doğrula, cookie set et, dashboard'a yönlendir
POST /logout         → Cookie sil, login'e yönlendir
GET  /logout         → Cookie sil, login'e yönlendir
POST /profile/avatar → Profil fotoğrafı kaydet (JSON)
POST /profile/update → Ad, unvan, telefon güncelle
"""

import base64
import os

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

import auth as auth_module
from auth import COOKIE_NAME, ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token, get_current_user
from database import get_db
from models import User

router = APIRouter()
from templates_config import templates


@router.get("/login", response_class=HTMLResponse, name="login_get")
async def login_get(request: Request, db: Session = Depends(get_db)):
    """Giriş formunu göster — zaten giriş yapmışsa dashboard'a yönlendir"""
    user = auth_module.get_current_user_optional(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
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
    """Kullanıcı girişini doğrula ve JWT cookie set et"""
    user = auth_module.authenticate_user(db, email, password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "E-posta adresi veya şifre hatalı. Lütfen tekrar deneyin.",
                "current_user": None,
                "email_value": email,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token = create_access_token(data={"sub": user.id})

    _is_production = os.environ.get("ENVIRONMENT", "").lower() == "production"
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        secure=_is_production,
    )
    return response


@router.get("/logout", name="logout_get")
@router.post("/logout", name="logout_post")
async def logout(request: Request):
    """Oturumu kapat"""
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key=COOKIE_NAME)
    return response


@router.post("/profile/avatar")
async def profile_avatar(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Profil fotoğrafını kaydet — body: {data_uri: "data:image/...;base64,..."} veya {clear: true}"""
    body = await request.json()
    if body.get("clear"):
        current_user.avatar_b64 = ""
    else:
        data_uri = body.get("data_uri", "")
        if not data_uri.startswith("data:image/"):
            return JSONResponse({"error": "Geçersiz resim"}, status_code=400)
        if len(data_uri) > 2_000_000:   # ~1.5 MB
            return JSONResponse({"error": "Resim çok büyük (max ~1.5 MB)"}, status_code=400)
        current_user.avatar_b64 = data_uri
    db.commit()
    return JSONResponse({"ok": True, "avatar": current_user.avatar_b64})


@router.post("/profile/update")
async def profile_update(
    name:    str = Form(...),
    surname: str = Form(...),
    title:   str = Form(""),
    phone:   str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ad, unvan, telefon güncelle"""
    if not name.strip() or not surname.strip():
        return JSONResponse({"error": "Ad Soyad boş olamaz"}, status_code=400)
    current_user.name    = name.strip()
    current_user.surname = surname.strip()
    current_user.title   = title.strip()
    current_user.phone   = phone.strip()
    db.commit()
    return JSONResponse({"ok": True, "full_name": current_user.full_name, "title": current_user.title})
