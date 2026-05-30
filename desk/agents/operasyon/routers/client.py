"""
Müşteri / Katılımcı Portalı — Salt-okunur etkinlik görünümü.
/client/{token}  →  etkinlik özeti + program + katılımcı istatistikleri
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from collections import OrderedDict

from config import now_tr
from database import get_db
from models import Event, UserToken, Participant, AgendaSession, SESSION_TYPES, AccommodationRecord, TransferRecord
from templates_config import templates

router = APIRouter(tags=["client"])


@router.get("/client/{token}", response_class=HTMLResponse)
async def client_portal(
    request: Request,
    token: str,
    db: Session = Depends(get_db),
):
    """Müşteri/Katılımcı salt-okunur portalı. Token ile erişilir, login gerekmez."""
    ut = db.query(UserToken).filter(
        UserToken.token == token,
        UserToken.role == "client",
        UserToken.active == True,
    ).first()

    if not ut:
        return HTMLResponse("""
        <html><body style='font-family:sans-serif;text-align:center;padding:60px'>
        <h2>❌ Geçersiz veya süresi dolmuş bağlantı</h2>
        <p>Bu link artık aktif değil. Proje yöneticinizden yeni bir link isteyin.</p>
        </body></html>
        """, status_code=404)

    # Son kullanım zamanını güncelle
    ut.last_used_at = now_tr()
    db.commit()

    event = db.query(Event).filter(Event.id == ut.event_id).first()
    if not event:
        return HTMLResponse("<h2>Etkinlik bulunamadı.</h2>", status_code=404)

    # Program — güne göre grupla
    sessions = (
        db.query(AgendaSession)
        .filter(AgendaSession.event_id == event.id)
        .order_by(AgendaSession.session_date, AgendaSession.start_time, AgendaSession.sort_order)
        .all()
    )
    by_day: dict = OrderedDict()
    for s in sessions:
        key = s.session_date
        if key not in by_day:
            by_day[key] = []
        by_day[key].append(s)

    # Katılımcı istatistikleri
    participants = db.query(Participant).filter(Participant.event_id == event.id).all()
    participant_count = len(participants)
    complete_count = sum(1 for p in participants if p.status == "complete")
    warning_count  = sum(1 for p in participants if p.status == "warning")

    # Konaklama check-in durumu
    accommodations = (
        db.query(AccommodationRecord)
        .join(Participant, AccommodationRecord.participant_id == Participant.id)
        .filter(Participant.event_id == event.id)
        .order_by(AccommodationRecord.checked_in.desc(), AccommodationRecord.hotel, Participant.last_name)
        .all()
    )
    acc_checked_in = sum(1 for a in accommodations if a.checked_in)

    # Transfer biniş durumu — gruba göre sırala
    transfers = (
        db.query(TransferRecord)
        .join(Participant, TransferRecord.participant_id == Participant.id)
        .filter(Participant.event_id == event.id)
        .order_by(TransferRecord.boarded.desc(), TransferRecord.transfer_date, TransferRecord.pickup_time, Participant.last_name)
        .all()
    )
    transfer_boarded = sum(1 for t in transfers if t.boarded)

    # Transfer'ları gruba göre grupla (araç grubu veya tarih+saat)
    from collections import defaultdict
    transfer_groups: dict = defaultdict(list)
    for t in transfers:
        if t.vehicle_group:
            key = t.vehicle_group
        elif t.transfer_date:
            direction = "Karşılama" if t.direction == "in" else "Gidiş"
            key = f"{direction} · {t.transfer_date.strftime('%d.%m.%Y')}"
            if t.pickup_time:
                key += f" · {t.pickup_time}"
        else:
            key = "Karşılama" if t.direction == "in" else "Gidiş"
        transfer_groups[key].append(t)

    return templates.TemplateResponse("client/overview.html", {
        "request":          request,
        "event":            event,
        "by_day":           by_day,
        "session_types":    SESSION_TYPES,
        "participant_count": participant_count,
        "complete_count":   complete_count,
        "warning_count":    warning_count,
        "accommodations":   accommodations,
        "acc_checked_in":   acc_checked_in,
        "transfers":        transfers,
        "transfer_boarded": transfer_boarded,
        "transfer_groups":  dict(transfer_groups),
        "token":            token,
    })
