"""
RFQ Şablon yönetimi — takım bazlı tekrar eden talep şablonları.

GET  /request-templates            → liste
GET  /request-templates/new        → oluşturma formu
POST /request-templates/new        → kaydet
GET  /request-templates/{id}/edit  → düzenle
POST /request-templates/{id}/edit  → güncelle
POST /request-templates/{id}/delete→ sil (soft)
GET  /request-templates/{id}/json  → JS için items_json API
"""
import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db, EVENT_COMPANY_ID
from models import RequestTemplate, Team, User, INVOICE_TYPES, _uuid, _now
from templates_config import templates

router = APIRouter(prefix="/request-templates", tags=["request_templates"])


def _visible_templates(db: Session, user: User):
    """Kullanıcının görebileceği şablonlar: kendi takımı + kendi oluşturduğu."""
    q = db.query(RequestTemplate).filter(
        RequestTemplate.active == True,
        RequestTemplate.company_id == EVENT_COMPANY_ID,
    )
    if user.is_gm or user.role in ("admin", "super_admin"):
        return q.order_by(RequestTemplate.name).all()
    if user.team_id:
        from sqlalchemy import or_
        q = q.filter(
            or_(
                RequestTemplate.team_id == user.team_id,
                RequestTemplate.created_by == user.id,
            )
        )
    else:
        q = q.filter(RequestTemplate.created_by == user.id)
    return q.order_by(RequestTemplate.name).all()


def _can_edit(tmpl: RequestTemplate, user: User) -> bool:
    if user.is_gm or user.role in ("admin", "super_admin"):
        return True
    return tmpl.created_by == user.id or (
        user.team_id and tmpl.team_id == user.team_id
        and user.role in ("mudur",)
    )


# ---------------------------------------------------------------------------
# Liste
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="request_templates_list")
async def templates_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tmpls = _visible_templates(db, current_user)
    teams = db.query(Team).filter(Team.active == True).order_by(Team.name).all()
    return templates.TemplateResponse("request_templates/list.html", {
        "request": request,
        "current_user": current_user,
        "tmpls": tmpls,
        "teams": teams,
        "page_title": "RFQ Şablonları",
    })


# ---------------------------------------------------------------------------
# Oluştur
# ---------------------------------------------------------------------------

