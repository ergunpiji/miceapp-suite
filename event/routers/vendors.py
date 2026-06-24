"""
Satın Alma — Finansal Tedarikçi Yönetimi (Vendor)
Erişim: admin, muhasebe_muduru, muhasebe  (liste/düzenle)
Görüntüleme: mudur (GM), muhasebe ekibi
"""
import os
from datetime import date, datetime, timedelta
from collections import defaultdict

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import Session, sessionmaker

from auth import get_current_user
from database import get_db
from models import Vendor, Invoice, InvoiceLog, VendorPrepayment, PREPAYMENT_STATUSES, SUPPLIER_TYPES, User, _uuid, _now
from templates_config import templates

router = APIRouter(prefix="/vendors", tags=["vendors"])

# ── Finans agent DB (kredi kartı ekstrelerini okumak için) ────────────────────
_finans_raw_url = os.environ.get(
    "FINANS_AGENT_DB",
    os.environ.get("DATABASE_URL", "sqlite:///./agents/finans/finans_agent.db"),
)
if _finans_raw_url.startswith("postgres://"):
    _finans_raw_url = _finans_raw_url.replace("postgres://", "postgresql://", 1)
_finans_is_sqlite = _finans_raw_url.startswith("sqlite")
_finans_kwargs: dict = {"echo": False}
if _finans_is_sqlite:
    _finans_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _finans_kwargs["pool_pre_ping"] = True
    _finans_kwargs["pool_recycle"]  = 300
    _finans_kwargs["pool_size"]     = 3
    _finans_kwargs["max_overflow"]  = 5
_finans_engine = create_engine(_finans_raw_url, **_finans_kwargs)
_FinansSession = sessionmaker(autocommit=False, autoflush=False, bind=_finans_engine)


def _get_cc_statements(today_str: str, end_str: str) -> list[dict]:
    """Ödenmemiş/kısmi kredi kartı ekstrelerini finans DB'den çek."""
    try:
        with _FinansSession() as sess:
            rows = sess.execute(
                text("""
                    SELECT s.id, s.due_date, s.total_amount, s.paid_amount, s.status,
                           c.name AS card_name, c.bank, c.last_four
                    FROM credit_card_statements s
                    JOIN credit_cards c ON c.id = s.card_id
                    WHERE s.status != 'odendi'
                      AND s.due_date >= :today
                      AND s.due_date <= :end
                    ORDER BY s.due_date
                """),
                {"today": today_str, "end": end_str},
            ).fetchall()
            return [dict(r._mapping) for r in rows]
    except Exception:
        return []

FINANCE_ROLES = {"admin", "muhasebe_muduru", "muhasebe"}
VIEW_ROLES    = {"admin", "muhasebe_muduru", "muhasebe", "mudur"}  # mudur = GM here


def _require_finance(current_user: User):
    if current_user.role not in FINANCE_ROLES and not current_user.is_gm:
        raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok.")


def _require_view(current_user: User):
    if current_user.role not in VIEW_ROLES and not current_user.is_gm:
        raise HTTPException(status_code=403, detail="Bu sayfayı görüntüleme yetkiniz yok.")


# ---------------------------------------------------------------------------
# GET /vendors/autocomplete  — JSON autocomplete (fatura formunda kullanılır)
# ---------------------------------------------------------------------------

