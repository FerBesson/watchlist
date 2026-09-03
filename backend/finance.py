import os
import time
import re
import json
import threading
import requests
from requests.adapters import HTTPAdapter
import datetime
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional

BASE_URL = "https://query2.finance.yahoo.com"
FALLBACK_BASE_URL = "https://query1.finance.yahoo.com"
SESSION_CACHE_FILE = os.path.join(os.path.dirname(__file__), ".session_cache.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5"
}

class YahooFinanceClient:
    def __init__(self):
        self.session = None
        self.crumb = None
        self.last_session_time = 0
        self.session_expiry = 43200  # Reutilizar sesión y crumb hasta por 12 horas
        self.failed_cooldown = 120   # Tiempo de espera si la obtención de crumb falló
        self._session_lock = threading.Lock()
        
        # In-memory quote cache to prevent spamming on rapid polling (TTL: 45 seconds)
        self._cache = {}
        self._cache_ttl = 45

        # In-memory historical chart cache (TTL: 300 seconds / 5 min)
        self._hist_cache = {}
        self._hist_cache_ttl = 300

    def _create_base_session(self) -> requests.Session:
        """Crea una sesión HTTP con Connection Pooling (Keep-Alive) para reutilizar sockets."""
        s = requests.Session()
        s.headers.update(HEADERS)
        adapter = HTTPAdapter(pool_connections=25, pool_maxsize=25, max_retries=1)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        return s

    def _load_cached_session(self, now: float) -> bool:
        """Carga la sesión (cookies + crumb) guardada en disco para inicialización instantánea (0 ms)."""
        if not os.path.exists(SESSION_CACHE_FILE):
            return False
        try:
            with open(SESSION_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            saved_at = data.get("saved_at", 0)
            crumb = data.get("crumb")
            cookies = data.get("cookies", {})
            if crumb and (now - saved_at < self.session_expiry):
                s = self._create_base_session()
                s.cookies.update(requests.utils.cookiejar_from_dict(cookies))
                s.params = {"crumb": crumb}
                self.session = s
                self.crumb = crumb
                self.last_session_time = saved_at
                print(f"[YahooFinance] Sesión y crumb restaurados desde caché persistente.")
                return True
        except Exception as e:
            print(f"[YahooFinance] Error leyendo caché de sesión: {e}")
        return False

    def _save_cached_session(self, now: float):
        """Persiste la sesión en disco para que persista entre reinicios del servidor."""
        if not self.session or not self.crumb:
            return
        try:
            data = {
                "crumb": self.crumb,
                "cookies": requests.utils.dict_from_cookiejar(self.session.cookies),
                "saved_at": now
            }
            with open(SESSION_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"[YahooFinance] Error guardando caché de sesión: {e}")

    def warmup(self):
        """Pre-warms the session in background so initial requests are instant."""
        try:
            self._init_session()
        except Exception:
            pass

    def _init_session(self, force: bool = False):
        """
        Inicializa o reutiliza la sesión HTTP con cookie y crumb.
        Es seguro para concurrencia (thread-safe) y almacena en caché en disco.
        """
        now = time.time()
        # Verificación rápida en memoria antes de bloquear el lock
        if not force and self.session and self.crumb and (now - self.last_session_time < self.session_expiry):
            return

        if not force and not self.crumb and (now - self.last_session_time < self.failed_cooldown):
            return

        with self._session_lock:
            # Doble verificación dentro del lock
            if not force and self.session and self.crumb and (now - self.last_session_time < self.session_expiry):
                return

            # Intentar cargar desde el caché en disco si no se fuerza la renovación
            if not force and self._load_cached_session(now):
                return

            self.last_session_time = now
            try:
                s = self._create_base_session()
                # Paso 1: Obtener cookie de sesión de Yahoo
                s.get("https://fc.yahoo.com", timeout=8)
                # Paso 2: Obtener crumb desde query2
                crumb_resp = s.get(f"{BASE_URL}/v1/test/getcrumb", timeout=8)
                if crumb_resp.status_code != 200:
                    # Intentar en fallback query1
                    crumb_resp = s.get(f"{FALLBACK_BASE_URL}/v1/test/getcrumb", timeout=8)

                crumb_resp.raise_for_status()
                crumb_text = crumb_resp.text.strip()
                if crumb_text and "<html" not in crumb_text.lower():
                    self.crumb = crumb_text
                    s.params = {"crumb": self.crumb}
                    self.session = s
                    self._save_cached_session(now)
                    print(f"[YahooFinance] Nueva sesión inicializada con crumb exitosamente.")
                else:
                    self.crumb = None
                    self.session = s
            except Exception as e:
                print(f"[YahooFinance] Fallo al negociar nuevo crumb: {e}")
                self.session = self._create_base_session()
                self.crumb = None

    def search_symbols(self, query: str) -> List[Dict[str, Any]]:
        """Search for symbols on Yahoo Finance using persistent session."""
        self._init_session()
        client = self.session or requests
        url = f"{BASE_URL}/v1/finance/search"
        params = {"q": query, "quotesCount": 10, "newsCount": 0}
        try:
            resp = client.get(url, params=params, timeout=8)
            if resp.status_code != 200:
                resp = client.get(f"{FALLBACK_BASE_URL}/v1/finance/search", params=params, timeout=8)
            resp.raise_for_status()
            data = resp.json()
            results = []
            for quote in data.get("quotes", []):
                qtype = quote.get("quoteType")
                if qtype in ["EQUITY", "CRYPTO", "ETF", "INDEX", "FUTURE", "COMMODITY", "CURRENCY"]:
                    sector = quote.get("sector")
                    if not sector or sector == "N/A":
                        if qtype in ["FUTURE", "COMMODITY"]:
                            sector = "Commodities"
                        elif qtype == "CRYPTO":
                            sector = "Criptomonedas"
                        elif qtype == "CURRENCY":
                            sector = "Forex / Divisas"
                        elif qtype == "INDEX":
                            sector = "Indices"
                        else:
                            sector = "N/A"

                    results.append({
                        "symbol": quote.get("symbol"),
                        "name": quote.get("shortname") or quote.get("longname") or quote.get("symbol"),
                        "exchange": quote.get("exchange"),
                        "quoteType": qtype,
                        "sector": sector,
                        "industry": quote.get("industry", "N/A")
                    })
            return results
        except Exception as e:
            print(f"[YahooFinance] Search error: {e}")
            return []

    def get_symbol_metadata(self, symbol: str) -> Dict[str, Any]:
        """Fetch metadata like long name, sector, and industry for a specific ticker."""
        self._init_session()
        
        metadata = {
            "symbol": symbol.upper(),
            "name": symbol.upper(),
            "sector": "International",
            "industry": "N/A"
        }

        # Try search first
        search_res = self.search_symbols(symbol)
        for res in search_res:
            if res["symbol"].upper() == symbol.upper():
                metadata["name"] = res["name"]
                if res["sector"] != "N/A":
                    metadata["sector"] = res["sector"]
                if res["industry"] != "N/A":
                    metadata["industry"] = res["industry"]
                return metadata

        if not self.crumb or not self.session:
            return metadata

        url = f"{BASE_URL}/v10/finance/quoteSummary/{symbol}"
        params = {"modules": "assetProfile,quoteType", "crumb": self.crumb}
        try:
            resp = self.session.get(url, params=params, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                result = data.get("quoteSummary", {}).get("result", [{}])[0]
                profile = result.get("assetProfile", {})
                qtype = result.get("quoteType", {})
                metadata["name"] = qtype.get("longName") or qtype.get("shortName") or symbol.upper()
                metadata["sector"] = profile.get("sector", "International")
                metadata["industry"] = profile.get("industry", "N/A")
        except Exception as e:
            pass
        
        return metadata

    def _fetch_single_chart_quote(self, sym_upper: str) -> tuple:
        """Fetch single quote via the robust /v8/finance/chart endpoint reusing session."""
        try:
            client = self.session or requests
            url = f"{BASE_URL}/v8/finance/chart/{sym_upper}"
            resp = client.get(url, params={"range": "1d", "interval": "1d"}, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
                price = meta.get("regularMarketPrice")
                prev_close = meta.get("chartPreviousClose")
                
                change = None
                change_percent = None
                if price is not None and prev_close is not None:
                    change = price - prev_close
                    change_percent = (change / prev_close) * 100 if prev_close != 0 else 0
                    
                return sym_upper, {
                    "price": price,
                    "prev_close": prev_close,
                    "change": change,
                    "change_percent": change_percent,
                    "volume": meta.get("regularMarketVolume"),
                    "market_cap": None,
                    "pe": None,
                    "dividend_yield": None
                }
        except Exception:
            pass
        return sym_upper, None

    def _fetch_batch_chunk(self, chunk: List[str], quotes_dict: Dict[str, Any], now: float) -> bool:
        """Fetch a batch of symbols via /v7/finance/quote with automatic host fallback."""
        if not self.crumb or not self.session:
            return False

        symbols_str = ",".join(chunk)
        params = {"symbols": symbols_str, "crumb": self.crumb}

        for base in [BASE_URL, FALLBACK_BASE_URL]:
            try:
                url = f"{base}/v7/finance/quote"
                resp = self.session.get(url, params=params, timeout=8)
                if resp.status_code in (401, 403):
                    # Crumb expired or rejected
                    return False
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("quoteResponse", {}).get("result", [])
                    for q in results:
                        sym = q.get("symbol", "").upper()
                        quote_obj = {
                            "name": q.get("shortName") or q.get("longName") or sym,
                            "price": q.get("regularMarketPrice"),
                            "prev_close": q.get("regularMarketPreviousClose"),
                            "change": q.get("regularMarketChange"),
                            "change_percent": q.get("regularMarketChangePercent"),
                            "volume": q.get("regularMarketVolume"),
                            "market_cap": q.get("marketCap"),
                            "pe": q.get("trailingPE"),
                            "dividend_yield": q.get("dividendYield"),
                            "_cached_at": now
                        }
                        quotes_dict[sym] = quote_obj
                        self._cache[sym] = quote_obj
                    return True
            except Exception:
                continue
        return False

    def get_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Fetch real-time quotes for multiple symbols using optimized batch requests,
        in-memory TTL caching, automatic crumb renewal, and parallel fallback.
        """
        if not symbols:
            return {}

        now = time.time()
        symbols_upper = [s.strip().upper() for s in symbols if s.strip()]
        quotes_dict = {}
        missing_symbols = []

        # 1. Check in-memory cache
        for sym in symbols_upper:
            if sym in self._cache and (now - self._cache[sym]["_cached_at"] < self._cache_ttl):
                quotes_dict[sym] = self._cache[sym]
            else:
                missing_symbols.append(sym)

        if not missing_symbols:
            return quotes_dict

        self._init_session()

        # 2. Batch requests in chunks of 40 symbols (avoids URL length limits & timeouts)
        BATCH_SIZE = 40
        chunks = [missing_symbols[i:i + BATCH_SIZE] for i in range(0, len(missing_symbols), BATCH_SIZE)]

        for chunk in chunks:
            success = self._fetch_batch_chunk(chunk, quotes_dict, now)
            if not success:
                # If session/crumb expired or failed, force re-initialization and retry chunk
                self._init_session(force=True)
                if self.crumb and self.session:
                    self._fetch_batch_chunk(chunk, quotes_dict, now)

        # 3. Update missing symbols list
        missing_symbols = [s for s in missing_symbols if s not in quotes_dict]

        # 4. Parallel fallback using ThreadPoolExecutor on /v8/finance/chart for any remaining symbols
        if missing_symbols:
            with ThreadPoolExecutor(max_workers=min(12, len(missing_symbols))) as executor:
                results = executor.map(self._fetch_single_chart_quote, missing_symbols)
                for sym, q in results:
                    if q:
                        q["_cached_at"] = now
                        quotes_dict[sym] = q
                        self._cache[sym] = q

        return quotes_dict

    def get_historical_data(self, symbol: str, time_range: str = "1mo", interval: str = "1d") -> List[Dict[str, Any]]:
        """Fetch historical chart data for drawing charts reusing session with TTL cache."""
        sym_upper = symbol.upper()
        cache_key = (sym_upper, time_range, interval)
        now = time.time()
        if cache_key in self._hist_cache:
            entry = self._hist_cache[cache_key]
            if now - entry["cached_at"] < self._hist_cache_ttl:
                return entry["data"]

        self._init_session()
        client = self.session or requests
        if time_range == "1d":
            interval = "5m"
        elif time_range == "5d":
            interval = "15m"
            
        url = f"{BASE_URL}/v8/finance/chart/{sym_upper}"
        params = {"range": time_range, "interval": interval}
        
        try:
            resp = client.get(url, params=params, timeout=8)
            if resp.status_code != 200:
                resp = client.get(f"{FALLBACK_BASE_URL}/v8/finance/chart/{sym_upper}", params=params, timeout=8)
            resp.raise_for_status()
            data = resp.json()
            
            result = data.get("chart", {}).get("result", [{}])[0]
            timestamps = result.get("timestamp", [])
            quotes = result.get("indicators", {}).get("quote", [{}])[0]
            close_prices = quotes.get("close", [])
            
            chart_data = []
            for i, ts in enumerate(timestamps):
                if i < len(close_prices) and close_prices[i] is not None:
                    chart_data.append({
                        "time": ts,
                        "value": close_prices[i]
                    })
            
            self._hist_cache[cache_key] = {"data": chart_data, "cached_at": now}
            return chart_data
        except Exception as e:
            print(f"[YahooFinance] Chart fetch failed for {symbol}: {e}")
            return []

# Singleton instance
finance_client = YahooFinanceClient()



from .cedear_ratios_data import BYMA_CEDEAR_RATIOS

cedear_ratios: Dict[str, Dict[str, Any]] = {}

def load_cedear_ratios():
    global cedear_ratios
    url = "https://www.comafi.com.ar/custodiaglobal/2483-Programas-Cedear.note.aspx"
    
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            tables = soup.find_all('table')
            scraped = {}
            for table in tables:
                rows = table.find_all('tr')
                if len(rows) < 5:
                    continue
                header = [col.get_text(strip=True).lower() for col in rows[0].find_all(['td', 'th'])]
                
                idx_ratio = 2
                idx_byma = 5
                idx_origin = 6
                
                for idx, name in enumerate(header):
                    if 'ratio' in name:
                        idx_ratio = idx
                    elif 'iddemercado' in name or 'código' in name:
                        idx_byma = idx
                    elif 'origen' in name or 'ticker' in name:
                        idx_origin = idx
                        
                for row in rows[1:]:
                    cols = [col.get_text(strip=True) for col in row.find_all(['td', 'th'])]
                    if len(cols) <= max(idx_ratio, idx_byma, idx_origin):
                        continue
                    
                    byma_ticker = cols[idx_byma].strip().upper()
                    origin_ticker = cols[idx_origin].strip().upper()
                    ratio_str = cols[idx_ratio].strip()
                    
                    if not byma_ticker or not ratio_str:
                        continue
                        
                    match = re.match(r'^([\d\.,]+)\s*:\s*([\d\.,]+)$', ratio_str)
                    if match:
                        try:
                            num = float(match.group(1).replace('.', '').replace(',', '.'))
                            den = float(match.group(2).replace('.', '').replace(',', '.'))
                            ratio_val = num / den if den > 0 else 1.0
                            scraped[byma_ticker] = {
                                "symbol": byma_ticker,
                                "symbol_origin": origin_ticker,
                                "ratio": ratio_val
                            }
                        except ValueError:
                            pass
            if scraped:
                merged = scraped.copy()
                merged.update(BYMA_CEDEAR_RATIOS)
                cedear_ratios = merged
                print(f"[Cedears] Successfully loaded {len(cedear_ratios)} CEDEAR ratios (merged with fixed database).")
                return
        print("[Cedears] Failed to fetch Comafi table. Using fixed database.")
        cedear_ratios = BYMA_CEDEAR_RATIOS
    except Exception as e:
        print(f"[Cedears] Error loading ratios from Comafi ({e}). Using fixed database.")
        cedear_ratios = BYMA_CEDEAR_RATIOS

# ADR and CEDEAR ticker aliases (including BYMA local tickers and MEP/CCL variants)
ADR_CEDEAR_ALIASES = {
    # Argentine ADRs
    "SUPV": {"symbol": "SUPV", "symbol_origin": "SUPV", "ratio": 5.0},
    "SUPVD": {"symbol": "SUPV", "symbol_origin": "SUPV", "ratio": 5.0},
    "SUPVC": {"symbol": "SUPV", "symbol_origin": "SUPV", "ratio": 5.0},
    "YPF": {"symbol": "YPF", "symbol_origin": "YPF", "ratio": 1.0},
    "YPFD": {"symbol": "YPF", "symbol_origin": "YPF", "ratio": 1.0},
    "YPFDD": {"symbol": "YPF", "symbol_origin": "YPF", "ratio": 1.0},
    "YPFDC": {"symbol": "YPF", "symbol_origin": "YPF", "ratio": 1.0},
    "GGAL": {"symbol": "GGAL", "symbol_origin": "GGAL", "ratio": 10.0},
    "GGALD": {"symbol": "GGAL", "symbol_origin": "GGAL", "ratio": 10.0},
    "GGALC": {"symbol": "GGAL", "symbol_origin": "GGAL", "ratio": 10.0},
    "BMA": {"symbol": "BMA", "symbol_origin": "BMA", "ratio": 10.0},
    "BMAD": {"symbol": "BMA", "symbol_origin": "BMA", "ratio": 10.0},
    "BMAC": {"symbol": "BMA", "symbol_origin": "BMA", "ratio": 10.0},
    "BBAR": {"symbol": "BBAR", "symbol_origin": "BBAR", "ratio": 3.0},
    "BBARD": {"symbol": "BBAR", "symbol_origin": "BBAR", "ratio": 3.0},
    "BBARC": {"symbol": "BBAR", "symbol_origin": "BBAR", "ratio": 3.0},
    "PAM": {"symbol": "PAM", "symbol_origin": "PAM", "ratio": 25.0},
    "PAMP": {"symbol": "PAM", "symbol_origin": "PAM", "ratio": 25.0},
    "PAMPD": {"symbol": "PAM", "symbol_origin": "PAM", "ratio": 25.0},
    "PAMPC": {"symbol": "PAM", "symbol_origin": "PAM", "ratio": 25.0},
    "CEPU": {"symbol": "CEPU", "symbol_origin": "CEPU", "ratio": 10.0},
    "CEPUD": {"symbol": "CEPU", "symbol_origin": "CEPU", "ratio": 10.0},
    "CEPUC": {"symbol": "CEPU", "symbol_origin": "CEPU", "ratio": 10.0},
    "CRES": {"symbol": "CRESY", "symbol_origin": "CRESY", "ratio": 10.0},
    "CRESD": {"symbol": "CRESY", "symbol_origin": "CRESY", "ratio": 10.0},
    "CRESC": {"symbol": "CRESY", "symbol_origin": "CRESY", "ratio": 10.0},
    "TECO2": {"symbol": "TEO", "symbol_origin": "TEO", "ratio": 5.0},
    "TECO2D": {"symbol": "TEO", "symbol_origin": "TEO", "ratio": 5.0},
    "TECO2C": {"symbol": "TEO", "symbol_origin": "TEO", "ratio": 5.0},
    "LOMA": {"symbol": "LOMA", "symbol_origin": "LOMA", "ratio": 5.0},
    "LOMAD": {"symbol": "LOMA", "symbol_origin": "LOMA", "ratio": 5.0},
    "LOMAC": {"symbol": "LOMA", "symbol_origin": "LOMA", "ratio": 5.0},
    "IRS": {"symbol": "IRS", "symbol_origin": "IRS", "ratio": 10.0},
    "IRSD": {"symbol": "IRS", "symbol_origin": "IRS", "ratio": 10.0},
    "IRSC": {"symbol": "IRS", "symbol_origin": "IRS", "ratio": 10.0},
    "EDN": {"symbol": "EDN", "symbol_origin": "EDN", "ratio": 20.0},
    "EDND": {"symbol": "EDN", "symbol_origin": "EDN", "ratio": 20.0},
    "EDNC": {"symbol": "EDN", "symbol_origin": "EDN", "ratio": 20.0},
    "TGS": {"symbol": "TGS", "symbol_origin": "TGS", "ratio": 5.0},
    "TGSU2": {"symbol": "TGS", "symbol_origin": "TGS", "ratio": 5.0},
    "TGSU2D": {"symbol": "TGS", "symbol_origin": "TGS", "ratio": 5.0},
    "TGSU2C": {"symbol": "TGS", "symbol_origin": "TGS", "ratio": 5.0},
    # Common Cedear ticker aliases
    "GOGL": {"symbol": "GOOGL", "symbol_origin": "GOOGL", "ratio": 58.0},
    "GOGLD": {"symbol": "GOOGL", "symbol_origin": "GOOGL", "ratio": 58.0},
    "GOGLC": {"symbol": "GOOGL", "symbol_origin": "GOOGL", "ratio": 58.0},
}

# Load ratios on module import
load_cedear_ratios()

def get_cedear_info_by_symbol_and_date(symbol: str, date_val: Any = None) -> Dict[str, Any]:
    global cedear_ratios
    raw = str(symbol).strip().upper()
    
    # If string contains description pipe (e.g. "NUD | NU Holdings Ltd"), extract ticker part
    if '|' in raw:
        raw = raw.split('|')[0].strip()
    else:
        raw = raw.split()[0].strip() if raw else ""
        
    sym_clean = raw[:-3] if raw.endswith(".BA") else raw
    
    # 1. Direct alias check
    if sym_clean in ADR_CEDEAR_ALIASES:
        info = ADR_CEDEAR_ALIASES[sym_clean]
        res = {
            "ratio": info["ratio"],
            "symbol": info["symbol"],
            "symbol_origin": info["symbol_origin"]
        }
    # 2. Direct cedear_ratios check
    elif sym_clean in cedear_ratios:
        info = cedear_ratios[sym_clean]
        res = {
            "ratio": info["ratio"],
            "symbol": info["symbol"],
            "symbol_origin": info["symbol_origin"]
        }
    # 3. Trailing D (MEP) or C (CCL) check if >= 3 characters
    elif (sym_clean.endswith('D') or sym_clean.endswith('C')) and len(sym_clean) >= 3:
        stripped = sym_clean[:-1]
        if stripped in ADR_CEDEAR_ALIASES:
            info = ADR_CEDEAR_ALIASES[stripped]
            res = {
                "ratio": info["ratio"],
                "symbol": info["symbol"],
                "symbol_origin": info["symbol_origin"]
            }
        elif stripped in cedear_ratios:
            info = cedear_ratios[stripped]
            res = {
                "ratio": info["ratio"],
                "symbol": info["symbol"],
                "symbol_origin": info["symbol_origin"]
            }
        else:
            res = {
                "ratio": 1.0,
                "symbol": sym_clean,
                "symbol_origin": sym_clean
            }
    else:
        res = {
            "ratio": 1.0,
            "symbol": sym_clean,
            "symbol_origin": sym_clean
        }
        
    if res.get("symbol_origin") == "SPY" or sym_clean == "SPY":
        target_date = None
        if date_val is not None:
            if isinstance(date_val, (datetime.datetime, datetime.date)):
                target_date = date_val
                if isinstance(target_date, datetime.datetime):
                    target_date = target_date.date()
            elif isinstance(date_val, str):
                try:
                    clean_date = date_val.split('T')[0]
                    target_date = datetime.datetime.strptime(clean_date, "%Y-%m-%d").date()
                except ValueError:
                    pass
        
        if target_date is not None:
            if target_date < datetime.date(2026, 5, 29):
                res["ratio"] = 20.0
            else:
                res["ratio"] = 60.0
        else:
            # Default to the current ratio if no date is provided
            res["ratio"] = 60.0
            
    return res


def compute_portfolio_benchmark_series(
    transactions: List[Any],
    time_range: str = "ALL"
) -> Dict[str, Any]:
    """
    Calcula las series temporales de rendimiento porcentual acumulado normalizado (base 0%)
    tanto para la cartera del usuario como para el benchmark S&P 500 (SPY).
    Soporta rangos: '1M', '3M', '6M', '1A'/'1Y', 'ALL'/'TODO'.
    """
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    tx_list = []
    for tx in transactions:
        t_dict = tx if isinstance(tx, dict) else {
            "symbol": tx.symbol,
            "operation_type": tx.operation_type,
            "quantity": tx.quantity,
            "ratio": tx.ratio,
            "price_comparable": tx.price_comparable,
            "date": tx.date
        }
        d = t_dict.get("date")
        if isinstance(d, str):
            try:
                d = _dt.fromisoformat(d.replace("Z", "+00:00"))
            except Exception:
                d = _dt.now(_tz.utc)
        if hasattr(d, "tzinfo") and d.tzinfo is not None:
            d = d.astimezone(_tz.utc)
        else:
            d = d.replace(tzinfo=_tz.utc) if d else _dt.now(_tz.utc)
        t_dict["date"] = d
        tx_list.append(t_dict)

    # Filtrar operaciones de CASH y ordenar cronológicamente
    tx_list = [t for t in tx_list if str(t.get("symbol", "")).upper() != "CASH"]
    tx_list.sort(key=lambda x: x["date"])

    empty_response = {
        "range": time_range,
        "labels": [],
        "portfolio_returns": [],
        "benchmark_returns": [],
        "summary": {
            "portfolio_return": 0.0,
            "benchmark_return": 0.0,
            "alpha": 0.0
        }
    }

    if not tx_list:
        return empty_response

    # Obtener tickers internacionales subyacentes
    symbols_in_tx = list(set(t["symbol"].upper() for t in tx_list))
    underlying_syms = list(set([get_cedear_info_by_symbol_and_date(s).get("symbol_origin", s) for s in symbols_in_tx] + ["SPY"]))

    # Descargar precios históricos en paralelo
    def _fetch_hist(sym):
        try:
            raw = finance_client.get_historical_data(sym, time_range="2y", interval="1d")
            prices = {}
            for row in raw:
                dt_str = _dt.fromtimestamp(row["time"], tz=_tz.utc).strftime("%Y-%m-%d")
                prices[dt_str] = float(row["value"])
            return sym, prices
        except Exception:
            return sym, {}

    with ThreadPoolExecutor(max_workers=8) as ex:
        hist_map = dict(list(ex.map(_fetch_hist, underlying_syms)))

    spy_hist = hist_map.get("SPY", {})
    if not spy_hist:
        return empty_response

    all_trading_dates = sorted(spy_hist.keys())
    first_tx_date_str = tx_list[0]["date"].strftime("%Y-%m-%d")

    # Determinar fecha de corte según el rango solicitado
    now_utc = _dt.now(_tz.utc)
    cutoff_date_str = first_tx_date_str

    tr_upper = time_range.upper().strip() if time_range else "ALL"
    if tr_upper == "1M":
        target = (now_utc - _td(days=30)).strftime("%Y-%m-%d")
        cutoff_date_str = max(first_tx_date_str, target)
    elif tr_upper == "3M":
        target = (now_utc - _td(days=90)).strftime("%Y-%m-%d")
        cutoff_date_str = max(first_tx_date_str, target)
    elif tr_upper == "6M":
        target = (now_utc - _td(days=180)).strftime("%Y-%m-%d")
        cutoff_date_str = max(first_tx_date_str, target)
    elif tr_upper in ("1Y", "1A"):
        target = (now_utc - _td(days=365)).strftime("%Y-%m-%d")
        cutoff_date_str = max(first_tx_date_str, target)
    elif tr_upper in ("ALL", "TODO"):
        cutoff_date_str = first_tx_date_str

    valid_dates = [d for d in all_trading_dates if d >= cutoff_date_str]
    if not valid_dates:
        valid_dates = all_trading_dates[-30:] if len(all_trading_dates) >= 30 else all_trading_dates

    # Indexar transacciones por fecha (YYYY-MM-DD)
    tx_by_date: Dict[str, List[Dict[str, Any]]] = {}
    for tx in tx_list:
        d_str = tx["date"].strftime("%Y-%m-%d")
        if d_str not in tx_by_date:
            tx_by_date[d_str] = []
        tx_by_date[d_str].append(tx)

    # Posiciones iniciales antes de valid_dates[0]
    holdings: Dict[str, float] = {s: 0.0 for s in symbols_in_tx}
    last_known_prices: Dict[str, float] = {s: 0.0 for s in symbols_in_tx}

    start_date = valid_dates[0]
    for tx in tx_list:
        d_str = tx["date"].strftime("%Y-%m-%d")
        if d_str < start_date:
            s = tx["symbol"].upper()
            ratio = tx.get("ratio") or 1.0
            qty = tx["quantity"] / ratio
            if tx["operation_type"] == "BUY":
                holdings[s] += qty
                last_known_prices[s] = tx["price_comparable"]
            elif tx["operation_type"] == "SELL":
                holdings[s] = max(0.0, holdings[s] - qty)

    labels = []
    nav_port_series = []
    nav_spy_series = []

    # Base inicial 100.0
    labels.append(start_date)
    nav_port_series.append(100.0)
    nav_spy_series.append(100.0)

    # Transacciones en la fecha inicial
    if start_date in tx_by_date:
        for tx in tx_by_date[start_date]:
            s = tx["symbol"].upper()
            ratio = tx.get("ratio") or 1.0
            qty = tx["quantity"] / ratio
            if tx["operation_type"] == "BUY":
                holdings[s] += qty
                last_known_prices[s] = tx["price_comparable"]
            elif tx["operation_type"] == "SELL":
                holdings[s] = max(0.0, holdings[s] - qty)

    # Recorrer días hábiles
    for i in range(1, len(valid_dates)):
        cur_d = valid_dates[i]
        prev_d = valid_dates[i - 1]

        # Actualizar últimos precios conocidos
        for s in symbols_in_tx:
            us_sym = get_cedear_info_by_symbol_and_date(s).get("symbol_origin", s)
            p = hist_map.get(us_sym, {}).get(cur_d)
            if p is not None and p > 0:
                last_known_prices[s] = p

        # Retorno diario de la cartera ponderada
        val_start = 0.0
        val_end = 0.0
        for s, qty in holdings.items():
            if qty > 0:
                us_sym = get_cedear_info_by_symbol_and_date(s).get("symbol_origin", s)
                p_end = hist_map.get(us_sym, {}).get(cur_d, last_known_prices[s])
                p_start = hist_map.get(us_sym, {}).get(prev_d, p_end)
                if p_start > 0 and p_end > 0:
                    val_start += qty * p_start
                    val_end += qty * p_end

        r_port = (val_end / val_start - 1.0) if val_start > 0 else 0.0

        p_spy_end = spy_hist.get(cur_d)
        p_spy_start = spy_hist.get(prev_d)
        r_spy = (p_spy_end / p_spy_start - 1.0) if (p_spy_start and p_spy_end and p_spy_start > 0) else 0.0

        nav_port_series.append(nav_port_series[-1] * (1.0 + r_port))
        nav_spy_series.append(nav_spy_series[-1] * (1.0 + r_spy))
        labels.append(cur_d)

        # Aplicar operaciones del día
        if cur_d in tx_by_date:
            for tx in tx_by_date[cur_d]:
                s = tx["symbol"].upper()
                ratio = tx.get("ratio") or 1.0
                qty = tx["quantity"] / ratio
                if tx["operation_type"] == "BUY":
                    holdings[s] += qty
                    if last_known_prices[s] == 0:
                        last_known_prices[s] = tx["price_comparable"]
                elif tx["operation_type"] == "SELL":
                    holdings[s] = max(0.0, holdings[s] - qty)

    # Normalizar a porcentaje acumulado respecto a la fecha inicial
    base_port = nav_port_series[0] if nav_port_series else 100.0
    base_spy = nav_spy_series[0] if nav_spy_series else 100.0

    port_returns = [round((v / base_port - 1.0) * 100, 2) for v in nav_port_series]
    spy_returns = [round((v / base_spy - 1.0) * 100, 2) for v in nav_spy_series]

    final_port = port_returns[-1] if port_returns else 0.0
    final_spy = spy_returns[-1] if spy_returns else 0.0
    alpha = round(final_port - final_spy, 2)

    return {
        "range": tr_upper,
        "labels": labels,
        "portfolio_returns": port_returns,
        "benchmark_returns": spy_returns,
        "summary": {
            "portfolio_return": final_port,
            "benchmark_return": final_spy,
            "alpha": alpha
        }
    }

