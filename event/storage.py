"""
Dosya depolama abstraksiyon katmanı.

R2_ACCESS_KEY_ID env var'ı varsa Cloudflare R2'ye yazar/okur.
Yoksa local disk'e yazar (geliştirme ortamı).

Kullanım:
    from storage import save_upload, delete_upload, serve_upload

    key = save_upload(data_bytes, "invoices", "uuid.pdf")
    return serve_upload(key, "fatura.pdf")
    delete_upload(key)
"""
import os
from pathlib import Path

from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

_USE_R2 = bool(os.environ.get("R2_ACCESS_KEY_ID"))

if _USE_R2:
    import boto3  # type: ignore
    # miceapp suite kanonik env seti: R2_ENDPOINT / R2_BUCKET (eski isimler fallback)
    _endpoint = os.environ.get("R2_ENDPOINT") or (
        f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
        if os.environ.get("R2_ACCOUNT_ID") else None
    )
    _s3 = boto3.client(
        "s3",
        endpoint_url=_endpoint,
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )
    _BUCKET = os.environ.get("R2_BUCKET") or os.environ.get("R2_BUCKET_NAME")
    _PUB = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")
    print(f"[STORAGE] Cloudflare R2 aktif — bucket: {_BUCKET}", flush=True)
else:
    print("[STORAGE] ⚠️  R2 env var yok — local disk kullanılıyor", flush=True)


def save_upload(data: bytes, folder: str, filename: str, company_id: str | None = None) -> str:
    """Dosyayı saklar; göreli key döner (DB'de saklanır).

    company_id verilirse çok-kiracılı izolasyon için anahtar
    `companies/{company_id}/{folder}/{filename}` olur; verilmezse eski düz
    anahtar (`{folder}/{filename}`) — geriye uyum (mevcut DB kayıtları okunmaya
    devam eder). serve_upload tam anahtarı kullandığı için her ikisi de çalışır.
    """
    cid = (str(company_id).strip() if company_id else "")
    key = f"companies/{cid}/{folder}/{filename}" if cid else f"{folder}/{filename}"
    if _USE_R2:
        _s3.put_object(Bucket=_BUCKET, Key=key, Body=data)
    else:
        p = Path("static/uploads") / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return key


def delete_upload(key: str) -> None:
    """Dosyayı siler; hata olursa sessizce geçer."""
    if not key:
        return
    try:
        if _USE_R2:
            _s3.delete_object(Bucket=_BUCKET, Key=key)
        else:
            (Path("static/uploads") / key).unlink(missing_ok=True)
    except Exception:
        pass


def serve_upload(key: str, filename: str) -> FileResponse | RedirectResponse | StreamingResponse:
    """İndirme response'u döner."""
    if _USE_R2:
        if _PUB:
            return RedirectResponse(f"{_PUB}/{key}")
        obj = _s3.get_object(Bucket=_BUCKET, Key=key)
        return StreamingResponse(
            obj["Body"],
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    local = Path("static/uploads") / key
    return FileResponse(path=str(local), filename=filename, media_type="application/octet-stream")


def serve_upload_secure(key: str, filename: str, user):
    """İndirme response'u — `companies/{cid}/...` prefix'li anahtarda kiracı sahipliğini
    doğrular (desk get_file_url_secure deseni). Uymazsa 403; super_admin bypass.
    Düz (legacy, prefix'siz) anahtarlar serbest kalır — geriye uyum."""
    if key and key.startswith("companies/"):
        parts = key.split("/", 2)   # ["companies", "{cid}", "rest..."]
        file_cid = (parts[1] or "").strip() if len(parts) >= 2 else ""
        if file_cid and user is not None:
            is_super = getattr(user, "is_super_admin", False) or getattr(user, "role", "") == "super_admin"
            user_cid = getattr(user, "company_id", None)
            if not is_super and str(file_cid) != str(user_cid or ""):
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail="Bu dosyaya erişim yetkiniz yok.")
    return serve_upload(key, filename)
