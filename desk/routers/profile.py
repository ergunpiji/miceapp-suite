"""Kullanıcı profili — kendi bilgilerini günceller (ad/soyad/ünvan/telefon)."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, safe_redirect
from database import get_db
from models import User


router = APIRouter(tags=["profile"])


@router.post("/profile", name="profile_update")
async def profile_update(
    request: Request,
    name: str = Form(...),
    surname: str = Form(""),
    title: str = Form(""),
    phone: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    n = (name or "").strip()
    if not n:
        n = current_user.name  # boş gönderilirse mevcut kalır
    current_user.name = n
    current_user.surname = (surname or "").strip() or None
    current_user.title = (title or "").strip() or None
    current_user.phone = (phone or "").strip() or None
    db.commit()
    referer = safe_redirect(request.headers.get("referer", ""), "/dashboard")
    return RedirectResponse(url=referer, status_code=303)
