from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = "sqlite:///./hr_agent.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
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
    from models import Base as ModelsBase  # noqa: F401
    ModelsBase.metadata.create_all(bind=engine)
    # Yeni kolon migrasyonu (mevcut DB için ALTER TABLE)
    _migrate_payroll_columns()


def _migrate_payroll_columns():
    """PayrollRecord tablosuna yeni kolonları ekler (varsa atlar)."""
    from sqlalchemy import text
    new_cols = [
        ("total_gross",                "FLOAT DEFAULT 0.0"),
        ("sgk_monthly_base",           "FLOAT DEFAULT 0.0"),
        ("gv_monthly_base",            "FLOAT DEFAULT 0.0"),
        ("cumulative_gv_base",         "FLOAT DEFAULT 0.0"),
        ("asgari_ucret_istisnasi_gv",  "FLOAT DEFAULT 0.0"),
        ("asgari_ucret_istisnasi_dv",  "FLOAT DEFAULT 0.0"),
        ("ele_gecen_ucret",            "FLOAT DEFAULT 0.0"),
        ("meal_allowance_ayni",        "FLOAT DEFAULT 0.0"),
    ]
    with engine.connect() as conn:
        for col, typedef in new_cols:
            try:
                conn.execute(text(f"ALTER TABLE payroll_records ADD COLUMN {col} {typedef}"))
                conn.commit()
            except Exception:
                pass  # kolon zaten var
