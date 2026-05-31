"""
Satın Alma — Dashboard router
GET /dashboard → İstatistikleri sorgula, dashboard.html render et
"""

import json
from collections import defaultdict
from datetime import datetime, date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Budget, Customer, Invoice, Request as ReqModel, Service, Team, User, Vendor, ClosureRequest

router = APIRouter()
from templates_config import templates


def _last_n_months(n: int = 6) -> list[str]:
    """Son n ayın YYYY-MM listesini döner (en eski → en yeni)"""
    now = datetime.utcnow()
    months = []
    for i in range(n - 1, -1, -1):
        m = now.month - i
        y = now.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        months.append(f"{y}-{m:02d}")
    return months


def _build_financial_stats(db: Session, req_id_filter=None, d_from=None, d_to=None, customer_id=None, ref_status=None):
    """Onaylı faturalardan ciro/kar/aylık veri hesapla — sadece gerçek rakamlar.

    Fon havuzu ana referanslarının `kesilen` faturaları ciro'ya dahil EDİLMEZ
    (çift sayma önlemi — gelir, alt referanslara yapılan transferlerde oluşur).
    FundTransfer'ler KDV hariç TRY karşılığı ile ciroya/kara eklenir.
    d_from/d_to verilirse, kalemin etkin tarihi (referans check_in → tarih → oluşturma)
    bu aralıkta olanlar hesaba katılır.
    """
    from utils.funds import fund_pool_invoice_ids
    _fund_inv_ids = fund_pool_invoice_ids(db)

    _df = d_from.isoformat() if d_from else None
    _dt = d_to.isoformat() if d_to else None

    def _eff(*cands) -> str | None:
        """Adaylardan ilk geçerli tarihi YYYY-MM-DD string olarak döndür."""
        for v in cands:
            if not v:
                continue
            try:
                return v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else str(v)[:10]
            except Exception:
                continue
        return None

    def _in_range(eff: str | None) -> bool:
        if not eff:
            return d_from is None and d_to is None  # tarihi yoksa: filtre yoksa dahil
        if _df and eff < _df:
            return False
        if _dt and eff > _dt:
            return False
        return True

    inv_query = db.query(Invoice).filter(
        Invoice.status.in_(["approved", "gm_approved", "active"]),
    )
    if req_id_filter is not None:
        inv_query = inv_query.filter(Invoice.request_id.in_(req_id_filter))
    if _fund_inv_ids:
        inv_query = inv_query.filter(~Invoice.id.in_(_fund_inv_ids))

    invoices = inv_query.all()

    total_sale     = 0.0
    total_cost     = 0.0
    total_komisyon = 0.0
    monthly: dict[str, dict] = defaultdict(lambda: {"sale": 0.0, "cost": 0.0})

    for inv in invoices:
        if not _in_range(_eff(inv.request.check_in if inv.request else None, inv.invoice_date, inv.created_at)):
            continue
        if customer_id and (not inv.request or inv.request.customer_id != customer_id):
            continue
        if ref_status and (not inv.request or inv.request.status not in ref_status):
            continue
        if inv.invoice_type == "kesilen":
            total_sale += inv.amount
        elif inv.invoice_type == "iade_kesilen":
            total_sale -= inv.amount
        elif inv.invoice_type == "gelen":
            total_cost += inv.amount
        elif inv.invoice_type == "iade_gelen":
            total_cost -= inv.amount
        elif inv.invoice_type == "komisyon":
            # Komisyon faturası → gelir (kar'a direkt katkı)
            total_komisyon += inv.amount
        else:
            continue

        # Aylık gruplama: referansın etkinlik başlangıç tarihini (check_in) kullan.
        # Fatura önce ya da sonra gelse bile iş hangi ayda gerçekleştiyse o aya yaz.
        # Fallback: fatura tarihi → oluşturulma tarihi
        key = None
        req_obj = inv.request
        if req_obj and req_obj.check_in:
            try:
                ci = req_obj.check_in
                if hasattr(ci, "strftime"):
                    key = ci.strftime("%Y-%m")
                else:
                    key = str(ci)[:7]
            except Exception:
                pass
        if not key and inv.invoice_date:
            try:
                key = inv.invoice_date[:7]
            except Exception:
                pass
        if not key and inv.created_at:
            key = inv.created_at.strftime("%Y-%m")
        if key:
            if inv.invoice_type == "kesilen":
                monthly[key]["sale"] += inv.amount
            elif inv.invoice_type == "iade_kesilen":
                monthly[key]["sale"] -= inv.amount
            elif inv.invoice_type == "gelen":
                monthly[key]["cost"] += inv.amount
            elif inv.invoice_type == "iade_gelen":
                monthly[key]["cost"] -= inv.amount
            elif inv.invoice_type == "komisyon":
                monthly[key]["sale"] += inv.amount   # komisyon → gelir

    # Fon transferleri → ciroya TRY/KDV hariç katkı
    # out = alt ref'e giren (gelir), in = alt ref'ten fona dönen (iade)
    from models import FundTransfer as _FT, Request as _Req
    ft_query = db.query(_FT)
    if req_id_filter is not None:
        ft_query = ft_query.filter(_FT.related_request_id.in_(req_id_filter))
    for t in ft_query.all():
        if not _in_range(_eff(t.related_request.check_in if t.related_request else None, t.transfer_date)):
            continue
        if customer_id and (not t.related_request or t.related_request.customer_id != customer_id):
            continue
        if ref_status and (not t.related_request or t.related_request.status not in ref_status):
            continue
        val = t.amount_try_excl_vat
        sign = +1 if t.direction == "out" else -1
        total_sale += sign * val

        # Aylık gruplama: alt referansın check_in'i
        req_obj = t.related_request
        key = None
        if req_obj and req_obj.check_in:
            try:
                ci = req_obj.check_in
                key = ci.strftime("%Y-%m") if hasattr(ci, "strftime") else str(ci)[:7]
            except Exception:
                pass
        if not key and t.transfer_date:
            key = t.transfer_date[:7]
        if key:
            monthly[key]["sale"] += sign * val

    # HBF (Harcama Bildirim Formları) → gider. GM onayından geçenler (onaylandi/kapandi)
    # KDV hariç tutarıyla maliyete eklenir (requests/detail.html ile aynı mantık).
    from models import ExpenseReport as _ER
    hbf_q = db.query(_ER).filter(_ER.status.in_(["onaylandi", "kapandi", "approved"]))
    if req_id_filter is not None:
        hbf_q = hbf_q.filter(_ER.request_id.in_(req_id_filter))
    hbf_gider = 0.0
    for r in hbf_q.all():
        if not _in_range(_eff(r.request.check_in if r.request else None, r.created_at)):
            continue
        if customer_id and (not r.request or r.request.customer_id != customer_id):
            continue
        if ref_status and (not r.request or r.request.status not in ref_status):
            continue
        amt = r.grand_excl_vat or 0
        hbf_gider += amt
        # Aylık gruplama: referansın check_in'i, yoksa HBF oluşturma tarihi
        key = None
        req_obj = r.request
        if req_obj and req_obj.check_in:
            try:
                ci = req_obj.check_in
                key = ci.strftime("%Y-%m") if hasattr(ci, "strftime") else str(ci)[:7]
            except Exception:
                pass
        if not key and r.created_at:
            key = r.created_at.strftime("%Y-%m")
        if key:
            monthly[key]["cost"] += amt
    hbf_gider = round(hbf_gider, 2)
    total_cost = round(total_cost + hbf_gider, 2)

    # Kar = kesilen + komisyon − (gelen + HBF gideri)
    kar = total_sale + total_komisyon - total_cost
    total_revenue = total_sale + total_komisyon
    karlilik = round(kar / total_revenue * 100, 1) if total_revenue > 0 else 0.0

    labels = _last_n_months(6)
    chart_sale = [round(monthly[m]["sale"], 0) for m in labels]
    chart_cost = [round(monthly[m]["cost"], 0) for m in labels]
    chart_labels = [m[5:] + "/" + m[2:4] for m in labels]

    return {
        "total_sale":      round(total_revenue, 2),   # ciro + komisyon
        "total_cost":      round(total_cost, 2),
        "hbf_gider":       hbf_gider,
        "total_kar":       round(kar, 2),
        "karlilik":        karlilik,
        "chart_labels":    chart_labels,
        "chart_sale":      chart_sale,
        "chart_cost":      chart_cost,
    }


