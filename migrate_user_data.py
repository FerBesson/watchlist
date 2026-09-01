import sys
import os
from sqlalchemy.orm import Session
from backend.database import SessionLocal, engine, Base
from backend.models import User, Watchlist, Transaction, WatchlistItem

def migrate_existing_data_to_user(target_email: str = None):
    """
    Asocia todas las watchlists y transacciones que no tienen user_id
    al usuario que coincida con target_email o al único usuario existente.
    """
    # Asegurar que todas las tablas y columnas existan
    Base.metadata.create_all(bind=engine)
    
    db: Session = SessionLocal()
    try:
        users = db.query(User).all()
        if not users:
            print("======================================================================")
            print(" [AVISO] No se encontraron usuarios en la base de datos.")
            print(" Por favor, inicia sesión con Google al menos una vez en la app")
            print(" para que tu usuario quede registrado en la base de datos.")
            print(" Luego vuelve a ejecutar este script.")
            print("======================================================================")
            return

        target_user = None
        if target_email:
            target_user = db.query(User).filter(User.email.ilike(target_email.strip())).first()
            if not target_user:
                print(f"[ERROR] No se encontró ningún usuario con el correo: {target_email}")
                print(f"Usuarios disponibles: {[u.email for u in users]}")
                return
        elif len(users) == 1:
            target_user = users[0]
            print(f"[INFO] Se detectó un único usuario registrado: {target_user.email} (ID: {target_user.id})")
        else:
            print("\n--- USUARIOS DISPONIBLES ---")
            for idx, u in enumerate(users):
                print(f" [{idx + 1}] ID: {u.id} | Email: {u.email} | Nombre: {u.name}")
            
            try:
                choice = int(input("\nElige el número de usuario al cual asociar los datos: "))
                target_user = users[choice - 1]
            except Exception:
                print("[ERROR] Selección inválida.")
                return

        print(f"\n-> Vinculando datos al usuario: {target_user.email} (ID: {target_user.id})...")

        # 1. Asociar Watchlists huérfanas
        unassigned_wls = db.query(Watchlist).filter((Watchlist.user_id == None) | (Watchlist.user_id == 0)).all()
        wl_count = len(unassigned_wls)
        for wl in unassigned_wls:
            wl.user_id = target_user.id

        # 2. Asociar Transacciones huérfanas
        unassigned_txs = db.query(Transaction).filter((Transaction.user_id == None) | (Transaction.user_id == 0)).all()
        tx_count = len(unassigned_txs)
        for tx in unassigned_txs:
            tx.user_id = target_user.id

        db.commit()

        print("======================================================================")
        print(f" ¡MIGRACIÓN EXITOSA!")
        print(f" - Listas asociadas a {target_user.email}: {wl_count}")
        print(f" - Transacciones asociadas a {target_user.email}: {tx_count}")
        print(" Todos tus datos existentes ahora están vinculados a tu cuenta de Google.")
        print("======================================================================")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Ocurrió un error durante la migración: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    email_arg = sys.argv[1] if len(sys.argv) > 1 else None
    migrate_existing_data_to_user(email_arg)
