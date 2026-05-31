"""
HBF — Harcama Bildirim Formu yönetimi
"""

import json
import os
import shutil
import uuid
from datetime import date as _date, datetime
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

import storage_helper
from email_helper import send_email, is_configured as smtp_configured

_TMP_DIR = "static/uploads/hbf/tmp"  # Geçici dosyalar — yalnızca yerel
os.makedirs(_TMP_DIR, exist_ok=True)

ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".xlsx", ".xls", ".docx", ".doc"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

from auth import get_current_user, get_company_id
from database import get_db, generate_hbf_no
from models import (
    HBF, HBF_STATUS_LABELS, Employee, Reference,
    User, CashBook, BankAccount, GeneralExpense,
    GeneralExpenseCategory, CashEntry, BankMovement,
    PAYMENT_METHODS,
)
from notification_helper import notify
from templates_config import templates

router = APIRouter(prefix="/hbf", tags=["hbf"])


def _parse_items(items_json: str) -> tuple[list, float]:
    """
    items_json iki formatta gelebilir:
      - Yeni (gruplu): [{ref_id, ref_no, ref_title, items:[...]}]
      - Eski (düz):    [{description, amount, ...}]
    Her zaman gruplu listeyi döndürür (detay/liste şablonu için tutarlılık).
    """
    try:
        data = json.loads(items_json or "[]")
    except Exception:
        data = []
    if not data:
        return [], 0.0
    # Gruplu format tespiti: ilk elemanın "items" anahtarı varsa
    if isinstance(data[0], dict) and "items" in data[0]:
        sections = data
        total = sum(
            float(item.get("amount_with_vat", item.get("amount", 0)))
            for sec in sections
            for item in sec.get("items", [])
        )
        return sections, total
    # Eski düz format → tek anonim section olarak sar
    total = sum(float(i.get("amount_with_vat", i.get("amount", 0))) for i in data)
    return [{"ref_id": None, "ref_no": "", "ref_title": "", "items": data}], total


def _parse_refs(refs_json: str) -> tuple[list, int | None]:
    """refs_json → (list, first_ref_id)"""
    try:
        refs = json.loads(refs_json or "[]")
    except Exception:
        refs = []
    first_id = refs[0]["id"] if refs else None
    return refs, first_id


def _hbf_expense_category(db, company_id: str) -> int:
    cat = (
        db.query(GeneralExpenseCategory)
        .filter_by(name="HBF Harcaması", company_id=company_id)
        .first()
    )
    if not cat:
        parent = (
            db.query(GeneralExpenseCategory)
            .filter_by(name="Diğer", parent_id=None, company_id=company_id)
            .first()
        )
        cat = GeneralExpenseCategory(
            name="HBF Harcaması",
            company_id=company_id,
            parent_id=parent.id if parent else None,
            sort_order=99,
        )
        db.add(cat)
        db.flush()
    return cat.id


# ---------------------------------------------------------------------------
# Geçici yükleme yardımcısı
# ---------------------------------------------------------------------------

def _process_row_attachments(
    hbf_id: str,
    form_token: str,
    row_atts_input: dict,
    existing_atts: list,
) -> list:
    """
    row_atts_input: {row_id: {filename, original}}  — form'dan gelen
    existing_atts : mevcut attachments_json listesi
    Döner: yeni attachments listesi
    """
    existing_map = {a["row_id"]: a for a in existing_atts if a.get("row_id")}
    global_atts  = [a for a in existing_atts if not a.get("row_id")]
    new_atts     = list(global_atts)

    for row_id, att_info in row_atts_input.items():
        tmp_path = os.path.join(_TMP_DIR, form_token, att_info["filename"])
        if os.path.exists(tmp_path):
            _, ext = os.path.splitext(att_info["filename"])
            new_fn = f"{uuid.uuid4().hex}{ext}"
            # RBAC v2: company-scoped key (eski path'lerle uyumlu — sadece yeni yüklenenler)
            company_prefix = f"companies/{current_user.company_id}/" if current_user.company_id else ""
            r2_key = f"{company_prefix}uploads/hbf/{hbf_id}/{new_fn}"
            with open(tmp_path, "rb") as f:
                storage_helper.upload_file(f.read(), r2_key)
            os.remove(tmp_path)
            # Önceki dosyayı sil (satır değiştirildi)
            if row_id in existing_map:
                old_fn = existing_map[row_id]["filename"]
                storage_helper.delete_file(f"uploads/hbf/{hbf_id}/{old_fn}")
            new_atts.append({
                "row_id": row_id,
                "filename": new_fn,
                "original": att_info["original"],
                "uploaded_at": _date.today().isoformat(),
            })
        elif row_id in existing_map:
            new_atts.append(existing_map[row_id])

    # Tmp dizinini temizle
    tmp_dir = os.path.join(_TMP_DIR, form_token)
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return new_atts


