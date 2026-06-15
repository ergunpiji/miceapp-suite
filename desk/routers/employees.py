"""
Çalışan yönetimi
"""

import json
import os
import shutil
import uuid
from datetime import date, datetime
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin, require_module, get_company_id
from database import get_db
from models import (
    Employee, SalaryPayment, EmployeeBenefit, EmployeeAdvance,
    GeneralExpense, GeneralExpenseCategory,
    BankAccount, CashBook, CashEntry, BankMovement,
    Reference, User, PayrollRecord, PayrollSettings,
    EmployeePersonalInfo, EmployeeAsset, EmployeeDocument, EmployeeCareerEvent,
    LeaveRequest, LeaveType,
)
from templates_config import templates

EMP_UPLOAD_DIR = "static/uploads/employees"
os.makedirs(EMP_UPLOAD_DIR, exist_ok=True)

router = APIRouter(prefix="/employees", tags=["employees"])


def _get_salary_category(db) -> int:
    cat = db.query(GeneralExpenseCategory).filter(
        GeneralExpenseCategory.name == "Maaş"
    ).first()
    if not cat:
        parent = db.query(GeneralExpenseCategory).filter(
            GeneralExpenseCategory.name == "Personel"
        ).first()
        cat = GeneralExpenseCategory(name="Maaş", parent_id=parent.id if parent else None, sort_order=1)
        db.add(cat)
        db.flush()
    return cat.id


def _get_benefit_category(db) -> int:
    cat = db.query(GeneralExpenseCategory).filter(
        GeneralExpenseCategory.name == "Yan Haklar"
    ).first()
    if not cat:
        parent = db.query(GeneralExpenseCategory).filter(
            GeneralExpenseCategory.name == "Personel"
        ).first()
        cat = GeneralExpenseCategory(name="Yan Haklar", parent_id=parent.id if parent else None, sort_order=2)
        db.add(cat)
        db.flush()
    return cat.id