def _build_ytd_team_stats(db: Session) -> list[dict]:
    """Yılbaşından bugüne takım bazlı ciro/kar (tüm takımlar — GM/admin için).

    Fon havuzu referansları (customer + vendor) tamamen hariç tutulur —
    sahte takım/müşteri olarak görünmesinler.
    """
    from utils.funds import fund_pool_invoice_ids
    from models import FundTransfer as _FT
    year_start = date(date.today().year, 1, 1).isoformat()

    reqs = (db.query(ReqModel)
              .filter(ReqModel.check_in >= year_start,
                      ReqModel.is_fund_pool == False)            # noqa: E712
              .all())
    if not reqs:
        return []
    req_team_map = {r.id: r.team_id for r in reqs}
    req_ids = list(req_team_map.keys())

    _fund_inv_ids = fund_pool_invoice_ids(db)
    inv_q = db.query(Invoice).filter(
        Invoice.status.in_(["approved", "gm_approved", "active"]),
        Invoice.request_id.in_(req_ids),
    )
    if _fund_inv_ids:
        inv_q = inv_q.filter(~Invoice.id.in_(_fund_inv_ids))
    invoices = inv_q.all()

    team_name_map = {t.id: t.name for t in db.query(Team).all()}

    agg: dict[str, dict] = defaultdict(lambda: {"ciro": 0.0, "maliyet": 0.0, "komisyon": 0.0})
    for inv in invoices:
        tid  = req_team_map.get(inv.request_id)
        name = team_name_map.get(tid, "Takımsız") if tid else "Takımsız"
        if inv.invoice_type == "kesilen":
            agg[name]["ciro"] += inv.amount
        elif inv.invoice_type == "iade_kesilen":
            agg[name]["ciro"] -= inv.amount
        elif inv.invoice_type == "komisyon":
            agg[name]["komisyon"] += inv.amount
        elif inv.invoice_type == "gelen":
            agg[name]["maliyet"] += inv.amount
        elif inv.invoice_type == "iade_gelen":
            agg[name]["maliyet"] -= inv.amount

    # FundTransfer'ler — alt ref'in takımına göre
    for t in db.query(_FT).filter(_FT.related_request_id.in_(req_ids)).all():
        tid  = req_team_map.get(t.related_request_id)
        name = team_name_map.get(tid, "Takımsız") if tid else "Takımsız"
        v = t.amount_try_excl_vat
        if t.direction == "out":
            agg[name]["ciro"] += v
        elif t.direction == "in":
            agg[name]["ciro"] -= v

    rows = []
    for name, v in agg.items():
        ciro = v["ciro"] + v["komisyon"]
        kar  = ciro - v["maliyet"]
        rows.append({"name": name, "ciro": round(ciro, 0), "kar": round(kar, 0)})
    rows.sort(key=lambda r: r["ciro"], reverse=True)
    return rows


