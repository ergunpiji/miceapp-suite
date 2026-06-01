"""
Satın Alma — Talep yönetimi router'ı
PM:    Yeni talep oluştur, referanslarım
Admin: Tüm referanslar
Satın Alma: Gelen referanslar, durum güncelle
"""

import io
import json
import os
import unicodedata
import urllib.parse
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session, joinedload

from auth import get_current_user, has_permission
from database import generate_ref_no, get_db
from models import (
    Budget, Customer, CustomCategory, EmailTemplate, EventType, PrepaymentRequest,
    REQUEST_STATUSES, REQUEST_TABS,
    TR_CITIES, SUPPLIER_TYPES, Service, SERVICE_CATEGORIES, Request as ReqModel, RequestModule, Team, User, Vendor,
    _uuid, _now, REQUEST_STATUS_LABELS, DeskReference,
)
from routers.library import log_activity

router = APIRouter(prefix="/requests", tags=["requests"])
from templates_config import templates


def _get_oa_module(request_id: str, db: Session):
    return db.query(RequestModule).filter(
        RequestModule.request_id == request_id,
        RequestModule.module_type == "operasyon",
        RequestModule.active == True,
    ).first()


def _check_pm_or_admin(current_user: User, db: Session = None):
    # miceapp suite: event'te TÜM kullanıcılar referans/talep oluşturabilir (yetki kısıtı yok).
    return


def _ensure_reference(db: Session, req, current_user: User) -> None:
    """Talep için ortak references kaydı oluşturur — idempotent (yoksa).
    miceapp suite: event referansı yaratır, desk (finans) görür. Draft'lar bunu çağırmaz."""
    if not req.request_no:
        return
    if db.query(DeskReference).filter(DeskReference.ref_no == req.request_no).first():
        return  # zaten var
    company_id = None
    if req.customer_id:
        _rc = db.query(Customer).filter(Customer.id == req.customer_id).first()
        if _rc:
            company_id = _rc.company_id

    def _d(s):
        try:
            return date.fromisoformat(s) if s else None
        except Exception:
            return None

    db.add(DeskReference(
        id=_uuid(), ref_no=req.request_no, company_id=company_id,
        customer_id=req.customer_id, title=req.event_name,
        event_type=req.event_type, check_in=_d(req.check_in), check_out=_d(req.check_out),
        status="aktif", created_by=current_user.id, owner_id=current_user.id, created_at=_now(),
    ))


def _get_subtree_ids(user_id: str, db: Session) -> list[str]:
    """Kullanıcının tüm astları (doğrudan + dolaylı) — BFS."""
    result: list[str] = []
    queue = [user_id]
    while queue:
        curr = queue.pop(0)
        subs = [r.id for r in db.query(User).filter(User.manager_id == curr).all()]
        for sid in subs:
            if sid not in result:
                result.append(sid)
                queue.append(sid)
    return result


def _check_satinalma_or_admin(current_user: User):
    if current_user.role not in ("admin", "satinalma"):
        raise HTTPException(status_code=403, detail="Bu sayfa Satın Alma kullanıcılarına özeldir.")


def _check_fund_admin(current_user: User):
    """Fon havuzu aç / transfer yap yetkisi: admin / muhasebe_muduru / GM."""
    from utils.funds import can_manage_funds
    if not can_manage_funds(current_user):
        raise HTTPException(
            status_code=403,
            detail="Fon havuzu işlemleri için yetkiniz yok. (Admin / Muhasebe Müdürü / Genel Müdür)"
        )


# ---------------------------------------------------------------------------
# Listeler
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="requests_list")
async def requests_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status_filter: str = "",
    search: str = "",
    view: str = "",
):
    """Rol bazlı talep listesi"""
    query = db.query(ReqModel)

    # NOT: requests tablosunda company_id kolonu henüz YOK (model tanımlıyor ama DB'de yok).
    # Tenant filtresi, kolon eklenip backfill yapıldıktan sonra eklenmeli (bkz. denetim raporu).

    # ── ADIM 1: Rol bazlı BASE SCOPE — tüm view filtreleri bunun üstüne eklenir ──
    if current_user.is_gm:
        pass  # GM: tüm referanslar
    elif current_user.role == "mudur":
        _mudur_team = db.query(Team).filter(Team.id == current_user.team_id).first() if current_user.team_id else None
        if _mudur_team and _mudur_team.is_support_team:
            # Destek ekibi müdürü: kendi üyelerinin oluşturduğu tüm referanslar
            _member_ids = [u.id for u in db.query(User).filter(
                User.team_id == current_user.team_id, User.active == True).all()]
            query = query.filter(ReqModel.created_by.in_(_member_ids))
        elif current_user.team_id:
            # Normal birim müdürü: sadece kendi takımı
            query = query.filter(ReqModel.team_id == current_user.team_id)
        else:
            query = query.filter(False)
    elif current_user.role == "yonetici":
        sub_ids = _get_subtree_ids(current_user.id, db)
        query = query.filter(ReqModel.created_by.in_([current_user.id] + sub_ids))
        if current_user.team_id:
            query = query.filter(ReqModel.team_id == current_user.team_id)
    elif current_user.role == "asistan":
        query = query.filter(ReqModel.created_by == current_user.id)
    elif current_user.role == "satinalma":
        query = query.filter(
            ReqModel.status.in_(["pending", "in_progress", "venues_contacted", "budget_ready",
                                  "offer_sent", "revision"])
        )
    # admin, muhasebe_muduru → filtre yok (tüm veriler)

    # ── ADIM 2: View / sayfa filtreleri (base scope üstüne eklenir) ──
    page_title = ""
    if view == "ongoing":
        query = query.filter(
            ReqModel.status == "confirmed",
            ReqModel.confirmed_budget_id.isnot(None),
        )
        page_title = "Aktif İşler"
    elif view == "completed":
        query = query.filter(ReqModel.status == "completed")
        page_title = "Tamamlanan İşler"
    elif view == "closing":
        query = query.filter(ReqModel.status == "closing")
        page_title = "Kapama Onayında"
    elif view == "closed":
        query = query.filter(ReqModel.status == "closed")
        page_title = "Kapatılan Dosyalar"
    elif view == "cancelled":
        query = query.filter(ReqModel.status == "cancelled")
        page_title = "İptal İşler"
    elif view == "pending_work":
        query = query.filter(ReqModel.status.in_(
            ["pending", "in_progress", "venues_contacted", "budget_ready"]
        ))
        page_title = "Yeni & İşlemdeki Talepler"
    elif view == "awaiting":
        query = query.filter(ReqModel.status.in_(["offer_sent", "revision", "postponed"]))
        page_title = "Referans Onaylama"
    elif view == "fund_pools":
        query = query.filter(ReqModel.is_fund_pool == True)
        page_title = "Fon Havuzları"
    elif view == "awaiting_closure":
        from models import ClosureRequest
        # status=completed olanlar arasında henüz closure_request oluşturulmamışlar
        existing_closure_reqs = db.query(ClosureRequest.request_id).subquery()
        query = query.filter(
            ReqModel.status == "completed",
            ~ReqModel.id.in_(existing_closure_reqs),
        )
        page_title = "Referans Kapatma"

    # Sayfa başlığı (view yoksa role bazlı)
    if not page_title:
        if current_user.role in ("yonetici", "asistan"):
            page_title = "Referanslarım"
        elif current_user.role == "satinalma":
            page_title = "Gelen Referanslar"
        else:
            page_title = "Tüm Referanslar"

    if status_filter:
        query = query.filter(ReqModel.status == status_filter)

    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            ReqModel.request_no.ilike(term) |
            ReqModel.event_name.ilike(term) |
            ReqModel.client_name.ilike(term)
        )

    requests_all = query.order_by(ReqModel.created_at.desc()).all()

    # For ongoing view, resolve confirmed venue name from budget
    confirmed_venue_map = {}
    if view == "ongoing":
        for req in requests_all:
            if req.confirmed_budget_id:
                bgt = db.query(Budget).filter(Budget.id == req.confirmed_budget_id).first()
                if bgt:
                    confirmed_venue_map[req.id] = bgt.venue_name

    return templates.TemplateResponse(
        "requests/list.html",
        {
            "request":               request,
            "current_user":          current_user,
            "requests":              requests_all,
            "page_title":            page_title,
            "statuses":              REQUEST_STATUSES,
            "status_filter":         status_filter,
            "search":                search,
            "view":                  view,
            "confirmed_venue_map":   confirmed_venue_map,
        },
    )


# ---------------------------------------------------------------------------
# Fon Havuzu (Fund Pool) — kurulum ve transfer
# ---------------------------------------------------------------------------

