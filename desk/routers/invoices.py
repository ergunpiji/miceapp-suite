"""
Fatura yönetimi
"""

from datetime import date, datetime
from typing import List
import json
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from auth import get_current_user, get_company_id, require_admin, require_module, safe_redirect
from access_policy import visible_invoices_query, can_access_invoice, can_access_customer
from database import get_db
from models import (
    Invoice, InvoicePayment, Reference, Vendor, Customer, CashBook, BankAccount,
    CreditCard, CreditCardTxn, Cheque, CashEntry, BankMovement,
    User, INVOICE_TYPES, PAYMENT_METHODS, VAT_RATES
)
from templates_config import templates

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.get("", response_class=HTMLResponse, name="invoices_list")
async def invoices_list(
    request: Request,
    invoice_type: str = "",
    status_filter: str = "",
    approval: str = "",
    q: str = "",
    archived: str = "",
    current_user: User = Depends(require_module("invoices")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    show_archived = archived == "1" and current_user.has_role_min("mudur")
    query = visible_invoices_query(db, current_user)
    if approval == "pending_mine":
        query = query.filter(
            Invoice.current_approver_id == current_user.id,
            Invoice.approval_status == "onay_bekliyor",
        )
    elif approval == "pending":
        query = query.filter(Invoice.approval_status == "onay_bekliyor")
    elif approval == "rejected":
        query = query.filter(Invoice.approval_status == "reddedildi")
    else:
        # Varsayılan: onay bekleyenleri hariç tut (ayrı "Fatura Talepleri" linki var)
        from sqlalchemy import or_ as _or2
        query = query.filter(
            _or2(Invoice.approval_status.is_(None), Invoice.approval_status != "onay_bekliyor")
        )
    if show_archived:
        query = query.filter(Invoice.deleted_at != None)  # noqa: E711
    else:
        query = query.filter(Invoice.deleted_at == None)  # noqa: E711
    if invoice_type:
        query = query.filter(Invoice.invoice_type == invoice_type)
    if status_filter:
        query = query.filter(Invoice.status == status_filter)
    if q:
        query = query.filter(Invoice.invoice_no.ilike(f"%{q}%"))
    invoices = query.options(joinedload(Invoice.payments)).order_by(Invoice.invoice_date.desc()).all()
    return templates.TemplateResponse(
        "invoices/list.html",
        {
            "request": request, "current_user": current_user,
            "invoices": invoices, "invoice_types": INVOICE_TYPES,
            "invoice_type": invoice_type, "status_filter": status_filter,
            "q": q, "page_title": "Faturalar",
            "show_archived": show_archived,
        },
    )


@router.get("/new", response_class=HTMLResponse, name="invoice_new_get")
async def invoice_new_get(
    request: Request,
    ref_id: str = None,
    vendor_id: str = None,
    current_user: User = Depends(require_module("invoices", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    import json
    refs = db.query(Reference).filter(Reference.status == "aktif", Reference.company_id == cid).order_by(Reference.ref_no).all()
    vendors = db.query(Vendor).filter(Vendor.active == True, Vendor.company_id == cid).order_by(Vendor.name).all()  # noqa: E712
    customers = db.query(Customer).filter(Customer.active == True, Customer.company_id == cid).order_by(Customer.name).all()  # noqa: E712
    vendors_json = json.dumps([
        {"id": v.id, "name": v.name, "payment_term": v.payment_term or 30, "tax_no": v.tax_no or ""}
        for v in vendors
    ])
    customers_json = json.dumps([
        {"id": c.id, "name": c.name, "tax_no": c.tax_no or "",
         "payment_term": c.payment_term, "payment_dow": c.payment_dow}
        for c in customers
    ])
    refs_json = json.dumps([
        {"id": r.id, "text": r.ref_no + " — " + r.title}
        for r in refs
    ])
    return templates.TemplateResponse(
        "invoices/form.html",
        {
            "request": request, "current_user": current_user,
            "invoice": None, "refs": refs, "vendors": vendors,
            "vendors_json": vendors_json, "customers_json": customers_json,
            "refs_json": refs_json,
            "invoice_types": INVOICE_TYPES, "vat_rates": VAT_RATES,
            "preselected_ref_id": ref_id,
            "preselected_vendor_id": vendor_id,
            "page_title": "Fatura Girişi",
        },
    )


@router.post("/new", name="invoice_new_post")
async def invoice_new_post(
    request: Request,
    ref_id: str = Form(None),
    vendor_id: str = Form(None),
    customer_id: str = Form(None),
    invoice_type: str = Form(...),
    invoice_no: str = Form(""),
    invoice_date: str = Form(...),
    due_date: str = Form(""),
    currency: str = Form("TRY"),
    notes: str = Form(""),
    items_json: str = Form("[]"),
    send_to_gib: str = Form(""),
    attachment_file: UploadFile = File(None),
    current_user: User = Depends(require_module("invoices", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    net_total, vat_total = _parse_items(items_json)
    amount = net_total
    vat_rate = (vat_total / net_total) if net_total else 0.0
    _is_kesilen = invoice_type in ("kesilen", "iade_gelen")
    inv_date = date.fromisoformat(invoice_date)
    coll_date = None
    if _is_kesilen and customer_id:
        c = db.get(Customer, customer_id)
        if c and c.payment_term is not None:
            coll_date = _compute_collection_date(inv_date, c.payment_term, c.payment_dow)
    inv = Invoice(
        ref_id=ref_id,
        vendor_id=None if _is_kesilen else vendor_id,
        customer_id=customer_id if _is_kesilen else None,
        invoice_type=invoice_type,
        invoice_no=invoice_no.strip(),
        invoice_date=inv_date,
        due_date=date.fromisoformat(due_date) if due_date else None,
        collection_date=coll_date,
        amount=amount,
        vat_rate=round(vat_rate, 4),
        total_amount=round(amount * (1 + round(vat_rate, 4)), 2),
        payment_status="unpaid",
        currency=currency,
        status="approved",
        notes=notes.strip(),
        items_json=items_json if items_json != "[]" else None,
        created_by=current_user.id,
        company_id=cid,
    )
    # Senaryo A: gelen faturada referans seçildiyse sahibi otomatik onaylayıcı atanır
    if invoice_type == "gelen" and ref_id:
        ref_obj = db.query(Reference).filter(Reference.id == ref_id).first()
        if ref_obj and ref_obj.owner_id:
            inv.current_approver_id = ref_obj.owner_id
    # Senaryo B: gelen faturada referans seçilmediyse havuza at
    if invoice_type == "gelen" and not ref_id:
        inv.in_pool = True

    db.add(inv)
    db.flush()
    # Çok kademeli onay zinciri başlat (temsilci → müdür → GM, limit dahilinde)
    # Admin/GM kendisi yaratıyorsa onay zincirini atla — direkt approved.
    if current_user.role in ("admin", "super_admin", "genel_mudur"):
        inv.approval_status = "approved"
    else:
        from invoice_approval import start_approval
        start_approval(db, inv, current_user)
    # Koordinatör onay akışı: kesilen fatura bir referansa bağlıysa miceapp onayına gönder
    if invoice_type == "kesilen" and ref_id:
        inv.coordinator_status = "beklemede"
    db.commit()
    db.refresh(inv)
    if attachment_file and attachment_file.filename:
        import os, storage_helper
        ext = os.path.splitext(attachment_file.filename)[1].lower()
        key = storage_helper.company_key(current_user.company_id, "invoices", inv.id, ext)
        _content = await attachment_file.read()
        if len(_content) <= 50 * 1024 * 1024:
            inv.attachment_path = storage_helper.upload_file(_content, key)
        db.commit()

    # "Kaydet ve GİB'e Gönder" basıldıysa ve modül aktifse otomatik gönder
    redirect_query = ""
    if (send_to_gib == "1" and invoice_type in ("kesilen", "komisyon")
            and current_user.is_admin):
        # Modül aktif mi?
        from models import SystemSetting
        s = db.query(SystemSetting).filter(
            SystemSetting.key == "module_einvoice_enabled"
        ).first()
        if s and s.value == "1":
            # Müşteri bilgisi tam mı?
            customer = inv.reference.customer if (inv.reference and inv.reference.customer) else None
            missing = []
            if not customer:
                missing.append("müşteri")
            else:
                if not customer.tax_no:
                    missing.append("vergi no")
                if not customer.tax_office:
                    missing.append("vergi dairesi")

            if missing:
                # Eksik bilgi var — kayıt edildi, gönderim atlandı, uyarı
                redirect_query = f"?ef_warning=" + ",".join(missing)
            else:
                # Gönder
                try:
                    from app import einvoice_module as mod
                    if mod is not None:
                        from datetime import datetime as _dt
                        # Mükellef cache kontrolü
                        if customer.is_efatura_user is None:
                            info = mod.provider.check_efatura_user(customer.tax_no)
                            customer.is_efatura_user = info.is_user
                            customer.efatura_alias = info.alias
                            customer.efatura_checked_at = _dt.utcnow()
                            db.flush()
                        is_efatura = bool(customer.is_efatura_user)

                        # Kalemlerden InvoicePayload üret
                        import json as _json
                        lines = []
                        try:
                            raw = _json.loads(inv.items_json or "[]")
                            for li in raw:
                                lines.append({
                                    "description": li.get("description") or "Hizmet",
                                    "quantity": float(li.get("qty") or 1),
                                    "unit": li.get("unit") or "ADET",
                                    "unit_price": float(li.get("price") or 0),
                                    "vat_rate": float(li.get("vat_rate") or inv.vat_rate or 0.20),
                                    "discount": float(li.get("discount") or 0),
                                })
                        except Exception:  # noqa: BLE001
                            pass
                        if not lines:
                            lines = [{
                                "description": inv.invoice_no or "Hizmet bedeli",
                                "quantity": 1, "unit": "ADET",
                                "unit_price": float(inv.amount or 0),
                                "vat_rate": float(inv.vat_rate or 0.20),
                                "discount": 0,
                            }]
                        payload_dict = {
                            "invoice_no": inv.invoice_no or f"INV-{inv.id}",
                            "invoice_date": inv.invoice_date.isoformat(),
                            "currency": inv.currency or "TRY",
                            "is_efatura": is_efatura,
                            "customer": {
                                "name": customer.name, "tax_no": customer.tax_no,
                                "tax_office": customer.tax_office,
                                "address": customer.address or "",
                                "email": customer.email or "",
                                "phone": customer.phone or "",
                                "alias": customer.efatura_alias,
                            },
                            "lines": lines,
                            "notes": inv.notes or "",
                        }
                        from prizma_einvoice import build_invoice_payload_from_dict, submit_payload
                        sub = submit_payload(
                            db,
                            invoice_id=inv.id,
                            payload=build_invoice_payload_from_dict(payload_dict),
                            submission_model=mod.Submission,
                            provider=mod.provider,
                            user_id=current_user.id,
                        )
                        inv.einvoice_status = sub.status
                        inv.einvoice_uuid = sub.uuid
                        inv.einvoice_pdf_url = sub.pdf_url
                        inv.einvoice_sent_at = sub.submitted_at
                        db.commit()
                        redirect_query = "?ef_sent=1"
                except Exception as exc:  # noqa: BLE001
                    print(f"[invoice-create-send] hata: {exc}", flush=True)
                    redirect_query = "?ef_error=1"

    return RedirectResponse(
        url=f"/invoices/{inv.id}{redirect_query}",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/parse-pdf", name="invoice_parse_pdf")
async def invoice_parse_pdf(
    file: UploadFile = File(...),
    current_user: User = Depends(require_module("invoices", edit=True)),
):
    import io, re
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Sadece PDF dosyası kabul edilir.")
    contents = await file.read()
    try:
        import pdfplumber
    except ImportError:
        raise HTTPException(status_code=500, detail="pdfplumber kütüphanesi bulunamadı.")

    text = ""
    tables = []
    try:
        with pdfplumber.open(io.BytesIO(contents)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text += page_text + "\n"
                try:
                    for tbl in (page.extract_tables() or []):
                        if tbl:
                            tables.append(tbl)
                except Exception:
                    pass
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"PDF okunamadı: {str(e)}")

    result: dict = {}
    filled: list = []

    def search(patterns):
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
            if m:
                return m.group(1).strip()
        return None

    # Fatura No
    v = search([
        r'(?:FATURA\s*NO|Fatura\s*Numaras[ıi])\s*[:\s]+([A-Z0-9\-/]{4,30})',
        r'(?:ETTN|No\.?)\s*[:\s]+([A-Z0-9\-/]{4,30})',
    ])
    if v:
        result["invoice_no"] = v
        filled.append("Fatura No")

    # Fatura Tarihi (DD.MM.YYYY → YYYY-MM-DD)
    def to_iso(s):
        m2 = re.match(r'^(\d{2})[./](\d{2})[./](\d{4})$', s.strip())
        return f"{m2.group(3)}-{m2.group(2)}-{m2.group(1)}" if m2 else s

    v = search([
        r'(?:FATURA\s*TARİHİ|Fatura\s*Tarihi|Düzenleme\s*Tarihi)\s*[:\s]+(\d{2}[./]\d{2}[./]\d{4})',
    ])
    if v:
        result["invoice_date"] = to_iso(v)
        filled.append("Fatura Tarihi")

    v = search([
        r'(?:VADE\s*TARİHİ|Vade\s*Tarihi|Son\s*Ödeme)\s*[:\s]+(\d{2}[./]\d{2}[./]\d{4})',
    ])
    if v:
        result["due_date"] = to_iso(v)
        filled.append("Vade Tarihi")

    # Tedarikçi VKN (10 hane)
    v = search([
        r'(?:VKN|V\.K\.N\.?|Vergi\s*Kimlik\s*No\.?|VERGİ\s*NO)\s*[:/\s]+(\d{10})',
        r'(\d{10})\s*(?:vergi|VKN)',
    ])
    if v:
        result["vendor_tax_no"] = v
        filled.append("Tedarikçi VKN")

    # Tedarikçi adı
    v = search([
        r'(?:Unvan|UNVAN|Satıcı\s*Unvan[ıi]|Firma\s*Ad[ıi])\s*[:\s]+(.{5,120})',
    ])
    if v:
        result["vendor_name"] = v.split("\n")[0].strip()
        filled.append("Tedarikçi")

    # Kalemler — tablodan çek
    items = []
    for tbl in tables:
        if len(tbl) < 2:
            continue
        header = [str(c or "").lower() for c in tbl[0]]
        desc_col = next((i for i, h in enumerate(header) if any(k in h for k in ("açıklama", "ürün", "hizmet", "description", "mal"))), None)
        net_col  = next((i for i, h in enumerate(header) if any(k in h for k in ("tutar", "fiyat", "amount", "price", "bedel"))), None)
        vat_col  = next((i for i, h in enumerate(header) if any(k in h for k in ("kdv", "vat", "oran", "%"))), None)
        if desc_col is None or net_col is None:
            continue
        for row in tbl[1:]:
            if not row or len(row) <= net_col:
                continue
            desc = str(row[desc_col] or "").strip()
            if not desc or desc.lower() in ("", "-", "toplam", "total", "genel toplam", "ara toplam"):
                continue
            raw_net = str(row[net_col] or "0").strip()
            clean = re.sub(r"[^\d,.]", "", raw_net).replace(".", "").replace(",", ".")
            net_val = float(clean) if clean else 0.0
            vat_pct = 20
            if vat_col is not None and vat_col < len(row):
                vm = re.search(r"(\d+)", str(row[vat_col] or ""))
                if vm:
                    vp = int(vm.group(1))
                    if vp in (0, 1, 8, 10, 18, 20):
                        vat_pct = vp
            if desc and net_val > 0:
                items.append({"desc": desc, "net": net_val, "vat_pct": vat_pct})
        if items:
            break  # ilk geçerli tabloyu kullan

    if items:
        result["items"] = items
        filled.append(f"{len(items)} kalem")

    result["_msg"] = ("Dolduruldu: " + ", ".join(filled) + ". Lütfen kontrol edin.") if filled else "Alan bulunamadı. Lütfen manuel doldurun."
    return result


@router.get("/{invoice_id}", response_class=HTMLResponse, name="invoice_detail")
async def invoice_detail(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(require_module("invoices")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    if not can_access_invoice(db, current_user, invoice_id):
        raise HTTPException(status_code=404)
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.company_id == cid).first()
    if not inv:
        raise HTTPException(status_code=404)
    cash_books = db.query(CashBook).filter(CashBook.company_id == cid).all()
    bank_accounts = db.query(BankAccount).filter(BankAccount.company_id == cid).all()
    credit_cards = db.query(CreditCard).filter(CreditCard.company_id == cid).all()
    split_children = (
        db.query(Invoice)
        .filter(Invoice.split_parent_id == inv.id)
        .options(joinedload(Invoice.reference))
        .all()
    ) if inv.is_split_parent else []
    return templates.TemplateResponse(
        "invoices/detail.html",
        {
            "request": request, "current_user": current_user,
            "invoice": inv, "cash_books": cash_books,
            "bank_accounts": bank_accounts, "credit_cards": credit_cards,
            "payment_methods": PAYMENT_METHODS,
            "split_children_ctx": split_children,
            "page_title": f"Fatura — {inv.invoice_no or inv.id}",
        },
    )


def _compute_collection_date(invoice_date, payment_term: int, payment_dow):
    from datetime import timedelta
    due = invoice_date + timedelta(days=int(payment_term))
    if payment_dow is None:
        return due
    days_ahead = (int(payment_dow) - due.weekday()) % 7
    return due + timedelta(days=days_ahead)


def _parse_items(items_json: str):
    """Returns (net_total, vat_total) from items JSON string."""
    import json as _json
    try:
        items = _json.loads(items_json or "[]")
    except Exception:
        items = []
    net_total = sum(float(i.get("net", 0)) for i in items)
    vat_total = sum(float(i.get("vat_amt", 0)) for i in items)
    return net_total, vat_total


@router.get("/{invoice_id}/edit", response_class=HTMLResponse, name="invoice_edit_get")
async def invoice_edit_get(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(require_module("invoices", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    import json
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.company_id == cid).first()
    if not inv:
        raise HTTPException(status_code=404)
    refs = db.query(Reference).filter(Reference.status == "aktif", Reference.company_id == cid).order_by(Reference.ref_no).all()
    vendors = db.query(Vendor).filter(Vendor.active == True, Vendor.company_id == cid).order_by(Vendor.name).all()  # noqa: E712
    customers = db.query(Customer).filter(Customer.active == True, Customer.company_id == cid).order_by(Customer.name).all()  # noqa: E712
    vendors_json = json.dumps([
        {"id": v.id, "name": v.name, "payment_term": v.payment_term or 30, "tax_no": v.tax_no or ""}
        for v in vendors
    ])
    customers_json = json.dumps([
        {"id": c.id, "name": c.name, "tax_no": c.tax_no or "",
         "payment_term": c.payment_term, "payment_dow": c.payment_dow}
        for c in customers
    ])
    refs_json = json.dumps([
        {"id": r.id, "text": r.ref_no + " — " + r.title}
        for r in refs
    ])
    return templates.TemplateResponse(
        "invoices/form.html",
        {
            "request": request, "current_user": current_user,
            "invoice": inv, "refs": refs, "vendors": vendors,
            "vendors_json": vendors_json, "customers_json": customers_json,
            "refs_json": refs_json,
            "invoice_types": INVOICE_TYPES, "vat_rates": VAT_RATES,
            "preselected_ref_id": None,
            "preselected_vendor_id": None,
            "page_title": f"Düzenle — Fatura {inv.invoice_no or inv.id}",
        },
    )


@router.post("/{invoice_id}/edit", name="invoice_edit_post")
async def invoice_edit_post(
    invoice_id: str,
    ref_id: str = Form(None),
    vendor_id: str = Form(None),
    customer_id: str = Form(None),
    invoice_type: str = Form(...),
    invoice_no: str = Form(""),
    invoice_date: str = Form(...),
    due_date: str = Form(""),
    currency: str = Form("TRY"),
    notes: str = Form(""),
    items_json: str = Form("[]"),
    attachment_file: UploadFile = File(None),
    current_user: User = Depends(require_module("invoices", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.company_id == cid).first()
    if not inv:
        raise HTTPException(status_code=404)
    net_total, vat_total = _parse_items(items_json)
    _is_kesilen = invoice_type in ("kesilen", "iade_gelen")
    inv_date = date.fromisoformat(invoice_date)
    coll_date = inv.collection_date
    if _is_kesilen and customer_id:
        c = db.get(Customer, customer_id)
        if c and c.payment_term is not None:
            coll_date = _compute_collection_date(inv_date, c.payment_term, c.payment_dow)
    elif not _is_kesilen:
        coll_date = None
    inv.ref_id = ref_id
    inv.vendor_id = None if _is_kesilen else vendor_id
    inv.customer_id = customer_id if _is_kesilen else None
    inv.invoice_type = invoice_type
    inv.invoice_no = invoice_no.strip()
    inv.invoice_date = inv_date
    inv.due_date = date.fromisoformat(due_date) if due_date else None
    inv.collection_date = coll_date
    inv.amount = net_total
    inv.vat_rate = round((vat_total / net_total) if net_total else 0.0, 4)
    inv.currency = currency
    inv.notes = notes.strip()
    inv.items_json = items_json if items_json != "[]" else None
    # Koordinatör durumunu güncelle: kesilen+ref varsa beklemede, yoksa temizle
    if invoice_type == "kesilen" and ref_id:
        if inv.coordinator_status is None:
            inv.coordinator_status = "beklemede"
    else:
        if inv.coordinator_status == "beklemede":
            inv.coordinator_status = None
    if attachment_file and attachment_file.filename:
        import os, storage_helper
        ext = os.path.splitext(attachment_file.filename)[1].lower()
        key = storage_helper.company_key(current_user.company_id, "invoices", invoice_id, ext)
        _content = await attachment_file.read()
        if len(_content) <= 50 * 1024 * 1024:
            inv.attachment_path = storage_helper.upload_file(_content, key)
    db.commit()
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{invoice_id}/pay", name="invoice_pay")
async def invoice_pay(
    invoice_id: str,
    payment_method: str = Form(...),
    pay_amount: float = Form(None),
    pay_date: str = Form(""),
    cash_book_id: str = Form(None),
    bank_account_id: str = Form(None),
    credit_card_id: str = Form(None),
    cheque_no: str = Form(""),
    cheque_bank: str = Form(""),
    cheque_date: str = Form(""),
    cheque_due_date: str = Form(""),
    pay_notes: str = Form(""),
    current_user: User = Depends(require_module("invoices", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    from payment_helpers import apply_invoice_payment
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.company_id == cid).first()
    if not inv or inv.status == "paid":
        raise HTTPException(status_code=400, detail="Fatura bulunamadı veya zaten ödendi.")

    amount = pay_amount if pay_amount and pay_amount > 0 else inv.total_with_vat
    pdate = date.fromisoformat(pay_date) if pay_date else date.today()

    apply_invoice_payment(
        db, inv,
        payment_method=payment_method, amount=amount, pdate=pdate,
        current_user=current_user,
        cash_book_id=cash_book_id, bank_account_id=bank_account_id,
        credit_card_id=credit_card_id,
        cheque_no=cheque_no, cheque_bank=cheque_bank,
        cheque_date_str=cheque_date, cheque_due_date_str=cheque_due_date,
        pay_notes=pay_notes,
    )
    db.commit()
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{invoice_id}/payment/{payment_id}/delete", name="invoice_payment_delete")
async def invoice_payment_delete(
    invoice_id: str,
    payment_id: str,
    current_user: User = Depends(require_module("invoices", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.company_id == cid).first()
    pmt = db.query(InvoicePayment).filter(
        InvoicePayment.id == payment_id,
        InvoicePayment.invoice_id == invoice_id,
    ).first()
    if not pmt:
        raise HTTPException(status_code=404)

    # İlgili kasa/banka hareketlerini de sil
    # instruction_id FK varsa bunu önceliklendir; yoksa tutar yakınlığıyla eşleştir
    for ce in list(inv.cash_entries):
        if ce.invoice_id == invoice_id:
            if (pmt.instruction_id and ce.instruction_id == pmt.instruction_id) or (
                not pmt.instruction_id and abs(ce.amount - pmt.amount) < 0.01
            ):
                db.delete(ce)
                break
    for bm in list(inv.bank_movements):
        if bm.invoice_id == invoice_id:
            if (pmt.instruction_id and bm.instruction_id == pmt.instruction_id) or (
                not pmt.instruction_id and abs(bm.amount - pmt.amount) < 0.01
            ):
                db.delete(bm)
                break

    db.delete(pmt)
    db.flush()

    # Status güncelle
    total = inv.total_with_vat
    remaining_payments = db.query(InvoicePayment).filter(
        InvoicePayment.invoice_id == invoice_id
    ).all()
    paid = sum(p.amount for p in remaining_payments)
    if paid <= 0.01:
        inv.status = "approved"
        inv.paid_at = None
        inv.payment_method = None
    elif paid >= total - 0.01:
        inv.status = "paid"
    else:
        inv.status = "partial"

    db.commit()
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=status.HTTP_302_FOUND)


@router.post("/pay-bulk", name="invoice_pay_bulk")
async def invoice_pay_bulk(
    invoice_ids: List[int] = Form(...),
    payment_method: str = Form(...),
    cash_book_id: str = Form(None),
    bank_account_id: str = Form(None),
    credit_card_id: str = Form(None),
    redirect_url: str = Form("/invoices"),
    current_user: User = Depends(require_module("invoices", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """Toplu ödeme — her fatura için InvoicePayment + yan kayıt yaratır (audit)."""
    from payment_helpers import apply_invoice_payment
    today = date.today()
    for inv_id in invoice_ids:
        inv = db.query(Invoice).filter(Invoice.id == inv_id, Invoice.company_id == cid).first()
        if not inv or inv.status == "paid":
            continue
        try:
            apply_invoice_payment(
                db, inv,
                payment_method=payment_method, amount=inv.remaining, pdate=today,
                current_user=current_user,
                cash_book_id=cash_book_id, bank_account_id=bank_account_id,
                credit_card_id=credit_card_id,
            )
        except HTTPException:
            # Bir fatura için hedef hesap eksikse atla; toplu işlemi yarıda kesme
            continue
    db.commit()
    return RedirectResponse(url=safe_redirect(redirect_url, "/invoices"), status_code=status.HTTP_302_FOUND)


@router.post("/{invoice_id}/delete", name="invoice_delete")
async def invoice_delete(
    invoice_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.company_id == current_user.company_id).first()
    if inv and inv.deleted_at is None:
        inv.deleted_at = datetime.utcnow()
        inv.deleted_by = current_user.id
        db.commit()
    return RedirectResponse(url="/invoices", status_code=status.HTTP_302_FOUND)


@router.post("/{invoice_id}/undelete", name="invoice_undelete")
async def invoice_undelete(
    invoice_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.company_id == current_user.company_id).first()
    if inv and inv.deleted_at is not None:
        inv.deleted_at = None
        inv.deleted_by = None
        db.commit()
    return RedirectResponse(url="/invoices?archived=1", status_code=status.HTTP_302_FOUND)


@router.post("/bulk-archive", name="invoice_bulk_archive")
async def invoice_bulk_archive(
    ids_json: str = Form(...),
    current_user: User = Depends(require_module("invoices", edit=True)),
    db: Session = Depends(get_db),
):
    if not current_user.has_role_min("mudur"):
        return JSONResponse({"ok": False, "error": "Yetersiz yetki"}, status_code=403)
    try:
        ids = json.loads(ids_json)
        if not isinstance(ids, list):
            raise ValueError
    except Exception:
        return JSONResponse({"ok": False, "error": "Geçersiz veri"}, status_code=400)

    updated = 0
    skipped = 0
    for iid in ids:
        inv = db.query(Invoice).filter(
            Invoice.id == int(iid),
            Invoice.company_id == current_user.company_id,
            Invoice.deleted_at == None,  # noqa: E711
        ).first()
        if not inv:
            continue
        if inv.status != "paid":
            skipped += 1
            continue
        inv.deleted_at = datetime.utcnow()
        inv.deleted_by = current_user.id
        updated += 1
    db.commit()
    msg = None
    if skipped:
        msg = f"{skipped} fatura 'ödendi/tahsil edildi' durumunda olmadığı için arşivlenmedi."
    return JSONResponse({"ok": True, "archived": updated, "skipped": skipped, "msg": msg})


# ============================================================================
# Çok kademeli onay akışı (RBAC v2): temsilci → müdür → GM
# ============================================================================

@router.post("/{invoice_id}/approve-step", name="invoice_approve_step")
async def invoice_approve_step(
    invoice_id: str,
    request: Request,
    note: str = Form(""),
    next_url: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """Bir kademeyi onayla. Limit dahilinde ise zincir biter."""
    from invoice_approval import approve_step
    inv = db.query(Invoice).filter_by(id=invoice_id, company_id=cid).first()
    if not inv:
        raise HTTPException(404, "Fatura bulunamadı.")
    ok, msg = approve_step(db, inv, current_user, note=note.strip())
    if not ok:
        db.rollback()
        raise HTTPException(400, msg)
    db.commit()
    redirect = next_url.strip() if next_url.strip().startswith("/") else f"/invoices/{inv.id}?approved=1"
    return RedirectResponse(url=redirect, status_code=302)


# ---------------------------------------------------------------------------
# Muhasebe "Fatura Kes" — onay zincirini atlayarak direkt kesme yetkisi
# ---------------------------------------------------------------------------

@router.post("/{invoice_id}/muhasebe-cut", name="invoice_muhasebe_cut")
async def invoice_muhasebe_cut(
    invoice_id: str,
    request: Request,
    invoice_no: str = Form(""),
    next_url: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """Muhasebe/admin fatura talebini direkt keser (onay zincirini atlar)."""
    is_accounting = (
        current_user.has_department_key("accounting")
        or current_user.role in ("muhasebe", "muhasebe_muduru")
        or current_user.is_admin
    )
    if not is_accounting:
        raise HTTPException(403, "Bu işlem için muhasebe yetkisi gereklidir.")

    inv = db.query(Invoice).filter_by(id=invoice_id, company_id=cid).first()
    if not inv:
        raise HTTPException(404, "Fatura bulunamadı.")
    if inv.approval_status == "approved":
        raise HTTPException(400, "Fatura zaten kesilmiş.")

    if invoice_no.strip():
        inv.invoice_no = invoice_no.strip()
    inv.approval_status = "approved"

    import json as _json
    try:
        history = _json.loads(inv.approval_history or "[]")
    except Exception:
        history = []
    history.append({
        "action": "muhasebe_cut",
        "user_id": current_user.id,
        "user_name": f"{current_user.name} {current_user.surname or ''}".strip(),
        "user_role": current_user.role,
        "ts": __import__("datetime").datetime.utcnow().isoformat(),
    })
    inv.approval_history = _json.dumps(history, ensure_ascii=False)

    db.commit()
    redirect = next_url.strip() if next_url.strip().startswith("/") else "/invoices?approval=pending"
    return RedirectResponse(url=redirect, status_code=302)


@router.post("/{invoice_id}/reject-step", name="invoice_reject_step")
async def invoice_reject_step(
    invoice_id: str,
    request: Request,
    note: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """Faturayı reddet — zincir biter, muhasebeciye bildirim gider."""
    from invoice_approval import reject_step
    inv = db.query(Invoice).filter_by(id=invoice_id, company_id=cid).first()
    if not inv:
        raise HTTPException(404, "Fatura bulunamadı.")
    ok, msg = reject_step(db, inv, current_user, note=note.strip())
    if not ok:
        db.rollback()
        raise HTTPException(400, msg)
    db.commit()
    return RedirectResponse(url=f"/invoices/{inv.id}?rejected=1", status_code=302)


# ---------------------------------------------------------------------------
# Ortak Havuz (referanssız gelen faturalar)
# ---------------------------------------------------------------------------

@router.get("/pool", response_class=HTMLResponse, name="invoice_pool")
async def invoice_pool(
    request: Request,
    current_user: User = Depends(require_module("invoices")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """Referanssız gelen faturalar — satış ekibi sahiplenip referans atayabilir."""
    invoices = (
        db.query(Invoice)
        .filter(Invoice.company_id == cid, Invoice.in_pool == True,  # noqa: E712
                Invoice.deleted_at == None)  # noqa: E711
        .options(joinedload(Invoice.vendor))
        .order_by(Invoice.invoice_date.desc())
        .all()
    )
    # Satışçıya yalnızca kendi takımının aktif referanslarını göster
    from access_policy import visible_references_query
    refs = (
        visible_references_query(db, current_user)
        .filter(Reference.status == "aktif")
        .order_by(Reference.ref_no)
        .all()
    )
    return templates.TemplateResponse(
        "invoices/pool.html",
        {
            "request": request,
            "current_user": current_user,
            "invoices": invoices,
            "refs": refs,
            "page_title": "Ortak Fatura Havuzu",
        },
    )


@router.post("/{invoice_id}/claim", name="invoice_claim")
async def invoice_claim(
    invoice_id: str,
    ref_id: str = Form(...),
    current_user: User = Depends(require_module("invoices")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """Havuzdaki faturayı sahiplen: referans ata ve kendini onaylayıcı yap."""
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.company_id == cid).first()
    if not inv or not inv.in_pool:
        raise HTTPException(404, "Havuzda fatura bulunamadı.")
    from access_policy import visible_references_query
    ref = visible_references_query(db, current_user).filter(Reference.id == ref_id).first()
    if not ref:
        raise HTTPException(403, "Bu referansa erişim yetkiniz yok.")

    inv.ref_id = ref_id
    inv.in_pool = False
    inv.current_approver_id = current_user.id
    inv.approval_status = "onay_bekliyor"
    db.commit()
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=302)


# ---------------------------------------------------------------------------
# Fatura Bölme
# ---------------------------------------------------------------------------

@router.get("/api/active-refs", name="invoices_api_active_refs")
async def api_active_refs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """Split modal için aktif referansları döner."""
    refs = (
        db.query(Reference)
        .filter(Reference.company_id == cid, Reference.status == "aktif")
        .order_by(Reference.ref_no)
        .options(joinedload(Reference.customer))
        .all()
    )
    return JSONResponse([{
        "id": r.id,
        "ref_no": r.ref_no,
        "title": r.title,
        "customer_name": r.customer.name if r.customer else "",
    } for r in refs])


@router.post("/{invoice_id}/split", name="invoice_split")
async def invoice_split(
    invoice_id: str,
    allocations_json: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """Faturayı referanslara böl — parent işaretlenir, her allocation için child oluşturulur."""
    inv = db.query(Invoice).filter_by(id=invoice_id, company_id=cid).first()
    if not inv:
        raise HTTPException(404, "Fatura bulunamadı.")
    if inv.is_split_parent:
        raise HTTPException(400, "Bu fatura zaten bölünmüş.")

    try:
        allocs = json.loads(allocations_json)
    except Exception:
        raise HTTPException(400, "Geçersiz bölme verisi.")

    target = round(inv.total_with_vat, 2)
    total_alloc = round(sum(float(a.get("amount_incl", 0)) for a in allocs), 2)
    if abs(target - total_alloc) > 0.02:
        raise HTTPException(400, f"Toplam uyuşmuyor: fatura {target:.2f}, atanan {total_alloc:.2f}.")

    for i, alloc in enumerate(allocs, 1):
        rid_str = str(alloc.get("request_id", "")).strip()
        if not rid_str or rid_str == "__vendor_fund__":
            continue
        try:
            ref_id = int(rid_str)
        except ValueError:
            continue

        amount_incl = float(alloc.get("amount_incl", 0))
        vat_pct = float(alloc.get("vat_rate", inv.vat_rate * 100))
        vat_dec = vat_pct / 100.0
        amount_net = round(amount_incl / (1 + vat_dec), 2) if vat_dec else amount_incl

        child = Invoice(
            company_id=inv.company_id,
            ref_id=ref_id,
            vendor_id=inv.vendor_id,
            customer_id=inv.customer_id,
            invoice_type=inv.invoice_type,
            invoice_no=f"{inv.invoice_no or inv.id}-{i}",
            invoice_date=inv.invoice_date,
            amount=amount_net,
            vat_rate=vat_dec,
            total_amount=round(amount_incl, 2),
            payment_status="unpaid",
            currency=inv.currency,
            status=inv.status,
            payment_method=inv.payment_method,
            due_date=inv.due_date,
            notes=inv.notes,
            created_by=current_user.id,
            split_parent_id=inv.id,
        )
        db.add(child)

    inv.is_split_parent = True
    db.commit()
    return RedirectResponse(url=f"/invoices/{inv.id}?split=1", status_code=302)
