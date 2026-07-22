"""Seed default visit types and bootstrap the first admin user.

Idempotent. Run after migrations:  python -m app.seed
"""
from sqlalchemy import select

from app.auth.security import hash_password
from app.config import settings
from app.db import SessionLocal
from app.models import User, VisitType

DEFAULT_VISIT_TYPES = [
    ("blood_test", "Esame del sangue"),
    ("xray", "Radiografia"),
    ("ct_scan", "TAC"),
    ("mri", "Risonanza magnetica"),
    ("ultrasound", "Ecografia"),
    ("ecg", "Elettrocardiogramma"),
    ("report", "Referto / Visita"),
    ("prescription", "Prescrizione / Ricetta"),
    ("vaccination", "Vaccinazione"),
    ("other", "Altro"),
]


def seed() -> None:
    db = SessionLocal()
    try:
        for key, label in DEFAULT_VISIT_TYPES:
            if not db.scalar(select(VisitType).where(VisitType.key == key)):
                db.add(VisitType(key=key, label=label))
        db.commit()

        if not db.scalar(select(User).where(User.email == settings.admin_email)):
            db.add(
                User(
                    email=settings.admin_email,
                    password_hash=hash_password(settings.admin_password),
                    is_admin=True,
                )
            )
            db.commit()
            print(f"Created admin user: {settings.admin_email}")
        else:
            print("Admin user already exists; skipping.")
        print("Seed complete.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
