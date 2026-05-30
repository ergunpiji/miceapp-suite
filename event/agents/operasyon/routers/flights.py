from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from templates_config import templates
from sqlalchemy.orm import Session
from datetime import date

from config import url
from database import get_db
from models import Event, Participant, FlightRecord, TransferRecord
from services.cascade import update_transfer_from_flight

router = APIRouter(prefix="/events/{event_id}", tags=["flights"])


@router.get("/flights", response_class=HTMLResponse)
async def flight_list(
    request: Request,
    event_id: str,
    direction: str = Query(""),
    search: str = Query(""),
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return RedirectResponse(url=url("/events"))

    q = db.query(FlightRecord).join(Participant).filter(Participant.event_id == event_id)
    if direction:
        q = q.filter(FlightRecord.direction == direction)
    if search:
        q = q.filter(
            (Participant.first_name.ilike(f"%{search}%")) |
            (Participant.last_name.ilike(f"%{search}%"))
        )

    flights = q.order_by(
        FlightRecord.flight_date,
        FlightRecord.departure_time,
        Participant.last_name,
        Participant.first_name
    ).all()

    return templates.TemplateResponse("flights/list.html", {
        "request": request,
        "event": event,
        "flights": flights,
        "direction_filter": direction,
        "search": search,
        "active": "flights"
    })


@router.get("/participants/{participant_id}/flights/new", response_class=HTMLResponse)
async def new_flight_form(
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
    return templates.TemplateResponse("flights/form.html", {
        "request": request,
        "event": event,
        "participant": participant,
        "flight": None,
        "direction": direction,
        "active": "flights"
    })


@router.post("/participants/{participant_id}/flights/new")
async def create_flight(
    event_id: str,
    participant_id: str,
    direction: str = Form(...),
    flight_number: str = Form(""),
    airline: str = Form(""),
    departure_airport: str = Form(""),
    arrival_airport: str = Form(""),
    flight_date: date = Form(None),
    departure_time: str = Form(""),
    arrival_time: str = Form(""),
    seat: str = Form(""),
    pnr: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db)
):
    # Aynı yönde zaten kayıt varsa güncelle
    existing = db.query(FlightRecord).filter(
        FlightRecord.participant_id == participant_id,
        FlightRecord.direction == direction
    ).first()

    if existing:
        flight = existing
    else:
        flight = FlightRecord(participant_id=participant_id, direction=direction)
        db.add(flight)

    flight.flight_number = flight_number or None
    flight.airline = airline or None
    flight.departure_airport = departure_airport or None
    flight.arrival_airport = arrival_airport or None
    flight.flight_date = flight_date
    flight.departure_time = departure_time or None
    flight.arrival_time = arrival_time or None
    flight.seat = seat or None
    flight.pnr = pnr or None
    flight.notes = notes or None
    db.commit()
    db.refresh(flight)

    # Cascade: bağlı transferi güncelle
    update_transfer_from_flight(db, flight)

    return RedirectResponse(
        url=url(f"/events/{event_id}/participants/{participant_id}"), status_code=303
    )


@router.post("/participants/{participant_id}/flights/{flight_id}/delete")
async def delete_flight(
    event_id: str,
    participant_id: str,
    flight_id: str,
    db: Session = Depends(get_db)
):
    flight = db.query(FlightRecord).filter(FlightRecord.id == flight_id).first()
    if flight:
        db.delete(flight)
        db.commit()
    return RedirectResponse(
        url=url(f"/events/{event_id}/participants/{participant_id}"), status_code=303
    )