def _build_ytd_customer_stats(db: Session, req_id_filter=None, limit: int = 10) -> list[dict]:
    """Yılbaşından bugüne müşteri bazlı ciro/kar.

    req_id_filter verilirse sadece o referans ID'leri kapsanır (rol scope).
    Dönen her kayıt: {code, name, ciro, kar} — label olarak 3 harfli kod
    (kod yoksa adın ilk 3 harfi) kullanılır, tam ad tooltip/alt satır için.
    """
    year_start = date(date.today().year, 1, 1).isoformat()

    req_q = (db.query(ReqModel)
               .filter(ReqModel.check_in >= year_start,
                       ReqModel.is_fund_pool == False))           # noqa: E712
    if req_id_filter is not None:
        req_q = req_q.filter(ReqModel.id.in_(req_id_filter))
    reqs = req_q.all()
    if not reqs:
        return []

    req_info = {r.id: (r.customer_id, r.client_name) for r in reqs}
    cust_map = {c.id: (c.code, c.name) for c in db.query(Customer).all()}

    from utils.funds import fund_pool_invoice_ids
    _fund_inv_ids = fund_pool_invoice_ids(db)
    inv_q = db.query(Invoice).filter(
        Invoice.status.in_(["approved", "gm_approved", "active"]),
        Invoice.request_id.in_(list(req_info.keys())),
    )
    if _fund_inv_ids:
        inv_q = inv_q.filter(~Invoice.id.in_(_fund_inv_ids))
    invoices = inv_q.all()

    def _fallback_code(name: str) -> str:
        n = (name or "").strip()
        return (n[:3] or "—").upper()

    # key = customer_id (varsa) veya "free:"+client_name — aynı müşteriye ait faturalar toplansın
    agg: dict[str, dict] = defaultdict(
        lambda: {"code": "—", "name": "—", "ciro": 0.0, "maliyet": 0.0, "komisyon": 0.0}
    )
    for inv in invoices:
        cid, cname = req_info.get(inv.request_id, (None, None))
        if cid and cid in cust_map:
            code, full = cust_map[cid]
            key = f"cust:{cid}"
            label_code = (code or _fallback_code(full)).upper()
            label_name = full
        else:
            key = f"free:{(cname or '—').lower()}"
            label_code = _fallback_code(cname)
            label_name = cname or "—"
        agg[key]["code"] = label_code
        agg[key]["name"] = label_name
        if inv.invoice_type == "kesilen":
            agg[key]["ciro"] += inv.amount
        elif inv.invoice_type == "iade_kesilen":
            agg[key]["ciro"] -= inv.amount
        elif inv.invoice_type == "komisyon":
            agg[key]["komisyon"] += inv.amount
        elif inv.invoice_type == "gelen":
            agg[key]["maliyet"] += inv.amount
        elif inv.invoice_type == "iade_gelen":
            agg[key]["maliyet"] -= inv.amount

    # FundTransfer'ler — alt ref'in müşterisine göre
    from models import FundTransfer as _FT
    for t in db.query(_FT).filter(_FT.related_request_id.in_(list(req_info.keys()))).all():
        cid, cname = req_info.get(t.related_request_id, (None, None))
        if cid and cid in cust_map:
            code, full = cust_map[cid]
            key = f"cust:{cid}"
            agg[key]["code"] = (code or _fallback_code(full)).upper()
            agg[key]["name"] = full
        else:
            key = f"free:{(cname or '—').lower()}"
            agg[key]["code"] = _fallback_code(cname)
            agg[key]["name"] = cname or "—"
        v = t.amount_try_excl_vat
        if t.direction == "out":
            agg[key]["ciro"] += v
        elif t.direction == "in":
            agg[key]["ciro"] -= v

    rows = []
    for v in agg.values():
        ciro = v["ciro"] + v["komisyon"]
        kar  = ciro - v["maliyet"]
        if ciro == 0 and kar == 0:
            continue
        rows.append({
            "code": v["code"],
            "name": v["name"],
            "ciro": round(ciro, 0),
            "kar":  round(kar, 0),
        })
    rows.sort(key=lambda r: r["ciro"], reverse=True)
    return rows[:limit]


