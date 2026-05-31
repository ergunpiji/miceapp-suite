"""
Satın Alma — Tedarikçi (Vendor) yönetimi router'ı
GET    /venues           → Liste (tüm roller)
GET    /venues/new       → Form (Admin + Satın Alma)
POST   /venues/new       → Oluştur
GET    /venues/{id}      → Detay
GET    /venues/{id}/edit → Düzenleme formu
POST   /venues/{id}/edit → Güncelle
POST   /venues/{id}/delete → Sil
"""

import json
import os
import shutil

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from storage import save_upload, delete_upload
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin_or_edem
from database import get_db
from models import TR_CITIES, SUPPLIER_TYPES, User, Vendor, _uuid, _now

router = APIRouter(prefix="/venues", tags=["venues"])
from templates_config import templates


@router.get("", response_class=HTMLResponse, name="venues_list")
async def venues_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    city: str = "",
    stype: str = "",
    q: str = "",
):
    query = db.query(Vendor).filter(Vendor.active == True)

    if q:
        query = query.filter(Vendor.name.ilike(f"%{q}%"))
    if stype:
        query = query.filter(Vendor.supplier_type == stype)
    if city:
        query = query.filter(Vendor.city == city)

    venues = query.order_by(Vendor.name).all()

    can_edit = current_user.role in ("admin", "satinalma", "muhasebe_muduru")

    return templates.TemplateResponse(
        "venues/list.html",
        {
            "request":        request,
            "current_user":   current_user,
            "venues":         venues,
            "page_title":     "Tedarikçi Havuzu",
            "supplier_types": SUPPLIER_TYPES,
            "tr_cities":      TR_CITIES,
            "can_edit":       can_edit,
            "filter_q":       q,
            "filter_city":    city,
            "filter_stype":   stype,
        },
    )


@router.get("/new", response_class=HTMLResponse, name="venues_new")
async def venues_new(
    request: Request,
    current_user: User = Depends(require_admin_or_edem),
):
    return templates.TemplateResponse(
        "venues/form.html",
        {
            "request":        request,
            "current_user":   current_user,
            "venue":          None,
            "page_title":     "Yeni Tedarikçi",
            "supplier_types": SUPPLIER_TYPES,
            "tr_cities":      TR_CITIES,
            "error":          None,
        },
    )


@router.post("/new", name="venues_create")
async def venues_create(
    request: Request,
    name:          str = Form(...),
    city:          str = Form(""),
    supplier_type: str = Form("otel"),
    address:       str = Form(""),
    stars:         str = Form(""),
    total_rooms:   str = Form("0"),
    website:       str = Form(""),
    notes:         str = Form(""),
    cities_json:   str = Form("[]"),
    halls_json:    str = Form("[]"),
    contacts_json: str = Form("[]"),
    payment_term:  str = Form(""),
    current_user:  User = Depends(require_admin_or_edem),
    db: Session = Depends(get_db),
):
    _pt = payment_term.strip()
    venue = Vendor(
        id=_uuid(),
        name=name.strip(),
        city=city.strip(),
        cities_json=cities_json,
        supplier_type=supplier_type,
        address=address.strip(),
        stars=int(stars) if stars and stars.isdigit() else None,
        total_rooms=int(total_rooms) if total_rooms and total_rooms.isdigit() else 0,
        website=website.strip(),
        notes=notes.strip(),
        halls_json=halls_json,
        contacts_json=contacts_json,
        payment_term=int(_pt) if _pt and _pt.isdigit() else 30,
        active=True,
        created_at=_now(),
    )
    db.add(venue)
    db.commit()
    return RedirectResponse(url="/venues", status_code=status.HTTP_302_FOUND)


