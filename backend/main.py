import os
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Query, status, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .database import engine, get_db, Base
from . import models, schemas, crud
from .finance import finance_client
from .auth import router as auth_router, get_current_user

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Tracker de Acciones - Terminal Style",
    description="Backend en FastAPI para seguimiento de acciones con autenticación Google y multiusuario",
    version="2.0.0"
)

# CORS middleware to allow local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Auth Router
app.include_router(auth_router)

# --- WATCHLIST ENDPOINTS ---

@app.get("/api/watchlists", response_model=List[schemas.Watchlist])
def read_watchlists(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """Retrieve all watchlists for the logged in user."""
    return crud.get_watchlists(db, user_id=current_user.id, skip=skip, limit=limit)

@app.get("/api/watchlists/{watchlist_id}", response_model=schemas.Watchlist)
def read_watchlist(
    watchlist_id: int, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """Retrieve a single watchlist by ID belonging to current user."""
    db_watchlist = crud.get_watchlist(db, watchlist_id, user_id=current_user.id)
    if db_watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return db_watchlist

@app.post("/api/watchlists", response_model=schemas.Watchlist, status_code=status.HTTP_201_CREATED)
def create_watchlist(
    watchlist: schemas.WatchlistCreate, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """Create a new watchlist for current user."""
    db_watchlist_exists = crud.get_watchlist_by_name(db, name=watchlist.name, user_id=current_user.id)
    if db_watchlist_exists:
        raise HTTPException(status_code=400, detail="Watchlist with this name already exists")
    return crud.create_watchlist(db=db, watchlist=watchlist, user_id=current_user.id)

@app.put("/api/watchlists/{watchlist_id}", response_model=schemas.Watchlist)
def update_watchlist(
    watchlist_id: int, 
    watchlist: schemas.WatchlistUpdate, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """Update a watchlist (name, description, or metrics)."""
    db_watchlist = crud.update_watchlist(db=db, watchlist_id=watchlist_id, watchlist_update=watchlist, user_id=current_user.id)
    if db_watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return db_watchlist

@app.delete("/api/watchlists/{watchlist_id}")
def delete_watchlist(
    watchlist_id: int, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """Delete a watchlist."""
    success = crud.delete_watchlist(db=db, watchlist_id=watchlist_id, user_id=current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return {"message": "Watchlist deleted successfully", "id": watchlist_id}

@app.post("/api/watchlists/reorder")
def reorder_watchlists_list(
    watchlist_ids: List[int], 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """Reorder multiple watchlists in bulk by updating their sequence order."""
    crud.reorder_watchlists(db=db, watchlist_ids=watchlist_ids, user_id=current_user.id)
    return {"message": "Watchlists reordered successfully", "watchlist_ids": watchlist_ids}




# --- WATCHLIST ITEM ENDPOINTS ---

@app.post("/api/watchlists/{watchlist_id}/items", response_model=schemas.WatchlistItem, status_code=status.HTTP_201_CREATED)
def add_item_to_watchlist(
    watchlist_id: int, 
    item: schemas.WatchlistItemCreate, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """Add a stock symbol to a watchlist."""
    db_watchlist = crud.get_watchlist(db, watchlist_id, user_id=current_user.id)
    if db_watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    
    # Check if item already exists in this watchlist
    existing = crud.get_watchlist_item_by_symbol(db, watchlist_id, item.symbol)
    if existing:
        raise HTTPException(status_code=400, detail=f"Symbol {item.symbol.upper()} is already in this watchlist")
        
    return crud.add_item_to_watchlist(db=db, watchlist_id=watchlist_id, item=item)

@app.delete("/api/watchlists/{watchlist_id}/items/{symbol}")
def delete_item_from_watchlist(
    watchlist_id: int, 
    symbol: str, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """Remove a stock symbol from a watchlist."""
    db_watchlist = crud.get_watchlist(db, watchlist_id, user_id=current_user.id)
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
def get_watchlist_realtime_quotes(
    watchlist_id: int, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """
    Get real-time quotes aggregated with watchlist database metadata.
    Returns details for each stock in the watchlist, sorted by order.
    """
    db_watchlist = crud.get_watchlist(db, watchlist_id, user_id=current_user.id)
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
def move_watchlist_item(
    watchlist_id: int, 
    item_id: int, 
    direction: str, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """Move a stock or divider up or down in the sorting sequence of the watchlist."""
    db_watchlist = crud.get_watchlist(db, watchlist_id, user_id=current_user.id)
    if db_watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
        
    if direction not in ["up", "down"]:
        raise HTTPException(status_code=400, detail="Direction must be 'up' or 'down'")
    success = crud.move_watchlist_item(db=db, watchlist_id=watchlist_id, item_id=item_id, direction=direction)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": f"Item moved {direction} successfully", "item_id": item_id, "direction": direction}

@app.post("/api/watchlists/{watchlist_id}/reorder")
def reorder_watchlist_items(
    watchlist_id: int, 
    item_ids: List[int], 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """Reorder multiple items in a watchlist simultaneously."""
    db_watchlist = crud.get_watchlist(db, watchlist_id, user_id=current_user.id)
    if not db_watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found")
        
    db_items = {item.id: item for item in db_watchlist.items}
    for idx, item_id in enumerate(item_ids):
        if item_id in db_items:
            db_items[item_id].order = idx
            
    db.commit()
    return {"message": "Reordered successfully", "item_ids": item_ids}

@app.put("/api/watchlists/{watchlist_id}/items/{item_id}", response_model=schemas.WatchlistItem)
def update_watchlist_item(
    watchlist_id: int, 
    item_id: int, 
    item_update: schemas.WatchlistItemUpdate, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """Update a watchlist item (e.g., rename a section divider)."""
    db_watchlist = crud.get_watchlist(db, watchlist_id, user_id=current_user.id)
    if not db_watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found")
        
    db_item = db.query(models.WatchlistItem).filter(
        models.WatchlistItem.id == item_id,
        models.WatchlistItem.watchlist_id == watchlist_id
    ).first()
    
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    new_symbol = item_update.symbol.strip()
    if not new_symbol:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
        
    # Keep stocks uppercase, preserve custom case for dividers
    if not db_item.is_divider:
        new_symbol = new_symbol.upper()
        
    # Check for name duplicates in same watchlist
    existing = db.query(models.WatchlistItem).filter(
        models.WatchlistItem.watchlist_id == watchlist_id,
        models.WatchlistItem.symbol == new_symbol,
        models.WatchlistItem.id != item_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Symbol or section name already exists in this watchlist")
        
    db_item.symbol = new_symbol
    db.commit()
    db.refresh(db_item)
    return db_item



# --- TRANSACTION & PORTFOLIO ENDPOINTS ---

@app.post("/api/transactions", response_model=schemas.Transaction, status_code=status.HTTP_201_CREATED)
def create_transaction(
    transaction: schemas.TransactionCreate, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """Create a new transaction (BUY or SELL)."""
    if transaction.operation_type not in ["BUY", "SELL"]:
        raise HTTPException(status_code=400, detail="Operation type must be 'BUY' or 'SELL'")
    if transaction.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")
    if transaction.price <= 0:
        raise HTTPException(status_code=400, detail="Price must be greater than zero")
    if transaction.ratio <= 0:
        raise HTTPException(status_code=400, detail="Ratio must be greater than zero")
    if transaction.exchange_rate <= 0:
        raise HTTPException(status_code=400, detail="Exchange rate must be greater than zero")
        
    return crud.create_transaction(db=db, tx=transaction, user_id=current_user.id)

@app.get("/api/transactions", response_model=List[schemas.Transaction])
def read_transactions(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """Get the log of transactions for logged in user."""
    return crud.get_transactions(db=db, user_id=current_user.id, skip=skip, limit=limit)

@app.put("/api/transactions/{transaction_id}", response_model=schemas.Transaction)
def update_transaction(
    transaction_id: int, 
    transaction: schemas.TransactionUpdate, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """Update an existing transaction."""
    if transaction.operation_type not in ["BUY", "SELL"]:
        raise HTTPException(status_code=400, detail="Operation type must be 'BUY' or 'SELL'")
    if transaction.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")
    if transaction.price <= 0:
        raise HTTPException(status_code=400, detail="Price must be greater than zero")
    if transaction.ratio <= 0:
        raise HTTPException(status_code=400, detail="Ratio must be greater than zero")
    if transaction.exchange_rate <= 0:
        raise HTTPException(status_code=400, detail="Exchange rate must be greater than zero")
        
    db_tx = crud.update_transaction(db=db, tx_id=transaction_id, tx_update=transaction, user_id=current_user.id)
    if not db_tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return db_tx

@app.delete("/api/transactions")
def delete_all_transactions(
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """Delete all transactions belonging to current user."""
    num_deleted = db.query(models.Transaction).filter(models.Transaction.user_id == current_user.id).delete()
    db.commit()
    return {"message": "All transactions deleted successfully", "count": num_deleted}

@app.delete("/api/transactions/{transaction_id}")
def delete_transaction(
    transaction_id: int, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """Delete a transaction by ID."""
    success = crud.delete_transaction(db=db, tx_id=transaction_id, user_id=current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"message": "Transaction deleted successfully", "id": transaction_id}

@app.get("/api/portfolio", response_model=schemas.PortfolioResponse)
def read_portfolio(
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """Get the consolidated portfolio with real-time stock prices from Yahoo Finance."""
    return crud.get_portfolio(db=db, user_id=current_user.id)


@app.post("/api/transactions/import")
def import_transactions(
    file: UploadFile = File(...), 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    """Import transactions from an Excel file for current user."""
    import pandas as pd
    from io import BytesIO
    
    if not (file.filename.endswith(".xlsx") or file.filename.endswith(".xls")):
        raise HTTPException(status_code=400, detail="El archivo debe ser un Excel (.xlsx o .xls)")
        
    try:
        contents = file.file.read()
        df = pd.read_excel(BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al leer el archivo Excel: {e}")
        
    # Map column headers to expected keys
    col_map = {}
    for col in df.columns:
        col_clean = ''.join(c for c in str(col) if c.isalnum() or c == ' ').lower().strip()
        if 'operac' in col_clean:
            col_map['operation'] = col
        elif 'concert' in col_clean or 'fecha' in col_clean:
            col_map['date'] = col
        elif 'descrip' in col_clean or 'ticker' in col_clean:
            col_map['symbol'] = col
        elif 'moneda' in col_clean:
            col_map['currency'] = col
        elif 'cant' in col_clean:
            col_map['quantity'] = col
        elif 'prec' in col_clean:
            col_map['price'] = col
            
    required = ['operation', 'date', 'symbol', 'currency', 'quantity', 'price']
    missing = [req for req in required if req not in col_map]
    if missing:
        raise HTTPException(
            status_code=400, 
            detail=f"No se pudieron encontrar las columnas requeridas: {', '.join(missing)}. "
                   f"Columnas detectadas: {list(df.columns)}"
        )
        
    imported_count = 0
    skipped_count = 0
    
    from .finance import get_cedear_info_by_symbol_and_date
    from .exchange import get_rates_for_date
    
    for idx, row in df.iterrows():
        try:
            # Operation Type
            raw_op = str(row[col_map['operation']]).strip().upper()
            if 'COMPRA' in raw_op or 'BUY' in raw_op:
                op_type = 'BUY'
            elif 'VENTA' in raw_op or 'SELL' in raw_op:
                op_type = 'SELL'
            else:
                continue
                
            # Date
            raw_date = row[col_map['date']]
            if pd.isnull(raw_date):
                continue
            date_dt = pd.to_datetime(raw_date)
            date_val = date_dt.to_pydatetime()
            
            # Symbol
            raw_symbol = str(row[col_map['symbol']]).strip().upper()
            sym_clean = raw_symbol[:-3] if raw_symbol.endswith(".BA") else raw_symbol
            
            info = get_cedear_info_by_symbol_and_date(sym_clean, date_val)
            ratio = info["ratio"]
            symbol = info["symbol_origin"]
                
            # Currency
            raw_currency = str(row[col_map['currency']]).strip().upper()
            if 'ARS' in raw_currency or 'PESO' in raw_currency:
                currency = 'ARS'
            elif 'USD' in raw_currency or 'DOLAR' in raw_currency or 'DÓLAR' in raw_currency or 'MEP' in raw_currency:
                currency = 'USD'
            else:
                currency = 'ARS'  # fallback
                
            # Quantity
            quantity = float(row[col_map['quantity']])
            if pd.isnull(quantity) or quantity <= 0:
                continue
                
            # Price
            price = float(row[col_map['price']])
            if pd.isnull(price) or price <= 0:
                continue
                
            # Check duplicates (comparing date part) for current user
            candidates = db.query(models.Transaction).filter(
                models.Transaction.user_id == current_user.id,
                models.Transaction.symbol == symbol,
                models.Transaction.operation_type == op_type,
                models.Transaction.quantity == quantity,
                models.Transaction.price == price,
                models.Transaction.currency == currency
            ).all()
            
            is_duplicate = False
            for cand in candidates:
                if cand.date.date() == date_val.date():
                    is_duplicate = True
                    break
                    
            if is_duplicate:
                skipped_count += 1
                continue
                
            # Get exchange rate for the date
            target_date, mep, ccl, source = get_rates_for_date(date_val.strftime("%Y-%m-%d"))
            
            if currency == "ARS":
                exchange_rate = 1.0 / ccl if ccl and ccl > 0 else 1.0 / 1350.0
            else:
                exchange_rate = mep / ccl if mep and ccl and ccl > 0 else 1300.0 / 1350.0
                
            price_comparable = price * ratio * exchange_rate
            
            db_tx = models.Transaction(
                user_id=current_user.id,
                symbol=symbol,
                operation_type=op_type,
                quantity=quantity,
                price=price,
                currency=currency,
                ratio=ratio,
                exchange_rate=exchange_rate,
                price_comparable=price_comparable,
                date=date_val,
                notes="Importado desde Excel"
            )
            db.add(db_tx)
            imported_count += 1
        except Exception as row_err:
            print(f"[Import] Error processing row {idx}: {row_err}")
            continue
            
    if imported_count > 0:
        db.commit()
        
    return {"imported": imported_count, "skipped": skipped_count}




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


@app.get("/api/cedear-info/{symbol}")
def get_cedear_info(
    symbol: str,
    date: Optional[str] = Query(None, description="Fecha de la operación (YYYY-MM-DD)")
):
    """Retrieve the ratio and official origin ticker for a Cedear from Comafi dataset."""
    from .finance import get_cedear_info_by_symbol_and_date
    return get_cedear_info_by_symbol_and_date(symbol, date)


@app.get("/api/exchange-rate")
def get_exchange_rate(
    date: Optional[str] = Query(None, description="Fecha de operación (YYYY-MM-DD)"),
    currency: str = Query("ARS", description="Moneda de pago ('ARS' o 'USD')")
):
    """Obtener cotizaciones de MEP, CCL y calcular el valor del tipo de cambio / canje para la fecha dada."""
    from .exchange import get_rates_for_date
    
    target_date, mep, ccl, source = get_rates_for_date(date)
    
    # Calcular el valor que debe ver el input en la UI
    exchange_rate_input = 1.0
    if currency == "USD":
        # Canje MEP-CCL en porcentaje: (1 - mep/ccl) * 100
        if ccl and mep and ccl > 0:
            exchange_rate_input = round((1.0 - (mep / ccl)) * 100.0, 2)
        else:
            exchange_rate_input = 0.0
    else:
        # Dólar CCL nominal para ARS
        exchange_rate_input = round(ccl, 2) if ccl else 1.0
        
    return {
        "date": target_date.strftime("%Y-%m-%d"),
        "mep": round(mep, 2) if mep else None,
        "ccl": round(ccl, 2) if ccl else None,
        "exchange_rate_input": exchange_rate_input,
        "currency": currency,
        "source": source
    }


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
