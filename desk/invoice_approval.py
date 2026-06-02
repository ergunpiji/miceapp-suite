"""
Fatura çok kademeli onay akışı.

Akış (muhasebe fatura girdikten sonra):
  1. Customer.owner_id (müşteri temsilcisi, satış kullanıcısı)
  2. temsilcinin manager_id'si (satış müdürü)
  3. GM (genel_mudur rolü)

Her kademede:
  - Tutar ≤ rolün onay limiti  → approved (zincir biter)
  - Tutar > limit               → bir üst kademeye gönder

Onay limitleri SystemSetting'da TL olarak tutulur:
  invoice_approval_limit_kullanici
  invoice_approval_limit_mudur
  invoice_approval_limit_genel_mudur
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session


def get_approval_limit(db: Session, role: str) -> float:
    """Rolün TL bazlı onay limitini SystemSetting'tan oku."""
    from models import SystemSetting
    if role not in ("kullanici", "mudur", "genel_mudur"):
        return 0.0
    row = db.query(SystemSetting).filter_by(
        key=f"invoice_approval_limit_{role}"
    ).first()
    try:
        return float(row.value) if row and row.value else 0.0
    except (ValueError, TypeError):
        return 0.0


def find_first_approver(db: Session, invoice) -> Optional[int]:
    """Fatura için ilk onaylayıcıyı belirler:
       1) Customer.owner_id (müşteri temsilcisi)
       2) Reference.owner_id (proje sahibi)
       3) Şirketin GM'i (genel_mudur rolündeki ilk active user)
       4) Şirketin admin'i (son çare)
    """
    from models import User, Customer, Reference
    # Komisyon: ÖNCE oluşturanın kendi müdürü onaylar (limit aşılırsa GM'e gider)
    if invoice.invoice_type == "komisyon" and invoice.created_by:
        creator = db.query(User).get(invoice.created_by)
        if creator and creator.manager_id:
            mgr = db.query(User).get(creator.manager_id)
            if mgr and mgr.active:
                return mgr.id
        # müdür yoksa aşağıdaki GM/admin fallback'e düşer
    if invoice.customer_id:
        cust = db.query(Customer).get(invoice.customer_id)
        if cust and cust.owner_id:
            owner = db.query(User).get(cust.owner_id)
            if owner and owner.active:
                return owner.id
    if invoice.ref_id:
        ref = db.query(Reference).get(invoice.ref_id)
        if ref and ref.owner_id:
            owner = db.query(User).get(ref.owner_id)
            if owner and owner.active:
                return owner.id
    # Fallback: aynı şirketin GM'i veya admin'i
    gm = db.query(User).filter(
        User.company_id == invoice.company_id,
        User.role.in_(("genel_mudur", "admin", "super_admin")),
        User.active == True,  # noqa: E712
    ).order_by(User.role.desc()).first()
    return gm.id if gm else None


def find_next_approver(db: Session, current_approver_id: int) -> Optional[int]:
    """Mevcut onaylayıcının üst kademesini bul:
       1) User.manager_id varsa onu
       2) Yoksa şirketin GM'i (genel_mudur)
       3) Yoksa admin
    """
    from models import User
    user = db.query(User).get(current_approver_id)
    if not user:
        return None
    if user.manager_id:
        mgr = db.query(User).get(user.manager_id)
        if mgr and mgr.active:
            return mgr.id
    # Manager yoksa şirketin GM'ine gönder
    gm = db.query(User).filter(
        User.company_id == user.company_id,
        User.role == "genel_mudur",
        User.active == True,  # noqa: E712
        User.id != user.id,
    ).first()
    if gm:
        return gm.id
    # GM yoksa admin'e
    admin = db.query(User).filter(
        User.company_id == user.company_id,
        User.role.in_(("admin", "super_admin")),
        User.active == True,  # noqa: E712
        User.id != user.id,
    ).first()
    return admin.id if admin else None


def start_approval(db: Session, invoice, accountant_user) -> None:
    """Muhasebe fatura yarattıktan sonra çağrılır.
    Onay zincirini başlatır + ilk onaylayıcıya bildirim gönderir."""
    invoice.approval_status = "onay_bekliyor"
    invoice.current_approver_id = find_first_approver(db, invoice)
    history = [{
        "action": "created",
        "user_id": accountant_user.id,
        "user_name": f"{accountant_user.name} {accountant_user.surname or ''}".strip(),
        "ts": datetime.utcnow().isoformat(),
        "amount": invoice.total_with_vat,
    }]
    invoice.approval_history = json.dumps(history, ensure_ascii=False)

    if invoice.current_approver_id:
        from notification_helper import notify
        notify(
            db,
            user_id=invoice.current_approver_id,
            title="Onayınızı bekleyen fatura",
            message=f"#{invoice.invoice_no or invoice.id} · "
                    f"{_money(invoice.total_with_vat)} TL · "
                    f"{accountant_user.name} tarafından girildi.",
            link=f"/invoices/{invoice.id}",
            notif_type="info",
            ref_id=invoice.id,
        )


