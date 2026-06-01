"""
Taleplerim — Kullanıcının kendi gönderdiği tüm talepler tek sayfada.
Fatura talepleri, ön ödemeler, HBF formları.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Invoice, PrepaymentRequest, ExpenseReport, User
from templates_config import templates

router = APIRouter(prefix="/taleplerim", tags=["taleplerim"])

INVOICE_STATUS_LABEL = {
    "pending":       ("Muhasebe Bekliyor", "warning"),
    "approved":      ("Onaylandı",         "success"),
    "rejected":      ("Reddedildi",        "danger"),
    "cancelled":     ("İptal",             "secondary"),
}

PREPAYMENT_STATUS_LABEL = {
    "pending_gm":  ("GM Onayı Bekliyor", "warning"),
    "approved":    ("Onaylandı",         "info"),
    "paid":        ("Ödendi",            "success"),
    "rejected":    ("Reddedildi",        "danger"),
    "cancelled":   ("İptal",             "secondary"),
}

EXPENSE_STATUS_LABEL = {
    "draft":             ("Taslak",             "secondary"),
    "submitted":         ("Onay Bekliyor",       "warning"),
    "owner_approved":    ("Dosya Sahibi Onayladı","info"),
    "manager_approved":  ("Müdür Onayladı",      "info"),
    "approved":          ("GM Onayladı",          "primary"),
    "paid":              ("Ödendi",               "success"),
    "rejected":          ("Reddedildi",           "danger"),
    "cancelled":         ("İptal",                "secondary"),
}


@router.get("", response_class=HTMLResponse, name="my_requests")
async def my_requests(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # ── Fatura talepleri (bu kullanıcı tarafından oluşturulmuş) ──────────────
    invoices = (
        db.query(Invoice)
        .filter(Invoice.created_by == current_user.id)
        .order_by(Invoice.created_at.desc())
        .limit(50)
        .all()
    )

    # ── Ön ödeme talepleri ───────────────────────────────────────────────────
    prepayments = (
        db.query(PrepaymentRequest)
        .filter(PrepaymentRequest.requested_by == current_user.id)
        .order_by(PrepaymentRequest.requested_at.desc())
        .limit(50)
        .all()
    )

    # ── HBF talepleri ────────────────────────────────────────────────────────
    hbfs = (
        db.query(ExpenseReport)
        .filter(ExpenseReport.submitted_by == current_user.id)
        .order_by(ExpenseReport.created_at.desc())
        .limit(50)
        .all()
    )

    return templates.TemplateResponse(
        "my_requests/index.html",
        {
            "request":       request,
            "current_user":  current_user,
            "page_title":    "Taleplerim",
            "invoices":      invoices,
            "prepayments":   prepayments,
            "hbfs":          hbfs,
            "invoice_status_label":    INVOICE_STATUS_LABEL,
            "prepayment_status_label": PREPAYMENT_STATUS_LABEL,
            "expense_status_label":    EXPENSE_STATUS_LABEL,
        },
    )
