import os
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .database import engine, get_db, Base
from . import models, schemas, crud
from .finance import finance_client

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Tracker de Acciones - Terminal Style",
    description="Backend en FastAPI para seguimiento de acciones utilizando Yahoo Finance",
    version="1.0.0"
)

# CORS middleware to allow local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from .database import SessionLocal

@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    try:
        watchlists = crud.get_watchlists(db)
        if not watchlists:
            # Create a default watchlist
            default_wl = schemas.WatchlistCreate(
                name="Favoritas",
                description="Mi lista de seguimiento principal para acciones globales y criptomonedas",
                metrics="sector,price,prev_close,change_percent"
            )
            created_wl = crud.create_watchlist(db, default_wl)
            
            # Add section divider: CARTERA
            crud.add_item_to_watchlist(
                db,
                watchlist_id=created_wl.id,
                item=schemas.WatchlistItemCreate(symbol="CARTERA", is_divider=True)
            )
            
            # Add stocks under CARTERA
            tech_stocks = ["AAPL", "MSFT", "TSLA"]
            for sym in tech_stocks:
                crud.add_item_to_watchlist(
                    db,
                    watchlist_id=created_wl.id,
                    item=schemas.WatchlistItemCreate(symbol=sym, is_divider=False, notes="Acción tecnológica")
                )
                
            # Add section divider: CRIPTO
            crud.add_item_to_watchlist(
                db,
                watchlist_id=created_wl.id,
                item=schemas.WatchlistItemCreate(symbol="CRIPTO", is_divider=True)
            )
            
            # Add stock under CRIPTO
            crud.add_item_to_watchlist(
                db,
                watchlist_id=created_wl.id,
                item=schemas.WatchlistItemCreate(symbol="BTC-USD", is_divider=False, notes="Moneda digital principal")
            )
            
            print("[Database] Seeded default watchlist 'Favoritas' with section dividers and assets.")
    except Exception as e:
        print(f"[Database] Error seeding database: {e}")
    finally:
        db.close()

# --- WATCHLIST ENDPOINTS ---

@app.get("/api/watchlists", response_model=List[schemas.Watchlist])
def read_watchlists(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """Retrieve all watchlists."""
    return crud.get_watchlists(db, skip=skip, limit=limit)

@app.get("/api/watchlists/{watchlist_id}", response_model=schemas.Watchlist)
def read_watchlist(watchlist_id: int, db: Session = Depends(get_db)):
    """Retrieve a single watchlist by ID."""
    db_watchlist = crud.get_watchlist(db, watchlist_id)
    if db_watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return db_watchlist

@app.post("/api/watchlists", response_model=schemas.Watchlist, status_code=status.HTTP_201_CREATED)
def create_watchlist(watchlist: schemas.WatchlistCreate, db: Session = Depends(get_db)):
    """Create a new watchlist."""
    db_watchlist_exists = crud.get_watchlist_by_name(db, name=watchlist.name)
    if db_watchlist_exists:
        raise HTTPException(status_code=400, detail="Watchlist with this name already exists")
    return crud.create_watchlist(db=db, watchlist=watchlist)

@app.put("/api/watchlists/{watchlist_id}", response_model=schemas.Watchlist)
def update_watchlist(watchlist_id: int, watchlist: schemas.WatchlistUpdate, db: Session = Depends(get_db)):
    """Update a watchlist (name, description, or metrics)."""
    db_watchlist = crud.update_watchlist(db=db, watchlist_id=watchlist_id, watchlist_update=watchlist)
    if db_watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return db_watchlist

@app.delete("/api/watchlists/{watchlist_id}")
def delete_watchlist(watchlist_id: int, db: Session = Depends(get_db)):
    """Delete a watchlist."""
    success = crud.delete_watchlist(db=db, watchlist_id=watchlist_id)
    if not success:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return {"message": "Watchlist deleted successfully", "id": watchlist_id}


# --- WATCHLIST ITEM ENDPOINTS ---

@app.post("/api/watchlists/{watchlist_id}/items", response_model=schemas.WatchlistItem, status_code=status.HTTP_201_CREATED)
def add_item_to_watchlist(watchlist_id: int, item: schemas.WatchlistItemCreate, db: Session = Depends(get_db)):
    """Add a stock symbol to a watchlist."""
    db_watchlist = crud.get_watchlist(db, watchlist_id)
    if db_watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    
    # Check if item already exists in this watchlist
    existing = crud.get_watchlist_item_by_symbol(db, watchlist_id, item.symbol)
    if existing:
        raise HTTPException(status_code=400, detail=f"Symbol {item.symbol.upper()} is already in this watchlist")
        
    return crud.add_item_to_watchlist(db=db, watchlist_id=watchlist_id, item=item)

@app.delete("/api/watchlists/{watchlist_id}/items/{symbol}")
def delete_item_from_watchlist(watchlist_id: int, symbol: str, db: Session = Depends(get_db)):
    """Remove a stock symbol from a watchlist."""
    db_watchlist = crud.get_watchlist(db, watchlist_id)
    if db_watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
        
    success = crud.delete_item_from_watchlist(db=db, watchlist_id=watchlist_id, symbol=symbol)
    if not success:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found in this watchlist")
    return {"message": f"Symbol {symbol.upper()} removed from watchlist", "symbol": symbol.upper()}


# --- FINANCIAL DATA ENDPOINTS ---

@app.get("/api/search")
def search_symbols(q: str = Query(..., min_length=1)):
    """Search for symbols on Yahoo Finance."""
    return finance_client.search_symbols(query=q)

@app.get("/api/quotes")
def get_realtime_quotes(symbols: str = Query(..., description="Comma-separated list of ticker symbols")):
    """Get real-time quote data for a comma-separated list of symbols."""
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=400, detail="No symbols provided")
    return finance_client.get_quotes(symbol_list)

