"""
Genel gider yönetimi
"""

from datetime import date
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from auth import get_current_user, get_company_id, require_admin, require_module
from database import get_db
from models import (
    GeneralExpense, GeneralExpenseCategory, Vendor,
    Reference, User
)
from templates_config import templates

router = APIRouter(prefix="/general-expenses", tags=["general_expenses"])


def _categories_tree(db, cid: int):
    parents = db.query(GeneralExpenseCategory).filter(
        GeneralExpenseCategory.company_id == cid,
        GeneralExpenseCategory.parent_id == None  # noqa: E711
    ).order_by(GeneralExpenseCategory.sort_order).all()
    for p in parents:
        p._children = db.query(GeneralExpenseCategory).filter(
            GeneralExpenseCategory.company_id == cid,
            GeneralExpenseCategory.parent_id == p.id
        ).order_by(GeneralExpenseCategory.sort_order).all()
    return parents


@router.get("", response_class=HTMLResponse, name="general_expenses_list")
async def general_expenses_list(
    request: Request,
    category_id: str = None,
    payment_method: str = "",
    month: str = "",
    q: str = "",
    current_user: User = Depends(require_module("general_expenses")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    query = db.query(GeneralExpense).filter(GeneralExpense.company_id == cid)
    if category_id:
        # Include subcategories
        sub_ids = [s.id for s in db.query(GeneralExpenseCategory).filter(
            GeneralExpenseCategory.company_id == cid,
            GeneralExpenseCategory.parent_id == category_id
        ).all()]
        ids = [category_id] + sub_ids
        query = query.filter(GeneralExpense.category_id.in_(ids))
    if payment_method:
        query = query.filter(GeneralExpense.payment_method == payment_method)
    if month:
        query = query.filter(func.to_char(GeneralExpense.expense_date, "YYYY-MM") == month)
    if q:
        query = query.filter(GeneralExpense.description.ilike(f"%{q}%"))
    expenses = query.order_by(GeneralExpense.expense_date.desc()).all()
    categories = _categories_tree(db, cid)
    total = sum(e.amount for e in expenses)
    return templates.TemplateResponse(
        "general_expenses/list.html",
        {
            "request": request, "current_user": current_user,
            "expenses": expenses, "categories": categories,
            "category_id": category_id, "payment_method": payment_method,
            "month": month, "q": q, "total": total,
            "page_title": "Genel Giderler",
        },
    )


@router.get("/new", response_class=HTMLResponse, name="general_expense_new_get")
async def general_expense_new_get(
    request: Request,
    current_user: User = Depends(require_module("general_expenses")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    categories = db.query(GeneralExpenseCategory).filter(
        GeneralExpenseCategory.company_id == cid
    ).order_by(
        GeneralExpenseCategory.parent_id, GeneralExpenseCategory.sort_order
    ).all()
    vendors = db.query(Vendor).filter(Vendor.active == True).order_by(Vendor.name).all()  # noqa: E712
    refs = db.query(Reference).filter(Reference.status == "aktif").order_by(Reference.ref_no).all()
    return templates.TemplateResponse(
        "general_expenses/form.html",
        {
            "request": request, "current_user": current_user,
            "expense": None, "categories": categories,
            "vendors": vendors, "refs": refs,
            "page_title": "Yeni Gider",
        },
    )


@router.post("/new", name="general_expense_new_post")
async def general_expense_new_post(
    category_id: str = Form(...),
    expense_date: str = Form(...),
    amount: float = Form(...),
    vat_rate: float = Form(0.0),
    payment_method: str = Form(None),
    vendor_id: str = Form(None),
    ref_id: str = Form(None),
    description: str = Form(""),
    current_user: User = Depends(require_module("general_expenses")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    e = GeneralExpense(
        company_id=cid,
        category_id=category_id,
        expense_date=date.fromisoformat(expense_date),
        amount=amount,
        vat_rate=vat_rate,
        payment_method=payment_method,
        vendor_id=vendor_id,
        ref_id=ref_id,
        source="manual",
        description=description.strip(),
        created_by=current_user.id,
    )
    db.add(e)
    db.commit()
    return RedirectResponse(url="/general-expenses?_ok=Gider+kaydedildi", status_code=status.HTTP_302_FOUND)


@router.get("/summary", response_class=HTMLResponse, name="general_expenses_summary")
async def general_expenses_summary(
    request: Request,
    year: int = None,
    current_user: User = Depends(require_module("general_expenses")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    if not year:
        year = date.today().year
    from sqlalchemy import extract
    expenses = db.query(GeneralExpense).filter(
        GeneralExpense.company_id == cid,
        extract("year", GeneralExpense.expense_date) == year
    ).all()
    categories = _categories_tree(db, cid)
    cat_totals = {}
    for e in expenses:
        cat_totals[e.category_id] = cat_totals.get(e.category_id, 0) + e.amount
    return templates.TemplateResponse(
        "general_expenses/summary.html",
        {
            "request": request, "current_user": current_user,
            "expenses": expenses, "categories": categories,
            "cat_totals": cat_totals, "year": year,
            "total": sum(e.amount for e in expenses),
            "page_title": f"Gider Özeti — {year}",
        },
    )


@router.get("/{expense_id}/edit", response_class=HTMLResponse, name="general_expense_edit_get")
async def general_expense_edit_get(
    expense_id: str,
    request: Request,
    current_user: User = Depends(require_module("general_expenses")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    e = db.query(GeneralExpense).filter(
        GeneralExpense.id == expense_id, GeneralExpense.company_id == cid
    ).first()
    if not e or e.source != "manual":
        raise HTTPException(status_code=404)
    categories = db.query(GeneralExpenseCategory).filter(
        GeneralExpenseCategory.company_id == cid
    ).order_by(
        GeneralExpenseCategory.parent_id, GeneralExpenseCategory.sort_order
    ).all()
    vendors = db.query(Vendor).filter(Vendor.active == True).order_by(Vendor.name).all()  # noqa: E712
    refs = db.query(Reference).filter(Reference.status == "aktif").order_by(Reference.ref_no).all()
    return templates.TemplateResponse(
        "general_expenses/form.html",
        {
            "request": request, "current_user": current_user,
            "expense": e, "categories": categories,
            "vendors": vendors, "refs": refs,
            "page_title": "Gider Düzenle",
        },
    )


@router.post("/{expense_id}/edit", name="general_expense_edit_post")
async def general_expense_edit_post(
    expense_id: str,
    category_id: str = Form(...),
    expense_date: str = Form(...),
    amount: float = Form(...),
    vat_rate: float = Form(0.0),
    payment_method: str = Form(None),
    vendor_id: str = Form(None),
    ref_id: str = Form(None),
    description: str = Form(""),
    current_user: User = Depends(require_module("general_expenses")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    e = db.query(GeneralExpense).filter(
        GeneralExpense.id == expense_id, GeneralExpense.company_id == cid
    ).first()
    if not e:
        raise HTTPException(status_code=404)
    e.category_id = category_id
    e.expense_date = date.fromisoformat(expense_date)
    e.amount = amount
    e.vat_rate = vat_rate
    e.payment_method = payment_method
    e.vendor_id = vendor_id
    e.ref_id = ref_id
    e.description = description.strip()
    db.commit()
    return RedirectResponse(url="/general-expenses?_ok=Gider+güncellendi", status_code=status.HTTP_302_FOUND)


@router.post("/{expense_id}/delete", name="general_expense_delete")
async def general_expense_delete(
    expense_id: str,
    current_user: User = Depends(require_module("general_expenses", edit=True)),
    db: Session = Depends(get_db),
):
    e = db.query(GeneralExpense).filter(
        GeneralExpense.id == expense_id, GeneralExpense.company_id == current_user.company_id
    ).first()
    if e and e.source == "manual":
        db.delete(e)
        db.commit()
    return RedirectResponse(url="/general-expenses?_ok=Gider+silindi", status_code=status.HTTP_302_FOUND)
