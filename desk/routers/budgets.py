"""
E-dem — Bütçe yönetimi router'ı

Workflow:
  E-dem:   oluştur (draft_edem) → manager'a gönder (pending_manager) → revizyonu düzelt
  Manager: satış fiyatı gir (draft_manager) → onayla (approved) / revizyon iste / iptal et
  Admin:   her şeyi görür

Endpoints:
  GET    /budgets                    → liste (role-based)
  GET    /budgets/new                → E-dem: yeni bütçe formu
  POST   /budgets/new                → E-dem: oluştur
  GET    /budgets/{id}               → detay (role-based)
  GET    /budgets/{id}/edit          → E-dem: maliyet düzenle (draft_edem veya revision_requested)
  POST   /budgets/{id}/edit          → E-dem: kaydet
  POST   /budgets/{id}/send-to-manager → E-dem: manager'a gönder
  GET    /budgets/{id}/price         → Manager: satış fiyatı editörü
  POST   /budgets/{id}/price         → Manager: satış fiyatlarını kaydet (draft_manager)
  POST   /budgets/{id}/approve       → Manager: onayla → approved
  POST   /budgets/{id}/request-revision → Manager: revizyon iste
  POST   /budgets/{id}/cancel        → Manager: iptal et
  GET    /budgets/{id}/export        → Manager: Excel export (customer template kullan)
  POST   /budgets/{id}/delete        → E-dem/Admin: sil (sadece draft_edem)
"""

import io
import json
import os

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import (
    Budget, Customer, Request as ReqModel, Service, SERVICE_CATEGORIES, User, _uuid, _now,
)
from routers.library import log_activity, save_document

router = APIRouter(prefix="/budgets", tags=["budgets"])
from templates_config import templates


# ---------------------------------------------------------------------------
# Fiyat geçmişi kaydedici
# ---------------------------------------------------------------------------

FIELD_LABELS = {
    "cost_price":           "Maliyet",
    "sale_price":           "Satış",
    "confirmed_cost_price": "Kesin Maliyet",
}

def _record_price_changes(budget: "Budget", new_rows: list, current_user: "User",
                           fields: list[str]) -> None:
    """Eski ve yeni satırları karşılaştır; değişen fiyatları geçmişe ekle."""
    old_by_id = {}
    for i, r in enumerate(budget.rows):
        key = r.get("id") or str(i)
        old_by_id[key] = r

    changes = []
    for i, new_row in enumerate(new_rows):
        key = new_row.get("id") or str(i)
        old_row = old_by_id.get(key, {})
        desc = new_row.get("service_name") or f"Satır {i+1}"
        for field in fields:
            old_val = round(float(old_row.get(field) or 0), 4)
            new_val = round(float(new_row.get(field) or 0), 4)
            if abs(old_val - new_val) > 0.001:
                changes.append({
                    "row": desc,
                    "field": FIELD_LABELS.get(field, field),
                    "old": old_val,
                    "new": new_val,
                })

    if changes:
        history = budget.price_history or []
        history.append({
            "ts":   _now().strftime("%d.%m.%Y %H:%M"),
            "user": f"{current_user.name} {current_user.surname}".strip() or current_user.email,
            "role": current_user.role,
            "changes": changes,
        })
        budget.price_history_json = json.dumps(history, ensure_ascii=False)

BUDGET_STATUS_LABELS = {
    "draft_edem":         "Taslak (E-dem)",
    "pending_manager":    "Manager Onayında",
    "draft_manager":      "Manager Düzenliyor",
    "approved":           "Onaylandı",
    "confirmed":          "Müşteri Seçti",
    "revision_requested": "Revizyon Bekleniyor",
    "cancelled":          "İptal Edildi",
}
BUDGET_STATUS_COLORS = {
    "draft_edem":         "secondary",
    "pending_manager":    "warning",
    "draft_manager":      "info",
    "approved":           "success",
    "confirmed":          "success",
    "revision_requested": "danger",
    "cancelled":          "dark",
}


def _can_edem_edit(budget: Budget) -> bool:
    return budget.budget_status in ("draft_edem", "revision_requested")


def _can_manager_price(budget: Budget) -> bool:
    return budget.budget_status != "cancelled"


@router.get("", response_class=HTMLResponse, name="budgets_list")
async def budgets_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Budget)
    if current_user.role == "e_dem":
        query = query.filter(Budget.created_by == current_user.id)
    # mudur (Etkinlik Süreç Müdürü) ve GM tüm bütçeleri görür — takım engeli yok
    elif current_user.role in ("yonetici", "asistan"):
        my_req_ids = [
            r.id for r in db.query(ReqModel)
            .filter(ReqModel.created_by == current_user.id)
            .all()
        ]
        query = query.filter(Budget.request_id.in_(my_req_ids))

    budgets = query.order_by(Budget.created_at.desc()).all()
    return templates.TemplateResponse("budgets/list.html", {
        "request":       request,
        "current_user":  current_user,
        "budgets":       budgets,
        "page_title":    "Bütçe Yönetimi" if current_user.role == "e_dem" else "Bütçeler",
        "status_labels": BUDGET_STATUS_LABELS,
        "status_colors": BUDGET_STATUS_COLORS,
    })


def _can_create_budget(user: User) -> bool:
    return user.role in ("admin", "e_dem", "mudur", "yonetici", "asistan")


SECTION_ORDER = ["accommodation", "meeting", "fb", "teknik", "dekor", "transfer", "tasarim", "other"]


def _default_vat(section: str) -> int:
    return 10 if section == "accommodation" else 20


