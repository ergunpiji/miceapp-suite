"""
Operasyon Ajanı — Veri Modelleri

Tüm ilişkili tablolar (uçuş, konaklama, transfer, kayıt) opsiyoneldir.
Bir katılımcı yalnızca temel bilgileriyle de var olabilir.
"""

import uuid
import secrets
from datetime import datetime, date
from config import now_tr
from sqlalchemy import (
    String, Integer, Float, Boolean, Date, DateTime,
    ForeignKey, Text, Enum as SAEnum
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def new_token() -> str:
    return secrets.token_urlsafe(12)


# ---------------------------------------------------------------------------
# Etkinlik
# ---------------------------------------------------------------------------
class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String, nullable=False)
    edem_request_id: Mapped[str | None] = mapped_column(String)
    edem_request_no: Mapped[str | None] = mapped_column(String)
    supplier_token: Mapped[str] = mapped_column(String, default=new_token, unique=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    venue: Mapped[str | None] = mapped_column(String)
    city: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_tr)

    participants: Mapped[list["Participant"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )

    @property
    def participant_count(self) -> int:
        return len(self.participants)

    @property
    def flight_count(self) -> int:
        return sum(1 for p in self.participants if p.flights)

    @property
    def accommodation_count(self) -> int:
        return sum(1 for p in self.participants if p.accommodation)

    @property
    def transfer_count(self) -> int:
        return sum(1 for p in self.participants if p.transfers)

    @property
    def missing_info_count(self) -> int:
        return sum(1 for p in self.participants if p.has_missing_info)


# ---------------------------------------------------------------------------
# Katılımcı (temel bilgiler — her zaman var)
# ---------------------------------------------------------------------------
class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), nullable=False)

    # Temel bilgiler
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    company: Mapped[str | None] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String)
    email: Mapped[str | None] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String)

    # Kayıt / yaka kartı
    badge_name: Mapped[str | None] = mapped_column(String)   # yoksa first_name + last_name
    dietary: Mapped[str | None] = mapped_column(String)       # vejetaryen, helal, vb.
    special_needs: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_tr)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_tr, onupdate=now_tr)

    # İlişkiler (hepsi opsiyonel)
    event: Mapped["Event"] = relationship(back_populates="participants")
    flights: Mapped[list["FlightRecord"]] = relationship(
        back_populates="participant",
        cascade="all, delete-orphan",
        foreign_keys="FlightRecord.participant_id"
    )
    accommodation: Mapped["AccommodationRecord | None"] = relationship(
        back_populates="participant",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="AccommodationRecord.participant_id"
    )
    transfers: Mapped[list["TransferRecord"]] = relationship(
        back_populates="participant",
        cascade="all, delete-orphan",
        foreign_keys="TransferRecord.participant_id"
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def display_badge(self) -> str:
        return self.badge_name or self.full_name

    @property
    def flight_in(self) -> "FlightRecord | None":
        return next((f for f in self.flights if f.direction == "in"), None)

    @property
    def flight_out(self) -> "FlightRecord | None":
        return next((f for f in self.flights if f.direction == "out"), None)

    @property
    def has_missing_info(self) -> bool:
        """Herhangi bir modül eksik veya kritik alan boşsa True döner."""
        for f in self.flights:
            if not f.flight_number:
                return True
        return False

    @property
    def status(self) -> str:
        """complete | warning | empty"""
        if self.has_missing_info:
            return "warning"
        if not self.flights and not self.accommodation:
            return "empty"
        return "complete"


# ---------------------------------------------------------------------------
# Uçuş Kaydı (opsiyonel)
# direction: 'in' = geliş, 'out' = dönüş
# ---------------------------------------------------------------------------
class FlightRecord(Base):
    __tablename__ = "flight_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), nullable=False)
    direction: Mapped[str] = mapped_column(SAEnum("in", "out", name="flight_direction"), nullable=False)

    flight_number: Mapped[str | None] = mapped_column(String)     # TK 2341
    airline: Mapped[str | None] = mapped_column(String)
    departure_airport: Mapped[str | None] = mapped_column(String)  # IST
    arrival_airport: Mapped[str | None] = mapped_column(String)    # AYT
    flight_date: Mapped[date | None] = mapped_column(Date)
    departure_time: Mapped[str | None] = mapped_column(String)     # "10:30"
    arrival_time: Mapped[str | None] = mapped_column(String)       # "12:05"
    seat: Mapped[str | None] = mapped_column(String)
    pnr: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)

    # Doğrulama (Claude ile)
    validation_status: Mapped[str | None] = mapped_column(String)   # 'ok' | 'warning' | 'error' | None
    validation_issues: Mapped[str | None] = mapped_column(Text)     # JSON list of issue strings
    validated_departure_time: Mapped[str | None] = mapped_column(String)  # Claude'un bulduğu doğru saat
    validated_arrival_time: Mapped[str | None] = mapped_column(String)
    validated_departure_airport: Mapped[str | None] = mapped_column(String)
    validated_arrival_airport: Mapped[str | None] = mapped_column(String)

    participant: Mapped["Participant"] = relationship(
        back_populates="flights",
        foreign_keys=[participant_id]
    )


