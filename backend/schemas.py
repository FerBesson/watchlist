from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

# --- Watchlist Item ---
class WatchlistItemBase(BaseModel):
    symbol: str = Field(..., description="Ticker symbol (e.g., AAPL) OR section title if is_divider is True")
    notes: Optional[str] = None
    is_divider: Optional[bool] = Field(False, description="True if this item represents a section header")

class WatchlistItemCreate(WatchlistItemBase):
    pass

class WatchlistItemUpdate(BaseModel):
    symbol: str = Field(..., description="New ticker symbol or section header title")

class WatchlistItem(WatchlistItemBase):
    id: int
    watchlist_id: int
    name: Optional[str] = None
    sector: Optional[str] = None
    is_divider: bool
    order: int
    added_at: datetime

    class Config:
        from_attributes = True


# --- Watchlist ---
class WatchlistBase(BaseModel):
    name: str = Field(..., description="Name of the watchlist")
    description: Optional[str] = None
    metrics: str = Field("sector,price,prev_close,change", description="Comma-separated metrics to display")

class WatchlistCreate(WatchlistBase):
    pass

class WatchlistUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    metrics: Optional[str] = None

class Watchlist(WatchlistBase):
    id: int
    items: List[WatchlistItem] = []

    class Config:
        from_attributes = True