def _calc_nights(date_from: str, date_to: str, section: str = "accommodation") -> int:
    """Gece/gün sayısını hesapla.
    Konaklama: exclusive (08.05→09.05 = 1 gece)
    Diğerleri: inclusive (08.05→09.05 = 2 gün — her iki gün sayılır)
    """
    try:
        from datetime import date as dt
        d1 = dt.fromisoformat(str(date_from))
        d2 = dt.fromisoformat(str(date_to))
        n = (d2 - d1).days
        if section != "accommodation":
            n += 1  # inclusive: başlangıç günü de sayılır
        return max(1, n)
    except Exception:
        return 1


def _items_to_budget_rows(items: dict, req) -> list:
    """Talep items_json dict → bütçe satırı flat list"""
    rows = []
    for section in SECTION_ORDER:
        for item in items.get(section, []):
            date_from = str(item.get("date_from") or "")
            date_to   = str(item.get("date_to")   or "")
            # Tarih yoksa talepten al
            if section == "accommodation":
                date_from = date_from or str(req.accom_check_in or req.check_in or "")
                date_to   = date_to   or str(req.accom_check_out or req.check_out or "")
            elif section == "meeting":
                date_from = date_from or str(req.check_in  or "")
                date_to   = date_to   or str(req.check_out or "")

            nights = _calc_nights(date_from, date_to, section) if date_from and date_to else 1

            row = {
                "section":      section,
                "service_name": item.get("description", ""),
                "unit":         item.get("unit", "Adet"),
                "qty":          float(item.get("qty") or 1),
                "nights":       nights,
                "cost_price":   0,
                "sale_price":   0,
                "vat_rate":     _default_vat(section),
                "service_id":   item.get("service_id"),
                "quotes":       [],
            }
            if section == "accommodation":
                row["accom_in"]  = date_from
                row["accom_out"] = date_to
            elif section == "meeting":
                row["meeting_in"]  = date_from
                row["meeting_out"] = date_to
            rows.append(row)
    return rows


