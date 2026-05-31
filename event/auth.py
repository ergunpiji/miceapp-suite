"""
E-dem — JWT tabanlı kimlik doğrulama
HttpOnly cookie ile token saklama
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
from models import User, RolePermission

# ---------------------------------------------------------------------------
# Yapılandırma
# ---------------------------------------------------------------------------

# SECRET_KEY: Önce ortam değişkeninden oku.
# Production'da mutlaka .env dosyasına güçlü bir değer yazın.
# Üretmek için: python -c "import secrets; print(secrets.token_hex(32))"
_env_key = os.environ.get("SECRET_KEY", "")
if _env_key:
    SECRET_KEY = _env_key
else:
    # Development fallback — her restart'ta aynı kalır,
    # ama production'da asla kullanılmamalı.
    SECRET_KEY = "edem-dev-fallback-key--set-SECRET_KEY-env-var-in-production"
    print("[AUTH] ⚠️  SECRET_KEY env variable ayarlı değil — development fallback kullanılıyor!", flush=True)

ALGORITHM       = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480   # 8 saat

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
    """E-posta ve şifre ile kullanıcıyı doğrular"""
    user = db.query(User).filter(
        User.email == email.lower().strip(),
        User.active == True,  # noqa: E712
    ).first()
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_user_by_id(db: Session, user_id: str) -> Optional[User]:
    return db.query(User).filter(User.id == user_id, User.active == True).first()  # noqa: E712


# ---------------------------------------------------------------------------
# FastAPI Dependencies
# ---------------------------------------------------------------------------

def _get_token_from_cookie(request: Request) -> Optional[str]:
    return request.cookies.get(COOKIE_NAME)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """
    Dependency: Mevcut kullanıcıyı döndürür.
    Cookie yoksa veya geçersizse → 401 (login'e yönlendirmek için)
    """
    token = _get_token_from_cookie(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Oturum bulunamadı. Lütfen giriş yapın.",
        )
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Geçersiz veya süresi dolmuş oturum. Lütfen tekrar giriş yapın.",
        )
    user_id: str = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Geçersiz token.",
        )
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kullanıcı bulunamadı veya hesap devre dışı.",
        )
    return user


def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Login sayfası gibi yerlerde opsiyonel kullanıcı"""
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None


# ---------------------------------------------------------------------------
# Rol tabanlı dependency'ler
# ---------------------------------------------------------------------------

def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Admin, GM (grade=1), Müdür veya Muhasebe Müdürü yetkisi gereklidir."""
    if current_user.role not in ("admin", "mudur", "muhasebe_muduru") and not current_user.is_gm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için Admin yetkisi gereklidir.",
        )
    return current_user


def require_pm(current_user: User = Depends(get_current_user)) -> User:
    """Tüm proje tarafı roller (mudur + yonetici + asistan) + admin + GM."""
    if current_user.role not in ("admin", "mudur", "yonetici", "asistan", "project_manager") and not current_user.is_gm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için Proje Yöneticisi yetkisi gereklidir.",
        )
    return current_user


def require_pm_yonetici(current_user: User = Depends(get_current_user)) -> User:
    """Talep oluşturma, teklif gönderme, bütçe onayı gibi işlemler için."""
    if current_user.role in ("admin", "mudur", "yonetici") or current_user.is_gm:
        return current_user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Bu işlem için en az Proje Yöneticisi yetkisi gereklidir.",
    )


def require_pm_mudur(current_user: User = Depends(get_current_user)) -> User:
    """Kapama L1 onayı gibi üst düzey işlemler için (mudur + admin + GM)."""
    if current_user.role in ("admin", "mudur") or current_user.is_gm:
        return current_user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Bu işlem için Müdür yetkisi gereklidir.",
    )


def require_edem(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ("admin", "e_dem") and not current_user.is_gm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için E-dem yetkisi gereklidir.",
        )
    return current_user


def require_admin_or_edem(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ("admin", "e_dem", "muhasebe_muduru") and not current_user.is_gm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için Admin, E-dem veya Muhasebe Müdürü yetkisi gereklidir.",
        )
    return current_user


def require_finance(current_user: User = Depends(get_current_user)) -> User:
    """Fatura girişi için muhasebe + muhasebe_muduru + admin + GM."""
    if current_user.role not in ("admin", "muhasebe_muduru", "muhasebe") and not current_user.is_gm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için Muhasebe yetkisi gereklidir.",
        )
    return current_user


def can_approve_invoice(user: User) -> bool:
    """Fatura onayı: admin, mudur, yonetici, muhasebe_muduru, GM."""
    return user.role in ("admin", "mudur", "yonetici", "muhasebe_muduru") or user.is_gm


def can_approve_expense(user: User) -> bool:
    """HBF onayı: admin, mudur, yonetici, GM."""
    return user.role in ("admin", "mudur", "yonetici") or user.is_gm


def can_send_offer(user: User) -> bool:
    """Müşteriye teklif gönderme: admin, mudur, yonetici."""
    return user.role in ("admin", "mudur", "yonetici") or user.is_gm


def can_approve_budget(user: User) -> bool:
    """Bütçe onayı: admin, mudur, yonetici."""
    return user.role in ("admin", "mudur", "yonetici") or user.is_gm


def can_start_closure(user: User) -> bool:
    """Dosya kapamayı başlatma: admin, mudur, yonetici."""
    return user.role in ("admin", "mudur", "yonetici") or user.is_gm


def can_approve_closure_l1(user: User) -> bool:
    """Kapama L1 onayı: admin, mudur."""
    return user.role in ("admin", "mudur")


def can_approve_closure_final(user: User) -> bool:
    """Kapama final onayı: admin, muhasebe_muduru."""
    return user.role in ("admin", "muhasebe_muduru")


# ---------------------------------------------------------------------------
# DB tabanlı izin kontrolü
# ---------------------------------------------------------------------------

def has_permission(user: User, permission_key: str, db: Session) -> bool:
    """Kullanıcının belirli bir izne sahip olup olmadığını DB'den kontrol eder.
    Admin her zaman izinlidir. DB'de satır yoksa DEFAULT_ROLE_PERMISSIONS'a fallback yapar."""
    if user.role in ("admin", "super_admin"):   # miceapp suite: super_admin = en üst yetki
        return True
    rp = db.query(RolePermission).filter(
        RolePermission.role == user.role,
        RolePermission.permission == permission_key,
    ).first()
    if rp is not None:
        return bool(rp.allowed)
    # DB'de kayıt yoksa varsayılan izin tablosuna bak
    from models import DEFAULT_ROLE_PERMISSIONS
    return permission_key in DEFAULT_ROLE_PERMISSIONS.get(user.role, [])


def require_permission(permission_key: str):
    """FastAPI Dependency factory — belirli izni olmayan kullanıcıyı engeller."""
    def _check(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not has_permission(current_user, permission_key, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bu işlem için yetkiniz bulunmuyor.",
            )
        return current_user
    return _check
