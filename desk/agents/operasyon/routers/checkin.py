"""
Check-in (konaklama) ve Boarding (transfer) işlemleri
PM ve tedarikçi token erişimi için ortak route'lar.
"""
import sys as _sys
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from templates_config import templates
from sqlalchemy.orm import Session
from typing import List

from config import url, now_tr
from database import get_db
from models import Event, Participant, AccommodationRecord, TransferRecord, Notification, SupplierTask, TASK_STATUSES, SUPPLIER_TASK_TYPES


def _ensure_tables():
    """Eksik tablolar varsa oluştur (notifications gibi)."""
    db_mod = _sys.modules.get("_oa.database") or _sys.modules.get("database")
    if db_mod and hasattr(db_mod, "init_db"):
        try:
            db_mod.init_db()
        except Exception:
            pass

router = APIRouter(tags=["checkin"])


def _new_id():
    import uuid
    return str(uuid.uuid4())


def _create_notification(db: Session, event_id: str, actor: str,
                          action: str, participant_name: str, detail: str | None = None):
    notif = Notification(
        id=_new_id(),
        event_id=event_id,
        actor=actor,
        action=action,
        participant_name=participant_name,
        detail=detail,
        created_at=now_tr(),
    )
    db.add(notif)


# ---------------------------------------------------------------------------
# Konaklama — Tekil Check-in (PM)
# ---------------------------------------------------------------------------
@router.post("/events/{event_id}/accommodations/{acc_id}/checkin")
async def checkin_accommodation(
    event_id: str,
    acc_id: str,
    db: Session = Depends(get_db),
    redirect_to: str = Form("/")
):
    acc = db.query(AccommodationRecord).filter(AccommodationRecord.id == acc_id).first()
    if acc:
        acc.checked_in = not acc.checked_in
        if acc.checked_in:
            acc.checked_in_at = now_tr()
            acc.checked_in_by = "PM"
            _create_notification(
                db, event_id, "PM", "checked_in",
                acc.participant.full_name,
                acc.hotel or None
            )
        else:
            acc.checked_in_at = None
            acc.checked_in_by = None
        db.commit()
    return RedirectResponse(url=redirect_to, status_code=303)


# ---------------------------------------------------------------------------
# Transfer — Tekil Boarding (PM)
# ---------------------------------------------------------------------------
@router.post("/events/{event_id}/transfers/{transfer_id}/board")
async def board_transfer(
    event_id: str,
    transfer_id: str,
    db: Session = Depends(get_db),
    redirect_to: str = Form("/")
):
    t = db.query(TransferRecord).filter(TransferRecord.id == transfer_id).first()
    if t:
        t.boarded = not t.boarded
        if t.boarded:
            t.boarded_at = now_tr()
            t.boarded_by = "PM"
            _create_notification(
                db, event_id, "PM", "boarded",
                t.participant.full_name,
                t.vehicle_group or None
            )
        else:
            t.boarded_at = None
            t.boarded_by = None
        db.commit()
    return RedirectResponse(url=redirect_to, status_code=303)


# ---------------------------------------------------------------------------
# Konaklama — Toplu Check-in (PM)
# ---------------------------------------------------------------------------
@router.post("/events/{event_id}/accommodations/bulk-checkin")
async def bulk_checkin(
    event_id: str,
    acc_ids: List[str] = Form(default=[]),
    db: Session = Depends(get_db)
):
    now = now_tr()
    for acc_id in acc_ids:
        acc = db.query(AccommodationRecord).filter(AccommodationRecord.id == acc_id).first()
        if acc and not acc.checked_in:
            acc.checked_in = True
            acc.checked_in_at = now
            acc.checked_in_by = "PM"
            _create_notification(
                db, event_id, "PM", "checked_in",
                acc.participant.full_name,
                acc.hotel or None
            )
    db.commit()
    return RedirectResponse(
        url=url(f"/events/{event_id}/accommodations?checked_in=1"),
        status_code=303
    )


# ---------------------------------------------------------------------------
# Transfer — Toplu Boarding (PM)
# ---------------------------------------------------------------------------
@router.post("/events/{event_id}/transfers/bulk-board")
async def bulk_board(
    event_id: str,
    transfer_ids: List[str] = Form(default=[]),
    db: Session = Depends(get_db)
):
    now = now_tr()
    for tid in transfer_ids:
        t = db.query(TransferRecord).filter(TransferRecord.id == tid).first()
        if t and not t.boarded:
            t.boarded = True
            t.boarded_at = now
            t.boarded_by = "PM"
            _create_notification(
                db, event_id, "PM", "boarded",
                t.participant.full_name,
                t.vehicle_group or None
            )
    db.commit()
    return RedirectResponse(
        url=url(f"/events/{event_id}/transfers?boarded=1"),
        status_code=303
    )


