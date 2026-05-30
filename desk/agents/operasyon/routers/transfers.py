from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from templates_config import templates
from sqlalchemy.orm import Session
from datetime import date, datetime, timedelta
from collections import defaultdict
from typing import List

from config import url
from database import get_db
from models import Event, Participant, TransferRecord, FlightRecord

router = APIRouter(prefix="/events/{event_id}", tags=["transfers"])


def _time_to_minutes(t: str | None) -> int | None:
    """'HH:MM' → dakika cinsinden tam sayı. Hatalıysa None."""
    if not t:
        return None
    try:
        h, m = t.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _add_minutes_str(t: str, delta: int) -> str:
    """'HH:MM' formatına delta dakika ekle, 'HH:MM' döndür."""
    mins = _time_to_minutes(t)
    if mins is None:
        return t
    total = max(0, min(mins + delta, 23 * 60 + 59))
    return f"{total // 60:02d}:{total % 60:02d}"


@router.get("/transfers", response_class=HTMLResponse)
async def transfer_list(
    request: Request,
    event_id: str,
    direction: str = Query(""),
    status: str = Query(""),
    search: str = Query(""),
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return RedirectResponse(url=url("/events"))

    q = db.query(TransferRecord).join(Participant).filter(Participant.event_id == event_id)
    if direction:
        q = q.filter(TransferRecord.direction == direction)
    if status == "boarded":
        q = q.filter(TransferRecord.boarded == True)
    elif status == "pending":
        q = q.filter(TransferRecord.boarded == False)
    if search:
        q = q.filter(
            (Participant.first_name.ilike(f"%{search}%")) |
            (Participant.last_name.ilike(f"%{search}%"))
        )

    transfers = q.order_by(
        TransferRecord.direction,
        TransferRecord.transfer_date,
        TransferRecord.pickup_time
    ).all()

    # Grupla:
    #  - Karşılama (in): (tarih, pickup_time) çifti — "Karşılama 13 Nis 07:30"
    #  - Gidiş (out): vehicle_group'a göre (wizard tarafından atanan)
    from datetime import date as date_type
    groups: dict[str, list] = defaultdict(list)
    for t in transfers:
        if t.direction == "in":
            tarih = t.transfer_date.strftime("%d %b") if t.transfer_date else "?"
            saat = t.pickup_time or "Saat Belirsiz"
            key = f"Karşılama · {tarih} · {saat}"
        else:
            key = t.vehicle_group or "Gidiş"
        groups[key].append(t)

    # Grupları önce transfer_date, sonra pickup_time'a göre sırala
    def group_sort_key(kv):
        items = kv[1]
        earliest_date = min(
            (t.transfer_date or date_type.min) for t in items
        )
        earliest_time = min(
            (t.pickup_time or "99:99") for t in items
        )
        return (earliest_date, earliest_time)

    sorted_groups = dict(sorted(groups.items(), key=group_sort_key))

    return templates.TemplateResponse("transfers/list.html", {
        "request": request,
        "event": event,
        "transfers": transfers,
        "groups": sorted_groups,
        "direction_filter": direction,
        "status_filter": status,
        "search": search,
        "active": "transfers"
    })


@router.get("/participants/{participant_id}/transfers/new", response_class=HTMLResponse)
async def new_transfer_form(
    request: Request,
    event_id: str,
    participant_id: str,
    direction: str = Query("in"),
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    participant = db.query(Participant).filter(
        Participant.id == participant_id, Participant.event_id == event_id
    ).first()
    return templates.TemplateResponse("transfers/form.html", {
        "request": request,
        "event": event,
        "participant": participant,
        "transfer": None,
        "direction": direction,
        "active": "transfers"
    })


@router.post("/participants/{participant_id}/transfers/new")
async def create_transfer(
    event_id: str,
    participant_id: str,
    direction: str = Form(...),
    transfer_date: date = Form(None),
    pickup_time: str = Form(""),
    from_location: str = Form(""),
    to_location: str = Form(""),
    vehicle_group: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db)
):
    existing = db.query(TransferRecord).filter(
        TransferRecord.participant_id == participant_id,
        TransferRecord.direction == direction
    ).first()

    if existing:
        t = existing
    else:
        t = TransferRecord(participant_id=participant_id, direction=direction)
        db.add(t)

    t.transfer_date = transfer_date
    t.pickup_time = pickup_time or None
    t.from_location = from_location or None
    t.to_location = to_location or None
    t.vehicle_group = vehicle_group or None
    t.notes = notes or None
    db.commit()

    return RedirectResponse(
        url=url(f"/events/{event_id}/participants/{participant_id}"), status_code=303
    )


@router.post("/participants/{participant_id}/transfers/{transfer_id}/delete")
async def delete_transfer(
    event_id: str,
    participant_id: str,
    transfer_id: str,
    db: Session = Depends(get_db)
):
    t = db.query(TransferRecord).filter(TransferRecord.id == transfer_id).first()
    if t:
        db.delete(t)
        db.commit()
    return RedirectResponse(
        url=url(f"/events/{event_id}/participants/{participant_id}"), status_code=303
    )


# ---------------------------------------------------------------------------
# Transfer Sihirbazı
# ---------------------------------------------------------------------------

@router.get("/transfers/wizard", response_class=HTMLResponse)
async def transfer_wizard(request: Request, event_id: str, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return RedirectResponse(url=url("/events"))

    # Uçuşu olan katılımcıları getir
    participants = db.query(Participant).filter(Participant.event_id == event_id).all()
    with_flight_in  = [p for p in participants if p.flight_in]
    with_flight_out = [p for p in participants if p.flight_out]

    # Etkinlik mekanını varsayılan konum olarak öner
    default_venue = event.venue or ""
    default_city  = event.city or ""

    return templates.TemplateResponse("transfers/wizard.html", {
        "request": request,
        "event": event,
        "with_flight_in": with_flight_in,
        "with_flight_out": with_flight_out,
        "default_venue": default_venue,
        "default_city": default_city,
        "active": "transfers"
    })


@router.post("/transfers/wizard/generate")
async def transfer_wizard_generate(
    request: Request,
    event_id: str,
    # Seçilen katılımcılar
    arrival_ids:   List[str] = Form(default=[]),
    departure_ids: List[str] = Form(default=[]),
    # Karşılama ayarları
    arrival_buffer:   int  = Form(60),      # iniş saatinden kaç dk sonra
    arrival_from:     str  = Form(""),      # nereden (havalimanı)
    arrival_to:       str  = Form(""),      # nereye (otel)
    # Dönüş ayarları
    departure_lead:   int  = Form(120),     # kalkıştan kaç dk önce
    departure_from:   str  = Form(""),      # nereden (otel)
    departure_to:     str  = Form(""),      # nereye (havalimanı)
    group_threshold:  int  = Form(60),      # birleştirme eşiği (dakika)
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return RedirectResponse(url=url("/events"))

    created = 0

    # ── Karşılama transferleri ───────────────────────────────────────────────
    for pid in arrival_ids:
        p = db.query(Participant).filter(
            Participant.id == pid, Participant.event_id == event_id
        ).first()
        if not p or not p.flight_in:
            continue

        # Zaten varış transferi varsa atla
        existing = db.query(TransferRecord).filter(
            TransferRecord.participant_id == pid,
            TransferRecord.direction == "in"
        ).first()
        if existing:
            continue

        fi = p.flight_in
        pickup = _add_minutes_str(fi.arrival_time or "12:00", arrival_buffer)

        t = TransferRecord(
            participant_id=pid,
            direction="in",
            transfer_date=fi.flight_date,
            pickup_time=pickup,
            from_location=arrival_from or fi.arrival_airport or "",
            to_location=arrival_to or event.venue or "",
            vehicle_group="",          # karşılamada bireysel
            linked_flight_id=fi.id,
        )
        db.add(t)
        created += 1

    # ── Dönüş transferleri + gruplama ────────────────────────────────────────
    # Önce uçuşları kalkış saatine göre sırala
    departure_participants = []
    for pid in departure_ids:
        p = db.query(Participant).filter(
            Participant.id == pid, Participant.event_id == event_id
        ).first()
        if not p or not p.flight_out:
            continue
        existing = db.query(TransferRecord).filter(
            TransferRecord.participant_id == pid,
            TransferRecord.direction == "out"
        ).first()
        if existing:
            continue
        departure_participants.append(p)

    # Kalkış saatine göre sırala
    departure_participants.sort(
        key=lambda p: (
            p.flight_out.flight_date or date.min,
            _time_to_minutes(p.flight_out.departure_time) or 0
        )
    )

    # Gruplama: aynı gün, threshold dakika içinde → aynı grup
    groups: list[list] = []
    for p in departure_participants:
        fo = p.flight_out
        p_mins = _time_to_minutes(fo.departure_time)
        p_date = fo.flight_date

        placed = False
        for g in groups:
            last = g[-1]
            last_fo = last.flight_out
            last_mins = _time_to_minutes(last_fo.departure_time)
            last_date = last_fo.flight_date
            if (p_date == last_date and
                    p_mins is not None and last_mins is not None and
                    abs(p_mins - last_mins) <= group_threshold):
                g.append(p)
                placed = True
                break
        if not placed:
            groups.append([p])

    # Her grup için transfer kayıtları oluştur
    for g_idx, group in enumerate(groups, 1):
        group_name = f"Dönüş Grubu {g_idx}" if len(groups) > 1 else "Dönüş"
        # Grubun en erken kalkışına göre pickup saatini hesapla
        earliest_mins = min(
            (_time_to_minutes(p.flight_out.departure_time) or 9999)
            for p in group
        )
        pickup_mins = max(0, earliest_mins - departure_lead)
        pickup_time = f"{pickup_mins // 60:02d}:{pickup_mins % 60:02d}"
        transfer_date = group[0].flight_out.flight_date

        for p in group:
            fo = p.flight_out
            t = TransferRecord(
                participant_id=p.id,
                direction="out",
                transfer_date=transfer_date,
                pickup_time=pickup_time,
                from_location=departure_from or event.venue or "",
                to_location=departure_to or fo.departure_airport or "",
                vehicle_group=group_name,
                linked_flight_id=fo.id,
            )
            db.add(t)
            created += 1

    db.commit()
    return RedirectResponse(
        url=url(f"/events/{event_id}/transfers?wizard_created={created}"),
        status_code=303
    )


# ---------------------------------------------------------------------------
# Uçuş Detay Doldurma (tek uçuş — AJAX)
# ---------------------------------------------------------------------------

@router.get("/flights/lookup", response_class=HTMLResponse)
async def lookup_flight_details(
    request: Request,
    event_id: str,
    flight_number: str = Query(""),
    flight_date: str = Query(""),
    db: Session = Depends(get_db)
):
    """Uçuş numarasından detay döner (JSON). Uçuş formundan AJAX ile çağrılır."""
    from fastapi.responses import JSONResponse
    from services.flight_lookup import lookup_flight

    if not flight_number:
        return JSONResponse({"error": "flight_number gerekli"}, status_code=400)

    result = lookup_flight(flight_number, flight_date or None)
    if result:
        return JSONResponse(result)
    return JSONResponse({"error": "Uçuş bulunamadı"}, status_code=404)


@router.post("/flights/fill-missing")
async def fill_missing_flight_details(
    event_id: str,
    db: Session = Depends(get_db)
):
    """
    Etkinlikteki tüm uçuşları tarar; havalimanı veya saat eksik olanları
    Claude'a sorarak tamamlar.
    """
    from services.flight_lookup import lookup_flights_batch

    flights = db.query(FlightRecord).join(Participant).filter(
        Participant.event_id == event_id
    ).all()

    # Eksik alanı olan uçuşları seç
    to_fill = [
        {
            "id": f.id,
            "flight_number": f.flight_number,
            "flight_date": str(f.flight_date) if f.flight_date else None,
        }
        for f in flights
        if f.flight_number and (
            not f.departure_airport or not f.arrival_airport or
            not f.departure_time or not f.arrival_time
        )
    ]

    filled = 0
    if to_fill:
        results = lookup_flights_batch(to_fill)
        for f in flights:
            r = results.get(f.id)
            if not r:
                continue
            if not f.airline and r.get("airline"):
                f.airline = r["airline"]
            if not f.departure_airport and r.get("departure_airport"):
                f.departure_airport = r["departure_airport"]
            if not f.arrival_airport and r.get("arrival_airport"):
                f.arrival_airport = r["arrival_airport"]
            if not f.departure_time and r.get("departure_time"):
                f.departure_time = r["departure_time"]
            if not f.arrival_time and r.get("arrival_time"):
                f.arrival_time = r["arrival_time"]
            filled += 1
        db.commit()

    return RedirectResponse(
        url=f"/events/{event_id}/flights?filled={filled}",
        status_code=303
    )


# ---------------------------------------------------------------------------
# Uçuş Doğrulama
# ---------------------------------------------------------------------------

@router.get("/flights/validate", response_class=HTMLResponse)
async def validate_flights_page(
    request: Request, event_id: str, db: Session = Depends(get_db)
):
    """Tüm etkinlik uçuşlarını Claude ile doğrula ve sonuçları kaydet."""
    from services.flight_checker import check_flights_batch
    import json

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return RedirectResponse(url=url("/events"))

    flights = db.query(FlightRecord).join(Participant).filter(
        Participant.event_id == event_id
    ).all()

    if not flights:
        return RedirectResponse(url=f"/events/{event_id}/flights")

    # Doğrulama için veri hazırla
    batch = [
        {
            "id": f.id,
            "flight_number": f.flight_number,
            "departure_airport": f.departure_airport,
            "arrival_airport": f.arrival_airport,
            "flight_date": str(f.flight_date) if f.flight_date else None,
            "departure_time": f.departure_time,
            "arrival_time": f.arrival_time,
        }
        for f in flights
    ]

    results = check_flights_batch(batch)

    # Sonuçları kaydet
    result_map = {r["id"]: r for r in results if "id" in r}
    for f in flights:
        r = result_map.get(f.id, {})
        f.validation_status = r.get("status")
        f.validation_issues = json.dumps(r.get("issues", []), ensure_ascii=False)
        corrected = r.get("corrected", {})
        f.validated_departure_time    = corrected.get("departure_time")
        f.validated_arrival_time      = corrected.get("arrival_time")
        f.validated_departure_airport = corrected.get("departure_airport")
        f.validated_arrival_airport   = corrected.get("arrival_airport")

    db.commit()
    return RedirectResponse(url=f"/events/{event_id}/flights?validated=1", status_code=303)
