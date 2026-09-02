import io
import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.dates import DateFormatter

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

from .finance import finance_client
from .cedear_ratios_data import BYMA_CEDEAR_RATIOS


# =========================================================================
# WEB APP CYBER-TERMINAL COLOR PALETTE
# =========================================================================
COLOR_PAGE_BG = colors.HexColor("#080c14")       # Deep terminal obsidian
COLOR_CARD_BG = colors.HexColor("#101524")       # Panel dark slate
COLOR_CARD_BORDER = colors.HexColor("#1e2738")   # Subtle dark border
COLOR_HEADER_BG = colors.HexColor("#141b2d")     # Table header background
COLOR_ROW_ALT1 = colors.HexColor("#0c101a")      # Row dark 1
COLOR_ROW_ALT2 = colors.HexColor("#101524")      # Row dark 2

# Neon Accent Colors (Matched to Web App)
COLOR_CYAN = colors.HexColor("#00f0ff")          # Web App Neon Cyan
COLOR_MAGENTA = colors.HexColor("#d92672")       # Web App Neon Magenta
COLOR_GREEN = colors.HexColor("#00ff66")         # Web App Neon Green
COLOR_RED = colors.HexColor("#ff3b30")           # Web App Neon Red
COLOR_AMBER = colors.HexColor("#f59e0b")         # Web App Neon Amber

# Text Colors
COLOR_TEXT_WHITE = colors.HexColor("#f8fafc")    # Crisp white
COLOR_TEXT_MAIN = colors.HexColor("#e2e8f0")     # Main light gray
COLOR_TEXT_MUTED = colors.HexColor("#94a3b8")    # Muted secondary text
COLOR_TEXT_DIM = colors.HexColor("#64748b")      # Dim label text

# Consistent Sector Color Map for Visual Correlation between Charts
SECTOR_COLOR_MAP = {
    "Tecnología": "#d92672",                 # Neon Magenta
    "Consumo Cíclico": "#f59e0b",            # Neon Amber / Gold
    "Índices / Benchmark": "#6366f1",        # Indigo
    "Servicios de Comunicación": "#00f0ff",  # Neon Cyan
    "Servicios Financieros": "#00ff66",      # Neon Green
    "Fintech / Financiero": "#14b8a6",       # Teal
    "Energía": "#ea580c",                    # Orange
    "Energía / Petróleo": "#ea580c",         # Orange
    "Cash & Liquidez": "#10b981",            # Emerald
    "Materias Primas / Oro": "#eab308",      # Gold
    "Criptoactivos / Digital": "#8b5cf6",    # Purple
    "Salud": "#ec4899",                      # Pink
    "Industrial": "#64748b",                 # Slate
    "Otros": "#475569"                       # Dark slate
}

# Known sector / name fallbacks for common Cedears / Argentine stocks
CUSTOM_METADATA_FALLBACKS = {
    "CASH": {"name": "Liquidez / Efectivo (USD)", "sector": "Cash & Liquidez"},
    "YPFD": {"name": "YPF S.A.", "sector": "Energía / Petróleo"},
    "YPF": {"name": "YPF S.A.", "sector": "Energía / Petróleo"},
    "VIST": {"name": "Vista Energy, S.A.B.", "sector": "Energía / Petróleo"},
    "SUPV": {"name": "Grupo Supervielle S.A.", "sector": "Servicios Financieros"},
    "GLD": {"name": "SPDR Gold Shares", "sector": "Materias Primas / Oro"},
    "IBIT": {"name": "iShares Bitcoin Trust", "sector": "Criptoactivos / Digital"},
    "SPY": {"name": "SPDR S&P 500 ETF Trust", "sector": "Índices / Benchmark"},
    "SPXL": {"name": "Direxion Daily S&P 500 Bull 3X", "sector": "Índices / Benchmark"},
    "GPRK": {"name": "Geopark Limited", "sector": "Energía / Petróleo"},
    "IREN": {"name": "Iris Energy Limited", "sector": "Tecnología"},
    "NU": {"name": "Nu Holdings Ltd.", "sector": "Fintech / Financiero"},
    "MELI": {"name": "MercadoLibre, Inc.", "sector": "Consumo Cíclico"},
    "SPOT": {"name": "Spotify Technology S.A.", "sector": "Servicios de Comunicación"},
}

SECTOR_TRANSLATIONS = {
    "Technology": "Tecnología",
    "Communication Services": "Servicios de Comunicación",
    "Financial Services": "Servicios Financieros",
    "Consumer Cyclical": "Consumo Cíclico",
    "Consumer Defensive": "Consumo Básico",
    "Healthcare": "Salud",
    "Energy": "Energía",
    "Industrials": "Industrial",
    "Basic Materials": "Materiales Básicos",
    "Real Estate": "Inmobiliario",
    "Utilities": "Servicios Públicos",
    "Cash & Equivalents": "Cash & Liquidez",
    "International": "Renta Variable"
}


def draw_cyber_background(c: canvas.Canvas, doc):
    """Draws the dark terminal background and neon top accent border on every page."""
    c.saveState()
    # Deep dark background
    c.setFillColor(COLOR_PAGE_BG)
    c.rect(0, 0, A4[0], A4[1], fill=True, stroke=False)
    
    # Dual Neon Top Accent Bar (Cyan to Magenta)
    c.setFillColor(COLOR_CYAN)
    c.rect(0, A4[1] - 3.5, A4[0] * 0.5, 3.5, fill=True, stroke=False)
    c.setFillColor(COLOR_MAGENTA)
    c.rect(A4[0] * 0.5, A4[1] - 3.5, A4[0] * 0.5, 3.5, fill=True, stroke=False)

    # Subtle side neon accents at top left
    c.setFillColor(COLOR_CYAN)
    c.rect(25, A4[1] - 12, 1.5, 6, fill=True, stroke=False)

    c.restoreState()


