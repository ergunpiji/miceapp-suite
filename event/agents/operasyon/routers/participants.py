from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from templates_config import templates
from sqlalchemy.orm import Session

from config import url
from database import get_db
from models import Event, Participant, AccommodationRecord, FlightRecord, TransferRecord

router = APIRouter(prefix="/events/{event_id}/participants", tags=["participants"])


@router.get("/", response_class=HTMLResponse)
async def list_participants(
    request: Request,
    event_id: str,
    search: str = Query(""),
    status: str = Query(""),
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return RedirectResponse(url=url("/events"))

    q = db.query(Participant).filter(Participant.event_id == event_id)
    if search:
        q = q.filter(
            (Participant.first_name.ilike(f"%{search}%")) |
            (Participant.last_name.ilike(f"%{search}%")) |
            (Participant.company.ilike(f"%{search}%")) |
            (Participant.email.ilike(f"%{search}%"))
        )
    participants = q.order_by(Participant.last_name, Participant.first_name).all()

    if status:
        participants = [p for p in participants if p.status == status]

    return templates.TemplateResponse("participants/list.html", {
        "request": request,
        "event": event,
        "participants": participants,
        "search": search,
        "status_filter": status,
        "active": "participants"
    })


@router.get("/new", response_class=HTMLResponse)
async def new_participant_form(request: Request, event_id: str, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    return templates.TemplateResponse("participants/form.html", {
        "request": request,
        "event": event,
        "participant": None,
        "active": "participants"
    })


@router.post("/new")
async def create_participant(
    event_id: str,
    first_name: str = Form(...),
    last_name: str = Form(...),
    company: str = Form(""),
    title: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    badge_name: str = Form(""),
    dietary: str = Form(""),
    special_needs: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db)
):
    p = Participant(
        event_id=event_id,
        first_name=first_name,
        last_name=last_name,
        company=company or None,
        title=title or None,
        email=email or None,
        phone=phone or None,
        badge_name=badge_name or None,
        dietary=dietary or None,
        special_needs=special_needs or None,
        notes=notes or None,
    )
    db.add(p)
    db.commit()
    return RedirectResponse(url=url(f"/events/{event_id}/participants/{p.id}"), status_code=303)


@router.get("/{participant_id}", response_class=HTMLResponse)
async def participant_card(
    request: Request,
    event_id: str,
    participant_id: str,
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    participant = db.query(Participant).filter(
        Participant.id == participant_id,
        Participant.event_id == event_id
    ).first()
    if not participant:
        return RedirectResponse(url=url(f"/events/{event_id}/participants"))

    # Uçuşları yükle
    flights = db.query(FlightRecord).filter(
        FlightRecord.participant_id == participant_id
    ).all()
    flight_in = next((f for f in flights if f.direction == "in"), None)
    flight_out = next((f for f in flights if f.direction == "out"), None)

    accommodation = db.query(AccommodationRecord).filter(
        AccommodationRecord.participant_id == participant_id
    ).first()

    transfers = db.query(TransferRecord).filter(
        TransferRecord.participant_id == participant_id
    ).order_by(TransferRecord.direction).all()
    transfer_in = next((t for t in transfers if t.direction == "in"), None)
    transfer_out = next((t for t in transfers if t.direction == "out"), None)

    # Oda arkadaşı bilgisi
    roommate = None
    if accommodation and accommodation.roommate_id:
        roommate = db.query(Participant).filter(
            Participant.id == accommodation.roommate_id
        ).first()

    return templates.TemplateResponse("participants/card.html", {
        "request": request,
        "event": event,
        "participant": participant,
        "flight_in": flight_in,
        "flight_out": flight_out,
        "accommodation": accommodation,
        "transfer_in": transfer_in,
        "transfer_out": transfer_out,
        "roommate": roommate,
        "active": "participants"
    })


@router.get("/{participant_id}/edit", response_class=HTMLResponse)
async def edit_participant_form(
    request: Request,
    event_id: str,
    participant_id: str,
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    participant = db.query(Participant).filter(
        Participant.id == participant_id,
        Participant.event_id == event_id
    ).first()
    if not participant:
        return RedirectResponse(url=url(f"/events/{event_id}/participants"))
    return templates.TemplateResponse("participants/form.html", {
        "request": request,
        "event": event,
        "participant": participant,
        "active": "participants"
    })


@router.post("/{participant_id}/edit")
async def update_participant(
    event_id: str,
    participant_id: str,
    first_name: str = Form(...),
    last_name: str = Form(...),
    company: str = Form(""),
    title: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    badge_name: str = Form(""),
    dietary: str = Form(""),
    special_needs: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db)
):
    p = db.query(Participant).filter(
        Participant.id == participant_id,
        Participant.event_id == event_id
    ).first()
    if p:
        p.first_name = first_name
        p.last_name = last_name
        p.company = company or None
        p.title = title or None
        p.email = email or None
        p.phone = phone or None
        p.badge_name = badge_name or None
        p.dietary = dietary or None
        p.special_needs = special_needs or None
        p.notes = notes or None
        db.commit()
    return RedirectResponse(url=url(f"/events/{event_id}/participants/{participant_id}"), status_code=303)


@router.post("/{participant_id}/delete")
async def delete_participant(event_id: str, participant_id: str, db: Session = Depends(get_db)):
    p = db.query(Participant).filter(
        Participant.id == participant_id,
        Participant.event_id == event_id
    ).first()
    if p:
        db.delete(p)
        db.commit()
    return RedirectResponse(url=url(f"/events/{event_id}/participants"), status_code=303)