# ---------------------------------------------------------------------------
# Geçici dosya yükleme (form kaydedilmeden önce)
# ---------------------------------------------------------------------------

@router.post("/tmp-upload", name="hbf_tmp_upload")
async def hbf_tmp_upload(
    file: UploadFile = File(...),
    form_token: str = Form(...),
    row_id: str = Form(...),
    current_user: User = Depends(get_current_user),
):
    _, ext = os.path.splitext(file.filename or "")
    ext = ext.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"Desteklenmeyen dosya türü: {ext}")

    tmp_dir = os.path.join(_TMP_DIR, form_token)
    os.makedirs(tmp_dir, exist_ok=True)

    # Satır başına tek dosya: row_id{ext} olarak sakla
    safe_name = f"{row_id}{ext}"
    dest = os.path.join(tmp_dir, safe_name)
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Dosya boyutu 50MB sınırını aşıyor.")
    with open(dest, "wb") as f:
        f.write(content)

    return JSONResponse({"filename": safe_name, "original": file.filename, "row_id": row_id})


# ---------------------------------------------------------------------------
# Liste
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="hbf_list")
async def hbf_list(
    request: Request,
    status_filter: str = "all",
    archived: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    show_archived = archived == "1"
    q = db.query(HBF).filter(HBF.company_id == cid)
    if show_archived:
        q = q.filter(HBF.deleted_at != None)  # noqa: E711
    else:
        q = q.filter(HBF.deleted_at == None)  # noqa: E711
        if current_user.has_role_min("genel_mudur"):
            pass
        elif current_user.has_role_min("mudur"):
            team_ids = [u.id for u in db.query(User).filter(User.manager_id == current_user.id).all()]
            team_ids.append(current_user.id)
            q = q.filter(HBF.created_by.in_(team_ids))
        else:
            q = q.filter(HBF.created_by == current_user.id)
        if status_filter != "all":
            q = q.filter(HBF.status == status_filter)
    forms = q.order_by(HBF.created_at.desc()).all()
    archived_count = db.query(HBF).filter(HBF.company_id == cid, HBF.deleted_at != None).count()  # noqa: E711
    return templates.TemplateResponse(
        "hbf/list.html",
        {
            "request": request, "current_user": current_user,
            "forms": forms, "status_filter": status_filter,
            "status_labels": HBF_STATUS_LABELS,
            "show_archived": show_archived,
            "archived_count": archived_count,
            "page_title": "Harcama Bildirimleri",
        },
    )


# ---------------------------------------------------------------------------
# Yeni HBF
# ---------------------------------------------------------------------------

def _refs_for_template(db, cid: int = None):
    q = db.query(Reference).filter(Reference.status == "aktif")
    if cid:
        q = q.filter(Reference.company_id == cid)
    refs = q.order_by(Reference.ref_no).all()
    return [{"id": r.id, "ref_no": r.ref_no, "title": r.title} for r in refs]


@router.get("/new", response_class=HTMLResponse, name="hbf_new_get")
async def hbf_new_get(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    employees = db.query(Employee).filter(Employee.active == True, Employee.company_id == cid).order_by(Employee.name).all()  # noqa: E712
    return templates.TemplateResponse(
        "hbf/form.html",
        {
            "request": request, "current_user": current_user,
            "hbf": None, "employees": employees,
            "refs_data": json.dumps(_refs_for_template(db, cid), ensure_ascii=False),
            "form_token": uuid.uuid4().hex,
            "existing_row_atts": "{}",
            "page_title": "Yeni Harcama Bildirimi",
        },
    )


@router.post("/new", name="hbf_new_post")
async def hbf_new_post(
    refs_json: str = Form("[]"),
    employee_id: str = Form(None),
    items_json: str = Form("[]"),
    notes: str = Form(""),
    action: str = Form("taslak"),
    form_token: str = Form(""),
    row_attachments_json: str = Form("{}"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    items, total = _parse_items(items_json)
    refs, first_ref_id = _parse_refs(refs_json)
    ref_nos = ", ".join(r["ref_no"] for r in refs) if refs else None
    hbf_status = "beklemede" if action == "gonder" else "taslak"
    hbf = HBF(
        hbf_no=generate_hbf_no(db),
        ref_id=first_ref_id,
        refs_json=refs_json if refs else None,
        employee_id=employee_id or None,
        title=ref_nos or "HBF",
        items_json=json.dumps(items, ensure_ascii=False),
        total_amount=total,
        status=hbf_status,
        notes=notes.strip() or None,
        created_by=current_user.id,
        company_id=cid,
    )
    db.add(hbf)
    db.flush()

    try:
        row_atts = json.loads(row_attachments_json or "{}")
    except Exception:
        row_atts = {}
    if row_atts and form_token:
        new_atts = _process_row_attachments(hbf.id, form_token, row_atts, [])
        if new_atts:
            hbf.attachments_json = json.dumps(new_atts, ensure_ascii=False)

    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf.id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Detay
# ---------------------------------------------------------------------------

@router.get("/{hbf_id}", response_class=HTMLResponse, name="hbf_detail")
async def hbf_detail(
    hbf_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    hbf = db.query(HBF).filter(HBF.id == hbf_id, HBF.company_id == cid).first()
    if not hbf:
        raise HTTPException(status_code=404)

    # Erişim: GM/Admin, oluşturan, veya ekibinden biri ise müdür
    hbf_creator = db.query(User).get(hbf.created_by)
    is_team_manager = (
        current_user.has_role_min("mudur")
        and hbf_creator
        and hbf_creator.manager_id == current_user.id
    )
    if not (current_user.has_role_min("genel_mudur") or
            hbf.created_by == current_user.id or is_team_manager):
        raise HTTPException(status_code=403)

    items, _ = _parse_items(hbf.items_json)
    refs, _ = _parse_refs(hbf.refs_json)
    cash_books = db.query(CashBook).filter(CashBook.company_id == cid).all()
    bank_accounts = db.query(BankAccount).filter(BankAccount.company_id == cid).all()

    kdv_haric = sum(
        float(item.get("amount_without_vat", item.get("amount", 0)))
        for sec in items for item in sec.get("items", [])
    )
    kdv_toplam = sum(
        float(item.get("vat_amount", 0))
        for sec in items for item in sec.get("items", [])
    )

    try:
        attachments = json.loads(hbf.attachments_json or "[]")
    except Exception:
        attachments = []
    row_attachments = {a["row_id"]: a for a in attachments if a.get("row_id")}
    global_attachments = [a for a in attachments if not a.get("row_id")]

    return templates.TemplateResponse(
        "hbf/detail.html",
        {
            "request": request, "current_user": current_user,
            "hbf": hbf, "items": items, "refs": refs,
            "hbf_creator": hbf_creator,
            "kdv_haric": kdv_haric, "kdv_toplam": kdv_toplam,
            "status_labels": HBF_STATUS_LABELS,
            "cash_books": cash_books, "bank_accounts": bank_accounts,
            "payment_methods": PAYMENT_METHODS,
            "today": _date.today(),
            "row_attachments": row_attachments,
            "global_attachments": global_attachments,
            "page_title": hbf.hbf_no,
        },
    )


# ---------------------------------------------------------------------------
# Düzenle (sadece taslak)
# ---------------------------------------------------------------------------

@router.get("/{hbf_id}/edit", response_class=HTMLResponse, name="hbf_edit_get")
async def hbf_edit_get(
    hbf_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    hbf = db.query(HBF).filter(HBF.id == hbf_id, HBF.company_id == cid).first()
    if not hbf or hbf.status != "taslak":
        raise HTTPException(status_code=404)
    if hbf.created_by != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403)
    employees = db.query(Employee).filter(Employee.active == True, Employee.company_id == cid).order_by(Employee.name).all()  # noqa: E712
    try:
        existing_atts = json.loads(hbf.attachments_json or "[]")
    except Exception:
        existing_atts = []
    existing_row_atts = {
        a["row_id"]: {"filename": a["filename"], "original": a["original"]}
        for a in existing_atts if a.get("row_id")
    }
    return templates.TemplateResponse(
        "hbf/form.html",
        {
            "request": request, "current_user": current_user,
            "hbf": hbf, "employees": employees,
            "refs_data": json.dumps(_refs_for_template(db, cid), ensure_ascii=False),
            "form_token": uuid.uuid4().hex,
            "existing_row_atts": json.dumps(existing_row_atts, ensure_ascii=False),
            "page_title": f"Düzenle — {hbf.hbf_no}",
        },
    )


@router.post("/{hbf_id}/edit", name="hbf_edit_post")
async def hbf_edit_post(
    hbf_id: str,
    refs_json: str = Form("[]"),
    employee_id: str = Form(None),
    items_json: str = Form("[]"),
    notes: str = Form(""),
    action: str = Form("taslak"),
    form_token: str = Form(""),
    row_attachments_json: str = Form("{}"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    hbf = db.query(HBF).filter(HBF.id == hbf_id, HBF.company_id == cid).first()
    if not hbf or hbf.status != "taslak":
        raise HTTPException(status_code=404)
    if hbf.created_by != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Bu HBF'yi düzenleme yetkiniz yok.")
    items, total = _parse_items(items_json)
    refs, first_ref_id = _parse_refs(refs_json)
    ref_nos = ", ".join(r["ref_no"] for r in refs) if refs else None
    hbf.refs_json = refs_json if refs else None
    hbf.ref_id = first_ref_id
    hbf.title = ref_nos or hbf.title or "HBF"
    hbf.employee_id = employee_id or None
    hbf.items_json = json.dumps(items, ensure_ascii=False)
    hbf.total_amount = total
    hbf.notes = notes.strip() or None
    if action == "gonder":
        hbf.status = "beklemede"

    try:
        row_atts = json.loads(row_attachments_json or "{}")
    except Exception:
        row_atts = {}
    if form_token:
        try:
            existing_atts = json.loads(hbf.attachments_json or "[]")
        except Exception:
            existing_atts = []
        new_atts = _process_row_attachments(hbf_id, form_token, row_atts, existing_atts)
        hbf.attachments_json = json.dumps(new_atts, ensure_ascii=False) if new_atts else hbf.attachments_json

    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Gönder (taslak → beklemede)
# ---------------------------------------------------------------------------

@router.post("/{hbf_id}/submit", name="hbf_submit")
async def hbf_submit(
    hbf_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    hbf = db.query(HBF).filter(HBF.id == hbf_id, HBF.company_id == cid).first()
    if not hbf or hbf.status != "taslak":
        raise HTTPException(status_code=404)
    if hbf.created_by != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Bu HBF'yi gönderme yetkiniz yok.")
    hbf.status = "beklemede"
    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Onayla / Reddet — iki aşamalı onay akışı
# ---------------------------------------------------------------------------

@router.post("/{hbf_id}/approve", name="hbf_approve")
async def hbf_approve(
    hbf_id: str,
    approval_note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    hbf = db.query(HBF).filter(HBF.id == hbf_id, HBF.company_id == cid).first()
    if not hbf:
        raise HTTPException(status_code=404)

    is_mudur = current_user.has_role_min("mudur")
    is_gm = current_user.has_role_min("genel_mudur")

    # HBF oluşturanın müdürü var mı?
    creator = db.query(User).get(hbf.created_by)
    has_manager = bool(creator and creator.manager_id)

    if hbf.status == "beklemede":
        if is_gm:
            # GM/Admin: has_manager yoksa doğrudan onayla, varsa da GM atlayarak onaylayabilir
            hbf.status = "onaylandi"
            hbf.approved_by = current_user.id
            hbf.approved_at = datetime.utcnow()
            hbf.approval_note = approval_note.strip() or None
        elif is_mudur:
            # Müdür: sadece kendi ekibini onaylayabilir (creator.manager_id == current_user.id)
            if not creator or creator.manager_id != current_user.id:
                raise HTTPException(status_code=403, detail="Bu HBF sizin ekibinize ait değil.")
            hbf.status = "mudur_onayladi"
            hbf.manager_approved_by = current_user.id
            hbf.manager_approved_at = datetime.utcnow()
            if approval_note.strip():
                hbf.approval_note = approval_note.strip()
        else:
            raise HTTPException(status_code=403)

    elif hbf.status == "mudur_onayladi":
        if not is_gm:
            raise HTTPException(status_code=403, detail="Bu aşamada sadece Genel Müdür onaylayabilir.")
        hbf.status = "onaylandi"
        hbf.approved_by = current_user.id
        hbf.approved_at = datetime.utcnow()
        hbf.approval_note = approval_note.strip() or None
    else:
        raise HTTPException(status_code=400, detail="Bu HBF onaylanamaz.")

    if hbf.status == "onaylandi":
        notify(db, hbf.created_by,
               title=f"HBF onaylandı: {hbf.hbf_no}",
               message=f"{current_user.name} harcama bildiriminizi onayladı.",
               link=f"/hbf/{hbf_id}", notif_type="success", ref_id=hbf_id)
        if smtp_configured() and creator and creator.email:
            app_url = os.environ.get("APP_URL", "")
            send_email(
                creator.email,
                f"HBF Onaylandı — {hbf.hbf_no}",
                f"<p>Sayın {creator.name},</p>"
                f"<p>Harcama bildirim formunuz (<b>{hbf.hbf_no}</b>) onaylanmıştır.</p>"
                f"<p>Tutar: <b>₺{hbf.total_amount:,.2f}</b></p>"
                + (f"<p>Not: {hbf.approval_note}</p>" if hbf.approval_note else "")
                + (f"<p><a href='{app_url}/hbf/{hbf_id}'>Detayı görüntüle</a></p>" if app_url else ""),
            )
    elif hbf.status == "mudur_onayladi":
        notify(db, hbf.created_by,
               title=f"HBF müdür onayında: {hbf.hbf_no}",
               message=f"{current_user.name} onayladı. GM onayı bekleniyor.",
               link=f"/hbf/{hbf_id}", notif_type="info", ref_id=hbf_id)
        if smtp_configured() and creator and creator.email:
            app_url = os.environ.get("APP_URL", "")
            send_email(
                creator.email,
                f"HBF Müdür Onayında — {hbf.hbf_no}",
                f"<p>Sayın {creator.name},</p>"
                f"<p>Harcama bildirim formunuz (<b>{hbf.hbf_no}</b>) müdürünüz tarafından onaylanmıştır. Genel Müdür onayı bekleniyor.</p>"
                f"<p>Tutar: <b>₺{hbf.total_amount:,.2f}</b></p>"
                + (f"<p><a href='{app_url}/hbf/{hbf_id}'>Detayı görüntüle</a></p>" if app_url else ""),
            )
    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{hbf_id}/reject", name="hbf_reject")
async def hbf_reject(
    hbf_id: str,
    approval_note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    hbf = db.query(HBF).filter(HBF.id == hbf_id, HBF.company_id == cid).first()
    if not hbf or hbf.status not in ("beklemede", "mudur_onayladi"):
        raise HTTPException(status_code=404)

    creator = db.query(User).get(hbf.created_by)
    is_gm = current_user.has_role_min("genel_mudur")
    is_mudur = current_user.has_role_min("mudur")

    if is_gm:
        pass  # her durumda reddedebilir
    elif is_mudur and hbf.status == "beklemede":
        if not creator or creator.manager_id != current_user.id:
            raise HTTPException(status_code=403, detail="Bu HBF sizin ekibinize ait değil.")
    else:
        raise HTTPException(status_code=403)

    hbf.status = "reddedildi"
    hbf.approved_by = current_user.id
    hbf.approved_at = datetime.utcnow()
    hbf.approval_note = approval_note.strip() or None
    notify(db, hbf.created_by,
           title=f"HBF reddedildi: {hbf.hbf_no}",
           message=f"{current_user.name} harcama bildiriminizi reddetti." + (f" Not: {approval_note.strip()}" if approval_note.strip() else ""),
           link=f"/hbf/{hbf_id}", notif_type="danger", ref_id=hbf_id)
    if smtp_configured() and creator and creator.email:
        app_url = os.environ.get("APP_URL", "")
        send_email(
            creator.email,
            f"HBF Reddedildi — {hbf.hbf_no}",
            f"<p>Sayın {creator.name},</p>"
            f"<p>Harcama bildirim formunuz (<b>{hbf.hbf_no}</b>) reddedilmiştir.</p>"
            f"<p>Tutar: <b>₺{hbf.total_amount:,.2f}</b></p>"
            + (f"<p>Red gerekçesi: {approval_note.strip()}</p>" if approval_note.strip() else "")
            + (f"<p><a href='{app_url}/hbf/{hbf_id}'>Detayı görüntüle</a></p>" if app_url else ""),
        )
    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Ödeme Kaydı (onaylandi → odendi)
# ---------------------------------------------------------------------------

@router.post("/{hbf_id}/pay", name="hbf_pay")
async def hbf_pay(
    hbf_id: str,
    pay_date: str = Form(""),
    payment_method: str = Form("banka"),
    bank_account_id: str = Form(None),
    cash_book_id: str = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # miceapp suite: HBF kapatma/ödeme adımı MUHASEBE'ye ait (admin de yapabilir)
    if not current_user.is_admin and current_user.role not in ("muhasebe", "muhasebe_muduru"):
        raise HTTPException(status_code=403, detail="Bu adım muhasebe tarafından yapılır.")
    cid = current_user.company_id
    hbf = db.query(HBF).filter(HBF.id == hbf_id, HBF.company_id == cid).first()
    if not hbf or hbf.status != "onaylandi":
        raise HTTPException(status_code=404)

    pdate = _date.fromisoformat(pay_date) if pay_date else _date.today()
    emp_name = hbf.employee.name if hbf.employee else "Çalışan"
    desc = f"HBF {hbf.hbf_no} — {emp_name}"

    # GeneralExpense kaydı
    cat_id = _hbf_expense_category(db, cid)
    ge = GeneralExpense(
        company_id=cid,
        category_id=cat_id,
        employee_id=hbf.employee_id,
        description=f"HBF {hbf.hbf_no}: {hbf.title}",
        amount=hbf.total_amount,
        expense_date=pdate,
        source="manual",
        created_by=current_user.id,
    )
    db.add(ge)
    db.flush()
    hbf.general_expense_id = ge.id

    # Kasa/Banka hareketi
    if payment_method == "nakit" and cash_book_id:
        db.add(CashEntry(
            company_id=cid,
            book_id=cash_book_id, entry_date=pdate,
            entry_type="cikis", amount=hbf.total_amount, description=desc,
        ))
    elif payment_method == "banka" and bank_account_id:
        db.add(BankMovement(
            company_id=cid,
            account_id=bank_account_id, movement_date=pdate,
            movement_type="cikis", amount=hbf.total_amount, description=desc,
        ))

    hbf.status = "odendi"
    hbf.paid_at = pdate
    hbf.payment_method = payment_method
    hbf.bank_account_id = bank_account_id if payment_method == "banka" else None
    hbf.cash_book_id = cash_book_id if payment_method == "nakit" else None
    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Sil (sadece taslak)
# ---------------------------------------------------------------------------

@router.post("/bulk-archive", name="hbf_bulk_archive")
async def hbf_bulk_archive(
    ids_json: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    if not current_user.has_role_min("mudur"):
        return JSONResponse({"ok": False, "error": "Yetersiz yetki"}, status_code=403)
    try:
        ids = json.loads(ids_json)
        if not isinstance(ids, list):
            raise ValueError
    except Exception:
        return JSONResponse({"ok": False, "error": "Geçersiz veri"}, status_code=400)

    TERMINAL = {"odendi", "reddedildi"}
    updated = 0
    skipped = 0
    for hid in ids:
        hbf = db.query(HBF).filter(
            HBF.id == int(hid), HBF.company_id == cid, HBF.deleted_at == None  # noqa: E711
        ).first()
        if not hbf:
            continue
        if hbf.status not in TERMINAL:
            skipped += 1
            continue
        hbf.deleted_at = datetime.utcnow()
        hbf.deleted_by = current_user.id
        updated += 1
    db.commit()
    msg = None
    if skipped:
        msg = f"{skipped} HBF henüz kapanmadığı için arşivlenmedi (ödendi veya reddedildi olmalı)."
    return JSONResponse({"ok": True, "archived": updated, "skipped": skipped, "msg": msg})


@router.post("/{hbf_id}/unarchive", name="hbf_unarchive")
async def hbf_unarchive(
    hbf_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    if not current_user.has_role_min("mudur"):
        raise HTTPException(status_code=403)
    hbf = db.query(HBF).filter(HBF.id == hbf_id, HBF.company_id == cid).first()
    if not hbf:
        raise HTTPException(status_code=404)
    hbf.deleted_at = None
    hbf.deleted_by = None
    db.commit()
    return RedirectResponse(url="/hbf?archived=1", status_code=status.HTTP_302_FOUND)


@router.post("/{hbf_id}/delete", name="hbf_delete")
async def hbf_delete(
    hbf_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    hbf = db.query(HBF).filter(HBF.id == hbf_id, HBF.company_id == cid).first()
    if hbf and (hbf.created_by == current_user.id or current_user.is_admin):
        if hbf.status == "taslak":
            db.delete(hbf)
            db.commit()
    return RedirectResponse(url="/hbf", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Belge Yükle / Sil
# ---------------------------------------------------------------------------

@router.post("/{hbf_id}/upload", name="hbf_upload")
async def hbf_upload(
    hbf_id: str,
    file: UploadFile = File(...),
    row_id: str = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    hbf = db.query(HBF).filter(HBF.id == hbf_id, HBF.company_id == cid).first()
    if not hbf:
        raise HTTPException(status_code=404)
    if not (current_user.is_admin or current_user.is_approver or hbf.created_by == current_user.id):
        raise HTTPException(status_code=403)

    _, ext = os.path.splitext(file.filename or "")
    ext = ext.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"Desteklenmeyen dosya türü: {ext}")

    safe_name = f"{uuid.uuid4().hex}{ext}"
    # RBAC v2: company-scoped key
    company_prefix = f"companies/{current_user.company_id}/" if current_user.company_id else ""
    r2_key = f"{company_prefix}uploads/hbf/{hbf_id}/{safe_name}"
    content = await file.read()
    storage_helper.upload_file(content, r2_key)

    try:
        attachments = json.loads(hbf.attachments_json or "[]")
    except Exception:
        attachments = []

    new_att = {
        "filename": safe_name,
        "original": file.filename,
        "uploaded_at": _date.today().isoformat(),
    }
    if row_id:
        new_att["row_id"] = row_id
        # Aynı satıra ait önceki dosyayı sil (replace semantics)
        for old in [a for a in attachments if a.get("row_id") == row_id]:
            storage_helper.delete_file(f"uploads/hbf/{hbf_id}/{old['filename']}")
        attachments = [a for a in attachments if a.get("row_id") != row_id]

    attachments.append(new_att)
    hbf.attachments_json = json.dumps(attachments, ensure_ascii=False)
    db.commit()
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{hbf_id}/attachment/{filename}/delete", name="hbf_attachment_delete")
async def hbf_attachment_delete(
    hbf_id: str,
    filename: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    hbf = db.query(HBF).filter(HBF.id == hbf_id, HBF.company_id == cid).first()
    if not hbf:
        raise HTTPException(status_code=404)
    if not (current_user.is_admin or hbf.created_by == current_user.id):
        raise HTTPException(status_code=403)

    try:
        attachments = json.loads(hbf.attachments_json or "[]")
    except Exception:
        attachments = []
    attachments = [a for a in attachments if a["filename"] != filename]
    hbf.attachments_json = json.dumps(attachments, ensure_ascii=False)
    db.commit()

    storage_helper.delete_file(f"uploads/hbf/{hbf_id}/{filename}")
    return RedirectResponse(url=f"/hbf/{hbf_id}", status_code=status.HTTP_302_FOUND)