@router.get("/new", response_class=HTMLResponse, name="request_templates_new")
async def templates_new_form(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    teams = db.query(Team).filter(Team.active == True).order_by(Team.name).all()
    return templates.TemplateResponse("request_templates/form.html", {
        "request": request,
        "current_user": current_user,
        "tmpl": None,
        "teams": teams,
        "page_title": "Yeni RFQ Şablonu",
        "error": None,
    })


@router.post("/new", name="request_templates_create")
async def templates_create(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    event_type: str = Form(""),
    team_id: str = Form(""),
    items_json: str = Form("{}"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not name.strip():
        raise HTTPException(400, "Şablon adı boş olamaz.")
    tmpl = RequestTemplate(
        id=_uuid(),
        name=name.strip(),
        description=description.strip(),
        event_type=event_type.strip(),
        team_id=team_id.strip() or current_user.team_id or None,
        items_json=items_json or "{}",
        company_id=EVENT_COMPANY_ID,
        created_by=current_user.id,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(tmpl)
    db.commit()
    return RedirectResponse("/request-templates?saved=1", status_code=302)


# ---------------------------------------------------------------------------
# Düzenle
# ---------------------------------------------------------------------------

@router.get("/{tmpl_id}/edit", response_class=HTMLResponse, name="request_templates_edit")
async def templates_edit_form(
    tmpl_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tmpl = db.query(RequestTemplate).filter(RequestTemplate.id == tmpl_id).first()
    if not tmpl or not tmpl.active:
        raise HTTPException(404)
    if not _can_edit(tmpl, current_user):
        raise HTTPException(403)
    teams = db.query(Team).filter(Team.active == True).order_by(Team.name).all()
    return templates.TemplateResponse("request_templates/form.html", {
        "request": request,
        "current_user": current_user,
        "tmpl": tmpl,
        "teams": teams,
        "page_title": f"Düzenle — {tmpl.name}",
        "error": None,
    })


@router.post("/{tmpl_id}/edit", name="request_templates_update")
async def templates_update(
    tmpl_id: str,
    name: str = Form(...),
    description: str = Form(""),
    event_type: str = Form(""),
    team_id: str = Form(""),
    items_json: str = Form("{}"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tmpl = db.query(RequestTemplate).filter(RequestTemplate.id == tmpl_id).first()
    if not tmpl or not tmpl.active:
        raise HTTPException(404)
    if not _can_edit(tmpl, current_user):
        raise HTTPException(403)
    tmpl.name = name.strip()
    tmpl.description = description.strip()
    tmpl.event_type = event_type.strip()
    tmpl.team_id = team_id.strip() or current_user.team_id or None
    tmpl.items_json = items_json or "{}"
    tmpl.updated_at = _now()
    db.commit()
    return RedirectResponse("/request-templates?saved=1", status_code=302)


# ---------------------------------------------------------------------------
# Sil (soft)
# ---------------------------------------------------------------------------

@router.post("/{tmpl_id}/delete", name="request_templates_delete")
async def templates_delete(
    tmpl_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tmpl = db.query(RequestTemplate).filter(RequestTemplate.id == tmpl_id).first()
    if tmpl and _can_edit(tmpl, current_user):
        tmpl.active = False
        db.commit()
    return RedirectResponse("/request-templates", status_code=302)


# ---------------------------------------------------------------------------
# JSON API — talep formunda JS ile yüklemek için
# ---------------------------------------------------------------------------

@router.get("/{tmpl_id}/json", name="request_templates_json")
async def templates_json(
    tmpl_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tmpl = db.query(RequestTemplate).filter(
        RequestTemplate.id == tmpl_id,
        RequestTemplate.active == True,
    ).first()
    if not tmpl:
        raise HTTPException(404)
    # Erişim kontrolü
    if not (current_user.is_gm or current_user.role in ("admin", "super_admin")):
        if tmpl.team_id and tmpl.team_id != current_user.team_id:
            if tmpl.created_by != current_user.id:
                raise HTTPException(403)
    return JSONResponse({
        "id":          tmpl.id,
        "name":        tmpl.name,
        "event_type":  tmpl.event_type,
        "items":       tmpl.items,
    })


# ---------------------------------------------------------------------------
# Referanstan şablon kaydetme (AJAX / form POST)
# ---------------------------------------------------------------------------

@router.post("/save-from-request", name="request_templates_save_from_request")
async def templates_save_from_request(
    name: str = Form(...),
    description: str = Form(""),
    team_id: str = Form(""),
    items_json: str = Form("{}"),
    event_type: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mevcut referansın items_json'ını şablon olarak kaydet (tarihler sıfırlanır)."""
    # Tarihleri sıfırla — şablon yeniden kullanılabilir olsun
    try:
        items = json.loads(items_json or "{}")
    except Exception:
        items = {}

    for section_items in items.values():
        if not isinstance(section_items, list):
            continue
        for item in section_items:
            item.pop("date_from", None)
            item.pop("date_to", None)
            if "daily_attendees" in item:
                for da in item["daily_attendees"]:
                    da.pop("date", None)

    tmpl = RequestTemplate(
        id=_uuid(),
        name=name.strip(),
        description=description.strip(),
        event_type=event_type.strip(),
        team_id=team_id.strip() or current_user.team_id or None,
        items_json=json.dumps(items, ensure_ascii=False),
        company_id=EVENT_COMPANY_ID,
        created_by=current_user.id,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(tmpl)
    db.commit()
    return JSONResponse({"ok": True, "id": tmpl.id, "name": tmpl.name})
