"""
Basit SMTP e-posta gönderimi. SMTP env vars boşsa sessizce atlar (log).
Submit gibi akışları email hatası nedeniyle bozmamak için her hata yutulur.
"""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Iterable, Optional, Union


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def is_configured() -> bool:
    # Resend (önerilen) VEYA SMTP yapılandırılmışsa True
    if _env("RESEND_API_KEY"):
        return True
    return bool(_env("SMTP_HOST") and (_env("SMTP_FROM") or _env("SMTP_USER")))


def _send_via_resend(to_list, subject, html_body, text_body) -> bool:
    """RESEND_API_KEY set ise Resend HTTP API ile gönder."""
    import httpx
    from_addr = _env("FROM_EMAIL") or _env("SMTP_FROM") or "miceapp <noreply@miceapp.net>"
    payload = {"from": from_addr, "to": to_list, "subject": subject, "html": html_body}
    if text_body:
        payload["text"] = text_body
    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {_env('RESEND_API_KEY')}"},
            json=payload, timeout=15,
        )
        if r.status_code < 300:
            print(f"[email] Resend ile gönderildi → {', '.join(to_list)} ({subject})", flush=True)
            return True
        print(f"[email] Resend hatası {r.status_code}: {r.text[:200]}", flush=True)
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"[email] Resend gönderme hatası: {exc}", flush=True)
        return False


def send_email(
    to_addrs: Union[str, Iterable[str]],
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
) -> bool:
    """Resend (varsa) veya SMTP ile e-posta gönder; yoksa False döner (sessiz)."""
    to_list = [to_addrs] if isinstance(to_addrs, str) else [a for a in to_addrs if a]
    if not to_list:
        return False

    # Önce Resend (önerilen) — başarısızsa SMTP'ye düşer
    if _env("RESEND_API_KEY"):
        if _send_via_resend(to_list, subject, html_body, text_body):
            return True

    host = _env("SMTP_HOST")
    if not host:
        print(f"[email] Resend yok/başarısız ve SMTP yok; e-posta atlandı: {subject}", flush=True)
        return False

    try:
        port = int(_env("SMTP_PORT", "587"))
    except ValueError:
        port = 587
    user = _env("SMTP_USER")
    password = _env("SMTP_PASSWORD")
    from_addr = _env("SMTP_FROM") or user
    use_tls = _env("SMTP_TLS", "1") != "0"

    if not from_addr:
        print(f"[email] SMTP_FROM/SMTP_USER tanımlı değil; e-posta atlandı: {subject}", flush=True)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_list)
    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            if use_tls:
                server.starttls()
            if user and password:
                server.login(user, password)
            server.sendmail(from_addr, to_list, msg.as_string())
        print(f"[email] gönderildi → {', '.join(to_list)} ({subject})", flush=True)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[email] gönderme hatası: {exc}", flush=True)
        return False
