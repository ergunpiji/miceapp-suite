"""
Satın Alma — Fatura Yönetimi
Erişim: admin, muhasebe_muduru, muhasebe
"""
import json
import logging
import os
import shutil

_log = logging.getLogger("miceapp.invoices")
from datetime import datetime, date as _date, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from storage import save_upload, delete_upload, serve_upload as _serve_upload
from sqlalchemy.orm import Session

from auth import get_current_user, get_company_id
from database import get_db
from models import Budget, Customer, Invoice, InvoiceLog, VendorPrepayment, INVOICE_TYPES, INVOICE_TYPE_LABELS, BELGESIZ_TYPES, Request as ReqModel, UndocumentedEntry, Vendor, User, _uuid, _now
from routers.library import log_activity
from templates_config import templates

router = APIRouter(prefix="/invoices", tags=["invoices"])

FINANCE_ROLES        = {"admin", "muhasebe_muduru", "muhasebe"}
# Fatura talebi oluşturabilecek tüm roller (herkes talep oluşturabilir, muhasebe direkt keser)
INVOICE_REQUEST_ROLES = {"admin", "mudur", "yonetici", "asistan", "satinalma", "muhasebe_muduru", "muhasebe"}
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "uploads", "invoices")
ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _add_log(db: Session, invoice_id: str, action: str, actor_id: str | None,
             amount: float | None = None, payment_method: str | None = None,
             cc_due_date: str | None = None, note: str = "") -> None:
    db.add(InvoiceLog(
        id=_uuid(), invoice_id=invoice_id, action=action,
        actor_id=actor_id, amount=amount, payment_method=payment_method,
        cc_due_date=cc_due_date, note=note or "",
    ))


def _apply_prepayments(db: Session, inv: Invoice) -> None:
    """Fatura onaylandığında aynı tedarikçinin açık ön ödemelerini uygula."""
    if not inv.vendor_id:
        return
    open_pps = (
        db.query(VendorPrepayment)
        .filter(
            VendorPrepayment.vendor_id == inv.vendor_id,
            VendorPrepayment.status.in_(["open", "partial"]),
        )
        .order_by(VendorPrepayment.payment_date)
        .all()
    )
    if not open_pps:
        return

    invoice_remaining = round(max(0.0, (inv.total_amount or 0) - (inv.paid_amount or 0)), 2)
    for pp in open_pps:
        if invoice_remaining <= 0:
            break
        apply = min(pp.remaining, invoice_remaining)
        if apply <= 0:
            continue
        pp.applied_amount = round((pp.applied_amount or 0) + apply, 2)
        pp.updated_at = _now()
        pp.status = "applied" if pp.applied_amount >= pp.amount else "partial"

        inv.paid_amount = round((inv.paid_amount or 0) + apply, 2)
        if inv.paid_amount >= (inv.total_amount or 0):
            inv.payment_status = "paid"
        else:
            inv.payment_status = "partial"

        invoice_remaining = round(invoice_remaining - apply, 2)
        _add_log(db, inv.id, "payment", None,
                 amount=apply, payment_method=pp.payment_method,
                 note=f"Ön ödeme uygulandı ({pp.payment_date})")


def _require_finance(current_user: User):
    if current_user.role not in FINANCE_ROLES and not current_user.is_gm:
        raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok.")


def _is_gm(user: User) -> bool:
    return user.is_gm


def _is_above_in_chain(db: Session, candidate_id: str, subordinate_id: str, max_depth: int = 10) -> bool:
    """candidate_id, subordinate_id'nin hiyerarşik üstünde mi kontrol eder."""
    seen: set = set()
    user = db.query(User).filter(User.id == subordinate_id).first()
    depth = 0
    while user and user.manager_id and depth < max_depth:
        if user.manager_id in seen:
            break
        seen.add(user.manager_id)
        if user.manager_id == candidate_id:
            return True
        user = db.query(User).filter(User.id == user.manager_id).first()
        depth += 1
    return False


def _require_approval_permission(current_user: User, inv, db: Session):
    """
    Onay/red için yetki:
    - admin / muhasebe_muduru → her zaman
    - current_approver_id eşleşiyorsa → onaylayabilir
    - current_approver_id'nin hiyerarşik üstündeyse → onaylayabilir (zinciri atlayarak)
    - current_approver_id yoksa → req sahibi veya mudur/GM
    """
    if current_user.role in ("admin", "muhasebe_muduru") or _is_gm(current_user):
        return
    if inv.current_approver_id:
        if current_user.id == inv.current_approver_id:
            return
        if _is_above_in_chain(db, current_user.id, inv.current_approver_id):
            return
    else:
        # current_approver_id NULL: req sahibine izin ver (eski fatura / backfill bekliyor)
        if inv.request and inv.request.created_by == current_user.id:
            return
        if _is_gm(current_user) or current_user.role == "mudur":
            return
    raise HTTPException(status_code=403, detail="Bu faturayı onaylamak için yetkiniz yok.")


def _can_approve_inv(db: Session, inv, user: User) -> bool:
    """Kullanıcının bu faturayı onaylayıp onaylayamayacağını bool döner."""
    if inv.status not in ("pending", "mudur_approved"):
        return False
    # Oluşturan kişi kendi talebini onaylayamaz
    if user.id == inv.created_by and not _is_gm(user) and user.role not in ("admin", "muhasebe_muduru"):
        return False
    if user.role in ("admin", "muhasebe_muduru") or _is_gm(user):
        return True
    if inv.current_approver_id:
        if user.id == inv.current_approver_id:
            return True
        if _is_above_in_chain(db, user.id, inv.current_approver_id):
            return True
    else:
        if inv.request and inv.request.created_by == user.id:
            return True
        if _is_gm(user) or user.role == "mudur":
            return True
    return False


def _find_next_approver(db: Session, user_id: str):
    """Zincirde bir üst onaylayıcıyı (yöneticiyi) döner."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.manager_id:
        return None
    return db.query(User).filter(User.id == user.manager_id).first()


def _get_invoice_or_404(db: Session, invoice_id: str) -> Invoice:
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Fatura bulunamadı.")
    return inv


def _save_document(file: UploadFile, invoice_id: str) -> tuple[str, str]:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        _log.warning("_save_document: desteklenmeyen uzantı '%s' (dosya: %s)", ext, file.filename)
        raise HTTPException(status_code=400, detail="Desteklenmeyen dosya türü. PDF veya resim yükleyin.")
    data = file.file.read()
    if len(data) > MAX_FILE_SIZE:
        _log.warning("_save_document: dosya çok büyük %d bytes (dosya: %s)", len(data), file.filename)
        raise HTTPException(status_code=400, detail="Dosya boyutu 10 MB'ı aşamaz.")
    dest_filename = f"{invoice_id}{ext}"
    key = save_upload(data, "invoices", dest_filename)
    return key, file.filename or dest_filename


def _compute_totals(lines: list) -> tuple[float, float, float]:
    """lines'dan (amount_excl, vat_amount, total_incl) hesapla."""
    total_excl = sum(float(l.get("amount", 0) or 0) for l in lines)
    total_vat  = sum(float(l.get("vat_amount", 0) or 0) for l in lines)
    return round(total_excl, 2), round(total_vat, 2), round(total_excl + total_vat, 2)


