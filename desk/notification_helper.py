"""
Bildirim yardımcısı — GM (veya yetkili) bir onay/red işlemi yaptığında
ilgili kişiye in-app notification oluşturur.

Kullanım:
    from notification_helper import notify
    notify(db, user_id=adv.employee.user_id, title="Avansınız onaylandı",
           message="Ergun Piji tarafından onaylandı.", link="/advances/42",
           notif_type="success")
    # db.commit() çağrısından önce yapılmalı; aynı transaction'a girer.
"""
from __future__ import annotations
from models import Notification, _now


def notify(
    db,
    user_id: int | None,
    title: str,
    message: str = "",
    link: str = "",
    notif_type: str = "info",
    ref_id: int | None = None,
) -> None:
    """Kullanıcıya bildirim ekler. user_id None ise sessizce atlar."""
    if not user_id:
        return
    db.add(Notification(
        user_id=user_id,
        notif_type=notif_type,
        title=title,
        message=message or None,
        link=link or None,
        ref_id=ref_id,
        created_at=_now(),
    ))
