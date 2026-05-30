"""
Finans Ajanı — Ana giriş noktası

Modüller:
  - Bütçe vs Gerçekleşen
  - Ödeme Planı / Nakit Akışı
  - Tedarikçi Ödeme Yönetimi
  - E-Fatura
  - Kasa (Giriş/Çıkış + Gün Sonu)
  - Raporlar (Gelir/Gider)
  - Kredi Kartı Takibi
"""
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(Path(__file__).parent / ".env")

from database import init_db
import templates_config  # noqa: F401 — filtreler burada kayıtlı

from routers import (
    dashboard,
    budget_actual,
    payments,
    suppliers,
    efatura,
    cashbook,
    reports,
    credit_cards,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Finans Ajanı", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(dashboard.router)
app.include_router(budget_actual.router)
app.include_router(payments.router)
app.include_router(suppliers.router)
app.include_router(efatura.router)
app.include_router(cashbook.router)
app.include_router(reports.router)
app.include_router(credit_cards.router)


@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")