class InstitutionalFactsheetCanvas(canvas.Canvas):
    """
    Custom canvas that draws persistent regulatory legal disclaimers, methodology notes,
    and page numbering in the cyber-terminal theme on BOTH pages.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_persistent_footer(num_pages)
            super().showPage()
        super().save()

    def draw_persistent_footer(self, num_pages):
        self.saveState()
        
        # Footer Container Background (Dark Card Panel)
        footer_y = 12
        footer_h = 64
        self.setFillColor(colors.HexColor("#0c111c"))
        self.rect(25, footer_y, 545, footer_h, fill=True, stroke=False)
        
        # Border around footer
        self.setStrokeColor(COLOR_CARD_BORDER)
        self.setLineWidth(0.6)
        self.rect(25, footer_y, 545, footer_h, fill=False, stroke=True)
        
        # Top accent marker in Cyan
        self.setFillColor(COLOR_CYAN)
        self.rect(25, footer_y + footer_h - 1.5, 38, 1.5, fill=True, stroke=False)
        
        # Regulatory / Legal Disclaimer Header
        self.setFont("Helvetica-Bold", 5.6)
        self.setFillColor(COLOR_CYAN)
        self.drawString(32, footer_y + 51, "> NOTAS METODOLÓGICAS Y MARCO REGULATORIO (DISCLAIMER):")
        
        # Methodology note lines (broken into complete readable sentences without clipping)
        self.setFont("Helvetica", 5.0)
        self.setFillColor(COLOR_TEXT_MUTED)
        self.drawString(32, footer_y + 42, "METODOLOGÍA: Evolución calculada bajo Retorno Ponderado en el Tiempo (Time-Weighted Return - TWR / VCP Base 100), aislando aportes y retiros.")
        self.drawString(32, footer_y + 34, "TIR (XIRR) anualizada representa la rentabilidad ponderada por dinero (Money-Weighted Return). Benchmark: S&P 500 Total Return (SPY). Rf: 4.50% anual.")
        self.drawString(32, footer_y + 26, "AVISO LEGAL: Documento estrictamente informativo para seguimiento patrimonial. Rentabilidades históricas no garantizan rendimientos futuros.")
        self.drawString(32, footer_y + 18, "No constituye oferta de compraventa, recomendación ni asesoramiento financiero personalizado. Operaciones sujetas a riesgo y volatilidad de mercado.")
        
        # Bottom divider rule inside card
        self.setStrokeColor(COLOR_CARD_BORDER)
        self.setLineWidth(0.4)
        self.line(32, footer_y + 12, 563, footer_y + 12)
        
        # Document metadata & page number
        self.setFont("Helvetica", 5.8)
        self.setFillColor(COLOR_TEXT_DIM)
        report_date = datetime.now().strftime("%d/%m/%Y %H:%M")
        self.drawString(32, footer_y + 5, f"NEBULA STOCK TRACKER // FACTSHEET RENTA VARIABLE  |  Emisión: {report_date}  |  Cotizaciones Oficiales en Tiempo Real")
        
        # Page indicator in Cyan
        self.setFont("Helvetica-Bold", 5.8)
        self.setFillColor(COLOR_CYAN)
        page_str = f"PÁGINA {self._pageNumber} / {num_pages}"
        self.drawRightString(563, footer_y + 5, page_str)
        
        self.restoreState()


def get_underlying_us_ticker(symbol: str) -> str:
    """Resolve Argentine Cedear / local ticker to international US ticker if needed."""
    sym = symbol.upper().strip()
    if sym == "CASH":
        return "CASH"
    if sym in BYMA_CEDEAR_RATIOS:
        return BYMA_CEDEAR_RATIOS[sym].get("symbol_origin", sym)
    if len(sym) >= 4 and sym.endswith("D") and sym[:-1] in BYMA_CEDEAR_RATIOS:
        return BYMA_CEDEAR_RATIOS[sym[:-1]].get("symbol_origin", sym[:-1])
    if sym.endswith(".BA"):
        base = sym[:-3]
        if base in BYMA_CEDEAR_RATIOS:
            return BYMA_CEDEAR_RATIOS[base].get("symbol_origin", base)
        return base
    return sym


def fetch_all_historical_data(symbols: List[str]) -> Dict[str, Dict[str, float]]:
    """Fetch 2-year daily historical prices for benchmark and portfolio symbols in parallel."""
    unique_syms = list(set([get_underlying_us_ticker(s) for s in symbols if s != "CASH"] + ["SPY"]))
    
    def _fetch_single(sym):
        try:
            raw = finance_client.get_historical_data(sym, time_range="2y", interval="1d")
            prices = {}
            for row in raw:
                dt_str = datetime.fromtimestamp(row["time"], tz=timezone.utc).strftime("%Y-%m-%d")
                prices[dt_str] = float(row["value"])
            return sym, prices
        except Exception as e:
            print(f"[Factsheet] Error fetching history for {sym}: {e}")
            return sym, {}

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = dict(list(ex.map(_fetch_single, unique_syms)))
    return results


def fetch_symbol_metadata_batch(symbols: List[str]) -> Dict[str, Dict[str, str]]:
    """Fetch metadata (name, sector) for symbols."""
    meta_map = {}
    for s in symbols:
        upper = s.upper().strip()
        if upper in CUSTOM_METADATA_FALLBACKS:
            meta_map[upper] = CUSTOM_METADATA_FALLBACKS[upper]
            continue
        us_sym = get_underlying_us_ticker(upper)
        if us_sym in CUSTOM_METADATA_FALLBACKS:
            meta_map[upper] = CUSTOM_METADATA_FALLBACKS[us_sym]
            continue
        try:
            m = finance_client.get_symbol_metadata(us_sym)
            raw_sector = m.get("sector", "International")
            translated_sector = SECTOR_TRANSLATIONS.get(raw_sector, raw_sector)
            meta_map[upper] = {
                "name": m.get("name") or upper,
                "sector": translated_sector
            }
        except Exception:
            meta_map[upper] = {"name": upper, "sector": "Renta Variable"}
    return meta_map


def compute_factsheet_data(portfolio_data: Dict[str, Any], transactions: List[Any]) -> Dict[str, Any]:
    """Computes quantitative metrics and historical series."""
    items = portfolio_data.get("items", [])
    metrics = portfolio_data.get("metrics", {})
    closed_trades = portfolio_data.get("closed_trades", [])
    tir = portfolio_data.get("tir")
    realized_pnl = portfolio_data.get("realized_pnl", 0.0)
    realized_pnl_percent = portfolio_data.get("realized_pnl_percent", 0.0)

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
        d = t_dict["date"]
        if isinstance(d, str):
            try:
                d = datetime.fromisoformat(d.replace("Z", "+00:00"))
            except Exception:
                d = datetime.now(timezone.utc)
        if hasattr(d, "tzinfo") and d.tzinfo is not None:
            d = d.astimezone(timezone.utc)
        else:
            d = d.replace(tzinfo=timezone.utc) if d else datetime.now(timezone.utc)
        t_dict["date"] = d
        tx_list.append(t_dict)

    tx_list.sort(key=lambda x: x["date"])

    symbols_in_tx = list(set(t["symbol"].upper() for t in tx_list if t["symbol"].upper() != "CASH"))
    symbols_in_items = [i["symbol"].upper() for i in items if i["symbol"].upper() != "CASH"]
    all_symbols = list(set(symbols_in_tx + symbols_in_items))

    hist_map = fetch_all_historical_data(all_symbols)
    meta_map = fetch_symbol_metadata_batch(all_symbols + ["CASH"])

    portfolio_cost = sum(i.get("costo_total_usd", 0.0) or 0.0 for i in items)
    portfolio_value = sum(i.get("valor_actual_usd", 0.0) or (i.get("costo_total_usd", 0.0) or 0.0) for i in items)
    unrealized_pnl = portfolio_value - portfolio_cost

    spy_hist = hist_map.get("SPY", {})
    if tx_list and spy_hist:
        first_tx_date = tx_list[0]["date"].strftime("%Y-%m-%d")
        valid_dates = sorted([d for d in spy_hist.keys() if d >= first_tx_date])
    else:
        valid_dates = sorted(list(spy_hist.keys()))[-100:] if spy_hist else []

    tx_by_date: Dict[str, List[Dict[str, Any]]] = {}
    for tx in tx_list:
        d_str = tx["date"].strftime("%Y-%m-%d")
        if d_str not in tx_by_date:
            tx_by_date[d_str] = []
        tx_by_date[d_str].append(tx)

    holdings = {s: 0.0 for s in all_symbols}
    last_known_prices = {s: 0.0 for s in all_symbols}

    dates_series = []
    nav_port_series = []
    nav_spy_series = []

    if valid_dates:
        dates_series.append(valid_dates[0])
        nav_port_series.append(100.0)
        nav_spy_series.append(100.0)

        for i in range(len(valid_dates)):
            cur_d = valid_dates[i]
            prev_d = valid_dates[i - 1] if i > 0 else cur_d

            for s in all_symbols:
                us_sym = get_underlying_us_ticker(s)
                p = hist_map.get(us_sym, {}).get(cur_d)
                if p is not None and p > 0:
                    last_known_prices[s] = p

            if i > 0:
                val_start = 0.0
                val_end = 0.0
                for s, qty in holdings.items():
                    if qty > 0:
                        us_sym = get_underlying_us_ticker(s)
                        p_end = hist_map.get(us_sym, {}).get(cur_d, last_known_prices[s])
                        p_start = hist_map.get(us_sym, {}).get(prev_d, p_end)
                        if p_start > 0 and p_end > 0:
                            val_start += qty * p_start
                            val_end += qty * p_end

                r_port = (val_end / val_start - 1.0) if val_start > 0 else 0.0

                p_spy_end = spy_hist.get(cur_d)
                p_spy_start = spy_hist.get(prev_d)
                r_spy = (p_spy_end / p_spy_start - 1.0) if (p_spy_start and p_spy_end) else 0.0

                nav_port_series.append(nav_port_series[-1] * (1.0 + r_port))
                nav_spy_series.append(nav_spy_series[-1] * (1.0 + r_spy))
                dates_series.append(cur_d)

            if cur_d in tx_by_date:
                for tx in tx_by_date[cur_d]:
                    s = tx["symbol"].upper()
                    if s in holdings:
                        qty = tx["quantity"] / tx["ratio"]
                        if tx["operation_type"] == "BUY":
                            holdings[s] += qty
                            if last_known_prices[s] == 0:
                                last_known_prices[s] = tx["price_comparable"]
                        elif tx["operation_type"] == "SELL":
                            holdings[s] = max(0.0, holdings[s] - qty)
    else:
        dates_series = [datetime.now().strftime("%Y-%m-%d")]
        nav_port_series = [100.0]
        nav_spy_series = [100.0]

    nav_port_arr = np.array(nav_port_series)
    nav_spy_arr = np.array(nav_spy_series)

    if len(nav_port_arr) > 1:
        r_port = np.diff(nav_port_arr) / nav_port_arr[:-1]
        r_spy = np.diff(nav_spy_arr) / nav_spy_arr[:-1]
    else:
        r_port = np.array([0.0])
        r_spy = np.array([0.0])

    vol_port = float(np.std(r_port, ddof=1) * np.sqrt(252) * 100) if len(r_port) > 2 else 0.0
    vol_spy = float(np.std(r_spy, ddof=1) * np.sqrt(252) * 100) if len(r_spy) > 2 else 0.0

    rf = 0.045
    rf_daily = rf / 252

    days_count = len(nav_port_arr)
    years_elapsed = max(days_count / 252.0, 0.05)
    cum_ret_port = (nav_port_arr[-1] / nav_port_arr[0]) - 1.0
    cum_ret_spy = (nav_spy_arr[-1] / nav_spy_arr[0]) - 1.0
    ann_ret_port = float((1.0 + cum_ret_port) ** (1.0 / years_elapsed) - 1.0) if cum_ret_port > -1 else 0.0
    ann_ret_spy = float((1.0 + cum_ret_spy) ** (1.0 / years_elapsed) - 1.0) if cum_ret_spy > -1 else 0.0

    sharpe = float((ann_ret_port - rf) / (vol_port / 100)) if vol_port > 0.01 else 0.0

    neg_excess = np.minimum(0.0, r_port - rf_daily)
    downside_dev = float(np.sqrt(np.mean(neg_excess ** 2)) * np.sqrt(252))
    sortino = float((ann_ret_port - rf) / downside_dev) if downside_dev > 0.0001 else (sharpe if sharpe > 0 else 0.0)

    if len(r_port) > 2 and len(r_spy) > 2 and np.var(r_spy) > 1e-7:
        cov_matrix = np.cov(r_port, r_spy)
        beta = float(cov_matrix[0, 1] / np.var(r_spy, ddof=1))
    else:
        beta = 1.0

    alpha = float((ann_ret_port - (rf + beta * (ann_ret_spy - rf))) * 100)

    running_max_port = np.maximum.accumulate(nav_port_arr)
    dd_port_arr = (nav_port_arr - running_max_port) / running_max_port * 100.0
    max_dd_port = float(np.min(dd_port_arr)) if len(dd_port_arr) > 0 else 0.0

    running_max_spy = np.maximum.accumulate(nav_spy_arr)
    dd_spy_arr = (nav_spy_arr - running_max_spy) / running_max_spy * 100.0
    max_dd_spy = float(np.min(dd_spy_arr)) if len(dd_spy_arr) > 0 else 0.0

    calmar = float(abs(ann_ret_port / (max_dd_port / 100))) if max_dd_port < -0.1 else 0.0

    def _period_return(arr, n_days):
        if len(arr) <= 1:
            return 0.0
        idx = max(0, len(arr) - 1 - n_days)
        return float((arr[-1] / arr[idx] - 1.0) * 100.0)

    current_year = datetime.now().year
    ytd_idx = 0
    for idx_d, d_str in enumerate(dates_series):
        if d_str.startswith(str(current_year)):
            ytd_idx = idx_d
            break

    ytd_ret_port = float((nav_port_arr[-1] / nav_port_arr[ytd_idx] - 1.0) * 100.0) if ytd_idx < len(nav_port_arr) else 0.0
    ytd_ret_spy = float((nav_spy_arr[-1] / nav_spy_arr[ytd_idx] - 1.0) * 100.0) if ytd_idx < len(nav_spy_arr) else 0.0

    periods_table = [
        {"period": "1 Mes (21d)", "port": _period_return(nav_port_arr, 21), "spy": _period_return(nav_spy_arr, 21)},
        {"period": "3 Meses (63d)", "port": _period_return(nav_port_arr, 63), "spy": _period_return(nav_spy_arr, 63)},
        {"period": "6 Meses (126d)", "port": _period_return(nav_port_arr, 126), "spy": _period_return(nav_spy_arr, 126)},
        {"period": f"YTD ({current_year})", "port": ytd_ret_port, "spy": ytd_ret_spy},
        {"period": "1 Año (252d)", "port": _period_return(nav_port_arr, 252), "spy": _period_return(nav_spy_arr, 252)},
        {"period": "Desde Incepción", "port": float(cum_ret_port * 100), "spy": float(cum_ret_spy * 100)},
    ]
    for p in periods_table:
        p["alpha"] = p["port"] - p["spy"]

    sector_weights: Dict[str, float] = {}
    enhanced_items = []
    for item in items:
        sym = item["symbol"].upper()
        val = item.get("valor_actual_usd", 0.0) or item.get("costo_total_usd", 0.0) or 0.0
        meta = meta_map.get(sym, {"name": sym, "sector": "Renta Variable"})
        sec = meta.get("sector", "Renta Variable")
        sector_weights[sec] = sector_weights.get(sec, 0.0) + val
        
        weight_pct = (val / portfolio_value * 100) if portfolio_value > 0 else 0.0
        enhanced_items.append({
            **item,
            "name": meta.get("name", sym),
            "sector": sec,
            "weight_pct": weight_pct,
            "sector_color": SECTOR_COLOR_MAP.get(sec, "#94a3b8")
        })

    enhanced_items.sort(key=lambda x: (x.get("valor_actual_usd") or 0.0), reverse=True)

    sector_summary = []
    for sec, val in sorted(sector_weights.items(), key=lambda x: x[1], reverse=True):
        pct = (val / portfolio_value * 100) if portfolio_value > 0 else 0.0
        sector_summary.append({
            "sector": sec,
            "value_usd": val,
            "weight_pct": pct,
            "color": SECTOR_COLOR_MAP.get(sec, "#94a3b8")
        })

    return {
        "portfolio_value": portfolio_value,
        "portfolio_cost": portfolio_cost,
        "unrealized_pnl": unrealized_pnl,
        "realized_pnl": realized_pnl,
        "realized_pnl_percent": realized_pnl_percent,
        "tir": tir,
        "metrics": metrics,
        "closed_trades": closed_trades,
        "quant_metrics": {
            "vol_port": vol_port,
            "vol_spy": vol_spy,
            "sharpe": sharpe,
            "sortino": sortino,
            "beta": beta,
            "alpha": alpha,
            "max_dd_port": max_dd_port,
            "max_dd_spy": max_dd_spy,
            "calmar": calmar,
            "ann_ret_port": ann_ret_port * 100,
            "ann_ret_spy": ann_ret_spy * 100,
        },
        "periods_table": periods_table,
        "dates_series": dates_series,
        "nav_port_series": nav_port_series,
        "nav_spy_series": nav_spy_series,
        "dd_port_series": dd_port_arr.tolist(),
        "sector_summary": sector_summary,
        "holdings": enhanced_items
    }


def generate_factsheet_charts(data: Dict[str, Any]) -> Tuple[io.BytesIO, io.BytesIO]:
    """Generates high-resolution Matplotlib figures with dark cyber-terminal aesthetic."""
    dates_str = data.get("dates_series", [])
    nav_port = data.get("nav_port_series", [])
    nav_spy = data.get("nav_spy_series", [])
    dd_port = data.get("dd_port_series", [])
    sector_summary = data.get("sector_summary", [])
    holdings = data.get("holdings", [])

    dt_list = []
    for d in dates_str:
        try:
            dt_list.append(datetime.strptime(d, "%Y-%m-%d"))
        except Exception:
            dt_list.append(datetime.now())

    # --- FIGURE 1: Dark Terminal Performance Evolution & Drawdown (Ultra High Resolution) ---
    dark_fig_bg = "#0c101a"
    dark_axes_bg = "#090d16"
    
    fig1, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(7.57, 4.3), sharex=True, 
        gridspec_kw={'height_ratios': [2.7, 1.0], 'hspace': 0.12},
        facecolor=dark_fig_bg,
        dpi=400
    )
    ax1.set_facecolor(dark_axes_bg)
    ax2.set_facecolor(dark_axes_bg)

    # Top Plot: Portfolio vs SPY (No inner title, title is in ReportLab section header)
    ax1.plot(dt_list, nav_port, label="Cartera (VCP Cuota Parte)", color="#00f0ff", linewidth=2.4, antialiased=True)
    ax1.plot(dt_list, nav_spy, label="S&P 500 (SPY Benchmark)", color="#64748b", linewidth=1.5, linestyle="--", alpha=0.95, antialiased=True)
    ax1.axhline(100.0, color="#1e2738", linestyle=":", linewidth=0.9)
    ax1.set_ylabel("NAV (Base 100)", fontsize=8.5, fontweight="bold", color="#94a3b8")
    
    leg = ax1.legend(loc="upper left", fontsize=8, framealpha=0.92, facecolor='#101524', edgecolor='#1e2738')
    for text in leg.get_texts():
        text.set_color('#e2e8f0')
    
    ax1.tick_params(axis='both', labelsize=8, colors='#94a3b8')
    ax1.grid(color='#161d2d', linestyle=':', linewidth=0.7)
    for spine in ax1.spines.values():
        spine.set_color('#1e2738')

    # Bottom Plot: Underwater Drawdown
    ax2.plot(dt_list, dd_port, color="#ff3b30", linewidth=1.4, label="Drawdown Cartera", antialiased=True)
    ax2.fill_between(dt_list, dd_port, 0, color="#ff3b30", alpha=0.25)
    ax2.set_ylabel("DD (%)", fontsize=8, fontweight="bold", color="#94a3b8")
    ax2.axhline(0, color="#1e2738", linestyle=":", linewidth=0.9)
    ax2.yaxis.set_major_formatter(ticker.PercentFormatter(xmax=100, decimals=0))
    ax2.tick_params(axis='both', labelsize=8, colors='#94a3b8')
    ax2.grid(color='#161d2d', linestyle=':', linewidth=0.7)
    for spine in ax2.spines.values():
        spine.set_color('#1e2738')
    ax2.xaxis.set_major_formatter(DateFormatter("%b %y"))

    fig1.subplots_adjust(top=0.97, bottom=0.08, left=0.08, right=0.97, hspace=0.12)
    chart1_buf = io.BytesIO()
    fig1.savefig(chart1_buf, format="png", facecolor=dark_fig_bg, dpi=400, bbox_inches='tight', pad_inches=0.03)
    plt.close(fig1)
    chart1_buf.seek(0)

    # --- FIGURE 2: Single Enlarged Stock Allocation Donut Chart (All Stocks, No 'Otros') ---
    PALETTE_NEON = [
        "#00f0ff", "#6366f1", "#d92672", "#00ff66", "#a855f7", 
        "#f59e0b", "#3b82f6", "#14b8a6", "#f43f5e", "#eab308", 
        "#8b5cf6", "#10b981", "#ec4899", "#06b6d4"
    ]

    active_h = [h for h in holdings if (h.get("valor_actual_usd", 0.0) or 0.0) > 0]
    if not active_h:
        active_h = holdings[:9]

    h_symbols = [h["symbol"] for h in active_h]
    h_values = [(h.get("valor_actual_usd", 0.0) or 0.0) for h in active_h]
    h_weights = [h.get("weight_pct", 0.0) for h in active_h]
    h_colors = [PALETTE_NEON[i % len(PALETTE_NEON)] for i in range(len(active_h))]

    fig2, (ax_pie, ax_leg) = plt.subplots(
        1, 2, figsize=(7.57, 2.5), 
        gridspec_kw={'width_ratios': [1.15, 1.0]}, 
        facecolor=dark_fig_bg, dpi=400
    )
    ax_pie.set_facecolor(dark_fig_bg)
    ax_leg.set_facecolor(dark_fig_bg)
    ax_leg.axis('off')

    wedges, texts, autotexts = ax_pie.pie(
        h_values,
        startangle=140,
        colors=h_colors,
        wedgeprops=dict(width=0.48, edgecolor=dark_fig_bg, linewidth=2.0),
        autopct=lambda p: f'{p:.1f}%' if p >= 8.0 else '',
        pctdistance=0.74
    )
    for at in autotexts:
        at.set_color('#080c14')
        at.set_fontsize(7.5)
        at.set_fontweight('bold')

    ax_pie.text(0, 0, f'{len(active_h)} ACTIVOS\n100%', ha='center', va='center', color='#94a3b8', fontsize=8.2, fontweight='bold')

    # Breakdown Legend with all individual stocks (No 'Otros')
    leg_labels = [f'{s}: {w:.1f}%' for s, w in zip(h_symbols, h_weights)]
    leg = ax_leg.legend(
        wedges, leg_labels,
        loc='center left',
        fontsize=8.5,
        ncol=2,
        frameon=True,
        facecolor='#101524',
        edgecolor='#1e2738',
        labelcolor='#f8fafc',
        columnspacing=1.8,
        handletextpad=0.8,
        borderpad=1.0,
        labelspacing=0.9
    )
    for text in leg.get_texts():
        text.set_fontweight('600')

    fig2.subplots_adjust(top=0.96, bottom=0.04, left=0.02, right=0.98, wspace=0.05)
    chart2_buf = io.BytesIO()
    fig2.savefig(chart2_buf, format="png", facecolor=dark_fig_bg, dpi=400, bbox_inches='tight', pad_inches=0.03)
    plt.close(fig2)
    chart2_buf.seek(0)

    return chart1_buf, chart2_buf


def build_factsheet_pdf(portfolio_data: Dict[str, Any], transactions: List[Any]) -> bytes:
    """Generates the complete cyber-terminal dark theme institutional 2-page PDF Factsheet."""
    data = compute_factsheet_data(portfolio_data, transactions)
    chart1_buf, chart2_buf = generate_factsheet_charts(data)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=25,
        rightMargin=25,
        topMargin=20,
        bottomMargin=84
    )

    styles = getSampleStyleSheet()

    # Typography styles matching the dark web app (Decompressed & Elegant)
    style_title = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=18,
        textColor=COLOR_TEXT_WHITE,
        spaceAfter=3
    )
    style_subtitle = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.8,
        leading=11,
        textColor=COLOR_TEXT_MUTED
    )
    style_header_right_top = ParagraphStyle(
        'HeaderRightTop',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=12,
        alignment=2,
        textColor=COLOR_TEXT_MAIN
    )
    style_header_right_sub = ParagraphStyle(
        'HeaderRightSub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.2,
        leading=10,
        alignment=2,
        textColor=COLOR_TEXT_DIM
    )
    style_sec_title = ParagraphStyle(
        'SecTitle',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=8.8,
        leading=12,
        textColor=COLOR_TEXT_WHITE,
        spaceBefore=4,
        spaceAfter=5
    )
    style_cell = ParagraphStyle(
        'CellText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.6,
        leading=10.2,
        textColor=COLOR_TEXT_MAIN
    )
    style_cell_bold = ParagraphStyle(
        'CellTextBold',
        parent=style_cell,
        fontName='Helvetica-Bold',
        textColor=COLOR_TEXT_WHITE
    )
    style_cell_center = ParagraphStyle(
        'CellTextCenter',
        parent=style_cell,
        alignment=1
    )
    style_cell_right = ParagraphStyle(
        'CellTextRight',
        parent=style_cell,
        alignment=2
    )
    style_kpi_num = ParagraphStyle(
        'KpiNum',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=17,
        alignment=1,
        textColor=COLOR_TEXT_WHITE
    )
    style_kpi_label = ParagraphStyle(
        'KpiLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7.2,
        leading=10,
        alignment=1,
        textColor=COLOR_TEXT_MUTED
    )

    def make_page_header(subtitle_left: str) -> Table:
        report_date = datetime.now().strftime("%d de %B de %Y")
        h_data = [
            [
                Paragraph("<font color='#00f0ff'>&gt;</font> <b>FACTSHEET DE CARTERA — RENTA VARIABLE</b>", style_title),
                Paragraph(f"<font color='#00f0ff'>BENCHMARK:</font> S&P 500 (SPY)  |  <font color='#d92672'>MONEDA:</font> USD<br/><font color='#94a3b8'>FECHA DE EMISIÓN:</font> {report_date}", style_header_right_top)
            ],
            [
                Paragraph(subtitle_left, style_subtitle),
                Paragraph("ESTRATEGIA: GESTIÓN ACTIVA // RATIOS PPC COMPARABLES", style_header_right_sub)
            ]
        ]
        t = Table(h_data, colWidths=[355, 190])
        t.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
            ('TOPPADDING', (0, 1), (-1, 1), 3),
            ('BOTTOMPADDING', (0, 1), (-1, 1), 6),
            ('LINEBELOW', (0, 1), (-1, 1), 1.5, COLOR_CYAN)
        ]))
        return t

    story = []

    # =========================================================================
    # PÁGINA 1: RESUMEN EJECUTIVO, KPIS Y EVOLUCIÓN VS BENCHMARK
    # =========================================================================

    # --- Header Bar (Página 1) ---
    story.append(make_page_header("REPORTE EJECUTIVO // ANÁLISIS CUANTITATIVO DE RENDIMIENTO Y RIESGO"))
    story.append(Spacer(1, 8))

    # --- 3 KPI Cards: AUM, RESULTADO TOTAL (GANANCIAS REALIZADAS) Y TIR ---
    val_usd = f"${data['portfolio_value']:,.2f}"
    realized_val = data['realized_pnl']
    realized_pct = data['realized_pnl_percent']
    realized_sign = "+" if realized_val >= 0 else ""
    realized_col = "#00ff66" if realized_val >= 0 else "#ff3b30"
    realized_str = f"<font color='{realized_col}'>{realized_sign}${realized_val:,.2f} ({realized_sign}{realized_pct:.2f}%)</font>"
    
    tir_val = data['tir']
    tir_col = "#00ff66" if (tir_val or 0) >= 0 else "#ff3b30"
    tir_str = f"<font color='{tir_col}'>{tir_val:.2f}%</font>" if tir_val is not None else "—"

    kpi_table_data = [
        [
            Paragraph("AUM (VALOR ACTUAL DE CARTERA)", style_kpi_label),
            Paragraph("RESULTADO TOTAL (GANANCIAS REALIZADAS)", style_kpi_label),
            Paragraph("TIR ANUALIZADA (XIRR)", style_kpi_label)
        ],
        [
            Paragraph(f"<font color='#00f0ff'>{val_usd}</font>", style_kpi_num),
            Paragraph(realized_str, style_kpi_num),
            Paragraph(tir_str, style_kpi_num)
        ]
    ]
    t_kpis = Table(kpi_table_data, colWidths=[181, 182, 182])
    t_kpis.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COLOR_CARD_BG),
        ('BOX', (0, 0), (-1, -1), 0.8, COLOR_CARD_BORDER),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, COLOR_CARD_BORDER),
        ('TOPPADDING', (0, 0), (-1, 0), 5),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 2),
        ('TOPPADDING', (0, 1), (-1, 1), 2),
        ('BOTTOMPADDING', (0, 1), (-1, 1), 6),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER')
    ]))
    story.append(t_kpis)
    story.append(Spacer(1, 8))

    # --- Risk & Quantitative Metrics Table (Filas más altas) ---
    q = data["quant_metrics"]
    m = data["metrics"]
    
    story.append(Paragraph("<font color='#d92672'>&gt;</font> <b>MÉTRICAS CUANTITATIVAS DE RIESGO Y DESEMPEÑO (EQUITY METRICS)</b>", style_sec_title))
    
    quant_headers = ["MÉTRICA / RATIO", "CARTERA", "S&P 500 (SPY)", "INTERPRETACIÓN EN FONDOS DE RENTA VARIABLE"]
    quant_rows = [
        [
            Paragraph("<font color='#f8fafc'><b>Volatilidad Anualizada (&sigma;)</b></font>", style_cell),
            Paragraph(f"<font color='#00f0ff'><b>{q['vol_port']:.2f}%</b></font>", style_cell_center),
            Paragraph(f"{q['vol_spy']:.2f}%", style_cell_center),
            Paragraph("Dispersión estadística de retornos diarios anualizados (&radic;252 días).", style_cell)
        ],
        [
            Paragraph("<font color='#f8fafc'><b>Ratio de Sharpe (Rf = 4.5%)</b></font>", style_cell),
            Paragraph(f"<font color='#00f0ff'><b>{q['sharpe']:.2f}</b></font>", style_cell_center),
            Paragraph("—", style_cell_center),
            Paragraph("Exceso de retorno generado por unidad de volatilidad total.", style_cell)
        ],
        [
            Paragraph("<font color='#f8fafc'><b>Ratio de Sortino</b></font>", style_cell),
            Paragraph(f"<font color='#00f0ff'><b>{q['sortino']:.2f}</b></font>", style_cell_center),
            Paragraph("—", style_cell_center),
            Paragraph("Retorno ajustado penalizando exclusivamente la volatilidad negativa (downside).", style_cell)
        ],
        [
            Paragraph("<font color='#f8fafc'><b>Beta (&beta;) vs S&P 500</b></font>", style_cell),
            Paragraph(f"<font color='#00ff66'><b>{q['beta']:.2f}</b></font>", style_cell_center),
            Paragraph("1.00", style_cell_center),
            Paragraph("Sensibilidad sistemática frente al mercado (>1 agresivo, <1 defensivo).", style_cell)
        ],
        [
            Paragraph("<font color='#f8fafc'><b>Alfa de Jensen (&alpha; anual)</b></font>", style_cell),
            Paragraph(f"<font color='{'#00ff66' if q['alpha'] >= 0 else '#ff3b30'}'><b>{'+' if q['alpha'] >= 0 else ''}{q['alpha']:.2f}%</b></font>", style_cell_center),
            Paragraph("0.00%", style_cell_center),
            Paragraph("Exceso de retorno por sobre el modelo CAPM (valor agregado del portfolio).", style_cell)
        ],
        [
            Paragraph("<font color='#f8fafc'><b>Máximo Drawdown (MDD)</b></font>", style_cell),
            Paragraph(f"<font color='#ff3b30'><b>{q['max_dd_port']:.2f}%</b></font>", style_cell_center),
            Paragraph(f"<font color='#94a3b8'>{q['max_dd_spy']:.2f}%</font>", style_cell_center),
            Paragraph("Mayor pérdida histórica acumulada pico a valle durante el período evaluado.", style_cell)
        ],
        [
            Paragraph("<font color='#f8fafc'><b>Tasa de Acierto (Win Rate)</b></font>", style_cell),
            Paragraph(f"<font color='#00ff66'><b>{m.get('win_rate', 0):.1f}%</b></font>", style_cell_center),
            Paragraph("—", style_cell_center),
            Paragraph(f"{m.get('winning_trades', 0)} operaciones ganadoras de {m.get('total_trades', 0)} operaciones cerradas.", style_cell)
        ],
        [
            Paragraph("<font color='#f8fafc'><b>Factor Beneficio (Profit Factor)</b></font>", style_cell),
            Paragraph(f"<font color='#00ff66'><b>{m.get('profit_factor', 1):.2f}</b></font>", style_cell_center),
            Paragraph("—", style_cell_center),
            Paragraph("Ratio de ganancia bruta acumulada sobre pérdida bruta total.", style_cell)
        ]
    ]

    t_quant = Table([quant_headers] + quant_rows, colWidths=[135, 65, 75, 270])
    t_quant.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), COLOR_CYAN),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 7.6),
        ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
        ('ALIGN', (1, 0), (2, -1), 'CENTER'),
        ('BOX', (0, 0), (-1, -1), 0.6, COLOR_CARD_BORDER),
        ('INNERGRID', (0, 0), (-1, -1), 0.35, COLOR_CARD_BORDER),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [COLOR_ROW_ALT1, COLOR_ROW_ALT2]),
        ('TOPPADDING', (0, 0), (-1, -1), 4.6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4.6)
    ]))
    story.append(t_quant)
    story.append(Spacer(1, 8))

    # --- Chart 1: Título unificado en Story y Gráfico ampliado ---
    story.append(Paragraph("<font color='#d92672'>&gt;</font> <b>EVOLUCIÓN DE RENDIMIENTO ACUMULADO VS BENCHMARK (S&P 500)</b>", style_sec_title))
    story.append(Image(chart1_buf, width=545, height=252))
    story.append(Spacer(1, 8))

    # --- Returns by Period Table (Solo Cartera y S&P 500, filas más altas) ---
    story.append(Paragraph("<font color='#d92672'>&gt;</font> <b>RETORNOS COMPARATIVOS POR PERÍODO TEMPORAL</b>", style_sec_title))
    
    period_labels = ["1 MES", "3 MESES", "6 MESES", f"YTD ({datetime.now().year})", "1 AÑO", "INCEPCIÓN"]
    transposed_headers = ["SERIE / BENCHMARK"] + period_labels
    
    cartera_cells = [Paragraph("<font color='#00f0ff'><b>Cartera (VCP)</b></font>", style_cell)]
    spy_cells = [Paragraph("<font color='#f8fafc'><b>S&P 500 (SPY)</b></font>", style_cell)]
    
    for p in data["periods_table"]:
        port_col = "#00ff66" if p['port'] >= 0 else "#ff3b30"
        spy_col = "#00ff66" if p['spy'] >= 0 else "#ff3b30"
        
        cartera_cells.append(Paragraph(f"<font color='{port_col}'><b>{'+' if p['port'] >= 0 else ''}{p['port']:.2f}%</b></font>", style_cell_center))
        spy_cells.append(Paragraph(f"<font color='{spy_col}'>{'+' if p['spy'] >= 0 else ''}{p['spy']:.2f}%</font>", style_cell_center))
        
    t_periods = Table([transposed_headers, cartera_cells, spy_cells], colWidths=[125, 70, 70, 70, 70, 70, 70])
    t_periods.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), COLOR_CYAN),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 7.6),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('BOX', (0, 0), (-1, -1), 0.6, COLOR_CARD_BORDER),
        ('INNERGRID', (0, 0), (-1, -1), 0.35, COLOR_CARD_BORDER),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [COLOR_ROW_ALT1, COLOR_ROW_ALT2]),
        ('TOPPADDING', (0, 0), (-1, -1), 6.0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6.0)
    ]))
    story.append(t_periods)

    # Fin Página 1
    story.append(PageBreak())

    # =========================================================================
    # PÁGINA 2: DISTRIBUCIÓN (GRÁFICOS DUALES), TENENCIAS Y ESTADÍSTICAS
    # =========================================================================

    # --- Header Bar (Página 2 - Idéntico encabezado principal) ---
    story.append(make_page_header("COMPOSICIÓN DE LA CARTERA // ASIGNACIÓN DE ACTIVOS Y TENENCIAS"))
    story.append(Spacer(1, 6))

    # --- Single Stock Allocation Chart (No inner title, title as text Paragraph) ---
    story.append(Paragraph("<font color='#d92672'>&gt;</font> <b>DISTRIBUCIÓN POR ACTIVO / ACCIÓN (PARTICIPACIÓN TOTAL)</b>", style_sec_title))
    story.append(Image(chart2_buf, width=545, height=170))
    story.append(Spacer(1, 6))

    # --- Detailed Active Holdings Table (Filas más altas) ---
    story.append(Paragraph("<font color='#d92672'>&gt;</font> <b>TENENCIAS CONSOLIDADAS Y DESGLOSE POR ACTIVO (HOLDINGS)</b>", style_sec_title))
    
    holdings_headers = ["TICKER", "NOMBRE / EMPRESA", "SECTOR", "VN / ACC.", "PPC", "PRECIO", "VALOR (USD)", "PESO", "P&L LATENTE"]
    holdings_rows = []
    
    display_items = data["holdings"][:9]
    for h in display_items:
        sym = h["symbol"]
        name = h.get("name", sym)[:20]
        sec = h.get("sector", "Renta Variable")[:18]
        vn = f"{h['vn_total']:,.0f}" if h['vn_total'] % 1 == 0 else f"{h['vn_total']:,.2f}"
        ppc = f"${h['ppc_comparable']:.2f}"
        prc = f"${h['precio_afuera']:.2f}" if h.get('precio_afuera') is not None else "—"
        val = f"${h.get('valor_actual_usd', 0.0) or 0.0:,.2f}"
        weight = f"{h['weight_pct']:.1f}%"
        
        pnl_usd_val = h.get("pnl_usd", 0.0) or 0.0
        pnl_pct_val = h.get("pnl_percent", 0.0) or 0.0
        pnl_sign = "+" if pnl_usd_val >= 0 else ""
        pnl_col = "#00ff66" if pnl_usd_val >= 0 else "#ff3b30"
        pnl_txt = f"{pnl_sign}${pnl_usd_val:,.0f} ({pnl_sign}{pnl_pct_val:.1f}%)" if sym != "CASH" else "—"

        holdings_rows.append([
            Paragraph(f"<font color='#00f0ff'><b>{sym}</b></font>", style_cell_bold),
            Paragraph(f"<font color='#f8fafc'>{name}</font>", style_cell),
            Paragraph(f"<font color='#94a3b8'>{sec}</font>", style_cell),
            Paragraph(vn, style_cell_right),
            Paragraph(ppc, style_cell_right),
            Paragraph(prc, style_cell_right),
            Paragraph(f"<font color='#00f0ff'>{val}</font>", style_cell_right),
            Paragraph(f"<b>{weight}</b>", style_cell_center),
            Paragraph(f"<font color='{pnl_col}'><b>{pnl_txt}</b></font>", style_cell_right)
        ])

    t_holdings = Table([holdings_headers] + holdings_rows, colWidths=[40, 102, 85, 47, 47, 47, 63, 36, 78])
    t_holdings.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), COLOR_CYAN),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 7.2),
        ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
        ('ALIGN', (3, 0), (6, -1), 'RIGHT'),
        ('ALIGN', (7, 0), (7, -1), 'CENTER'),
        ('ALIGN', (8, 0), (8, -1), 'RIGHT'),
        ('BOX', (0, 0), (-1, -1), 0.6, COLOR_CARD_BORDER),
        ('INNERGRID', (0, 0), (-1, -1), 0.35, COLOR_CARD_BORDER),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [COLOR_ROW_ALT1, COLOR_ROW_ALT2]),
        ('TOPPADDING', (0, 0), (-1, -1), 4.2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4.2)
    ]))
    story.append(t_holdings)
    story.append(Spacer(1, 6))

    # --- Trading Activity & Closed Trades Summary (Filas más altas) ---
    story.append(Paragraph("<font color='#d92672'>&gt;</font> <b>ESTADÍSTICAS DE TRADING Y OPERACIONES CERRADAS</b>", style_sec_title))
    avg_loss_val = m.get('avg_loss', 0)
    largest_loss_val = m.get('largest_loss', 0)
    avg_loss_str = f"-${abs(avg_loss_val):.2f}" if avg_loss_val < 0 else f"${avg_loss_val:.2f}"
    largest_loss_str = f"-${abs(largest_loss_val):.2f}" if largest_loss_val < 0 else f"${largest_loss_val:.2f}"

    trade_stats = [
        [
            Paragraph(f"<font color='#94a3b8'>Total Operaciones:</font> <font color='#00f0ff'><b>{m.get('total_trades', 0)}</b></font>", style_cell),
            Paragraph(f"<font color='#94a3b8'>Ops Ganadoras:</font> <font color='#00ff66'><b>{m.get('winning_trades', 0)}</b></font>", style_cell),
            Paragraph(f"<font color='#94a3b8'>Ops Perdedoras:</font> <font color='#ff3b30'><b>{m.get('losing_trades', 0)}</b></font>", style_cell),
            Paragraph(f"<font color='#94a3b8'>Tasa Acierto:</font> <font color='#00ff66'><b>{m.get('win_rate', 0):.1f}%</b></font>", style_cell),
        ],
        [
            Paragraph(f"<font color='#94a3b8'>Ganancia Prom.:</font> <font color='#00ff66'><b>${m.get('avg_win', 0):.2f}</b></font>", style_cell),
            Paragraph(f"<font color='#94a3b8'>Pérdida Prom.:</font> <font color='#ff3b30'><b>{avg_loss_str}</b></font>", style_cell),
            Paragraph(f"<font color='#94a3b8'>Mayor Ganancia:</font> <font color='#00ff66'><b>${m.get('largest_win', 0):.2f}</b></font>", style_cell),
            Paragraph(f"<font color='#94a3b8'>Mayor Pérdida:</font> <font color='#ff3b30'><b>{largest_loss_str}</b></font>", style_cell),
        ]
    ]
    t_trade = Table(trade_stats, colWidths=[136, 136, 136, 137])
    t_trade.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COLOR_CARD_BG),
        ('BOX', (0, 0), (-1, -1), 0.6, COLOR_CARD_BORDER),
        ('INNERGRID', (0, 0), (-1, -1), 0.35, COLOR_CARD_BORDER),
        ('TOPPADDING', (0, 0), (-1, -1), 5.0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5.0)
    ]))
    story.append(t_trade)

    # Build document using InstitutionalFactsheetCanvas and draw_cyber_background
    doc.build(
        story, 
        canvasmaker=InstitutionalFactsheetCanvas, 
        onFirstPage=draw_cyber_background, 
        onLaterPages=draw_cyber_background
    )
    return buffer.getvalue()
