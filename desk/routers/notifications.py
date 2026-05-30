"""
E-dem — Bildirim Endpoint'leri
GET  /notifications/count   → {count: int}
GET  /notifications         → [{id, type, title, message, link, created_at, read_at}, ...]
POST /notifications/read-all → tümünü okundu işaretle
POST /notifications/{id}/read → tek bildirimi okundu işaretle
"""
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Notification, User, _now

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/count", name="notifications_count")
async def notifications_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    count = (
        db.query(Notification)
        .filter(
            Notification.user_id == current_user.id,
            Notification.read_at == None,  # noqa: E711
        )
        .count()
    )
    return JSONResponse({"count": count})


@router.get("", name="notifications_list")
async def notifications_list(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notifs = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(40)
        .all()
    )
    return JSONResponse([
        {
            "id":         n.id,
            "type":       n.notif_type,
            "title":      n.title,
            "message":    n.message,
            "link":       n.link,
            "ref_id":     n.ref_id,
            "read":       n.read_at is not None,
            "created_at": n.created_at.strftime("%d.%m.%Y %H:%M") if n.created_at else "",
        }
        for n in notifs
    ])


@router.post("/read-all", name="notifications_read_all")
async def notifications_read_all(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.read_at == None,  # noqa: E711
    ).update({"read_at": _now()})
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/{notif_id}/read", name="notifications_read_one")
async def notifications_read_one(
    notif_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    n = db.query(Notification).filter(
        Notification.id      == notif_id,
        Notification.user_id == current_user.id,
    ).first()
    if n and not n.read_at:
        n.read_at = _now()
        db.commit()
    return JSONResponse({"ok": True})