@router.get("/new", response_class=HTMLResponse, name="budgets_new")
async def budgets_new(
    request: Request,
    req_id: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _can_create_budget(current_user):
        raise HTTPException(403)
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first() if req_id else None
    services = db.query(Service).filter(Service.active == True).order_by(Service.category, Service.sort_order, Service.name).all()
    grouped_services: dict = {}
    for svc in services:
        grouped_services.setdefault(svc.category, []).append(svc.to_dict())

    # Talep kalemlerini bütçe satırlarına dönüştür
    initial_rows: list = []
    preferred_venues: list = []
    if req:
        items = req.items or {}
        if any(items.get(s) for s in SECTION_ORDER):
            initial_rows = _items_to_budget_rows(items, req)
        # Tercih edilen mekanları getir (mekan adı seçimi için)
        if req.preferred_venues:
            from models import Venue as VenueModel
            preferred_venues = (
                db.query(VenueModel)
                  .filter(VenueModel.id.in_(req.preferred_venues))
                  .filter(VenueModel.supplier_type.in_(["otel", "etkinlik"]))
                  .order_by(VenueModel.name)
                  .all()
            )

    return templates.TemplateResponse("budgets/editor.html", {
        "request":            request,
        "current_user":       current_user,
        "budget":             None,
        "req":                req,
        "page_title":         "Yeni Bütçe",
        "service_categories": SERVICE_CATEGORIES,
        "grouped_services":   json.dumps(grouped_services, ensure_ascii=False),
        "initial_rows_json":  json.dumps(initial_rows, ensure_ascii=False),
        "preferred_venues":   preferred_venues,
        "offer_currency":     "TRY",
        "exchange_rates":     {},
    })


@router.post("/new", name="budgets_create")
async def budgets_create(
    request: Request,
    req_id:              str = Form(...),
    venue_name:          str = Form(""),
    venue_id:            str = Form(""),
    rows_json:           str = Form("[]"),
    offer_currency:      str = Form("TRY"),
    exchange_rates_json: str = Form("{}"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _can_create_budget(current_user):
        raise HTTPException(403)

    # Satış fiyatlarını sıfırla — sadece E-dem için (PM/Admin direkt yönetimde sıfırlama)
    is_direct_manager = current_user.role in ("mudur", "yonetici", "admin")
    if not is_direct_manager:
        try:
            rows = json.loads(rows_json)
            for row in rows:
                if not row.get("is_service_fee"):
                    row["sale_price"] = 0
            rows_json = json.dumps(rows, ensure_ascii=False)
        except Exception:
            pass

    # PM/Admin direkt yönetimde bütçe direkt approved olur
    initial_status = "approved" if is_direct_manager else "draft_edem"

    budget = Budget(
        id=_uuid(),
        request_id=req_id,
        venue_name=venue_name.strip(),
        venue_id=venue_id.strip() or None,
        rows_json=rows_json,
        budget_status=initial_status,
        created_by=current_user.id,
        created_at=_now(),
        updated_at=_now(),
        offer_currency=offer_currency.upper() or "TRY",
        exchange_rates_json=exchange_rates_json or "{}",
    )
    db.add(budget)
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if req and req.status in ("in_progress", "venues_contacted"):
        req.status = "budget_ready"
        req.updated_at = _now()
    db.commit()
    return RedirectResponse(url=f"/budgets/{budget.id}", status_code=status.HTTP_302_FOUND)


@router.get("/{budget_id}", response_class=HTMLResponse, name="budgets_detail")
async def budgets_detail(
    budget_id: str,
    request: Request,
    back: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        return RedirectResponse(url="/budgets", status_code=status.HTTP_302_FOUND)
    req = db.query(ReqModel).filter(ReqModel.id == budget.request_id).first()
    rows_by_section: dict = {}
    for row in budget.rows:
        sec = row.get("section", "other")
        rows_by_section.setdefault(sec, []).append(row)

    # KDV rate bazlı döküm (detail sayfası alt özet için) — TRY cinsinden
    _ex_rates = budget.exchange_rates  # {'EUR': 38.5, 'USD': 32.1}
    _offer_currency = budget.offer_currency or "TRY"
    vat_by_rate: dict = {}
    for row in budget.rows:
        qty      = float(row.get("qty", 1) or 1)
        nights   = float(row.get("nights", 1) or 1)
        sale     = float(row.get("sale_price", 0) or 0)
        vrate    = float(row.get("vat_rate", 0) or 0)
        currency = row.get("currency", "TRY") or "TRY"
        rate     = 1.0 if currency == "TRY" else float(_ex_rates.get(currency, 1.0) or 1.0)
        if row.get("is_service_fee"):
            qty, nights = 1, 1
        sale_sub = sale * qty * nights * rate  # TRY tutarı
        vat_amt  = round(sale_sub * (vrate / 100), 2)
        if vat_amt > 0 and vrate > 0:
            vat_by_rate[int(vrate)] = round(vat_by_rate.get(int(vrate), 0) + vat_amt, 2)
    vat_by_rate_sorted = sorted(vat_by_rate.items())  # [(10, 30000), (20, 5000)]

    # Geri dön URL: ?back=req_id → referans özet sayfası; yoksa bütçe listesi
    if back:
        back_url = f"/requests/{back}#btpane-summary"
        back_label = "Referansa Dön"
    elif req:
        back_url = f"/requests/{req.id}#btpane-summary"
        back_label = "Referansa Dön"
    else:
        back_url = "/budgets"
        back_label = "Bütçe Listesine Dön"

    # Onay bekleyen kişiyi bul
    pending_approver = None
    if budget.budget_status == "pending_manager" and req:
        visited: set = set()
        current_u = db.query(User).filter(User.id == req.created_by).first() if req.created_by else None
        while current_u and current_u.manager_id and current_u.manager_id not in visited:
            visited.add(current_u.manager_id)
            mgr = db.query(User).filter(User.id == current_u.manager_id, User.active == True).first()
            if not mgr:
                break
            if mgr.role in ("mudur", "admin"):
                pending_approver = mgr
                break
            current_u = mgr
        if not pending_approver:
            pending_approver = db.query(User).filter(User.role == "mudur", User.active == True).first()

    return templates.TemplateResponse("budgets/detail.html", {
        "request":            request,
        "current_user":       current_user,
        "budget":             budget,
        "req":                req,
        "page_title":         f"Bütçe — {budget.venue_name or 'Yeni'}",
        "rows_by_section":    rows_by_section,
        "vat_by_rate":        vat_by_rate_sorted,
        "service_categories": SERVICE_CATEGORIES,
        "can_edem_edit":      _can_edem_edit(budget) and current_user.role in ("admin", "e_dem", "asistan"),
        "can_manager_price":  _can_manager_price(budget) and current_user.role in ("admin", "mudur", "yonetici"),
        "status_label":       BUDGET_STATUS_LABELS.get(budget.budget_status, budget.budget_status),
        "status_color":       BUDGET_STATUS_COLORS.get(budget.budget_status, "secondary"),
        "back_url":           back_url,
        "back_label":         back_label,
        "offer_currency":     _offer_currency,
        "exchange_rates":     _ex_rates,
        "pending_approver":   pending_approver,
    })


@router.get("/{budget_id}/edit", response_class=HTMLResponse, name="budgets_edit")
async def budgets_edit(
    budget_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _can_create_budget(current_user):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        return RedirectResponse(url="/budgets", status_code=status.HTTP_302_FOUND)
    if not _can_edem_edit(budget) and current_user.role not in ("admin", "asistan"):
        return RedirectResponse(url=f"/budgets/{budget_id}", status_code=status.HTTP_302_FOUND)
    req = db.query(ReqModel).filter(ReqModel.id == budget.request_id).first()
    services = db.query(Service).filter(Service.active == True).order_by(Service.category, Service.sort_order, Service.name).all()
    grouped_services: dict = {}
    for svc in services:
        grouped_services.setdefault(svc.category, []).append(svc.to_dict())
    all_request_budgets = (
        db.query(Budget)
        .filter(Budget.request_id == budget.request_id)
        .order_by(Budget.created_at)
        .all()
    )
    preferred_venues = []
    if req and req.preferred_venues:
        from models import Venue as VenueModel
        preferred_venues = (
            db.query(VenueModel)
            .filter(VenueModel.id.in_(req.preferred_venues))
            .filter(VenueModel.supplier_type.in_(["otel", "etkinlik"]))
            .order_by(VenueModel.name)
            .all()
        )
    return templates.TemplateResponse("budgets/editor.html", {
        "request":             request,
        "current_user":        current_user,
        "budget":              budget,
        "req":                 req,
        "page_title":          f"Bütçe Düzenle — {budget.venue_name}",
        "service_categories":  SERVICE_CATEGORIES,
        "grouped_services":    json.dumps(grouped_services, ensure_ascii=False),
        "initial_rows_json":   "[]",
        "preferred_venues":    preferred_venues,
        "all_request_budgets": all_request_budgets,
        "status_labels":       BUDGET_STATUS_LABELS,
        "status_colors":       BUDGET_STATUS_COLORS,
        "offer_currency":      budget.offer_currency or "TRY",
        "exchange_rates":      budget.exchange_rates,
    })


@router.post("/{budget_id}/edit", name="budgets_update")
async def budgets_update(
    budget_id:           str,
    venue_name:          str = Form(""),
    venue_id:            str = Form(""),
    rows_json:           str = Form("[]"),
    next_action:         str = Form(""),
    offer_currency:      str = Form("TRY"),
    exchange_rates_json: str = Form("{}"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _can_create_budget(current_user):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        return RedirectResponse(url="/budgets", status_code=status.HTTP_302_FOUND)

    is_direct_manager = current_user.role in ("mudur", "yonetici", "admin")

    # E-dem satış fiyatı giremez — mevcut sale_price değerlerini sıfırla (PM/Admin hariç)
    try:
        new_rows = json.loads(rows_json)
        if not is_direct_manager:
            for row in new_rows:
                if not row.get("is_service_fee"):
                    row["sale_price"] = 0
        # Fiyat geçmişi: cost_price ve confirmed_cost_price değişimlerini kaydet
        _record_price_changes(budget, new_rows, current_user,
                              ["cost_price", "confirmed_cost_price"])
        rows_json = json.dumps(new_rows, ensure_ascii=False)
    except Exception:
        pass

    budget.venue_name          = venue_name.strip()
    budget.venue_id            = venue_id.strip() or None
    budget.rows_json           = rows_json
    budget.offer_currency      = offer_currency.upper() or "TRY"
    budget.exchange_rates_json = exchange_rates_json or "{}"
    budget.updated_at          = _now()

    if is_direct_manager and budget.budget_status in ("draft_edem", "pending_manager", "revision_requested"):
        # PM/Admin direkt yönetimde kaydetmek = onaylamak
        budget.budget_status = "approved"
    elif next_action == "send_to_manager" and budget.budget_status in ("draft_edem", "revision_requested"):
        budget.budget_status = "pending_manager"

    db.commit()

    if next_action == "send_to_manager":
        return RedirectResponse(url=f"/budgets/{budget_id}", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url=f"/budgets/{budget_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{budget_id}/send-to-manager", name="budgets_send_to_manager")
async def budgets_send_to_manager(
    budget_id: str,
    back: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("admin", "e_dem", "asistan"):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if budget and budget.budget_status in ("draft_edem", "revision_requested"):
        budget.budget_status = "pending_manager"
        budget.updated_at    = _now()
        db.commit()

        # Bildirim: PM fiyatlandırma yapmalı
        req_obj = db.query(ReqModel).filter(ReqModel.id == budget.request_id).first() if budget else None
        if req_obj and req_obj.created_by:
            from utils.notifications import create_notification
            create_notification(
                db,
                user_id    = req_obj.created_by,
                notif_type = "budget_pricing",
                title      = f"Bütçe fiyatlandırması gerekiyor — {budget.venue_name or req_obj.request_no}",
                message    = f"{req_obj.request_no} referansına ait bütçe fiyatlandırmanızı bekliyor.",
                link       = f"/budgets/{budget.id}/price",
                ref_id     = budget.id,
            )
            db.commit()

    # Manager bildirimi için mailto: hazırla
    manager_email = ""
    if budget:
        req = db.query(ReqModel).filter(ReqModel.id == budget.request_id).first()
        if req and req.created_by:
            pm = db.query(User).filter(User.id == req.created_by).first()
            if pm and pm.email:
                manager_email = pm.email

    if back:
        url = f"/requests/{back}#tab-summary"
        if manager_email:
            url = f"/requests/{back}?manager_notified={manager_email}#tab-summary"
        return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)

    url = f"/budgets/{budget_id}"
    if manager_email:
        url += f"?manager_notified={manager_email}"
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/{budget_id}/json", name="budgets_json")
async def budgets_json(
    budget_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bütçe verisini JSON olarak döner (AJAX sekme geçişi için)"""
    from fastapi.responses import JSONResponse
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({
        "id":                  budget.id,
        "venue_name":          budget.venue_name or "",
        "rows":                budget.rows,
        "service_fee_pct":     budget.service_fee_pct or 0,
        "manager_notes":       budget.manager_notes or "",
        "budget_status":       budget.budget_status,
        "offer_currency":      budget.offer_currency or "TRY",
        "exchange_rates":      budget.exchange_rates,
    })


@router.get("/{budget_id}/price", response_class=HTMLResponse, name="budgets_price")
async def budgets_price(
    budget_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("admin", "mudur", "yonetici"):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        return RedirectResponse(url="/budgets", status_code=status.HTTP_302_FOUND)
    req = db.query(ReqModel).filter(ReqModel.id == budget.request_id).first()
    customer = db.query(Customer).filter(Customer.id == req.customer_id).first() if req and req.customer_id else None
    rows_by_section: dict = {}
    for row in budget.rows:
        sec = row.get("section", "other")
        rows_by_section.setdefault(sec, []).append(row)
    services = db.query(Service).filter(Service.active == True).order_by(Service.category, Service.sort_order, Service.name).all()
    grouped_services: dict = {}
    for svc in services:
        grouped_services.setdefault(svc.category, []).append(svc.to_dict())
    # Aynı talebe ait tüm bütçeler (sekme çubuğu için)
    all_request_budgets = (
        db.query(Budget)
        .filter(Budget.request_id == budget.request_id)
        .order_by(Budget.created_at)
        .all()
    )
    # Talepteki tercih edilen mekanlar (dropdown için)
    preferred_venues = []
    if req and req.preferred_venues:
        from models import Venue as VenueModel
        preferred_venues = (
            db.query(VenueModel)
            .filter(VenueModel.id.in_(req.preferred_venues))
            .filter(VenueModel.supplier_type.in_(["otel", "etkinlik"]))
            .order_by(VenueModel.name)
            .all()
        )
    return templates.TemplateResponse("budgets/manager_editor.html", {
        "request":             request,
        "current_user":        current_user,
        "budget":              budget,
        "req":                 req,
        "customer":            customer,
        "page_title":          f"Satış Fiyatı — {budget.venue_name}",
        "rows_by_section":     rows_by_section,
        "status_label":        BUDGET_STATUS_LABELS.get(budget.budget_status, budget.budget_status),
        "status_color":        BUDGET_STATUS_COLORS.get(budget.budget_status, "secondary"),
        "grouped_services":    json.dumps(grouped_services, ensure_ascii=False),
        "all_request_budgets": all_request_budgets,
        "status_labels":       BUDGET_STATUS_LABELS,
        "status_colors":       BUDGET_STATUS_COLORS,
        "preferred_venues":    preferred_venues,
        "offer_currency":      budget.offer_currency or "TRY",
        "exchange_rates":      budget.exchange_rates,
        # Fiyat editörü için bu modlar kapalı
        "revise_mode":         False,
        "statement_mode":      False,
        "statement_status":    None,
        "statement_sent_label": None,
        "customer_email":      (next((c.get("email","") for c in (customer.contacts or []) if c.get("email")), "") or customer.email) if customer else "",
    })


@router.post("/{budget_id}/price", name="budgets_price_save")
async def budgets_price_save(
    budget_id:           str,
    rows_json:           str = Form("[]"),
    service_fee_pct:     str = Form("0"),
    manager_notes:       str = Form(""),
    venue_name:          str = Form(""),
    next_action:         str = Form(""),
    offer_currency:      str = Form(""),
    exchange_rates_json: str = Form("{}"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("admin", "mudur", "yonetici"):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        return RedirectResponse(url="/budgets", status_code=status.HTTP_302_FOUND)

    # Fiyat geçmişi: sale_price değişimlerini kaydet
    try:
        new_rows = json.loads(rows_json)
        _record_price_changes(budget, new_rows, current_user, ["sale_price"])
    except Exception:
        pass

    budget.rows_json           = rows_json
    budget.service_fee_pct     = float(service_fee_pct or 0)
    budget.manager_notes       = manager_notes.strip()
    budget.exchange_rates_json = exchange_rates_json or "{}"
    if venue_name.strip():
        budget.venue_name      = venue_name.strip()
    if offer_currency and offer_currency.upper() in ("TRY", "EUR", "USD"):
        budget.offer_currency  = offer_currency.upper()
    # Onaylanmış bütçe düzenlenince onay durumunu koru
    if budget.budget_status != "approved":
        budget.budget_status   = "draft_manager"
    budget.updated_at          = _now()
    db.commit()

    # Kopyala ve yeni sekmeye git
    if next_action == "copy":
        new_budget = Budget(
            id=_uuid(),
            request_id=budget.request_id,
            venue_name=(budget.venue_name or "Bütçe") + " (Kopya)",
            rows_json=rows_json,
            budget_status="pending_manager",
            service_fee_pct=float(service_fee_pct or 0),
            offer_currency=budget.offer_currency or "TRY",
            exchange_rates_json=exchange_rates_json or budget.exchange_rates_json or "{}",
            created_by=budget.created_by,
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(new_budget)
        db.commit()
        db.refresh(new_budget)
        return RedirectResponse(url=f"/budgets/{new_budget.id}/price", status_code=status.HTTP_302_FOUND)

    return RedirectResponse(url=f"/budgets/{budget_id}/price", status_code=status.HTTP_302_FOUND)


@router.post("/{budget_id}/approve", name="budgets_approve")
async def budgets_approve(
    budget_id: str,
    back: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("admin", "mudur", "yonetici"):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if budget:
        budget.budget_status = "approved"
        budget.updated_at    = _now()
        req = db.query(ReqModel).filter(ReqModel.id == budget.request_id).first()
        if req:
            req.status     = "offer_sent"
            req.updated_at = _now()
            log_activity(
                db, req.id, "budget_approved",
                f"Bütçe fiyatlandırıldı ve onaylandı ({budget.venue_name or 'bütçe'})",
                user_id=current_user.id,
            )
        db.commit()
    if back:
        return RedirectResponse(url=f"/requests/{back}#tab-summary", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url=f"/budgets/{budget_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{budget_id}/mark-offer-sent", name="budgets_mark_offer_sent")
async def budgets_mark_offer_sent(
    budget_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Excel müşteriye gönderildi → talebin durumunu offer_sent yap."""
    if current_user.role not in ("admin", "mudur", "yonetici"):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        from fastapi.responses import JSONResponse
        return JSONResponse({"ok": False, "error": "Bütçe bulunamadı"}, status_code=404)
    req = db.query(ReqModel).filter(ReqModel.id == budget.request_id).first()
    if req and req.status not in ("offer_sent", "confirmed", "completed", "closing", "closed"):
        req.status     = "offer_sent"
        req.updated_at = _now()
        db.commit()
    from fastapi.responses import JSONResponse
    return JSONResponse({"ok": True, "status": req.status if req else ""})


@router.post("/{budget_id}/request-revision", name="budgets_request_revision")
async def budgets_request_revision(
    budget_id:      str,
    revision_notes: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("admin", "mudur", "yonetici"):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if budget:
        budget.budget_status  = "revision_requested"
        budget.revision_notes = revision_notes.strip()
        budget.updated_at     = _now()
        db.commit()

        # Bildirim: E-dem revizyona almalı
        if budget.created_by:
            from utils.notifications import create_notification
            req_obj = db.query(ReqModel).filter(ReqModel.id == budget.request_id).first()
            req_no  = req_obj.request_no if req_obj else ""
            create_notification(
                db,
                user_id    = budget.created_by,
                notif_type = "budget_revision",
                title      = f"Bütçe revizyonu istendi — {budget.venue_name or req_no}",
                message    = revision_notes.strip()[:200] or "PM revizyon talep etti.",
                link       = f"/budgets/{budget_id}/edit",
                ref_id     = budget_id,
            )
            db.commit()

    return RedirectResponse(url=f"/budgets/{budget_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{budget_id}/cancel", name="budgets_cancel")
async def budgets_cancel(
    budget_id: str,
    back: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("admin", "mudur", "yonetici"):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if budget:
        budget.budget_status = "cancelled"
        budget.updated_at    = _now()
        req = db.query(ReqModel).filter(ReqModel.id == budget.request_id).first()
        if req:
            req.status     = "cancelled"
            req.updated_at = _now()
        db.commit()
    if back:
        return RedirectResponse(url=f"/requests/{back}#tab-summary", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url=f"/budgets/{budget_id}", status_code=status.HTTP_302_FOUND)


@router.get("/{budget_id}/export", name="budgets_export")
async def budgets_export(
    budget_id: str,
    vat: str = "exclusive",           # ?vat=exclusive | inclusive
    currency: str = "",               # ?currency=TRY|EUR|USD — override DB değerini
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Excel teklif dosyası indirir.
    - Maliyet/karlılık bilgisi HİÇ gönderilmez (yalnızca satış fiyatları)
    - ?vat=exclusive → KDV hariç göster | ?vat=inclusive → KDV dahil göster
    - ?currency=TRY → DB'deki para birimini override eder (kaydetmeden önce export için)
    - Müşteriye özel template varsa filler.py, yoksa builder.py kullanılır
    """
    if current_user.role not in ("admin", "mudur", "yonetici"):
        raise HTTPException(403)

    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        return RedirectResponse(url="/budgets", status_code=status.HTTP_302_FOUND)

    # Query param ile para birimi override — editörde kaydetmeden export için
    if currency and currency.upper() in ("TRY", "EUR", "USD"):
        budget.offer_currency = currency.upper()

    req      = db.query(ReqModel).filter(ReqModel.id == budget.request_id).first()
    customer = (db.query(Customer)
                  .filter(Customer.id == req.customer_id)
                  .first()
                if req and req.customer_id else None)
    # Excel'de "Hazırlayan:" = talebi oluşturan PM (manager), bütçeyi hazırlayan E-dem değil
    manager_user_id = req.created_by if req else budget.created_by
    creator  = db.query(User).filter(User.id == manager_user_id).first()

    # KDV modu öncelik: query param > customer config > varsayılan 'exclusive'
    # 'mixed' = birim fiyat yabancı para birimi, toplam TRY (kur ile çarpılır)
    cfg = customer.excel_config if customer else {}
    vat_mode = vat if vat in ("exclusive", "inclusive", "mixed") else cfg.get("vat_mode", "exclusive")

    # Özel kategorileri çek
    from models import CustomCategory
    custom_cats = [
        {"id": cc.id, "name": cc.name}
        for cc in db.query(CustomCategory).all()
    ]

    try:
        template_path = customer.excel_template_path if customer else ""
        cell_map      = cfg.get("cell_map") or {}
        b64_data      = getattr(customer, "excel_template_b64", "") if customer else ""

        # Dosya yoksa ama DB'de base64 varsa yeniden yaz (Railway restart sonrası)
        if b64_data and (not template_path or not os.path.exists(template_path)):
            import base64 as _b64
            upload_dir = "static/uploads/customer_templates"
            os.makedirs(upload_dir, exist_ok=True)
            template_path = os.path.join(upload_dir, f"{customer.id}.xlsx")
            with open(template_path, "wb") as _f:
                _f.write(_b64.b64decode(b64_data))
            customer.excel_template_path = template_path
            db.commit()

        use_template = bool(template_path and os.path.exists(template_path) and cell_map)
        print(
            f"[EXPORT] budget={budget_id} "
            f"customer={customer.id if customer else 'None'} "
            f"template_path={template_path!r} "
            f"file_exists={os.path.exists(template_path) if template_path else False} "
            f"b64_len={len(b64_data)} "
            f"cell_map_keys={list(cell_map.keys()) if cell_map else []} "
            f"use_template={use_template}",
            flush=True,
        )

        if False:  # Müşteri template export geçici olarak devre dışı
            pass
        else:
            # ── E-dem standart format ──────────────────────────────────────
            from excel_export import build_standard
            output = build_standard(
                budget=budget,
                request=req,
                customer=customer,
                creator=creator,
                vat_mode=vat_mode,
                custom_sections=custom_cats,
            )
    except Exception as exc:
        import traceback as _tb
        print(f"[EXCEL ERROR] budget={budget_id}: {exc}\n{_tb.format_exc()}", flush=True)
        raise HTTPException(500, detail="Excel dosyası oluşturulamadı. Lütfen tekrar deneyin.")

    # Dosya adı: Türkçe karakterleri ASCII'ye çevir (HTTP header latin-1 sınırı)
    import unicodedata
    raw_name = (budget.venue_name or "teklif")[:30]
    ascii_name = unicodedata.normalize("NFKD", raw_name)
    ascii_name = "".join(c for c in ascii_name if ord(c) < 128)
    ascii_name = ascii_name.replace(" ", "_").replace("/", "-").strip("_") or "teklif"
    filename_ascii = f"{ascii_name}_teklif.xlsx"

    # RFC 5987 ile UTF-8 dosya adı (modern tarayıcılar için)
    import urllib.parse
    filename_utf8 = urllib.parse.quote(f"{raw_name}_teklif.xlsx")
    content_disposition = (
        f'attachment; filename="{filename_ascii}"; '
        f"filename*=UTF-8''{filename_utf8}"
    )

    # Kütüphane: teklif Excel'ini otomatik arşivle
    if req:
        try:
            save_document(
                db=db,
                request_id=req.id,
                buf=output,
                doc_type="teklif",
                file_name=filename_ascii,
                user_id=current_user.id,
            )
            log_activity(
                db=db,
                request_id=req.id,
                event_type="document_added",
                title=f"Teklif Excel indirildi ({budget.venue_name or 'bütçe'})",
                user_id=current_user.id,
            )
            db.commit()
        except Exception as _e:
            import traceback
            print(f"[LIBRARY] teklif kayıt hatası: {_e}\n{traceback.format_exc()}", flush=True)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition},
    )


@router.post("/{budget_id}/delete", name="budgets_delete")
async def budgets_delete(
    budget_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("admin", "e_dem"):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if budget and (budget.budget_status == "draft_edem" or current_user.role == "admin"):
        db.delete(budget)
        db.commit()
    return RedirectResponse(url="/budgets", status_code=status.HTTP_302_FOUND)


@router.post("/{budget_id}/copy-edem", name="budgets_copy_edem")
async def budgets_copy_edem(
    budget_id: str,
    rows_json: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """E-dem maliyet kopyası oluşturur → /edit'e yönlendirir"""
    if current_user.role not in ("admin", "e_dem"):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        raise HTTPException(404)
    src_rows = rows_json.strip() or budget.rows_json
    new_budget = Budget(
        id=_uuid(),
        request_id=budget.request_id,
        venue_name=budget.venue_name + " (Kopya)",
        rows_json=src_rows,
        budget_status="draft_edem",
        service_fee_pct=budget.service_fee_pct,
        offer_currency=budget.offer_currency or "TRY",
        exchange_rates_json=budget.exchange_rates_json or "{}",
        created_by=current_user.id,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(new_budget)
    db.commit()
    db.refresh(new_budget)
    return RedirectResponse(url=f"/budgets/{new_budget.id}/edit", status_code=status.HTTP_302_FOUND)


@router.post("/{budget_id}/copy-rows", name="budgets_copy_rows")
async def budgets_copy_rows(
    budget_id: str,
    rows_json: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Kaynak bütçenin satırlarını bu bütçeye kopyalar (üzerine yazar)"""
    if current_user.role not in ("admin", "e_dem"):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        raise HTTPException(404)
    if rows_json.strip():
        budget.rows_json = rows_json.strip()
        budget.updated_at = _now()
        db.commit()
    return {"ok": True}


@router.post("/{budget_id}/copy", name="budgets_copy")
async def budgets_copy(
    budget_id: str,
    rows_json: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("admin", "mudur", "yonetici"):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        raise HTTPException(404)

    # Satış fiyatlarını ve durum bayraklarını kopyala; yeni bütçe pending_manager'dan başlar
    src_rows = rows_json.strip() or budget.rows_json
    new_budget = Budget(
        id=_uuid(),
        request_id=budget.request_id,
        venue_name=budget.venue_name + " (Kopya)",
        rows_json=src_rows,
        budget_status="pending_manager",
        service_fee_pct=budget.service_fee_pct,
        offer_currency=budget.offer_currency or "TRY",
        exchange_rates_json=budget.exchange_rates_json or "{}",
        created_by=budget.created_by,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(new_budget)
    db.commit()
    db.refresh(new_budget)
    return RedirectResponse(url=f"/budgets/{new_budget.id}/price", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Revize Fiyat (konfirme sonrası kesin maliyet + satış revizyonu)
# ---------------------------------------------------------------------------

@router.get("/{budget_id}/revise-price", response_class=HTMLResponse, name="budgets_revise_price")
async def budgets_revise_price(
    budget_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Konfirme bütçenin fiyatlarını revize et (manager veya e_dem)"""
    if current_user.role not in ("admin", "mudur", "yonetici", "e_dem"):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if not budget:
        return RedirectResponse(url="/budgets", status_code=status.HTTP_302_FOUND)
    if budget.budget_status != "confirmed":
        return RedirectResponse(url=f"/budgets/{budget_id}", status_code=status.HTTP_302_FOUND)

    req = db.query(ReqModel).filter(ReqModel.id == budget.request_id).first()
    customer = db.query(Customer).filter(Customer.id == req.customer_id).first() if req and req.customer_id else None
    rows_by_section: dict = {}
    for row in budget.rows:
        sec = row.get("section", "other")
        rows_by_section.setdefault(sec, []).append(row)
    services = db.query(Service).filter(Service.active == True).order_by(Service.category, Service.sort_order, Service.name).all()
    grouped_services: dict = {}
    for svc in services:
        grouped_services.setdefault(svc.category, []).append(svc.to_dict())

    return templates.TemplateResponse("budgets/manager_editor.html", {
        "request":             request,
        "current_user":        current_user,
        "budget":              budget,
        "req":                 req,
        "customer":            customer,
        "page_title":          f"Revize Fiyat — {budget.venue_name}",
        "rows_by_section":     rows_by_section,
        "status_label":        BUDGET_STATUS_LABELS.get(budget.budget_status, budget.budget_status),
        "status_color":        BUDGET_STATUS_COLORS.get(budget.budget_status, "secondary"),
        "grouped_services":    json.dumps(grouped_services, ensure_ascii=False),
        "all_request_budgets": [],
        "status_labels":       BUDGET_STATUS_LABELS,
        "status_colors":       BUDGET_STATUS_COLORS,
        "preferred_venues":    [],
        "offer_currency":      budget.offer_currency or "TRY",
        "exchange_rates":      budget.exchange_rates,
        "revise_mode":         True,
    })


@router.post("/{budget_id}/revise-price", name="budgets_revise_price_save")
async def budgets_revise_price_save(
    budget_id:           str,
    rows_json:           str = Form("[]"),
    service_fee_pct:     str = Form("0"),
    manager_notes:       str = Form(""),
    venue_name:          str = Form(""),
    exchange_rates_json: str = Form("{}"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("admin", "mudur", "yonetici", "e_dem"):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id).first()
    if not budget or budget.budget_status != "confirmed":
        return RedirectResponse(url="/budgets", status_code=status.HTTP_302_FOUND)

    import copy

    # Revize öncesi snapshot al
    snap = {
        "ts":      _now().strftime("%d.%m.%Y %H:%M"),
        "label":   f"Revize Öncesi ({current_user.full_name})",
        "trigger": "revise",
        "rows":    copy.deepcopy(budget.rows),
    }
    snaps = budget.price_snapshots
    snaps.append(snap)
    budget.price_snapshots_json = json.dumps(snaps, ensure_ascii=False)

    # Fiyat geçmişi: hem maliyet hem satış değişimlerini kaydet
    try:
        new_rows = json.loads(rows_json)
        _record_price_changes(budget, new_rows, current_user, ["cost_price", "sale_price", "confirmed_cost_price"])
    except Exception:
        pass

    budget.rows_json           = rows_json
    budget.service_fee_pct     = float(service_fee_pct or 0)
    budget.manager_notes       = manager_notes.strip()
    budget.exchange_rates_json = exchange_rates_json or "{}"
    if venue_name.strip():
        budget.venue_name      = venue_name.strip()
    # confirmed durumu korunur
    budget.updated_at          = _now()
    db.commit()

    req_id = budget.request_id
    return RedirectResponse(url=f"/requests/{req_id}#tab-summary", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Hesap Dökümü (Statement)
# ---------------------------------------------------------------------------


@router.get("/{budget_id}/statement", response_class=HTMLResponse, name="budgets_statement_editor")
async def budgets_statement_editor(
    budget_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hesap dökümü editörü"""
    if current_user.role not in ("admin", "mudur", "yonetici"):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id, Budget.budget_type == "statement").first()
    if not budget:
        return RedirectResponse(url="/budgets", status_code=status.HTTP_302_FOUND)

    req = db.query(ReqModel).filter(ReqModel.id == budget.request_id).first()
    customer = db.query(Customer).filter(Customer.id == req.customer_id).first() if req and req.customer_id else None
    rows_by_section: dict = {}
    for row in budget.rows:
        sec = row.get("section", "other")
        rows_by_section.setdefault(sec, []).append(row)
    services = db.query(Service).filter(Service.active == True).order_by(Service.category, Service.sort_order, Service.name).all()
    grouped_services: dict = {}
    for svc in services:
        grouped_services.setdefault(svc.category, []).append(svc.to_dict())

    stmt_sent_label = None
    if budget.statement_sent_at:
        stmt_sent_label = budget.statement_sent_at.strftime("%d.%m.%Y %H:%M")

    customer_email = ""
    if customer:
        # Önce ilk kişisel kontağın emailini kullan, yoksa firma emaili
        contacts = customer.contacts or []
        contact_email = next((c.get("email", "") for c in contacts if c.get("email")), "")
        customer_email = contact_email or customer.email or ""

    return templates.TemplateResponse("budgets/manager_editor.html", {
        "request":             request,
        "current_user":        current_user,
        "budget":              budget,
        "req":                 req,
        "customer":            customer,
        "page_title":          f"Hesap Dökümü — {budget.venue_name}",
        "rows_by_section":     rows_by_section,
        "status_label":        "Hesap Dökümü",
        "status_color":        "indigo",
        "grouped_services":    json.dumps(grouped_services, ensure_ascii=False),
        "all_request_budgets": [],
        "status_labels":       BUDGET_STATUS_LABELS,
        "status_colors":       BUDGET_STATUS_COLORS,
        "preferred_venues":    [],
        "offer_currency":      budget.offer_currency or "TRY",
        "exchange_rates":      budget.exchange_rates,
        "statement_mode":      True,
        "statement_status":    budget.statement_status,
        "statement_sent_label": stmt_sent_label,
        "customer_email":       customer_email,
    })


@router.post("/{budget_id}/statement", name="budgets_statement_save")
async def budgets_statement_save(
    budget_id:           str,
    rows_json:           str = Form("[]"),
    service_fee_pct:     str = Form("0"),
    manager_notes:       str = Form(""),
    venue_name:          str = Form(""),
    exchange_rates_json: str = Form("{}"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hesap dökümünü kaydet"""
    if current_user.role not in ("admin", "mudur", "yonetici"):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id, Budget.budget_type == "statement").first()
    if not budget:
        return RedirectResponse(url="/budgets", status_code=status.HTTP_302_FOUND)

    budget.rows_json           = rows_json
    budget.service_fee_pct     = float(service_fee_pct or 0)
    budget.manager_notes       = manager_notes.strip()
    budget.exchange_rates_json = exchange_rates_json or "{}"
    if venue_name.strip():
        budget.venue_name      = venue_name.strip()
    budget.updated_at          = _now()
    db.commit()
    return RedirectResponse(url=f"/budgets/{budget_id}/statement", status_code=status.HTTP_302_FOUND)


@router.post("/{budget_id}/send-statement", name="budgets_send_statement")
async def budgets_send_statement(
    budget_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hesap dökümünü müşteriye gönderildi olarak işaretle"""
    if current_user.role not in ("admin", "mudur", "yonetici"):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id, Budget.budget_type == "statement").first()
    if not budget:
        raise HTTPException(404)

    budget.statement_status  = "sent"
    budget.statement_sent_at = _now()
    budget.updated_at        = _now()

    req = db.query(ReqModel).filter(ReqModel.id == budget.request_id).first()
    if req:
        log_activity(
            db, req.id, "document_added",
            f"Hesap dökümü müşteriye gönderildi ({budget.venue_name or 'bütçe'})",
            user_id=current_user.id,
        )
    db.commit()

    return RedirectResponse(url=f"/budgets/{budget_id}/statement", status_code=status.HTTP_302_FOUND)


@router.post("/{budget_id}/approve-statement", name="budgets_approve_statement")
async def budgets_approve_statement(
    budget_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Müşteri hesap dökümünü onayladı"""
    if current_user.role not in ("admin", "mudur", "yonetici"):
        raise HTTPException(403)
    budget = db.query(Budget).filter(Budget.id == budget_id, Budget.budget_type == "statement").first()
    if not budget:
        raise HTTPException(404)

    budget.statement_status      = "customer_approved"
    budget.statement_approved_at = _now()
    budget.updated_at            = _now()
    db.commit()

    return RedirectResponse(url=f"/budgets/{budget_id}/statement", status_code=status.HTTP_302_FOUND)
