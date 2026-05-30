"""Fon havuzu (FundTransfer) yardımcı fonksiyonları.

- Bakiye hesaplama
- Güncel kur (TCMB)
- Şirket genelinde fon ana faturalarını ciro'dan filtrelemek için ID kümesi
"""
from typing import TYPE_CHECKING
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from models import Request as ReqModel


FUND_ADMIN_ROLES = {"admin", "muhasebe_muduru"}
INVOICE_SPLIT_ROLES = {"admin", "muhasebe_muduru", "mudur"}   # mudur = etkinlik süreç müdürü


def can_manage_funds(user) -> bool:
    """Müşteri fonu havuzu aç / transfer yap yetkisi (admin / muhasebe_muduru / GM)."""
    if not user:
        return False
    if user.role in FUND_ADMIN_ROLES:
        return True
    try:
        return bool(user.is_gm)
    except Exception:
        return False


def can_split_invoice(user) -> bool:
    """Fatura bölme yetkisi (admin / muhasebe_muduru / mudur / GM)."""
    if not user:
        return False
    if user.role in INVOICE_SPLIT_ROLES:
        return True
    try:
        return bool(user.is_gm)
    except Exception:
        return False


def get_or_create_vendor_fund_pool(vendor_name: str, year: int, currency: str, db: Session, *, created_by_id: str):
    """Tedarikçi adı + yıl bazlı tek aktif vendor fund pool — yoksa yarat.

    Bölme sırasında "kalan" tutar bu havuza atanır. Havuzun client_name'i
    tedarikçi adı, customer_id NULL olur (müşteriye ait değil — tedarikçiye ait).
    """
    from models import Request as ReqModel, _uuid, _now
    from database import generate_ref_no

    vendor_name = (vendor_name or "").strip()
    if not vendor_name:
        raise ValueError("Tedarikçi adı boş olamaz")

    # Aynı yıl + tedarikçi için mevcut havuz var mı?
    year_prefix = str(year)
    existing = (db.query(ReqModel)
                  .filter(ReqModel.is_fund_pool == True,                  # noqa: E712
                          ReqModel.fund_pool_type == "vendor",
                          ReqModel.fund_vendor_name == vendor_name,
                          ReqModel.check_in.like(f"{year_prefix}-%"))
                  .first())
    if existing:
        return existing

    # Yeni havuz oluştur
    check_in = f"{year}-01-01"
    code = "vfn"   # vendor fund — özel ev. tipi
    ref_no = generate_ref_no(db, code, vendor_name[:3] or "ven", check_in)
    new_fund = ReqModel(
        id=_uuid(),
        request_no=ref_no,
        client_name=vendor_name,
        customer_id=None,
        event_name=f"{vendor_name} — {year} Tedarikçi Fonu",
        event_type=code,
        city="",
        cities_json="[]",
        attendee_count=0,
        check_in=check_in,
        check_out=f"{year}-12-31",
        status="fund_pool",
        items_json="{}",
        description=f"Tedarikçi fonu — {vendor_name} · {year}",
        notes="",
        preferred_venues_json="[]",
        selected_venues_json="[]",
        contact_person_json="{}",
        is_fund_pool=True,
        fund_pool_type="vendor",
        fund_vendor_name=vendor_name,
        fund_currency=(currency or "TRY"),
        fund_initial_amount=0.0,    # birikimli — bölme arttıkça artar
        fund_initial_vat_rate=20.0,
        created_by=created_by_id,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(new_fund)
    db.flush()
    return new_fund


def get_fund_balance(fund_req: "ReqModel", db: Session) -> dict:
    """Fon havuzu bakiyesi — original currency (KDV dahil).

    initial + in − out = remaining.
    """
    from models import FundTransfer
    transfers = db.query(FundTransfer).filter(
        FundTransfer.fund_request_id == fund_req.id
    ).all()
    total_out = round(sum(t.amount for t in transfers if t.direction == "out"), 2)
    total_in  = round(sum(t.amount for t in transfers if t.direction == "in"),  2)
    initial   = float(fund_req.fund_initial_amount or 0)
    remaining = round(initial - total_out + total_in, 2)
    return {
        "currency":       fund_req.fund_currency or "TRY",
        "vat_rate":       float(fund_req.fund_initial_vat_rate or 0),
        "initial":        initial,
        "initial_excl":   round(initial / (1 + float(fund_req.fund_initial_vat_rate or 0) / 100.0), 2)
                          if fund_req.fund_initial_vat_rate else initial,
        "out_total":      total_out,
        "in_total":       total_in,
        "remaining":      remaining,
        "transfer_count": len(transfers),
        "transfers":      transfers,
    }


def get_current_exchange_rate(currency: str) -> float:
    """Currency → TRY kuru. TRY için 1.0. TCMB başarısız olursa 1.0."""
    cur = (currency or "TRY").upper()
    if cur == "TRY":
        return 1.0
    try:
        from utils.tcmb import fetch_today_rates
        rates = fetch_today_rates()
        rate = rates.get(cur)
        if rate and rate > 0:
            return float(rate)
    except Exception:
        pass
    return 1.0


def fund_pool_invoice_ids(db: Session) -> set[str]:
    """Finansal hesaplamalarda hariç tutulması gereken fatura ID'leri.

    İçerir:
    - Fon havuzu (customer) ana referanslarına bağlı 'kesilen' faturalar
      (gelir transferlerle alt ref'lere taşınır)
    - Bölünmüş parent gelen faturalar (child'lara pay edildi — parent çift sayma)

    Şirket geneli ciro/kar hesaplamalarında `.notin_()` ile filtrelenmeli.
    """
    from models import Invoice, Request as ReqModel
    pool_rows = (db.query(Invoice.id)
                   .join(ReqModel, ReqModel.id == Invoice.request_id)
                   .filter(ReqModel.is_fund_pool == True,        # noqa: E712
                           Invoice.invoice_type == "kesilen")
                   .all())
    split_rows = (db.query(Invoice.id)
                    .filter(Invoice.is_split_parent == True)     # noqa: E712
                    .all())
    return {r[0] for r in pool_rows} | {r[0] for r in split_rows}


def get_customer_fund_pools(customer_id: str, db: Session) -> list:
    """Müşteriye ait aktif fon havuzu referansları (alt ref dropdown için)."""
    from models import Request as ReqModel
    if not customer_id:
        return []
    return (db.query(ReqModel)
              .filter(ReqModel.customer_id == customer_id,
                      ReqModel.is_fund_pool == True,        # noqa: E712
                      ReqModel.status == "fund_pool")
              .order_by(ReqModel.created_at.desc())
              .all())
