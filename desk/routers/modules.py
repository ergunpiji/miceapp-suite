"""
Operasyon Ajanı Modülü — E-dem entegrasyonu.
Bir referansa Operasyon Ajanı modülünü bağlar / kaldırır.

Sub-app olarak mount edildiğinde HTTP çağrısı yerine doğrudan
_activate_internal() fonksiyonu kullanılır.
"""
import os
import sys
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, JSONResponse

from auth import get_current_user
from database import get_db
from models import Request as Req, RequestModule
from sqlalchemy.orm import Session

router = APIRouter(tags=["modules"])

def _get_oa_db():
    """Operasyon ajanının DB session'ını döner.
    _mount_operasyon() operasyon modüllerini _oa.* isimleriyle sys.modules'a kaydeder.
    """
    oa_db_mod = sys.modules.get("_oa.database")
    if oa_db_mod is None:
        raise RuntimeError("Operasyon database modülü yüklü değil (_oa.database)")
    return oa_db_mod.SessionLocal()


def _get_activate_fn():
    """Operasyon _activate_internal fonksiyonunu sys.modules'tan döner."""
    oa_api = sys.modules.get("_oa.routers.api")
    if oa_api is None:
        raise RuntimeError("Operasyon API modülü yüklü değil (_oa.routers.api)")
    return oa_api._activate_internal


@router.post("/requests/{request_id}/modules/operasyon/activate")
async def activate_operasyon(
    request_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    req = db.query(Req).filter(Req.id == request_id).first()
    if not req:
        return RedirectResponse(url=f"/requests/{request_id}", status_code=303)

    # Zaten aktif mi?
    existing = db.query(RequestModule).filter(
        RequestModule.request_id == request_id,
        RequestModule.module_type == "operasyon",
        RequestModule.active == True,
    ).first()

    if existing:
        return RedirectResponse(url=f"/requests/{request_id}#operasyon-module", status_code=303)

    # Payload hazırla
    # base_url: mevcut isteğin host'u + /operasyon (OA_PUBLIC_BASE env var öncelikli)
    _host_base = str(request.base_url).rstrip("/") + "/operasyon"
    _oa_base = os.environ.get("OA_PUBLIC_BASE", _host_base).rstrip("/")

    payload = {
        "edem_request_id":  req.id,
        "edem_request_no":  req.request_no or "",
        "event_name":       req.event_name,
        "start_date":       (req.check_in.isoformat() if hasattr(req.check_in, 'isoformat') else str(req.check_in)) if req.check_in else datetime.today().date().isoformat(),
        "end_date":         (req.check_out.isoformat() if hasattr(req.check_out, 'isoformat') else str(req.check_out)) if req.check_out else datetime.today().date().isoformat(),
        "venue":            None,
        "city":             req.cities_display or None,
        "base_url":         _oa_base,
    }

    # Onaylı bütçeden mekanı al
    if req.confirmed_budget_id:
        from models import Budget
        b = db.query(Budget).filter(Budget.id == req.confirmed_budget_id).first()
        if b and b.venue_name:
            payload["venue"] = b.venue_name

    try:
        # sys.modules["_oa.routers.api"] ve "_oa.database" üzerinden çağır
        # (app.py'deki _mount_operasyon() bu isimleri kayıt eder)
        _activate_internal = _get_activate_fn()
        oa_db = _get_oa_db()
        try:
            data = _activate_internal(payload, oa_db)
        finally:
            oa_db.close()
    except Exception as exc:
        import traceback; traceback.print_exc()
        return RedirectResponse(
            url=f"/requests/{request_id}?oa_error=1",
            status_code=303
        )

    module = RequestModule(
        request_id=request_id,
        module_type="operasyon",
        activated_by=current_user.id,
        oa_event_id=data.get("event_id"),
        oa_manager_url=data.get("manager_url"),
        oa_coordinator_url=data.get("coordinator_url"),
        oa_transfer_supplier_url=data.get("transfer_supplier_url"),
        oa_accommodation_supplier_url=data.get("accommodation_supplier_url"),
        oa_task_supplier_url=data.get("task_supplier_url"),
        oa_client_url=data.get("client_url"),
        active=True,
    )
    db.add(module)
    db.commit()

    # Aktivasyon başarılıysa doğrudan operasyon yönetici paneline yönlendir
    manager_url = data.get("manager_url")
    if manager_url:
        return RedirectResponse(url=manager_url, status_code=303)
    return RedirectResponse(url=f"/requests/{request_id}#operasyon-module", status_code=303)


@router.post("/requests/{request_id}/modules/operasyon/deactivate")
async def deactivate_operasyon(
    request_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    module = db.query(RequestModule).filter(
        RequestModule.request_id == request_id,
        RequestModule.module_type == "operasyon",
        RequestModule.active == True,
    ).first()
    if module:
        module.active = False
        db.commit()
    return RedirectResponse(url=f"/requests/{request_id}#operasyon-module", status_code=303)
