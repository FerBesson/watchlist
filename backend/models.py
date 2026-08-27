from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint, Boolean
from sqlalchemy.orm import relationship
from .database import Base

class Watchlist(Base):
    __tablename__ = "watchlists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    description = Column(String, nullable=True)
    # Comma-separated list of metrics/columns to show, e.g., "sector,price,prev_close,change"
    metrics = Column(String, default="sector,price,prev_close,change", nullable=False)

    items = relationship("WatchlistItem", back_populates="watchlist", cascade="all, delete-orphan")


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
