"""
Railway PRE-DEPLOY migration scripti (event).

Web process'inden TAMAMEN ayrı, tek seferlik çalışır:
- Eski deployment hizmet vermeye devam ederken arka planda koşar (kullanıcı 502 görmez).
- app.py / operasyon alt-app'i import EDİLMEZ → sys.modules takası yok, GIL/healthcheck
  baskısı yok, web event-loop'u açlık çekmez.
- SKIP_INIT_DB'ye BAKMAZ — her zaman migrate eder (web process SKIP_INIT_DB=1 ile init'i atlar).
- Hata olsa bile exit 0 → deploy'u BLOKE ETMEZ (migration'lar idempotent; eksik kalan
  sonraki deploy'da tamamlanır).

Railway: railway.json → deploy.preDeployCommand = "python migrate.py"
"""
import sys


def main() -> None:
    try:
        from database import (
            Base, engine, seed_data, migrate_db,
            _seed_event_company, _seed_org_titles_per_company,
            backfill_vendor_codes_and_po_nos,
        )
        try:
            Base.metadata.create_all(bind=engine)
            print("[migrate.py] create_all tamam.", flush=True)
        except Exception as e:
            print(f"[migrate.py] create_all atlandı: {e}", flush=True)
        for step in (migrate_db, seed_data, _seed_event_company,
                     _seed_org_titles_per_company, backfill_vendor_codes_and_po_nos):
            try:
                step()
                print(f"[migrate.py] {step.__name__} tamam.", flush=True)
            except Exception as e:
                print(f"[migrate.py] {step.__name__} atlandı: {e}", flush=True)
        print("[migrate.py] TAMAMLANDI.", flush=True)
    except Exception as e:
        # Hiçbir koşulda deploy'u bloke etme
        print(f"[migrate.py] genel hata (yok sayıldı): {e}", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
