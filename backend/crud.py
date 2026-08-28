from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import Session
from . import models, schemas

# --- Watchlist Operations ---

def get_watchlist(db: Session, watchlist_id: int):
    return db.query(models.Watchlist).filter(models.Watchlist.id == watchlist_id).first()

def get_watchlist_by_name(db: Session, name: str):
    return db.query(models.Watchlist).filter(models.Watchlist.name == name).first()

def get_watchlists(db: Session, skip: int = 0, limit: int = 100):
    # Sort watchlists by order ascending, then by database id
    return db.query(models.Watchlist).order_by(models.Watchlist.order.asc(), models.Watchlist.id.asc()).offset(skip).limit(limit).all()

def create_watchlist(db: Session, watchlist: schemas.WatchlistCreate):
    # Get max order currently in watchlists
    max_order = db.query(func.max(models.Watchlist.order)).scalar() or 0
    
    db_watchlist = models.Watchlist(
        name=watchlist.name,
        description=watchlist.description,
        metrics=watchlist.metrics,
        order=max_order + 1
    )
    db.add(db_watchlist)
    db.commit()
    db.refresh(db_watchlist)
    return db_watchlist

def update_watchlist(db: Session, watchlist_id: int, watchlist_update: schemas.WatchlistUpdate):
    db_watchlist = get_watchlist(db, watchlist_id)
    if not db_watchlist:
        return None
    
    update_data = watchlist_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_watchlist, key, value)
        
    db.commit()
    db.refresh(db_watchlist)
    return db_watchlist

def delete_watchlist(db: Session, watchlist_id: int):
    db_watchlist = get_watchlist(db, watchlist_id)
    if db_watchlist:
        db.delete(db_watchlist)
        db.commit()
        return True
    return False

def reorder_watchlists(db: Session, watchlist_ids: list[int]) -> bool:
    """Reorder multiple watchlists in bulk by assigning sequence order indices."""
    watchlists = db.query(models.Watchlist).all()
    watchlists_dict = {wl.id: wl for wl in watchlists}
    
    for index, wl_id in enumerate(watchlist_ids):
        if wl_id in watchlists_dict:
            watchlists_dict[wl_id].order = index
            
    db.commit()
    return True


# --- Watchlist Item Operations ---

def get_watchlist_item(db: Session, item_id: int):
    return db.query(models.WatchlistItem).filter(models.WatchlistItem.id == item_id).first()

def get_watchlist_item_by_symbol(db: Session, watchlist_id: int, symbol: str):
    return db.query(models.WatchlistItem).filter(
        models.WatchlistItem.watchlist_id == watchlist_id,
        models.WatchlistItem.symbol == symbol
    ).first()

def add_item_to_watchlist(db: Session, watchlist_id: int, item: schemas.WatchlistItemCreate):
    # Preserve original case for dividers (so "Cartera" stays "Cartera"), uppercase for stocks
    symbol_formatted = item.symbol.strip() if item.is_divider else item.symbol.strip().upper()
    
    # Check if already exists in this watchlist
    existing = get_watchlist_item_by_symbol(db, watchlist_id, symbol_formatted)
    if existing:
        return existing
        
    # Get max order currently in this watchlist
    max_order = db.query(func.max(models.WatchlistItem.order)).filter(
        models.WatchlistItem.watchlist_id == watchlist_id
    ).scalar() or 0
    
    if item.is_divider:
        db_item = models.WatchlistItem(
            watchlist_id=watchlist_id,
            symbol=symbol_formatted,
            name=None,
            sector=None,
            is_divider=True,
            order=max_order + 1,
            notes=item.notes
        )
    else:
        # Fetch metadata (name and sector) on-the-fly using the finance client
        from .finance import finance_client
        meta = finance_client.get_symbol_metadata(symbol_formatted)
        
        db_item = models.WatchlistItem(
            watchlist_id=watchlist_id,
            symbol=symbol_formatted,
            name=meta.get("name"),
            sector=meta.get("sector"),
            is_divider=False,
            order=max_order + 1,
            notes=item.notes
        )
        
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

def delete_item_from_watchlist(db: Session, watchlist_id: int, symbol: str):
    db_item = get_watchlist_item_by_symbol(db, watchlist_id, symbol)
    if db_item:
        db.delete(db_item)
        db.commit()
        return True
    return False

def delete_item_by_id(db: Session, item_id: int):
    db_item = get_watchlist_item(db, item_id)
    if db_item:
        db.delete(db_item)
        db.commit()
        return True
    return False