@router.get("/autocomplete", name="vendors_autocomplete")
async def vendors_autocomplete(
    q: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in {*FINANCE_ROLES, "mudur", "satinalma", "yonetici", "asistan"} and not current_user.is_gm:
        return JSONResponse([])
    term = f"%{q.strip()}%"
    _vq = db.query(Vendor).filter(Vendor.active == True, Vendor.name.ilike(term))
    if current_user.company_id:
        _vq = _vq.filter(Vendor.company_id == current_user.company_id)
    vendors = _vq.order_by(Vendor.name).limit(20).all()
    return JSONResponse([
        {
            "id":           v.id,
            "name":         v.name,
            "payment_term": v.payment_term,
            "email":        v.email,
            "phone":        v.phone,
        }
        for v in vendors
    ])


# ---------------------------------------------------------------------------
# POST /vendors/quick-create  — RFQ modalından hızlı tedarikçi oluştur (JSON)
# ---------------------------------------------------------------------------

@router.post("/quick-create", name="vendors_quick_create")
async def vendors_quick_create(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """RFQ modalı için hızlı tedarikçi oluşturma — JSON döner."""
    data = await request.json()
    name    = (data.get("name") or "").strip()
    email   = (data.get("email") or "").strip()
    phone   = (data.get("phone") or "").strip()
    contact = (data.get("contact_name") or "").strip()
    contact_title = (data.get("contact_title") or "").strip()

    if not name:
        return JSONResponse({"error": "Tedarikçi adı zorunludur."}, status_code=400)

    contacts_json = "[]"
    if contact or email or phone:
        import json as _json
        contacts_json = _json.dumps([{
            "name": contact or name, "title": contact_title,
            "email": email, "phone": phone,
        }], ensure_ascii=False)

    vendor = Vendor(
        id            = _uuid(),
        name          = name,
        email         = email,
        phone         = phone,
        contacts_json = contacts_json,
        active        = True,
        company_id    = current_user.company_id,
        created_by    = current_user.id,
        created_at    = _now(),
        updated_at    = _now(),
    )
    db.add(vendor)
    db.commit()
    return JSONResponse({
        "id":    vendor.id,
        "name":  vendor.name,
        "email": vendor.email,
        "phone": vendor.phone,
    })


# ---------------------------------------------------------------------------
# GET /vendors  — Liste
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="vendors_list")
async def vendors_list(
    request: Request,
    q: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_view(current_user)

    query = db.query(Vendor).filter(Vendor.active == True)
    # Tenant izolasyonu — sadece kendi şirketinin tedarikçileri
    if current_user.company_id:
        query = query.filter(Vendor.company_id == current_user.company_id)
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(Vendor.name.ilike(term))
    vendors = query.order_by(Vendor.name).all()

    # Her tedarikçi için ödenmemiş toplam hesapla
    unpaid_map = {}
    overdue_map = {}
    today_str = date.today().isoformat()
    for v in vendors:
        unpaid = (
            db.query(func.sum(Invoice.total_amount))
            .filter(Invoice.vendor_id == v.id, Invoice.payment_status == "unpaid",
                    Invoice.status == "approved")
            .scalar() or 0.0
        )
        overdue = (
            db.query(func.sum(Invoice.total_amount))
            .filter(Invoice.vendor_id == v.id, Invoice.payment_status == "unpaid",
                    Invoice.status == "approved",
                    Invoice.due_date < today_str, Invoice.due_date != None)
            .scalar() or 0.0
        )
        unpaid_map[v.id]  = round(unpaid,  2)
        overdue_map[v.id] = round(overdue, 2)

    # Vendor fund pool bakiyeleri — tedarikçi adına göre eşleşen havuzları bul
    from models import Request as ReqModel
    from utils.funds import get_fund_balance
    pools = (db.query(ReqModel)
               .filter(ReqModel.is_fund_pool == True,                 # noqa: E712
                       ReqModel.fund_pool_type == "vendor")
               .order_by(ReqModel.check_in.desc())
               .all())
    # vendor_name (case-insensitive) → en güncel havuz + bakiye
    fund_map: dict = {}
    for p in pools:
        key = (p.fund_vendor_name or "").strip().lower()
        if not key or key in fund_map:
            continue   # ilk gelen (en güncel yıl) tutulur
        bal = get_fund_balance(p, db)
        fund_map[key] = {
            "pool_id":   p.id,
            "request_no": p.request_no,
            "year":      p.check_in[:4] if p.check_in else "",
            "currency":  bal["currency"],
            "remaining": bal["remaining"],
            "initial":   bal["initial"],
        }

    return templates.TemplateResponse("vendors/list.html", {
        "request":      request,
        "current_user": current_user,
        "page_title":   "Finansal Tedarikçiler",
        "vendors":      vendors,
        "q":            q,
        "unpaid_map":   unpaid_map,
        "overdue_map":  overdue_map,
        "fund_map":     fund_map,
        "can_edit":     current_user.role in FINANCE_ROLES,
    })


# ---------------------------------------------------------------------------
# GET /vendors/new  — Yeni tedarikçi formu
# ---------------------------------------------------------------------------

@router.get("/new", response_class=HTMLResponse, name="vendors_new")
async def vendors_new(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _require_finance(current_user)
    return templates.TemplateResponse("vendors/form.html", {
        "request":        request,
        "current_user":   current_user,
        "page_title":     "Yeni Tedarikçi",
        "vendor":         None,
        "edit_mode":      False,
        "supplier_types": SUPPLIER_TYPES,
    })


# ---------------------------------------------------------------------------
# POST /vendors/new
# ---------------------------------------------------------------------------

@router.post("/new", name="vendors_create")
async def vendors_create(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    name:          str = Form(...),
    supplier_type: str = Form("diger"),
    tax_number:    str = Form(""),
    tax_office:    str = Form(""),
    address:       str = Form(""),
    email:         str = Form(""),
    phone:         str = Form(""),
    payment_term:  str = Form("30"),
    notes:         str = Form(""),
    code:          str = Form(""),
):
    _require_finance(current_user)
    from database import generate_vendor_code
    _code = (code or "").strip().upper()[:12]
    if not _code:
        _code = generate_vendor_code(db, name, current_user.company_id)
    vendor = Vendor(
        id            = _uuid(),
        name          = name.strip(),
        code          = _code,
        supplier_type = supplier_type or "diger",
        tax_no        = tax_number.strip(),
        tax_office    = tax_office.strip(),
        address       = address.strip(),
        email         = email.strip(),
        phone         = phone.strip(),
        payment_term  = int(payment_term or 30),
        notes         = notes.strip(),
        active        = True,
        created_by    = current_user.id,
        created_at    = _now(),
        updated_at    = _now(),
    )
    db.add(vendor)
    db.commit()
    return RedirectResponse(url=f"/vendors/{vendor.id}", status_code=303)


# ---------------------------------------------------------------------------
# GET /vendors/{id}  — Tedarikçi kartı
# ---------------------------------------------------------------------------

@router.get("/{vendor_id}", response_class=HTMLResponse, name="vendors_card")
async def vendors_card(
    vendor_id: str,
    request: Request,
    period: str = "all",   # all | 30 | 90 | 180 | 365
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_view(current_user)
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Tedarikçi bulunamadı.")

    inv_q = db.query(Invoice).filter(Invoice.vendor_id == vendor_id)

    # Dönem filtresi
    if period != "all":
        days = int(period)
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        inv_q = inv_q.filter(Invoice.invoice_date >= cutoff)

    invoices = inv_q.order_by(Invoice.invoice_date.desc()).all()

    # Özet hesaplamalar
    today_str = date.today().isoformat()

    def _remaining(inv) -> float:
        return round(max(0.0, (inv.total_amount or 0) - (inv.paid_amount or 0)), 2)

    approved = [inv for inv in invoices if inv.status == "approved"]
    total_amount   = sum(inv.total_amount or 0 for inv in approved)
    # ÖDENEN: gerçek ödenen tutar (partial için paid_amount, paid için total_amount)
    paid_amount    = sum(inv.paid_amount or 0 for inv in approved
                         if inv.payment_status in ("paid", "partial"))
    # BEKLEYEN: vadesi henüz geçmemiş ya da vade yok → kalan bakiye
    unpaid_amount  = sum(_remaining(inv) for inv in approved
                         if inv.payment_status in ("unpaid", "partial")
                         and (not inv.due_date or inv.due_date >= today_str))
    # GECİKMİŞ: vadesi geçmiş, henüz tam ödenmemiş → kalan bakiye
    overdue_amount = sum(_remaining(inv) for inv in approved
                         if inv.payment_status in ("unpaid", "partial")
                         and inv.due_date and inv.due_date < today_str)

    # Ön ödemeler (açık + kısmen uygulanmış)
    prepayments = (
        db.query(VendorPrepayment)
        .filter(VendorPrepayment.vendor_id == vendor_id)
        .order_by(VendorPrepayment.payment_date.desc())
        .all()
    )
    open_prepayment_total = sum(p.remaining for p in prepayments if p.status in ("open", "partial"))

    # Referans listesi — ön ödeme modalı için
    from models import Request as ReqModel
    vendor_requests = (
        db.query(ReqModel)
        .join(Invoice, Invoice.request_id == ReqModel.id)
        .filter(Invoice.vendor_id == vendor_id)
        .distinct()
        .order_by(ReqModel.created_at.desc())
        .all()
    )

    return templates.TemplateResponse("vendors/card.html", {
        "request":               request,
        "current_user":          current_user,
        "page_title":            vendor.name,
        "vendor":                vendor,
        "invoices":              invoices,
        "prepayments":           prepayments,
        "open_prepayment_total": round(open_prepayment_total, 2),
        "vendor_requests":       vendor_requests,
        "period":                period,
        "total_amount":          round(total_amount,   2),
        "paid_amount":           round(paid_amount,    2),
        "unpaid_amount":         round(unpaid_amount,  2),
        "overdue_amount":        round(overdue_amount, 2),
        "today_str":             today_str,
        "can_edit":                current_user.role in FINANCE_ROLES,
        # Ön ödeme TALEP etme yetkisi — /prepayment-requests/new ile aynı rol seti
        "can_request_prepayment":  current_user.role in {"admin", "mudur", "yonetici", "asistan"} or current_user.is_gm,
        "prepayment_statuses":     PREPAYMENT_STATUSES,
    })


# ---------------------------------------------------------------------------
# GET /vendors/{id}/edit
# ---------------------------------------------------------------------------

@router.get("/{vendor_id}/edit", response_class=HTMLResponse, name="vendors_edit")
async def vendors_edit(
    vendor_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(current_user)
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Tedarikçi bulunamadı.")
    return templates.TemplateResponse("vendors/form.html", {
        "request":        request,
        "current_user":   current_user,
        "page_title":     f"Düzenle — {vendor.name}",
        "vendor":         vendor,
        "edit_mode":      True,
        "supplier_types": SUPPLIER_TYPES,
    })


# ---------------------------------------------------------------------------
# POST /vendors/{id}/edit
# ---------------------------------------------------------------------------

@router.post("/{vendor_id}/edit", name="vendors_update")
async def vendors_update(
    vendor_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    name:          str = Form(...),
    supplier_type: str = Form("diger"),
    tax_number:    str = Form(""),
    tax_office:    str = Form(""),
    address:       str = Form(""),
    email:         str = Form(""),
    phone:         str = Form(""),
    payment_term:  str = Form("30"),
    notes:         str = Form(""),
    code:          str = Form(""),
):
    _require_finance(current_user)
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Tedarikçi bulunamadı.")
    _code = (code or "").strip().upper()[:12]
    if not _code:
        from database import generate_vendor_code
        _code = vendor.code or generate_vendor_code(db, name, vendor.company_id, exclude_id=vendor.id)
    vendor.code          = _code
    vendor.name          = name.strip()
    vendor.supplier_type = supplier_type or "diger"
    vendor.tax_no        = tax_number.strip()
    vendor.tax_office    = tax_office.strip()
    vendor.address       = address.strip()
    vendor.email         = email.strip()
    vendor.phone         = phone.strip()
    vendor.payment_term  = int(payment_term or 30)
    vendor.notes         = notes.strip()
    vendor.updated_at    = _now()
    db.commit()
    return RedirectResponse(url=f"/vendors/{vendor.id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /vendors/{id}/delete
# ---------------------------------------------------------------------------

@router.post("/{vendor_id}/delete", name="vendors_delete")
async def vendors_delete(
    vendor_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(current_user)
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Tedarikçi bulunamadı.")
    # Soft delete
    vendor.active  = False
    vendor.updated_at = _now()
    db.commit()
    return RedirectResponse(url="/vendors", status_code=303)


# ---------------------------------------------------------------------------
# POST /vendors/{id}/mark-paid  — Fatura ödemesini işaretle
# ---------------------------------------------------------------------------

@router.post("/{vendor_id}/invoices/{invoice_id}/mark-paid", name="vendors_mark_paid")
async def vendors_mark_paid(
    vendor_id:      str,
    invoice_id:     str,
    current_user:   User = Depends(get_current_user),
    db:             Session = Depends(get_db),
    payment_status: str   = Form("paid"),   # paid | partial
    paid_at:        str   = Form(""),
    paid_amount:    str   = Form(""),       # kısmi ödeme tutarı
    payment_method: str   = Form("banka"),  # banka | kredi_karti | cek
    cc_due_date:    str   = Form(""),       # kredi kartı son ödeme tarihi
):
    _require_finance(current_user)
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.vendor_id == vendor_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Fatura bulunamadı.")

    inv.paid_at    = paid_at or date.today().isoformat()
    inv.updated_at = _now()

    if payment_status == "partial" and paid_amount:
        try:
            amt = round(float(paid_amount), 2)
            inv.paid_amount = round((inv.paid_amount or 0.0) + amt, 2)

            # Kredi kartı kısmını ayrı izle (nakit akışında cc_due_date'e ayrı giriş)
            if payment_method == "kredi_karti":
                inv.cc_pending_amount = round((inv.cc_pending_amount or 0.0) + amt, 2)
                if cc_due_date:
                    inv.cc_due_date = cc_due_date   # en son CC vadesini güncelle

            # Tam ödendiyse otomatik "paid" yap
            if inv.paid_amount >= (inv.total_amount or 0.0):
                inv.payment_status = "paid"
                inv.payment_method = payment_method
            else:
                inv.payment_status = "partial"
                # Birden fazla yöntem olabilir; son yöntemi kaydet
                inv.payment_method = payment_method
        except (ValueError, TypeError):
            inv.payment_status = "partial"
    else:
        # Tam ödeme
        inv.payment_status    = "paid"
        inv.payment_method    = payment_method
        inv.paid_amount       = inv.total_amount or 0.0
        inv.cc_pending_amount = 0.0   # tam ödeme = kart borcu da kapandı
        if payment_method == "kredi_karti" and cc_due_date:
            inv.cc_due_date   = cc_due_date
        else:
            inv.cc_due_date   = None

    # Ödeme logu
    _log_amt = round(float(paid_amount), 2) if (payment_status == "partial" and paid_amount) else (inv.total_amount or 0.0)
    _log_cc  = cc_due_date if payment_method == "kredi_karti" and cc_due_date else None
    db.add(InvoiceLog(
        id=_uuid(), invoice_id=invoice_id, action="payment",
        actor_id=current_user.id, amount=_log_amt,
        payment_method=payment_method, cc_due_date=_log_cc,
        note=inv.paid_at or "",
    ))
    db.commit()
    return RedirectResponse(url=f"/vendors/{vendor_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /vendors/{id}/prepayments/add  — Ön ödeme ekle
# ---------------------------------------------------------------------------

@router.post("/{vendor_id}/prepayments/add", name="vendors_prepayment_add")
async def vendors_prepayment_add(
    vendor_id:      str,
    current_user:   User = Depends(get_current_user),
    db:             Session = Depends(get_db),
    amount:         float = Form(...),
    payment_date:   str   = Form(...),
    payment_method: str   = Form("banka"),
    request_id:     str   = Form(""),
    notes:          str   = Form(""),
):
    _require_finance(current_user)
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404)

    pp = VendorPrepayment(
        id             = _uuid(),
        vendor_id      = vendor_id,
        request_id     = request_id.strip() or None,
        amount         = round(float(amount), 2),
        payment_date   = payment_date,
        payment_method = payment_method,
        notes          = notes.strip(),
        status         = "open",
        created_by     = current_user.id,
        created_at     = _now(),
        updated_at     = _now(),
    )
    db.add(pp)
    db.commit()
    return RedirectResponse(url=f"/vendors/{vendor_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /vendors/{id}/prepayments/{pp_id}/cancel  — Ön ödeme iptal
# ---------------------------------------------------------------------------

@router.post("/{vendor_id}/prepayments/{pp_id}/cancel", name="vendors_prepayment_cancel")
async def vendors_prepayment_cancel(
    vendor_id: str,
    pp_id:     str,
    current_user: User = Depends(get_current_user),
    db:        Session = Depends(get_db),
):
    _require_finance(current_user)
    pp = db.query(VendorPrepayment).filter(
        VendorPrepayment.id == pp_id,
        VendorPrepayment.vendor_id == vendor_id,
    ).first()
    if pp and pp.status in ("open", "partial"):
        pp.status     = "cancelled"
        pp.updated_at = _now()
        db.commit()
    return RedirectResponse(url=f"/vendors/{vendor_id}", status_code=303)


# ---------------------------------------------------------------------------
# GET /cash-flow  — Nakit Akışı tahmini
# ---------------------------------------------------------------------------
def _iso(x) -> str:
    """date/datetime/str/None → 'YYYY-MM-DD' string (string karşılaştırmaları için).
    Paylaşımlı invoices tablosunda due_date Postgres'te DATE; event modeli String(10)
    deklare etse de psycopg2 date objesi döndürebiliyor → 'str <= date' TypeError'ını
    önlemek için normalize edilir."""
    if not x:
        return ""
    if hasattr(x, "isoformat"):
        return x.isoformat()[:10]
    return str(x)[:10]


def _parse_payment_term_days(s, default: int = 30) -> int:
    """Customer.payment_term serbest metin → gün sayısı.
    'peşin'→0, '30 gün'→30, parse edilemez/boş → default (30)."""
    import re
    if not s:
        return default
    t = str(s).strip().lower()
    if "peşin" in t or "pesin" in t or "peş" in t:
        return 0
    m = re.search(r"\d+", t)
    return int(m.group()) if m else default


@router.get("/cash-flow/view", response_class=HTMLResponse, name="cash_flow")
async def cash_flow(
    request: Request,
    weeks: int = 8,
    forecast: int = 1,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Nakit Akışı sadece finans tarafına: admin / GM / muhasebe / muhasebe_muduru
    _require_finance(current_user)

    today = date.today()
    end_date = today + timedelta(weeks=weeks)
    end_str  = end_date.isoformat()
    today_str = today.isoformat()

    # ── Nakit akışı kalemleri oluştur ─────────────────────────────────────────
    # Her Invoice birden fazla kalem üretebilir (ör. kısmi CC + kalan bakiye).
    # Kalem formatı: {invoice, amount, eff_date, is_cc, cc_label}
    def _build_outgoing_items(invoices: list) -> list:
        items = []
        for inv in invoices:
            total  = inv.total_amount  or 0.0
            paid   = inv.paid_amount   or 0.0
            cc_pnd = inv.cc_pending_amount or 0.0
            remaining_cash = round(max(0.0, total - paid), 2)   # vadede ödenecek
            due = _iso(inv.due_date)

            # 1) Kalan bakiye (banka/çek ile ödenecek) → orijinal vade tarihinde
            if remaining_cash > 0 and due:
                items.append({
                    "invoice":  inv,
                    "amount":   remaining_cash,
                    "eff_date": due,
                    "is_cc":    False,
                    "cc_label": None,
                })

            # 2) Kredi kartı ile taahhüt edilen tutar → cc_due_date'te ayrı giriş
            _cc_due = _iso(inv.cc_due_date)
            if cc_pnd > 0 and _cc_due:
                items.append({
                    "invoice":  inv,
                    "amount":   round(cc_pnd, 2),
                    "eff_date": _cc_due,
                    "is_cc":    True,
                    "cc_label": _cc_due,
                })

        return items

    # Ödenmemiş/kısmi gider faturaları — approved (kesilen/iade_kesilen hariç: onlar gelir)
    _expense_types_excl = ["kesilen", "iade_kesilen"]
    invoices_raw = (
        db.query(Invoice)
        .filter(
            Invoice.payment_status.in_(["unpaid", "partial"]),
            Invoice.status == "approved",
            Invoice.due_date != None,
            Invoice.invoice_type.notin_(_expense_types_excl),
        )
        .order_by(Invoice.due_date)
        .all()
    )
    # Tamamen ödendi ama CC borcu henüz bankadan çıkmadı
    cc_fully_paid = (
        db.query(Invoice)
        .filter(
            Invoice.payment_status == "paid",
            Invoice.cc_pending_amount > 0,
            Invoice.cc_due_date != None,
            Invoice.cc_due_date >= today_str,
            Invoice.cc_due_date <= end_str,
            Invoice.invoice_type.notin_(_expense_types_excl),
        )
        .all()
    )

    all_outgoing_items = _build_outgoing_items(invoices_raw) + _build_outgoing_items(cc_fully_paid)
    # Dönem aralığına filtrele
    all_outgoing_items = [
        it for it in all_outgoing_items
        if today_str <= _iso(it["eff_date"]) <= end_str
    ]

    # Ödenmemiş müşteri alacakları (gelir) — approved, kesilen tip
    incoming = (
        db.query(Invoice)
        .filter(
            Invoice.payment_status.in_(["unpaid", "partial"]),
            Invoice.status == "approved",
            Invoice.invoice_type == "kesilen",
            Invoice.due_date != None,
            Invoice.due_date >= today_str,
            Invoice.due_date <= end_str,
        )
        .order_by(Invoice.due_date)
        .all()
    )

    # Kredi kartı ekstresi ödemeleri (finans agent DB'den)
    cc_statements = _get_cc_statements(today_str, end_str)
    # Kalem formatına dönüştür (is_cc_stmt=True ile ayırt edelim)
    cc_stmt_items = [
        {
            "invoice":    None,
            "amount":     round(max(0.0, (s["total_amount"] or 0) - (s["paid_amount"] or 0)), 2),
            "eff_date":   str(s["due_date"]),
            "is_cc":      True,
            "is_cc_stmt": True,
            "cc_label":   str(s["due_date"]),
            "card_name":  s["card_name"],
            "card_bank":  s["bank"] or "",
            "card_last4": s["last_four"] or "",
        }
        for s in cc_statements
        if round(max(0.0, (s["total_amount"] or 0) - (s["paid_amount"] or 0)), 2) > 0
    ]
    all_outgoing_items = all_outgoing_items + cc_stmt_items

    # ── Tahmini tahsilat (inflow) — onaylı bütçelerden, henüz faturalanmamış ──
    # Sıfır veri girişi: onaylı bütçe satışı − kesilen faturalar = beklenen tahsilat.
    # Tarih = etkinlik bitiş + müşteri vadesi. Faturalar geldikçe otomatik kapanır.
    forecast_items = []
    if forecast:
        from models import Request as ReqModel, Budget, Customer
        from tenant import scope
        fc_reqs = (
            scope(db.query(ReqModel), ReqModel, current_user)
            .filter(
                ReqModel.confirmed_budget_id.isnot(None),
                ReqModel.status.notin_(["cancelled", "closed"]),
            )
            .all()
        )
        for req in fc_reqs:
            # Tek bir bozuk bütçe/kayıt tüm sayfayı 500'e düşürmesin — izole et, atla, logla
            try:
                bgt = db.query(Budget).filter(Budget.id == req.confirmed_budget_id).first()
                if not bgt:
                    continue
                expected = bgt.grand_sale or 0.0          # KDV dahil satış toplamı
                if expected <= 0:
                    continue
                invoiced = sum(
                    (inv.total_amount or 0.0)
                    for inv in db.query(Invoice).filter(
                        Invoice.request_id == req.id,
                        Invoice.invoice_type == "kesilen",
                    ).all()
                )
                draft = round(expected - invoiced, 2)     # faturalanmamış beklenen tahsilat
                if draft <= 0:
                    continue
                base = req.check_out or req.check_in
                if not base:
                    continue
                cust = (
                    db.query(Customer).filter(Customer.id == req.customer_id).first()
                    if req.customer_id else None
                )
                term = _parse_payment_term_days(cust.payment_term if cust else None)
                try:
                    eff = (date.fromisoformat(base) + timedelta(days=term)).isoformat()
                except Exception:
                    continue
                if not (today_str <= eff <= end_str):
                    continue
                forecast_items.append({
                    "request":       req,
                    "amount":        draft,
                    "eff_date":      eff,
                    "customer_name": (cust.name if cust else (req.client_name or "—")),
                    "event_name":    req.event_name or "",
                    "request_no":    req.request_no or "",
                })
            except Exception as _e:
                print(f"[cash_flow] inflow tahmini atlandı (req={getattr(req, 'id', '?')}): {_e}", flush=True)
                continue

    # ── Tahmini gider (outflow) — tedarikçi ödeme taahhütlerinden (Faz 2) ──
    # Faz 3: Taahhüdün KALAN'ı (amount − invoiced_amount) = beklenen ödeme; tarih = taahhüdün
    # beklenen ödeme tarihi. Bağlı gelen fatura geldikçe invoiced_amount artar → tahmin küçülür,
    # tam faturalanınca status=closed olur ve düşer. Legacy (link'siz, invoiced_amount=0) taahhütler
    # için (request,vendor) bazlı orantısal heuristik fallback korunur.
    forecast_out_items = []
    if forecast:
        from models import SupplierCommitment, Request as _Req
        from collections import defaultdict as _dd
        commits = (
            scope(db.query(SupplierCommitment), SupplierCommitment, current_user)
            .filter(SupplierCommitment.status.in_(["open", "partial"]))
            .all()
        )
        # Link'li (Faz 3) ve legacy (link'siz) taahhütleri ayır
        _legacy_groups = _dd(list)
        _req_cache = {}

        def _req_no(rid):
            if rid not in _req_cache:
                _r = db.query(_Req).filter(_Req.id == rid).first()
                _req_cache[rid] = (_r.request_no if _r else "")
            return _req_cache[rid]

        # Bir taahhüde bağlı (commitment_id) en az bir gelen fatura var mı? → link'li say
        _linked_ids = {
            row[0] for row in db.query(Invoice.commitment_id)
            .filter(Invoice.commitment_id.isnot(None), Invoice.invoice_type == "gelen",
                    Invoice.status != "cancelled")
            .distinct().all() if row[0]
        }
        for cm in commits:
            try:
                if cm.id in _linked_ids or (cm.invoiced_amount or 0.0) > 0:
                    # Faz 3: gerçek kalan
                    remaining = cm.remaining
                    if remaining <= 0:
                        continue
                    eff = cm.expected_payment_date
                    if not eff or not (today_str <= eff <= end_str):
                        continue
                    forecast_out_items.append({
                        "amount":       remaining,
                        "eff_date":     eff,
                        "vendor_name":  cm.vendor_name or "—",
                        "section":      cm.section,
                        "payment_type": cm.payment_type,
                        "request_no":   _req_no(cm.request_id),
                    })
                else:
                    _legacy_groups[(cm.request_id, cm.vendor_id)].append(cm)
            except Exception as _e:
                print(f"[cash_flow] outflow taahhüt atlandı (cm={getattr(cm, 'id', '?')}): {_e}", flush=True)
                continue

        # Legacy fallback: link'siz taahhütler için (request,vendor) orantısal dağıtım
        for (rid, vid), cms in _legacy_groups.items():
            q = db.query(Invoice).filter(
                Invoice.request_id == rid, Invoice.invoice_type == "gelen",
                Invoice.commitment_id.is_(None), Invoice.status != "cancelled",
            )
            if vid:
                q = q.filter(Invoice.vendor_id == vid)
            invoiced = sum((inv.total_amount or 0.0) for inv in q.all())
            for cm in sorted(cms, key=lambda c: c.expected_payment_date or "9999"):
                amt = cm.amount or 0.0
                alloc = min(amt, invoiced)
                invoiced -= alloc
                remaining = round(amt - alloc, 2)
                if remaining <= 0:
                    continue
                eff = cm.expected_payment_date
                if not eff or not (today_str <= eff <= end_str):
                    continue
                forecast_out_items.append({
                    "amount":       remaining,
                    "eff_date":     eff,
                    "vendor_name":  cm.vendor_name or "—",
                    "section":      cm.section,
                    "payment_type": cm.payment_type,
                    "request_no":   _req_no(rid),
                })

    # Haftalık gruplama
    weeks_data = []
    for w in range(weeks):
        week_start = today + timedelta(weeks=w)
        week_end   = week_start + timedelta(days=6)
        ws_str = week_start.isoformat()
        we_str = week_end.isoformat()

        w_items = [it for it in all_outgoing_items if ws_str <= _iso(it["eff_date"]) <= we_str]
        w_in    = [i  for i  in incoming           if ws_str <= _iso(i.due_date)     <= we_str]
        w_fc    = [f  for f  in forecast_items     if ws_str <= _iso(f["eff_date"])  <= we_str]
        w_fc_out = [f for f in forecast_out_items  if ws_str <= _iso(f["eff_date"])  <= we_str]

        weeks_data.append({
            "label":         f"Hafta {w+1}",
            "start":         week_start.strftime("%d.%m"),
            "end":           week_end.strftime("%d.%m"),
            "outgoing":      w_items,
            "incoming":      w_in,
            "forecast_in":   w_fc,
            "forecast_out":  w_fc_out,
            "total_out":     round(sum(it["amount"] for it in w_items), 2),
            "total_in":      round(sum(max(0.0, (i.total_amount or 0) - (i.paid_amount or 0)) for i in w_in), 2),
            "total_fc_in":   round(sum(f["amount"] for f in w_fc), 2),
            "total_fc_out":  round(sum(f["amount"] for f in w_fc_out), 2),
        })

    # Vadesi geçmiş (overdue)
    overdue = (
        db.query(Invoice)
        .filter(
            Invoice.payment_status.in_(["unpaid", "partial"]),
            Invoice.status == "approved",
            Invoice.due_date != None,
            Invoice.due_date < today_str,
        )
        .order_by(Invoice.due_date)
        .all()
    )

    return templates.TemplateResponse("vendors/cash_flow.html", {
        "request":      request,
        "current_user": current_user,
        "page_title":   "Nakit Akışı",
        "weeks_data":   weeks_data,
        "overdue":      overdue,
        "weeks":        weeks,
        "today_str":    today_str,
        "total_overdue": round(sum(max(0.0, (i.total_amount or 0) - (i.paid_amount or 0)) for i in overdue), 2),
        "show_forecast": bool(forecast),
        "total_forecast": round(sum(f["amount"] for f in forecast_items), 2),
        "total_forecast_out": round(sum(f["amount"] for f in forecast_out_items), 2),
    })
