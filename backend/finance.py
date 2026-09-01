import time
import re
import requests
import datetime
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional

BASE_URL = "https://query2.finance.yahoo.com"
FALLBACK_BASE_URL = "https://query1.finance.yahoo.com"
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
        self.session_expiry = 1800  # Refresh session after 30 min
        self.failed_cooldown = 300  # Don't hammer crumb endpoint if failed, wait 5 min
        
        # In-memory quote cache to prevent spamming on rapid polling (TTL: 45 seconds)
        self._cache = {}
        self._cache_ttl = 45

    def warmup(self):
        """Pre-warms the session in background so initial requests are instant."""
        try:
            self._init_session()
        except Exception:
            pass

    def _init_session(self):
        """Creates a requests session and retrieves the cookie + crumb from Yahoo Finance."""
        now = time.time()
        # If we have a valid session and not expired, skip
        if self.session and self.crumb and (now - self.last_session_time < self.session_expiry):
            return

        # If it failed recently, don't spam getcrumb on every single request
        if not self.crumb and (now - self.last_session_time < self.failed_cooldown):
            return

        self.last_session_time = now
        try:
            s = requests.Session()
            s.headers.update(HEADERS)
            # Step 1: Fetch cookie
            s.get("https://fc.yahoo.com", timeout=8)
            # Step 2: Fetch crumb from query2
            crumb_resp = s.get(f"{BASE_URL}/v1/test/getcrumb", timeout=8)
            if crumb_resp.status_code != 200:
                # Try fallback query1
                crumb_resp = s.get(f"{FALLBACK_BASE_URL}/v1/test/getcrumb", timeout=8)

            crumb_resp.raise_for_status()
            crumb_text = crumb_resp.text.strip()
            if crumb_text and not "<html" in crumb_text.lower():
                self.crumb = crumb_text
                s.params = {"crumb": self.crumb}
                self.session = s
                print(f"[YahooFinance] Session initialized successfully with crumb.")
            else:
                self.crumb = None
                self.session = s
        except Exception as e:
            # Silent fallback without breaking app
            self.session = requests.Session()
            self.session.headers.update(HEADERS)
            self.crumb = None

    def search_symbols(self, query: str) -> List[Dict[str, Any]]:
        """Search for symbols on Yahoo Finance."""
        url = f"{BASE_URL}/v1/finance/search"
        params = {"q": query, "quotesCount": 10, "newsCount": 0}
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
            if resp.status_code != 200:
                resp = requests.get(f"{FALLBACK_BASE_URL}/v1/finance/search", params=params, headers=HEADERS, timeout=8)
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
        """Fetch single quote via the robust /v8/finance/chart endpoint."""
        try:
            url = f"{BASE_URL}/v8/finance/chart/{sym_upper}"
            resp = requests.get(url, params={"range": "1d", "interval": "1d"}, headers=HEADERS, timeout=6)
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

    def get_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch real-time quotes for multiple symbols with caching and parallel fallback."""
        if not symbols:
            return {}

        now = time.time()
        symbols_upper = [s.strip().upper() for s in symbols if s.strip()]
        quotes_dict = {}
        missing_symbols = []

        # Check in-memory cache
        for sym in symbols_upper:
            if sym in self._cache and (now - self._cache[sym]["_cached_at"] < self._cache_ttl):
                quotes_dict[sym] = self._cache[sym]
            else:
                missing_symbols.append(sym)

        if not missing_symbols:
            return quotes_dict

        self._init_session()

        # 1. Try batch quotes using /v7/finance/quote if crumb is available
        if self.crumb and self.session:
            try:
                symbols_str = ",".join(missing_symbols)
                url = f"{BASE_URL}/v7/finance/quote"
                resp = self.session.get(url, params={"symbols": symbols_str, "crumb": self.crumb}, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("quoteResponse", {}).get("result", [])
                    for q in results:
                        sym = q.get("symbol", "").upper()
                        quote_obj = {
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
                    
                    # Update missing list
                    missing_symbols = [s for s in missing_symbols if s not in quotes_dict]
            except Exception:
                pass

        # 2. Parallel fallback using ThreadPoolExecutor on /v8/finance/chart
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
        """Fetch historical chart data for drawing charts."""
        if time_range == "1d":
            interval = "5m"
        elif time_range == "5d":
            interval = "15m"
            
        url = f"{BASE_URL}/v8/finance/chart/{symbol.upper()}"
        params = {"range": time_range, "interval": interval}
        
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
            if resp.status_code != 200:
                resp = requests.get(f"{FALLBACK_BASE_URL}/v8/finance/chart/{symbol.upper()}", params=params, headers=HEADERS, timeout=8)
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
