"""
Railway PRE-DEPLOY migration scripti (desk).

Web process'inden TAMAMEN ayrı, tek seferlik çalışır:
- Eski deployment hizmet verirken arka planda koşar (kullanıcı 502 görmez).
- app.py import EDİLMEZ → GIL/healthcheck baskısı yok.
- SKIP_INIT_DB'ye BAKMAZ — her zaman migrate eder (web SKIP_INIT_DB=1 ile init'i atlar).
- Hata olsa bile exit 0 → deploy'u BLOKE ETMEZ (idempotent; eksik kalan sonraki deploy'da).

Railway: railway.json → deploy.preDeployCommand = "python migrate.py"
"""
import sys


def main() -> None:
    try:
        from database import init_db
        init_db()
        print("[migrate.py] TAMAMLANDI.", flush=True)
    except Exception as e:
        print(f"[migrate.py] genel hata (yok sayıldı): {e}", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
