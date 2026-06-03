"""
GSK teklif şablonu export router.
GET  /requests/{req_id}/export/gsk  → minimal header formu + otomatik önizleme
POST /requests/{req_id}/export/gsk  → doldurulmuş Excel indir
"""
import io
import os
import tempfile
from datetime import date as _date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Request as ReqModel, User
from templates_config import templates

router = APIRouter(tags=["gsk"])

SABLON_YOLU = os.path.join(os.path.dirname(__file__), "sablonlar", "GSK_BOS.xlsx")
GSK_TEMPLATE_PATH = SABLON_YOLU

GSK_SECTION_LABELS = {
    "hekim_yiyecek":       "Hekim Yiyecek",
    "hekim_icecek":        "Hekim İçecek",
    "staff_yiyecek":       "Staff Yiyecek",
    "staff_icecek":        "Staff İçecek",
    "konusmaci_konaklama": "Konuşmacı Konaklama",
    "konusmaci_ulasim":    "Konuşmacı Ulaşım",
    "diger_hizmetler":     "Diğer Hizmetler",
}


def _get_budget_rows(req: ReqModel) -> list[dict]:
    """Kalemleri döner: önce bütçe satırları, yoksa referansın hizmet talepleri."""
    rows = []
    for b in req.budgets:
        for r in (b.rows or []):
            if not r.get("description"):
                continue
            sale  = float(r.get("sale_price", 0) or 0)
            cost  = float(r.get("cost_price", 0) or 0)
            rows.append({
                "id":          r.get("id", ""),
                "section":     r.get("section", ""),
                "description": r.get("description", ""),
                "sale_price":  sale if sale > 0 else cost,  # cost_price fallback
                "qty":         float(r.get("qty", 1) or 1),
                "nights":      float(r.get("nights", 1) or 1),
                "unit":        r.get("unit", ""),
                "budget_name": b.venue_name or "Bütçe",
                "source":      "budget",
            })
    if rows:
        return rows
    items = req.items or {}
    for section, section_items in items.items():
        if not isinstance(section_items, list):
            continue
        for idx, r in enumerate(section_items):
            desc = r.get("description", "").strip()
            if not desc:
                continue
            rows.append({
                "id":          f"{section}_{idx}",
                "section":     section,
                "description": desc,
                "sale_price":  0.0,
                "qty":         float(r.get("qty", 1) or 1),
                "nights":      1.0,
                "unit":        r.get("unit", ""),
                "budget_name": "Hizmet Talebi",
                "source":      "request",
            })
    return rows


def _build_items_auto(req: ReqModel, price_overrides: dict | None = None) -> tuple[dict, list[str]]:
    """Budget satırlarını otomatik GSK bölümlerine dağıtır.
    price_overrides: {row_id: float} — formdan gelen fiyat düzeltmeleri
    Returns: (items_by_section, warnings)
    """
    from gsk_export import LineItem, GSK_SECTIONS

    hekim_count = float(req.hekim_count or 0)
    staff_count = float(req.staff_count or 0)
    price_overrides = price_overrides or {}

    raw: dict[str, list] = {k: [] for k in GSK_SECTION_LABELS}
    warnings: list[str] = []
    budget_rows = _get_budget_rows(req)

    for r in budget_rows:
        sec       = (r.get("section") or "").lower()
        desc_low  = (r.get("description") or "").lower()
        desc      = r.get("description", "")
        row_id    = r.get("id", "")
        price     = price_overrides.get(row_id, float(r.get("sale_price") or 0))
        qty       = float(r.get("qty") or 1)
        nights    = float(r.get("nights") or 1)

        is_accom    = sec == "accommodation" or any(w in desc_low for w in ("konaklama", "otel", "oda"))
        is_transfer = sec == "transfer"      or any(w in desc_low for w in ("transfer", "ulaşım", "ulasim", "araç", "arac"))
        is_drink    = any(w in desc_low for w in ("içecek", "icecek", "drink", "coffee", "su ikramı", "su ikami"))
        is_fb       = sec in ("fb", "f&b")   or any(w in desc_low for w in (
                          "yemek", "yiyecek", "kahvaltı", "kahvalti", "öğle", "ogle",
                          "akşam", "aksam", "gala", "meze", "kokteyl", "coffee", "içecek",
                          "icecek", "drink", "brunch", "tabldot",
                      ))

        if is_accom:
            raw["konusmaci_konaklama"].append(
                LineItem(description=desc, unit_price=price, quantity=qty, days=nights)
            )
        elif is_transfer:
            raw["konusmaci_ulasim"].append(
                LineItem(description=desc, unit_price=price, quantity=qty, days=nights)
            )
        elif is_fb:
            explicit_hekim = "hekim" in desc_low
            explicit_staff = "staff" in desc_low

            if explicit_hekim:
                gsk_sec = "hekim_icecek" if is_drink else "hekim_yiyecek"
                raw[gsk_sec].append(LineItem(description=desc, unit_price=price, quantity=qty, days=nights))
            elif explicit_staff:
                gsk_sec = "staff_icecek" if is_drink else "staff_yiyecek"
                raw[gsk_sec].append(LineItem(description=desc, unit_price=price, quantity=qty, days=nights))
            else:
                # Genel F&B → hekim_count ve staff_count'a böl
                if hekim_count > 0:
                    gsk_sec = "hekim_icecek" if is_drink else "hekim_yiyecek"
                    raw[gsk_sec].append(LineItem(description=desc, unit_price=price, quantity=hekim_count, days=nights))
                if staff_count > 0:
                    gsk_sec = "staff_icecek" if is_drink else "staff_yiyecek"
                    raw[gsk_sec].append(LineItem(description=desc, unit_price=price, quantity=staff_count, days=nights))
                if hekim_count == 0 and staff_count == 0:
                    gsk_sec = "hekim_icecek" if is_drink else "hekim_yiyecek"
                    raw[gsk_sec].append(LineItem(description=desc, unit_price=price, quantity=qty, days=nights))
        else:
            raw["diger_hizmetler"].append(
                LineItem(description=desc, unit_price=price, quantity=qty, days=nights)
            )

    # Taşma kontrolü: kapasiteyi aşan kalemler diger_hizmetler'e gider
    overflow: list = []
    items: dict[str, list] = {}
    for key, sec_def in GSK_SECTIONS.items():
        if key == "diger_hizmetler":
            continue
        cap = len(sec_def["rows"])
        sec_items = raw[key]
        if len(sec_items) > cap:
            warnings.append(
                f"{sec_def['label']}: {len(sec_items)} kalem, max {cap} → "
                f"{len(sec_items) - cap} kalem 'Diğer Hizmetler'e taşındı"
            )
            overflow.extend(sec_items[cap:])
            items[key] = sec_items[:cap]
        else:
            items[key] = sec_items

    diger_items = raw["diger_hizmetler"] + overflow
    diger_cap = len(GSK_SECTIONS["diger_hizmetler"]["rows"])
    if len(diger_items) > diger_cap:
        warnings.append(f"Diğer Hizmetler kapasitesi ({diger_cap}) aşıldı, ilk {diger_cap} kalem alındı")
        diger_items = diger_items[:diger_cap]
    items["diger_hizmetler"] = diger_items

    return items, warnings


