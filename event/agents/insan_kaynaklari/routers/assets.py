"""HR Ajanı — Zimmet Takibi."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user, require_hr_admin
from database import get_db
from models import ASSET_CONDITIONS, ASSET_TYPES, Asset, Employee, HRUser, Notification
from routers.notifications import create_notification
from templates_config import templates

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_class=HTMLResponse)
async def list_assets(
    request: Request,
    q: str = "",
    asset_type: str = "",
    status: str = "",
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    unread_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).scalar() or 0

    query = db.query(Asset)
    if current_user.role == "employee" and current_user.employee:
        query = query.filter(Asset.employee_id == current_user.employee.id)
    if q:
        query = query.filter(
            Asset.brand.ilike(f"%{q}%") | Asset.model.ilike(f"%{q}%") | Asset.serial_no.ilike(f"%{q}%")
        )
    if asset_type:
        query = query.filter(Asset.asset_type == asset_type)
    if status == "active":
        query = query.filter(Asset.returned_date == None)
    elif status == "returned":
        query = query.filter(Asset.returned_date != None)

    assets = query.order_by(Asset.assigned_date.desc()).all()

    return templates.TemplateResponse(
        "assets/list.html",
        {
            "request": request, "active": "assets", "user": current_user,
            "assets": assets, "q": q, "asset_type": asset_type, "status_filter": status,
            "asset_types": ASSET_TYPES, "unread_count": unread_count,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_asset_form(
    request: Request,
    employee_id: str = "",
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    employees = db.query(Employee).filter(Employee.status == "aktif").order_by(Employee.first_name).all()
    unread_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).scalar() or 0
    return templates.TemplateResponse(
        "assets/form.html",
        {
            "request": request, "active": "assets", "user": current_user,
            "asset": None, "employees": employees, "preselected_employee": employee_id,
            "asset_types": ASSET_TYPES, "conditions": ASSET_CONDITIONS,
            "unread_count": unread_count, "error": None,
        },
    )


@router.post("/new")
async def create_asset(
    employee_id: str = Form(...),
    asset_type: str = Form("diger"),
    brand: str = Form(""),
    model: str = Form(""),
    serial_no: str = Form(""),
    assigned_date: str = Form(...),
    condition: str = Form("iyi"),
    notes: str = Form(""),
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    asset = Asset(
        employee_id=employee_id,
        asset_type=asset_type,
        brand=brand or None,
        model=model or None,
        serial_no=serial_no or None,
        assigned_date=date.fromisoformat(assigned_date),
        condition=condition,
        notes=notes or None,
    )
    db.add(asset)
    db.flush()

    # Çalışanın user hesabına bildirim gönder
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if emp and emp.user:
        create_notification(
            db, emp.user.id, "zimmet",
            f"Yeni zimmet: {asset.asset_type_label}",
            f"{asset.description} zimmetinize eklendi.",
            ref_type="asset", ref_id=asset.id,
        )

    db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}?tab=assets", status_code=302)


@router.post("/{asset_id}/return")
async def return_asset(
    asset_id: str,
    returned_date: str = Form(...),
    condition: str = Form("iyi"),
    notes: str = Form(""),
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404)
    asset.returned_date = date.fromisoformat(returned_date)
    asset.condition = condition
    if notes:
        asset.notes = (asset.notes or "") + f"\nİade notu: {notes}"
    db.commit()
    return RedirectResponse(url=f"/employees/{asset.employee_id}?tab=assets", status_code=302)


@router.post("/{asset_id}/sign")
async def sign_asset(
    asset_id: str,
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404)
    asset.signed = True
    asset.signed_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url=f"/employees/{asset.employee_id}?tab=assets", status_code=302)


@router.post("/{asset_id}/delete")
async def delete_asset(
    asset_id: str,
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if asset:
        emp_id = asset.employee_id
        db.delete(asset)
        db.commit()
        return RedirectResponse(url=f"/employees/{emp_id}?tab=assets", status_code=302)
    raise HTTPException(status_code=404)