@app.get("/api/watchlists/{watchlist_id}/quotes")
def get_watchlist_realtime_quotes(watchlist_id: int, db: Session = Depends(get_db)):
    """
    Get real-time quotes aggregated with watchlist database metadata.
    Returns details for each stock in the watchlist, sorted by order.
    """
    db_watchlist = crud.get_watchlist(db, watchlist_id)
    if db_watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
        
    # Query items explicitly sorted by order, then id
    items = db.query(models.WatchlistItem).filter(
        models.WatchlistItem.watchlist_id == watchlist_id
    ).order_by(models.WatchlistItem.order.asc(), models.WatchlistItem.id.asc()).all()
    
    if not items:
        return []
        
    # Get quotes only for non-divider stock items
    symbols = [item.symbol for item in items if not item.is_divider]
    realtime_quotes = finance_client.get_quotes(symbols) if symbols else {}
    
    # Merge DB metadata with real-time quote data
    merged_data = []
    for item in items:
        if item.is_divider:
            merged_data.append({
                "id": item.id,
                "symbol": item.symbol,
                "name": None,
                "sector": None,
                "notes": item.notes,
                "is_divider": True,
                "order": item.order,
                "added_at": item.added_at,
                "price": None,
                "prev_close": None,
                "change": None,
                "change_percent": None,
                "volume": None,
                "market_cap": None,
                "pe": None,
                "dividend_yield": None
            })
        else:
            quote = realtime_quotes.get(item.symbol, {})
            merged_data.append({
                "id": item.id,
                "symbol": item.symbol,
                "name": item.name or item.symbol,
                "sector": item.sector or "International",
                "notes": item.notes,
                "is_divider": False,
                "order": item.order,
                "added_at": item.added_at,
                "price": quote.get("price"),
                "prev_close": quote.get("prev_close"),
                "change": quote.get("change"),
                "change_percent": quote.get("change_percent"),
                "volume": quote.get("volume"),
                "market_cap": quote.get("market_cap"),
                "pe": quote.get("pe"),
                "dividend_yield": quote.get("dividend_yield")
            })
        
    return merged_data

@app.post("/api/watchlists/{watchlist_id}/items/{item_id}/move")
def move_watchlist_item(watchlist_id: int, item_id: int, direction: str, db: Session = Depends(get_db)):
    """Move a stock or divider up or down in the sorting sequence of the watchlist."""
    if direction not in ["up", "down"]:
        raise HTTPException(status_code=400, detail="Direction must be 'up' or 'down'")
    success = crud.move_watchlist_item(db=db, watchlist_id=watchlist_id, item_id=item_id, direction=direction)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": f"Item moved {direction} successfully", "item_id": item_id, "direction": direction}


@app.get("/api/charts/{symbol}")
def get_chart_data(
    symbol: str, 
    range: str = Query("1mo", description="Range: 1d, 5d, 1mo, 3mo, 6mo, 1y, 5y, max"),
    interval: str = Query("1d", description="Interval: 1m, 5m, 15m, 1h, 1d, 1wk, 1mo")
):
    """Get historical chart data for drawing charts."""
    data = finance_client.get_historical_data(symbol=symbol, time_range=range, interval=interval)
    if not data:
        raise HTTPException(status_code=404, detail=f"No chart data found for symbol {symbol.upper()}")
    return data


# --- SERVING STATIC FRONTEND ---

# Mount static files directory if it exists
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def read_root():
    """Serve the index.html at root."""
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Tracker de Acciones Backend Running. Frontend index.html not found."}
