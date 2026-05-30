"""
E-dem — Dosya Kapama Onay Akışı

Akış:
  1. PM / Yönetici → POST /requests/{id}/submit-closure
     Referans status: confirmed/completed → closing
     → Tutar, müdürün limitiyle karşılaştırılır:
       * Tutar ≤ limit (veya müdür sınırsız / GM'in kendisi): pending_manager
       * Tutar > limit: pending_manager (needs_gm=True)

  2. Müdür → POST /closure/{id}/approve-l1
     * needs_gm=False → pending_finance
     * needs_gm=True  → pending_gm

  3. Genel Müdür → POST /closure/{id}/approve-gm  (yalnızca needs_gm=True)
     → pending_finance

  4. Muhasebe Müdürü → POST /closure/{id}/approve-final
     → closed  +  Referans status: closing → closed

  * Herhangi adımda: POST /closure/{id}/reject → rejected + referans geri alınır
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import (
    Budget, ClosureRequest, OrgTitle, Request as ReqModel, User,
    CLOSURE_STATUS_LABELS, CLOSURE_STATUS_COLORS,
    _uuid, _now,
)
from templates_config import templates

router = APIRouter(tags=["closure"])


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------

def _can_approve_l1(user: User) -> bool:
    return user.role in ("admin", "mudur") or user.is_gm


def _can_approve_gm(user: User) -> bool:
    return user.role in ("admin", "mudur") or user.is_gm


def _can_approve_final(user: User) -> bool:
    return user.role in ("admin", "muhasebe_muduru") or user.is_gm


def _find_mudur_in_chain(user: User, db: Session) -> User | None:
    """Kullanıcının manager zincirinde ilk mudur rolündeki kişiyi bul."""
    visited: set[str] = set()
    current = user
    while current.manager_id and current.manager_id not in visited:
        visited.add(current.manager_id)
        mgr = db.query(User).filter(User.id == current.manager_id, User.active == True).first()
        if not mgr:
            break
        if mgr.role == "mudur":
            return mgr
        current = mgr
    # Fallback: sistemdeki herhangi bir aktif mudur
    return db.query(User).filter(User.role == "mudur", User.active == True).first()


def _find_gm(db: Session) -> User | None:
    """
    Genel Müdürü bul: mudur rolü + en düşük grade org_title (K1).
    Yoksa: admin rolündeki ilk aktif kullanıcı.
    """
    users = db.query(User).filter(User.role == "mudur", User.active == True).all()
    best: User | None = None
    best_grade = 999
    for u in users:
        if u.org_title and u.org_title.grade < best_grade:
            best_grade = u.org_title.grade
            best = u
    if best is None:
        # Grade bilgisi yoksa manager zinciri en üstünde olan mudur
        best = db.query(User).filter(User.role == "mudur", User.active == True).first()
    return best


def _get_confirmed_budget_total(req: ReqModel, db: Session) -> float:
    """Onaylı bütçenin KDV dahil toplam satış tutarını TRY cinsinden döndür."""
    if req.confirmed_budget_id:
        budget = db.query(Budget).filter(Budget.id == req.confirmed_budget_id).first()
        if budget:
            return budget.grand_sale or 0.0
    # Onaylı bütçe yoksa tüm approved bütçelerin maksimumu
    budgets = [b for b in req.budgets if b.budget_status == "approved"]
    if budgets:
        return max(b.grand_sale or 0.0 for b in budgets)
    return 0.0


def _needs_gm_step(mudur: User, amount: float, gm: User | None) -> bool:
    """
    GM onayı gerekiyor mu?
    - Müdür limit tanımlanmamış (None) → hayır (sınırsız yetkisi var)
    - Müdür zaten GM (K1) → hayır
    - Tutar ≤ limit → hayır
    - Tutar > limit → evet
    """
    if gm and mudur.id == gm.id:
        return False  # Zaten GM, ikinci adım gereksiz
    if not mudur.org_title or mudur.org_title.budget_limit is None:
        return False  # Limit tanımsız = sınırsız yetkisi
    return amount > mudur.org_title.budget_limit


def _check_closure_prerequisites(req: ReqModel) -> list[str]:
    errors = []
    pending_inv  = [i for i in req.invoices if i.status == "pending"]
    rejected_inv = [i for i in req.invoices if i.status == "rejected"]
    if pending_inv:
        errors.append(f"{len(pending_inv)} fatura onay bekliyor.")
    if rejected_inv:
        errors.append(f"{len(rejected_inv)} fatura reddedildi — düzeltilmeli.")
    pending_hbf  = [r for r in req.expense_reports if r.status in ("draft", "submitted")]
    rejected_hbf = [r for r in req.expense_reports if r.status == "rejected"]
    if pending_hbf:
        errors.append(f"{len(pending_hbf)} HBF onaylanmamış.")
    if rejected_hbf:
        errors.append(f"{len(rejected_hbf)} HBF reddedildi — düzeltilmeli.")
    return errors


# ---------------------------------------------------------------------------
# GET /closure  — liste
# ---------------------------------------------------------------------------

@router.get("/closure", response_class=HTMLResponse, name="closure_list")
async def closure_list(
    request: Request,
    status_filter: str = "all",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("admin", "mudur", "muhasebe_muduru"):
        raise HTTPException(403)

    from models import Request as ReqModel, User as UserModel
    query = db.query(ClosureRequest)
    # mudur (Etkinlik Süreç Müdürü) ve GM tüm kapama taleplerini görür — takım engeli yok

    if status_filter != "all":
        query = query.filter(ClosureRequest.status == status_filter)
    closures = query.order_by(ClosureRequest.created_at.desc()).all()

    pend_q = db.query(ClosureRequest).filter(
        ClosureRequest.status.in_(["pending_manager", "pending_gm", "pending_finance"])
    )
    pending_count = pend_q.count()

    return templates.TemplateResponse("closure/list.html", {
        "request":        request,
        "current_user":   current_user,
        "page_title":     "Dosya Kapama",
        "closures":       closures,
        "status_filter":  status_filter,
        "pending_count":  pending_count,
        "STATUS_LABELS":  CLOSURE_STATUS_LABELS,
        "STATUS_COLORS":  CLOSURE_STATUS_COLORS,
    })


# ---------------------------------------------------------------------------
# POST /requests/{req_id}/submit-closure
# ---------------------------------------------------------------------------

@router.post("/requests/{req_id}/submit-closure", name="closure_submit")
async def closure_submit(
    req_id: str,
    request: Request,
    note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = db.query(ReqModel).filter(ReqModel.id == req_id).first()
    if not req:
        raise HTTPException(404)

    if current_user.role not in ("admin", "mudur") and req.created_by != current_user.id:
        raise HTTPException(403, "Kapama başlatmak için yetkiniz yok.")
    if current_user.role == "asistan":
        raise HTTPException(403, "Kapama başlatmak için yetkiniz yok.")

    if req.status not in ("confirmed", "completed"):
        raise HTTPException(400, "Kapama yalnızca onaylanmış veya tamamlanmış referanslar için başlatılabilir.")

    if req.closure_request and req.closure_request.status in ("pending_manager", "pending_gm", "pending_finance"):
        raise HTTPException(400, "Bu referans zaten kapama onayında.")

    errors = _check_closure_prerequisites(req)
    if errors:
        return RedirectResponse(f"/requests/{req_id}?closure_error={';'.join(errors)}", status_code=303)

    if req.closure_request:
        db.delete(req.closure_request)
        db.flush()

    # Onay zincirini belirle
    submitter     = current_user
    mudur         = _find_mudur_in_chain(submitter, db)
    gm            = _find_gm(db)
    amount        = _get_confirmed_budget_total(req, db)
    needs_gm_flag = _needs_gm_step(mudur, amount, gm) if mudur else False

    cr = ClosureRequest(
        id=_uuid(),
        request_id=req_id,
        submitted_by=current_user.id,
        submitted_at=_now(),
        note=note,
        needs_gm=needs_gm_flag,
        status="pending_manager",
    )
    db.add(cr)
    req.status = "closing"
    db.commit()

    return RedirectResponse(f"/requests/{req_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /closure/{closure_id}/approve-l1  — Müdür onayı
# ---------------------------------------------------------------------------

@router.post("/closure/{closure_id}/approve-l1", name="closure_approve_l1")
async def closure_approve_l1(
    closure_id: str,
    request: Request,
    note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _can_approve_l1(current_user):
        raise HTTPException(403)

    cr = db.query(ClosureRequest).filter(ClosureRequest.id == closure_id).first()
    if not cr or cr.status != "pending_manager":
        raise HTTPException(400, "Bu adım için uygun durum değil.")

    cr.l1_approver_id = current_user.id
    cr.l1_approved_at = _now()
    cr.l1_note        = note
    cr.updated_at     = _now()

    # Tutar limiti aşıyorsa → GM onayına yönlendir
    if cr.needs_gm:
        cr.status = "pending_gm"
    else:
        cr.status = "pending_finance"

    db.commit()
    return RedirectResponse(f"/requests/{cr.request_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /closure/{closure_id}/approve-gm  — Genel Müdür onayı
# ---------------------------------------------------------------------------

@router.post("/closure/{closure_id}/approve-gm", name="closure_approve_gm")
async def closure_approve_gm(
    closure_id: str,
    request: Request,
    note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _can_approve_gm(current_user):
        raise HTTPException(403)

    cr = db.query(ClosureRequest).filter(ClosureRequest.id == closure_id).first()
    if not cr or cr.status != "pending_gm":
        raise HTTPException(400, "Bu adım için uygun durum değil.")

    cr.gm_approver_id = current_user.id
    cr.gm_approved_at = _now()
    cr.gm_note        = note
    cr.status         = "closed"
    cr.updated_at     = _now()

    req = cr.request
    req.status     = "closed"
    req.updated_at = _now()
    db.commit()

    return RedirectResponse(f"/requests/{cr.request_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /closure/{closure_id}/approve-final  — Muhasebe Müdürü kapanış
# ---------------------------------------------------------------------------

@router.post("/closure/{closure_id}/approve-final", name="closure_approve_final")
async def closure_approve_final(
    closure_id: str,
    request: Request,
    note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _can_approve_final(current_user):
        raise HTTPException(403)

    cr = db.query(ClosureRequest).filter(ClosureRequest.id == closure_id).first()
    if not cr or cr.status != "pending_finance":
        raise HTTPException(400, "Bu adım için uygun durum değil.")

    cr.l2_approver_id = current_user.id
    cr.l2_approved_at = _now()
    cr.l2_note        = note
    cr.status         = "closed"
    cr.updated_at     = _now()

    req = cr.request
    req.status     = "closed"
    req.updated_at = _now()
    db.commit()

    return RedirectResponse(f"/requests/{cr.request_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /closure/{closure_id}/reject  — Herhangi adımdan ret
# ---------------------------------------------------------------------------

@router.post("/closure/{closure_id}/reject", name="closure_reject")
async def closure_reject(
    closure_id: str,
    request: Request,
    rejection_note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cr = db.query(ClosureRequest).filter(ClosureRequest.id == closure_id).first()
    if not cr:
        raise HTTPException(404)

    if cr.status == "pending_manager" and not _can_approve_l1(current_user):
        raise HTTPException(403)
    if cr.status == "pending_gm" and not _can_approve_gm(current_user):
        raise HTTPException(403)
    if cr.status == "pending_finance" and not _can_approve_final(current_user):
        raise HTTPException(403)

    cr.rejection_note = rejection_note
    cr.rejected_by_id = current_user.id
    cr.rejected_at    = _now()
    cr.status         = "rejected"
    cr.updated_at     = _now()

    req = cr.request
    req.status     = "confirmed"
    req.updated_at = _now()
    db.commit()

    return RedirectResponse(f"/requests/{cr.request_id}", status_code=303)
