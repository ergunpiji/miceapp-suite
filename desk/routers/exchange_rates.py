"""
E-dem — Döviz Kuru Endpoint'leri
GET /exchange-rates/today  → TCMB'den günlük kurları çek
"""
from fastapi import APIRouter, Depends
from models import User
from auth import get_current_user
from utils.tcmb import fetch_today_rates

router = APIRouter(prefix="/exchange-rates", tags=["exchange_rates"])


@router.get("/today")
async def today_rates(current_user: User = Depends(get_current_user)):
    """Bugünkü TCMB satış kurlarını JSON olarak döner. Bütçe editörü AJAX ile çağırır."""
    return fetch_today_rates()