# ---------------------------------------------------------------------------
# Tedarikçi Ekranı — Transfer linki: /supplier/{token}/transfers
# ---------------------------------------------------------------------------
@router.get("/supplier/{token}/transfers", response_class=HTMLResponse)
async def supplier_transfers(
    request: Request,
    token: str,
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.supplier_token == token).first()
    if not event:
        return HTMLResponse("<h2>Geçersiz bağlantı.</h2>", status_code=404)

    from collections import defaultdict
    from datetime import date as date_type

    transfers = (
        db.query(TransferRecord)
        .join(Participant, TransferRecord.participant_id == Participant.id)
        .filter(Participant.event_id == event.id)
        .order_by(TransferRecord.direction, TransferRecord.transfer_date, TransferRecord.pickup_time)
        .all()
    )

    groups: dict = defaultdict(list)
    for t in transfers:
        if t.direction == "in":
            tarih = t.transfer_date.strftime("%d %b") if t.transfer_date else "?"
            saat = t.pickup_time or "Saat Belirsiz"
            key = f"Karşılama · {tarih} · {saat}"
        else:
            key = t.vehicle_group or "Gidiş"
        groups[key].append(t)

    def group_sort_key(kv):
        items = kv[1]
        earliest_date = min((t.transfer_date or date_type.min) for t in items)
        earliest_time = min((t.pickup_time or "99:99") for t in items)
        return (earliest_date, earliest_time)

    from services.edem_bridge import get_reference as _edem_ref, is_available as _edem_ok
    edem_ref = _edem_ref(event.edem_request_id) if event.edem_request_id and _edem_ok() else None

    return templates.TemplateResponse("supplier/transfers.html", {
        "request": request,
        "event": event,
        "token": token,
        "transfers": transfers,
        "groups": dict(sorted(groups.items(), key=group_sort_key)),
        "edem_ref": edem_ref,
    })


# ---------------------------------------------------------------------------
# Tedarikçi Ekranı — Konaklama linki: /supplier/{token}/accommodations
# ---------------------------------------------------------------------------
@router.get("/supplier/{token}/accommodations", response_class=HTMLResponse)
async def supplier_accommodations(
    request: Request,
    token: str,
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.supplier_token == token).first()
    if not event:
        return HTMLResponse("<h2>Geçersiz bağlantı.</h2>", status_code=404)

    accommodations = (
        db.query(AccommodationRecord)
        .join(Participant, AccommodationRecord.participant_id == Participant.id)
        .filter(Participant.event_id == event.id)
        .order_by(AccommodationRecord.check_in, AccommodationRecord.hotel, AccommodationRecord.room_number)
        .all()
    )

    from services.edem_bridge import get_reference as _edem_ref, is_available as _edem_ok
    edem_ref = _edem_ref(event.edem_request_id) if event.edem_request_id and _edem_ok() else None

    return templates.TemplateResponse("supplier/accommodations.html", {
        "request": request,
        "event": event,
        "token": token,
        "accommodations": accommodations,
        "edem_ref": edem_ref,
    })


# ---------------------------------------------------------------------------
# Tedarikçi — Tekil Check-in
# ---------------------------------------------------------------------------
@router.post("/supplier/{token}/accommodations/{acc_id}/checkin")
async def supplier_checkin(
    token: str,
    acc_id: str,
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.supplier_token == token).first()
    if not event:
        return HTMLResponse("Geçersiz token", status_code=403)

    acc = db.query(AccommodationRecord).filter(AccommodationRecord.id == acc_id).first()
    if acc and not acc.checked_in:
        supplier_label = f"Tedarikçi"
        acc.checked_in = True
        acc.checked_in_at = now_tr()
        acc.checked_in_by = supplier_label
        _create_notification(
            db, event.id, supplier_label, "checked_in",
            acc.participant.full_name,
            acc.hotel or None
        )
        db.commit()
    return RedirectResponse(url=url(f"/supplier/{token}/accommodations"), status_code=303)


