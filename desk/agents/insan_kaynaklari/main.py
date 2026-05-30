"""
HR Ajanı — İnsan Kaynakları Yönetim Sistemi

Modüller:
  - Çalışan Yönetimi (özlük dosyaları)
  - Zimmet Takibi
  - İzin Yönetimi
  - Maaş & Bordro
  - Fazla Mesai
  - Yemek Kartı
  - Esnek Yan Haklar
  - In-App Bildirimler
"""
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

# Proje kökünü path'e ekle (seed import için)
sys.path.insert(0, str(Path(__file__).parent))

from database import SessionLocal, init_db
import templates_config  # noqa: F401 — filtreler burada kayıtlı

from routers import auth, employees, assets, leaves, notifications, payroll, benefits, dashboard, advances


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Seed verisi
    db = SessionLocal()
    try:
        from seed import seed_data
        seed_data(db)
    finally:
        db.close()
    yield


app = FastAPI(title="HR Ajanı — İnsan Kaynakları", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(employees.router)
app.include_router(assets.router)
app.include_router(leaves.router)
app.include_router(notifications.router)
app.include_router(payroll.router)
app.include_router(benefits.router)
app.include_router(advances.router)


@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")
