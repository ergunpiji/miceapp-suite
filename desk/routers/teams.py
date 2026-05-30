"""
E-dem — Etkinlik Takımları router'ı
GET  /teams           → Takım listesi
GET  /teams/new       → Yeni takım formu
POST /teams/new       → Takım oluştur
GET  /teams/{id}      → Takım detayı (org ağacı)
POST /teams/{id}/edit → Takım bilgilerini güncelle
POST /teams/{id}/delete → Takımı pasif yap
"""

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import require_admin
from database import get_db
from models import Team, User, _uuid

router = APIRouter(prefix="/teams", tags=["teams"])
from templates_config import templates


def _build_tree(members: list[User]) -> list[dict]:
    """
    manager_id ilişkisine göre kullanıcıları ağaç yapısına dönüştür.
    Her düğüm: {user, children: [...]}
    Kök düğümler: manager_id None veya takım dışı olanlar.
    """
    id_map: dict[str, dict] = {}
    for u in members:
        id_map[u.id] = {"user": u, "children": []}

    roots = []
    for u in members:
        node = id_map[u.id]
        if u.manager_id and u.manager_id in id_map:
            id_map[u.manager_id]["children"].append(node)
        else:
            roots.append(node)
    return roots


# ── Liste ──────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def teams_list(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    saved: str = "",
):
    teams = db.query(Team).order_by(Team.name).all()
    counts = {
        t.id: db.query(User).filter(User.team_id == t.id, User.active == True).count()
        for t in teams
    }
    return templates.TemplateResponse("teams/list.html", {
        "request": request,
        "current_user": current_user,
        "teams": teams,
        "member_counts": counts,
        "saved": saved,
    })


# ── Yeni Takım ────────────────────────────────────────────────────────────

@router.get("/new", response_class=HTMLResponse)
async def teams_new_form(
    request: Request,
    current_user: User = Depends(require_admin),
):
    return templates.TemplateResponse("teams/form.html", {
        "request": request,
        "current_user": current_user,
        "team": None,
        "error": "",
    })


@router.post("/new")
async def teams_create(
    request: Request,
    name: str = Form(...),
    code: str = Form(""),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    name = name.strip()
    code = code.strip().upper()[:10]
    if not name:
        return templates.TemplateResponse("teams/form.html", {
            "request": request,
            "current_user": current_user,
            "team": None,
            "error": "Takım adı boş olamaz.",
        })
    team = Team(id=_uuid(), name=name, code=code)
    db.add(team)
    db.commit()
    return RedirectResponse(f"/teams/{team.id}", status_code=status.HTTP_303_SEE_OTHER)


# ── Detay / Org Ağacı ─────────────────────────────────────────────────────

@router.get("/{team_id}", response_class=HTMLResponse)
async def teams_detail(
    team_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    saved: str = "",
):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        return RedirectResponse("/teams", status_code=status.HTTP_303_SEE_OTHER)

    members = (
        db.query(User)
        .filter(User.team_id == team_id, User.active == True)
        .order_by(User.name)
        .all()
    )
    tree = _build_tree(members)

    # Takım içinde manager_id'si takım üyesine işaret etmeyenler
    member_ids = {m.id for m in members}
    unassigned = [u for u in members
                  if u.manager_id and u.manager_id not in member_ids]

    return templates.TemplateResponse("teams/detail.html", {
        "request": request,
        "current_user": current_user,
        "team": team,
        "members": members,
        "tree": tree,
        "unassigned": unassigned,
        "saved": saved,
    })


# ── Takım Güncelle ────────────────────────────────────────────────────────

@router.post("/{team_id}/edit")
async def teams_edit(
    team_id: str,
    name: str = Form(...),
    code: str = Form(""),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    team = db.query(Team).filter(Team.id == team_id).first()
    if team:
        team.name = name.strip()
        team.code = code.strip().upper()[:10]
        db.commit()
    return RedirectResponse(f"/teams/{team_id}?saved=1", status_code=status.HTTP_303_SEE_OTHER)


# ── Takımı Pasif Yap ──────────────────────────────────────────────────────

@router.post("/{team_id}/delete")
async def teams_delete(
    team_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    team = db.query(Team).filter(Team.id == team_id).first()
    if team:
        team.active = False
        db.commit()
    return RedirectResponse("/teams", status_code=status.HTTP_303_SEE_OTHER)
