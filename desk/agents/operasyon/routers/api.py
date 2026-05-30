"""
Operasyon Ajanı — Dahili API
E-dem'in modülü aktifleştirmek için çağırdığı endpoint'ler.
API key ile korunur (OA_API_KEY env değişkeni).

Sub-app olarak mount edilince, E-dem doğrudan _activate_internal() fonksiyonunu
çağırır — HTTP round-trip gerekmez.
"""
import os
import secrets
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Event, UserToken

router = APIRouter(prefix="/api", tags=["api"])

OA_API_KEY     = os.environ.get("OA_API_KEY", "")
# Dış iş ortaklarına gösterilecek genel URL (E-dem'in host'u + /operasyon)
OA_PUBLIC_BASE = os.environ.get("OA_PUBLIC_BASE", "http://localhost:8000/operasyon")


def _verify_key(x_api_key: str = Header(...)):
    if not OA_API_KEY:
        return  # key ayarlı değilse dev modunda kabul et
    if x_api_key != OA_API_KEY:
        raise HTTPException(status_code=403, detail="Geçersiz API anahtarı")


class ActivateRequest(BaseModel):
    edem_request_id: str
    edem_request_no: str
    event_name: str
    start_date: str   # YYYY-MM-DD
    end_date: str     # YYYY-MM-DD
    venue: str | None = None
    city: str | None = None


def _activate_internal(body: dict, db: Session) -> dict:
    """
    Aktivasyon iş mantığı — HTTP katmanı olmadan doğrudan çağrılabilir.
    E-dem, sub-app mount sonrasında bunu doğrudan import ederek kullanır.

    Döner: {event_id, manager_url, coordinator_url,
            transfer_supplier_url, accommodation_supplier_url,
            task_supplier_url, client_url}
    """
    edem_request_id = body["edem_request_id"]

    # Zaten aktifleştirilmiş mi?
    existing = db.query(Event).filter(
        Event.edem_request_id == edem_request_id
    ).first()

    if existing:
        event = existing
    else:
        event = Event(
            name=body["event_name"],
            edem_request_id=edem_request_id,
            edem_request_no=body.get("edem_request_no", ""),
            start_date=date.fromisoformat(body["start_date"]),
            end_date=date.fromisoformat(body["end_date"]),
            venue=body.get("venue"),
            city=body.get("city"),
        )
        db.add(event)
        db.flush()  # event.id üret

    # Mevcut tokenleri getir
    tokens = db.query(UserToken).filter(UserToken.event_id == event.id).all()
    token_map = {t.role: t for t in tokens}

    # Yönetici tokeni
    if "manager" not in token_map:
        t = UserToken(event_id=event.id, label="Yönetici", role="manager")
        db.add(t)
        token_map["manager"] = t

    # Koordinatör tokeni
    if "coordinator" not in token_map:
        t = UserToken(event_id=event.id, label="Koordinatör", role="coordinator")
        db.add(t)
        token_map["coordinator"] = t

    # Tedarikçi Görev Portalı tokeni (teknik/dekor/diğer)
    if "task_supplier" not in token_map:
        t = UserToken(event_id=event.id, label="Tedarikçi Görev Portalı", role="task_supplier")
        db.add(t)
        token_map["task_supplier"] = t

    # Müşteri Portalı tokeni (salt-okunur program + katılımcı özeti)
    if "client" not in token_map:
        t = UserToken(event_id=event.id, label="Müşteri Portalı", role="client")
        db.add(t)
        token_map["client"] = t

    db.commit()
    db.refresh(event)

    base = (body.get("base_url") or OA_PUBLIC_BASE).rstrip("/")

    return {
        "event_id":                    event.id,
        "event_url":                   f"{base}/events/{event.id}",
        "manager_token":               token_map["manager"].token,
        "coordinator_token":           token_map["coordinator"].token,
        "manager_url":                 f"{base}/access/{token_map['manager'].token}",
        "coordinator_url":             f"{base}/access/{token_map['coordinator'].token}",
        "transfer_supplier_url":       f"{base}/supplier/{event.supplier_token}/transfers",
        "accommodation_supplier_url":  f"{base}/supplier/{event.supplier_token}/accommodations",
        "task_supplier_url":           f"{base}/supplier/{event.supplier_token}/tasks",
        "client_url":                  f"{base}/client/{token_map['client'].token}",
    }


@router.post("/activate")
async def activate_module(
    body: ActivateRequest,
    db: Session = Depends(get_db),
    _: None = Depends(_verify_key),
):
    """
    E-dem'den HTTP ile çağrılır (standalone mod).
    Sub-app olarak mount edilince _activate_internal() doğrudan kullanılır.
    """
    data = _activate_internal(body.model_dump(), db)
    return JSONResponse(data)


@router.get("/status/{edem_request_id}")
async def module_status(
    edem_request_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(_verify_key),
):
    """Modülün aktif olup olmadığını ve token URL'lerini döner."""
    event = db.query(Event).filter(
        Event.edem_request_id == edem_request_id
    ).first()

    if not event:
        return JSONResponse({"active": False})

    tokens = {t.role: t for t in db.query(UserToken).filter(
        UserToken.event_id == event.id, UserToken.active == True
    ).all()}

    base = OA_PUBLIC_BASE.rstrip("/")
    return JSONResponse({
        "active":                      True,
        "event_id":                    event.id,
        "manager_url":                 f"{base}/access/{tokens['manager'].token}" if "manager" in tokens else None,
        "coordinator_url":             f"{base}/access/{tokens['coordinator'].token}" if "coordinator" in tokens else None,
        "transfer_supplier_url":       f"{base}/supplier/{event.supplier_token}/transfers",
        "accommodation_supplier_url":  f"{base}/supplier/{event.supplier_token}/accommodations",
        "task_supplier_url":           f"{base}/supplier/{event.supplier_token}/tasks",
        "client_url":                  f"{base}/client/{tokens['client'].token}" if "client" in tokens else None,
    })
