"""
Veritabanı yedekleme — pg_dump → gzip → R2
POST /admin/backup-db  (super_admin only — full DB tüm şirketler içinde)

Multi-tenant izolasyon: Müşteri şirket admin'leri kendi şirketleri için
ayrı export endpoint kullanır (planlanan: /admin/company-export).
"""

import gzip
import os
import subprocess
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from auth import get_current_user
from models import User

router = APIRouter(tags=["admin"])


def require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem yalnızca süper admin tarafından yapılabilir (tüm şirket DB dump'ı).",
        )
    return current_user


@router.post("/admin/backup-db", name="admin_backup_db")
async def admin_backup_db(current_user: User = Depends(require_super_admin)):
    """pg_dump çalıştır → gzip → R2'ye yükle. Sadece super_admin."""
    import storage_helper

    if not storage_helper.R2_ENABLED:
        return JSONResponse(
            {"ok": False, "error": "R2 yapılandırılmamış — yedek hedefi yok."},
            status_code=400,
        )

    db_url = os.environ.get("DATABASE_URL", "")
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    # system/ prefix: company prefix'lerinden ayrı (multi-tenant izolasyon)
    key = f"system/backups/full_db_{timestamp}.sql.gz"

    try:
        if db_url.startswith("postgres"):
            from urllib.parse import urlparse
            parsed = urlparse(db_url)
            pg_env = os.environ.copy()
            if parsed.password:
                pg_env["PGPASSWORD"] = parsed.password  # process args'tan gizle
            args = ["pg_dump"]
            if parsed.hostname:
                args += ["-h", parsed.hostname]
            if parsed.port:
                args += ["-p", str(parsed.port)]
            if parsed.username:
                args += ["-U", parsed.username]
            db_name = parsed.path.lstrip("/")
            if db_name:
                args.append(db_name)
            result = subprocess.run(args, capture_output=True, timeout=120, env=pg_env)
            if result.returncode != 0:
                print(f"[admin_backup] pg_dump hatası: {result.stderr.decode()}", flush=True)
                return JSONResponse(
                    {"ok": False, "error": "Yedekleme başarısız. Sunucu loglarını kontrol edin."},
                    status_code=500,
                )
            content = gzip.compress(result.stdout)
        else:
            db_file = "satinalma.db"
            if not os.path.exists(db_file):
                return JSONResponse({"ok": False, "error": "SQLite dosyası bulunamadı."}, status_code=400)
            with open(db_file, "rb") as f:
                content = gzip.compress(f.read())

        storage_helper.upload_file(content, key, content_type="application/gzip")
        return JSONResponse({"ok": True, "key": key, "size_kb": len(content) // 1024})

    except Exception as exc:
        print(f"[admin_backup] Hata: {exc}", flush=True)
        return JSONResponse({"ok": False, "error": "Yedekleme sırasında hata oluştu."}, status_code=500)