@router.get("/fund-pools/new", response_class=HTMLResponse, name="fund_pool_new")
async def fund_pool_new(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_fund_admin(current_user)
    customers = db.query(Customer).order_by(Customer.name).all()
    return templates.TemplateResponse(
        "requests/fund_pool_form.html",
        {
            "request":      request,
            "current_user": current_user,
            "page_title":   "Fon Havuzu Aç",
            "customers":    customers,
        },
    )


@router.post("/fund-pools/new", name="fund_pool_create")
async def fund_pool_create(
    request: Request,
    customer_id:     str = Form(...),
    fund_name:       str = Form(...),
    fund_currency:   str = Form("TRY"),
    initial_amount:  str = Form("0"),
    vat_rate:        str = Form("20"),
    fund_year:       str = Form(""),
    invoice_no:      str = Form(""),
    invoice_date:    str = Form(""),
    document:        UploadFile = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_fund_admin(current_user)
    from models import Invoice
    from utils.funds import get_current_exchange_rate
    from routers.invoices import _save_document

    cust = db.query(Customer).filter(Customer.id == customer_id).first()
    if not cust:
        raise HTTPException(400, "Müşteri bulunamadı.")

    try:
        amount_incl = float(initial_amount.replace(",", "."))
    except ValueError:
        amount_incl = 0.0
    if amount_incl <= 0:
        raise HTTPException(400, "Fon başlangıç tutarı 0'dan büyük olmalı.")
    try:
        vat_pct = float(vat_rate)
    except ValueError:
        vat_pct = 20.0

    currency = (fund_currency or "TRY").upper()
    if currency not in ("TRY", "USD", "EUR"):
        currency = "TRY"

    # Fon yılı → check_in (yıl başlangıcı)
    try:
        year_int = int(fund_year) if fund_year else _now().year
    except ValueError:
        year_int = _now().year
    check_in_str = f"{year_int}-01-01"

    # Ref no (özel ev. tipi "fn" — fon)
    ref_no = generate_ref_no(db, "fn", cust.code, check_in_str)

    # Fon ana referansı
    fund_req = ReqModel(
        id=_uuid(),
        request_no=ref_no,
        client_name=cust.name,
        customer_id=cust.id,
        event_name=fund_name.strip(),
        event_type="fn",
        city="",
        cities_json="[]",
        attendee_count=0,
        check_in=check_in_str,
        check_out=f"{year_int}-12-31",
        status="fund_pool",
        items_json="{}",
        description=f"Fon havuzu · {currency} · %{vat_pct:g} KDV dahil",
        notes="",
        preferred_venues_json="[]",
        selected_venues_json="[]",
        contact_person_json="{}",
        is_fund_pool=True,
        fund_currency=currency,
        fund_initial_amount=amount_incl,
        fund_initial_vat_rate=vat_pct,
        team_id=cust.team_id if getattr(cust, "team_id", None) else current_user.team_id,
        created_by=current_user.id,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(fund_req)
    db.flush()

    # Muhasebe kaydı — ana fatura (kesilen)
    amount_excl = round(amount_incl / (1 + vat_pct / 100.0), 2) if vat_pct else amount_incl
    vat_amount  = round(amount_incl - amount_excl, 2)
    inv_id = _uuid()
    inv = Invoice(
        id=inv_id,
        request_id=fund_req.id,
        invoice_type="kesilen",
        invoice_no=invoice_no.strip(),
        invoice_date=(invoice_date or check_in_str),
        vendor_name=cust.name,
        description=f"Fon havuzu kurulum faturası — {fund_name.strip()}",
        amount=amount_excl,
        vat_rate=vat_pct,
        vat_amount=vat_amount,
        total_amount=amount_incl,
        status="approved",
        created_by=current_user.id,
        created_at=_now(),
        updated_at=_now(),
    )
    # Belge yükleme — opsiyonel
    if document and getattr(document, "filename", ""):
        try:
            doc_path, doc_name = _save_document(document, inv_id)
            inv.document_path = doc_path
            inv.document_name = doc_name
        except HTTPException:
            raise
        except Exception:
            pass  # belge yüklemede hata fonun kurulumunu engellemez
    db.add(inv)
    log_activity(
        db, fund_req.id, "fund_pool_created",
        f"Fon havuzu kuruldu: {currency} {amount_incl:,.2f} (KDV dahil)",
        user_id=current_user.id,
    )
    db.commit()
    return RedirectResponse(url=f"/requests/{fund_req.id}", status_code=status.HTTP_302_FOUND)


@router.get("/fund/{fund_id}/export", name="fund_pool_export")
async def fund_pool_export(
    fund_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fon havuzunun T cetveli + alt referans özeti — Excel."""
    # Sadece fon yöneticileri veya hesabı görüntüleyebilen finans rolleri
    from utils.funds import can_manage_funds
    if not can_manage_funds(current_user) and current_user.role not in ("muhasebe",):
        raise HTTPException(403, "Fon raporunu indirme yetkiniz yok.")
    fund = db.query(ReqModel).filter(ReqModel.id == fund_id).first()
    if not fund or not fund.is_fund_pool:
        raise HTTPException(404, "Fon havuzu bulunamadı.")

    from excel_export.fund_pool import build_fund_pool_excel
    try:
        buf = build_fund_pool_excel(fund, db)
    except Exception as exc:
        import traceback as _tb
        print(f"[FUND-POOL EXCEL ERROR] fund={fund_id}: {exc}\n{_tb.format_exc()}", flush=True)
        raise HTTPException(500, "Excel raporu oluşturulamadı.")

    raw_name = (fund.event_name or fund.request_no or "fon")[:40]
    ascii_name = unicodedata.normalize("NFKD", raw_name)
    ascii_name = "".join(c for c in ascii_name if ord(c) < 128)
    ascii_name = ascii_name.replace(" ", "_").replace("/", "-").strip("_") or "fon"
    filename_utf8 = urllib.parse.quote(f"{raw_name}_fon_raporu.xlsx")
    content_disposition = (
        f'attachment; filename="{ascii_name}_fon_raporu.xlsx"; '
        f"filename*=UTF-8''{filename_utf8}"
    )
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition},
    )


@router.post("/fund/{fund_id}/transfer", name="fund_transfer_create")
async def fund_transfer_create(
    fund_id: str,
    request: Request,
    related_request_id: str = Form(...),
    direction:          str = Form("out"),           # "out" | "in"
    amount:             str = Form("0"),
    vat_rate:           str = Form(""),
    exchange_rate_try:  str = Form(""),
    description:        str = Form(""),
    transfer_date:      str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_fund_admin(current_user)
    from models import FundTransfer
    from utils.funds import get_fund_balance, get_current_exchange_rate

    fund = db.query(ReqModel).filter(ReqModel.id == fund_id).first()
    if not fund or not fund.is_fund_pool:
        raise HTTPException(404, "Fon havuzu bulunamadı.")
    alt  = db.query(ReqModel).filter(ReqModel.id == related_request_id).first()
    if not alt:
        raise HTTPException(404, "Alt referans bulunamadı.")
    if direction not in ("out", "in"):
        raise HTTPException(400, "Geçersiz yön.")

    try:
        amt = float(amount.replace(",", "."))
    except ValueError:
        amt = 0.0
    if amt <= 0:
        raise HTTPException(400, "Transfer tutarı 0'dan büyük olmalı.")

    vat_pct = float(vat_rate) if vat_rate else float(fund.fund_initial_vat_rate or 20.0)
    rate    = float(exchange_rate_try) if exchange_rate_try else get_current_exchange_rate(fund.fund_currency)

    # Validasyon
    balance = get_fund_balance(fund, db)
    if direction == "out":
        if amt > balance["remaining"] + 0.01:
            raise HTTPException(
                400,
                f"Bakiye yetersiz: kalan {balance['currency']} {balance['remaining']:,.2f}, "
                f"talep {balance['currency']} {amt:,.2f}"
            )
        # alt ref aynı fon altında değilse bağla
        if alt.parent_fund_request_id != fund.id:
            alt.parent_fund_request_id = fund.id
            alt.is_funded = True

    if direction == "in" and alt.parent_fund_request_id != fund.id:
        raise HTTPException(400, "Bu alt referans bu fon havuzuna bağlı değil.")

    td = (transfer_date or _now().strftime("%Y-%m-%d")).strip()

    ft = FundTransfer(
        id=_uuid(),
        fund_request_id=fund.id,
        related_request_id=alt.id,
        direction=direction,
        amount=round(amt, 2),
        vat_rate=vat_pct,
        currency=fund.fund_currency or "TRY",
        exchange_rate_try=rate,
        description=description.strip(),
        transfer_date=td,
        created_by=current_user.id,
        created_at=_now(),
    )
    db.add(ft)
    dir_label = "dağıtım" if direction == "out" else "iade"
    log_activity(
        db, alt.id, "fund_transfer",
        f"Fon {dir_label}: {fund.fund_currency} {amt:,.2f} · {fund.request_no}",
        user_id=current_user.id,
    )
    log_activity(
        db, fund.id, "fund_transfer",
        f"{dir_label.capitalize()}: {fund.fund_currency} {amt:,.2f} · {alt.request_no}",
        user_id=current_user.id,
    )
    db.commit()
    redirect_to = request.headers.get("referer") or f"/requests/{fund.id}"
    return RedirectResponse(url=redirect_to, status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Yeni Talep Oluştur
# ---------------------------------------------------------------------------

@router.get("/api/customer-contacts/{customer_id}", name="customer_contacts_api")
async def get_customer_contacts(
    customer_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Sadece talep oluşturabilen / yönetebilen roller müşteri kontaktlarını çekebilir
    # (e-posta + telefon bilgisi içeriyor → bilgi sızıntısı korunur)
    if current_user.role not in ("admin", "mudur", "yonetici", "asistan", "satinalma", "muhasebe", "muhasebe_muduru") \
       and not current_user.is_gm:
        raise HTTPException(403)
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return JSONResponse([])
    return JSONResponse(customer.contacts)


@router.get("/api/customer-fund-pools/{customer_id}", name="customer_fund_pools_api")
async def get_customer_fund_pools(
    customer_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Müşteriye ait aktif fon havuzları (form'daki alt referans dropdown'ı için)."""
    # Sadece talep oluşturma yetkisi olanlar — fon havuzu seçmek için
    if current_user.role not in ("admin", "mudur", "yonetici", "asistan") and not current_user.is_gm:
        raise HTTPException(403)
    from utils.funds import get_customer_fund_pools as _cfp
    pools = _cfp(customer_id, db)
    return JSONResponse([{
        "id":         p.id,
        "request_no": p.request_no,
        "event_name": p.event_name,
        "currency":   p.fund_currency or "TRY",
    } for p in pools])


@router.get("/new", response_class=HTMLResponse, name="requests_new")
async def requests_new(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_pm_or_admin(current_user, db)
    customers   = db.query(Customer).order_by(Customer.name).all()
    venues      = db.query(Vendor).filter(Vendor.active == True).order_by(Vendor.name).all()
    event_types = db.query(EventType).filter(EventType.active == True).order_by(EventType.sort_order).all()
    services    = db.query(Service).filter(Service.active == True).order_by(Service.category, Service.sort_order, Service.name).all()
    # Group services by category
    services_by_cat: dict = {}
    for svc in services:
        services_by_cat.setdefault(svc.category, []).append(svc.to_dict())
    custom_cats = []
    try:
        from models import CustomCategory
        custom_cats = db.query(CustomCategory).all()
    except Exception:
        pass
    teams = db.query(Team).filter(Team.active == True).order_by(Team.name).all() if current_user.is_gm else []

    return templates.TemplateResponse(
        "requests/form.html",
        {
            "request":          request,
            "current_user":     current_user,
            "req":              None,
            "page_title":       "Yeni Talep Oluştur",
            "customers":        customers,
            "venues":           venues,
            "event_types":      event_types,
            "services_by_cat":  services_by_cat,
            "service_categories": SERVICE_CATEGORIES,
            "tr_cities":        TR_CITIES,
            "request_tabs":     REQUEST_TABS,
            "supplier_types":   SUPPLIER_TYPES,
            "custom_cats":      custom_cats,
            "teams":            teams,
            "show_team_selector": current_user.is_gm,
            "error":            None,
        },
    )


@router.post("/new", name="requests_create")
async def requests_create(
    request: Request,
    client_name:          str = Form(...),
    customer_id:          str = Form(""),
    event_name:           str = Form(...),
    event_type:           str = Form("yi"),   # EventType.code
    cities_json:          str = Form("[]"),
    attendee_count:       str = Form("0"),
    check_in:             str = Form(""),
    check_out:            str = Form(""),
    accom_check_in:       str = Form(""),
    accom_check_out:      str = Form(""),
    quote_deadline:       str = Form(""),
    description:          str = Form(""),
    notes:                str = Form(""),
    items_json:           str = Form("{}"),
    preferred_venues_json: str = Form("[]"),
    contact_person_json:  str = Form("{}"),
    is_funded:            str = Form(""),     # checkbox: "on" veya boş
    funding_source:       str = Form(""),
    parent_fund_request_id: str = Form(""),   # fon havuzu (is_funded=on ise doldurulur)
    action:               str = Form("draft"),  # 'draft' veya 'send'
    team_id:              str = Form(""),       # GM seçimi için
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_pm_or_admin(current_user, db)

    # Müşteri kodu + takım tespiti
    customer_code = "xxx"
    _team_id = current_user.team_id  # varsayılan: creator'ın takımı
    if customer_id:
        cust = db.query(Customer).filter(Customer.id == customer_id).first()
        if cust:
            customer_code = cust.code
            if cust.team_id:
                _team_id = cust.team_id  # müşterinin takımı öncelikli
    # GM ise formdan gelen team_id önceliklidir
    if current_user.is_gm and team_id.strip():
        _team_id = team_id.strip()

    # Resolve event_type_code
    event_type_code = event_type  # already a code like 'yi'

    if action == "send":
        ref_status = "pending"
    elif action == "direct":
        ref_status = "in_progress"
    else:
        ref_status = "draft"
    ref_no = generate_ref_no(db, event_type_code, customer_code, check_in)

    # cities JSON → city string (geriye uyumluluk)
    try:
        cities_list = json.loads(cities_json or "[]")
    except Exception:
        cities_list = []
    city_str = ", ".join(cities_list)

    req = ReqModel(
        id=_uuid(),
        request_no=ref_no,
        client_name=client_name.strip(),
        customer_id=customer_id or None,
        event_name=event_name.strip(),
        event_type=event_type_code,
        city=city_str,
        cities_json=cities_json,
        attendee_count=int(attendee_count) if attendee_count.isdigit() else 0,
        check_in=check_in or None,
        check_out=check_out or None,
        accom_check_in=accom_check_in or None,
        accom_check_out=accom_check_out or None,
        quote_deadline=quote_deadline or None,
        status=ref_status,
        items_json=items_json,
        description=description.strip(),
        notes=notes.strip(),
        preferred_venues_json=preferred_venues_json,
        selected_venues_json="[]",
        contact_person_json=contact_person_json,
        is_funded=(is_funded == "on"),
        funding_source=funding_source.strip(),
        parent_fund_request_id=parent_fund_request_id or None,
        team_id=_team_id,
        created_by=current_user.id,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(req)
    db.flush()

    # --- miceapp suite: draft DEĞİLSE referans oluştur (kaydet/gönder sonrası) ---
    if ref_status != "draft":
        _ensure_reference(db, req, current_user)

    log_activity(
        db, req.id, "request_created",
        f"Referans oluşturuldu: {req.request_no}",
        user_id=current_user.id,
    )
    db.commit()
    return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Detay
# ---------------------------------------------------------------------------

@router.get("/{req_id}", response_class=HTMLResponse, name="requests_detail")
async def requests_detail(
    req_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = (db.query(ReqModel)
             .options(joinedload(ReqModel.budgets), joinedload(ReqModel.invoices))
             .filter(ReqModel.id == req_id)
             .first())
    if not req:
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)

    # Erişim kontrolü — admin/GM/muhasebe_muduru tümünü görür;
    # mudur sadece kendi takımının referanslarını; yonetici alt ağacını; asistan kendininkini;
    # satinalma ve muhasebe iş akışı gereği tüm referansları görür.
    if not current_user.is_gm and current_user.role == "mudur":
        _mudur_team = db.query(Team).filter(Team.id == current_user.team_id).first() if current_user.team_id else None
        if _mudur_team and _mudur_team.is_support_team:
            _member_ids = [u.id for u in db.query(User).filter(
                User.team_id == current_user.team_id, User.active == True).all()]
            if req.created_by not in _member_ids:
                raise HTTPException(403, "Bu referans ekibinize ait değil.")
        elif req.team_id and req.team_id != current_user.team_id:
            raise HTTPException(403, "Bu referans takımınıza ait değil.")
    elif current_user.role == "yonetici":
        sub_ids = _get_subtree_ids(current_user.id, db)
        if req.created_by not in [current_user.id] + sub_ids:
            raise HTTPException(403, "Bu referansa erişim yetkiniz yok.")
        if current_user.team_id and req.team_id and req.team_id != current_user.team_id:
            raise HTTPException(403, "Bu referans takımınıza ait değil.")
    elif current_user.role == "asistan":
        if req.created_by != current_user.id:
            raise HTTPException(403, "Bu referansa erişim yetkiniz yok.")

    # Fon havuzu referansı → özel detay sayfası
    if req.is_fund_pool:
        from models import FundTransfer as _FT, Invoice as _Inv
        from utils.funds import get_fund_balance, get_current_exchange_rate, can_manage_funds
        balance = get_fund_balance(req, db)
        # En yeniden eskiye transferler
        transfers = (db.query(_FT)
                       .filter(_FT.fund_request_id == req.id)
                       .order_by(_FT.transfer_date.desc(), _FT.created_at.desc())
                       .all())
        # Kurulum faturası (en eski "kesilen" fatura — havuz açılışı)
        initial_invoice = (db.query(_Inv)
                             .filter(_Inv.request_id == req.id, _Inv.invoice_type == "kesilen")
                             .order_by(_Inv.created_at.asc())
                             .first())
        # Vendor fund pool: bölme yoluyla gelen child gelen faturalar
        incoming_invoices = []
        if req.fund_pool_type == "vendor":
            incoming_invoices = (db.query(_Inv)
                                   .filter(_Inv.request_id == req.id,
                                           _Inv.parent_invoice_id.isnot(None))
                                   .order_by(_Inv.invoice_date.desc(), _Inv.created_at.desc())
                                   .all())
        # Alt referans isimlerini toplu çek
        alt_ids = {t.related_request_id for t in transfers}
        alt_map = {r.id: r for r in db.query(ReqModel).filter(ReqModel.id.in_(alt_ids)).all()} if alt_ids else {}
        # Bu fona bağlı tüm alt referanslar (transfer olmamış olsa da) — "Fona Bağlı" tablosu için
        alt_refs = (db.query(ReqModel)
                      .filter(ReqModel.parent_fund_request_id == req.id)
                      .order_by(ReqModel.created_at.desc())
                      .all())
        # Transfer modalı için aktif referans listesi:
        # - Customer pool → aynı müşteriye ait aktif refler
        # - Vendor pool  → TÜM aktif refler (vendor fonu herhangi bir referansa pay edilebilir)
        eligible_alt_refs = []
        _base_q = (db.query(ReqModel)
                     .filter(ReqModel.is_fund_pool == False,            # noqa: E712
                             ReqModel.status.notin_(["draft", "cancelled", "closed"])))
        if req.fund_pool_type == "vendor":
            eligible_alt_refs = _base_q.order_by(ReqModel.created_at.desc()).all()
        elif req.customer_id:
            eligible_alt_refs = (_base_q.filter(ReqModel.customer_id == req.customer_id)
                                       .order_by(ReqModel.created_at.desc()).all())
        current_rate = get_current_exchange_rate(req.fund_currency)
        customer = (db.query(Customer).filter(Customer.id == req.customer_id).first()
                    if req.customer_id else None)
        return templates.TemplateResponse(
            "requests/fund_pool_detail.html",
            {
                "request":      request,
                "current_user": current_user,
                "req":          req,
                "page_title":   req.request_no,
                "balance":      balance,
                "transfers":    transfers,
                "alt_map":      alt_map,
                "alt_refs":     alt_refs,
                "eligible_alt_refs": eligible_alt_refs,
                "current_rate": current_rate,
                "can_manage_funds": can_manage_funds(current_user),
                "customer":     customer,
                "initial_invoice": initial_invoice,
                "incoming_invoices": incoming_invoices,
            },
        )

    venues      = db.query(Vendor).filter(Vendor.active == True).all()
    event_types = db.query(EventType).order_by(EventType.sort_order).all()
    et_map      = {et.code: et.label for et in event_types}
    can_edit_status = current_user.role in ("admin", "satinalma")
    # mudur tüm referansları düzenleyebilir; yonetici/asistan sadece kendi talebini
    can_edit_req = (
        current_user.role == "admin" or
        (current_user.role in ("mudur", "yonetici") and
         (req.created_by == current_user.id or current_user.role == "mudur")) or
        (current_user.role == "asistan" and req.created_by == current_user.id)
    )
    # Teklif gönderme ve bütçe onayı: admin, mudur, yonetici (asistan yapamaz)
    can_send_offer    = current_user.role in ("admin", "mudur", "yonetici")
    can_approve_budget = current_user.role in ("admin", "mudur", "yonetici")
    # Bütçeye fiyat girme: asistan dahil tüm PM tarafı
    can_price_budget  = current_user.role in ("admin", "mudur", "yonetici", "asistan")
    # PM kendi talebini direkt yönetiyorsa (in_progress) RFQ ve bütçe oluşturabilir
    can_direct_manage = (
        current_user.role in ("admin", "mudur", "yonetici") and
        req.status in ("in_progress", "venues_contacted", "budget_ready") and
        (req.created_by == current_user.id or current_user.role in ("admin", "mudur"))
    )
    # Bütçe oluşturma/düzenleme: asistan da yapabilir (durum güncelleme/RFQ hariç)
    can_budget_ops = (
        can_direct_manage or (
            current_user.role == "asistan" and
            req.status in ("in_progress", "venues_contacted", "budget_ready")
        )
    )

    # Onay bekleyen kişi bilgisi
    def _find_next_approver(user_id: str | None) -> User | None:
        """Bir kullanıcının zincirindeki ilk mudur'u bul."""
        if not user_id:
            return None
        visited: set = set()
        current = db.query(User).filter(User.id == user_id).first()
        while current and current.manager_id and current.manager_id not in visited:
            visited.add(current.manager_id)
            mgr = db.query(User).filter(User.id == current.manager_id, User.active == True).first()
            if not mgr:
                break
            if mgr.role in ("mudur", "admin"):
                return mgr
            current = mgr
        return db.query(User).filter(User.role == "mudur", User.active == True).first()

    def _find_gm_approver() -> User | None:
        users = db.query(User).filter(User.role == "mudur", User.active == True).all()
        best, best_grade = None, 999
        for u in users:
            if u.org_title and u.org_title.grade < best_grade:
                best_grade = u.org_title.grade
                best = u
        return best or db.query(User).filter(User.role == "mudur", User.active == True).first()

    def _find_muhasebe_muduru() -> User | None:
        return db.query(User).filter(User.role == "muhasebe_muduru", User.active == True).first()

    # Kapama için beklenen onaylayıcı
    closure_pending_approver: User | None = None
    if req.closure_request and req.closure_request.status == "pending_manager":
        closure_pending_approver = _find_next_approver(req.closure_request.submitted_by)
    elif req.closure_request and req.closure_request.status == "pending_gm":
        closure_pending_approver = _find_gm_approver()
    elif req.closure_request and req.closure_request.status == "pending_finance":
        closure_pending_approver = _find_muhasebe_muduru()

    # Bütçeler için beklenen onaylayıcı (pending_manager)
    budget_pending_approvers: dict = {}  # budget_id → User
    for b in req.budgets:
        if b.budget_status == "pending_manager":
            budget_pending_approvers[b.id] = _find_next_approver(req.created_by)

    # venue id → supplier_type map (RFQ filtrelemesi için)
    venues_map = {v.id: {"name": v.name, "city": v.city,
                          "supplier_type": v.supplier_type,
                          "contacts": v.contacts} for v in venues}

    # Her bütçe için rows_by_section + totals hesapla
    _CURR_SYMS = {"TRY": "₺", "EUR": "€", "USD": "$"}

    def _budget_totals(b):
        SECTION_ORDER = ["accommodation", "meeting", "fb", "teknik", "dekor", "transfer", "tasarim", "other"]
        offer_curr  = b.offer_currency or "TRY"
        ex_rates    = b.exchange_rates  # {'EUR': 38.5, 'USD': 32.1}
        offer_rate  = float(ex_rates.get(offer_curr, 1.0) or 1.0) if offer_curr != "TRY" else 1.0
        offer_sym   = _CURR_SYMS.get(offer_curr, offer_curr)

        sec_totals = {}
        cost_ex = sale_ex = vat_total = 0.0
        for row in b.rows:
            if row.get("is_service_fee") or row.get("is_accommodation_tax"):
                continue
            sec      = row.get("section", "other")
            qty      = float(row.get("qty", 1)  or 1)
            nts      = float(row.get("nights", 1) or 1)
            cost     = float(row.get("cost_price", 0) or 0)
            sale     = float(row.get("sale_price", 0) or 0)
            vat      = float(row.get("vat_rate", 0) or 0)
            row_curr = row.get("currency", "TRY") or "TRY"
            row_rate = float(ex_rates.get(row_curr, 1.0) or 1.0) if row_curr != "TRY" else 1.0
            # Her satırı offer_currency'ye çevir: TRY'ye çevir, sonra offer_currency'ye
            # row_curr → TRY: × row_rate; TRY → offer_curr: ÷ offer_rate
            conv = (row_rate / offer_rate) if offer_rate else 1.0
            cost_sub = cost * qty * nts * conv
            sale_sub = sale * qty * nts * conv
            cost_ex  += cost_sub
            sale_ex  += sale_sub
            vat_total += sale_sub * (vat / 100)
            if sec not in sec_totals:
                sec_totals[sec] = {"cost": 0.0, "sale": 0.0}
            sec_totals[sec]["cost"] += cost_sub
            sec_totals[sec]["sale"] += sale_sub
        sf_pct    = float(b.service_fee_pct or 0)
        sf_amount = round(sale_ex * sf_pct / 100, 2)
        sf_vat    = round(sf_amount * 0.20, 2)
        grand     = round(sale_ex + vat_total + sf_amount + sf_vat, 2)  # offer_currency cinsinden
        grand_try = round(grand * offer_rate, 2)                         # TRY cinsinden
        base      = sale_ex + sf_amount
        margin    = round((sale_ex - cost_ex + sf_amount) / base * 100, 1) if base > 0 else 0.0
        # sections listesi: SECTION_ORDER sırasına göre sadece veri olanlar
        ordered_secs = [(s, sec_totals[s]) for s in SECTION_ORDER if s in sec_totals]
        return {
            "cost_ex":        cost_ex,
            "sale_ex":        sale_ex,
            "vat":            vat_total,
            "sf_pct":         sf_pct,
            "sf_amount":      sf_amount,
            "sf_vat":         sf_vat,
            "grand":          grand,       # offer_currency cinsinden
            "grand_try":      grand_try,   # TRY cinsinden (karşılaştırma + alt satır için)
            "margin":         margin,
            "sections":       ordered_secs,
            "offer_currency": offer_curr,
            "offer_sym":      offer_sym,
            "offer_rate":     offer_rate,
        }

    budgets_data = []
    for b in req.budgets:
        rbs = {}
        for row in b.rows:
            if row.get("is_service_fee") or row.get("is_accommodation_tax"):
                continue
            sec = row.get("section", "other")
            rbs.setdefault(sec, []).append(row)
        budgets_data.append({"budget": b, "rows_by_section": rbs, "totals": _budget_totals(b)})

    # Özet sekmesi için tüm benzersiz sectionlar (en az bir bütçede var olanlar)
    all_sections_set = []
    seen = set()
    for bd in budgets_data:
        for sec, _ in bd["totals"]["sections"]:
            if sec not in seen:
                seen.add(sec)
                all_sections_set.append(sec)

    customer = (db.query(Customer).filter(Customer.id == req.customer_id).first()
                if req.customer_id else None)

    # E-posta şablonları — JS'e aktarılacak {slug: {subject_tpl, body_tpl}}
    from models import Settings as SettingsModel
    settings = db.query(SettingsModel).filter(SettingsModel.id == 1).first()
    _email_tpls_raw = db.query(EmailTemplate).filter(EmailTemplate.active == True).all()
    email_templates_json = {
        t.slug: {"subject_tpl": t.subject_tpl, "body_tpl": t.body_tpl}
        for t in _email_tpls_raw
    }
    # Settings değerleri (imza vb.)
    settings_ctx = {
        "company_name":    settings.company_name    if settings else "",
        "company_email":   settings.company_email   if settings else "",
        "company_phone":   settings.company_phone   if settings else "",
        "email_signature": settings.email_signature if settings else "",
    }

    # Email taslakları için bütçe + venue kontakt bilgileri
    # İsim bazlı fallback lookup için: {normalize(name): contacts}
    _venues_by_name = {
        v["name"].strip().lower(): v.get("contacts", []) or []
        for v in venues_map.values()
    }

    budgets_json = []
    for b in req.budgets:
        contacts = []
        if b.venue_id and b.venue_id in venues_map:
            contacts = venues_map[b.venue_id].get("contacts", []) or []
        elif b.venue_name:
            # venue_id bağlantısı yoksa isme göre eşleştir
            contacts = _venues_by_name.get(b.venue_name.strip().lower(), [])
        budgets_json.append({
            "id":         b.id,
            "venue_name": b.venue_name or "",
            "venue_id":   b.venue_id or "",
            "contacts":   contacts,
            "status":     b.budget_status,
        })

    # ── Finansal veriler ──
    approved_invoices    = [inv for inv in (req.invoices or []) if inv.status == "approved"]
    pending_invoices     = [inv for inv in (req.invoices or []) if inv.status == "pending"]
    gm_approved_invoices = [inv for inv in (req.invoices or []) if inv.status == "gm_approved"]
    rejected_invoices    = [inv for inv in (req.invoices or []) if inv.status == "rejected"]
    # Kar/zarar hesabına: onaylanmış (approved), kesilecek (gm_approved) ve eski "active" dahildir.
    # mudur_approved ve pending henüz GM onayından geçmediği için hariç tutulur.
    # Bölünmüş parent fatura (is_split_parent=True) çift sayılmasın diye dışarıda.
    active_invoices = [inv for inv in (req.invoices or [])
                       if inv.status in ("approved", "gm_approved", "active")
                       and not inv.is_split_parent]

    invoice_ciro     = (sum(inv.amount for inv in active_invoices if inv.invoice_type == "kesilen")
                      - sum(inv.amount for inv in active_invoices if inv.invoice_type == "iade_kesilen"))
    invoice_komisyon = sum(inv.amount for inv in active_invoices if inv.invoice_type == "komisyon")
    invoice_maliyet  = (sum(inv.amount for inv in active_invoices if inv.invoice_type == "gelen")
                      - sum(inv.amount for inv in active_invoices if inv.invoice_type == "iade_gelen"))
    # Net maliyet: sadece gelen faturalar (komisyon artık kar'a direkt ekleniyor, maliyet düşümü değil)
    invoice_net_maliyet = invoice_maliyet
    # Kar = kesilen fatura geliri + komisyon geliri − gelen fatura maliyeti
    invoice_kar      = invoice_ciro + invoice_komisyon - invoice_net_maliyet

    # Belgesiz gelir/gider → ciro ve kar'a dahil et (HBF öncesi)
    from models import UndocumentedEntry as _UE
    _undoc = req.undocumented_entries or []
    _undoc_gelir = round(sum(e.amount for e in _undoc if e.entry_type == "gelir"), 2)
    _undoc_gider = round(sum(e.amount for e in _undoc if e.entry_type == "gider"), 2)
    invoice_ciro = round(invoice_ciro + _undoc_gelir - _undoc_gider, 2)
    invoice_kar  = round(invoice_kar  + _undoc_gelir - _undoc_gider, 2)

    # Fon transferleri → ciroya dahil et (KDV hariç TRY karşılığı)
    # out = fondan ref'e (gelir ekler), in = ref'ten fona (gelir çıkarır)
    from models import FundTransfer as _FT
    fund_transfers = (db.query(_FT)
                        .filter(_FT.related_request_id == req.id)
                        .order_by(_FT.transfer_date.desc(), _FT.created_at.desc())
                        .all())
    fund_in_total  = 0.0   # out direction — ref'e giren (gelir)
    fund_out_total = 0.0   # in direction — ref'ten çıkan (iade)
    for t in fund_transfers:
        # TRY cinsinden, KDV hariç
        v = t.amount_try_excl_vat
        if t.direction == "out":
            fund_in_total += v
        elif t.direction == "in":
            fund_out_total += v
    fund_net_ciro = round(fund_in_total - fund_out_total, 2)
    invoice_ciro  = round(invoice_ciro + fund_net_ciro, 2)
    invoice_kar   = round(invoice_kar  + fund_net_ciro, 2)

    # Fon havuzu referansı bilgisi (alt referansın bağlı olduğu)
    parent_fund = None
    if req.parent_fund_request_id:
        parent_fund = db.query(ReqModel).filter(ReqModel.id == req.parent_fund_request_id).first()

    confirmed_budget = None
    for b in req.budgets:
        if b.id == req.confirmed_budget_id:
            confirmed_budget = b
            break
    budget_sale_excl = confirmed_budget.grand_sale_excl_vat if confirmed_budget else 0.0
    budget_cost_excl = confirmed_budget.grand_cost_excl_vat if confirmed_budget else 0.0

    can_manage_invoices  = current_user.role in ("admin", "muhasebe_muduru", "muhasebe") or current_user.is_gm
    can_manage_undoc     = current_user.role in ("admin", "muhasebe_muduru", "muhasebe") or current_user.is_gm
    # Limit tabanlı zincirleme onay: approver veya hiyerarşik üstü onaylayabilir
    def _above_in_chain(candidate_id: str, subordinate_id: str) -> bool:
        seen: set = set()
        u = db.query(User).filter(User.id == subordinate_id).first()
        depth = 0
        while u and u.manager_id and depth < 10:
            if u.manager_id in seen:
                break
            seen.add(u.manager_id)
            if u.manager_id == candidate_id:
                return True
            u = db.query(User).filter(User.id == u.manager_id).first()
            depth += 1
        return False

    def _can_approve_inv(inv) -> bool:
        _user_is_gm = (
            current_user.role == "admin" or
            bool(getattr(current_user.org_title, "grade", None) == 1)
        )
        if current_user.role in ("admin", "muhasebe_muduru") or _user_is_gm:
            return True
        if inv.current_approver_id:
            if current_user.id == inv.current_approver_id:
                return True
            return _above_in_chain(current_user.id, inv.current_approver_id)
        # NULL fallback
        if inv.request and inv.request.created_by == current_user.id:
            return True
        return current_user.role == "mudur"

    approvable_invoice_ids = {
        inv.id for inv in (req.invoices or [])
        if inv.status == "pending" and _can_approve_inv(inv)
    }
    can_approve_invoices = bool(approvable_invoice_ids) or current_user.role in ("admin", "muhasebe_muduru") or current_user.is_gm
    # Adım 2 — Muhasebe keser (approved → final)
    can_cut_invoices     = current_user.role in ("admin", "muhasebe_muduru", "muhasebe")

    # Kapanan dosyada tüm aksiyon izinleri devre dışı (salt görüntüleme)
    if req.status == "closed":
        can_edit_req        = False
        can_edit_status     = False
        can_direct_manage   = False
        can_budget_ops      = False
        can_manage_invoices = False
        can_approve_invoices = False
        can_cut_invoices    = False
        can_manage_undoc    = False
    # Admin referans taşıma için tüm referanslar
    all_requests = []
    if current_user.role == "admin":
        from models import Request as ReqModel2
        all_requests = db.query(ReqModel2).order_by(ReqModel2.created_at.desc()).limit(200).all()

    # ── HBF & Belgesiz ──
    expense_reports      = req.expense_reports or []
    # miceapp suite: HBF onay butonu — sadece gerçekten onaylayabilen görsün (kendi HBF'sini değil)
    from routers.expenses import _can_approve as _hbf_can_approve
    approvable_hbf_ids = {r.id for r in expense_reports if _hbf_can_approve(r, current_user, db)}
    undocumented_entries = _undoc
    undoc_gelir_total    = _undoc_gelir
    undoc_gider_total    = _undoc_gider

    # GM onayından geçmiş HBF giderleri → karlılığa eksi etki (KDV hariç)
    # (onaylandi=muhasebe bekliyor, kapandi=ödendi; "approved" eski kayıtlar)
    hbf_approved_total = round(
        sum(r.grand_excl_vat for r in expense_reports
            if r.status in ("onaylandi", "kapandi", "approved")), 2
    )
    # Gerçek kar = fatura karı − onaylanan HBF giderleri
    invoice_kar = round(invoice_kar - hbf_approved_total, 2)
    from datetime import date as _date
    today = _date.today().strftime("%Y-%m-%d")

    # ── Kütüphane — aktivite + belgeler birleşik timeline ──
    from models import (
        ActivityLog as _AL, RequestDocument as _RD,
        ACTIVITY_EVENT_ICONS as _AEI, ACTIVITY_EVENT_COLORS as _AEC,
    )
    activity_logs = (db.query(_AL)
                     .filter(_AL.request_id == req_id)
                     .order_by(_AL.created_at.desc())
                     .all())
    req_documents = (db.query(_RD)
                     .filter(_RD.request_id == req_id)
                     .order_by(_RD.created_at)
                     .all())

    # Belgeler zaten aktivite logundan tetiklenerek kaydediliyor;
    # timeline = aktivite logu + belge kayıtları birleşik, eski→yeni sırada
    timeline = []
    for al in activity_logs:
        timeline.append({
            "kind":       "log",
            "icon":       al.icon,
            "color":      al.color,
            "title":      al.title,
            "detail":     al.detail,
            "user":       al.user,
            "created_at": al.created_at,
            "id":         al.id,
        })
    for doc in req_documents:
        timeline.append({
            "kind":       "doc",
            "icon":       "bi-file-earmark-arrow-down",
            "color":      "info",
            "title":      doc.doc_name,
            "detail":     f"{doc.type_label} · {doc.size_display}",
            "user":       doc.uploader,
            "created_at": doc.created_at,
            "id":         doc.id,
        })
    # miceapp suite: en üstte en son işlem (yeniden eskiye)
    timeline.sort(key=lambda x: x["created_at"], reverse=True)

    return templates.TemplateResponse(
        "requests/detail.html",
        {
            "request":          request,
            "current_user":     current_user,
            "req":              req,
            "page_title":       req.request_no,
            "statuses":         REQUEST_STATUSES,
            "venues":           venues,
            "venues_map":       venues_map,
            "event_types":      event_types,
            "et_map":           et_map,
            "can_edit_status":   can_edit_status,
            "can_edit_req":      can_edit_req,
            "can_send_offer":    can_send_offer,
            "can_approve_budget": can_approve_budget,
            "can_price_budget":  can_price_budget,
            "can_direct_manage": can_direct_manage,
            "can_budget_ops":    can_budget_ops,
            "closure_pending_approver":  closure_pending_approver,
            "budget_pending_approvers":  budget_pending_approvers,
            "request_tabs":     REQUEST_TABS,
            "budgets_data":     budgets_data,
            "all_sections":     all_sections_set,
            "customer":         customer,
            "budgets_json":     budgets_json,
            # Finansal
            "active_invoices":        active_invoices,
            "pending_invoices":       pending_invoices,
            "gm_approved_invoices":   gm_approved_invoices,
            "rejected_invoices":      rejected_invoices,
            "invoice_ciro":          round(invoice_ciro, 2),
            "invoice_komisyon":      round(invoice_komisyon, 2),
            "invoice_maliyet":       round(invoice_maliyet, 2),
            "invoice_net_maliyet":   round(invoice_net_maliyet, 2),
            "invoice_kar":           round(invoice_kar, 2),
            "budget_sale_excl":  budget_sale_excl,
            "budget_cost_excl":  budget_cost_excl,
            "can_manage_invoices":      can_manage_invoices,
            "can_approve_invoices":     can_approve_invoices,
            "approvable_invoice_ids":   approvable_invoice_ids,
            "can_cut_invoices":         can_cut_invoices,
            "can_manage_undoc":      can_manage_undoc,
            "all_requests":          all_requests,
            "email_templates_json":  email_templates_json,
            "settings_ctx":          settings_ctx,
            "hbf_approved_total":      hbf_approved_total,
            # HBF & Belgesiz
            "expense_reports":        expense_reports,
            "approvable_hbf_ids":     approvable_hbf_ids,
            "undocumented_entries":   undocumented_entries,
            "undoc_gelir_total":      undoc_gelir_total,
            "undoc_gider_total":      undoc_gider_total,
            # Fon transferleri (alt referans görünümü)
            "fund_transfers":         fund_transfers,
            "fund_in_total":          round(fund_in_total, 2),
            "fund_out_total":         round(fund_out_total, 2),
            "fund_net_ciro":          fund_net_ciro,
            "parent_fund":            parent_fund,
            "can_manage_funds":       (lambda u: u.role in ("admin", "muhasebe_muduru") or u.is_gm)(current_user),
            "today":                  today,
            # Talepler (kütüphanenin üstünde) — PrepaymentRequest ilişkisi modelde yok, direkt query
            "req_invoices":    sorted(req.invoices or [], key=lambda x: x.created_at, reverse=True),
            "req_prepayments": sorted(
                db.query(PrepaymentRequest).filter(PrepaymentRequest.request_id == req.id).all(),
                key=lambda x: x.requested_at, reverse=True,
            ),
            "req_hbfs":        sorted(expense_reports, key=lambda x: x.created_at, reverse=True),
            # Kütüphane
            "timeline":               timeline,
            "req_documents":          req_documents,
            # Operasyon Ajanı modülü
            "oa_module":  _get_oa_module(req.id, db),
            "oa_active":  _get_oa_module(req.id, db) is not None,
        },
    )


# ---------------------------------------------------------------------------
# Düzenleme
# ---------------------------------------------------------------------------

@router.get("/{req_id}/edit", response_class=HTMLResponse, name="requests_edit")
async def requests_edit(
    req_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_pm_or_admin(current_user)
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)

    # Admin ve mudur her talebi düzenleyebilir; yonetici/asistan sadece kendi talebini
    if current_user.role not in ("admin", "mudur") and req.created_by != current_user.id:
        return RedirectResponse(url=f"/requests/{req_id}", status_code=status.HTTP_302_FOUND)

    customers   = db.query(Customer).order_by(Customer.name).all()
    venues      = db.query(Vendor).filter(Vendor.active == True).order_by(Vendor.name).all()
    event_types = db.query(EventType).filter(EventType.active == True).order_by(EventType.sort_order).all()
    services    = db.query(Service).filter(Service.active == True).order_by(Service.category, Service.sort_order, Service.name).all()
    services_by_cat: dict = {}
    for svc in services:
        services_by_cat.setdefault(svc.category, []).append(svc.to_dict())
    teams = db.query(Team).filter(Team.active == True).order_by(Team.name).all() if current_user.is_gm else []

    return templates.TemplateResponse(
        "requests/form.html",
        {
            "request":          request,
            "current_user":     current_user,
            "req":              req,
            "page_title":       f"{req.request_no} — Düzenle",
            "customers":        customers,
            "venues":           venues,
            "event_types":      event_types,
            "services_by_cat":  services_by_cat,
            "service_categories": SERVICE_CATEGORIES,
            "tr_cities":        TR_CITIES,
            "request_tabs":     REQUEST_TABS,
            "supplier_types":   SUPPLIER_TYPES,
            "custom_cats":      [],
            "teams":            teams,
            "show_team_selector": current_user.is_gm,
            "error":            None,
        },
    )


@router.post("/{req_id}/edit", name="requests_update")
async def requests_update(
    req_id: str,
    request: Request,
    client_name:          str = Form(...),
    customer_id:          str = Form(""),
    event_name:           str = Form(...),
    event_type:           str = Form("yi"),
    cities_json:          str = Form("[]"),
    attendee_count:       str = Form("0"),
    check_in:             str = Form(""),
    check_out:            str = Form(""),
    accom_check_in:       str = Form(""),
    accom_check_out:      str = Form(""),
    quote_deadline:       str = Form(""),
    description:          str = Form(""),
    notes:                str = Form(""),
    items_json:           str = Form("{}"),
    preferred_venues_json: str = Form("[]"),
    contact_person_json:  str = Form("{}"),
    is_funded:            str = Form(""),
    funding_source:       str = Form(""),
    parent_fund_request_id: str = Form(""),
    action:               str = Form("draft"),
    team_id:              str = Form(""),       # GM seçimi için
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_pm_or_admin(current_user)
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)
    if current_user.role not in ("admin", "mudur") and req.created_by != current_user.id:
        return RedirectResponse(url=f"/requests/{req_id}", status_code=status.HTTP_302_FOUND)

    try:
        cities_list = json.loads(cities_json or "[]")
    except Exception:
        cities_list = []

    req.client_name           = client_name.strip()
    req.customer_id           = customer_id or None
    # Takım tespiti: GM ise formdan gelen team_id öncelikli
    if current_user.is_gm and team_id.strip():
        req.team_id = team_id.strip()
    elif customer_id:
        _upd_cust = db.query(Customer).filter(Customer.id == customer_id).first()
        if _upd_cust and _upd_cust.team_id:
            req.team_id = _upd_cust.team_id
        elif not req.team_id:
            req.team_id = current_user.team_id
    elif not req.team_id:
        req.team_id = current_user.team_id
    req.event_name            = event_name.strip()
    req.event_type            = event_type
    req.cities_json           = cities_json
    req.city                  = ", ".join(cities_list)
    req.attendee_count        = int(attendee_count) if attendee_count.isdigit() else 0
    req.check_in              = check_in or None
    req.check_out             = check_out or None
    req.accom_check_in        = accom_check_in or None
    req.accom_check_out       = accom_check_out or None
    req.quote_deadline        = quote_deadline or None
    req.description           = description.strip()
    req.notes                 = notes.strip()
    req.items_json            = items_json
    req.preferred_venues_json = preferred_venues_json
    req.contact_person_json   = contact_person_json
    req.is_funded             = (is_funded == "on")
    req.funding_source        = funding_source.strip()
    req.parent_fund_request_id = parent_fund_request_id or None
    req.updated_at            = _now()

    went_pending = False
    if action == "send" and req.status == "draft":
        req.status   = "pending"
        went_pending = True
    elif action == "direct" and req.status == "draft":
        req.status = "in_progress"

    # miceapp suite: draft değilse referans oluştur (idempotent) — taslak gönderilince de tetiklenir
    if req.status != "draft":
        _ensure_reference(db, req, current_user)

    db.commit()

    # Bildirim: tüm satinalma kullanıcılarına yeni referans
    if went_pending:
        from utils.notifications import create_notification
        satinalma_users = db.query(User).filter(
            User.role == "satinalma", User.active == True  # noqa: E712
        ).all()
        for eu in satinalma_users:
            create_notification(
                db,
                user_id    = eu.id,
                notif_type = "new_request",
                title      = f"Yeni referans — {req.request_no}",
                message    = f"{req.event_name} ({req.client_name or ''})",
                link       = f"/requests/{req_id}",
                ref_id     = req_id,
            )
        db.commit()

    return RedirectResponse(url=f"/requests/{req_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Durum güncelleme (Satın Alma)
# ---------------------------------------------------------------------------

@router.post("/{req_id}/status", name="requests_update_status")
async def requests_update_status(
    req_id: str,
    new_status: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)

    # Satın Alma/Admin: her duruma geçebilir
    # PM direkt yönetim: sadece kendi talebi ve belirli statüler
    is_satinalma_or_admin = current_user.role in ("admin", "satinalma")
    is_pm_direct = (
        current_user.role in ("mudur", "yonetici") and
        (req.created_by == current_user.id or current_user.role == "mudur") and
        req.status in ("in_progress", "venues_contacted", "budget_ready")
    )
    if not is_satinalma_or_admin and not is_pm_direct:
        raise HTTPException(status_code=403, detail="Yetkisiz erişim.")

    old_status = req.status
    req.status     = new_status
    req.updated_at = _now()
    log_activity(
        db, req_id, "status_change",
        f"Durum güncellendi: {REQUEST_STATUS_LABELS.get(old_status, old_status)} → {REQUEST_STATUS_LABELS.get(new_status, new_status)}",
        user_id=current_user.id,
    )
    db.commit()
    return RedirectResponse(url=f"/requests/{req_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Post-Offer Workflow: Teklif Gönderildi / Onay / İptal / Revizyon / Tamamla
# ---------------------------------------------------------------------------

@router.post("/{req_id}/offer-sent", name="requests_offer_sent")
async def requests_offer_sent(
    req_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Teklif müşteriye gönderildi → status: offer_sent
    fetch() ile AJAX olarak da çağrılabilir (redirect'i görmez, 200/302 döner).
    """
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)
    # Onaylı bütçesi olan her non-terminal statüden offer_sent'e geçilebilir
    allowed = ("in_progress", "venues_contacted", "budget_ready", "offer_sent", "revision", "completed")
    if req.status in allowed and req.status != "offer_sent":
        req.status     = "offer_sent"
        req.updated_at = _now()
        db.commit()
    return RedirectResponse(url=f"/requests/{req_id}#tab-summary", status_code=status.HTTP_302_FOUND)


@router.post("/{req_id}/confirm", name="requests_confirm")
async def requests_confirm(
    req_id: str,
    budget_id: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Müşteri onayladı → seçilen budget 'confirmed', diğerleri değişmez, request 'confirmed'"""
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)

    revise_budget_id = None
    if budget_id:
        bgt = db.query(Budget).filter(Budget.id == budget_id, Budget.request_id == req_id).first()
        if bgt:
            bgt.budget_status = "confirmed"
            # Onay anı fiyat snapshot'ı
            import copy
            snap = {
                "ts":      _now().strftime("%d.%m.%Y %H:%M"),
                "label":   "Müşteri Onay Anı",
                "trigger": "confirm",
                "rows":    copy.deepcopy(bgt.rows),
            }
            snaps = bgt.price_snapshots
            snaps.append(snap)
            bgt.price_snapshots_json = json.dumps(snaps, ensure_ascii=False)
            revise_budget_id = bgt.id
        req.confirmed_budget_id = budget_id
    req.status       = "confirmed"
    req.confirmed_at = _now()
    req.updated_at   = _now()
    db.commit()
    redirect_url = f"/requests/{req_id}?show_revise={revise_budget_id}#tab-summary" if revise_budget_id else f"/requests/{req_id}#tab-summary"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)


@router.post("/{req_id}/reopen", name="requests_reopen")
async def requests_reopen(
    req_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Değişiklik talebi: SADECE GM/admin onaylanmış referansı tekrar düzenlenebilir yapar.
    Onaylı referans kilitlidir; değişiklik için GM/admin bu butonla kilidi açar."""
    if not (current_user.is_gm or current_user.role in ("admin", "super_admin")):
        raise HTTPException(status_code=403, detail="Sadece Genel Müdür veya Admin değişiklik talebinde bulunabilir.")
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)
    if req.status == "confirmed":
        if req.confirmed_budget_id:
            bgt = db.query(Budget).filter(Budget.id == req.confirmed_budget_id).first()
            if bgt:
                bgt.budget_status = "approved"
        req.confirmed_budget_id = None
        req.status = "budget_ready"
        req.updated_at = _now()
        log_activity(db, req.id, "request_reopened",
                     f"Değişiklik talebi: {current_user.name} onaylı referansı tekrar açtı",
                     user_id=current_user.id)
        db.commit()
    return RedirectResponse(url=f"/requests/{req_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{req_id}/cancel-job", name="requests_cancel_job")
async def requests_cancel_job(
    req_id: str,
    reason: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """İşi iptal et → request 'cancelled', onaylı/confirmed bütçeler de cancelled"""
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req or req.status == "cancelled":
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)

    req.status              = "cancelled"
    req.cancellation_reason = reason.strip()
    req.updated_at          = _now()

    for b in req.budgets:
        if b.budget_status in ("approved", "confirmed", "pending_manager", "draft_manager"):
            b.budget_status = "cancelled"
    db.commit()
    return RedirectResponse(url=f"/requests/{req_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{req_id}/postpone", name="requests_postpone")
async def requests_postpone(
    req_id: str,
    reason: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ertelendi → request 'postponed', aktif bütçeler olduğu gibi kalır"""
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req or req.status in ("cancelled", "completed", "postponed"):
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)

    req.status              = "postponed"
    req.cancellation_reason = reason.strip()
    req.updated_at          = _now()
    db.commit()
    return RedirectResponse(url=f"/requests/{req_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{req_id}/revision", name="requests_revision")
async def requests_revision(
    req_id: str,
    new_check_in:       str = Form(""),
    new_check_out:      str = Form(""),
    new_accom_check_in:  str = Form(""),
    new_accom_check_out: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Tarih değişikliği → request 'revision', onaylı/confirmed bütçeler draft_satinalma'e döner"""
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)

    if new_check_in:
        req.check_in  = new_check_in
        req.city      = req.city  # unchanged
    if new_check_out:
        req.check_out = new_check_out
    if new_accom_check_in:
        req.accom_check_in  = new_accom_check_in
    if new_accom_check_out:
        req.accom_check_out = new_accom_check_out

    req.status         = "revision"
    req.revision_count = (req.revision_count or 0) + 1
    req.updated_at     = _now()

    for b in req.budgets:
        if b.budget_status in ("approved", "confirmed"):
            b.budget_status = "draft_satinalma"
    db.commit()
    return RedirectResponse(url=f"/requests/{req_id}#tab-summary", status_code=status.HTTP_302_FOUND)


@router.post("/{req_id}/complete", name="requests_complete")
async def requests_complete(
    req_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Etkinlik tamamlandı → request 'completed'"""
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req or req.status not in ("confirmed",):
        return RedirectResponse(url=f"/requests/{req_id}", status_code=status.HTTP_302_FOUND)
    req.status     = "completed"
    req.updated_at = _now()
    db.commit()
    return RedirectResponse(url=f"/requests/{req_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Tüm draft_satinalma bütçeleri manager'a gönder
# ---------------------------------------------------------------------------

@router.post("/{req_id}/send-all-to-manager", name="requests_send_all_to_manager")
async def requests_send_all_to_manager(
    req_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_satinalma_or_admin(current_user)
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(404)

    from models import Budget as BudgetModel
    drafts = db.query(BudgetModel).filter(
        BudgetModel.request_id == req_id,
        BudgetModel.budget_status == "draft_satinalma",
    ).all()

    for b in drafts:
        b.budget_status = "pending_manager"

    if drafts:
        db.commit()

    # Manager bildirimi: talebi oluşturan PM'e mailto: hazırla
    manager_email = ""
    if req.created_by:
        pm = db.query(User).filter(User.id == req.created_by).first()
        if pm and pm.email:
            manager_email = pm.email

    redirect_url = f"/requests/{req_id}"
    if manager_email:
        redirect_url += f"?manager_notified={manager_email}"

    return RedirectResponse(
        url=redirect_url,
        status_code=status.HTTP_302_FOUND,
    )


# ---------------------------------------------------------------------------
# Müşteri teklif önizleme sayfası
# ---------------------------------------------------------------------------

SECTION_LABELS_TR = {
    "accommodation": "Konaklama",
    "meeting":       "Toplantı / Salon",
    "fb":            "F&B (Yiyecek & İçecek)",
    "teknik":        "Teknik Ekipman",
    "dekor":         "Dekor / Süsleme",
    "transfer":      "Transfer & Ulaşım",
    "tasarim":       "Tasarım & Basılı Malzeme",
    "other":         "Diğer Hizmetler",
}
SECTIONS_ORDER_PREVIEW = [
    "accommodation", "meeting", "fb",
    "teknik", "dekor", "transfer", "tasarim", "other",
]


def _preview_budget_data(budget, vat_mode: str = "exclusive"):
    """Bütçe satırlarını önizleme için hazırlar (sadece satış fiyatı)."""
    currency  = (budget.offer_currency or "TRY").upper()
    rate      = budget.rate_to_try(currency)
    syms      = {"TRY": "₺", "EUR": "€", "USD": "$"}
    sym       = syms.get(currency, currency)

    sections = {}
    sf_sale = sf_vat = 0.0
    grand_sale = grand_vat = 0.0

    for row in budget.rows:
        if row.get("is_accommodation_tax"):
            continue
        if row.get("is_service_fee"):
            sf_pct  = float(budget.service_fee_pct or 0)
            # hesap budget'ta tutuldu, satır değerlerinden al
            sale  = float(row.get("sale_price", 0) or 0)
            qty   = float(row.get("qty", 1) or 1)
            nts   = float(row.get("nights", 1) or 1)
            row_currency = row.get("currency", "TRY") or "TRY"
            row_rate = budget.rate_to_try(row_currency)
            conv  = (row_rate / rate) if rate else 1.0
            sf_sale += sale * qty * nts * conv
            sf_vat  += sf_sale * (float(row.get("vat_rate", 0) or 0) / 100)
            continue

        sec  = row.get("section", "other")
        qty  = float(row.get("qty", 1) or 1)
        nts  = float(row.get("nights", 1) or 1)
        sale = float(row.get("sale_price", 0) or 0)
        vat  = float(row.get("vat_rate", 0) or 0)
        row_currency = row.get("currency", "TRY") or "TRY"
        row_rate = budget.rate_to_try(row_currency)
        conv   = (row_rate / rate) if rate else 1.0
        sale_sub = sale * qty * nts * conv
        vat_sub  = sale_sub * (vat / 100)

        if sec not in sections:
            sections[sec] = {"label": SECTION_LABELS_TR.get(sec, sec), "rows": [], "subtotal": 0.0, "subtotal_vat": 0.0}
        sections[sec]["rows"].append({
            "description": row.get("description") or "",
            "unit":        row.get("unit") or "",
            "qty":         qty,
            "nights":      nts,
            "sale_price":  sale * conv,
            "vat_rate":    vat,
            "sale_total":  sale_sub,
            "vat_total":   vat_sub,
            "notes":       row.get("notes") or "",
            "is_accommodation": sec == "accommodation",
        })
        sections[sec]["subtotal"]     += sale_sub
        sections[sec]["subtotal_vat"] += vat_sub
        grand_sale += sale_sub
        grand_vat  += vat_sub

    # Sıralı section listesi
    ordered = []
    for s in SECTIONS_ORDER_PREVIEW:
        if s in sections:
            ordered.append(sections[s])
    # Özel kategoriler (sıra dışı)
    for s, v in sections.items():
        if s not in SECTIONS_ORDER_PREVIEW:
            ordered.append(v)

    sf_total = sf_sale + sf_vat
    return {
        "sections":   ordered,
        "grand_sale": grand_sale,
        "grand_vat":  grand_vat,
        "grand_total": grand_sale + grand_vat,
        "sf_sale":    sf_sale,
        "sf_vat":     sf_vat,
        "sf_total":   sf_total,
        "final_total": grand_sale + grand_vat + sf_total,
        "currency":   currency,
        "sym":        sym,
    }


@router.get("/{req_id}/preview", response_class=HTMLResponse, name="requests_preview")
async def requests_preview(
    req_id:    str,
    request:   Request,
    budget_id: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Müşteriye gösterilecek teklif önizleme sayfası (sidebar yok, baskıya uygun)."""
    from models import Settings as SettingsModel
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(404)

    approved_budgets = [
        b for b in req.budgets
        if b.budget_status in ("approved", "confirmed")
    ]
    if not approved_budgets:
        raise HTTPException(404, "Bu talep için onaylı bütçe bulunamadı.")

    # Seçili bütçe
    budget = next((b for b in approved_budgets if b.id == budget_id), approved_budgets[0])

    customer = (db.query(Customer).filter(Customer.id == req.customer_id).first()
                if req.customer_id else None)
    settings = db.query(SettingsModel).filter(SettingsModel.id == 1).first()
    manager  = db.query(User).filter(User.id == req.created_by).first() if req.created_by else None

    preview_data_excl = _preview_budget_data(budget, "exclusive")
    preview_data_incl = _preview_budget_data(budget, "inclusive")

    # Müşteri template bilgisi (export butonu için)
    cust_cfg          = customer.excel_config if customer else {}
    has_cust_template = bool(
        cust_cfg.get("cell_map") and
        (getattr(customer, "excel_template_b64", "") or getattr(customer, "excel_template_path", ""))
    )
    cust_vat_mode     = cust_cfg.get("vat_mode", "exclusive")

    return templates.TemplateResponse("requests/preview.html", {
        "request":       request,
        "current_user":  current_user,
        "req":           req,
        "budget":        budget,
        "customer":      customer,
        "settings":      settings,
        "manager":       manager,
        "approved_budgets": approved_budgets,
        "data_excl":     preview_data_excl,
        "data_incl":     preview_data_incl,
        "has_cust_template": has_cust_template,
        "cust_vat_mode":     cust_vat_mode,
        "page_title":    f"Teklif Önizleme — {req.request_no}",
    })


# Eski /requests/{req_id}/statement endpoint kaldırıldı
# Hesap dökümü artık /budgets/{id}/statement üzerinden yönetiliyor


# ---------------------------------------------------------------------------
# Çoklu bütçe → tek Excel (özet sayfasından export)
# ---------------------------------------------------------------------------

@router.get("/{req_id}/export", name="requests_export")
async def requests_export(
    req_id:  str,
    vat:     str = "exclusive",   # ?vat=exclusive | inclusive
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Talebe bağlı tüm onaylı bütçeleri tek Excel'de birleştirir.
    Her bütçe (mekan) ayrı bir sheet olarak eklenir.
    """
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(404)

    budgets = (
        db.query(Budget)
          .filter(Budget.request_id == req_id,
                  Budget.budget_status.in_(["approved", "confirmed"]))
          .all()
    )
    if not budgets:
        raise HTTPException(404, "Bu talep için onaylı bütçe bulunamadı")

    customer = (db.query(Customer).filter(Customer.id == req.customer_id).first()
                if req.customer_id else None)

    vat_mode = vat if vat in ("exclusive", "inclusive") else "exclusive"
    custom_cats = [{"id": cc.id, "name": cc.name}
                   for cc in db.query(CustomCategory).all()]

    # Excel'de "Hazırlayan:" = talebi oluşturan PM (manager)
    manager_user = db.query(User).filter(User.id == req.created_by).first() if req.created_by else None

    entries = []
    for b in budgets:
        venue_obj = (db.query(Vendor).filter(Vendor.id == b.venue_id).first()
                     if b.venue_id else None)
        entries.append({
            "budget":   b,
            "request":  req,
            "customer": customer,
            "creator":  manager_user,
            "venue":    venue_obj,
        })

    # ── Template & cell_map hazırlığı (HTTPException'ları try dışında) ──────────
    cfg      = customer.excel_config if customer else {}
    cell_map = cfg.get("cell_map") or {}
    b64_data = (getattr(customer, "excel_template_b64", None) or "") if customer else ""
    tpl_path = (customer.excel_template_path or "") if customer else ""

    # Dosya yoksa ama DB'de base64 varsa yeniden oluştur (Railway restart)
    if b64_data and (not tpl_path or not os.path.exists(tpl_path)):
        try:
            import base64 as _b64
            _upload_dir = "static/uploads/customer_templates"
            os.makedirs(_upload_dir, exist_ok=True)
            tpl_path = os.path.join(_upload_dir, f"{customer.id}.xlsx")
            with open(tpl_path, "wb") as _f:
                _f.write(_b64.b64decode(b64_data))
            customer.excel_template_path = tpl_path
            db.commit()
        except Exception as _e:
            print(f"[REQ-EXPORT] b64 restore hatası: {_e}", flush=True)

    has_tpl_file = bool(tpl_path and os.path.exists(tpl_path))
    use_template = bool(has_tpl_file and cell_map)

    print(
        f"[REQ-EXPORT] req={req_id} tpl_path={tpl_path!r} "
        f"has_tpl_file={has_tpl_file} b64_len={len(b64_data)} "
        f"cell_map_keys={list(cell_map.keys())} use_template={use_template}",
        flush=True,
    )

    if has_tpl_file and not cell_map:
        raise HTTPException(
            400,
            "Müşteri şablonu yüklü ama hücre eşleştirmesi yapılmamış. "
            "Müşteri sayfasından 'Şablonu Eşleştir' butonunu kullanın."
        )

    # ── Excel oluştur ────────────────────────────────────────────────────────
    try:
        if False:  # Müşteri template export geçici olarak devre dışı
            pass
        else:
            from excel_export import build_multi_sheet
            output = build_multi_sheet(entries, vat_mode=vat_mode,
                                       custom_sections=custom_cats)
    except Exception as exc:
        import traceback as _tb
        print(f"[EXCEL ERROR] request={req.id}: {exc}\n{_tb.format_exc()}", flush=True)
        raise HTTPException(500, detail="Excel dosyası oluşturulamadı. Lütfen tekrar deneyin.")

    # Dosya adı
    raw_name = (req.event_name or req.request_no or "teklif")[:30]
    ascii_name = unicodedata.normalize("NFKD", raw_name)
    ascii_name = "".join(c for c in ascii_name if ord(c) < 128)
    ascii_name = ascii_name.replace(" ", "_").replace("/", "-").strip("_") or "teklif"
    filename_utf8 = urllib.parse.quote(f"{raw_name}_teklif.xlsx")
    content_disposition = (
        f'attachment; filename="{ascii_name}_teklif.xlsx"; '
        f"filename*=UTF-8''{filename_utf8}"
    )

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition},
    )


# ---------------------------------------------------------------------------
# Silme
# ---------------------------------------------------------------------------

@router.post("/{req_id}/delete", name="requests_delete")
async def requests_delete(
    req_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_pm_or_admin(current_user)
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if req and (req.status == "draft" or current_user.role == "admin"):
        db.delete(req)
        db.commit()
    return RedirectResponse(url="/requests", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Hesap Dökümü Oluştur
# ---------------------------------------------------------------------------

@router.post("/{req_id}/create-statement", name="requests_create_statement")
async def requests_create_statement(
    req_id: str,
    source_budget_id: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Onaylı bütçeden hesap dökümü kopyası oluştur → editöre yönlendir."""
    if current_user.role not in ("admin", "mudur", "yonetici"):
        raise HTTPException(403)

    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(404)

    # Mevcut statement varsa onu aç
    existing = (
        db.query(Budget)
        .filter(Budget.request_id == req_id, Budget.budget_type == "statement")
        .order_by(Budget.updated_at.desc())
        .first()
    )
    if existing:
        return RedirectResponse(url=f"/budgets/{existing.id}/statement", status_code=status.HTTP_302_FOUND)

    # Kaynak bütçeyi bul (belirtilmişse onu al, yoksa confirmed → approved sırasıyla)
    if source_budget_id:
        src = db.query(Budget).filter(Budget.id == source_budget_id, Budget.request_id == req_id).first()
    else:
        src = (
            db.query(Budget)
            .filter(Budget.request_id == req_id, Budget.budget_status == "confirmed", Budget.budget_type == "offer")
            .order_by(Budget.updated_at.desc())
            .first()
        )
        if not src:
            src = (
                db.query(Budget)
                .filter(Budget.request_id == req_id, Budget.budget_status == "approved", Budget.budget_type == "offer")
                .order_by(Budget.updated_at.desc())
                .first()
            )

    if not src:
        return RedirectResponse(url=f"/requests/{req_id}#tab-summary", status_code=status.HTTP_302_FOUND)

    # Satırlara cost_qty = qty başlangıç değeri ata (maliyet ve satış miktarı başta aynı)
    src_rows = src.rows
    for row in src_rows:
        if "cost_qty" not in row:
            row["cost_qty"] = row.get("qty", 1)
    import json as _json
    stmt_rows_json = _json.dumps(src_rows, ensure_ascii=False)

    # Yeni statement bütçesi oluştur
    stmt_budget = Budget(
        id=_uuid(),
        request_id=req_id,
        venue_name=src.venue_name,
        rows_json=stmt_rows_json,
        budget_status="confirmed",
        budget_type="statement",
        service_fee_pct=src.service_fee_pct,
        offer_currency=src.offer_currency or "TRY",
        exchange_rates_json=src.exchange_rates_json or "{}",
        created_by=current_user.id,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(stmt_budget)
    db.commit()
    db.refresh(stmt_budget)
    return RedirectResponse(url=f"/budgets/{stmt_budget.id}/statement", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Cari Kontrol — Referansın tüm mali hareketleri
# ---------------------------------------------------------------------------

@router.get("/{req_id}/cari", response_class=HTMLResponse, name="requests_cari")
async def requests_cari(
    req_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from models import Invoice as _Inv, INVOICE_TYPE_LABELS, ExpenseReport

    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404)

    # Tüm faturalar
    all_invoices = (
        db.query(_Inv)
        .filter(_Inv.request_id == req_id)
        .order_by(_Inv.invoice_date.asc(), _Inv.created_at.asc())
        .all()
    )
    gelirler = [i for i in all_invoices if i.invoice_type in ("kesilen", "komisyon")]
    giderler = [i for i in all_invoices if i.invoice_type in ("gelen", "iade_gelen", "iade_kesilen")]

    # HBF kayıtları
    hbf_list = (
        db.query(ExpenseReport)
        .filter(ExpenseReport.request_id == req_id)
        .order_by(ExpenseReport.created_at.asc())
        .all()
    )

    gelir_total  = round(sum(i.total_amount or 0 for i in gelirler), 2)
    gider_total  = round(sum(i.total_amount or 0 for i in giderler), 2)
    hbf_total    = round(sum(h.grand_total for h in hbf_list), 2)
    net          = round(gelir_total - gider_total - hbf_total, 2)

    return templates.TemplateResponse("requests/cari.html", {
        "request":          request,
        "current_user":     current_user,
        "page_title":       f"Cari Kontrol — {req.request_no}",
        "req":              req,
        "gelirler":         gelirler,
        "giderler":         giderler,
        "hbf_list":         hbf_list,
        "gelir_total":      gelir_total,
        "gider_total":      gider_total,
        "hbf_total":        hbf_total,
        "net":              net,
    })