def _fmt_amount(v: float) -> str:
    try:
        return "₺" + "{:,.0f}".format(float(v)).replace(",", ".")
    except Exception:
        return ""


def _build_pending_tasks(db: Session, current_user) -> list[dict]:
    """Role göre bekleyen işlemleri linkli liste olarak döner.

    Her görev: {icon, color, label, title, context, url}
      - label   = kısa etiket (renk + tip rozeti)
      - title   = kullanıcıya ne yapması gerektiği (aksiyon cümlesi)
      - context = ref no + etkinlik adı + (tutar / tedarikçi / müşteri gibi)
    """
    tasks = []
    role = current_user.role

    # ── Müdür / Admin / Muhasebe Müdürü: onay bekleyen fatura ──────────────
    if role in ("mudur", "admin", "muhasebe_muduru"):
        invs = (
            db.query(Invoice)
            .filter(Invoice.status == "pending")
            .order_by(Invoice.created_at.asc())
            .limit(15)
            .all()
        )
        for inv in invs:
            req = inv.request
            if not req:
                continue
            ctx_bits = [req.request_no, req.event_name]
            if inv.vendor_name:
                ctx_bits.append(inv.vendor_name)
            if inv.amount:
                ctx_bits.append(_fmt_amount(inv.amount))
            tasks.append({
                "icon":    "bi-receipt",
                "color":   "warning",
                "label":   "Fatura Onayı",
                "title":   "Fatura onayınız bekleniyor",
                "context": " · ".join(ctx_bits),
                "url":     f"/requests/{req.id}",
            })

    # ── GM / Admin: kapama GM onayı ────────────────────────────────────────
    if role in ("mudur", "admin"):
        closures = (
            db.query(ClosureRequest)
            .filter(ClosureRequest.status == "pending_gm")
            .order_by(ClosureRequest.created_at.asc())
            .limit(10)
            .all()
        )
        for cl in closures:
            req = cl.request
            if not req:
                continue
            tasks.append({
                "icon":    "bi-folder-check",
                "color":   "primary",
                "label":   "Kapama (GM)",
                "title":   "Dosya kapama — Genel Müdür onayınız bekleniyor",
                "context": f"{req.request_no} · {req.event_name}",
                "url":     f"/requests/{req.id}",
            })

    # ── Müdür / Admin: kapama müdür onayı ──────────────────────────────────
    if role in ("mudur", "admin"):
        closures_mgr = (
            db.query(ClosureRequest)
            .filter(ClosureRequest.status == "pending_manager")
            .order_by(ClosureRequest.created_at.asc())
            .limit(10)
            .all()
        )
        for cl in closures_mgr:
            req = cl.request
            if not req:
                continue
            tasks.append({
                "icon":    "bi-folder-check",
                "color":   "warning",
                "label":   "Kapama (Müdür)",
                "title":   "Dosya kapama — Müdür onayınız bekleniyor",
                "context": f"{req.request_no} · {req.event_name}",
                "url":     f"/requests/{req.id}",
            })

    # ── Muhasebe: GM onaylı fatura kesilecek ───────────────────────────────
    if role in ("muhasebe", "muhasebe_muduru", "admin"):
        invs_gm = (
            db.query(Invoice)
            .filter(Invoice.status == "gm_approved")
            .order_by(Invoice.created_at.asc())
            .limit(15)
            .all()
        )
        for inv in invs_gm:
            req = inv.request
            if not req:
                continue
            ctx_bits = [req.request_no, req.event_name]
            if inv.vendor_name:
                ctx_bits.append(inv.vendor_name)
            if inv.amount:
                ctx_bits.append(_fmt_amount(inv.amount))
            tasks.append({
                "icon":    "bi-scissors",
                "color":   "danger",
                "label":   "Fatura Kes",
                "title":   "GM onayladı — fatura kesilmeli",
                "context": " · ".join(ctx_bits),
                "url":     f"/requests/{req.id}",
            })

    # ── Muhasebe müdürü: kapama finans onayı ───────────────────────────────
    if role in ("muhasebe_muduru", "admin"):
        closures_fin = (
            db.query(ClosureRequest)
            .filter(ClosureRequest.status == "pending_finance")
            .order_by(ClosureRequest.created_at.asc())
            .limit(10)
            .all()
        )
        for cl in closures_fin:
            req = cl.request
            if not req:
                continue
            tasks.append({
                "icon":    "bi-folder-check",
                "color":   "info",
                "label":   "Kapama (Muhasebe)",
                "title":   "Dosya kapama — Muhasebe onayınız bekleniyor",
                "context": f"{req.request_no} · {req.event_name}",
                "url":     f"/requests/{req.id}",
            })

    # ── Satın Alma: atanmamış talepler ──────────────────────────────────────────
    if role == "satinalma":
        pending_reqs = (
            db.query(ReqModel)
            .filter(ReqModel.status == "pending")
            .order_by(ReqModel.created_at.asc())
            .limit(15)
            .all()
        )
        for req in pending_reqs:
            cust = req.client_name or (req.customer.name if req.customer else "")
            ctx_bits = [req.request_no, req.event_name]
            if cust:
                ctx_bits.append(cust)
            tasks.append({
                "icon":    "bi-inbox-fill",
                "color":   "warning",
                "label":   "Yeni Talep",
                "title":   "Yeni talep üstlenilmeyi bekliyor",
                "context": " · ".join(ctx_bits),
                "url":     f"/requests/{req.id}",
            })

    # ── Yönetici / Asistan: bütçesi hazır / teklif gönderilmiş ─────────────
    if role in ("yonetici", "asistan"):
        from routers.requests import _get_subtree_ids
        sub_ids = _get_subtree_ids(current_user.id, db)
        visible_ids = [current_user.id] + sub_ids
        budget_ready = (
            db.query(ReqModel)
            .filter(
                ReqModel.created_by.in_(visible_ids),
                ReqModel.status.in_(["budget_ready", "offer_sent"]),
            )
            .order_by(ReqModel.updated_at.desc())
            .limit(10)
            .all()
        )
        for req in budget_ready:
            if req.status == "budget_ready":
                title = "Bütçe hazırlandı — incelemenizi bekliyor"
            else:
                title = "Teklif müşteride — yanıt takibi bekliyor"
            tasks.append({
                "icon":    "bi-calculator-fill",
                "color":   "success",
                "label":   "Bütçe Hazır" if req.status == "budget_ready" else "Teklif Gönderildi",
                "title":   title,
                "context": f"{req.request_no} · {req.event_name}",
                "url":     f"/requests/{req.id}",
            })

    return tasks


