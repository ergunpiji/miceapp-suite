"""
Uçuş Doğrulama Servisi — Claude API ile

Verilen uçuş bilgilerini (numara, havalimanı, saat) Claude'a gönderir.
Claude'un bilgi kesim tarihi kapsamındaki uçuşlar için rota ve tipik saat
uyumunu kontrol eder; yanlış/tutarsız alanları işaretler.

NOT: Bu anlık gerçek zamanlı bir uçuş verisi kaynağı değildir.
Claude'un genel havacılık bilgisini kullanır. Tutarsızlıkları uyarır.
"""

import json
import anthropic
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
client = anthropic.Anthropic()

SYSTEM_PROMPT = """Sen bir havacılık uzmanı asistanısın. Sana bir uçuş kaydının detayları verilecek.
Görevin: Bu uçuş bilgilerini genel havacılık bilginle karşılaştırıp tutarsızlıkları tespit etmek.

Kontrol et:
1. Uçuş numarası + havayolu kodu eşleşiyor mu? (Örn: TK = Türk Hava Yolları, PC = Pegasus)
2. Kalkış ve varış havalimanı bu rota için mantıklı mı?
3. Belirtilen saatler bu rota için tipik uçuş süresiyle uyumlu mu?
4. Havalimanı kodları gerçek IATA kodları mı?

ÇIKTI (sadece JSON döndür, başka bir şey ekleme):
{
  "status": "ok" | "warning" | "error",
  "issues": ["sorun 1", "sorun 2"],
  "corrected": {
    "departure_airport": "doğru IATA kodu veya null",
    "arrival_airport": "doğru IATA kodu veya null",
    "departure_time": "HH:MM veya null (tipik kalkış saati biliniyorsa)",
    "arrival_time": "HH:MM veya null (tipik iniş saati biliniyorsa)"
  },
  "note": "kısa açıklama"
}

Eğer her şey tutarlıysa: status="ok", issues=[], corrected={...null değerler}
"""


def check_flight(
    flight_number: str | None,
    departure_airport: str | None,
    arrival_airport: str | None,
    flight_date: str | None,
    departure_time: str | None,
    arrival_time: str | None,
) -> dict:
    """
    Tek bir uçuşu doğrular.
    Önce AeroDataBox (gerçek veri), başarısız olursa Claude (genel bilgi).
    Döner: { status, issues, corrected, note }
    """
    if not flight_number:
        return {
            "status": "warning",
            "issues": ["Uçuş numarası girilmemiş"],
            "corrected": {},
            "note": ""
        }

    # 1. AeroDataBox ile gerçek veri doğrulaması
    try:
        from services.aerodatabox import check_flight_aerodatabox
        result = check_flight_aerodatabox(
            flight_number, departure_airport, arrival_airport,
            flight_date, departure_time, arrival_time
        )
        if result is not None:
            return result
    except Exception:
        pass

    # 2. Claude fallback
    prompt = f"""
Uçuş bilgileri:
- Uçuş numarası: {flight_number or '—'}
- Kalkış havalimanı: {departure_airport or '—'}
- Varış havalimanı: {arrival_airport or '—'}
- Tarih: {flight_date or '—'}
- Kalkış saati: {departure_time or '—'}
- İniş saati: {arrival_time or '—'}

Bu uçuşu doğrula.
"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",  # Hızlı ve ucuz — doğrulama için yeterli
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )
        text = message.content[0].text.strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:-1])
        return json.loads(text)
    except Exception as e:
        return {
            "status": "warning",
            "issues": [f"Doğrulama yapılamadı: {str(e)[:80]}"],
            "corrected": {},
            "note": ""
        }


def check_flights_batch(flights: list[dict]) -> list[dict]:
    """
    Birden fazla uçuşu doğrular.
    AeroDataBox API key varsa her uçuşu ayrı ayrı sorgular (gerçek veri).
    Key yoksa Claude ile toplu doğrulama yapar.
    flights: [{ id, flight_number, departure_airport, arrival_airport,
                flight_date, departure_time, arrival_time }, ...]
    Döner: [{ id, status, issues, corrected, note }, ...]
    """
    if not flights:
        return []

    # AeroDataBox denemesi (key varsa)
    try:
        from services.aerodatabox import check_flight_aerodatabox, RAPIDAPI_KEY
        if RAPIDAPI_KEY:
            results = []
            for f in flights:
                r = check_flight_aerodatabox(
                    f.get("flight_number"),
                    f.get("departure_airport"),
                    f.get("arrival_airport"),
                    f.get("flight_date"),
                    f.get("departure_time"),
                    f.get("arrival_time"),
                )
                if r is not None:
                    r["id"] = f["id"]
                    results.append(r)
                else:
                    # Bu uçuş bulunamadı — Claude ile tek tek dene
                    single = check_flight(
                        f.get("flight_number"),
                        f.get("departure_airport"),
                        f.get("arrival_airport"),
                        f.get("flight_date"),
                        f.get("departure_time"),
                        f.get("arrival_time"),
                    )
                    single["id"] = f["id"]
                    results.append(single)
            return results
    except Exception:
        pass

    # Claude toplu doğrulama

    # Claude toplu doğrulama (fallback)
    lines = []
    for i, f in enumerate(flights, 1):
        lines.append(
            f"{i}. ID={f['id']} | {f.get('flight_number','—')} | "
            f"{f.get('departure_airport','—')}→{f.get('arrival_airport','—')} | "
            f"Tarih:{f.get('flight_date','—')} | "
            f"Kalkış:{f.get('departure_time','—')} İniş:{f.get('arrival_time','—')}"
        )

    prompt = (
        "Aşağıdaki uçuşları doğrula. Her uçuş için ayrı bir JSON objesi içeren "
        "bir JSON array döndür. Her obje: { \"id\": \"...\", \"status\": \"...\", "
        "\"issues\": [...], \"corrected\": {...}, \"note\": \"...\" }\n\n"
        + "\n".join(lines)
    )

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            system=SYSTEM_PROMPT.replace(
                "Sana bir uçuş kaydının detayları verilecek.",
                "Sana birden fazla uçuş kaydı verilecek. Her biri için ayrı sonuç döndür."
            ),
            messages=[{"role": "user", "content": prompt}]
        )
        text = message.content[0].text.strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:-1])
        results = json.loads(text)
        if isinstance(results, list):
            return results
        return [results]
    except Exception as e:
        return [
            {"id": f["id"], "status": "warning",
             "issues": [f"Doğrulama hatası: {str(e)[:60]}"],
             "corrected": {}, "note": ""}
            for f in flights
        ]
