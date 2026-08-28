import time
import re
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional

BASE_URL = "https://query1.finance.yahoo.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

class YahooFinanceClient:
    def __init__(self):
        self.session = None
        self.crumb = None
        self.last_session_time = 0
        self.session_expiry = 3600  # Refresh session after 1 hour

    def _init_session(self):
        """Creates a requests session and retrieves the cookie + crumb from Yahoo Finance."""
        now = time.time()
        if self.session and (now - self.last_session_time < self.session_expiry):
            return

        try:
            s = requests.Session()
            s.headers.update(HEADERS)
            # Fetch cookie
            s.get("https://fc.yahoo.com", timeout=10)
            # Fetch crumb
            crumb_resp = s.get(f"{BASE_URL}/v1/test/getcrumb", timeout=10)
            crumb_resp.raise_for_status()
            self.crumb = crumb_resp.text.strip()
            
            s.params = {"crumb": self.crumb}
            self.session = s
            self.last_session_time = now
            print(f"[YahooFinance] Session initialized successfully with crumb: {self.crumb}")
        except Exception as e:
            print(f"[YahooFinance] Failed to initialize session with crumb: {e}. Falling back to crumb-less mode.")
            self.session = requests.Session()
            self.session.headers.update(HEADERS)
            self.crumb = None

    def search_symbols(self, query: str) -> List[Dict[str, Any]]:
        """Search for symbols on Yahoo Finance."""
        url = f"{BASE_URL}/v1/finance/search"
        params = {"q": query, "quotesCount": 10, "newsCount": 0}
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            results = []
            for quote in data.get("quotes", []):
                # Filter to only return equities, crypto, etc.
                if quote.get("quoteType") in ["EQUITY", "CRYPTO", "ETF", "INDEX"]:
                    results.append({
                        "symbol": quote.get("symbol"),
                        "name": quote.get("shortname") or quote.get("longname") or quote.get("symbol"),
                        "exchange": quote.get("exchange"),
                        "quoteType": quote.get("quoteType"),
                        "sector": quote.get("sector", "N/A"),
                        "industry": quote.get("industry", "N/A")
                    })
            return results
        except Exception as e:
            print(f"[YahooFinance] Search error: {e}")
            return []

    def get_symbol_metadata(self, symbol: str) -> Dict[str, Any]:
        """Fetch metadata like long name, sector, and industry for a specific ticker."""
        self._init_session()
        
        # Default fallback metadata
        metadata = {
            "symbol": symbol.upper(),
            "name": symbol.upper(),
            "sector": "International",
            "industry": "N/A"
        }

        # Try search first (often contains sector and name without crumb issues)
        search_res = self.search_symbols(symbol)
        for res in search_res:
            if res["symbol"].upper() == symbol.upper():
                metadata["name"] = res["name"]
                if res["sector"] != "N/A":
                    metadata["sector"] = res["sector"]
                if res["industry"] != "N/A":
                    metadata["industry"] = res["industry"]
                return metadata

        # If search does not match exactly, try quoteSummary (requires session crumb)
        if not self.crumb:
            return metadata

        url = f"{BASE_URL}/v10/finance/quoteSummary/{symbol}"
        params = {"modules": "assetProfile,quoteType"}
        try:
            resp = self.session.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                result = data.get("quoteSummary", {}).get("result", [{}])[0]
                
                profile = result.get("assetProfile", {})
                qtype = result.get("quoteType", {})
                
                metadata["name"] = qtype.get("longName") or qtype.get("shortName") or symbol.upper()
                metadata["sector"] = profile.get("sector", "International")
                metadata["industry"] = profile.get("industry", "N/A")
        except Exception as e:
            print(f"[YahooFinance] Error fetching metadata for {symbol}: {e}")
        
        return metadata

    def get_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch real-time quotes (price, change, previous close) for multiple symbols."""
        if not symbols:
            return {}
            
        self._init_session()
        symbols_str = ",".join([s.upper() for s in symbols])
        quotes_dict = {}

        # 1. Try batch quotes using /v7/finance/quote (requires crumb if initialized)
        if self.crumb:
            url = f"{BASE_URL}/v7/finance/quote"
            try:
                resp = self.session.get(url, params={"symbols": symbols_str}, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                results = data.get("quoteResponse", {}).get("result", [])
                for q in results:
                    symbol = q.get("symbol").upper()
                    quotes_dict[symbol] = {
                        "price": q.get("regularMarketPrice"),
                        "prev_close": q.get("regularMarketPreviousClose"),
                        "change": q.get("regularMarketChange"),
                        "change_percent": q.get("regularMarketChangePercent"),
                        "volume": q.get("regularMarketVolume"),
                        "market_cap": q.get("marketCap"),
                        "pe": q.get("trailingPE"),
                        "dividend_yield": q.get("dividendYield")
                    }
                return quotes_dict
            except Exception as e:
                print(f"[YahooFinance] Batch quote query failed ({e}). Falling back to individual charts.")

        # 2. Fallback: Fetch quotes individually using the robust /v8/finance/chart endpoint (no crumb needed)
        print("[YahooFinance] Fetching quotes via chart fallback...")
        for sym in symbols:
            sym_upper = sym.upper()
            try:
                url = f"{BASE_URL}/v8/finance/chart/{sym_upper}"
                # We only need 1 day of data
                resp = requests.get(url, params={"range": "1d", "interval": "1d"}, headers=HEADERS, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
                    
                    price = meta.get("regularMarketPrice")
                    prev_close = meta.get("chartPreviousClose")
                    
                    # Compute change manually if missing
                    change = None
                    change_percent = None
                    if price is not None and prev_close is not None:
                        change = price - prev_close
                        change_percent = (change / prev_close) * 100 if prev_close != 0 else 0
                        
                    quotes_dict[sym_upper] = {
                        "price": price,
                        "prev_close": prev_close,
                        "change": change,
                        "change_percent": change_percent,
                        "volume": meta.get("regularMarketVolume"),
                        "market_cap": None,  # Not available in chart meta
                        "pe": None,
                        "dividend_yield": None
                    }
            except Exception as e:
                print(f"[YahooFinance] Fallback quote failed for {sym_upper}: {e}")
                
        return quotes_dict

    def get_historical_data(self, symbol: str, time_range: str = "1mo", interval: str = "1d") -> List[Dict[str, Any]]:
        """Fetch historical chart data for drawing charts."""
        # Mapping standard ranges to valid yahoo ranges/intervals
        # Ranges: 1d, 5d, 1mo, 3mo, 6mo, 1y, 5y, max
        # Intervals: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo
        
        # Safety overrides
        if time_range == "1d":
            interval = "5m"
        elif time_range == "5d":
            interval = "15m"
            
        url = f"{BASE_URL}/v8/finance/chart/{symbol.upper()}"
        params = {"range": time_range, "interval": interval}
        
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
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
                        "time": ts, # Unix timestamp
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

# Load ratios on module import
load_cedear_ratios()
