import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

_BASE = os.path.dirname(os.path.abspath(__file__))

# Öncelik: OA_DATABASE_URL → DATABASE_URL (Railway PostgreSQL) → local SQLite
_db_url = (
    os.getenv("OA_DATABASE_URL")
    or os.getenv("DATABASE_URL")
    or f"sqlite:///{os.path.join(_BASE, 'operasyon_agent.db')}"
)

# Railway postgres:// → postgresql:// (SQLAlchemy uyumu)
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)

DATABASE_URL = _db_url

_is_sqlite = DATABASE_URL.startswith("sqlite")
engine = create_engine(
    DATABASE_URL,
    **({"connect_args": {"check_same_thread": False}} if _is_sqlite else {}),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    import sys as _sys
    # E-dem içine mount edilince operasyon modülleri _oa.* adıyla sys.modules'ta,
    # standalone çalışınca düz "models" adıyla bulunur.
    _models = (
        _sys.modules.get("_oa.models")
        or _sys.modules.get("models")
    )
    if _models is not None:
        _models.Base.metadata.create_all(bind=engine)
    else:
        from models import Base as _B  # standalone fallback
        _B.metadata.create_all(bind=engine)
