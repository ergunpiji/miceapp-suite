from fastapi import APIRouter, Depends, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from datetime import date
from collections import defaultdict, OrderedDict

from config import url, now_tr
from database import get_db
from models import Event, AgendaSession, SupplierTask, SESSION_TYPES, SUPPLIER_TASK_TYPES, TASK_STATUSES
from templates_config import templates

router = APIRouter(prefix="/events/{event_id}", tags=["agenda"])


# ---------------------------------------------------------------------------
# Günlük Program
# ---------------------------------------------------------------------------

@router.get("/agenda", response_class=HTMLResponse)
async def agenda_view(
    request: Request,
    event_id: str,
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return RedirectResponse(url=url("/events"))

    sessions = (
        db.query(AgendaSession)
        .filter(AgendaSession.event_id == event_id)
        .order_by(AgendaSession.session_date, AgendaSession.start_time, AgendaSession.sort_order)
        .all()
    )

    # Güne göre grupla
    by_day: dict = OrderedDict()
    for s in sessions:
        key = s.session_date
        if key not in by_day:
            by_day[key] = []
        by_day[key].append(s)

    # Etkinlik tarih aralığı (yeni seans eklerken varsayılan tarih için)
    from datetime import timedelta
    event_dates = []
    if event.start_date and event.end_date:
        d = event.start_date
        while d <= event.end_date:
            event_dates.append(d)
            d += timedelta(days=1)

    return templates.TemplateResponse("agenda/list.html", {
        "request": request,
        "event": event,
        "by_day": by_day,
        "event_dates": event_dates,
        "session_types": SESSION_TYPES,
        "active": "agenda",
    })


@router.get("/agenda/new", response_class=HTMLResponse)
async def new_session_form(
    request: Request,
    event_id: str,
    session_date: str = Query(""),
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    from datetime import timedelta
    event_dates = []
    if event.start_date and event.end_date:
        d = event.start_date
        while d <= event.end_date:
            event_dates.append(d)
            d += timedelta(days=1)

    return templates.TemplateResponse("agenda/form.html", {
        "request": request,
        "event": event,
        "session": None,
        "session_types": SESSION_TYPES,
        "event_dates": event_dates,
        "prefill_date": session_date,
        "active": "agenda",
    })


@router.post("/agenda/new")
async def create_session(
    event_id: str,
    session_date: date = Form(...),
    start_time: str = Form(""),
    end_time: str = Form(""),
    title: str = Form(...),
    session_type: str = Form("other"),
    hall: str = Form(""),
    speaker: str = Form(""),
    moderator: str = Form(""),
    description: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db)
):
    import uuid
    s = AgendaSession(
        id=str(uuid.uuid4()),
        event_id=event_id,
        session_date=session_date,
        start_time=start_time or None,
        end_time=end_time or None,
        title=title,
        session_type=session_type,
        hall=hall or None,
        speaker=speaker or None,
        moderator=moderator or None,
        description=description or None,
        notes=notes or None,
    )
    db.add(s)
    db.commit()
    return RedirectResponse(url=url(f"/events/{event_id}/agenda"), status_code=303)


@router.get("/agenda/{session_id}/edit", response_class=HTMLResponse)
async def edit_session_form(
    request: Request,
    event_id: str,
    session_id: str,
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    session = db.query(AgendaSession).filter(AgendaSession.id == session_id).first()
    from datetime import timedelta
    event_dates = []
    if event.start_date and event.end_date:
        d = event.start_date
        while d <= event.end_date:
            event_dates.append(d)
            d += timedelta(days=1)

    return templates.TemplateResponse("agenda/form.html", {
        "request": request,
        "event": event,
        "session": session,
        "session_types": SESSION_TYPES,
        "event_dates": event_dates,
        "prefill_date": "",
        "active": "agenda",
    })


@router.post("/agenda/{session_id}/edit")
async def update_session(
    event_id: str,
    session_id: str,
    session_date: date = Form(...),
    start_time: str = Form(""),
    end_time: str = Form(""),
    title: str = Form(...),
    session_type: str = Form("other"),
    hall: str = Form(""),
    speaker: str = Form(""),
    moderator: str = Form(""),
    description: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db)
):
    s = db.query(AgendaSession).filter(AgendaSession.id == session_id).first()
    if s:
        s.session_date = session_date
        s.start_time = start_time or None
        s.end_time = end_time or None
        s.title = title
        s.session_type = session_type
        s.hall = hall or None
        s.speaker = speaker or None
        s.moderator = moderator or None
        s.description = description or None
        s.notes = notes or None
        db.commit()
    return RedirectResponse(url=url(f"/events/{event_id}/agenda"), status_code=303)


@router.post("/agenda/{session_id}/delete")
async def delete_session(
    event_id: str,
    session_id: str,
    db: Session = Depends(get_db)
):
    s = db.query(AgendaSession).filter(AgendaSession.id == session_id).first()
    if s:
        db.delete(s)
        db.commit()
    return RedirectResponse(url=url(f"/events/{event_id}/agenda"), status_code=303)


# ---------------------------------------------------------------------------
# Tedarikçi Görev Planı
# ---------------------------------------------------------------------------

@router.get("/tasks", response_class=HTMLResponse)
async def tasks_view(
    request: Request,
    event_id: str,
    status: str = Query(""),
    supplier_type: str = Query(""),
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return RedirectResponse(url=url("/events"))

    q = db.query(SupplierTask).filter(SupplierTask.event_id == event_id)
    if status:
        q = q.filter(SupplierTask.status == status)
    if supplier_type:
        q = q.filter(SupplierTask.supplier_type == supplier_type)

    tasks = q.order_by(SupplierTask.task_date, SupplierTask.task_time, SupplierTask.supplier_name).all()

    # Tedarikçiye göre grupla
    by_supplier: dict = defaultdict(list)
    for t in tasks:
        by_supplier[t.supplier_name].append(t)

    # İstatistikler
    all_tasks = db.query(SupplierTask).filter(SupplierTask.event_id == event_id).all()
    stats = {s: sum(1 for t in all_tasks if t.status == s) for s in TASK_STATUSES}

    return templates.TemplateResponse("tasks/list.html", {
        "request": request,
        "event": event,
        "tasks": tasks,
        "by_supplier": dict(by_supplier),
        "stats": stats,
        "status_filter": status,
        "type_filter": supplier_type,
        "task_statuses": TASK_STATUSES,
        "supplier_task_types": SUPPLIER_TASK_TYPES,
        "active": "tasks",
    })


@router.get("/tasks/new", response_class=HTMLResponse)
async def new_task_form(
    request: Request,
    event_id: str,
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    # Mevcut tedarikçi adlarını öner
    existing_suppliers = sorted(set(
        t.supplier_name for t in
        db.query(SupplierTask).filter(SupplierTask.event_id == event_id).all()
    ))
    return templates.TemplateResponse("tasks/form.html", {
        "request": request,
        "event": event,
        "task": None,
        "existing_suppliers": existing_suppliers,
        "task_statuses": TASK_STATUSES,
        "supplier_task_types": SUPPLIER_TASK_TYPES,
        "active": "tasks",
    })


@router.post("/tasks/new")
async def create_task(
    event_id: str,
    supplier_name: str = Form(...),
    supplier_type: str = Form("other"),
    task: str = Form(...),
    task_date: date = Form(None),
    task_time: str = Form(""),
    status: str = Form("pending"),
    notes: str = Form(""),
    db: Session = Depends(get_db)
):
    import uuid
    t = SupplierTask(
        id=str(uuid.uuid4()),
        event_id=event_id,
        supplier_name=supplier_name,
        supplier_type=supplier_type,
        task=task,
        task_date=task_date,
        task_time=task_time or None,
        status=status,
        notes=notes or None,
        created_at=now_tr(),
    )
    db.add(t)
    db.commit()
    return RedirectResponse(url=url(f"/events/{event_id}/tasks"), status_code=303)


@router.post("/tasks/{task_id}/status")
async def update_task_status(
    event_id: str,
    task_id: str,
    status: str = Form(...),
    db: Session = Depends(get_db)
):
    t = db.query(SupplierTask).filter(SupplierTask.id == task_id).first()
    if t:
        t.status = status
        db.commit()
    return RedirectResponse(url=url(f"/events/{event_id}/tasks"), status_code=303)


@router.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
async def edit_task_form(
    request: Request,
    event_id: str,
    task_id: str,
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    task = db.query(SupplierTask).filter(SupplierTask.id == task_id).first()
    existing_suppliers = sorted(set(
        t.supplier_name for t in
        db.query(SupplierTask).filter(SupplierTask.event_id == event_id).all()
    ))
    return templates.TemplateResponse("tasks/form.html", {
        "request": request,
        "event": event,
        "task": task,
        "existing_suppliers": existing_suppliers,
        "task_statuses": TASK_STATUSES,
        "supplier_task_types": SUPPLIER_TASK_TYPES,
        "active": "tasks",
    })


@router.post("/tasks/{task_id}/edit")
async def update_task(
    event_id: str,
    task_id: str,
    supplier_name: str = Form(...),
    supplier_type: str = Form("other"),
    task: str = Form(...),
    task_date: date = Form(None),
    task_time: str = Form(""),
    status: str = Form("pending"),
    notes: str = Form(""),
    db: Session = Depends(get_db)
):
    t = db.query(SupplierTask).filter(SupplierTask.id == task_id).first()
    if t:
        t.supplier_name = supplier_name
        t.supplier_type = supplier_type
        t.task = task
        t.task_date = task_date
        t.task_time = task_time or None
        t.status = status
        t.notes = notes or None
        db.commit()
    return RedirectResponse(url=url(f"/events/{event_id}/tasks"), status_code=303)


@router.post("/tasks/{task_id}/delete")
async def delete_task(
    event_id: str,
    task_id: str,
    db: Session = Depends(get_db)
):
    t = db.query(SupplierTask).filter(SupplierTask.id == task_id).first()
    if t:
        db.delete(t)
        db.commit()
    return RedirectResponse(url=url(f"/events/{event_id}/tasks"), status_code=303)


# ---------------------------------------------------------------------------
# E-dem Bütçesinden İçe Aktar
# ---------------------------------------------------------------------------

@router.post("/tasks/import-edem")
async def import_tasks_from_edem(
    event_id: str,
    db: Session = Depends(get_db)
):
    """E-dem bütçesindeki satırları tedarikçi görevlerine dönüştürür."""
    import uuid
    from datetime import datetime as dt
    from services.edem_bridge import get_budget_rows, SECTION_TO_SUPPLIER_TYPE

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event or not event.edem_request_id:
        return RedirectResponse(url=url(f"/events/{event_id}/tasks"), status_code=303)

    venue_name, rows = get_budget_rows(event.edem_request_id)
    if not rows:
        return RedirectResponse(url=url(f"/events/{event_id}/tasks"), status_code=303)

    # Tedarikçi adı: bütçedeki venue_name ya da etkinlik mekanı
    supplier = venue_name or event.venue or "Tedarikçi"

    for row in rows:
        # Görev açıklaması: "25x Standart Oda SGL (Tek Kişilik)"
        qty_str = f"{int(row.qty)}x" if row.qty == int(row.qty) else f"{row.qty}x"
        task_text = f"{qty_str} {row.service_name}"
        if row.unit and row.unit not in ("Adet", "Hizmet"):
            task_text += f" ({row.unit})"

        notes_parts = []
        if row.nights > 1:
            notes_parts.append(f"{row.nights} gece")
        if row.sale_price:
            total = row.sale_price * row.qty * (row.nights if row.section == "accommodation" else 1)
            notes_parts.append(f"₺{total:,.0f}")
        notes = " · ".join(notes_parts)

        t = SupplierTask(
            id=str(uuid.uuid4()),
            event_id=event_id,
            supplier_name=supplier,
            supplier_type=SECTION_TO_SUPPLIER_TYPE.get(row.section, "other"),
            task=task_text,
            task_date=None,
            task_time=None,
            status="pending",
            notes=notes or None,
            created_at=now_tr(),
        )
        db.add(t)

    db.commit()
    return RedirectResponse(url=url(f"/events/{event_id}/tasks?imported=1"), status_code=303)


@router.post("/agenda/import-edem")
async def import_agenda_from_edem(
    event_id: str,
    db: Session = Depends(get_db)
):
    """E-dem bütçesindeki toplantı / yemek / transfer kalemlerini günlük programa ekler."""
    import uuid
    from services.edem_bridge import get_budget_rows, SECTION_TO_SESSION_TYPE

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event or not event.edem_request_id:
        return RedirectResponse(url=url(f"/events/{event_id}/agenda"), status_code=303)

    venue_name, rows = get_budget_rows(event.edem_request_id)
    if not rows:
        return RedirectResponse(url=url(f"/events/{event_id}/agenda"), status_code=303)

    # Sadece program'a uygun section'lar
    AGENDA_SECTIONS = {"meeting", "fb", "transfer", "other"}

    # Başlangıç tarihi yoksa atla
    default_date = event.start_date

    for row in rows:
        if row.section not in AGENDA_SECTIONS:
            continue

        session_type = SECTION_TO_SESSION_TYPE.get(row.section, "other")

        qty_str = f"{int(row.qty)}x" if row.qty == int(row.qty) else f"{row.qty}x"
        title = f"{qty_str} {row.service_name}"

        s = AgendaSession(
            id=str(uuid.uuid4()),
            event_id=event_id,
            session_date=default_date,
            start_time=None,
            end_time=None,
            title=title,
            session_type=session_type,
            hall=venue_name or None,
            speaker=None,
            moderator=None,
            description=None,
            notes=None,
        )
        db.add(s)

    db.commit()
    return RedirectResponse(url=url(f"/events/{event_id}/agenda?imported=1"), status_code=303)
