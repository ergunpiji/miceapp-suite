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

SABLON_YOLU = os.path.join(os.path.dirname(__file__), "..", "static", "GSK Boş Template Bütçe.xlsx")
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
            # Bütçe editörü "service_name" kullanır; fallback "description"
            desc = r.get("service_name") or r.get("description", "")
            if not desc:
                continue
            sale  = float(r.get("sale_price", 0) or 0)
            cost  = float(r.get("cost_price", 0) or 0)
            rows.append({
                "id":          r.get("id", ""),
                "section":     r.get("section", ""),
                "description": desc,
                "sale_price":  sale if sale > 0 else cost,
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
    from gsk_export import rows_to_items
    return rows_to_items(
        rows=_get_budget_rows(req),
        hekim=float(req.hekim_count or 0),
        staff=float(req.staff_count or 0),
        price_overrides=price_overrides,
    )


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
            gsk_sheet_name="Örnek",
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
