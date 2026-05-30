"""
E-dem — Etkinlik Tipleri yönetimi router'ı (Admin only)
"""

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import require_admin
from database import get_db
from models import EventType, User, _uuid

router = APIRouter(prefix="/event-types", tags=["event-types"])
from templates_config import templates


@router.get("", response_class=HTMLResponse, name="event_types_list")
async def event_types_list(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    event_types = db.query(EventType).order_by(EventType.sort_order, EventType.label).all()
    return templates.TemplateResponse(
        "event_types/list.html",
        {
            "request":      request,
            "current_user": current_user,
            "event_types":  event_types,
            "page_title":   "Etkinlik Tipleri",
        },
    )


@router.post("/new", name="event_types_create")
async def event_types_create(
    code:       str = Form(...),
    label:      str = Form(...),
    sort_order: str = Form("0"),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    code_clean = code.lower().strip()[:10]
    existing = db.query(EventType).filter(EventType.code == code_clean).first()
    if not existing:
        et = EventType(
            id=_uuid(),
            code=code_clean,
            label=label.strip(),
            active=True,
            sort_order=int(sort_order) if sort_order.isdigit() else 0,
        )
        db.add(et)
        db.commit()
    return RedirectResponse(url="/event-types", status_code=status.HTTP_302_FOUND)


@router.post("/{et_id}/toggle", name="event_types_toggle")
async def event_types_toggle(
    et_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    et = db.query(EventType).filter(EventType.id == et_id).first()
    if et:
        et.active = not et.active
        db.commit()
    return RedirectResponse(url="/event-types", status_code=status.HTTP_302_FOUND)


@router.post("/{et_id}/delete", name="event_types_delete")
async def event_types_delete(
    et_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    et = db.query(EventType).filter(EventType.id == et_id).first()
    if et:
        db.delete(et)
        db.commit()
    return RedirectResponse(url="/event-types", status_code=status.HTTP_302_FOUND)
