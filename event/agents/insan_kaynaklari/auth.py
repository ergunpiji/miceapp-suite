"""HR Ajanı — JWT kimlik doğrulama ve rol kontrolleri."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
from models import HRUser

SECRET_KEY = "hr-agent-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 saat

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    access_token: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_db),
) -> HRUser:
    credentials_exc = HTTPException(
        status_code=status.HTTP_302_FOUND,
        headers={"Location": "/auth/login"},
    )
    if not access_token:
        raise credentials_exc
    try:
        payload = jwt.decode(access_token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    user = db.query(HRUser).filter(HRUser.id == user_id, HRUser.is_active == True).first()
    if not user:
        raise credentials_exc
    return user


def require_hr_admin(current_user: HRUser = Depends(get_current_user)) -> HRUser:
    if current_user.role != "hr_admin":
        raise HTTPException(status_code=403, detail="HR Admin yetkisi gerekli")
    return current_user


def require_hr_manager_or_admin(current_user: HRUser = Depends(get_current_user)) -> HRUser:
    if current_user.role not in ("hr_admin", "hr_manager"):
        raise HTTPException(status_code=403, detail="HR Yöneticisi veya Admin yetkisi gerekli")
    return current_user
