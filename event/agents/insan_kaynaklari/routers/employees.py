"""HR Ajanı — Çalışan Yönetimi ve Özlük Dosyaları."""
import os
import shutil
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user, require_hr_admin
from database import get_db
from models import (
    ASSET_TYPES, DOC_TYPES, EMPLOYMENT_TYPES, EMPLOYEE_STATUSES,
    Asset, Employee, HRUser, LeaveBalance, MealCard, OvertimeRecord,
    PayrollRecord, PersonnelDocument,
)
from templates_config import templates

router = APIRouter(prefix="/employees", tags=["employees"])

UPLOADS_DIR = Path("uploads")


def _next_employee_no(db: Session) -> str:
    count = db.query(func.count(Employee.id)).scalar() or 0
    return f"EMP-{count + 1:03d}"


@router.get("", response_class=HTMLResponse)
async def list_employees(
    request: Request,
    q: str = "",
    dept: str = "",
    status: str = "",
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import func
    from models import Notification
    unread_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).scalar() or 0

    query = db.query(Employee)
    if q:
        query = query.filter(
            (Employee.first_name + " " + Employee.last_name).ilike(f"%{q}%")
            | Employee.email.ilike(f"%{q}%")
            | Employee.employee_no.ilike(f"%{q}%")
        )
    if dept:
        query = query.filter(Employee.department == dept)
    if status:
        query = query.filter(Employee.status == status)
    employees = query.order_by(Employee.first_name).all()

    departments = [r[0] for r in db.query(Employee.department).distinct().filter(Employee.department != None).all()]

    return templates.TemplateResponse(
        "employees/list.html",
        {
            "request": request, "active": "employees", "user": current_user,
            "employees": employees, "q": q, "dept": dept, "status_filter": status,
            "departments": departments, "statuses": EMPLOYEE_STATUSES,
            "unread_count": unread_count,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_employee_form(
    request: Request,
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    managers = db.query(Employee).filter(Employee.status == "aktif").all()
    from sqlalchemy import func
    from models import Notification
    unread_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).scalar() or 0
    return templates.TemplateResponse(
        "employees/form.html",
        {
            "request": request, "active": "employees", "user": current_user,
            "employee": None, "managers": managers,
            "employment_types": EMPLOYMENT_TYPES, "statuses": EMPLOYEE_STATUSES,
            "unread_count": unread_count, "error": None,
        },
    )


@router.post("/new")
async def create_employee(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    tc_no: str = Form(""),
    birth_date: str = Form(""),
    hire_date: str = Form(...),
    department: str = Form(""),
    title: str = Form(""),
    manager_id: str = Form(""),
    employment_type: str = Form("tam_zamanli"),
    status: str = Form("aktif"),
    annual_leave_days: int = Form(14),
    gross_salary: float = Form(0.0),
    notes: str = Form(""),
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    if db.query(Employee).filter(Employee.email == email).first():
        managers = db.query(Employee).filter(Employee.status == "aktif").all()
        return templates.TemplateResponse(
            "employees/form.html",
            {"request": request, "active": "employees", "user": current_user,
             "employee": None, "managers": managers,
             "employment_types": EMPLOYMENT_TYPES, "statuses": EMPLOYEE_STATUSES,
             "unread_count": 0, "error": "Bu e-posta adresi zaten kayıtlı"},
            status_code=400,
        )

    emp = Employee(
        employee_no=_next_employee_no(db),
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone or None,
        tc_no=tc_no or None,
        birth_date=date.fromisoformat(birth_date) if birth_date else None,
        hire_date=date.fromisoformat(hire_date),
        department=department or None,
        title=title or None,
        manager_id=manager_id or None,
        employment_type=employment_type,
        status=status,
        annual_leave_days=annual_leave_days,
        gross_salary=gross_salary,
        notes=notes or None,
    )
    db.add(emp)
    db.flush()

    # Bu yıl için izin bakiyesi oluştur
    db.add(LeaveBalance(
        employee_id=emp.id,
        year=date.today().year,
        total_days=annual_leave_days,
    ))
    db.commit()
    return RedirectResponse(url=f"/employees/{emp.id}", status_code=302)


@router.get("/{employee_id}", response_class=HTMLResponse)
async def employee_detail(
    employee_id: str,
    request: Request,
    tab: str = "overview",
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Çalışan kendi profilini görebilir, yöneticiler hepsini
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Çalışan bulunamadı")

    if current_user.role == "employee":
        if not current_user.employee or current_user.employee.id != employee_id:
            raise HTTPException(status_code=403, detail="Yetkisiz erişim")

    from sqlalchemy import func
    from models import Notification
    unread_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).scalar() or 0

    today = date.today()
    leave_balance = (
        db.query(LeaveBalance)
        .filter(LeaveBalance.employee_id == employee_id, LeaveBalance.year == today.year)
        .first()
    )
    recent_payrolls = (
        db.query(PayrollRecord)
        .filter(PayrollRecord.employee_id == employee_id)
        .order_by(PayrollRecord.period_year.desc(), PayrollRecord.period_month.desc())
        .limit(6)
        .all()
    )

    return templates.TemplateResponse(
        "employees/detail.html",
        {
            "request": request, "active": "employees", "user": current_user,
            "employee": emp, "tab": tab, "today": today,
            "leave_balance": leave_balance, "recent_payrolls": recent_payrolls,
            "doc_types": DOC_TYPES, "asset_types": ASSET_TYPES,
            "unread_count": unread_count,
        },
    )


@router.get("/{employee_id}/edit", response_class=HTMLResponse)
async def edit_employee_form(
    employee_id: str,
    request: Request,
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Çalışan bulunamadı")
    managers = db.query(Employee).filter(Employee.status == "aktif", Employee.id != employee_id).all()
    from sqlalchemy import func
    from models import Notification
    unread_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).scalar() or 0
    return templates.TemplateResponse(
        "employees/form.html",
        {"request": request, "active": "employees", "user": current_user,
         "employee": emp, "managers": managers,
         "employment_types": EMPLOYMENT_TYPES, "statuses": EMPLOYEE_STATUSES,
         "unread_count": unread_count, "error": None},
    )


@router.post("/{employee_id}/edit")
async def update_employee(
    employee_id: str,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    tc_no: str = Form(""),
    birth_date: str = Form(""),
    hire_date: str = Form(...),
    termination_date: str = Form(""),
    department: str = Form(""),
    title: str = Form(""),
    manager_id: str = Form(""),
    employment_type: str = Form("tam_zamanli"),
    status: str = Form("aktif"),
    annual_leave_days: int = Form(14),
    gross_salary: float = Form(0.0),
    notes: str = Form(""),
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Çalışan bulunamadı")

    emp.first_name = first_name
    emp.last_name = last_name
    emp.email = email
    emp.phone = phone or None
    emp.tc_no = tc_no or None
    emp.birth_date = date.fromisoformat(birth_date) if birth_date else None
    emp.hire_date = date.fromisoformat(hire_date)
    emp.termination_date = date.fromisoformat(termination_date) if termination_date else None
    emp.department = department or None
    emp.title = title or None
    emp.manager_id = manager_id or None
    emp.employment_type = employment_type
    emp.status = status
    emp.annual_leave_days = annual_leave_days
    emp.gross_salary = gross_salary
    emp.notes = notes or None
    emp.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=302)


# ---------------------------------------------------------------------------
# Özlük belgesi yükle
# ---------------------------------------------------------------------------
@router.post("/{employee_id}/documents/upload")
async def upload_document(
    employee_id: str,
    doc_type: str = Form("diger"),
    title: str = Form(...),
    notes: str = Form(""),
    file: UploadFile = File(...),
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404)

    emp_dir = UPLOADS_DIR / employee_id
    emp_dir.mkdir(parents=True, exist_ok=True)

    # Güvenli dosya adı
    safe_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    file_path = emp_dir / safe_name
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    doc = PersonnelDocument(
        employee_id=employee_id,
        doc_type=doc_type,
        title=title,
        file_name=file.filename,
        file_path=str(file_path),
        uploaded_by=current_user.id,
        notes=notes or None,
    )
    db.add(doc)
    db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}?tab=documents", status_code=302)


@router.get("/{employee_id}/documents/{doc_id}/download")
async def download_document(
    employee_id: str,
    doc_id: str,
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = db.query(PersonnelDocument).filter(
        PersonnelDocument.id == doc_id,
        PersonnelDocument.employee_id == employee_id,
    ).first()
    if not doc or not doc.file_path:
        raise HTTPException(status_code=404)
    return FileResponse(doc.file_path, filename=doc.file_name)


@router.post("/{employee_id}/documents/{doc_id}/delete")
async def delete_document(
    employee_id: str,
    doc_id: str,
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    doc = db.query(PersonnelDocument).filter(
        PersonnelDocument.id == doc_id,
        PersonnelDocument.employee_id == employee_id,
    ).first()
    if doc:
        if doc.file_path and os.path.exists(doc.file_path):
            os.remove(doc.file_path)
        db.delete(doc)
        db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}?tab=documents", status_code=302)