def move_watchlist_item(db: Session, watchlist_id: int, item_id: int, direction: str) -> bool:
    """Move an item or divider up or down in sorting order by swapping with its neighbor."""
    # Query all items ordered by current order, then id
    items = db.query(models.WatchlistItem).filter(
        models.WatchlistItem.watchlist_id == watchlist_id
    ).order_by(models.WatchlistItem.order.asc(), models.WatchlistItem.id.asc()).all()
    
    # Normalize sequence to be 0, 1, 2, ... to prevent duplicate order anomalies
    for i, it in enumerate(items):
        it.order = i
        
    # Find position of target item
    target_idx = None
    for idx, it in enumerate(items):
        if it.id == item_id:
            target_idx = idx
            break
            
    if target_idx is None:
        return False
        
    if direction == "up":
        if target_idx == 0:
            db.commit() # Save normalized order
            return True # Already at top
        # Swap order index with previous item
        items[target_idx].order = target_idx - 1
        items[target_idx - 1].order = target_idx
    elif direction == "down":
        if target_idx == len(items) - 1:
            db.commit() # Save normalized order
            return True # Already at bottom
        # Swap order index with next item
        items[target_idx].order = target_idx + 1
        items[target_idx + 1].order = target_idx
    else:
        return False
        
    db.commit()
    return True


# --- Transaction & Portfolio Operations ---

def create_transaction(db: Session, tx: schemas.TransactionCreate):
    symbol_formatted = tx.symbol.strip().upper()
    price_comparable = tx.price * tx.ratio * tx.exchange_rate
    
    db_tx = models.Transaction(
        symbol=symbol_formatted,
        operation_type=tx.operation_type,
        quantity=tx.quantity,
        price=tx.price,
        currency=tx.currency,
        ratio=tx.ratio,
        exchange_rate=tx.exchange_rate,
        price_comparable=price_comparable,
        date=tx.date if tx.date is not None else datetime.utcnow(),
        notes=tx.notes
    )
    db.add(db_tx)
    db.commit()
    db.refresh(db_tx)
    return db_tx

def get_transactions(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Transaction).order_by(models.Transaction.date.desc(), models.Transaction.id.desc()).offset(skip).limit(limit).all()

def update_transaction(db: Session, tx_id: int, tx_update: schemas.TransactionUpdate) -> Optional[models.Transaction]:
    db_tx = db.query(models.Transaction).filter(models.Transaction.id == tx_id).first()
    if not db_tx:
        return None
    
    symbol_formatted = tx_update.symbol.strip().upper()
    price_comparable = tx_update.price * tx_update.ratio * tx_update.exchange_rate
    
    db_tx.symbol = symbol_formatted
    db_tx.operation_type = tx_update.operation_type
    db_tx.quantity = tx_update.quantity
    db_tx.price = tx_update.price
    db_tx.currency = tx_update.currency
    db_tx.ratio = tx_update.ratio
    db_tx.exchange_rate = tx_update.exchange_rate
    db_tx.price_comparable = price_comparable
    if tx_update.date is not None:
        db_tx.date = tx_update.date
    db_tx.notes = tx_update.notes
    
    db.commit()
    db.refresh(db_tx)
    return db_tx

def delete_transaction(db: Session, tx_id: int) -> bool:
    db_tx = db.query(models.Transaction).filter(models.Transaction.id == tx_id).first()
    if db_tx:
        db.delete(db_tx)
        db.commit()
        return True
    return False

