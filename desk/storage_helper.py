"""
Dosya depolama yardımcısı — Cloudflare R2 veya yerel fallback.

Env var'lar set edilmişse R2 kullanılır:
  R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
  R2_PUBLIC_URL  (opsiyonel — set edilmişse presigned URL üretilmez, doğrudan URL döner)

Set edilmemişse (yerel geliştirme) dosyalar static/{key} altına kaydedilir.
"""
from __future__ import annotations

import mimetypes
import os
import uuid

_ENDPOINT = os.environ.get("R2_ENDPOINT", "").strip()
_BUCKET   = os.environ.get("R2_BUCKET", "").strip()
_KEY_ID   = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
_SECRET   = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
_PUBLIC   = os.environ.get("R2_PUBLIC_URL", "").strip().rstrip("/")

R2_ENABLED: bool = bool(_ENDPOINT and _BUCKET and _KEY_ID and _SECRET)

if R2_ENABLED:
    print(f"[storage] R2 aktif — bucket={_BUCKET}", flush=True)
else:
    print(
        f"[storage] R2 devre dışı — ENDPOINT={'✓' if _ENDPOINT else '✗'} "
        f"BUCKET={'✓' if _BUCKET else '✗'} "
        f"KEY_ID={'✓' if _KEY_ID else '✗'} "
        f"SECRET={'✓' if _SECRET else '✗'}",
        flush=True,
    )


def _client():
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        endpoint_url=_ENDPOINT,
        aws_access_key_id=_KEY_ID,
        aws_secret_access_key=_SECRET,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def upload_file(content: bytes, key: str, content_type: str = "") -> str:
    """İçeriği R2'ye (veya yerel sisteme) yükle. key'i döndürür."""
    if not content_type:
        ext = os.path.splitext(key)[1].lower()
        content_type = mimetypes.types_map.get(ext, "application/octet-stream")
    if R2_ENABLED:
        try:
            _client().put_object(
                Bucket=_BUCKET,
                Key=key,
                Body=content,
                ContentType=content_type,
            )
            return key
        except Exception as exc:
            print(f"[R2] upload_file HATA — key={key} bucket={_BUCKET} endpoint={_ENDPOINT}: {exc}", flush=True)
            raise
    local = os.path.join("static", key)
    os.makedirs(os.path.dirname(local), exist_ok=True)
    with open(local, "wb") as f:
        f.write(content)
    return key


def get_file_url(key: str, expires: int = 3600) -> str:
    """Dosyaya erişim URL'i döndürür (R2 presigned veya /static/{key})."""
    if not key:
        return ""
    if R2_ENABLED:
        if _PUBLIC:
            return f"{_PUBLIC}/{key}"
        return _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": _BUCKET, "Key": key},
            ExpiresIn=expires,
        )
    return f"/static/{key}"


def delete_file(key: str) -> None:
    """Dosyayı R2'den veya yerel sistemden sil (hata yutulur)."""
    if not key:
        return
    try:
        if R2_ENABLED:
            _client().delete_object(Bucket=_BUCKET, Key=key)
        else:
            local = os.path.join("static", key)
            if os.path.exists(local):
                os.remove(local)
    except Exception:
        pass


def make_key(prefix: str, ext: str) -> str:
    """Benzersiz obje anahtarı üretir: prefix/{uuid}{ext}"""
    return f"{prefix}/{uuid.uuid4().hex}{ext}"


# ---------------------------------------------------------------------------
# Multi-tenant key prefix — şirket başına izolasyon (RBAC v2)
# ---------------------------------------------------------------------------

def company_key(company_id: int | None, kind: str, entity_id, ext: str = "") -> str:
    """Şirket prefix'li unique key üret.

    Örn: companies/3/uploads/invoices/127/abc123.pdf

    company_id None ise legacy `uploads/{kind}/{entity_id}/...` döner —
    eski sistemle uyumluluk için.
    """
    safe_ext = ext if not ext or ext.startswith(".") else f".{ext}"
    if not company_id:
        return f"uploads/{kind}/{entity_id}/{uuid.uuid4().hex}{safe_ext}"
    return f"companies/{company_id}/uploads/{kind}/{entity_id}/{uuid.uuid4().hex}{safe_ext}"


def get_file_url_secure(key: str, user, expires: int = 3600) -> str:
    """URL üretirken company-id sahipliğini doğrular.

    `companies/{id}/...` prefix'i taşıyan key için, user'ın şirketi farklıysa
    HTTPException(403) — super_admin bypass yapar.
    """
    if key and key.startswith("companies/"):
        parts = key.split("/", 3)  # ["companies", "{id}", "uploads", ...]
        if len(parts) >= 2:
            file_company_id = (parts[1] or "").strip()   # UUID string (miceapp suite)
            if file_company_id and user is not None:
                is_super = getattr(user, "is_super_admin", False) or getattr(user, "role", "") == "super_admin"
                user_cid = getattr(user, "company_id", None)
                if not is_super and str(file_company_id) != str(user_cid or ""):
                    from fastapi import HTTPException
                    raise HTTPException(
                        status_code=403,
                        detail="Bu dosyaya erişim yetkiniz yok.",
                    )
    return get_file_url(key, expires=expires)
