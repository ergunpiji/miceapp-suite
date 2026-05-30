"""
E-dem — Kütüphane
Referans bazlı otomatik belge arşivi ve iş akışı logu.

log_activity()   → diğer router'lardan çağrılan aktivite kaydı
save_document()  → BytesIO belgeyi diske yazıp kütüphane kaydı oluşturur
                   (teklif export, hesap dökümü, fatura belgesi vb.)
"""
import io
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import (
    Request as ReqModel, RequestDocument, ActivityLog, User,
    REQUEST_DOCUMENT_TYPE_LABELS,
)

router = APIRouter(prefix="/requests", tags=["library"])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "uploads", "library")
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Aktivite logu  (diğer router'lardan import edilerek çağrılır)
# ---------------------------------------------------------------------------

def log_activity(
    db: Session,
    request_id: str,
    event_type: str,
    title: str,
    detail: str = "",
    user_id: str | None = None,
) -> ActivityLog:
    """Referans aktivite akışına bir satır ekler. Commit çağırana bırakılır."""
    entry = ActivityLog(
        request_id=request_id,
        user_id=user_id,
        event_type=event_type,
        title=title,
        detail=detail,
    )
    db.add(entry)
    db.flush()
    return entry


# ---------------------------------------------------------------------------
# Belge kaydet  (BytesIO → disk + RequestDocument kaydı)
# ---------------------------------------------------------------------------

def save_document(
    db: Session,
    request_id: str,
    buf: io.BytesIO,
    doc_type: str,
    file_name: str,
    user_id: str | None = None,
) -> RequestDocument:
    """
    BytesIO buffer'ı diske yazar, RequestDocument kaydı oluşturur.
    Aynı doc_type için kaçıncı versiyon olduğunu otomatik hesaplar.
    Commit çağırana bırakılır.
    """
    # Kaçıncı versiyon?
    existing = (
        db.query(RequestDocument)
        .filter(
            RequestDocument.request_id == request_id,
            RequestDocument.doc_type == doc_type,
        )
        .count()
    )
    version = existing + 1

    dest_dir = os.path.join(UPLOAD_DIR, request_id)
    os.makedirs(dest_dir, exist_ok=True)

    safe_name = f"{doc_type}_v{version}_{file_name}"
    dest_path = os.path.join(dest_dir, safe_name)

    buf.seek(0)
    content = buf.read()
    with open(dest_path, "wb") as f:
        f.write(content)
    buf.seek(0)   # caller hâlâ stream edebilir

    type_label = REQUEST_DOCUMENT_TYPE_LABELS.get(doc_type, doc_type)
    doc_name   = f"{type_label} v{version}" if version > 1 else type_label

    doc = RequestDocument(
        request_id=request_id,
        uploaded_by=user_id or "",
        doc_type=doc_type,
        doc_name=doc_name,
        file_path=f"uploads/library/{request_id}/{safe_name}",
        file_name=file_name,
        file_size=len(content),
    )
    db.add(doc)
    db.flush()
    return doc


# ---------------------------------------------------------------------------
# İndirme endpoint'i
# ---------------------------------------------------------------------------

@router.get("/{req_id}/documents/{doc_id}/download", name="library_download_document")
async def download_document(
    req_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = db.query(RequestDocument).filter(
        RequestDocument.id == doc_id,
        RequestDocument.request_id == req_id,
    ).first()
    if not doc:
        raise HTTPException(404)

    disk_path = os.path.join(os.path.dirname(__file__), "..", "static", doc.file_path)
    if not os.path.isfile(disk_path):
        raise HTTPException(404, "Dosya bulunamadı")

    return FileResponse(
        disk_path,
        filename=doc.file_name,
        media_type="application/octet-stream",
    )
