from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from versal.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), default=None)
    first_name: Mapped[str | None] = mapped_column(String(255), default=None)
    last_name: Mapped[str | None] = mapped_column(String(255), default=None)
    phone: Mapped[str | None] = mapped_column(String(32), default=None)

    # guest / staff / admin
    role: Mapped[str] = mapped_column(String(16), default="guest")

    # «Мёртвые души»: блокировка Guest List после N неиспользованных билетов
    is_blocked_guest_list: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    missed_tickets: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tickets: Mapped[list[GuestTicket]] = relationship(back_populates="user")
    reservations: Mapped[list[TableReservation]] = relationship(back_populates="user")


class Event(Base):
    """Афиша: концерты и тематические вечеринки."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    price: Mapped[str | None] = mapped_column(String(128), default=None)
    poster_path: Mapped[str | None] = mapped_column(String(512), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class GuestTicket(Base):
    """QR-билет в Guest List: одноразовый, привязан к пользователю."""

    __tablename__ = "guest_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Подписанный токен, который кодируется в QR
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    party_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    # active / used / expired
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="tickets")


class TableReservation(Base):
    """Заявка на бронь стола."""

    __tablename__ = "table_reservations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    date_text: Mapped[str] = mapped_column(String(64))
    guests_count: Mapped[int] = mapped_column(Integer)
    wishes: Mapped[str | None] = mapped_column(Text, default=None)
    # new / confirmed / cancelled
    status: Mapped[str] = mapped_column(String(16), default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="reservations")


class AppConfig(Base):
    """Простой key-value конфиг: лимит Guest List, файл меню и т.д."""

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, default=None)