# ---------------------------------------------------------------------------
# Tedarikçi — Tekil Boarding
# ---------------------------------------------------------------------------
@router.post("/supplier/{token}/transfers/{transfer_id}/board")
async def supplier_board(
    token: str,
    transfer_id: str,
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.supplier_token == token).first()
    if not event:
        return HTMLResponse("Geçersiz token", status_code=403)

    t = db.query(TransferRecord).filter(TransferRecord.id == transfer_id).first()
    if t and not t.boarded:
        supplier_label = f"Tedarikçi"
        t.boarded = True
        t.boarded_at = now_tr()
        t.boarded_by = supplier_label
        _create_notification(
            db, event.id, supplier_label, "boarded",
            t.participant.full_name,
            t.vehicle_group or None
        )
        db.commit()
    return RedirectResponse(url=url(f"/supplier/{token}/transfers"), status_code=303)


# ---------------------------------------------------------------------------
# Tedarikçi Ekranı — Görev Portalı: /supplier/{token}/tasks
# ---------------------------------------------------------------------------
@router.get("/supplier/{token}/tasks", response_class=HTMLResponse)
async def supplier_tasks(
    request: Request,
    token: str,
    status: str = "",
    db: Session = Depends(get_db)
):
    """Teknik/Dekor/Diğer tedarikçiler için görev listesi portalı."""
    from collections import defaultdict

    event = db.query(Event).filter(Event.supplier_token == token).first()
    if not event:
        return HTMLResponse("<h2>Geçersiz bağlantı.</h2>", status_code=404)

    q = db.query(SupplierTask).filter(SupplierTask.event_id == event.id)
    if status:
        q = q.filter(SupplierTask.status == status)

    tasks = q.order_by(SupplierTask.task_date, SupplierTask.task_time, SupplierTask.supplier_name).all()

    # Tedarikçiye göre grupla
    by_supplier: dict = defaultdict(list)
    for t in tasks:
        by_supplier[t.supplier_name].append(t)

    # İstatistikler
    all_tasks = db.query(SupplierTask).filter(SupplierTask.event_id == event.id).all()
    stats = {s: sum(1 for t in all_tasks if t.status == s) for s in TASK_STATUSES}

    return templates.TemplateResponse("supplier/tasks.html", {
        "request": request,
        "event": event,
        "token": token,
        "tasks": tasks,
        "by_supplier": dict(by_supplier),
        "stats": stats,
        "status_filter": status,
        "task_statuses": TASK_STATUSES,
        "supplier_task_types": SUPPLIER_TASK_TYPES,
    })


@router.post("/supplier/{token}/tasks/{task_id}/status")
async def supplier_update_task_status(
    token: str,
    task_id: str,
    status: str = Form(...),
    db: Session = Depends(get_db)
):
    """Tedarikçi görev durumunu günceller (pending→confirmed→done)."""
    event = db.query(Event).filter(Event.supplier_token == token).first()
    if not event:
        return HTMLResponse("Geçersiz token", status_code=403)

    task = db.query(SupplierTask).filter(
        SupplierTask.id == task_id,
        SupplierTask.event_id == event.id
    ).first()
    if task:
        task.status = status
        db.commit()
    return RedirectResponse(url=url(f"/supplier/{token}/tasks"), status_code=303)


# ---------------------------------------------------------------------------
# Bildirimler — PM okur
# ---------------------------------------------------------------------------
@router.get("/events/{event_id}/notifications", response_class=HTMLResponse)
async def notifications_page(
    request: Request,
    event_id: str,
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return RedirectResponse(url=url("/events"))

    try:
        notifs = (
            db.query(Notification)
            .filter(Notification.event_id == event_id)
            .order_by(Notification.created_at.desc())
            .all()
        )
    except Exception:
        # Tablo mevcut değilse yarat ve tekrar dene
        db.rollback()
        _ensure_tables()
        try:
            notifs = (
                db.query(Notification)
                .filter(Notification.event_id == event_id)
                .order_by(Notification.created_at.desc())
                .all()
            )
        except Exception:
            notifs = []

    # Okunmamışları okundu işaretle
    try:
        unread = [n for n in notifs if not n.read]
        for n in unread:
            n.read = True
        if unread:
            db.commit()
    except Exception:
        db.rollback()

    return templates.TemplateResponse("notifications/list.html", {
        "request": request,
        "event": event,
        "notifications": notifs,
        "active": "notifications"
    })


@router.get("/events/{event_id}/notifications/count")
async def notifications_count(
    event_id: str,
    db: Session = Depends(get_db)
):
    try:
        count = (
            db.query(Notification)
            .filter(Notification.event_id == event_id, Notification.read == False)
            .count()
        )
    except Exception:
        db.rollback()
        _ensure_tables()
        count = 0
    return JSONResponse({"count": count})
