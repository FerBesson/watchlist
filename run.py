import os
import shutil
from datetime import datetime
import uvicorn

def create_database_backup():
    db_file = "watchlists.db"
    backup_dir = "backups"
    
    if os.path.exists(db_file):
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(backup_dir, f"watchlists_backup_{timestamp}.db")
        try:
            shutil.copy2(db_file, backup_file)
            print(f"[Backup] Copia de seguridad guardada con éxito en: {backup_file}")
            
            # Maintain only the 10 most recent backups to save disk space
            all_backups = sorted(
                [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.startswith("watchlists_backup_")],
                key=os.path.getmtime
            )
            while len(all_backups) > 10:
                oldest = all_backups.pop(0)
                os.remove(oldest)
                print(f"[Backup] Backup antiguo eliminado para liberar espacio: {oldest}")
        except Exception as e:
            print(f"[Backup] No se pudo realizar el backup automático: {e}")

if __name__ == "__main__":
    print("--------------------------------------------------")
    print("   INICIANDO SERVIDOR DEL TRACKER DE ACCIONES     ")
    print("   Consola disponible en: http://127.0.0.1:8000   ")
    print("--------------------------------------------------")
    create_database_backup()
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