@router.get("/dashboard", response_class=HTMLResponse, name="dashboard")
async def dashboard(
    request: Request,
    date_from: str = None,
    date_to: str = None,
    customer_id: str = None,
    ref_status: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from datetime import date as _date
    _today = _date.today()
    cust_id = customer_id.strip() if customer_id and customer_id.strip() else None
    # İş durumu filtresi (referans status)
    _REF_STATUS_MAP = {
        "ongoing":   ["confirmed"],
        "completed": ["completed"],
        "closing":   ["closing"],
        "closed":    ["closed"],
        "cancelled": ["cancelled"],
    }
    ref_status = (ref_status or "").strip()
    ref_status_set = _REF_STATUS_MAP.get(ref_status)
    try:
        d_from = _date.fromisoformat(date_from) if date_from else _date(_today.year, 1, 1)
    except Exception:
        d_from = _date(_today.year, 1, 1)
    try:
        d_to = _date.fromisoformat(date_to) if date_to else _today
    except Exception:
        d_to = _today

    stats = {}
    financial = {}
    recent_requests = []

    if current_user.is_gm or current_user.role in ("admin", "muhasebe_muduru"):
        # GM, admin, muhasebe_muduru: tüm şirket verileri
        req_id_filter = None
        base_q = db.query(ReqModel)

        stats = {
            "total_venues":    db.query(Vendor).filter(Vendor.active == True).count(),
            "total_requests":  base_q.count(),
            "total_users":     db.query(User).filter(User.active == True).count(),
            "total_customers": db.query(Customer).count(),
            "total_budgets":   db.query(Budget).count(),
            "open_requests":   base_q.filter(
                ReqModel.status.in_(["pending", "in_progress", "venues_contacted",
                                     "budget_ready", "offer_sent", "revision"])
            ).count(),
        }
        financial = _build_financial_stats(db, req_id_filter=req_id_filter, d_from=d_from, d_to=d_to, customer_id=cust_id, ref_status=ref_status_set)
        recent_requests = (
            base_q.order_by(ReqModel.created_at.desc()).limit(8).all()
        )

    elif current_user.role == "mudur":
        _mudur_team = db.query(Team).filter(Team.id == current_user.team_id).first() if current_user.team_id else None
        _open_statuses = ["pending", "in_progress", "venues_contacted", "budget_ready", "offer_sent", "revision"]
        if _mudur_team and _mudur_team.is_support_team:
            # Destek ekibi: created_by bazlı — kendi üyelerinin yürüttüğü etkinlikler
            _member_ids = [u.id for u in db.query(User).filter(
                User.team_id == current_user.team_id, User.active == True).all()]
            base_q = db.query(ReqModel).filter(ReqModel.created_by.in_(_member_ids))
            req_id_filter = [r.id for r in base_q.with_entities(ReqModel.id).all()]
            stats = {
                "total_requests": base_q.count(),
                "open_requests":  base_q.filter(ReqModel.status.in_(_open_statuses)).count(),
                "my_confirmed":   base_q.filter(ReqModel.status == "confirmed").count(),
                "total_budgets":  db.query(Budget).filter(Budget.request_id.in_(req_id_filter)).count(),
            }
            financial = _build_financial_stats(db, req_id_filter=req_id_filter, d_from=d_from, d_to=d_to, customer_id=cust_id, ref_status=ref_status_set)
            recent_requests = base_q.order_by(ReqModel.created_at.desc()).limit(8).all()
        else:
            # Normal birim müdürü: sadece kendi takımının istatistikleri
            if current_user.team_id:
                base_q = db.query(ReqModel).filter(ReqModel.team_id == current_user.team_id)
            else:
                base_q = db.query(ReqModel).filter(False)
            req_id_filter = [r.id for r in base_q.with_entities(ReqModel.id).all()]
            stats = {
                "total_requests":  base_q.count(),
                "open_requests":   base_q.filter(ReqModel.status.in_(_open_statuses)).count(),
                "total_customers": db.query(Customer).filter(
                    Customer.team_id == current_user.team_id
                ).count() if current_user.team_id else 0,
                "total_budgets":   db.query(Budget).filter(Budget.request_id.in_(req_id_filter)).count(),
            }
            financial = _build_financial_stats(db, req_id_filter=req_id_filter, d_from=d_from, d_to=d_to, customer_id=cust_id, ref_status=ref_status_set)
            recent_requests = base_q.order_by(ReqModel.created_at.desc()).limit(8).all()

    elif current_user.role == "yonetici":
        from routers.requests import _get_subtree_ids
        sub_ids = _get_subtree_ids(current_user.id, db)
        visible_ids = [current_user.id] + sub_ids
        base_q = db.query(ReqModel).filter(ReqModel.created_by.in_(visible_ids))
        req_id_filter = [r.id for r in db.query(ReqModel.id).filter(
            ReqModel.created_by.in_(visible_ids)).all()]
        stats = {
            "my_total":     base_q.count(),
            "my_draft":     base_q.filter(ReqModel.status == "draft").count(),
            "my_pending":   db.query(ReqModel).filter(
                ReqModel.created_by.in_(visible_ids), ReqModel.status == "pending").count(),
            "budget_ready": db.query(ReqModel).filter(
                ReqModel.created_by.in_(visible_ids), ReqModel.status == "budget_ready").count(),
            "my_confirmed": db.query(ReqModel).filter(
                ReqModel.created_by.in_(visible_ids), ReqModel.status == "confirmed").count(),
            "open_requests": db.query(ReqModel).filter(
                ReqModel.created_by.in_(visible_ids),
                ReqModel.status.in_(["pending", "in_progress", "venues_contacted",
                                     "budget_ready", "offer_sent", "revision"])
            ).count(),
        }
        financial = _build_financial_stats(db, req_id_filter=req_id_filter, d_from=d_from, d_to=d_to, customer_id=cust_id, ref_status=ref_status_set)
        recent_requests = (
            base_q.order_by(ReqModel.created_at.desc()).limit(8).all()
        )

    elif current_user.role == "asistan":
        # Asistan: sadece kendi referanslarının sayısal istatistikleri — finansal veri yok
        my_q = db.query(ReqModel).filter(ReqModel.created_by == current_user.id)
        stats = {
            "my_total":     my_q.count(),
            "my_draft":     db.query(ReqModel).filter(
                ReqModel.created_by == current_user.id, ReqModel.status == "draft").count(),
            "my_pending":   db.query(ReqModel).filter(
                ReqModel.created_by == current_user.id, ReqModel.status == "pending").count(),
            "budget_ready": db.query(ReqModel).filter(
                ReqModel.created_by == current_user.id, ReqModel.status == "budget_ready").count(),
            "my_confirmed": db.query(ReqModel).filter(
                ReqModel.created_by == current_user.id, ReqModel.status == "confirmed").count(),
            "open_requests": db.query(ReqModel).filter(
                ReqModel.created_by == current_user.id,
                ReqModel.status.in_(["pending", "in_progress", "venues_contacted",
                                     "budget_ready", "offer_sent", "revision"])
            ).count(),
        }
        financial = {}   # asistan finansal veri görmez
        recent_requests = (
            my_q.order_by(ReqModel.created_at.desc()).limit(8).all()
        )

    else:  # satinalma, muhasebe — sadece iş yükü, finansal bilgi yok
        stats = {
            "pending":          db.query(ReqModel).filter(ReqModel.status == "pending").count(),
            "in_progress":      db.query(ReqModel).filter(ReqModel.status == "in_progress").count(),
            "venues_contacted": db.query(ReqModel).filter(ReqModel.status == "venues_contacted").count(),
            "budget_ready":     db.query(ReqModel).filter(ReqModel.status == "budget_ready").count(),
            "my_budgets":       db.query(Budget).filter(Budget.created_by == current_user.id).count(),
            "open_requests":    db.query(ReqModel).filter(
                ReqModel.status.in_(["pending", "in_progress", "venues_contacted", "budget_ready"])
            ).count(),
        }
        financial = {}
        recent_requests = (
            db.query(ReqModel)
            .filter(ReqModel.status.in_(["pending", "in_progress", "venues_contacted"]))
            .order_by(ReqModel.created_at.desc())
            .limit(8)
            .all()
        )

    pending_tasks = _build_pending_tasks(db, current_user)

    # Takım YTD grafiği — GM ve admin için (tüm takımları görür)
    team_ytd = []
    show_team_ytd = current_user.is_gm or current_user.role == "admin"
    if show_team_ytd:
        team_ytd = _build_ytd_team_stats(db)

    # Müşteri YTD grafiği — finansal görüntülemesi olan roller (asistan/satinalma hariç)
    customer_ytd = []
    show_customer_ytd = current_user.is_gm or current_user.role in ("admin", "mudur", "muhasebe_muduru", "yonetici")
    if show_customer_ytd:
        customer_ytd = _build_ytd_customer_stats(db, req_id_filter=req_id_filter)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request":         request,
            "current_user":    current_user,
            "stats":           stats,
            "financial":       financial,
            "recent_requests": recent_requests,
            "pending_tasks":   pending_tasks,
            "page_title":      "Dashboard",
            "d_from":          d_from.isoformat(),
            "d_to":            d_to.isoformat(),
            "customers":       db.query(Customer).order_by(Customer.name).all(),
            "selected_customer_id": cust_id,
            "ref_status_options": [
                ("", "Tüm İşler"),
                ("ongoing", "Aktif İşler"),
                ("completed", "Tamamlanan"),
                ("closed", "Kapalı Referanslar"),
                ("cancelled", "İptal Olan"),
            ],
            "selected_ref_status": ref_status,
            "chart_data":      json.dumps({
                "labels": financial.get("chart_labels", []),
                "sale":   financial.get("chart_sale", []),
                "cost":   financial.get("chart_cost", []),
            }),
            "show_team_ytd":   show_team_ytd,
            "team_ytd":        team_ytd,
            "team_ytd_json":   json.dumps({
                "labels": [t["name"] for t in team_ytd],
                "ciro":   [t["ciro"]  for t in team_ytd],
                "kar":    [t["kar"]   for t in team_ytd],
            }),
            "show_customer_ytd": show_customer_ytd,
            "customer_ytd_json": json.dumps({
                "labels": [c["code"] for c in customer_ytd],
                "names":  [c["name"] for c in customer_ytd],
                "ciro":   [c["ciro"] for c in customer_ytd],
                "kar":    [c["kar"]  for c in customer_ytd],
            }),
        },
    )
