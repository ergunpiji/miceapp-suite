"""
Cascade Güncelleme Servisi

Uçuş değiştiğinde bağlı transferi otomatik günceller.
Kural: Varış uçuşu → varış transferi saatini güncelle (arrival_time + 1 saat buffer)
       Dönüş uçuşu → dönüş transferini güncelle (departure_time - 2 saat)
"""

from sqlalchemy.orm import Session
from models import FlightRecord, TransferRecord
from datetime import datetime


def _add_minutes(time_str: str, minutes: int) -> str:
    """'HH:MM' formatında saat string'ine dakika ekle."""
    try:
        t = datetime.strptime(time_str, "%H:%M")
        total = t.hour * 60 + t.minute + minutes
        total = max(0, min(total, 23 * 60 + 59))
        return f"{total // 60:02d}:{total % 60:02d}"
    except Exception:
        return time_str


def update_transfer_from_flight(db: Session, flight: FlightRecord) -> TransferRecord | None:
    """
    Uçuş kaydedildiğinde/güncellendiğinde bağlı transferi cascade güncelle.
    Bağlı transfer yoksa oluşturmaz — sadece varsa günceller.
    """
    transfer = db.query(TransferRecord).filter(
        TransferRecord.participant_id == flight.participant_id,
        TransferRecord.direction == flight.direction,
        TransferRecord.linked_flight_id == flight.id
    ).first()

    if not transfer:
        # linked_flight_id olmayan ama aynı yönde transfer var mı?
        transfer = db.query(TransferRecord).filter(
            TransferRecord.participant_id == flight.participant_id,
            TransferRecord.direction == flight.direction,
            TransferRecord.linked_flight_id.is_(None)
        ).first()
        if not transfer:
            return None
        # Bağla
        transfer.linked_flight_id = flight.id

    # Transfer tarihini uçuş tarihiyle eşitle
    if flight.flight_date:
        transfer.transfer_date = flight.flight_date

    if flight.direction == "in":
        # Varış: havalimanından otele — uçuş iniş saatinden 1 saat sonra
        if flight.arrival_time:
            transfer.pickup_time = _add_minutes(flight.arrival_time, 60)
        if flight.arrival_airport:
            transfer.from_location = flight.arrival_airport

    elif flight.direction == "out":
        # Dönüş: otelden havalimanına — uçuş kalkış saatinden 2 saat önce
        if flight.departure_time:
            transfer.pickup_time = _add_minutes(flight.departure_time, -120)
        if flight.departure_airport:
            transfer.to_location = flight.departure_airport

    db.commit()
    return transfer


def cascade_summary(flight: FlightRecord, transfer: TransferRecord) -> dict:
    """Kullanıcıya gösterilecek cascade özeti."""
    return {
        "flight": f"{flight.flight_number} ({flight.flight_date})",
        "transfer_updated": True,
        "new_pickup_time": transfer.pickup_time,
        "direction": flight.direction,
    }
