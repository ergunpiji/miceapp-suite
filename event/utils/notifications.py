"""
E-dem — Bildirim yardımcıları
Deduplication ile Notification kaydı oluşturur.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def create_notification(
    db: "Session",
    user_id: str,
    notif_type: str,
    title: str,
    message: str = "",
    link: str = "",
    ref_id: str = "",
) -> None:
    """
    Deduplication ile bildirim oluştur.
    Aynı (user_id, notif_type, ref_id) için okunmamış bildirim varsa yeni kayıt açılmaz.
    db.commit() çağrıyı yapan yer sorumludur.
    """
    from models import Notification, _uuid, _now

    existing = (
        db.query(Notification)
        .filter(
            Notification.user_id    == user_id,
            Notification.notif_type == notif_type,
            Notification.ref_id     == ref_id,
            Notification.read_at    == None,  # noqa: E711
        )
        .first()
    )
    if existing:
        return

    n = Notification(
        id         = _uuid(),
        user_id    = user_id,
        notif_type = notif_type,
        title      = title,
        message    = message,
        link       = link,
        ref_id     = ref_id,
        created_at = _now(),
    )
    db.add(n)
