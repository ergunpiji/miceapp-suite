"""
Satış — Kesilen Fatura Talepleri
Satış ekibi muhasebeye "bu müşteriye fatura kesin" talebi açar.
Muhasebe faturayı keser ve invoice_id bağlar.
"""

from datetime import datetime
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, get_company_id, require_module
from access_policy import visible_sales_requests_query, visible_references_query, visible_customers_query
from database import get_db
from models import SalesInvoiceRequest, Customer, Reference, Invoice, User, VAT_RATES
from notification_helper import notify
from templates_config import templates

router = APIRouter(prefix="/sales/invoice-requests", tags=["sales_requests"])


def _enrich(db: Session, sreqs: list) -> list:
    """İlişkili objeleri (customer, reference, requester, invoice) manual yükle.
    SalesInvoiceRequest FK constraint içermiyor (tip uyumsuzluğu), bu nedenle
    ORM relationship yerine bu yardımcı kullanılır."""
    # Batch load — N+1 önlemi
    cust_ids = list({s.customer_id for s in sreqs if s.customer_id})
    ref_ids  = list({s.ref_id      for s in sreqs if s.ref_id})
    user_ids = list({s.requested_by for s in sreqs if s.requested_by})
    inv_ids  = list({s.invoice_id   for s in sreqs if s.invoice_id})

    customers  = {str(c.id): c for c in db.query(Customer).filter(Customer.id.in_(cust_ids)).all()} if cust_ids else {}
    references = {str(r.id): r for r in db.query(Reference).filter(Reference.id.in_(ref_ids)).all()} if ref_ids else {}
    users      = {str(u.id): u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    invoices   = {str(i.id): i for i in db.query(Invoice).filter(Invoice.id.in_(inv_ids)).all()} if inv_ids else {}

    for s in sreqs:
        s.customer  = customers.get(str(s.customer_id))
        s.reference = references.get(str(s.ref_id)) if s.ref_id else None
        s.requester = users.get(str(s.requested_by))
        s.invoice   = invoices.get(str(s.invoice_id)) if s.invoice_id else None
    return sreqs


@router.get("", response_class=HTMLResponse, name="sales_requests_list")
async def sales_requests_list(
    request: Request,
    status_filter: str = "",
    current_user: User = Depends(require_module("sales_requests")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    q = visible_sales_requests_query(db, current_user)
    if status_filter:
        q = q.filter(SalesInvoiceRequest.status == status_filter)
    reqs = q.order_by(SalesInvoiceRequest.created_at.desc()).all()
    _enrich(db, reqs)
    return templates.TemplateResponse(
        "sales/invoice_requests.html",
        {
            "request": request,
            "current_user": current_user,
            "requests": reqs,
            "status_filter": status_filter,
            "page_title": "Fatura Talepleri",
        },
    )


@router.get("/new", response_class=HTMLResponse, name="sales_request_new_get")
async def sales_request_new_get(
    request: Request,
    current_user: User = Depends(require_module("sales_requests", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    customers = (
        visible_customers_query(db, current_user)
        .filter(Customer.active == True)  # noqa: E712
        .order_by(Customer.name)
        .all()
    )
    refs = (
        visible_references_query(db, current_user)
        .filter(Reference.status == "aktif")
        .order_by(Reference.ref_no)
        .all()
    )
    return templates.TemplateResponse(
        "sales/invoice_request_form.html",
        {
            "request": request,
            "current_user": current_user,
            "sreq": None,
            "customers": customers,
            "refs": refs,
            "vat_rates": VAT_RATES,
            "page_title": "Yeni Fatura Talebi",
        },
    )


@router.post("/new", name="sales_request_new_post")
async def sales_request_new_post(
    request: Request,
    customer_id: str = Form(...),
    ref_id: str = Form(None),
    description: str = Form(...),
    amount: float = Form(...),
    vat_rate: float = Form(20.0),
    notes: str = Form(""),
    current_user: User = Depends(require_module("sales_requests", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    sreq = SalesInvoiceRequest(
        customer_id=customer_id,
        ref_id=ref_id or None,
        description=description.strip(),
        amount=amount,
        vat_rate=vat_rate,
        notes=notes.strip(),
        requested_by=current_user.id,
        status="beklemede",
        company_id=cid,
    )
    db.add(sreq)
    db.commit()

    # Muhasebe departmanındaki kullanıcılara bildirim
    from models import UserDepartment, Department
    acct_dept = db.query(Department).filter(
        Department.company_id == cid,
        Department.key == "accounting",
    ).first()
    if acct_dept:
        acct_users = (
            db.query(User)
            .join(UserDepartment, User.id == UserDepartment.user_id)
            .filter(UserDepartment.department_id == acct_dept.id, User.active == True)  # noqa: E712
            .all()
        )
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        for u in acct_users:
            notify(
                db, u.id,
                title="Yeni Fatura Talebi",
                message=f"{current_user.name} {customer.name if customer else ''} için fatura talebi açtı.",
                link=f"/sales/invoice-requests/{sreq.id}",
                notif_type="info",
            )
    db.commit()
    return RedirectResponse(url="/sales/invoice-requests", status_code=status.HTTP_302_FOUND)


@router.get("/{sreq_id}", response_class=HTMLResponse, name="sales_request_detail")
async def sales_request_detail(
    sreq_id: str,
    request: Request,
    current_user: User = Depends(require_module("sales_requests")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    sreq = (
        visible_sales_requests_query(db, current_user)
        .filter(SalesInvoiceRequest.id == sreq_id)
        .first()
    )
    if not sreq:
        raise HTTPException(404)
    _enrich(db, [sreq])
    invoices_list = db.query(Invoice).filter(Invoice.company_id == cid).order_by(Invoice.invoice_date.desc()).limit(50).all()
    return templates.TemplateResponse(
        "sales/invoice_request_detail.html",
        {
            "request": request,
            "current_user": current_user,
            "sreq": sreq,
            "invoices_list": invoices_list,
            "page_title": f"Fatura Talebi — {sreq.description[:30]}",
        },
    )


@router.post("/{sreq_id}/complete", name="sales_request_complete")
async def sales_request_complete(
    sreq_id: str,
    invoice_id: str = Form(...),
    current_user: User = Depends(require_module("sales_requests", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """Muhasebe faturayı kesti ve invoice_id'yi bağlıyor."""
    if not current_user.has_department_key("accounting") and not current_user.is_admin:
        raise HTTPException(403, "Yalnızca muhasebe bu işlemi yapabilir.")
    sreq = db.query(SalesInvoiceRequest).filter(
        SalesInvoiceRequest.id == sreq_id,
        SalesInvoiceRequest.company_id == cid,
    ).first()
    if not sreq:
        raise HTTPException(404)
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.company_id == cid).first()
    if not inv:
        raise HTTPException(404, "Fatura bulunamadı.")

    sreq.invoice_id = invoice_id
    sreq.status = "islendi"
    db.commit()

    notify(
        db, sreq.requested_by,
        title="Fatura Talebi İşlendi",
        message=f"Talebiniz işlendi. Fatura No: {inv.invoice_no or inv.id}",
        link=f"/invoices/{invoice_id}",
        notif_type="success",
    )
    db.commit()
    return RedirectResponse(url=f"/sales/invoice-requests/{sreq_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{sreq_id}/cancel", name="sales_request_cancel")
async def sales_request_cancel(
    sreq_id: str,
    current_user: User = Depends(require_module("sales_requests", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    sreq = (
        visible_sales_requests_query(db, current_user)
        .filter(SalesInvoiceRequest.id == sreq_id)
        .first()
    )
    if not sreq:
        raise HTTPException(404)
    if sreq.status != "beklemede":
        raise HTTPException(400, "Yalnızca beklemedeki talepler iptal edilebilir.")
    sreq.status = "iptal"
    db.commit()
    return RedirectResponse(url="/sales/invoice-requests", status_code=status.HTTP_302_FOUND)