# ---------------------------------------------------------------------------
# Konaklama Kaydı (opsiyonel)
# ---------------------------------------------------------------------------
class AccommodationRecord(Base):
    __tablename__ = "accommodation_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), nullable=False, unique=True)

    hotel: Mapped[str | None] = mapped_column(String)
    room_number: Mapped[str | None] = mapped_column(String)
    room_type: Mapped[str | None] = mapped_column(String)     # SGL, DBL, SUT, vb.
    roommate_id: Mapped[str | None] = mapped_column(ForeignKey("participants.id"))
    check_in: Mapped[date | None] = mapped_column(Date)
    check_out: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    # Giriş takibi
    checked_in: Mapped[bool] = mapped_column(Boolean, default=False)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime)
    checked_in_by: Mapped[str | None] = mapped_column(String)  # "PM" | "Tedarikçi: <ad>"

    participant: Mapped["Participant"] = relationship(
        back_populates="accommodation",
        foreign_keys=[participant_id]
    )
    roommate: Mapped["Participant | None"] = relationship(
        foreign_keys=[roommate_id]
    )

    @property
    def nights(self) -> int | None:
        if self.check_in and self.check_out:
            return (self.check_out - self.check_in).days
        return None


# ---------------------------------------------------------------------------
# Transfer Kaydı (opsiyonel)
# direction: 'in' = havalimanı→otel, 'out' = otel→havalimanı
# ---------------------------------------------------------------------------
class TransferRecord(Base):
    __tablename__ = "transfer_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), nullable=False)
    direction: Mapped[str] = mapped_column(SAEnum("in", "out", name="transfer_direction"), nullable=False)

    transfer_date: Mapped[date | None] = mapped_column(Date)
    pickup_time: Mapped[str | None] = mapped_column(String)    # "14:30"
    from_location: Mapped[str | None] = mapped_column(String)  # AYT Havalimanı
    to_location: Mapped[str | None] = mapped_column(String)    # Rixos Premium
    vehicle_group: Mapped[str | None] = mapped_column(String)  # Araç grubu (gruplamak için)
    notes: Mapped[str | None] = mapped_column(Text)

    # Biniş takibi
    boarded: Mapped[bool] = mapped_column(Boolean, default=False)
    boarded_at: Mapped[datetime | None] = mapped_column(DateTime)
    boarded_by: Mapped[str | None] = mapped_column(String)  # "PM" | "Tedarikçi: <ad>"

    # Uçuş bağlantısı (varsa — cascade için)
    linked_flight_id: Mapped[str | None] = mapped_column(ForeignKey("flight_records.id"))

    participant: Mapped["Participant"] = relationship(
        back_populates="transfers",
        foreign_keys=[participant_id]
    )
    linked_flight: Mapped["FlightRecord | None"] = relationship(foreign_keys=[linked_flight_id])


# ---------------------------------------------------------------------------
# Bildirim (PM'e gönderilen durum güncellemeleri)
# ---------------------------------------------------------------------------
class Notification(Base):
    __tablename__ = "oa_notifications"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), nullable=False)

    # Kimin için / kimden
    actor: Mapped[str] = mapped_column(String)          # "Tedarikçi: Otel Adı" | "PM"
    action: Mapped[str] = mapped_column(String)          # "checked_in" | "boarded"
    participant_name: Mapped[str] = mapped_column(String)
    detail: Mapped[str | None] = mapped_column(String)   # "Oda 204" | "Araç Grubu 1"

    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_tr)

    event: Mapped["Event"] = relationship()


