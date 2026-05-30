"""
Token tabanlı kullanıcı girişi.
/access/{token} → cookie atar → event sayfasına yönlendirir.
"""
from fastapi import APIRouter, Depends, Request, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from config import url, now_tr
from database import get_db
from models import UserToken, Event
from templates_config import templates

router = APIRouter(tags=["access"])

COOKIE_NAME = "oa_access"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 gün


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    oa_access: str | None = Cookie(default=None),
):
    """
    Cookie'deki token'ı doğrular.
    Geçerliyse (event_id, role, label) tuple döner; değilse None.
    """
    token_str = oa_access
    if not token_str:
        return None

    ut = db.query(UserToken).filter(
        UserToken.token == token_str,
        UserToken.active == True,
    ).first()

    if not ut:
        return None

    # Son kullanım zamanını güncelle
    ut.last_used_at = now_tr()
    db.commit()

    return {"event_id": ut.event_id, "role": ut.role, "label": ut.label}


def require_user(
    request: Request,
    db: Session = Depends(get_db),
    oa_access: str | None = Cookie(default=None),
):
    """
    Event route'larında kullanılır.
    Geçersiz token → giriş sayfasına yönlendirir (exception olarak).
    """
    user = get_current_user(request, db, oa_access)
    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=307, headers={"Location": url("/giris")})
    return user


# ---------------------------------------------------------------------------
# Token ile giriş
# ---------------------------------------------------------------------------
@router.get("/access/{token}", response_class=Response)
async def token_login(
    token: str,
    db: Session = Depends(get_db),
):
    ut = db.query(UserToken).filter(
        UserToken.token == token,
        UserToken.active == True,
    ).first()

    if not ut:
        return HTMLResponse("""
        <html><body style='font-family:sans-serif;text-align:center;padding:60px'>
        <h2>❌ Geçersiz veya süresi dolmuş bağlantı</h2>
        <p>Bu link artık aktif değil. Proje yöneticinizden yeni bir link isteyin.</p>
        </body></html>
        """, status_code=404)

    ut.last_used_at = now_tr()
    db.commit()

    response = RedirectResponse(url=url(f"/events/{ut.event_id}"), status_code=303)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


# ---------------------------------------------------------------------------
# Çıkış
# ---------------------------------------------------------------------------
@router.get("/giris", response_class=HTMLResponse)
async def login_required_page(request: Request):
    return templates.TemplateResponse("access/login_required.html", {"request": request})


@router.get("/cikis")
async def logout():
    response = RedirectResponse(url=url("/giris"), status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response
