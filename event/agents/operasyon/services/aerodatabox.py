"""
AeroDataBox API Entegrasyonu (RapidAPI üzerinden)
https://rapidapi.com/aedbx-aedbx/api/aerodatabox

Uçuş numarası + tarih → gerçek zamanlı kalkış/iniş havalimanı ve saatleri.
Ücretsiz plan: günlük 500 istek.

API key: RAPIDAPI_KEY değişkeni .env'de tanımlanmalı.
Tanımlı değilse servis None döner, üst katman Claude fallback'e geçer.
"""

import os
import re
import httpx
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "").strip()
RAPIDAPI_HOST = "aerodatabox.p.rapidapi.com"
BASE_URL = f"https://{RAPIDAPI_HOST}/flights/number"


def _parse_local_time(time_str: str | None) -> str | None:
    """
    "2024-01-15 10:30+03:00"  →  "10:30"
    "2024-01-15T10:30:00+03:00" → "10:30"
    """
    if not time_str:
        return None
    # HH:MM bul
    match = re.search(r'(\d{2}:\d{2})', time_str)
    return match.group(1) if match else None


def _normalize_flight_number(raw: str) -> str:
    """
    "TK 2341" → "TK2341"
    "tk2341"  → "TK2341"
    """
    cleaned = re.sub(r'\s+', '', raw.strip().upper())
    return cleaned


def lookup_flight_aerodatabox(flight_number: str, flight_date: str | None = None) -> dict | None:
    """
    AeroDataBox'tan uçuş detayı çeker.

    Döner:
        {
            airline, departure_airport, arrival_airport,
            departure_time, arrival_time,
            status,           # "Scheduled" | "Arrived" | "Departed" | ...
            confidence: "high",
            source: "aerodatabox",
            note
        }
    API key yoksa veya istek başarısızsa None döner.
    """
    if not RAPIDAPI_KEY:
        return None

    fn = _normalize_flight_number(flight_number)

    # Tarih yoksa bugünü kullan
    if not flight_date:
        from datetime import date
        flight_date = date.today().isoformat()

    url = f"{BASE_URL}/{fn}/{flight_date}"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": RAPIDAPI_HOST,
    }
    params = {
        "withAircraftImage": "false",
        "withLocation": "false",
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers, params=params)

        if resp.status_code == 404:
            return None
        if resp.status_code == 402:
            # Kota doldu
            return None
        resp.raise_for_status()

        data = resp.json()

        # API bir liste döndürür (aynı numaralı birden fazla sefer olabilir)
        if isinstance(data, list):
            if not data:
                return None
            flight = data[0]
        elif isinstance(data, dict):
            flight = data
        else:
            return None

        dep = flight.get("departure", {})
        arr = flight.get("arrival", {})

        dep_airport = (dep.get("airport") or {}).get("iata")
        arr_airport = (arr.get("airport") or {}).get("iata")

        # Önce actualTime, yoksa scheduledTime
        dep_time_raw = (
            (dep.get("actualTime") or {}).get("local")
            or (dep.get("scheduledTime") or {}).get("local")
        )
        arr_time_raw = (
            (arr.get("actualTime") or {}).get("local")
            or (arr.get("scheduledTime") or {}).get("local")
        )

        dep_time = _parse_local_time(dep_time_raw)
        arr_time = _parse_local_time(arr_time_raw)

        airline_name = (flight.get("airline") or {}).get("name")
        status = flight.get("status", "")

        return {
            "airline": airline_name,
            "departure_airport": dep_airport,
            "arrival_airport": arr_airport,
            "departure_time": dep_time,
            "arrival_time": arr_time,
            "status": status,
            "confidence": "high",
            "source": "aerodatabox",
            "note": f"AeroDataBox · {status}" if status else "AeroDataBox",
        }

    except httpx.HTTPStatusError as e:
        return None
    except Exception:
        return None


def check_flight_aerodatabox(
    flight_number: str | None,
    departure_airport: str | None,
    arrival_airport: str | None,
    flight_date: str | None,
    departure_time: str | None,
    arrival_time: str | None,
) -> dict | None:
    """
    Uçuşu AeroDataBox verisiyle karşılaştırarak doğrular.

    Döner:
        { status, issues, corrected, note }
    API key yoksa veya uçuş bulunamazsa None döner (Claude fallback için).
    """
    real = lookup_flight_aerodatabox(flight_number, flight_date)
    if not real:
        return None

    issues = []
    corrected = {}

    def _iata_match(a: str | None, b: str | None) -> bool:
        if not a or not b:
            return True   # bilinmeyen → hata sayma
        return a.strip().upper() == b.strip().upper()

    # Havalimanı kontrolü
    if real.get("departure_airport") and not _iata_match(departure_airport, real["departure_airport"]):
        issues.append(
            f"Kalkış havalimanı yanlış: {departure_airport} → doğrusu {real['departure_airport']}"
        )
        corrected["departure_airport"] = real["departure_airport"]

    if real.get("arrival_airport") and not _iata_match(arrival_airport, real["arrival_airport"]):
        issues.append(
            f"Varış havalimanı yanlış: {arrival_airport} → doğrusu {real['arrival_airport']}"
        )
        corrected["arrival_airport"] = real["arrival_airport"]

    # Saat kontrolü — 30 dakikadan fazla fark varsa uyar
    def _time_diff(t1: str | None, t2: str | None) -> int | None:
        if not t1 or not t2:
            return None
        try:
            h1, m1 = map(int, t1.split(":"))
            h2, m2 = map(int, t2.split(":"))
            return abs((h1 * 60 + m1) - (h2 * 60 + m2))
        except Exception:
            return None

    dep_diff = _time_diff(departure_time, real.get("departure_time"))
    if dep_diff is not None and dep_diff > 30:
        issues.append(
            f"Kalkış saati farklı: {departure_time} (kayıtlı) ↔ {real['departure_time']} (gerçek)"
        )
        corrected["departure_time"] = real["departure_time"]
    elif real.get("departure_time") and not departure_time:
        corrected["departure_time"] = real["departure_time"]

    arr_diff = _time_diff(arrival_time, real.get("arrival_time"))
    if arr_diff is not None and arr_diff > 30:
        issues.append(
            f"İniş saati farklı: {arrival_time} (kayıtlı) ↔ {real['arrival_time']} (gerçek)"
        )
        corrected["arrival_time"] = real["arrival_time"]
    elif real.get("arrival_time") and not arrival_time:
        corrected["arrival_time"] = real["arrival_time"]

    # Eksik alanları tamamla (sorun yoksa da)
    if real.get("departure_airport") and not departure_airport:
        corrected["departure_airport"] = real["departure_airport"]
    if real.get("arrival_airport") and not arrival_airport:
        corrected["arrival_airport"] = real["arrival_airport"]

    status = "error" if issues else "ok"
    # Sadece saat farkı varsa warning
    if issues and all("saati" in i for i in issues):
        status = "warning"

    return {
        "status": status,
        "issues": issues,
        "corrected": corrected,
        "note": f"AeroDataBox · {real.get('status', '')}",
    }