# ---------------------------------------------------------------------------
# Günlük Program (Agenda)
# ---------------------------------------------------------------------------
SESSION_TYPES = {
    "plenary":   ("🎤", "Genel Oturum"),
    "workshop":  ("🛠", "Atölye / Workshop"),
    "break":     ("☕", "Kahve Molası"),
    "meal":      ("🍽", "Yemek"),
    "transfer":  ("🚌", "Transfer"),
    "ceremony":  ("🏆", "Tören / Sergi"),
    "other":     ("📌", "Diğer"),
}

class AgendaSession(Base):
    __tablename__ = "agenda_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), nullable=False)

    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[str | None] = mapped_column(String)   # "09:00"
    end_time: Mapped[str | None] = mapped_column(String)     # "10:30"
    title: Mapped[str] = mapped_column(String, nullable=False)
    session_type: Mapped[str] = mapped_column(String, default="other")
    hall: Mapped[str | None] = mapped_column(String)
    speaker: Mapped[str | None] = mapped_column(String)
    moderator: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    event: Mapped["Event"] = relationship()

    @property
    def type_icon(self) -> str:
        return SESSION_TYPES.get(self.session_type, ("📌", ""))[0]

    @property
    def type_label(self) -> str:
        return SESSION_TYPES.get(self.session_type, ("📌", self.session_type))[1]

    @property
    def duration_minutes(self) -> int | None:
        if not self.start_time or not self.end_time:
            return None
        try:
            sh, sm = map(int, self.start_time.split(":"))
            eh, em = map(int, self.end_time.split(":"))
            return (eh * 60 + em) - (sh * 60 + sm)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Tedarikçi Görev Planı
# ---------------------------------------------------------------------------
TASK_STATUSES = {
    "pending":   ("⏳", "Bekliyor",   "#fef3c7", "#92400e"),
    "confirmed": ("✅", "Onaylandı",  "#dcfce7", "#166534"),
    "done":      ("🏁", "Tamamlandı", "#e0f2fe", "#0369a1"),
    "cancelled": ("❌", "İptal",      "#fee2e2", "#991b1b"),
}

SUPPLIER_TASK_TYPES = [
    ("transfer",  "🚌 Transfer"),
    ("hotel",     "🏨 Konaklama"),
    ("technical", "🔧 Teknik"),
    ("catering",  "🍽 Yemek & İkram"),
    ("design",    "🎨 Tasarım & Baskı"),
    ("decor",     "💐 Dekor"),
    ("staff",     "👤 Personel"),
    ("other",     "📦 Diğer"),
]

class SupplierTask(Base):
    __tablename__ = "supplier_tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), nullable=False)

    supplier_name: Mapped[str] = mapped_column(String, nullable=False)
    supplier_type: Mapped[str] = mapped_column(String, default="other")
    task: Mapped[str] = mapped_column(String, nullable=False)
    task_date: Mapped[date | None] = mapped_column(Date)
    task_time: Mapped[str | None] = mapped_column(String)   # "09:00"
    status: Mapped[str] = mapped_column(String, default="pending")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_tr)

    event: Mapped["Event"] = relationship()

    @property
    def status_icon(self) -> str:
        return TASK_STATUSES.get(self.status, ("⏳", "", "", ""))[0]

    @property
    def status_label(self) -> str:
        return TASK_STATUSES.get(self.status, ("⏳", self.status, "", ""))[1]

    @property
    def status_bg(self) -> str:
        return TASK_STATUSES.get(self.status, ("", "", "#f1f5f9", "#374151"))[2]

    @property
    def status_color(self) -> str:
        return TASK_STATUSES.get(self.status, ("", "", "#f1f5f9", "#374151"))[3]


# ---------------------------------------------------------------------------
# Kullanıcı Erişim Tokeni
# E-dem'den davet edilen kullanıcılar bu token ile giriş yapar.
# ---------------------------------------------------------------------------
USER_ROLES = {
    "manager":     "Yönetici",
    "coordinator": "Koordinatör",
}

class UserToken(Base):
    __tablename__ = "user_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), nullable=False)
    token: Mapped[str] = mapped_column(String, unique=True, default=new_token)
    label: Mapped[str] = mapped_column(String, default="Yönetici")  # görünen isim
    role: Mapped[str] = mapped_column(String, default="manager")     # manager | coordinator
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_tr)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    event: Mapped["Event"] = relationship()
