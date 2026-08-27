import sqlite3
import os

db_path = "watchlists.db"

def run_migration():
    if not os.path.exists(db_path):
        print("----------------------------------------------------------------------")
        print(" ERROR: No se encontró el archivo 'watchlists.db' en la raíz.")
        print(" Por favor, sigue el Paso 1 para restaurar tu archivo desde OneDrive.")
        print("----------------------------------------------------------------------")
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # --- Migrar Tabla watchlist_items ---
        cursor.execute("PRAGMA table_info(watchlist_items)")
        item_columns = [row[1] for row in cursor.fetchall()]
        
        migrated = False
        if "is_divider" not in item_columns:
            print("Adding column 'is_divider' to watchlist_items...")
            cursor.execute("ALTER TABLE watchlist_items ADD COLUMN is_divider BOOLEAN DEFAULT 0 NOT NULL")
            migrated = True
            
        if "order" not in item_columns:
            print("Adding column 'order' to watchlist_items...")
            cursor.execute("ALTER TABLE watchlist_items ADD COLUMN \"order\" INTEGER DEFAULT 0 NOT NULL")
            migrated = True
            
        # --- Migrar Tabla watchlists ---
        cursor.execute("PRAGMA table_info(watchlists)")
        wl_columns = [row[1] for row in cursor.fetchall()]
        
        if "order" not in wl_columns:
            print("Adding column 'order' to watchlists...")
            cursor.execute("ALTER TABLE watchlists ADD COLUMN \"order\" INTEGER DEFAULT 0 NOT NULL")
            migrated = True
            
        # --- Crear Tabla transactions si no existe ---
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'")
        table_exists = cursor.fetchone()
        
        if not table_exists:
            print("Creating 'transactions' table...")
            cursor.execute("""
                CREATE TABLE transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    operation_type TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'ARS',
                    ratio REAL NOT NULL DEFAULT 1.0,
                    exchange_rate REAL NOT NULL DEFAULT 1.0,
                    price_comparable REAL NOT NULL,
                    date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT
                )
            """)
            cursor.execute("CREATE INDEX ix_transactions_id ON transactions (id)")
            cursor.execute("CREATE INDEX ix_transactions_symbol ON transactions (symbol)")
            migrated = True
            
        if migrated:
            conn.commit()
            print("----------------------------------------------------------------------")
            print(" SUCCESS: Database migrated successfully!")
            print("----------------------------------------------------------------------")
        else:
            print("Database is already up to date.")
            
        conn.close()
    except Exception as e:
        print(f"Error during migration: {e}")

if __name__ == "__main__":
    run_migration()
