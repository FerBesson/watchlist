from sqlalchemy import func
from sqlalchemy.orm import Session
from . import models, schemas

# --- Watchlist Operations ---

def get_watchlist(db: Session, watchlist_id: int):
    return db.query(models.Watchlist).filter(models.Watchlist.id == watchlist_id).first()

def get_watchlist_by_name(db: Session, name: str):
    return db.query(models.Watchlist).filter(models.Watchlist.name == name).first()

def get_watchlists(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Watchlist).offset(skip).limit(limit).all()

def create_watchlist(db: Session, watchlist: schemas.WatchlistCreate):
    db_watchlist = models.Watchlist(
        name=watchlist.name,
        description=watchlist.description,
        metrics=watchlist.metrics
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
