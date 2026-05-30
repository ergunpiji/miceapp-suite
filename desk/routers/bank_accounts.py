"""
Banka hesabı yönetimi
"""

from datetime import date
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from auth import get_current_user, require_admin, require_module, get_company_id
from database import get_db
from models import BankAccount, BankMovement, User
from templates_config import templates

router = APIRouter(prefix="/bank-accounts", tags=["bank_accounts"])


def _balance(db, account: BankAccount):
    ins = db.query(func.sum(BankMovement.amount)).filter(
        BankMovement.account_id == account.id, BankMovement.movement_type == "giris"
    ).scalar() or 0
    outs = db.query(func.sum(BankMovement.amount)).filter(
        BankMovement.account_id == account.id, BankMovement.movement_type == "cikis"
    ).scalar() or 0
    return account.opening_balance + ins - outs


@router.get("", response_class=HTMLResponse, name="bank_accounts_list")
async def bank_accounts_list(
    request: Request,
    current_user: User = Depends(require_module("banks")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    accounts = db.query(BankAccount).filter(BankAccount.company_id == cid).order_by(BankAccount.name).all()
    accounts_with_balance = [{"account": a, "balance": _balance(db, a)} for a in accounts]
    return templates.TemplateResponse(
        "bank_accounts/list.html",
        {"request": request, "current_user": current_user,
         "accounts_with_balance": accounts_with_balance, "page_title": "Banka Hesapları"},
    )


@router.get("/new", response_class=HTMLResponse, name="bank_account_new_get")
async def bank_account_new_get(
    request: Request,
    current_user: User = Depends(require_module("banks", edit=True)),
):
    return templates.TemplateResponse(
        "bank_accounts/form.html",
        {"request": request, "current_user": current_user,
         "account": None, "page_title": "Yeni Banka Hesabı"},
    )


@router.post("/new", name="bank_account_new_post")
async def bank_account_new_post(
    name: str = Form(...),
    bank_name: str = Form(""),
    iban: str = Form(""),
    currency: str = Form("TRY"),
    opening_balance: float = Form(0.0),
    current_user: User = Depends(require_module("banks", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    a = BankAccount(
        name=name.strip(), bank_name=bank_name.strip(),
        iban=iban.strip(), currency=currency,
        opening_balance=opening_balance,
        company_id=cid,
    )
    db.add(a)
    db.commit()
    return RedirectResponse(url=f"/bank-accounts/{a.id}", status_code=status.HTTP_302_FOUND)


@router.get("/{account_id}", response_class=HTMLResponse, name="bank_account_detail")
async def bank_account_detail(
    account_id: str,
    request: Request,
    current_user: User = Depends(require_module("banks")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    account = db.query(BankAccount).filter(BankAccount.id == account_id, BankAccount.company_id == cid).first()
    if not account:
        raise HTTPException(status_code=404)
    movements = db.query(BankMovement).filter(
        BankMovement.account_id == account_id
    ).order_by(BankMovement.movement_date.desc()).all()
    balance = _balance(db, account)
    return templates.TemplateResponse(
        "bank_accounts/detail.html",
        {
            "request": request, "current_user": current_user,
            "account": account, "movements": movements, "balance": balance,
            "today": date.today().isoformat(),
            "page_title": account.name,
        },
    )


@router.post("/{account_id}/movements/new", name="bank_movement_add")
async def bank_movement_add(
    account_id: str,
    movement_date: str = Form(...),
    movement_type: str = Form(...),
    amount: float = Form(...),
    description: str = Form(""),
    current_user: User = Depends(require_module("banks")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    account = db.query(BankAccount).filter(BankAccount.id == account_id, BankAccount.company_id == cid).first()
    if not account:
        raise HTTPException(status_code=404)
    db.add(BankMovement(
        account_id=account_id,
        movement_date=date.fromisoformat(movement_date),
        movement_type=movement_type,
        amount=amount,
        description=description.strip(),
        company_id=cid,
    ))
    db.commit()
    return RedirectResponse(url=f"/bank-accounts/{account_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{account_id}/movements/{movement_id}/delete", name="bank_movement_delete")
async def bank_movement_delete(
    account_id: str,
    movement_id: str,
    current_user: User = Depends(require_module("banks", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    m = db.query(BankMovement).filter(BankMovement.id == movement_id, BankMovement.company_id == cid).first()
    if m and m.account_id == account_id:
        db.delete(m)
        db.commit()
    return RedirectResponse(url=f"/bank-accounts/{account_id}", status_code=status.HTTP_302_FOUND)
