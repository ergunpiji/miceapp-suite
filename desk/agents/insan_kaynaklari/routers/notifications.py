"""HR Ajanı — In-App Bildirimler."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import HRUser, Notification
from templates_config import templates

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_class=HTMLResponse)
async def list_notifications(
    request: Request,
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notifs = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )
    return templates.TemplateResponse(
        "notifications/list.html",
        {"request": request, "active": "notifications", "user": current_user,
         "notifications": notifs, "unread_count": sum(1 for n in notifs if not n.is_read)},
    )


@router.post("/{notif_id}/read")
async def mark_read(
    notif_id: str,
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notif = db.query(Notification).filter(
        Notification.id == notif_id, Notification.user_id == current_user.id
    ).first()
    if notif:
        notif.is_read = True
        db.commit()
    return JSONResponse({"ok": True})


@router.post("/read-all")
async def mark_all_read(
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(Notification).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).update({"is_read": True})
    db.commit()
    return JSONResponse({"ok": True})


@router.get("/count")
async def unread_count(
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import func
    count = (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == current_user.id, Notification.is_read == False)
        .scalar() or 0
    )
    return JSONResponse({"count": count})


# ---------------------------------------------------------------------------
# Yardımcı fonksiyon — diğer router'lardan çağrılır
# ---------------------------------------------------------------------------
def create_notification(
    db: Session,
    user_id: str,
    notif_type: str,
    title: str,
    body: str = "",
    ref_type: str = "",
    ref_id: str = "",
) -> None:
    notif = Notification(
        user_id=user_id,
        notif_type=notif_type,
        title=title,
        body=body,
        ref_type=ref_type,
        ref_id=ref_id,
    )
    db.add(notif)
    # Commit çağıran router'ın sorumluluğunda