@router.get("", response_class=HTMLResponse, name="employees_list")
async def employees_list(
    request: Request,
    active_only: str = "1",
    current_user: User = Depends(require_module("employees")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    from models import EmployeeAdvance, GeneralExpense
    query = db.query(Employee).filter(Employee.company_id == cid)
    if active_only == "1":
        query = query.filter(Employee.active == True)  # noqa: E712
    employees = query.order_by(Employee.name).all()

    emp_ids = [e.id for e in employees]

    # Açık avans bakiyeleri (open/partial)
    advance_balance: dict = {}
    for adv in db.query(EmployeeAdvance).filter(
        EmployeeAdvance.employee_id.in_(emp_ids),
        EmployeeAdvance.status.in_(["open", "partial"]),
    ).all():
        remaining = (adv.amount or 0) - (adv.repaid_amount or 0)
        advance_balance[adv.employee_id] = advance_balance.get(adv.employee_id, 0) + remaining

    # Çalışana atanmış genel giderler (HBF / masraf beyanı gibi)
    expense_totals: dict = {}
    for exp in db.query(GeneralExpense).filter(
        GeneralExpense.employee_id.in_(emp_ids)
    ).all():
        expense_totals[exp.employee_id] = expense_totals.get(exp.employee_id, 0) + (exp.amount or 0)

    return templates.TemplateResponse(
        "employees/list.html",
        {"request": request, "current_user": current_user,
         "employees": employees, "active_only": active_only,
         "advance_balance": advance_balance, "expense_totals": expense_totals,
         "page_title": "Çalışanlar"},
    )


@router.get("/new", response_class=HTMLResponse, name="employee_new_get")
async def employee_new_get(
    request: Request,
    current_user: User = Depends(require_module("employees", edit=True)),
):
    return templates.TemplateResponse(
        "employees/form.html",
        {"request": request, "current_user": current_user,
         "employee": None, "page_title": "Yeni Çalışan"},
    )


@router.post("/new", name="employee_new_post")
async def employee_new_post(
    name: str = Form(...),
    title: str = Form(""),
    department: str = Form(""),
    start_date: str = Form(...),
    gross_salary: float = Form(0.0),
    net_salary: float = Form(0.0),
    iban: str = Form(""),
    is_retired: str = Form("0"),
    notes: str = Form(""),
    current_user: User = Depends(require_module("employees", edit=True)),
    db: Session = Depends(get_db),
):
    cid = current_user.company_id
    e = Employee(
        name=name.strip(), title=title.strip(), department=department.strip(),
        start_date=date.fromisoformat(start_date),
        gross_salary=gross_salary, net_salary=net_salary,
        iban=iban.strip(), active=True, is_retired=(is_retired == "1"), notes=notes.strip(),
        company_id=cid,
    )
    db.add(e)
    db.commit()
    return RedirectResponse(url=f"/employees/{e.id}", status_code=status.HTTP_302_FOUND)


@router.get("/{employee_id}", response_class=HTMLResponse, name="employee_detail")
async def employee_detail(
    employee_id: str,
    request: Request,
    tab: str = "profil",
    current_user: User = Depends(require_module("employees")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    emp = db.query(Employee).filter(Employee.id == employee_id, Employee.company_id == cid).first()
    if not emp:
        raise HTTPException(status_code=404)
    bank_accounts = db.query(BankAccount).filter(BankAccount.company_id == cid).order_by(BankAccount.name).all()
    cash_books    = db.query(CashBook).filter(CashBook.company_id == cid).order_by(CashBook.name).all()
    references    = db.query(Reference).filter(Reference.status == "aktif", Reference.company_id == cid).order_by(Reference.ref_no).all()

    # Kariyer geçmişi
    career_events = (
        db.query(EmployeeCareerEvent)
        .filter_by(employee_id=employee_id)
        .order_by(EmployeeCareerEvent.event_date.desc())
        .all()
    )
    # İzin geçmişi
    leave_requests = (
        db.query(LeaveRequest)
        .filter_by(employee_id=employee_id)
        .order_by(LeaveRequest.start_date.desc())
        .all()
    )
    # Bordro geçmişi
    payroll_records = (
        db.query(PayrollRecord)
        .filter_by(employee_id=employee_id)
        .filter(PayrollRecord.status != "taslak")
        .order_by(PayrollRecord.period.desc())
        .all()
    )

    return templates.TemplateResponse(
        "employees/detail.html",
        {
            "request": request, "current_user": current_user,
            "employee": emp,
            "tab": tab,
            "salary_payments":  sorted(emp.salary_payments, key=lambda x: x.period, reverse=True),
            "benefits":         sorted(emp.benefits, key=lambda x: x.period, reverse=True),
            "advances":         sorted(emp.advances, key=lambda x: x.advance_date or date.min, reverse=True),
            "bank_accounts": bank_accounts, "cash_books": cash_books,
            "references": references,
            "career_events":   career_events,
            "leave_requests":  leave_requests,
            "payroll_records": payroll_records,
            "today": date.today().isoformat(),
            "page_title": emp.name,
        },
    )


@router.get("/{employee_id}/edit", response_class=HTMLResponse, name="employee_edit_get")
async def employee_edit_get(
    employee_id: str,
    request: Request,
    current_user: User = Depends(require_module("employees", edit=True)),
    db: Session = Depends(get_db),
):
    cid = current_user.company_id
    emp = db.query(Employee).filter(Employee.id == employee_id, Employee.company_id == cid).first()
    if not emp:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "employees/form.html",
        {"request": request, "current_user": current_user,
         "employee": emp, "page_title": f"Düzenle — {emp.name}"},
    )


@router.post("/{employee_id}/edit", name="employee_edit_post")
async def employee_edit_post(
    employee_id: str,
    name: str = Form(...),
    title: str = Form(""),
    department: str = Form(""),
    start_date: str = Form(...),
    end_date: str = Form(""),
    gross_salary: float = Form(0.0),
    net_salary: float = Form(0.0),
    iban: str = Form(""),
    active: str = Form("1"),
    is_retired: str = Form("0"),
    notes: str = Form(""),
    current_user: User = Depends(require_module("employees", edit=True)),
    db: Session = Depends(get_db),
):
    cid = current_user.company_id
    emp = db.query(Employee).filter(Employee.id == employee_id, Employee.company_id == cid).first()
    if not emp:
        raise HTTPException(status_code=404)
    emp.name = name.strip()
    emp.title = title.strip()
    emp.department = department.strip()
    emp.start_date = date.fromisoformat(start_date)
    emp.end_date = date.fromisoformat(end_date) if end_date else None
    emp.gross_salary = gross_salary
    emp.net_salary = net_salary
    emp.iban = iban.strip()
    emp.active = (active == "1")
    emp.is_retired = (is_retired == "1")
    emp.notes = notes.strip()

    # Cari aydaki taslak bordro varsa brüt maaşı ve emekli bayrağını güncelle
    current_period = date.today().strftime("%Y-%m")
    draft = db.query(PayrollRecord).filter_by(
        employee_id=employee_id, period=current_period, status="taslak"
    ).first()
    if draft:
        from routers.bordro import _calc_payroll, _get_settings, _prev_cum_gv, _unpaid_leave_days, _paid_leave_days
        import calendar as _cal
        year = date.today().year
        month = date.today().month
        p_start = date(year, month, 1)
        p_end   = date(year, month, _cal.monthrange(year, month)[1])
        unpaid_days, _ = _unpaid_leave_days(db, employee_id, p_start, p_end)
        paid_days      = _paid_leave_days(db, employee_id, p_start, p_end)
        draft.gross_salary      = gross_salary
        draft.is_retired_worker = (is_retired == "1")
        draft.unpaid_leave_days = unpaid_days
        draft.paid_leave_days   = paid_days
        draft.updated_at        = datetime.utcnow()
        settings = _get_settings(db, year)
        prev_gv  = _prev_cum_gv(db, employee_id, current_period)
        _calc_payroll(draft, settings, prev_gv)

    db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{employee_id}/salary", name="employee_salary_post")
async def employee_salary_post(
    employee_id: str,
    period: str = Form(...),
    gross_amount: float = Form(...),
    net_amount: float = Form(...),
    payment_method: str = Form("banka"),
    bank_account_id: str = Form(None),
    notes: str = Form(""),
    current_user: User = Depends(require_module("employees")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    emp = db.query(Employee).filter(Employee.id == employee_id, Employee.company_id == cid).first()
    if not emp:
        raise HTTPException(status_code=404)

    cat_id = _get_salary_category(db)
    paid_at = datetime.utcnow()
    paid_date = paid_at.date()

    expense = GeneralExpense(
        category_id=cat_id,
        expense_date=paid_date,
        amount=net_amount,
        payment_method=payment_method,
        employee_id=employee_id,
        source="salary",
        description=f"Maaş — {emp.name} — {period}",
        created_by=current_user.id,
    )
    db.add(expense)
    db.flush()

    sp = SalaryPayment(
        employee_id=employee_id, period=period,
        gross_amount=gross_amount, net_amount=net_amount,
        payment_method=payment_method,
        bank_account_id=bank_account_id if payment_method == "banka" else None,
        paid_at=paid_at, general_expense_id=expense.id, notes=notes.strip(),
    )
    db.add(sp)

    if payment_method == "banka" and bank_account_id:
        db.add(BankMovement(
            account_id=bank_account_id,
            movement_date=paid_date,
            movement_type="cikis",
            amount=net_amount,
            description=f"Maaş — {emp.name} — {period}",
        ))
    elif payment_method == "nakit":
        books = db.query(CashBook).first()
        if books:
            db.add(CashEntry(
                book_id=books.id, entry_date=paid_date,
                entry_type="cikis", amount=net_amount,
                description=f"Maaş — {emp.name} — {period}",
            ))

    db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{employee_id}/benefit", name="employee_benefit_post")
async def employee_benefit_post(
    employee_id: str,
    benefit_type: str = Form(...),
    period: str = Form(...),
    amount: float = Form(...),
    payment_method: str = Form("banka"),
    notes: str = Form(""),
    current_user: User = Depends(require_module("employees")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    emp = db.query(Employee).filter(Employee.id == employee_id, Employee.company_id == cid).first()
    if not emp:
        raise HTTPException(status_code=404)

    cat_id = _get_benefit_category(db)
    paid_at = datetime.utcnow()

    expense = GeneralExpense(
        category_id=cat_id,
        expense_date=paid_at.date(),
        amount=amount,
        payment_method=payment_method,
        employee_id=employee_id,
        source="benefit",
        description=f"Yan Hak ({benefit_type}) — {emp.name} — {period}",
        created_by=current_user.id,
    )
    db.add(expense)
    db.flush()

    db.add(EmployeeBenefit(
        employee_id=employee_id, benefit_type=benefit_type,
        period=period, amount=amount,
        paid_at=paid_at, payment_method=payment_method,
        general_expense_id=expense.id, notes=notes.strip(),
    ))
    db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{employee_id}/advance", name="employee_advance_post")
async def employee_advance_post(
    employee_id: str,
    amount: float = Form(...),
    advance_date: str = Form(...),
    reason: str = Form(""),
    advance_type: str = Form("maas"),
    ref_id: str = Form(None),
    payment_method: str = Form("nakit"),
    bank_account_id: str = Form(None),
    current_user: User = Depends(require_module("employees")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    emp = db.query(Employee).filter(Employee.id == employee_id, Employee.company_id == cid).first()
    if not emp:
        raise HTTPException(status_code=404)
    adv_date = date.fromisoformat(advance_date)

    adv = EmployeeAdvance(
        employee_id=employee_id, amount=amount, advance_date=adv_date,
        reason=reason.strip(), status="open", repaid_amount=0,
        advance_type=advance_type,
        ref_id=ref_id if advance_type == "is" else None,
        payment_method=payment_method,
        bank_account_id=bank_account_id if payment_method == "banka" else None,
    )
    db.add(adv)

    adv_type_label = "İş Avansı" if advance_type == "is" else "Maaş Avansı"
    desc = f"{adv_type_label} — {emp.name}"

    if payment_method == "banka" and bank_account_id:
        db.add(BankMovement(
            account_id=bank_account_id, movement_date=adv_date,
            movement_type="cikis", amount=amount, description=desc,
        ))
    elif payment_method == "nakit":
        book = db.query(CashBook).first()
        if book:
            db.add(CashEntry(
                book_id=book.id, entry_date=adv_date,
                entry_type="cikis", amount=amount, description=desc,
            ))
    db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{employee_id}/advance/{advance_id}/repay", name="employee_advance_repay")
async def employee_advance_repay(
    employee_id: str,
    advance_id: str,
    repay_amount: float = Form(...),
    repay_date: str = Form(...),
    payment_method: str = Form("nakit"),
    bank_account_id: str = Form(None),
    current_user: User = Depends(require_module("employees")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    adv = db.query(EmployeeAdvance).filter(
        EmployeeAdvance.id == advance_id, EmployeeAdvance.employee_id == employee_id,
        EmployeeAdvance.company_id == cid,
    ).first()
    if not adv:
        raise HTTPException(status_code=404)
    adv.repaid_amount = (adv.repaid_amount or 0) + repay_amount
    if adv.repaid_amount >= adv.amount:
        adv.status = "closed"
        adv.closed_at = date.fromisoformat(repay_date)
        adv.closed_by = current_user.id
    else:
        adv.status = "partial"
    rep_date = date.fromisoformat(repay_date)
    emp = db.query(Employee).filter(Employee.id == employee_id, Employee.company_id == cid).first()

    # maas_kesintisi = maaştan düşüldü, nakit hareketi yok
    if payment_method != "maas_kesintisi":
        if payment_method == "banka" and bank_account_id:
            db.add(BankMovement(
                account_id=bank_account_id, movement_date=rep_date,
                movement_type="giris", amount=repay_amount,
                description=f"Maaş avansı geri ödeme — {emp.name if emp else ''}",
            ))
        elif payment_method == "nakit":
            book = db.query(CashBook).first()
            if book:
                db.add(CashEntry(
                    book_id=book.id, entry_date=rep_date,
                    entry_type="giris", amount=repay_amount,
                    description=f"Maaş avansı geri ödeme — {emp.name if emp else ''}",
                ))
    db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{employee_id}/advance/{advance_id}/close-is", name="employee_advance_close_is")
async def employee_advance_close_is(
    employee_id: str,
    advance_id: str,
    close_date: str = Form(...),
    expense_items_json: str = Form("[]"),
    cash_return: float = Form(0.0),
    cash_book_id: str = Form(None),
    current_user: User = Depends(require_module("employees")),
    db: Session = Depends(get_db),
):
    """İş avansı kapatma: çalışan fiş/fatura ibraz eder, kalan nakit kasaya iade edilir."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403)
    cid = current_user.company_id
    adv = db.query(EmployeeAdvance).filter(
        EmployeeAdvance.id == advance_id, EmployeeAdvance.employee_id == employee_id,
        EmployeeAdvance.advance_type == "is", EmployeeAdvance.company_id == cid,
    ).first()
    if not adv:
        raise HTTPException(status_code=404)

    try:
        items = json.loads(expense_items_json or "[]")
    except Exception:
        items = []

    total_expenses = sum(float(i.get("amount", 0)) for i in items)
    close_dt = date.fromisoformat(close_date)
    emp = db.query(Employee).filter(Employee.id == employee_id, Employee.company_id == cid).first()

    # Harcama kaydı oluştur (GeneralExpense)
    if total_expenses > 0:
        cat = db.query(GeneralExpenseCategory).filter_by(name="HBF Harcaması").first()
        if not cat:
            cat = db.query(GeneralExpenseCategory).first()
        for item in items:
            amt = float(item.get("amount", 0))
            if amt <= 0:
                continue
            db.add(GeneralExpense(
                category_id=cat.id if cat else None,
                employee_id=employee_id,
                description=item.get("description", "İş Avansı Harcaması"),
                amount=amt,
                expense_date=close_dt,
                source="advance",
                created_by=current_user.id,
            ))

    # Nakit iade → kasaya giriş
    actual_return = min(cash_return, adv.amount - total_expenses)
    if actual_return > 0 and cash_book_id:
        db.add(CashEntry(
            book_id=cash_book_id, entry_date=close_dt,
            entry_type="giris", amount=actual_return,
            description=f"İş avansı nakit iadesi — {emp.name if emp else ''}",
        ))

    adv.expense_items_json = json.dumps(items, ensure_ascii=False)
    adv.cash_return_amount = actual_return
    adv.repaid_amount = total_expenses + actual_return
    adv.status = "closed"
    adv.closed_at = close_dt
    adv.closed_by = current_user.id
    db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{employee_id}/toggle-active", name="employee_toggle_active")
async def employee_toggle_active(
    employee_id: str,
    current_user: User = Depends(require_module("employees", edit=True)),
    db: Session = Depends(get_db),
):
    cid = current_user.company_id
    emp = db.query(Employee).filter(Employee.id == employee_id, Employee.company_id == cid).first()
    if emp:
        emp.active = not emp.active
        db.commit()
    return RedirectResponse(url="/employees", status_code=status.HTTP_302_FOUND)


@router.post("/{employee_id}/delete", name="employee_delete")
async def employee_delete(
    employee_id: str,
    current_user: User = Depends(require_module("employees", edit=True)),
    db: Session = Depends(get_db),
):
    cid = current_user.company_id
    emp = db.query(Employee).filter(Employee.id == employee_id, Employee.company_id == cid).first()
    if emp:
        try:
            db.delete(emp)
            db.commit()
        except Exception:
            db.rollback()
    return RedirectResponse(url="/employees", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Kişisel Bilgiler
# ---------------------------------------------------------------------------

@router.post("/{employee_id}/personal-info", name="employee_personal_info_save")
async def employee_personal_info_save(
    employee_id: str,
    tc_kimlik_no: str           = Form(""),
    birth_date: str             = Form(""),
    birth_place: str            = Form(""),
    gender: str                 = Form(""),
    marital_status: str         = Form(""),
    num_children: int           = Form(0),
    education_level: str        = Form(""),
    military_status: str        = Form(""),
    blood_type: str             = Form(""),
    clothing_size: str          = Form(""),
    disability_degree: int      = Form(0),
    emergency_contact_name: str     = Form(""),
    emergency_contact_phone: str    = Form(""),
    emergency_contact_relation: str = Form(""),
    nationality: str            = Form("TC"),
    address: str                = Form(""),
    current_user: User = Depends(require_module("employees", edit=True)),
    db: Session = Depends(get_db),
):
    cid = current_user.company_id
    emp = db.query(Employee).filter(Employee.id == employee_id, Employee.company_id == cid).first()
    if not emp:
        raise HTTPException(404)
    pi = emp.personal_info
    if not pi:
        pi = EmployeePersonalInfo(employee_id=employee_id)
        db.add(pi)
    pi.tc_kimlik_no    = tc_kimlik_no.strip() or None
    pi.birth_date      = date.fromisoformat(birth_date) if birth_date else None
    pi.birth_place     = birth_place.strip() or None
    pi.gender          = gender or None
    pi.marital_status  = marital_status or None
    pi.num_children    = num_children
    pi.education_level = education_level or None
    pi.military_status = military_status or None
    pi.blood_type      = blood_type or None
    pi.clothing_size   = clothing_size or None
    pi.disability_degree = disability_degree
    pi.emergency_contact_name     = emergency_contact_name.strip() or None
    pi.emergency_contact_phone    = emergency_contact_phone.strip() or None
    pi.emergency_contact_relation = emergency_contact_relation.strip() or None
    pi.nationality = nationality.strip() or "TC"
    pi.address     = address.strip() or None
    db.commit()
    return RedirectResponse(
        url=f"/employees/{employee_id}?tab=kisisel", status_code=status.HTTP_302_FOUND
    )


# ---------------------------------------------------------------------------
# Zimmet
# ---------------------------------------------------------------------------

@router.post("/{employee_id}/zimmet", name="employee_zimmet_add")
async def employee_zimmet_add(
    employee_id: str,
    asset_type: str   = Form(...),
    brand: str        = Form(""),
    model_name: str   = Form(""),
    serial_no: str    = Form(""),
    zimmet_date: str  = Form(...),
    description: str  = Form(""),
    notes: str        = Form(""),
    current_user: User = Depends(require_module("employees", edit=True)),
    db: Session = Depends(get_db),
):
    cid = current_user.company_id
    emp = db.query(Employee).filter(Employee.id == employee_id, Employee.company_id == cid).first()
    if not emp:
        raise HTTPException(404)
    asset = EmployeeAsset(
        employee_id=employee_id,
        asset_type=asset_type,
        brand=brand.strip() or None,
        model_name=model_name.strip() or None,
        serial_no=serial_no.strip() or None,
        zimmet_date=date.fromisoformat(zimmet_date),
        description=description.strip() or None,
        notes=notes.strip() or None,
        status="zimmetli",
        created_by=current_user.id,
    )
    db.add(asset)
    db.commit()
    return RedirectResponse(
        url=f"/employees/{employee_id}?tab=zimmet", status_code=status.HTTP_302_FOUND
    )


@router.post("/{employee_id}/zimmet/{asset_id}/return", name="employee_zimmet_return")
async def employee_zimmet_return(
    employee_id: str,
    asset_id: str,
    return_date: str = Form(...),
    notes: str       = Form(""),
    current_user: User = Depends(require_module("employees", edit=True)),
    db: Session = Depends(get_db),
):
    asset = db.query(EmployeeAsset).filter_by(id=asset_id, employee_id=employee_id).first()
    if not asset:
        raise HTTPException(404)
    asset.status      = "iade_edildi"
    asset.return_date = date.fromisoformat(return_date)
    if notes.strip():
        asset.notes = (asset.notes or "") + f"\nİade notu: {notes.strip()}"
    db.commit()
    return RedirectResponse(
        url=f"/employees/{employee_id}?tab=zimmet", status_code=status.HTTP_302_FOUND
    )


@router.post("/{employee_id}/zimmet/{asset_id}/delete", name="employee_zimmet_delete")
async def employee_zimmet_delete(
    employee_id: str,
    asset_id: str,
    current_user: User = Depends(require_module("employees", edit=True)),
    db: Session = Depends(get_db),
):
    asset = db.query(EmployeeAsset).filter_by(id=asset_id, employee_id=employee_id).first()
    if asset:
        db.delete(asset)
        db.commit()
    return RedirectResponse(
        url=f"/employees/{employee_id}?tab=zimmet", status_code=status.HTTP_302_FOUND
    )


# ---------------------------------------------------------------------------
# Belgeler
# ---------------------------------------------------------------------------

@router.post("/{employee_id}/documents", name="employee_document_upload")
async def employee_document_upload(
    employee_id: str,
    title: str    = Form(...),
    doc_type: str = Form("diger"),
    notes: str    = Form(""),
    file: UploadFile = File(...),
    current_user: User = Depends(require_module("employees", edit=True)),
    db: Session = Depends(get_db),
):
    cid = current_user.company_id
    emp = db.query(Employee).filter(Employee.id == employee_id, Employee.company_id == cid).first()
    if not emp:
        raise HTTPException(404)
    import storage_helper
    ext = os.path.splitext(file.filename or "")[1].lower()
    key = storage_helper.company_key(current_user.company_id, "employees", employee_id, ext)
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Dosya boyutu 50MB sınırını aşıyor.")
    storage_helper.upload_file(content, key)
    doc = EmployeeDocument(
        employee_id=employee_id,
        title=title.strip(),
        doc_type=doc_type,
        file_path=key,
        file_name=file.filename,
        file_size=len(content),
        notes=notes.strip() or None,
        uploaded_by=current_user.id,
    )
    db.add(doc)
    db.commit()
    return RedirectResponse(
        url=f"/employees/{employee_id}?tab=belgeler", status_code=status.HTTP_302_FOUND
    )


@router.get("/{employee_id}/documents/{doc_id}/download", name="employee_document_download")
async def employee_document_download(
    employee_id: str,
    doc_id: str,
    current_user: User = Depends(require_module("employees")),
    db: Session = Depends(get_db),
):
    import storage_helper
    from fastapi.responses import RedirectResponse as _Redirect
    doc = db.query(EmployeeDocument).filter_by(id=doc_id, employee_id=employee_id).first()
    if not doc or not doc.file_path:
        raise HTTPException(404)
    if storage_helper.R2_ENABLED:
        return _Redirect(url=storage_helper.get_file_url_secure(doc.file_path, current_user), status_code=302)
    # Yerel fallback — eski kayıtlarda tam dosya yolu, yeni kayıtlarda anahtar
    local = doc.file_path if os.path.exists(doc.file_path) else os.path.join("static", doc.file_path)
    if not os.path.exists(local):
        raise HTTPException(404)
    return FileResponse(path=local, filename=doc.file_name or "belge", media_type="application/octet-stream")


@router.post("/{employee_id}/documents/{doc_id}/delete", name="employee_document_delete")
async def employee_document_delete(
    employee_id: str,
    doc_id: str,
    current_user: User = Depends(require_module("employees", edit=True)),
    db: Session = Depends(get_db),
):
    doc = db.query(EmployeeDocument).filter_by(id=doc_id, employee_id=employee_id).first()
    if doc:
        import storage_helper
        if doc.file_path:
            if storage_helper.R2_ENABLED:
                storage_helper.delete_file(doc.file_path)
            elif os.path.exists(doc.file_path):
                os.remove(doc.file_path)
        db.delete(doc)
        db.commit()
    return RedirectResponse(
        url=f"/employees/{employee_id}?tab=belgeler", status_code=status.HTTP_302_FOUND
    )


# ---------------------------------------------------------------------------
# Kariyer Geçmişi
# ---------------------------------------------------------------------------

@router.post("/{employee_id}/career", name="employee_career_add")
async def employee_career_add(
    employee_id: str,
    event_date: str  = Form(...),
    event_type: str  = Form(...),
    old_value: str   = Form(""),
    new_value: str   = Form(""),
    description: str = Form(""),
    current_user: User = Depends(require_module("employees", edit=True)),
    db: Session = Depends(get_db),
):
    cid = current_user.company_id
    emp = db.query(Employee).filter(Employee.id == employee_id, Employee.company_id == cid).first()
    if not emp:
        raise HTTPException(404)
    ev = EmployeeCareerEvent(
        employee_id=employee_id,
        event_date=date.fromisoformat(event_date),
        event_type=event_type,
        old_value=old_value.strip() or None,
        new_value=new_value.strip() or None,
        description=description.strip() or None,
        created_by=current_user.id,
    )
    db.add(ev)
    db.commit()
    return RedirectResponse(
        url=f"/employees/{employee_id}?tab=kariyer", status_code=status.HTTP_302_FOUND
    )


@router.post("/{employee_id}/career/{event_id}/delete", name="employee_career_delete")
async def employee_career_delete(
    employee_id: str,
    event_id: str,
    current_user: User = Depends(require_module("employees", edit=True)),
    db: Session = Depends(get_db),
):
    ev = db.query(EmployeeCareerEvent).filter_by(id=event_id, employee_id=employee_id).first()
    if ev:
        db.delete(ev)
        db.commit()
    return RedirectResponse(
        url=f"/employees/{employee_id}?tab=kariyer", status_code=status.HTTP_302_FOUND
    )