# ---------------------------------------------------------------------------
# GET /invoices/{id}/detail  — Fatura Detay Sayfası
# ---------------------------------------------------------------------------

@router.get("/{invoice_id}/detail", response_class=HTMLResponse, name="invoice_detail")
async def invoice_detail(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fatura detayı — Nurcan'ın doldurduğu formun birebir görünümü (read-only)."""
    from models import INVOICE_LOG_ACTIONS
    inv = _get_invoice_or_404(db, invoice_id)

    req = db.query(ReqModel).filter(ReqModel.id == inv.request_id).first() if inv.request_id else None
    undoc_entries = req.undocumented_entries if req else []

    # Onay/red yetkisi
    can_approve_this = _can_approve_inv(db, inv, current_user)

    logs = []
    try:
        logs = (
            db.query(InvoiceLog)
            .filter(InvoiceLog.invoice_id == invoice_id)
            .order_by(InvoiceLog.created_at)
            .all()
        )
    except Exception:
        pass

    # Referansın tüm faturaları — cari finansal özet için
    req_gelirler, req_giderler = [], []
    req_gelir_total, req_gider_total = 0.0, 0.0
    if req:
        req_all_invoices = (
            db.query(Invoice)
            .filter(Invoice.request_id == req.id)
            .order_by(Invoice.invoice_date)
            .all()
        )
        req_gelirler = [i for i in req_all_invoices if i.invoice_type in ("kesilen", "komisyon")]
        req_giderler = [i for i in req_all_invoices if i.invoice_type in ("gelen",)]
        req_gelir_total = round(sum(i.total_amount or 0 for i in req_gelirler), 2)
        req_gider_total = round(sum(i.total_amount or 0 for i in req_giderler), 2)

    return templates.TemplateResponse("invoices/form.html", {
        "request":          request,
        "current_user":     current_user,
        "page_title":       f"Fatura Talebi — {inv.vendor_name or inv.invoice_no or inv.id[:8]}",
        "invoice":          inv,
        "selected_req":     req,
        "all_requests":     [],
        "undoc_entries":    undoc_entries,
        "invoice_types":    INVOICE_TYPES,
        "edit_mode":        False,
        "view_mode":        True,
        "statement_prefill": None,
        "from_statement":   None,
        "can_approve_this": can_approve_this,
        "logs":             logs,
        "log_actions":      INVOICE_LOG_ACTIONS,
        "req_gelirler":     req_gelirler,
        "req_giderler":     req_giderler,
        "req_gelir_total":  req_gelir_total,
        "req_gider_total":  req_gider_total,
    })


# ---------------------------------------------------------------------------
# GET /invoices  — Genel Fatura Listesi
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="invoices_list")
async def invoices_list(
    request: Request,
    status_filter: str = "all",
    type_filter: str = "all",
    view: str = "",          # my_pending → sadece benim onayımı bekleyenler
    q: str = "",             # serbest metin: fatura no, tedarikçi, referans no
    date_from: str = "",     # YYYY-MM-DD
    date_to: str = "",       # YYYY-MM-DD
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Finans rolleri + PM (kendi referanslarının faturalarını görebilir) + GM/super_admin
    if current_user.role not in {"admin", "super_admin", "genel_mudur", "muhasebe_muduru", "muhasebe", "mudur", "yonetici", "asistan", "satinalma"} and not current_user.is_gm:
        raise HTTPException(status_code=403)

    from database import EVENT_COMPANY_ID
    from sqlalchemy import or_ as _or_cid
    query = db.query(Invoice).outerjoin(Invoice.request).filter(
        _or_cid(Invoice.company_id == EVENT_COMPANY_ID, Invoice.company_id.is_(None))
    )

    # "Onaylarım" görünümü — sadece benim onayımı bekleyen faturalar
    if view == "my_pending":
        query = query.filter(
            Invoice.current_approver_id == current_user.id,
            Invoice.status == "pending",
        )
    else:
        # mudur (Etkinlik Süreç Müdürü) ve GM tüm faturaları görebilir
        # PM sadece kendi referanslarının faturalarını görür
        if current_user.role in ("yonetici", "asistan"):
            from models import Request as ReqModel
            query = query.filter(ReqModel.created_by == current_user.id)

    if status_filter != "all":
        query = query.filter(Invoice.status == status_filter)
    if type_filter != "all":
        query = query.filter(Invoice.invoice_type == type_filter)
    if q.strip():
        from models import Request as ReqModel
        term = f"%{q.strip()}%"
        query = query.filter(
            Invoice.invoice_no.ilike(term) |
            Invoice.vendor_name.ilike(term) |
            ReqModel.request_no.ilike(term) |
            ReqModel.event_name.ilike(term)
        )
    if date_from:
        query = query.filter(Invoice.invoice_date >= date_from)
    if date_to:
        query = query.filter(Invoice.invoice_date <= date_to)

    invoices = query.order_by(Invoice.created_at.desc()).all()

    _count_base = db.query(Invoice).outerjoin(Invoice.request)
    if current_user.role in ("yonetici", "asistan"):
        from models import Request as ReqModel
        _count_base = _count_base.filter(ReqModel.created_by == current_user.id)

    pending_count        = _count_base.filter(Invoice.status == "pending").count()
    mudur_approved_count = _count_base.filter(Invoice.status == "mudur_approved").count()

    can_cut           = current_user.role in ("admin", "muhasebe_muduru", "muhasebe")
    can_approve       = _is_gm(current_user) or current_user.role == "mudur"
    can_mudur_approve = _is_gm(current_user) or current_user.role == "mudur"
    can_gm_approve    = _is_gm(current_user)   # mudur_approved → gm_approved
    from utils.funds import can_split_invoice as _can_split
    can_split         = _can_split(current_user)

    return templates.TemplateResponse("invoices/list.html", {
        "request":              request,
        "current_user":         current_user,
        "page_title":           "Onaylarım" if view == "my_pending" else "Faturalar",
        "invoices":             invoices,
        "status_filter":        status_filter,
        "type_filter":          type_filter,
        "view":                 view,
        "q":                    q,
        "date_from":            date_from,
        "date_to":              date_to,
        "pending_count":        pending_count,
        "mudur_approved_count": mudur_approved_count,
        "invoice_types":        INVOICE_TYPES,
        "INVOICE_TYPE_LABELS":  {t["value"]: t["label"] for t in INVOICE_TYPES},
        "can_cut":              can_cut,
        "can_approve":          can_approve,
        "can_mudur_approve":    can_mudur_approve,
        "can_gm_approve":       can_gm_approve,
        "can_split":            can_split,
    })


# ---------------------------------------------------------------------------
# GET /invoices/new
# ---------------------------------------------------------------------------

@router.get("/new", response_class=HTMLResponse, name="invoices_new_form")
async def invoices_new_form(
    request: Request,
    request_id: str = "",
    statement_id: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # statement_id ile geliyorsa PM/yonetici de fatura talebi oluşturabilir
    # Herkes fatura talebi oluşturabilir; muhasebe/admin aynı form üzerinden direkt de keser
    if current_user.role not in INVOICE_REQUEST_ROLES and not current_user.is_gm:
        raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok.")
    req = None
    if request_id:
        req = db.query(ReqModel).filter(ReqModel.id == request_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="Referans bulunamadı.")
    _req_q = db.query(ReqModel).filter(
        ReqModel.status.notin_(["cancelled", "closing", "closed"])
    )
    if current_user.role in ("yonetici", "asistan"):
        _req_q = _req_q.filter(ReqModel.created_by == current_user.id)
    all_requests = _req_q.order_by(ReqModel.created_at.desc()).all()
    undoc_entries = req.undocumented_entries if req else []

    # Hesap dökümünden ön doldurma
    statement_prefill = None
    if statement_id:
        stmt = db.query(Budget).filter(Budget.id == statement_id, Budget.budget_type == "statement").first()
        if stmt:
            from collections import defaultdict
            ACCOM_SECTIONS = {"accommodation"}

            # Detaylı satırlar (tüm kalemler ayrı)
            invoice_lines = []
            # Gruplu satırlar için toplama
            accom_groups = defaultdict(float)   # vat_rate(int) -> total_amount (TRY)
            other_groups = defaultdict(float)   # vat_rate(int) -> total_amount (TRY)

            for row in stmt.rows:
                if row.get("is_service_fee"):
                    sale = float(row.get("sale_price", 0))
                    cur  = row.get("currency", "TRY") or "TRY"
                    sale_try = stmt.amount_to_try(sale, cur)
                    vat  = int(float(row.get("vat_rate", 20)))
                    if sale_try > 0:
                        invoice_lines.append({
                            "description": row.get("service_name", "Hizmet Bedeli"),
                            "amount":      round(sale_try, 2),
                            "vat_rate":    vat,
                            "vat_amount":  round(sale_try * vat / 100, 2),
                        })
                        other_groups[vat] += sale_try
                else:
                    sale   = float(row.get("sale_price", 0))
                    qty    = float(row.get("qty", 1))
                    nights = float(row.get("nights", 1))
                    cur    = row.get("currency", "TRY") or "TRY"
                    total_try = stmt.amount_to_try(sale * qty * nights, cur)
                    vat    = int(float(row.get("vat_rate", 20)))
                    if total_try > 0:
                        invoice_lines.append({
                            "description": row.get("service_name", row.get("description", "")),
                            "amount":      round(total_try, 2),
                            "vat_rate":    vat,
                            "vat_amount":  round(total_try * vat / 100, 2),
                        })
                        section = row.get("section", "")
                        if section in ACCOM_SECTIONS:
                            accom_groups[vat] += total_try
                        else:
                            other_groups[vat] += total_try

            # KDV gruplu satırlar oluştur
            grouped_lines = []
            for vat, amount in sorted(accom_groups.items()):
                amount = round(amount, 2)
                grouped_lines.append({
                    "description": "Konaklama Bedeli",
                    "amount":      amount,
                    "vat_rate":    vat,
                    "vat_amount":  round(amount * vat / 100, 2),
                })
            for vat, amount in sorted(other_groups.items()):
                amount = round(amount, 2)
                grouped_lines.append({
                    "description": f"Organizasyon Hizmet Bedeli (%{vat} KDV)",
                    "amount":      amount,
                    "vat_rate":    vat,
                    "vat_amount":  round(amount * vat / 100, 2),
                })

            customer_name = ""
            customer_payment_term = ""
            if req and req.customer_id:
                from models import Customer
                cust = db.query(Customer).filter(Customer.id == req.customer_id).first()
                if cust:
                    customer_name = cust.name
                    customer_payment_term = str(cust.payment_term or "")
            if not customer_name and req:
                customer_name = req.client_name or ""

            statement_prefill = {
                "vendor_name":          customer_name,
                "invoice_type":         "kesilen",
                "description":          f"Hesap Dökümü — {stmt.venue_name} / {req.request_no if req else ''}",
                "lines_json":           json.dumps(invoice_lines, ensure_ascii=False),
                "grouped_lines_json":   json.dumps(grouped_lines, ensure_ascii=False),
                "customer_payment_term": customer_payment_term,
            }

    page_title = "Fatura Talebi Oluştur" if statement_prefill else "Yeni Fatura"

    # Muhasebe dışındakiler sadece kesilen + komisyon talebi oluşturabilir
    _talep_types = {"kesilen", "komisyon"}
    if current_user.role in FINANCE_ROLES:
        _allowed_types = INVOICE_TYPES
    else:
        _allowed_types = [t for t in INVOICE_TYPES if t["value"] in _talep_types]

    return templates.TemplateResponse("invoices/form.html", {
        "request":           request,
        "current_user":      current_user,
        "page_title":        page_title,
        "invoice":           None,
        "selected_req":      req,
        "all_requests":      all_requests,
        "undoc_entries":     undoc_entries,
        "invoice_types":     _allowed_types,
        "edit_mode":         False,
        "statement_prefill": statement_prefill,
        "from_statement":    statement_id,
    })


# ---------------------------------------------------------------------------
# POST /invoices/new
# ---------------------------------------------------------------------------

@router.post("/new", name="invoices_create")
async def invoices_create(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    req_id:              str = Form(""),
    invoice_type:        str = Form(...),
    invoice_no:          str = Form(""),
    invoice_date:        str = Form(""),
    due_date:            str = Form(""),
    vendor_id:           str = Form(""),
    vendor_name:         str = Form(""),
    define_vendor:       str = Form("no"),   # "yes" → yeni Vendor oluştur
    vendor_payment_term: str = Form("60"),   # gün
    customer_id:         str = Form(""),     # kesilen fatura → müşteri FK
    define_customer:     str = Form("no"),   # "yes" → yeni Customer oluştur
    description:         str = Form(""),
    lines_json:          str = Form("[]"),
    belgesiz_amount:     str = Form(""),
    belgesiz_description:str = Form(""),
    belgesiz_date:       str = Form(""),
    from_statement:      str = Form(""),   # statement ID — PM'den gelenler
    document:            UploadFile = File(None),
):
    _log.info(
        "invoices_create: user=%s role=%s type=%s from_statement=%s doc=%s",
        current_user.id, current_user.role, invoice_type,
        bool(from_statement), document.filename if document else None,
    )
    # Herkes fatura talebi oluşturabilir
    if current_user.role not in INVOICE_REQUEST_ROLES and not current_user.is_gm:
        raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok.")
    # Muhasebe dışındakiler yalnızca kesilen + komisyon talebi oluşturabilir
    if current_user.role not in FINANCE_ROLES and invoice_type not in {"kesilen", "komisyon"}:
        raise HTTPException(status_code=403, detail="Gelen ve iade fatura kaydı yalnızca muhasebe tarafından yapılabilir.")
    req = None
    if req_id:
        req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="Referans bulunamadı.")

    # ── Belgesiz Gelir / Gider → UndocumentedEntry kaydet ──
    if invoice_type in BELGESIZ_TYPES:
        if not req:
            raise HTTPException(status_code=400, detail="Belgesiz giriş için referans seçilmesi zorunludur.")
        entry_type = "gelir" if invoice_type == "belgesiz_gelir" else "gider"
        entry = UndocumentedEntry(
            id          = _uuid(),
            request_id  = req_id,
            entry_type  = entry_type,
            description = belgesiz_description.strip(),
            amount      = float(belgesiz_amount or 0),
            entry_date  = belgesiz_date or "",
            created_by  = current_user.id,
            created_at  = _now(),
        )
        db.add(entry)
        db.commit()
        return RedirectResponse(url=f"/requests/{req_id}#tab-financial", status_code=303)

    from database import EVENT_COMPANY_ID
    try:
        lines = json.loads(lines_json or "[]")
    except Exception:
        lines = []

    # Her satırın vat_amount'unu hesapla
    for ln in lines:
        amt = float(ln.get("amount", 0) or 0)
        vat = float(ln.get("vat_rate", 0) or 0)
        ln["vat_amount"] = round(amt * vat / 100, 2)

    excl, vat_total, incl = _compute_totals(lines)
    # geriye uyumluluk için vat_rate: ilk satırın oranı (veya 0)
    first_vat = float(lines[0].get("vat_rate", 0)) if lines else 0.0

    # Onay zinciri: fatura talebi → oluşturanın yöneticisine gider (GM nihai onaylayıcı)
    # Oluşturan kişi ASLA kendi talebini onaylayamaz.
    _initial_approver_id = None
    if req:
        creator = db.query(User).filter(User.id == current_user.id).first()
        if creator and creator.manager_id:
            _initial_approver_id = creator.manager_id          # yönetici (müdür)
        else:
            # Yönetici yoksa doğrudan GM'e gider
            _gm = db.query(User).filter(
                User.active == True,
                User.is_gm == True,
            ).first()
            if not _gm:
                _gm = db.query(User).filter(
                    User.active == True,
                    User.role.in_(["admin", "genel_mudur"]),
                ).first()
            _initial_approver_id = _gm.id if _gm else None

    # due_date otomatik hesaplama: boşsa invoice_date + payment_term
    _due_date = due_date or None
    if not _due_date and invoice_date:
        try:
            _pt = int(vendor_payment_term or 60)
            # Mevcut vendor'un payment_term'i öncelikli
            if vendor_id.strip():
                _fv = db.query(Vendor).filter(Vendor.id == vendor_id.strip()).first()
                if _fv and _fv.payment_term:
                    _pt = _fv.payment_term
            _base = _date.fromisoformat(invoice_date)
            _due_date = (_base + timedelta(days=_pt)).isoformat()
        except Exception:
            pass

    inv = Invoice(
        id                  = _uuid(),
        request_id          = req_id or None,
        invoice_type        = invoice_type,
        invoice_no          = invoice_no.strip(),
        invoice_date        = invoice_date or _date.today().isoformat(),
        due_date            = _due_date,
        vendor_id           = vendor_id.strip() or None,
        vendor_name         = vendor_name.strip(),
        description         = description.strip(),
        lines_json          = json.dumps(lines, ensure_ascii=False),
        amount              = excl,
        vat_rate            = first_vat,
        vat_amount          = vat_total,
        total_amount        = incl,
        status              = "pending",
        current_approver_id = _initial_approver_id,
        company_id          = EVENT_COMPANY_ID,
        created_by          = current_user.id,
        created_at          = _now(),
        updated_at          = _now(),
    )

    if document and document.filename:
        doc_path, doc_name = _save_document(document, inv.id)
        inv.document_path = doc_path
        inv.document_name = doc_name

    db.add(inv)
    db.flush()

    # ── Tanımlı tedarikçi oluştur / bağla ──────────────────────────────────
    _resolved_vendor_id = vendor_id.strip() or None
    if define_vendor == "yes" and not _resolved_vendor_id and vendor_name.strip():
        # Aynı isimde zaten var mı kontrol et (case-insensitive)
        existing_fv = db.query(Vendor).filter(
            Vendor.name.ilike(vendor_name.strip())
        ).first()
        if existing_fv:
            _resolved_vendor_id = existing_fv.id
        else:
            _pt = max(1, int(vendor_payment_term or 60))
            new_fv = Vendor(
                id           = _uuid(),
                name         = vendor_name.strip(),
                payment_term = _pt,
                active       = True,
                created_by   = current_user.id,
                created_at   = _now(),
                updated_at   = _now(),
            )
            db.add(new_fv)
            db.flush()
            _resolved_vendor_id = new_fv.id

        # Bu faturayı ilişkilendir
        inv.vendor_id = _resolved_vendor_id

        # Aynı vendor_name sahip geçmiş faturaları da backfill et
        if _resolved_vendor_id:
            db.query(Invoice).filter(
                Invoice.vendor_name.ilike(vendor_name.strip()),
                Invoice.vendor_id == None,
                Invoice.id != inv.id,
            ).update({"vendor_id": _resolved_vendor_id}, synchronize_session=False)

    # ── Kesilen fatura: müşteri bağla / oluştur ──────────────────────────────
    if invoice_type in ("kesilen", "iade_kesilen"):
        _cust_name = vendor_name.strip()
        _cust_id   = customer_id.strip() or None

        if not _cust_id and _cust_name:
            # Önce mevcut müşteride ara (exact match)
            existing_cust = db.query(Customer).filter(
                Customer.name.ilike(_cust_name)
            ).first()
            if existing_cust:
                _cust_id = existing_cust.id
            elif define_customer == "yes":
                # Yeni müşteri oluştur
                import re as _re
                _code = _re.sub(r"[^a-z]", "", _cust_name.lower())[:3] or "mst"
                # code benzersiz yapılsın
                _base_code = _code
                _sfx = 1
                while db.query(Customer).filter(Customer.code == _code).first():
                    _code = _base_code[:2] + str(_sfx)
                    _sfx += 1
                new_cust = Customer(
                    id         = _uuid(),
                    name       = _cust_name,
                    code       = _code,
                    created_at = _now(),
                )
                db.add(new_cust)
                db.flush()
                _cust_id = new_cust.id

        # vendor_name'i müşteri adına normalize et
        if _cust_id:
            cust_obj = db.query(Customer).filter(Customer.id == _cust_id).first()
            if cust_obj:
                inv.vendor_name = cust_obj.name

    # Kütüphane: fatura girişi logu
    from models import INVOICE_TYPE_LABELS as _ITL
    if req_id:
        log_activity(
            db, req_id, "invoice_created",
            f"Fatura eklendi — {_ITL.get(inv.invoice_type, inv.invoice_type)}: {inv.vendor_name or inv.invoice_no or '—'}",
            detail=f"Tutar: ₺{inv.amount:,.0f}",
            user_id=current_user.id,
        )
    _add_log(db, inv.id, "created", current_user.id,
             note=f"{inv.type_label} — {inv.vendor_name or '—'} — ₺{inv.total_amount:,.0f}")
    db.commit()

    # Bildirim: ilk onaylayıcıya (current_approver_id) bildirim gönder
    if req:
        from utils.notifications import create_notification
        vendor = inv.vendor_name or inv.invoice_no or "—"

        # İlk onaylayıcı = PM (req.created_by) — kendisi değilse bildir
        _notified_ids = set()
        if inv.current_approver_id and inv.current_approver_id != current_user.id:
            create_notification(
                db,
                user_id    = inv.current_approver_id,
                notif_type = "invoice_pending",
                title      = f"Fatura onayı bekleniyor — {vendor}",
                message    = f"{req.request_no} referansına ait fatura onayınızı bekliyor.",
                link       = f"/requests/{req_id}#tab-financial",
                ref_id     = inv.id,
            )
            _notified_ids.add(inv.current_approver_id)

        # Talebi oluşturan PM'e bildirim (zaten bildirilmediyse + kendisi değilse)
        if req.created_by and req.created_by not in _notified_ids and req.created_by != current_user.id:
            create_notification(
                db,
                user_id    = req.created_by,
                notif_type = "invoice_pending",
                title      = f"Fatura eklendi — {vendor}",
                message    = f"{req.request_no} referansına fatura eklendi.",
                link       = f"/requests/{req_id}#tab-financial",
                ref_id     = inv.id,
            )
        db.commit()

    if req_id:
        return RedirectResponse(url=f"/requests/{req_id}#tab-financial", status_code=303)
    return RedirectResponse(url="/invoices/unlinked", status_code=303)


# ---------------------------------------------------------------------------
# GET /invoices/{id}/edit
# ---------------------------------------------------------------------------

@router.get("/{invoice_id}/edit", response_class=HTMLResponse, name="invoices_edit_form")
async def invoices_edit_form(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(current_user)
    inv = _get_invoice_or_404(db, invoice_id)
    all_requests = db.query(ReqModel).filter(
        ReqModel.status.notin_(["cancelled", "closing", "closed"])
    ).order_by(ReqModel.created_at.desc()).all()
    undoc_entries = inv.request.undocumented_entries if inv.request else []
    return templates.TemplateResponse("invoices/form.html", {
        "request":       request,
        "current_user":  current_user,
        "page_title":    "Fatura Düzenle",
        "invoice":       inv,
        "selected_req":  inv.request,
        "all_requests":  all_requests,
        "undoc_entries": undoc_entries,
        "invoice_types": INVOICE_TYPES,
        "edit_mode":     True,
    })


# ---------------------------------------------------------------------------
# POST /invoices/{id}/edit
# ---------------------------------------------------------------------------

@router.post("/{invoice_id}/edit", name="invoices_update")
async def invoices_update(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    invoice_type: str = Form(...),
    invoice_no:   str = Form(""),
    invoice_date: str = Form(""),
    due_date:     str = Form(""),
    vendor_id:    str = Form(""),
    vendor_name:  str = Form(""),
    description:  str = Form(""),
    lines_json:   str = Form("[]"),
    document:     UploadFile = File(None),
):
    _require_finance(current_user)
    inv = _get_invoice_or_404(db, invoice_id)

    try:
        lines = json.loads(lines_json or "[]")
    except Exception:
        lines = []

    for ln in lines:
        amt = float(ln.get("amount", 0) or 0)
        vat = float(ln.get("vat_rate", 0) or 0)
        ln["vat_amount"] = round(amt * vat / 100, 2)

    excl, vat_total, incl = _compute_totals(lines)
    first_vat = float(lines[0].get("vat_rate", 0)) if lines else 0.0

    inv.invoice_type = invoice_type
    inv.invoice_no   = invoice_no.strip()
    inv.invoice_date = invoice_date or _date.today().isoformat()
    inv.due_date     = due_date or None
    inv.vendor_id    = vendor_id.strip() or None
    inv.vendor_name  = vendor_name.strip()
    inv.description  = description.strip()
    inv.lines_json   = json.dumps(lines, ensure_ascii=False)
    inv.amount       = excl
    inv.vat_rate     = first_vat
    inv.vat_amount   = vat_total
    inv.total_amount = incl
    inv.updated_at   = _now()

    if document and document.filename:
        if inv.document_path:
            delete_upload(inv.document_path)
        doc_path, doc_name = _save_document(document, inv.id)
        inv.document_path = doc_path
        inv.document_name = doc_name

    db.commit()
    if inv.request_id:
        return RedirectResponse(url=f"/requests/{inv.request_id}#tab-financial", status_code=303)
    return RedirectResponse(url="/invoices/unlinked", status_code=303)


# ---------------------------------------------------------------------------
# POST /invoices/parse-pdf  — PDF'den otomatik fatura doldurma (AI'sız)
# ---------------------------------------------------------------------------

@router.post("/parse-pdf", name="invoices_parse_pdf")
async def invoices_parse_pdf(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    _require_finance(current_user)

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        return JSONResponse({"error": "Dosya 10 MB'ı aşıyor."}, status_code=400)

    try:
        from agents.invoice_parser import parse_invoice, _debug_extract
        debug = _debug_extract(file_bytes)
        print("[PARSE-PDF DEBUG] Tables:", len(debug.get("tables", [])), flush=True)
        for i, t in enumerate(debug.get("tables", [])):
            print(f"  Table {i}: {len(t)} rows, header={t[0] if t else 'empty'}", flush=True)
            for row in t[1:4]:
                print(f"    row: {row}", flush=True)
        data = parse_invoice(file_bytes, file.filename or "invoice.pdf")
        return JSONResponse({"ok": True, "data": data})
    except Exception as e:
        import traceback
        print(f"[PARSE-PDF] Hata: {e}\n{traceback.format_exc()}", flush=True)
        return JSONResponse({"error": "PDF okunamadı. Dosyayı kontrol edin."}, status_code=400)


# ---------------------------------------------------------------------------
# POST /invoices/{id}/approve  — referans sahibi (PM) veya admin onaylar
# ---------------------------------------------------------------------------
# POST /invoices/{id}/cut  — Muhasebe faturayı keser (detayları doldurur + onaylar)
# ---------------------------------------------------------------------------

@router.post("/{invoice_id}/cut", name="invoices_cut")
async def invoices_cut(
    invoice_id:   str,
    request:      Request,
    current_user: User = Depends(get_current_user),
    db:           Session = Depends(get_db),
    invoice_no:   str = Form(""),
    invoice_date: str = Form(""),
    due_date:     str = Form(""),
    document:     UploadFile = File(None),
):
    """Muhasebe onaylı faturaya detay ekler (fatura no, tarih, belge). Durum değişmez."""
    _require_finance(current_user)
    inv = _get_invoice_or_404(db, invoice_id)
    if inv.status not in ("approved", "gm_approved"):
        raise HTTPException(status_code=400, detail="Sadece onaylı faturalara detay eklenebilir.")

    if invoice_no.strip():
        inv.invoice_no = invoice_no.strip()
    if invoice_date:
        inv.invoice_date = invoice_date
    if due_date:
        inv.due_date = due_date

    if document and document.filename:
        doc_path, doc_name = _save_document(document, inv.id)
        inv.document_path = doc_path
        inv.document_name = doc_name

    # Eski gm_approved kayıtlar için durum approved'a güncellenir; zaten approved olanlar değişmez
    if inv.status == "gm_approved":
        inv.status = "approved"
    inv.updated_at  = _now()
    db.commit()
    return RedirectResponse(url="/invoices?status_filter=gm_approved", status_code=303)


# ---------------------------------------------------------------------------

@router.post("/{invoice_id}/approve", name="invoices_approve")
async def invoices_approve(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inv = _get_invoice_or_404(db, invoice_id)
    # Oluşturan kişi kendi talebini onaylayamaz
    if inv.created_by == current_user.id and not _is_gm(current_user) and current_user.role not in ("admin", "muhasebe_muduru"):
        raise HTTPException(status_code=403, detail="Kendi oluşturduğunuz fatura talebini onaylayamazsınız.")
    _require_approval_permission(current_user, inv, db)

    if inv.status not in ("pending", "mudur_approved", "gm_approved"):
        raise HTTPException(status_code=400, detail="Bu fatura onay için uygun durumda değil.")

    # Eski gm_approved kayıtlar — doğrudan approved
    if inv.status == "gm_approved":
        inv.status              = "approved"
        inv.current_approver_id = None
        inv.approved_by         = current_user.id
        inv.approved_at         = _now()
        inv.rejection_note      = ""
        inv.updated_at          = _now()
        _apply_prepayments(db, inv)
        _add_log(db, inv.id, "approved", current_user.id)
        db.commit()
        if inv.request_id:
            return RedirectResponse(url=f"/requests/{inv.request_id}#tab-financial", status_code=303)
        return RedirectResponse(url="/invoices?status_filter=approved", status_code=303)

    # Admin / muhasebe_muduru / GM → zinciri atla, direkt onayla
    if current_user.role in ("admin", "muhasebe_muduru") or _is_gm(current_user):
        inv.status              = "approved"
        inv.current_approver_id = None
        inv.approved_by         = current_user.id
        inv.approved_at         = _now()
        inv.rejection_note      = ""
        inv.updated_at          = _now()
        _apply_prepayments(db, inv)
        _add_log(db, inv.id, "approved", current_user.id)
        db.commit()
        if inv.request_id:
            return RedirectResponse(url=f"/requests/{inv.request_id}#tab-financial", status_code=303)
        return RedirectResponse(url="/invoices?status_filter=approved", status_code=303)

    # Zincirleme onay: current_approver_id == current_user.id
    approver_user = db.query(User).filter(User.id == current_user.id).first()
    limit = approver_user.org_title.budget_limit if (approver_user and approver_user.org_title) else None

    if limit is None or (inv.total_amount or 0) <= limit:
        # Limit yeterli → tamamen onaylandı
        inv.status              = "approved"
        inv.current_approver_id = None
        inv.approved_by         = current_user.id
        inv.approved_at         = _now()
        inv.rejection_note      = ""
        inv.updated_at          = _now()
        _apply_prepayments(db, inv)
        _add_log(db, inv.id, "approved", current_user.id)
        db.commit()
        if inv.request_id:
            return RedirectResponse(url=f"/requests/{inv.request_id}#tab-financial", status_code=303)
        return RedirectResponse(url="/invoices?status_filter=approved", status_code=303)
    else:
        # Limit yetersiz → bir üst yöneticiye eskalasyon
        next_approver = _find_next_approver(db, current_user.id)
        if next_approver:
            inv.current_approver_id = next_approver.id
            inv.rejection_note      = ""
            inv.updated_at          = _now()
            _add_log(db, inv.id, "forwarded", current_user.id,
                     note=f"Limit aşımı — {next_approver.full_name} adresine yönlendirildi")
            db.commit()
            # Bir üst onaylayıcıya bildirim
            if inv.request_id:
                from utils.notifications import create_notification
                _req_obj = inv.request
                create_notification(
                    db,
                    user_id    = next_approver.id,
                    notif_type = "invoice_pending",
                    title      = f"Fatura onayı bekleniyor — {inv.vendor_name or inv.invoice_no or '—'}",
                    message    = (
                        f"{_req_obj.request_no if _req_obj else inv.request_id} referansına ait fatura "
                        f"onayınızı bekliyor. ({current_user.full_name} onayladı, limit aşımı nedeniyle yönlendirildi)"
                    ),
                    link  = f"/requests/{inv.request_id}#tab-financial",
                    ref_id= inv.id,
                )
                db.commit()
            if inv.request_id:
                return RedirectResponse(url=f"/requests/{inv.request_id}#tab-financial", status_code=303)
            return RedirectResponse(url="/invoices?status_filter=pending", status_code=303)
        else:
            # Zincirde üst yönetici yok → üst kademedeyiz, direkt onayla
            inv.status              = "approved"
            inv.current_approver_id = None
            inv.approved_by         = current_user.id
            inv.approved_at         = _now()
            inv.rejection_note      = ""
            inv.updated_at          = _now()
            _apply_prepayments(db, inv)
            _add_log(db, inv.id, "approved", current_user.id)
            db.commit()
            if inv.request_id:
                return RedirectResponse(url=f"/requests/{inv.request_id}#tab-financial", status_code=303)
            return RedirectResponse(url="/invoices?status_filter=approved", status_code=303)


# ---------------------------------------------------------------------------
# POST /invoices/{id}/reject  — referans sahibi (PM) veya admin reddeder
# ---------------------------------------------------------------------------

@router.post("/{invoice_id}/reject", name="invoices_reject")
async def invoices_reject(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    rejection_note: str = Form(""),
):
    inv = _get_invoice_or_404(db, invoice_id)
    _require_approval_permission(current_user, inv, db)

    if inv.status not in ("pending", "mudur_approved", "approved"):
        raise HTTPException(status_code=400, detail="Bu fatura iptal edilmiş.")

    inv.status         = "rejected"
    inv.rejection_note = rejection_note.strip()[:300]
    inv.approved_by    = None
    inv.approved_at    = None
    inv.updated_at     = _now()
    _add_log(db, inv.id, "rejected", current_user.id, note=rejection_note.strip()[:300])
    db.commit()
    if inv.request_id:
        return RedirectResponse(url=f"/requests/{inv.request_id}#tab-financial", status_code=303)
    return RedirectResponse(url="/invoices/unlinked", status_code=303)


# ---------------------------------------------------------------------------
# POST /invoices/{id}/reassign  — sadece admin, referansı değiştirir
# ---------------------------------------------------------------------------

@router.post("/{invoice_id}/reassign", name="invoices_reassign")
async def invoices_reassign(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    new_request_id: str = Form(...),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Sadece admin referans değiştirebilir.")

    inv = _get_invoice_or_404(db, invoice_id)
    old_req_id = inv.request_id

    new_req = db.query(ReqModel).filter(ReqModel.id == new_request_id).first()
    if not new_req:
        raise HTTPException(status_code=404, detail="Hedef referans bulunamadı.")

    inv.request_id = new_request_id
    inv.updated_at = _now()
    db.commit()
    return RedirectResponse(url=f"/requests/{old_req_id}#tab-financial", status_code=303)


# ---------------------------------------------------------------------------
# GET /invoices/unlinked  — Referans bekleyen faturalar (herkese görünür)
# ---------------------------------------------------------------------------

@router.get("/unlinked", response_class=HTMLResponse, name="invoices_unlinked")
async def invoices_unlinked(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    invoices = (
        db.query(Invoice)
        .filter(Invoice.request_id == None, Invoice.status != "cancelled")
        .order_by(Invoice.created_at.desc())
        .all()
    )
    req_q = db.query(ReqModel).filter(
        ReqModel.status.notin_(["cancelled", "closing", "closed"])
    )
    # mudur (Etkinlik Süreç Müdürü), GM, admin, muhasebe: tüm referansları görür
    # yonetici/asistan: sadece kendi referansları
    if current_user.role in ("yonetici", "asistan"):
        req_q = req_q.filter(ReqModel.created_by == current_user.id)
    all_requests = req_q.order_by(ReqModel.created_at.desc()).all()
    return templates.TemplateResponse("invoices/unlinked.html", {
        "request":      request,
        "current_user": current_user,
        "page_title":   "Referans Bekleyen Faturalar",
        "invoices":     invoices,
        "all_requests": all_requests,
        "invoice_types": INVOICE_TYPES,
    })


# ---------------------------------------------------------------------------
# POST /invoices/{id}/assign-request  — Faturaya referans ata
# ---------------------------------------------------------------------------

@router.get("/api/active-requests", name="invoices_active_requests_api")
async def invoices_active_requests_api(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bölme modal'ı için aktif referans listesi — JSON."""
    from utils.funds import can_split_invoice
    if not can_split_invoice(current_user):
        raise HTTPException(403)
    q = db.query(ReqModel).filter(
        ReqModel.status.notin_(["draft", "cancelled", "closed"]),
        ReqModel.is_fund_pool == False,                     # noqa: E712
    )
    # mudur (Etkinlik Süreç Müdürü) tüm referansları görür — bölme için takım engeli yok
    rows = q.order_by(ReqModel.created_at.desc()).limit(300).all()
    return JSONResponse([{
        "id":         r.id,
        "request_no": r.request_no,
        "event_name": r.event_name,
        "client_name": r.client_name or "",
    } for r in rows])


@router.post("/{invoice_id}/split", name="invoices_split")
async def invoices_split(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Tedarikçiden gelen faturayı birden fazla alt referansa pay et.

    Form payload (JSON-encoded list olarak `allocations_json` ya da repeating
    form fields):
      allocations: [
        {request_id: "<alt_ref_id>" | "__vendor_fund__", amount_incl: 1500.00, vat_rate: 20},
        ...
      ]

    "__vendor_fund__" hedefi seçilirse: tedarikçi adı + yıl bazlı vendor fund
    pool otomatik bulunur/yaratılır.

    Validasyon: SUM(allocations.amount_incl) == invoice.total_amount.
    Her allocation için yeni bir Invoice (gelen, status=approved) yaratılır;
    parent_invoice_id ile orijinale bağlanır. Parent fatura is_split_parent=True
    olur ve finansal hesaplara dahil edilmez.
    """
    from utils.funds import can_split_invoice, get_or_create_vendor_fund_pool
    if not can_split_invoice(current_user):
        raise HTTPException(403, "Fatura bölme yetkiniz yok. (Admin / GM / Muhasebe Müdürü / Etkinlik Süreç Müdürü)")

    inv = _get_invoice_or_404(db, invoice_id)
    if inv.invoice_type not in ("gelen",):
        raise HTTPException(400, "Sadece gelen (tedarikçi) faturaları bölünebilir.")
    if inv.is_split_parent:
        raise HTTPException(400, "Bu fatura zaten bölünmüş.")
    if inv.parent_invoice_id:
        raise HTTPException(400, "Bu fatura zaten başka bir bölmenin parçası.")
    if inv.status not in ("approved", "active"):
        raise HTTPException(400, "Bölmek için fatura onaylanmış olmalı.")

    # Form datasını al
    form = await request.form()
    import json as _json
    raw = form.get("allocations_json") or "[]"
    try:
        allocations = _json.loads(raw)
        if not isinstance(allocations, list):
            raise ValueError
    except Exception:
        raise HTTPException(400, "Geçersiz allocations verisi.")
    if not allocations:
        raise HTTPException(400, "En az bir bölme satırı gerekli.")

    # Toplam validasyonu
    total_alloc = round(sum(float(a.get("amount_incl", 0) or 0) for a in allocations), 2)
    parent_total = round(float(inv.total_amount or 0), 2)
    if abs(total_alloc - parent_total) > 0.05:
        raise HTTPException(
            400,
            f"Atama toplamı fatura tutarına eşit olmalı: ₺{total_alloc:,.2f} ≠ ₺{parent_total:,.2f}"
        )

    # Vendor fund pool — gerekirse oluştur (lazy)
    _vendor_fund_cache = {"pool": None}
    def _vendor_fund():
        if _vendor_fund_cache["pool"] is None:
            year = int(inv.invoice_date[:4]) if inv.invoice_date else _now().year
            _vendor_fund_cache["pool"] = get_or_create_vendor_fund_pool(
                inv.vendor_name or "Tedarikçi", year, "TRY", db,
                created_by_id=current_user.id,
            )
        return _vendor_fund_cache["pool"]

    # Child fatura kayıtları
    child_count = 0
    for alloc in allocations:
        target = (alloc.get("request_id") or "").strip()
        if not target:
            raise HTTPException(400, "Hedef referans seçilmedi.")

        amount_incl = round(float(alloc.get("amount_incl", 0) or 0), 2)
        if amount_incl <= 0:
            continue
        vat_rate = float(alloc.get("vat_rate", inv.vat_rate or 20.0))
        amount_excl = round(amount_incl / (1 + vat_rate / 100.0), 2) if vat_rate else amount_incl
        vat_amount  = round(amount_incl - amount_excl, 2)

        if target == "__vendor_fund__":
            target_req = _vendor_fund()
            target_req.fund_initial_amount = float(target_req.fund_initial_amount or 0) + amount_incl
            target_id = target_req.id
            note = f"Bölme kalanı (parent: {inv.invoice_no or inv.id[:8]})"
        else:
            target_req = db.query(ReqModel).filter(ReqModel.id == target).first()
            if not target_req:
                raise HTTPException(400, f"Hedef referans bulunamadı: {target}")
            target_id = target_req.id
            note = f"Bölme — kaynak fatura: {inv.invoice_no or inv.id[:8]}"

        child = Invoice(
            id=_uuid(),
            request_id=target_id,
            vendor_id=inv.vendor_id,
            invoice_type="gelen",
            invoice_no=inv.invoice_no or "",
            invoice_date=inv.invoice_date,
            due_date=inv.due_date,
            vendor_name=inv.vendor_name or "",
            description=f"{inv.description} · {note}".strip(" ·"),
            amount=amount_excl,
            vat_rate=vat_rate,
            vat_amount=vat_amount,
            total_amount=amount_incl,
            status="approved",
            payment_status=inv.payment_status,
            payment_method=inv.payment_method,
            is_split_parent=False,
            parent_invoice_id=inv.id,
            created_by=current_user.id,
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(child)
        child_count += 1

        log_activity(
            db, target_id, "invoice_split_received",
            f"Bölünmüş fatura payı geldi — {inv.vendor_name or '—'}: ₺{amount_incl:,.2f}",
            user_id=current_user.id,
        )

    if child_count == 0:
        raise HTTPException(400, "Hiçbir geçerli bölme satırı yok.")

    inv.is_split_parent = True
    inv.updated_at = _now()
    if inv.request_id:
        log_activity(
            db, inv.request_id, "invoice_split",
            f"Fatura {child_count} parçaya bölündü — toplam ₺{parent_total:,.2f}",
            user_id=current_user.id,
        )
    db.commit()

    # Geri dönüş: hangi sayfadan geldiyse oraya
    referer = request.headers.get("referer") or "/invoices"
    return RedirectResponse(url=referer, status_code=303)


@router.post("/{invoice_id}/assign-request", name="invoices_assign_request")
async def invoices_assign_request(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    new_request_id: str = Form(...),
):
    inv = _get_invoice_or_404(db, invoice_id)
    if inv.request_id:
        raise HTTPException(status_code=400, detail="Bu faturanın zaten bir referansı var.")

    new_req = db.query(ReqModel).filter(ReqModel.id == new_request_id).first()
    if not new_req:
        raise HTTPException(status_code=404, detail="Hedef referans bulunamadı.")
    # mudur (Etkinlik Süreç Müdürü) ve GM tüm referanslara atama yapabilir
    if current_user.role in ("yonetici", "asistan"):
        if new_req.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="Bu referansa atama yetkiniz yok.")

    inv.request_id = new_request_id
    inv.updated_at = _now()

    from models import INVOICE_TYPE_LABELS as _ITL
    log_activity(
        db, new_request_id, "invoice_assigned",
        f"Fatura referansa atandı — {_ITL.get(inv.invoice_type, inv.invoice_type)}: {inv.vendor_name or inv.invoice_no or '—'}",
        detail=f"Tutar: ₺{inv.amount:,.0f}",
        user_id=current_user.id,
    )
    db.commit()
    return RedirectResponse(url=f"/requests/{new_request_id}#tab-financial", status_code=303)


# ---------------------------------------------------------------------------
# POST /invoices/{id}/delete
# ---------------------------------------------------------------------------

@router.post("/{invoice_id}/delete", name="invoices_delete")
async def invoices_delete(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(current_user)
    inv = _get_invoice_or_404(db, invoice_id)
    req_id = inv.request_id
    inv.status     = "cancelled"
    inv.updated_at = _now()
    db.commit()
    if req_id:
        return RedirectResponse(url=f"/requests/{req_id}#tab-financial", status_code=303)
    return RedirectResponse(url="/invoices/unlinked", status_code=303)


# ---------------------------------------------------------------------------
# GET /invoices/{id}/document
# ---------------------------------------------------------------------------

@router.get("/{invoice_id}/document", name="invoices_document")
async def invoices_document(
    invoice_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inv = _get_invoice_or_404(db, invoice_id)
    if not inv.document_path:
        raise HTTPException(status_code=404, detail="Belge bulunamadı.")
    return _serve_upload(inv.document_path, inv.document_name or "belge")