def get_portfolio(db: Session):
    # Fetch transactions in chronological order to calculate PPC
    txs = db.query(models.Transaction).order_by(models.Transaction.date.asc(), models.Transaction.id.asc()).all()
    
    portfolio = {}
    realized_pnl = 0.0
    realized_pnl_cost = 0.0
    closed_trades = []
    cash_balance = 0.0
    
    # Find chronological index of the first CASH transaction
    first_cash_idx = None
    for idx, tx in enumerate(txs):
        if tx.symbol.upper() == "CASH":
            first_cash_idx = idx
            break
    
    for idx, tx in enumerate(txs):
        symbol = tx.symbol.upper()
        cant_acciones = tx.quantity / tx.ratio
        monto_transaccion_usd = cant_acciones * tx.price_comparable
        
        if symbol == "CASH":
            if tx.operation_type == "BUY":
                cash_balance += monto_transaccion_usd
            elif tx.operation_type == "SELL":
                cash_balance = max(0.0, cash_balance - monto_transaccion_usd)
            continue
            
        if symbol not in portfolio:
            portfolio[symbol] = {
                "symbol": symbol,
                "vn_total": 0.0,
                "acciones_equivalentes": 0.0,
                "ppc_comparable": 0.0,
                "costo_total_usd": 0.0,
                "ratio": tx.ratio
            }
        
        p = portfolio[symbol]
        
        if tx.operation_type == "BUY":
            nuevas_acciones = p["acciones_equivalentes"] + cant_acciones
            if nuevas_acciones > 0:
                p["ppc_comparable"] = ((p["acciones_equivalentes"] * p["ppc_comparable"]) + (cant_acciones * tx.price_comparable)) / nuevas_acciones
            p["acciones_equivalentes"] = nuevas_acciones
            p["vn_total"] += tx.quantity
            p["costo_total_usd"] = p["acciones_equivalentes"] * p["ppc_comparable"]
            p["ratio"] = tx.ratio
            
            # Decrease cash balance by buy cost ONLY if after or at the first CASH transaction
            if first_cash_idx is not None and idx >= first_cash_idx:
                cash_balance -= monto_transaccion_usd
            
        elif tx.operation_type == "SELL":
            # Realized P&L is: cant_acciones * (precio_venta_comparable - ppc_previo)
            pnl_venta = cant_acciones * (tx.price_comparable - p["ppc_comparable"])
            realized_pnl += pnl_venta
            
            # Realized cost basis for the sold shares: cant_acciones * ppc_previo
            costo_venta = cant_acciones * p["ppc_comparable"]
            realized_pnl_cost += costo_venta
            
            # Record closed trade
            if p["acciones_equivalentes"] > 0:
                pnl_percent = ((tx.price_comparable - p["ppc_comparable"]) / p["ppc_comparable"] * 100) if p["ppc_comparable"] > 0 else 0.0
                closed_trades.append({
                    "symbol": symbol,
                    "quantity": cant_acciones,
                    "ppc_comparable": p["ppc_comparable"],
                    "price_comparable": tx.price_comparable,
                    "pnl_usd": pnl_venta,
                    "pnl_percent": pnl_percent,
                    "date": tx.date
                })
            
            p["acciones_equivalentes"] = max(0.0, p["acciones_equivalentes"] - cant_acciones)
            p["vn_total"] = max(0.0, p["vn_total"] - tx.quantity)
            p["costo_total_usd"] = p["acciones_equivalentes"] * p["ppc_comparable"]
            if p["acciones_equivalentes"] <= 0:
                p["ppc_comparable"] = 0.0
                p["vn_total"] = 0.0
                p["costo_total_usd"] = 0.0
                
            # Increase cash balance by sell revenue ONLY if after or at the first CASH transaction
            if first_cash_idx is not None and idx >= first_cash_idx:
                cash_balance += monto_transaccion_usd
                
    # Calculate realized percentage
    realized_pnl_percent = (realized_pnl / realized_pnl_cost * 100) if realized_pnl_cost > 0 else 0.0
    
    # Calculate performance metrics
    total_trades = len(closed_trades)
    winning_trades = sum(1 for t in closed_trades if t["pnl_usd"] > 0)
    losing_trades = sum(1 for t in closed_trades if t["pnl_usd"] < 0)
    
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
    
    gross_gains = sum(t["pnl_usd"] for t in closed_trades if t["pnl_usd"] > 0)
    gross_losses = sum(abs(t["pnl_usd"]) for t in closed_trades if t["pnl_usd"] < 0)
    
    profit_factor = (gross_gains / gross_losses) if gross_losses > 0 else (gross_gains if gross_gains > 0 else 1.0)
    if gross_losses == 0 and gross_gains > 0:
        profit_factor = 99.9
        
    avg_win = (gross_gains / winning_trades) if winning_trades > 0 else 0.0
    avg_loss = (-gross_losses / losing_trades) if losing_trades > 0 else 0.0
    win_loss_ratio = (avg_win / abs(avg_loss)) if avg_loss != 0 else 0.0
    
    largest_win = max((t["pnl_usd"] for t in closed_trades if t["pnl_usd"] > 0), default=0.0)
    largest_loss = min((t["pnl_usd"] for t in closed_trades if t["pnl_usd"] < 0), default=0.0)
    
    metrics = {
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "win_loss_ratio": win_loss_ratio,
        "largest_win": largest_win,
        "largest_loss": largest_loss
    }
    
    # Filter only active positions (VN > 0)
    active_portfolio = [item for item in portfolio.values() if item["vn_total"] > 0]
    
    result = []
    if active_portfolio:
        # Fetch real-time quotes from Yahoo Finance for the active underlying symbols
        symbols = [item["symbol"] for item in active_portfolio]
        from .finance import finance_client
        quotes = finance_client.get_quotes(symbols)
        
        # Calculate current values and unrealized PnL
        for item in active_portfolio:
            sym = item["symbol"]
            quote = quotes.get(sym, {})
            precio_afuera = quote.get("price") # Price of the stock in US (USD)
            prev_close = quote.get("prev_close")
            
            valor_actual_usd = None
            pnl_usd = None
            pnl_percent = None
            
            if precio_afuera is not None:
                valor_actual_usd = item["acciones_equivalentes"] * precio_afuera
                pnl_usd = valor_actual_usd - item["costo_total_usd"]
                pnl_percent = (pnl_usd / item["costo_total_usd"] * 100) if item["costo_total_usd"] > 0 else 0.0
                
            result.append({
                "symbol": sym,
                "vn_total": item["vn_total"],
                "acciones_equivalentes": item["acciones_equivalentes"],
                "ppc_comparable": item["ppc_comparable"],
                "costo_total_usd": item["costo_total_usd"],
                "precio_afuera": precio_afuera,
                "prev_close": prev_close,
                "valor_actual_usd": valor_actual_usd,
                "pnl_usd": pnl_usd,
                "pnl_percent": pnl_percent
            })
            
    if cash_balance != 0.0:
        result.append({
            "symbol": "CASH",
            "vn_total": cash_balance,
            "acciones_equivalentes": cash_balance,
            "ppc_comparable": 1.0,
            "costo_total_usd": cash_balance,
            "precio_afuera": 1.0,
            "prev_close": 1.0,
            "valor_actual_usd": cash_balance,
            "pnl_usd": 0.0,
            "pnl_percent": 0.0
        })

    # Sort closed trades by date descending
    closed_trades.sort(key=lambda x: x["date"], reverse=True)
    
    # --- XIRR (TIR) Calculation ---
    # Build cash flow series: BUY = negative outflow, SELL = positive inflow
    # Final flow = current portfolio value + cash balance at today's date
    from datetime import datetime as _dt, timezone as _tz
    
    cash_flows = []  # list of (datetime, amount)
    for tx in txs:
        symbol = tx.symbol.upper()
        cant_acciones = tx.quantity / tx.ratio
        monto_usd = cant_acciones * tx.price_comparable
        
        if symbol == "CASH":
            # CASH BUY = capital injection (negative outflow for XIRR)
            if tx.operation_type == "BUY":
                cash_flows.append((tx.date, -monto_usd))
            elif tx.operation_type == "SELL":
                cash_flows.append((tx.date, monto_usd))
        elif tx.operation_type == "BUY":
            cash_flows.append((tx.date, -monto_usd))
        elif tx.operation_type == "SELL":
            cash_flows.append((tx.date, monto_usd))
    
    # Add terminal value: current portfolio valuation + remaining cash
    terminal_value = sum(
        item.get("valor_actual_usd", 0.0) or 0.0 for item in result
        if item["symbol"] != "CASH"
    ) + max(cash_balance, 0.0)
    
    now = _dt.now(_tz.utc)
    if terminal_value > 0:
        cash_flows.append((now, terminal_value))
    
    # Calculate XIRR via Newton-Raphson
    tir = None
    if len(cash_flows) >= 2:
        t0 = cash_flows[0][0]
        # Ensure all datetimes are offset-naive for consistent subtraction
        def to_naive(dt_obj):
            if hasattr(dt_obj, 'tzinfo') and dt_obj.tzinfo is not None:
                return dt_obj.replace(tzinfo=None)
            return dt_obj
        
        t0_naive = to_naive(t0)
        years = [float((to_naive(cf[0]) - t0_naive).total_seconds()) / (365.25 * 86400) for cf in cash_flows]
        values = [cf[1] for cf in cash_flows]
        
        def npv(r):
            return sum(v / ((1.0 + r) ** y) for v, y in zip(values, years))
        
        def npv_deriv(r):
            return sum(-y * v / ((1.0 + r) ** (y + 1)) for v, y in zip(values, years))
        
        r = 0.1  # initial guess 10%
        try:
            for _ in range(200):
                val = npv(r)
                deriv = npv_deriv(r)
                if abs(deriv) < 1e-12:
                    break
                next_r = r - val / deriv
                if abs(next_r - r) < 1e-8:
                    r = next_r
                    break
                r = next_r
            # Sanity check: XIRR should be within reasonable bounds (-99% to +10000%)
            if -0.99 < r < 100.0:
                tir = round(r * 100, 2)
        except (ZeroDivisionError, OverflowError, ValueError):
            tir = None
        
    return {
        "items": result, 
        "realized_pnl": realized_pnl, 
        "realized_pnl_percent": realized_pnl_percent,
        "metrics": metrics,
        "closed_trades": closed_trades,
        "tir": tir
    }

