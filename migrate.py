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
        
        # Check current columns in watchlist_items
        cursor.execute("PRAGMA table_info(watchlist_items)")
        columns = [row[1] for row in cursor.fetchall()]
        
        migrated = False
        if "is_divider" not in columns:
            print("→ Añadiendo columna 'is_divider' a la tabla 'watchlist_items'...")
            cursor.execute("ALTER TABLE watchlist_items ADD COLUMN is_divider BOOLEAN DEFAULT 0 NOT NULL")
            migrated = True
            
        if "order" not in columns:
            print("→ Añadiendo columna 'order' a la tabla 'watchlist_items'...")
            # SQLite requires escaping double quotes or using brackets for keywords like "order"
            cursor.execute("ALTER TABLE watchlist_items ADD COLUMN \"order\" INTEGER DEFAULT 0 NOT NULL")
            migrated = True
            
        if migrated:
            conn.commit()
            print("----------------------------------------------------------------------")
            print(" ✓ ¡MIGRACIÓN COMPLETADA CON ÉXITO!")
            print(" Tu base de datos restaurada ha sido actualizada a la versión nueva.")
            print(" Ya puedes iniciar el servidor con: python run.py")
            print("----------------------------------------------------------------------")
        else:
            print("La base de datos ya contiene las columnas necesarias. No es necesario migrar.")
            
        conn.close()
    except Exception as e:
        print(f"Error durante la migración: {e}")

if __name__ == "__main__":
    run_migration()