def approve_step(db: Session, invoice, approver_user, note: str = "") -> tuple[bool, str]:
    """Bir kademeyi onayla. Limit dahilinde ise zincir biter.

    Returns: (success: bool, message: str)
    """
    # Yetki kontrolü
    if invoice.approval_status != "onay_bekliyor":
        return (False, "Bu fatura onay aşamasında değil.")
    if invoice.current_approver_id != approver_user.id and not approver_user.is_admin:
        return (False, "Bu faturanın onayı sizden beklenmiyor.")

    amount = invoice.total_with_vat or 0
    limit = get_approval_limit(db, approver_user.role)
    # admin/super_admin: sınırsız onay
    if approver_user.role in ("admin", "super_admin"):
        limit = float("inf")

    # Audit log
    try:
        history = json.loads(invoice.approval_history or "[]")
    except Exception:
        history = []
    history.append({
        "action": "approved",
        "user_id": approver_user.id,
        "user_name": f"{approver_user.name} {approver_user.surname or ''}".strip(),
        "user_role": approver_user.role,
        "limit": limit if limit != float("inf") else None,
        "amount": amount,
        "ts": datetime.utcnow().isoformat(),
        "note": note or None,
    })

    if amount <= limit:
        # Zincir biter — onay tamamlandı
        invoice.current_approver_id = None
        # Kesilen/komisyon TALEBİ henüz fatura no içermiyorsa → muhasebe KESİMİ bekliyor.
        # approval_status 'onay_bekliyor' + approver yok → listede "Fatura Kes" butonu çıkar.
        _needs_cut = (invoice.invoice_type in ("kesilen", "komisyon")
                      and not (invoice.invoice_no or "").strip())
        invoice.approval_status = "onay_bekliyor" if _needs_cut else "approved"
        invoice.approval_history = json.dumps(history, ensure_ascii=False)
        # Bildirim: faturayı yaratan kişiye
        from notification_helper import notify
        if invoice.created_by:
            _msg = ("onaylandı — muhasebe kesimi bekliyor"
                    if _needs_cut else "onaylandı")
            notify(
                db,
                user_id=invoice.created_by,
                title="Faturanız onaylandı",
                message=f"#{invoice.invoice_no or invoice.id} · "
                        f"{approver_user.name} ({approver_user.role}) tarafından {_msg}.",
                link=f"/invoices/{invoice.id}",
                notif_type="success",
                ref_id=invoice.id,
            )
        # Muhasebe kesimi bekliyorsa muhasebe ekibine de bildir
        if _needs_cut:
            from models import User as _U
            for _m in db.query(_U).filter(_U.company_id == invoice.company_id,
                                          _U.role.in_(("muhasebe", "muhasebe_muduru")),
                                          _U.active == True).all():  # noqa: E712
                notify(db, user_id=_m.id, title="Fatura kesilmeli",
                       message=f"Onaylanan {invoice.invoice_type} faturası kesim bekliyor · {_money(amount)} TL",
                       link=f"/invoices/{invoice.id}", notif_type="info", ref_id=invoice.id)
        return (True, "Onay tamamlandı." + (" Muhasebe kesimi bekliyor." if _needs_cut else ""))

    # Limit aştı → bir üst kademeye
    next_id = find_next_approver(db, approver_user.id)
    if not next_id:
        # Üst kademe yok → admin yetkisi gerek; admin yoksa hata
        return (False, "Tutar limiti aşıyor ama bir üst onaylayıcı bulunamadı.")

    invoice.current_approver_id = next_id
    history.append({
        "action": "escalated",
        "to_user_id": next_id,
        "ts": datetime.utcnow().isoformat(),
        "reason": f"Tutar limiti aşıyor ({amount:.2f} > {limit:.2f} TL)",
    })
    invoice.approval_history = json.dumps(history, ensure_ascii=False)

    from notification_helper import notify
    notify(
        db,
        user_id=next_id,
        title="Onayınızı bekleyen fatura",
        message=f"#{invoice.invoice_no or invoice.id} · "
                f"{_money(amount)} TL · "
                f"{approver_user.name} tarafından üst kademeye gönderildi.",
        link=f"/invoices/{invoice.id}",
        notif_type="info",
        ref_id=invoice.id,
    )
    return (True, "Tutar limiti aşıyor — üst kademeye iletildi.")


def reject_step(db: Session, invoice, approver_user, note: str) -> tuple[bool, str]:
    """Faturayı reddet. Zincir biter, muhasebeciye geri gönderilir."""
    if invoice.approval_status != "onay_bekliyor":
        return (False, "Bu fatura onay aşamasında değil.")
    if invoice.current_approver_id != approver_user.id and not approver_user.is_admin:
        return (False, "Bu faturanın reddi sizden beklenmiyor.")
    if not note or not note.strip():
        return (False, "Red gerekçesi zorunludur.")

    try:
        history = json.loads(invoice.approval_history or "[]")
    except Exception:
        history = []
    history.append({
        "action": "rejected",
        "user_id": approver_user.id,
        "user_name": f"{approver_user.name} {approver_user.surname or ''}".strip(),
        "ts": datetime.utcnow().isoformat(),
        "note": note,
    })
    invoice.approval_status = "reddedildi"
    invoice.approval_rejection_note = note
    invoice.current_approver_id = None
    invoice.approval_history = json.dumps(history, ensure_ascii=False)

    from notification_helper import notify
    if invoice.created_by:
        notify(
            db,
            user_id=invoice.created_by,
            title="Faturanız reddedildi",
            message=f"#{invoice.invoice_no or invoice.id} · "
                    f"{approver_user.name}: {note[:120]}",
            link=f"/invoices/{invoice.id}",
            notif_type="error",
            ref_id=invoice.id,
        )
    return (True, "Fatura reddedildi.")


def _money(v) -> str:
    try:
        return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(v)
