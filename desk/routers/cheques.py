"""
Çek takibi — alınan ve verilen çekler, durum geçişleri, belge yükleme
"""

import os
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

import storage_helper
from auth import get_current_user, require_module, get_company_id
from database import get_db
from models import BankAccount, BankMovement, Cheque, Customer, Vendor, User
from templates_config import templates

router = APIRouter(prefix="/cheques", tags=["cheques"])

_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".pdf", ".heic", ".webp"}
_MAX_UPLOAD = 50 * 1024 * 1024

STATUS_LABELS = {
    "beklemede":     ("secondary", "Beklemede"),
    "tahsil_edildi": ("success",   "Tahsil Edildi"),
    "iptal":         ("dark",      "İptal"),
    "iade":          ("warning",   "İade"),
    "karsilıksız":   ("danger",    "Karşılıksız"),
}


def _save_attachment(file: UploadFile, cheque_id: str, company_id: str | None = None) -> Optional[str]:
    if not file or not file.filename:
        return None
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in _ALLOWED_EXT:
        return None
    key = storage_helper.company_key(company_id, "cheques", cheque_id, ext)
    content = file.file.read(_MAX_UPLOAD + 1)
    if len(content) > _MAX_UPLOAD:
        return None
    storage_helper.upload_file(content, key)
    return key


