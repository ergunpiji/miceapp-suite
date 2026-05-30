import os
from fastapi import APIRouter, Depends, Request, Form, Query, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from templates_config import templates
from sqlalchemy.orm import Session
from datetime import date

from config import url
from database import get_db
from models import Event, UserToken
from services import edem_bridge


def _public_base(request: Request) -> str:
    """
    Tedarikçi / müşteri linklerinde kullanılacak tam URL prefix.
    Örn: https://e-dem.up.railway.app/operasyon
    """
    oa_prefix = os.getenv("OA_URL_PREFIX", "")
    host = str(request.base_url).rstrip("/")
    return f"{host}{oa_prefix}"

router = APIRouter(prefix="/events", tags=["events"])


def _get_user(event_id: str, db: Session, oa_access: str | None) -> dict | None:
    """Cookie token'ı doğrular. Geçerliyse user dict döner, değilse None."""
    if not oa_access:
        return None
    ut = db.query(UserToken).filter(
        UserToken.token == oa_access,
        UserToken.event_id == event_id,
        UserToken.active == True,
    ).first()
    if not ut:
        return None
    return {"role": ut.role, "label": ut.label}


def _auth_event(event_id: str, db: Session, oa_access: str | None):
    """
    Event'e erişim kontrolü.
    Token geçerliyse user dict döner.
    Yoksa RedirectResponse (login sayfası) döner.
    """
    user = _get_user(event_id, db, oa_access)
    if user is None:
        return RedirectResponse(url=url("/giris"), status_code=303)
    return user


@router.get("/", response_class=HTMLResponse)
async def list_events(request: Request, db: Session = Depends(get_db)):
    events = db.query(Event).order_by(Event.start_date.desc()).all()
    return templates.TemplateResponse("events/list.html", {
        "request": request,
        "events": events,
        "active": "events"
    })


@router.get("/edem-references", response_class=JSONResponse)
async def edem_references_api(search: str = Query("")):
    """E-dem referanslarını JSON olarak döner (form otomatik doldurma için)."""
    refs = edem_bridge.get_references(search=search)
    return [
        {
            "id": r.id,
            "request_no": r.request_no,
            "event_name": r.event_name,
            "client_name": r.client_name,
            "status_label": r.status_label,
            "check_in": r.check_in,
            "check_out": r.check_out,
            "accom_check_in": r.accom_check_in,
            "accom_check_out": r.accom_check_out,
            "city": r.city,
            "attendee_count": r.attendee_count,
            "venue_name": r.venue_name,
        }
        for r in refs
    ]


@router.get("/new", response_class=HTMLResponse)
async def new_event_form(request: Request):
    edem_available = edem_bridge.is_available()
    edem_refs = edem_bridge.get_references() if edem_available else []
    return templates.TemplateResponse("events/form.html", {
        "request": request,
        "event": None,
        "edem_available": edem_available,
        "edem_refs": edem_refs,
        "active": "events"
    })


@router.post("/new")
async def create_event(
    request: Request,
    name: str = Form(...),
    start_date: date = Form(...),
    end_date: date = Form(...),
    venue: str = Form(""),
    city: str = Form(""),
    notes: str = Form(""),
    edem_request_id: str = Form(""),
    edem_request_no: str = Form(""),
    db: Session = Depends(get_db)
):
    event = Event(
        name=name,
        start_date=start_date,
        end_date=end_date,
        venue=venue or None,
        city=city or None,
        notes=notes or None,
        edem_request_id=edem_request_id or None,
        edem_request_no=edem_request_no or None,
    )
    db.add(event)
    db.commit()
    return RedirectResponse(url=url(f"/events/{event.id}"), status_code=303)


@router.get("/{event_id}", response_class=HTMLResponse)
async def event_dashboard(
    request: Request, event_id: str,
    db: Session = Depends(get_db),
    oa_access: str | None = Cookie(default=None),
):
    auth = _auth_event(event_id, db, oa_access)
    if isinstance(auth, RedirectResponse):
        return auth
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return RedirectResponse(url=url("/events"))

    # Tüm token'ları getir — link kutuları için
    tokens = {
        t.role: t
        for t in db.query(UserToken).filter(
            UserToken.event_id == event.id,
            UserToken.active == True,
        ).all()
    }

    base = _public_base(request)

    links = {
        "manager":       f"{base}/access/{tokens['manager'].token}"      if "manager"      in tokens else None,
        "coordinator":   f"{base}/access/{tokens['coordinator'].token}"   if "coordinator"  in tokens else None,
        "transfers":     f"{base}/supplier/{event.supplier_token}/transfers"     if event.supplier_token else None,
        "accommodations":f"{base}/supplier/{event.supplier_token}/accommodations" if event.supplier_token else None,
        "tasks":         f"{base}/supplier/{event.supplier_token}/tasks"          if event.supplier_token else None,
        "client":        f"{base}/client/{tokens['client'].token}"        if "client"       in tokens else None,
    }

    return templates.TemplateResponse("events/dashboard.html", {
        "request": request,
        "event": event,
        "current_user": auth,
        "links": links,
        "active": "dashboard"
    })


@router.get("/{event_id}/edit", response_class=HTMLResponse)
async def edit_event_form(
    request: Request, event_id: str,
    db: Session = Depends(get_db),
    oa_access: str | None = Cookie(default=None),
):
    auth = _auth_event(event_id, db, oa_access)
    if isinstance(auth, RedirectResponse):
        return auth
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return RedirectResponse(url=url("/events"))
    edem_available = edem_bridge.is_available()
    edem_refs = edem_bridge.get_references() if edem_available else []
    return templates.TemplateResponse("events/form.html", {
        "request": request,
        "event": event,
        "edem_available": edem_available,
        "edem_refs": edem_refs,
        "active": "events"
    })


@router.post("/{event_id}/edit")
async def update_event(
    event_id: str,
    name: str = Form(...),
    start_date: date = Form(...),
    end_date: date = Form(...),
    venue: str = Form(""),
    city: str = Form(""),
    notes: str = Form(""),
    edem_request_id: str = Form(""),
    edem_request_no: str = Form(""),
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if event:
        event.name = name
        event.start_date = start_date
        event.end_date = end_date
        event.venue = venue or None
        event.city = city or None
        event.notes = notes or None
        event.edem_request_id = edem_request_id or None
        event.edem_request_no = edem_request_no or None
        db.commit()
    return RedirectResponse(url=url(f"/events/{event_id}"), status_code=303)


@router.post("/{event_id}/delete")
async def delete_event(event_id: str, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if event:
        db.delete(event)
        db.commit()
    return RedirectResponse(url=url("/events"), status_code=303)
