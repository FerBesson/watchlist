import os
import sys
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Base, User, Watchlist, WatchlistItem, Transaction

load_dotenv()

def push_local_to_cloud():
    cloud_url = os.getenv("DATABASE_URL")
    if not cloud_url or cloud_url.startswith("sqlite"):
        print("[ERROR] DATABASE_URL no está configurado con una URL de PostgreSQL en el archivo .env")
        return

    if cloud_url.startswith("postgres://"):
        cloud_url = cloud_url.replace("postgres://", "postgresql://", 1)

    sqlite_path = "watchlists.db"
    if not os.path.exists(sqlite_path):
        print(f"[ERROR] No se encontró el archivo local {sqlite_path}")
        return

    print("======================================================================")
    print(" INICIANDO MIGRACIÓN DE DATOS A NEON POSTGRESQL")
    print("======================================================================")

    # 1. Crear tablas en Neon
    print("-> Creando tablas en la base de datos de Neon...")
    cloud_engine = create_engine(cloud_url)
    Base.metadata.create_all(bind=cloud_engine)
    CloudSession = sessionmaker(bind=cloud_engine)
    cloud_db = CloudSession()

    # 2. Conectar a SQLite local
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    cursor = sqlite_conn.cursor()

    try:
        # --- A. MIGRAR USUARIOS ---
        print("\n[1/4] Migrando Usuarios...")
        cursor.execute("SELECT * FROM users")
        local_users = cursor.fetchall()
        user_id_map = {} # local_id -> cloud_id

        for u in local_users:
            # Parse datetime
            created_at = None
            if u["created_at"]:
                try:
                    created_at = datetime.fromisoformat(u["created_at"])
                except Exception:
                    created_at = datetime.utcnow()

            # Verificar si ya existe en cloud
            cloud_user = cloud_db.query(User).filter(User.google_id == u["google_id"]).first()
            if not cloud_user:
                cloud_user = User(
                    google_id=u["google_id"],
                    email=u["email"],
                    name=u["name"],
                    picture=u["picture"],
                    created_at=created_at or datetime.utcnow()
                )
                cloud_db.add(cloud_user)
                cloud_db.commit()
                cloud_db.refresh(cloud_user)
                print(f"  + Creado usuario en cloud: {cloud_user.email} (ID: {cloud_user.id})")
            else:
                print(f"  = Usuario ya existe en cloud: {cloud_user.email} (ID: {cloud_user.id})")

            user_id_map[u["id"]] = cloud_user.id

        # Fallback si no había usuario en SQLite pero sí listas
        default_cloud_user_id = list(user_id_map.values())[0] if user_id_map else None

        # --- B. MIGRAR WATCHLISTS ---
        print("\n[2/4] Migrando Watchlists...")
        cursor.execute("SELECT * FROM watchlists ORDER BY id ASC")
        local_wls = cursor.fetchall()
        wl_id_map = {} # local_wl_id -> cloud_wl_id

        for wl in local_wls:
            target_user_id = user_id_map.get(wl["user_id"], default_cloud_user_id)
            
            # Verificar si ya existe en cloud para ese usuario
            cloud_wl = cloud_db.query(Watchlist).filter(
                Watchlist.user_id == target_user_id,
                Watchlist.name == wl["name"]
            ).first()

            if not cloud_wl:
                cloud_wl = Watchlist(
                    user_id=target_user_id,
                    name=wl["name"],
                    description=wl["description"],
                    metrics=wl["metrics"] or "sector,price,prev_close,change",
                    order=wl["order"] if "order" in wl.keys() else 0
                )
                cloud_db.add(cloud_wl)
                cloud_db.commit()
                cloud_db.refresh(cloud_wl)
                print(f"  + Creada lista en cloud: '{cloud_wl.name}' (ID: {cloud_wl.id})")
            else:
                print(f"  = Lista ya existe en cloud: '{cloud_wl.name}' (ID: {cloud_wl.id})")

            wl_id_map[wl["id"]] = cloud_wl.id

        # --- C. MIGRAR WATCHLIST ITEMS ---
        print("\n[3/4] Migrando Ítems y Secciones de Watchlists...")
        cursor.execute("SELECT * FROM watchlist_items ORDER BY watchlist_id, id ASC")
        local_items = cursor.fetchall()
        items_migrated = 0

        for it in local_items:
            cloud_wl_id = wl_id_map.get(it["watchlist_id"])
            if not cloud_wl_id:
                continue

            # Verificar si existe el item
            cloud_item = cloud_db.query(WatchlistItem).filter(
                WatchlistItem.watchlist_id == cloud_wl_id,
                WatchlistItem.symbol == it["symbol"]
            ).first()

            if not cloud_item:
                added_at = None
                if it["added_at"]:
                    try:
                        added_at = datetime.fromisoformat(it["added_at"])
                    except Exception:
                        added_at = datetime.utcnow()

                cloud_item = WatchlistItem(
                    watchlist_id=cloud_wl_id,
                    symbol=it["symbol"],
                    name=it["name"],
                    sector=it["sector"],
                    notes=it["notes"],
                    is_divider=bool(it["is_divider"]) if "is_divider" in it.keys() else False,
                    order=it["order"] if "order" in it.keys() else 0,
                    added_at=added_at or datetime.utcnow()
                )
                cloud_db.add(cloud_item)
                items_migrated += 1

        cloud_db.commit()
        print(f"  + Ítems migrados/sincronizados: {items_migrated}")

        # --- D. MIGRAR TRANSACCIONES ---
        print("\n[4/4] Migrando Transacciones de Cartera...")
        cursor.execute("SELECT * FROM transactions ORDER BY date ASC, id ASC")
        local_txs = cursor.fetchall()
        txs_migrated = 0

        for tx in local_txs:
            target_user_id = user_id_map.get(tx["user_id"], default_cloud_user_id) if "user_id" in tx.keys() else default_cloud_user_id

            tx_date = None
            if tx["date"]:
                try:
                    tx_date = datetime.fromisoformat(tx["date"])
                except Exception:
                    tx_date = datetime.utcnow()

            # Verificar si la transacción ya existe (mismo símbolo, fecha, tipo, cant, precio)
            existing_tx = cloud_db.query(Transaction).filter(
                Transaction.user_id == target_user_id,
                Transaction.symbol == tx["symbol"],
                Transaction.operation_type == tx["operation_type"],
                Transaction.quantity == tx["quantity"],
                Transaction.price == tx["price"]
            ).first()

            if not existing_tx:
                cloud_tx = Transaction(
                    user_id=target_user_id,
                    symbol=tx["symbol"],
                    operation_type=tx["operation_type"],
                    quantity=tx["quantity"],
                    price=tx["price"],
                    currency=tx["currency"] or "ARS",
                    ratio=tx["ratio"] or 1.0,
                    exchange_rate=tx["exchange_rate"] or 1.0,
                    price_comparable=tx["price_comparable"],
                    date=tx_date or datetime.utcnow(),
                    notes=tx["notes"]
                )
                cloud_db.add(cloud_tx)
                txs_migrated += 1

        cloud_db.commit()
        print(f"  + Transacciones migradas: {txs_migrated}")

        # --- RECUENTO FINAL EN CLOUD ---
        total_users = cloud_db.query(User).count()
        total_wls = cloud_db.query(Watchlist).count()
        total_items = cloud_db.query(WatchlistItem).count()
        total_txs = cloud_db.query(Transaction).count()

        print("\n======================================================================")
        print(" MIGRACION A LA NUBE COMPLETADA CON EXITO!")
        print("======================================================================")
        print(" Resumen en Neon PostgreSQL:")
        print(f" - Usuarios:      {total_users}")
        print(f" - Watchlists:    {total_wls}")
        print(f" - Items totales: {total_items}")
        print(f" - Transacciones: {total_txs}")
        print("======================================================================")


    except Exception as e:
        cloud_db.rollback()
        print(f"\n[ERROR] Ocurrió un fallo durante la migración a Neon: {e}")
    finally:
        sqlite_conn.close()
        cloud_db.close()

if __name__ == "__main__":
    push_local_to_cloud()