def _auto_preview(req: ReqModel) -> dict:
    """Önizleme için bölüm bazlı kalem sayılarını hesaplar."""
    items, warnings = _build_items_auto(req)
    preview = {
        key: {"label": GSK_SECTION_LABELS[key], "count": len(v)}
        for key, v in items.items()
    }
    return {"sections": preview, "warnings": warnings, "total": sum(len(v) for v in items.values())}


@router.get("/requests/{req_id}/export/gsk", response_class=HTMLResponse, name="gsk_export_form")
async def gsk_export_form(
    req_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(404)

    venue_name = ""
    if req.budgets:
        venue_name = req.budgets[0].venue_name or ""

    template_exists = os.path.isfile(GSK_TEMPLATE_PATH)
    preview = _auto_preview(req)

    # Fiyatı eksik (0) kalemleri bul — kullanıcının girmesi gerekecek
    zero_price_rows = [r for r in _get_budget_rows(req) if r["sale_price"] == 0]

    return templates.TemplateResponse("requests/gsk_export.html", {
        "request":          request,
        "current_user":     current_user,
        "req":              req,
        "venue_name":       venue_name,
        "template_exists":  template_exists,
        "preview":          preview,
        "zero_price_rows":  zero_price_rows,
        "page_title":       f"GSK Teklif Export — {req.request_no}",
    })


@router.post("/requests/{req_id}/export/gsk", name="gsk_export_download")
async def gsk_export_download(
    req_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from gsk_export import fill_gsk_template, GSKOverflowError

    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(404)

    if not os.path.isfile(GSK_TEMPLATE_PATH):
        raise HTTPException(400, "GSK şablon dosyası bulunamadı. event/static/gsk_template.xlsx yükleyin.")

    form = await request.form()

    header = {
        "toplanti_adi":   form.get("toplanti_adi") or req.event_name,
        "tarih":          form.get("tarih") or req.check_in or "",
        "opsiyon_tarihi": form.get("opsiyon_tarihi") or "",
        "saat":           form.get("saat") or "",
        "mekan":          form.get("mekan") or "",
        "acente":         form.get("acente") or "STOK MICE",
        "gsk_grup":       form.get("gsk_grup") or req.client_name or "",
        "yetkili":        form.get("yetkili") or "",
    }

    commission_str = (form.get("commission_rate") or "5.5").replace(",", ".")
    try:
        commission_rate = float(commission_str) / 100
    except ValueError:
        commission_rate = 0.055

    # Formdan gelen fiyat düzeltmeleri (sıfır fiyatlı kalemler için)
    price_overrides: dict[str, float] = {}
    for key in form:
        if key.startswith("price_"):
            row_id = key[6:]
            try:
                price_overrides[row_id] = float((form.get(key) or "0").replace(",", "."))
            except ValueError:
                pass

    items_by_section, _ = _build_items_auto(req, price_overrides=price_overrides)

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        fill_gsk_template(
            template_path=GSK_TEMPLATE_PATH,
            output_path=tmp_path,
            items_by_section=items_by_section,
            header=header,
            commission_rate=commission_rate,
        )
        with open(tmp_path, "rb") as f:
            content = f.read()
    except GSKOverflowError as e:
        raise HTTPException(400, str(e))
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    filename = f"GSK_{req.request_no}_{_date.today().isoformat()}.xlsx"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
