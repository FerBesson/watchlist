import datetime
import requests
from typing import Dict, Optional, Tuple

# Memoria caché para históricos de Argentina Datos
_ccl_history: Dict[str, float] = {}
_mep_history: Dict[str, float] = {}
_history_loaded = False

def load_historical_data():
    """Descarga los históricos completos de MEP y CCL de Argentina Datos y los almacena en memoria."""
    global _ccl_history, _mep_history, _history_loaded
    if _history_loaded:
        return

    try:
        # Descargar CCL
        print("[Exchange] Cargando historial de dólar CCL...")
        ccl_url = "https://api.argentinadatos.com/v1/cotizaciones/dolares/contadoconliqui"
        resp = requests.get(ccl_url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            for item in data:
                fecha = item.get("fecha")
                venta = item.get("venta") or item.get("compra") or 0.0
                if fecha and venta > 0:
                    _ccl_history[fecha] = venta
        
        # Descargar MEP
        print("[Exchange] Cargando historial de dólar MEP...")
        mep_url = "https://api.argentinadatos.com/v1/cotizaciones/dolares/bolsa"
        resp = requests.get(mep_url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            for item in data:
                fecha = item.get("fecha")
                venta = item.get("venta") or item.get("compra") or 0.0
                if fecha and venta > 0:
                    _mep_history[fecha] = venta

        _history_loaded = True
        print(f"[Exchange] Historial cargado. CCL: {len(_ccl_history)} registros, MEP: {len(_mep_history)} registros.")
    except Exception as e:
        print(f"[Exchange] Error al cargar históricos de Argentina Datos: {e}")

# Caché para la cotización de hoy de DolarApi (5 minutos de validez)
_today_cache = {
    "mep": None,
    "ccl": None,
    "timestamp": 0.0
}

def get_today_rates() -> Tuple[Optional[float], Optional[float]]:
    """Obtiene la cotización en tiempo real de MEP y CCL desde DolarApi con caché de 5 minutos."""
    import time
    now = time.time()
    if _today_cache["timestamp"] > 0 and (now - _today_cache["timestamp"] < 300):
        return _today_cache["mep"], _today_cache["ccl"]

    mep = None
    ccl = None

    try:
        resp = requests.get("https://dolarapi.com/v1/dolares/bolsa", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            mep = data.get("venta") or data.get("compra")
    except Exception as e:
        print(f"[Exchange] Error al obtener MEP de DolarApi: {e}")

    try:
        resp = requests.get("https://dolarapi.com/v1/dolares/contadoconliqui", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            ccl = data.get("venta") or data.get("compra")
    except Exception as e:
        print(f"[Exchange] Error al obtener CCL de DolarApi: {e}")

    if mep and ccl:
        _today_cache["mep"] = mep
        _today_cache["ccl"] = ccl
        _today_cache["timestamp"] = now
    
    return mep, ccl

def find_nearest_rate(history: Dict[str, float], target_date: datetime.date) -> Optional[float]:
    """Busca en el historial la cotización más cercana a la fecha objetivo (hacia atrás hasta 10 días)."""
    for i in range(10):
        check_date = target_date - datetime.timedelta(days=i)
        check_str = check_date.strftime("%Y-%m-%d")
        if check_str in history:
            return history[check_str]
    return None

def get_rates_for_date(target_date_str: Optional[str]) -> Tuple[datetime.date, Optional[float], Optional[float], str]:
    """
    Obtiene las cotizaciones de MEP y CCL para una fecha dada.
    Si la fecha es hoy o futura, intenta usar DolarApi.
    De lo contrario, usa el histórico de Argentina Datos.
    """
    today = datetime.date.today()
    
    if not target_date_str:
        target_date = today
    else:
        try:
            clean_date = target_date_str.split('T')[0]
            target_date = datetime.datetime.strptime(clean_date, "%Y-%m-%d").date()
        except ValueError:
            target_date = today

    # Si es hoy o posterior, intentar tiempo real con DolarApi
    if target_date >= today:
        mep, ccl = get_today_rates()
        if mep and ccl:
            return today, mep, ccl, "dolarapi"

    # Cargar históricos si no están cargados
    load_historical_data()

    # Buscar MEP y CCL más cercanos a la fecha
    mep = find_nearest_rate(_mep_history, target_date)
    ccl = find_nearest_rate(_ccl_history, target_date)

    # Si no encontramos cotización MEP o CCL para esa fecha específica,
    # intentamos buscar la cotización más cercana disponible en absoluto
    if not mep and _mep_history:
        sorted_keys = sorted(_mep_history.keys())
        if sorted_keys:
            if target_date < datetime.datetime.strptime(sorted_keys[0], "%Y-%m-%d").date():
                mep = _mep_history[sorted_keys[0]]
            else:
                mep = _mep_history[sorted_keys[-1]]
                
    if not ccl and _ccl_history:
        sorted_keys = sorted(_ccl_history.keys())
        if sorted_keys:
            if target_date < datetime.datetime.strptime(sorted_keys[0], "%Y-%m-%d").date():
                ccl = _ccl_history[sorted_keys[0]]
            else:
                ccl = _ccl_history[sorted_keys[-1]]

    # Si todavía es None, usar fallback genérico
    mep = mep or 1300.0
    ccl = ccl or 1350.0

    return target_date, mep, ccl, "argentinadatos"
