"""
Uçuş Kodu → Detay Doldurma Servisi

Sadece uçuş numarası ve tarih verildiğinde Claude'un havacılık bilgisini
kullanarak kalkış/varış havalimanı ve tipik saatleri döndürür.

Gerçek zamanlı veri değil — yaygın rotalar için Claude'un eğitim verisine dayanır.
Doğrulama için uçuş doğrulama servisini kullanın.
"""

import json
import re
import anthropic
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
client = anthropic.Anthropic()

SYSTEM_PROMPT = """Sen bir havacılık uzmanısın. Verilen uçuş numarası ve tarihe göre
tipik uçuş bilgilerini döndür. Eğer bu uçuşu bilmiyorsan en azından havayolunu ve
IATA kodlarını çıkar.

ÇIKTI (sadece JSON, başka hiçbir şey ekleme):
{
  "airline": "havayolu adı (Türkçe)",
  "departure_airport": "IATA kodu (3 harf)",
  "arrival_airport": "IATA kodu (3 harf)",
  "departure_time": "HH:MM veya null",
  "arrival_time": "HH:MM veya null",
  "confidence": "high | medium | low",
  "note": "kısa not (Türkçe, max 60 karakter)"
}

Örnekler:
- TK2341: Türk Hava Yolları, IST→AYT
- PC1234: Pegasus Airlines
- XQ: SunExpress

Saatleri bilmiyorsan null döndür, uydurma.
"""


def lookup_flight(flight_number: str, flight_date: str | None = None) -> dict | None:
    """
    Uçuş numarasından detay çıkarır.
    Önce AeroDataBox API'yi dener (gerçek zamanlı), başarısız olursa Claude'a döner.
    Döner: { airline, departure_airport, arrival_airport,
              departure_time, arrival_time, confidence, note }
    None: lookup başarısız
    """
    if not flight_number or not flight_number.strip():
        return None

    # 1. AeroDataBox (gerçek zamanlı, yüksek güven)
    try:
        from services.aerodatabox import lookup_flight_aerodatabox
        result = lookup_flight_aerodatabox(flight_number, flight_date)
        if result:
            return result
    except Exception:
        pass

    # 2. Claude fallback (genel havacılık bilgisi)
    prompt = f"Uçuş: {flight_number.strip()}"
    if flight_date:
        prompt += f"\nTarih: {flight_date}"

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )
        text = message.content[0].text.strip()

        # JSON çıkar
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:-1])
        match = re.search(r"\{[\s\S]*?\}", text)
        if match:
            text = match.group(0)

        result = json.loads(text)
        return result
    except Exception:
        return None


def lookup_flights_batch(flights: list[dict]) -> dict[str, dict]:
    """
    Birden fazla uçuşu tek seferde sorgular.
    flights: [{ id, flight_number, flight_date }, ...]
    Döner: { id: lookup_result, ... }
    """
    if not flights:
        return {}

    lines = []
    for f in flights:
        lines.append(
            f"ID={f['id']} | {f.get('flight_number','?')} | {f.get('flight_date','?')}"
        )

    prompt = (
        "Aşağıdaki uçuşların detaylarını döndür. "
        "JSON array olarak her uçuş için bir obje: "
        "[{\"id\":\"...\", \"airline\":\"...\", \"departure_airport\":\"...\", "
        "\"arrival_airport\":\"...\", \"departure_time\":\"...\", "
        "\"arrival_time\":\"...\", \"confidence\":\"...\"}, ...]\n\n"
        + "\n".join(lines)
    )

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=SYSTEM_PROMPT.replace(
                "Verilen uçuş numarası ve tarihe göre",
                "Verilen uçuş numaraları ve tarihlerine göre her biri için"
            ),
            messages=[{"role": "user", "content": prompt}]
        )
        text = message.content[0].text.strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:-1])

        # JSON array bul
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1:
            results = json.loads(text[start:end+1])
            return {r["id"]: r for r in results if "id" in r}
    except Exception:
        pass
    return {}
