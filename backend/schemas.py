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
    order: int
    items: List[WatchlistItem] = []

    class Config:
        from_attributes = True


# --- Transactions & Portfolio ---
class TransactionBase(BaseModel):
    symbol: str = Field(..., description="Ticker symbol (e.g. AAPL)")
    operation_type: str = Field(..., description="'BUY' or 'SELL'")
    quantity: float = Field(..., description="Quantity/Volume Nominal (VN)")
    price: float = Field(..., description="Unit price of the asset")
    currency: Optional[str] = Field("ARS", description="ARS or USD")
    ratio: Optional[float] = Field(1.0, description="Cedear ratio (Cedears per share, e.g. 20)")
    exchange_rate: Optional[float] = Field(1.0, description="TC/Canje multiplier to get USD price")
    date: Optional[datetime] = Field(None, description="Date of the transaction. Defaults to now if not provided.")
    notes: Optional[str] = None

class TransactionCreate(TransactionBase):
    pass

class TransactionUpdate(TransactionBase):
    pass

class Transaction(TransactionBase):
    id: int
    price_comparable: float
    date: datetime

    class Config:
        from_attributes = True

class PortfolioItem(BaseModel):
    symbol: str
    vn_total: float
    acciones_equivalentes: float
    ppc_comparable: float
    costo_total_usd: float
    precio_afuera: Optional[float] = None
    prev_close: Optional[float] = None
    valor_actual_usd: Optional[float] = None
    pnl_usd: Optional[float] = None
    pnl_percent: Optional[float] = None

    class Config:
        from_attributes = True


class PortfolioResponse(BaseModel):
    items: List[PortfolioItem]
    realized_pnl: float
    realized_pnl_percent: float

    class Config:
        from_attributes = True

