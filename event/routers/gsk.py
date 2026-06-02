"""
GSK teklif şablonu export router.
GET  /requests/{req_id}/export/gsk  → mapping formu
POST /requests/{req_id}/export/gsk  → doldurulmuş Excel indir
"""
import io
import json
import os
import tempfile
from datetime import date as _date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Budget, Customer, Request as ReqModel, User
from templates_config import templates

router = APIRouter(tags=["gsk"])

# GSK şablonu bu path'te olmalı (event/static/gsk_template.xlsx)
_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
GSK_TEMPLATE_PATH = os.path.join(_TEMPLATE_DIR, "gsk_template.xlsx")

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
    """Referansa bağlı tüm bütçelerin kalemlerini döner (taslak dahil)."""
    rows = []
    for b in req.budgets:
        for r in (b.rows or []):
            if not r.get("description"):
                continue
            rows.append({
                "id":          r.get("id", ""),
                "section":     r.get("section", ""),
                "description": r.get("description", ""),
                "sale_price":  float(r.get("sale_price", 0) or 0),
                "qty":         float(r.get("qty", 1) or 1),
                "nights":      float(r.get("nights", 1) or 1),
                "unit":        r.get("unit", ""),
                "budget_name": b.venue_name or "",
            })
    return rows


def _auto_gsk_section(row: dict) -> str:
    """Miceapp section/description'dan GSK bölümü tahmin et."""
    sec = row.get("section", "").lower()
    desc = row.get("description", "").lower()
    if sec == "accommodation" or "konaklama" in desc or "otel" in desc:
        return "konusmaci_konaklama"
    if sec == "transfer" or "transfer" in desc or "ulaşım" in desc or "ulasim" in desc:
        return "konusmaci_ulasim"
    if sec == "fb" or sec == "f&b":
        if "içecek" in desc or "icecek" in desc or "drink" in desc:
            return "hekim_icecek"
        return "hekim_yiyecek"
    return "diger_hizmetler"


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

    budget_rows = _get_budget_rows(req)
    # Her satıra otomatik GSK bölümü öner
    for r in budget_rows:
        r["suggested_section"] = _auto_gsk_section(r)

    template_exists = os.path.isfile(GSK_TEMPLATE_PATH)

    return templates.TemplateResponse("requests/gsk_export.html", {
        "request":        request,
        "current_user":   current_user,
        "req":            req,
        "budget_rows":    budget_rows,
        "gsk_sections":   GSK_SECTION_LABELS,
        "template_exists": template_exists,
        "page_title":     f"GSK Teklif Export — {req.request_no}",
    })


@router.post("/requests/{req_id}/export/gsk", name="gsk_export_download")
async def gsk_export_download(
    req_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from gsk_export import fill_gsk_template, LineItem, GSKOverflowError

    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(404)

    if not os.path.isfile(GSK_TEMPLATE_PATH):
        raise HTTPException(400, "GSK şablon dosyası bulunamadı. event/static/gsk_template.xlsx yükleyin.")

    form = await request.form()

    # Header alanları
    header = {
        "toplanti_adi":   form.get("toplanti_adi", req.event_name),
        "tarih":          form.get("tarih", req.check_in or ""),
        "opsiyon_tarihi": form.get("opsiyon_tarihi", ""),
        "saat":           form.get("saat", ""),
        "mekan":          form.get("mekan", ""),
        "acente":         form.get("acente", "FORTUNA EVENTS"),
        "gsk_grup":       form.get("gsk_grup", ""),
        "yetkili":        form.get("yetkili", ""),
    }

    commission_str = form.get("commission_rate", "5.5").replace(",", ".")
    try:
        commission_rate = float(commission_str) / 100
    except ValueError:
        commission_rate = 0.055

    # Bütçe satırlarını GSK bölümlerine grupla
    budget_rows = _get_budget_rows(req)
    items_by_section: dict[str, list[LineItem]] = {k: [] for k in GSK_SECTION_LABELS}

    for r in budget_rows:
        row_id = r["id"]
        gsk_sec = form.get(f"gsk_section_{row_id}", "")
        if not gsk_sec or gsk_sec == "skip":
            continue
        items_by_section.setdefault(gsk_sec, []).append(
            LineItem(
                description=r["description"],
                unit_price=r["sale_price"],
                quantity=r["qty"],
                days=r["nights"],
            )
        )

    # Temp dosyaya yaz, stream olarak döndür
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
