from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from templates_config import templates
from sqlalchemy.orm import Session
from datetime import date

from config import url
from database import get_db
from models import Event, Participant, AccommodationRecord

router = APIRouter(prefix="/events/{event_id}", tags=["accommodations"])


@router.get("/accommodations", response_class=HTMLResponse)
async def accommodation_list(
    request: Request,
    event_id: str,
    hotel: str = Query(""),
    status: str = Query(""),
    search: str = Query(""),
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return RedirectResponse(url=url("/events"))

    q = db.query(AccommodationRecord).join(
        Participant, AccommodationRecord.participant_id == Participant.id
    ).filter(Participant.event_id == event_id)

    if hotel:
        q = q.filter(AccommodationRecord.hotel.ilike(f"%{hotel}%"))
    if status == "checked_in":
        q = q.filter(AccommodationRecord.checked_in == True)
    elif status == "pending":
        q = q.filter(AccommodationRecord.checked_in == False)
    if search:
        q = q.filter(
            (Participant.first_name.ilike(f"%{search}%")) |
            (Participant.last_name.ilike(f"%{search}%"))
        )

    accommodations = q.order_by(
        AccommodationRecord.check_in,
        AccommodationRecord.hotel,
        AccommodationRecord.room_number
    ).all()

    # Benzersiz oteller — filtresiz sorgula
    all_acc = db.query(AccommodationRecord).join(
        Participant, AccommodationRecord.participant_id == Participant.id
    ).filter(Participant.event_id == event_id).all()
    hotels = sorted(set(a.hotel for a in all_acc if a.hotel))

    return templates.TemplateResponse("accommodations/list.html", {
        "request": request,
        "event": event,
        "accommodations": accommodations,
        "hotels": hotels,
        "hotel_filter": hotel,
        "status_filter": status,
        "search": search,
        "active": "accommodations"
    })


@router.get("/participants/{participant_id}/accommodation/new", response_class=HTMLResponse)
async def new_accommodation_form(
    request: Request,
    event_id: str,
    participant_id: str,
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    participant = db.query(Participant).filter(
        Participant.id == participant_id, Participant.event_id == event_id
    ).first()
    other_participants = db.query(Participant).filter(
        Participant.event_id == event_id,
        Participant.id != participant_id
    ).order_by(Participant.last_name).all()
    return templates.TemplateResponse("accommodations/form.html", {
        "request": request,
        "event": event,
        "participant": participant,
        "accommodation": None,
        "other_participants": other_participants,
        "active": "accommodations"
    })


@router.post("/participants/{participant_id}/accommodation/new")
async def create_accommodation(
    event_id: str,
    participant_id: str,
    hotel: str = Form(""),
    room_number: str = Form(""),
    room_type: str = Form(""),
    roommate_id: str = Form(""),
    check_in: date = Form(None),
    check_out: date = Form(None),
    notes: str = Form(""),
    db: Session = Depends(get_db)
):
    existing = db.query(AccommodationRecord).filter(
        AccommodationRecord.participant_id == participant_id
    ).first()

    if existing:
        acc = existing
    else:
        acc = AccommodationRecord(participant_id=participant_id)
        db.add(acc)

    acc.hotel = hotel or None
    acc.room_number = room_number or None
    acc.room_type = room_type or None
    acc.roommate_id = roommate_id or None
    acc.check_in = check_in
    acc.check_out = check_out
    acc.notes = notes or None
    db.commit()

    return RedirectResponse(
        url=url(f"/events/{event_id}/participants/{participant_id}"), status_code=303
    )


@router.post("/participants/{participant_id}/accommodation/delete")
async def delete_accommodation(
    event_id: str,
    participant_id: str,
    db: Session = Depends(get_db)
):
    acc = db.query(AccommodationRecord).filter(
        AccommodationRecord.participant_id == participant_id
    ).first()
    if acc:
        db.delete(acc)
        db.commit()
    return RedirectResponse(
        url=url(f"/events/{event_id}/participants/{participant_id}"), status_code=303
    )