@router.get("/{venue_id}", response_class=HTMLResponse, name="venues_detail")
async def venues_detail(
    venue_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    venue = db.query(Vendor).filter(Vendor.id == venue_id).first()
    if not venue:
        return RedirectResponse(url="/venues", status_code=status.HTTP_302_FOUND)

    can_edit = current_user.role in ("admin", "satinalma", "muhasebe_muduru")

    return templates.TemplateResponse(
        "venues/detail.html",
        {
            "request":      request,
            "current_user": current_user,
            "venue":        venue,
            "page_title":   venue.name,
            "can_edit":     can_edit,
        },
    )


@router.get("/{venue_id}/edit", response_class=HTMLResponse, name="venues_edit")
async def venues_edit(
    venue_id: str,
    request: Request,
    current_user: User = Depends(require_admin_or_edem),
    db: Session = Depends(get_db),
):
    venue = db.query(Vendor).filter(Vendor.id == venue_id).first()
    if not venue:
        return RedirectResponse(url="/venues", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        "venues/form.html",
        {
            "request":        request,
            "current_user":   current_user,
            "venue":          venue,
            "page_title":     f"{venue.name} — Düzenle",
            "supplier_types": SUPPLIER_TYPES,
            "tr_cities":      TR_CITIES,
            "error":          None,
        },
    )


@router.post("/{venue_id}/edit", name="venues_update")
async def venues_update(
    venue_id: str,
    request: Request,
    name:          str = Form(...),
    city:          str = Form(""),
    supplier_type: str = Form("otel"),
    address:       str = Form(""),
    stars:         str = Form(""),
    total_rooms:   str = Form("0"),
    website:       str = Form(""),
    notes:         str = Form(""),
    cities_json:   str = Form("[]"),
    halls_json:    str = Form("[]"),
    contacts_json: str = Form("[]"),
    payment_term:  str = Form(""),
    active:        str = Form("on"),
    current_user:  User = Depends(require_admin_or_edem),
    db: Session = Depends(get_db),
):
    venue = db.query(Vendor).filter(Vendor.id == venue_id).first()
    if not venue:
        return RedirectResponse(url="/venues", status_code=status.HTTP_302_FOUND)

    venue.name          = name.strip()
    venue.city          = city.strip()
    venue.cities_json   = cities_json
    venue.supplier_type = supplier_type
    venue.address       = address.strip()
    venue.stars         = int(stars) if stars and stars.isdigit() else None
    venue.total_rooms   = int(total_rooms) if total_rooms and total_rooms.isdigit() else 0
    venue.website       = website.strip()
    venue.notes         = notes.strip()
    venue.halls_json    = halls_json
    venue.contacts_json = contacts_json
    _pt2 = payment_term.strip()
    venue.payment_term  = int(_pt2) if _pt2 and _pt2.isdigit() else 30
    venue.active        = (active == "on")

    db.commit()
    return RedirectResponse(url=f"/venues/{venue_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{venue_id}/upload-doc", name="venues_upload_doc")
async def venues_upload_doc(
    venue_id: str,
    doc_file: UploadFile = File(...),
    current_user: User = Depends(require_admin_or_edem),
    db: Session = Depends(get_db),
):
    venue = db.query(Vendor).filter(Vendor.id == venue_id).first()
    if not venue:
        return RedirectResponse(url="/venues", status_code=status.HTTP_302_FOUND)

    filename = os.path.basename(doc_file.filename or "dosya")
    key = save_upload(doc_file.file.read(), f"venue_docs/{venue_id}", filename)

    try:
        doc_list = json.loads(venue.docs_json or "[]")
    except Exception:
        doc_list = []
    doc_list.append({"name": filename, "path": key})
    venue.docs_json = json.dumps(doc_list, ensure_ascii=False)
    db.commit()
    return RedirectResponse(url=f"/venues/{venue_id}/edit", status_code=status.HTTP_302_FOUND)


@router.post("/{venue_id}/delete-doc", name="venues_delete_doc")
async def venues_delete_doc(
    venue_id: str,
    filename: str = Form(...),
    current_user: User = Depends(require_admin_or_edem),
    db: Session = Depends(get_db),
):
    venue = db.query(Vendor).filter(Vendor.id == venue_id).first()
    if not venue:
        return RedirectResponse(url="/venues", status_code=status.HTTP_302_FOUND)

    try:
        doc_list = json.loads(getattr(venue, "docs_json", None) or "[]")
    except Exception:
        doc_list = []

    remaining = []
    for d in doc_list:
        if d["name"] == filename:
            delete_upload(d.get("path", ""))
        else:
            remaining.append(d)

    venue.docs_json = json.dumps(remaining, ensure_ascii=False)
    db.commit()
    return RedirectResponse(url=f"/venues/{venue_id}/edit", status_code=status.HTTP_302_FOUND)


@router.post("/bulk-delete", name="venues_bulk_delete")
async def venues_bulk_delete(
    ids_json: str = Form(...),
    current_user: User = Depends(require_admin_or_edem),
    db: Session = Depends(get_db),
):
    try:
        ids = json.loads(ids_json)
        if not isinstance(ids, list):
            raise ValueError
    except Exception:
        return JSONResponse({"ok": False, "error": "Geçersiz veri"}, status_code=400)

    deleted = 0
    failed_ids = []
    for vid in ids:
        try:
            venue = db.query(Vendor).filter(Vendor.id == str(vid)).first()
            if venue:
                db.delete(venue)
                db.flush()   # FK hatası varsa burada patlar, commit öncesinde
                deleted += 1
        except Exception as e:
            db.rollback()
            failed_ids.append(str(vid))
            print(f"[bulk-delete] {vid} silinemedi: {e}", flush=True)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        return JSONResponse({"ok": False, "error": f"Commit hatası: {e}"}, status_code=500)

    return JSONResponse({"ok": True, "deleted": deleted, "failed": len(failed_ids)})


@router.post("/{venue_id}/delete", name="venues_delete")
async def venues_delete(
    venue_id: str,
    current_user: User = Depends(require_admin_or_edem),
    db: Session = Depends(get_db),
):
    venue = db.query(Vendor).filter(Vendor.id == venue_id).first()
    if venue:
        try:
            db.delete(venue)
            db.commit()
        except Exception:
            db.rollback()
            venue.active = False
            db.commit()
    return RedirectResponse(url="/venues", status_code=status.HTTP_302_FOUND)
