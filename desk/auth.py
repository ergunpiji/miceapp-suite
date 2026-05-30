"""
E-dem — JWT tabanlı kimlik doğrulama
HttpOnly cookie ile token saklama
"""

import os
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
from models import User, RolePermission, ROLE_ORDER

# ---------------------------------------------------------------------------
# Yapılandırma
# ---------------------------------------------------------------------------

_env_key = os.environ.get("SECRET_KEY", "")
SECRET_KEY = _env_key or "edem-dev-fallback-key--set-SECRET_KEY-env-var-in-production"
if not _env_key:
    print("[AUTH] SECRET_KEY env variable ayarlı değil — development fallback kullanılıyor!", flush=True)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 saat

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
COOKIE_NAME = "access_token"


# ---------------------------------------------------------------------------
# Şifre yardımcıları
# ---------------------------------------------------------------------------

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


# ---------------------------------------------------------------------------
# JWT yardımcıları
# ---------------------------------------------------------------------------

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# Kullanıcı sorgulama
# ---------------------------------------------------------------------------

def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    user = db.query(User).filter(
        User.email == email.lower().strip(),
        User.active == True,  # noqa: E712
    ).first()
    if not user or not verify_password(password, user.password_hash):
        return None
    return user


def get_user_by_id(db: Session, user_id) -> Optional[User]:
    return db.query(User).filter(User.id == str(user_id), User.active == True).first()  # noqa: E712


# ---------------------------------------------------------------------------
# FastAPI Dependencies
# ---------------------------------------------------------------------------

def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Oturum bulunamadı. Lütfen giriş yapın.")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Geçersiz veya süresi dolmuş oturum.")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Geçersiz token.")
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Kullanıcı bulunamadı veya hesap devre dışı.")
    return user


def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None


def get_company_id(current_user: User = Depends(get_current_user)) -> str:
    """Mevcut kullanıcının company_id'sini string olarak döner. Atanmamışsa 400."""
    if not current_user.company_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Kullanıcıya şirket atanmamış.")
    return str(current_user.company_id)


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Bu işlem için Admin yetkisi gereklidir.")
    return current_user


def require_gm(current_user: User = Depends(get_current_user)) -> User:
    """Genel Müdür veya Admin yetkisi gerektirir."""
    if not current_user.has_role_min("genel_mudur"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Bu sayfa için Genel Müdür yetkisi gereklidir.")
    return current_user


def require_mudur(current_user: User = Depends(get_current_user)) -> User:
    """Müdür veya üstü yetkisi gerektirir."""
    if not current_user.has_role_min("mudur"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Bu sayfa için Müdür yetkisi gereklidir.")
    return current_user


# ---------------------------------------------------------------------------
# İzin sistemi
# ---------------------------------------------------------------------------

DEFAULT_PERMISSIONS: dict[str, str] = {
    "advance_create":          "kullanici",
    "advance_approve_first":   "mudur",
    "advance_approve_final":   "genel_mudur",
    "hbf_create":              "kullanici",
    "hbf_approve_first":       "mudur",
    "hbf_approve_final":       "genel_mudur",
    "invoice_create":          "kullanici",
    "invoice_delete":          "admin",
    "payment_list_prepare":    "kullanici",
    "payment_list_approve":    "genel_mudur",
    "fund_pool_manage":        "admin",
    "cash_close":              "mudur",
    "report_view":             "kullanici",
    "report_view_financial":   "mudur",
    "report_view_all":         "genel_mudur",
    "customer_manage":         "admin",
    "employee_manage":         "admin",
    "vendor_manage":           "mudur",
    "user_manage":             "admin",
    "role_permission_manage":  "admin",
    "module_config":           "admin",
    "super_admin_panel":       "super_admin",
}


def check_permission(user: User, permission: str, db: Session) -> bool:
    """DB'de override varsa onu kullan, yoksa DEFAULT_PERMISSIONS'a bak."""
    row = db.query(RolePermission).filter_by(
        role=user.role, permission=permission
    ).first()
    if row is not None:
        return row.enabled
    min_role = DEFAULT_PERMISSIONS.get(permission, "super_admin")
    try:
        return ROLE_ORDER.index(user.role) >= ROLE_ORDER.index(min_role)
    except ValueError:
        return False


def require_permission(permission: str):
    """FastAPI dependency factory — belirtilen izin için rol kontrolü yapar."""
    def _dep(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not check_permission(current_user, permission, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bu işlem için yetkiniz yok.",
            )
        return current_user
    return Depends(_dep)


def require_module(module_key: str, edit: bool = False):
    """RBAC v2 — Departman bazlı modül erişim kontrolü.
    Kullanım: user: User = Depends(require_module("customers"))
    edit=True: yazma yetkisi gerektirir (POST/PUT/DELETE endpoint'leri için).
    """
    def _dep(current_user: User = Depends(get_current_user)) -> User:
        from access_policy import user_can_see_module, user_can_edit_module
        check = user_can_edit_module if edit else user_can_see_module
        if not check(current_user, module_key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Bu sayfaya erişim yetkiniz yok ({module_key}).",
            )
        return current_user
    return _dep


def safe_redirect(url: str, default: str = "/") -> str:
    """URL'nin aynı-origin olduğunu doğrula; dış URL ise default'a düş."""
    if not url:
        return default
    parsed = urlparse(url)
    if parsed.scheme or parsed.netloc:
        return default
    return url