@router.get("", response_class=HTMLResponse, name="cheques_list")
async def cheques_list(
    request: Request,
    cheque_type: str = "",
    status_filter: str = "",
    current_user: User = Depends(require_module("cheques")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    query = db.query(Cheque).filter(Cheque.company_id == cid)
    if cheque_type:
        query = query.filter(Cheque.cheque_type == cheque_type)
    if status_filter:
        query = query.filter(Cheque.status == status_filter)
    cheques = query.order_by(Cheque.due_date.asc()).all()
    bank_accounts = db.query(BankAccount).filter(BankAccount.company_id == cid).order_by(BankAccount.name).all()
    today = date.today()

    # KPI hesapla
    alinan_bekl = sum(c.amount for c in cheques if c.cheque_type == "alinan" and c.status == "beklemede")
    verilen_bekl = sum(c.amount for c in cheques if c.cheque_type == "verilen" and c.status == "beklemede")
    vadesi_gecmis = [c for c in cheques if c.status == "beklemede" and c.due_date < today]

    return templates.TemplateResponse(
        "cheques/list.html",
        {
            "request": request, "current_user": current_user,
            "cheques": cheques, "cheque_type": cheque_type,
            "status_filter": status_filter, "page_title": "Çekler",
            "bank_accounts": bank_accounts, "today": today.isoformat(),
            "status_labels": STATUS_LABELS,
            "alinan_bekl": alinan_bekl, "verilen_bekl": verilen_bekl,
            "vadesi_gecmis_count": len(vadesi_gecmis),
        },
    )


@router.get("/new", response_class=HTMLResponse, name="cheque_new_get")
async def cheque_new_get(
    request: Request,
    current_user: User = Depends(require_module("cheques")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    vendors = db.query(Vendor).filter(Vendor.active == True, Vendor.company_id == cid).order_by(Vendor.name).all()  # noqa: E712
    customers = db.query(Customer).filter(Customer.company_id == cid).order_by(Customer.name).all()
    bank_accounts = db.query(BankAccount).filter(BankAccount.company_id == cid).order_by(BankAccount.name).all()
    return templates.TemplateResponse(
        "cheques/form.html",
        {
            "request": request, "current_user": current_user,
            "vendors": vendors, "customers": customers,
            "bank_accounts": bank_accounts,
            "cheque": None, "page_title": "Yeni Çek",
        },
    )


@router.post("/new", name="cheque_new_post")
async def cheque_new_post(
    vendor_id: str = Form(None),
    customer_id: str = Form(None),
    cheque_type: str = Form(...),
    cheque_no: str = Form(""),
    bank: str = Form(""),
    branch: str = Form(""),
    amount: float = Form(...),
    currency: str = Form("TRY"),
    cheque_date: str = Form(...),
    due_date: str = Form(...),
    bank_account_id: str = Form(None),
    notes: str = Form(""),
    attachment: UploadFile = File(None),
    current_user: User = Depends(require_module("cheques")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    c = Cheque(
        vendor_id=vendor_id or None,
        customer_id=customer_id or None,
        cheque_type=cheque_type,
        cheque_no=cheque_no.strip(),
        bank=bank.strip(),
        branch=branch.strip(),
        amount=amount,
        currency=currency,
        cheque_date=date.fromisoformat(cheque_date),
        due_date=date.fromisoformat(due_date),
        bank_account_id=bank_account_id or None,
        status="beklemede",
        notes=notes.strip(),
        company_id=cid,
    )
    db.add(c)
    db.flush()
    if attachment and attachment.filename:
        c.attachment = _save_attachment(attachment, c.id, current_user.company_id)
    db.commit()
    return RedirectResponse(url=f"/cheques/{c.id}", status_code=status.HTTP_302_FOUND)


@router.get("/{cheque_id}", response_class=HTMLResponse, name="cheque_detail")
async def cheque_detail(
    cheque_id: str,
    request: Request,
    current_user: User = Depends(require_module("cheques")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    c = db.query(Cheque).filter(Cheque.id == cheque_id, Cheque.company_id == cid).first()
    if not c:
        raise HTTPException(status_code=404)
    bank_accounts = db.query(BankAccount).filter(BankAccount.company_id == cid).order_by(BankAccount.name).all()
    related_movement = None
    if c.status == "tahsil_edildi" and c.bank_account_id:
        search_term = c.cheque_no if c.cheque_no else str(c.id)
        related_movement = (
            db.query(BankMovement)
            .filter(
                BankMovement.account_id == c.bank_account_id,
                BankMovement.description.like(f"%{search_term}%"),
            )
            .order_by(BankMovement.movement_date.desc())
            .first()
        )
    sl = STATUS_LABELS.get(c.status, ("secondary", c.status))
    return templates.TemplateResponse(
        "cheques/detail.html",
        {
            "request": request, "current_user": current_user,
            "cheque": c, "bank_accounts": bank_accounts,
            "related_movement": related_movement,
            "page_title": f"Çek — {c.cheque_no or ('#' + str(c.id))}",
            "status_labels": STATUS_LABELS,
            "status_badge": sl[0], "status_text": sl[1],
            "today": date.today().isoformat(),
        },
    )


@router.get("/{cheque_id}/edit", response_class=HTMLResponse, name="cheque_edit_get")
async def cheque_edit_get(
    cheque_id: str,
    request: Request,
    current_user: User = Depends(require_module("cheques")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    c = db.query(Cheque).filter(Cheque.id == cheque_id, Cheque.company_id == cid).first()
    if not c:
        raise HTTPException(status_code=404)
    if c.status != "beklemede":
        raise HTTPException(status_code=400, detail="Sadece beklemede çekler düzenlenebilir")
    vendors = db.query(Vendor).filter(Vendor.active == True, Vendor.company_id == cid).order_by(Vendor.name).all()  # noqa: E712
    customers = db.query(Customer).filter(Customer.company_id == cid).order_by(Customer.name).all()
    bank_accounts = db.query(BankAccount).filter(BankAccount.company_id == cid).order_by(BankAccount.name).all()
    return templates.TemplateResponse(
        "cheques/form.html",
        {
            "request": request, "current_user": current_user,
            "vendors": vendors, "customers": customers,
            "bank_accounts": bank_accounts,
            "cheque": c, "page_title": "Çek Düzenle",
        },
    )


@router.post("/{cheque_id}/edit", name="cheque_edit_post")
async def cheque_edit_post(
    cheque_id: str,
    vendor_id: str = Form(None),
    customer_id: str = Form(None),
    cheque_type: str = Form(...),
    cheque_no: str = Form(""),
    bank: str = Form(""),
    branch: str = Form(""),
    amount: float = Form(...),
    currency: str = Form("TRY"),
    cheque_date: str = Form(...),
    due_date: str = Form(...),
    bank_account_id: str = Form(None),
    notes: str = Form(""),
    attachment: UploadFile = File(None),
    current_user: User = Depends(require_module("cheques")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    c = db.query(Cheque).filter(Cheque.id == cheque_id, Cheque.company_id == cid).first()
    if not c:
        raise HTTPException(status_code=404)
    if c.status != "beklemede":
        raise HTTPException(status_code=400, detail="Sadece beklemede çekler düzenlenebilir")
    c.vendor_id = vendor_id or None
    c.customer_id = customer_id or None
    c.cheque_type = cheque_type
    c.cheque_no = cheque_no.strip()
    c.bank = bank.strip()
    c.branch = branch.strip()
    c.amount = amount
    c.currency = currency
    c.cheque_date = date.fromisoformat(cheque_date)
    c.due_date = date.fromisoformat(due_date)
    c.bank_account_id = bank_account_id or None
    c.notes = notes.strip()
    if attachment and attachment.filename:
        c.attachment = _save_attachment(attachment, c.id, current_user.company_id)
    db.commit()
    return RedirectResponse(url=f"/cheques/{cheque_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{cheque_id}/settle", name="cheque_settle")
async def cheque_settle(
    cheque_id: str,
    bank_account_id: str = Form(...),
    settled_date: str = Form(...),
    current_user: User = Depends(require_module("cheques")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """Tahsil Et (alınan → banka giris) veya Ödendi (verilen → banka cikis)."""
    c = db.query(Cheque).filter(Cheque.id == cheque_id, Cheque.company_id == cid).first()
    if not c:
        raise HTTPException(status_code=404)
    if c.status != "beklemede":
        raise HTTPException(status_code=400, detail="Bu çek zaten işlem görmüş")

    sdate = date.fromisoformat(settled_date)
    flow = "giris" if c.cheque_type == "alinan" else "cikis"

    desc_parts = ["Çek tahsilat" if c.cheque_type == "alinan" else "Çek ödemesi"]
    if c.cheque_no:
        desc_parts.append(c.cheque_no)
    if c.vendor:
        desc_parts.append(c.vendor.name)
    elif c.customer:
        desc_parts.append(c.customer.name)
    desc = " — ".join(desc_parts)

    db.add(BankMovement(
        account_id=bank_account_id,
        movement_date=sdate,
        movement_type=flow,
        amount=c.amount,
        description=desc,
        company_id=cid,
    ))
    c.status = "tahsil_edildi"
    c.bank_account_id = bank_account_id
    c.settled_date = sdate
    c.settled_by = current_user.id
    db.commit()
    return RedirectResponse(url=f"/cheques/{cheque_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{cheque_id}/cancel", name="cheque_cancel")
async def cheque_cancel(
    cheque_id: str,
    reason: str = Form(...),
    current_user: User = Depends(require_module("cheques")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """İade / İptal / Karşılıksız — banka hareketi oluşturmaz."""
    c = db.query(Cheque).filter(Cheque.id == cheque_id, Cheque.company_id == cid).first()
    if not c:
        raise HTTPException(status_code=404)
    if c.status != "beklemede":
        raise HTTPException(status_code=400, detail="Bu çek zaten işlem görmüş")
    if reason not in {"iade", "iptal", "karsilıksız"}:
        raise HTTPException(status_code=400, detail="Geçersiz durum")
    c.status = reason
    db.commit()
    return RedirectResponse(url=f"/cheques/{cheque_id}", status_code=status.HTTP_302_FOUND)
