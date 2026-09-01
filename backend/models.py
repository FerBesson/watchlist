from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint, Boolean, Float
from sqlalchemy.orm import relationship
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    google_id = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    picture = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    watchlists = relationship("Watchlist", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")


class Watchlist(Base):
    __tablename__ = "watchlists"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String, index=True, nullable=False)
    description = Column(String, nullable=True)
    # Comma-separated list of metrics/columns to show, e.g., "sector,price,prev_close,change"
    metrics = Column(String, default="sector,price,prev_close,change", nullable=False)
    order = Column(Integer, default=0, nullable=False)    # Sorting sequence index for watchlists in sidebar

    user = relationship("User", back_populates="watchlists")
    items = relationship("WatchlistItem", back_populates="watchlist", order_by="WatchlistItem.order", cascade="all, delete-orphan")


    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_watchlist_name"),
    )


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id = Column(Integer, primary_key=True, index=True)
    watchlist_id = Column(Integer, ForeignKey("watchlists.id"), nullable=False)
    symbol = Column(String, index=True, nullable=False)  # Ticker symbol (e.g. AAPL) OR section title if is_divider is True
    name = Column(String, nullable=True)                  # Cached company name (e.g. Apple Inc.)
    sector = Column(String, nullable=True)                # Cached company sector (e.g. Technology)
    notes = Column(String, nullable=True)
    is_divider = Column(Boolean, default=False, nullable=False) # True if this item is a TradingView-style section divider
    order = Column(Integer, default=0, nullable=False)    # Numeric sorting sequence for dividers and stocks
    added_at = Column(DateTime, default=datetime.utcnow)

    watchlist = relationship("Watchlist", back_populates="items")

    # A stock symbol or divider should be unique within a single watchlist
    __table_args__ = (
        UniqueConstraint("watchlist_id", "symbol", name="uq_watchlist_symbol"),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    symbol = Column(String, index=True, nullable=False)        # Ticker symbol (e.g., AAPL)
    operation_type = Column(String, nullable=False)            # "BUY" or "SELL"
    quantity = Column(Float, nullable=False)                   # VN (Volumen Nominal)
    price = Column(Float, nullable=False)                      # Precio pactado del Cedear / activo
    currency = Column(String, default="ARS", nullable=False)   # "ARS" or "USD"
    ratio = Column(Float, default=1.0, nullable=False)         # Ratio Cedear (ej: 20 para AAPL)
    exchange_rate = Column(Float, default=1.0, nullable=False) # TC/Canje: Para ARS es 1/CCL, para USD es canje MEP-CCL
    price_comparable = Column(Float, nullable=False)           # Precio en USD afuera = price * ratio * exchange_rate
    date = Column(DateTime, default=datetime.utcnow, nullable=False)
    notes = Column(String, nullable=True)

    user = relationship("User", back_populates="transactions")


