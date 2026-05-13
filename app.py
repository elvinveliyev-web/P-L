from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st


# ============================================================
# FRANCHISE STATION P&L APP
# Admin-only multi-source upload + one-time mapping wizard
# ============================================================

st.set_page_config(
    page_title="Franchise Station P&L",
    page_icon="⛽",
    layout="wide",
    initial_sidebar_state="expanded",
)

DATA_DIR = Path("pnl_app_data")
DATA_DIR.mkdir(exist_ok=True)
MASTER_FILE = DATA_DIR / "master_pnl_report.pkl"
MAPPING_FILE = DATA_DIR / "mapping_config.json"
MANIFEST_FILE = DATA_DIR / "manifest.json"

try:
    ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "admin123")
except Exception:
    ADMIN_PASSWORD = "admin123"

SOURCE_TYPES = [
    "ZSD50 / ZSD50G Sales Report",
    "Dealer Master / Akpet Dealer List",
    "FBL3N Accounting Records",
    "Discount Premium Report",
    "Rebate Report",
    "ATS Sales Report",
    "Amortization Report",
    "Margin Share Report",
    "Manual P&L Template",
]

PERIOD_LEVELS = ["Senelik", "Çeyreklik", "Aylık", "Haftalık", "Günlük"]
CURRENCY_OPTIONS = ["TL", "USD"]
SIGN_MODES = ["Dosyadaki işaretleri koru", "Tip bazlı otomatik işaret ver"]

# ------------------------------------------------------------
# P&L line metadata
# ------------------------------------------------------------

INFO_COLS = [
    "Year_Month_Quarter",
    "Year",
    "Quarter",
    "Month",
    "Date",
    "Contract Beginning",
    "Contract Expiration",
    "İstasyon",
    "Name",
    "District",
    "City",
    "Territory",
    "Territory Manager",
    "Area Sales Manager",
    "Dealer/Acenta",
    "Supply city for fuel",
]

DASHBOARD_FILTERS = [
    ("City", "Şehir"),
    ("Territory", "Bölge"),
    ("Dealer/Acenta", "Bayi Tipi"),
    ("Territory Manager", "Bölge Müdürü"),
    ("Area Sales Manager", "Satış Temsilcisi"),
    ("İstasyon", "İstasyon"),
    ("Name", "Bayi / İstasyon Adı"),
]

# Keep this close to the P&L structure shared by the user.
LINE_INFO: Dict[str, Dict[str, str]] = {
    "Fuel Volume": {"type": "Volumes", "source": "ZSD50 & ZSD50G"},
    "Gas Volume": {"type": "Volumes", "source": "ZSD50 & ZSD50G"},
    "Volume Total": {"type": "Volumes", "source": "ZSD50 & ZSD50G"},
    "Fuel Gross Sales": {"type": "Revenues", "source": "ZSD50 & ZSD50G"},
    "Gas Gross Sales": {"type": "Revenues", "source": "ZSD50 & ZSD50G"},
    "Gross Sales Total": {"type": "Revenues", "source": "ZSD50 & ZSD50G"},
    "Discount Included in Invoice Total": {"type": "Discounts", "source": "ZSD50 & ZSD50G"},
    "Discount Premium": {"type": "Discounts", "source": "Discount Premium Report"},
    "Rebate": {"type": "Rebates", "source": "Rebate Report"},
    "Additive": {"type": "Additives", "source": "ZSD50 & ZSD50G"},
    "ATS Commision Fee": {"type": "Incomes", "source": "FBL3N"},
    "ATS Discount": {"type": "Discounts", "source": "FBL3N"},
    "ATS Income": {"type": "Incomes", "source": "FBL3N"},
    "ATS Disc given to Customers": {"type": "Discounts", "source": "ATS Sales Reports"},
    "Fuel COGS": {"type": "Costs", "source": "ZSD50 & ZSD50G"},
    "Gas COGS": {"type": "Costs", "source": "ZSD50 & ZSD50G"},
    "COGS Total": {"type": "Costs", "source": "ZSD50 & ZSD50G"},
    "Gross Margin": {"type": "Calculated Area", "source": "Calculated"},
    "Fuel Variable Process Expenses All": {"type": "Expenses", "source": "FBL3N Direct Variable"},
    "Fuel Variable Logistic Expenses": {"type": "Expenses", "source": "FBL3N Direct Variable"},
    "Transport Income fuel only": {"type": "Incomes", "source": "FBL3N Direct Variable"},
    "Autogas Variable Logistic Expenses": {"type": "Expenses", "source": "FBL3N Direct Variable"},
    "Loyalty Card Expenses": {"type": "Expenses", "source": "FBL3N Direct Variable"},
    "Card Cost All": {"type": "Expenses", "source": "FBL3N Direct Fixed"},
    "Cards Income": {"type": "Incomes", "source": "FBL3N Income"},
    "Rent": {"type": "Expenses", "source": "FBL3N Direct Fixed"},
    "Rent Income": {"type": "Incomes", "source": "FBL3N Income"},
    "BAYİLİK SATIŞLARI/DEALERSHIP SALES": {"type": "Expenses", "source": "FBL3N Direct Fixed"},
    "ATS SATIŞLARI/VIS SALES": {"type": "Expenses", "source": "FBL3N Direct Fixed"},
    "KURUMSAL İLETİŞİM/CORPORATE COMMUNI": {"type": "Expenses", "source": "FBL3N Direct Fixed"},
    "PAZARLAMA/MARKETING": {"type": "Expenses", "source": "FBL3N Direct Fixed"},
    "SATIŞ DESTEK/SALES SUPPORT": {"type": "Expenses", "source": "FBL3N Direct Fixed"},
    "OTOMASYON/AUTOMATION": {"type": "Expenses", "source": "FBL3N Direct Fixed"},
    "MÜHENDİSLİK/ENGINEERING": {"type": "Expenses", "source": "FBL3N Direct Fixed"},
    "Engineering Expenses All": {"type": "Expenses", "source": "FBL3N Direct Fixed"},
    "MUHASEBE/ACCOUNTING": {"type": "Expenses", "source": "FBL3N Indirect Opex"},
    "İDARİ İŞLER/ADMINISTRATIVE": {"type": "Expenses", "source": "FBL3N Indirect Opex"},
    "İNSAN KAYNAKLARI/HR": {"type": "Expenses", "source": "FBL3N Indirect Opex"},
    "BİLGİ İŞLEM/IT": {"type": "Expenses", "source": "FBL3N Indirect Opex"},
    "GENEL YÖNETİM/GENERAL ADMIN": {"type": "Expenses", "source": "FBL3N Indirect Opex"},
    "OFİS/OFFICE": {"type": "Expenses", "source": "FBL3N Indirect Opex"},
    "İKMAL/SUPPLY": {"type": "Expenses", "source": "FBL3N Indirect Opex"},
    "TESİS/TERMINALS": {"type": "Expenses", "source": "FBL3N Indirect Opex"},
    "SEÇ-G/HSSE": {"type": "Expenses", "source": "FBL3N Indirect Opex"},
    "HUKUK/LEGAL": {"type": "Expenses", "source": "FBL3N Indirect Opex"},
    "Gain on sale of fixed assets All": {"type": "Incomes", "source": "FBL3N Income"},
    "Insurance Income All": {"type": "Incomes", "source": "FBL3N Income"},
    "Late Payment Charges All": {"type": "Incomes", "source": "FBL3N Income"},
    "Price Difference All": {"type": "Incomes", "source": "FBL3N Income"},
    "Market Commission Income": {"type": "Incomes", "source": "FBL3N Income"},
    "Penalty Charge": {"type": "Incomes", "source": "FBL3N Income"},
    "EMRA Fee All": {"type": "Incomes", "source": "FBL3N Income"},
    "Tangible_Total": {"type": "Amortization", "source": "Amortization"},
    "Intangible_Total": {"type": "Amortization", "source": "Amortization"},
    "Net Income": {"type": "Calculated Area", "source": "Calculated"},
    "EBITDA": {"type": "Calculated Area", "source": "Calculated"},
    "Card Expenses/Incomes": {"type": "Calculated Area", "source": "Calculated"},
    "Rent Expenses/Incomes": {"type": "Calculated Area", "source": "Calculated"},
    "Engineering Expenses": {"type": "Calculated Area", "source": "Calculated"},
    "Indirect Expenses From Unrelated Departments": {"type": "Calculated Area", "source": "Calculated"},
    "Incomes Total": {"type": "Calculated Area", "source": "Calculated"},
    "Amortizations": {"type": "Calculated Area", "source": "Calculated"},
    "Process & Logistic Variable Expenses": {"type": "Calculated Area", "source": "Calculated"},
    "Process & Logistic Variable Expenses-Level OP1": {"type": "Calculated Area", "source": "Calculated"},
    "Terminal costs -Level OP2": {"type": "Calculated Area", "source": "Calculated"},
    "Direct Expenses From Related Departments-Level OP3": {"type": "Calculated Area", "source": "Calculated"},
    "Working Capital Cost": {"type": "Expenses", "source": "Working Capital"},
    "Net Income-Working Capital Cost": {"type": "Calculated Area", "source": "Calculated"},
    "Margin Share-Diesel-Old": {"type": "Calculated Area", "source": "Margin Share"},
    "Margin Share-Diesel-New": {"type": "Calculated Area", "source": "Margin Share"},
    "Margin Share-Gasoline-Old": {"type": "Calculated Area", "source": "Margin Share"},
    "Margin Share-Gasoline-New": {"type": "Calculated Area", "source": "Margin Share"},
}

P_AND_L_LINES = list(LINE_INFO.keys())
INPUT_LINES = [line for line, info in LINE_INFO.items() if info["source"] != "Calculated"]
CALCULATED_LINES = [line for line, info in LINE_INFO.items() if info["source"] == "Calculated"]

SUMMARY_LINES = [
    "Volume Total",
    "Gross Sales Total",
    "COGS Total",
    "Gross Margin",
    "Process & Logistic Variable Expenses-Level OP1",
    "Terminal costs -Level OP2",
    "EBITDA",
    "Amortizations",
    "Net Income",
    "Working Capital Cost",
    "Net Income-Working Capital Cost",
]

PNL_ORDER = P_AND_L_LINES

INFO_ALIASES = {
    "Year_Month_Quarter": ["Year_Month_Quarter", "Year Month Quarter", "YearMonthQuarter"],
    "Year": ["Year", "Yıl", "Yil", "Fiscal Year", "Calendar Year"],
    "Quarter": ["Quarter", "Çeyrek", "Ceyrek"],
    "Month": ["Month", "Ay", "Posting Period", "Period"],
    "Date": ["Date", "Tarih", "Posting Date", "Document Date", "Fatura Tarihi", "Billing Date", "Invoice Date"],
    "Contract Beginning": ["Contract Beginning", "Contract_Beginning"],
    "Contract Expiration": ["Contract Expiration", "Contract_Expiration"],
    "İstasyon": ["İstasyon", "Istasyon", "Station", "Station Code", "Station_Code", "Bayi Kodu", "Bayi", "Customer", "Müşteri", "Musteri"],
    "Name": ["Name", "Station Name", "Station_Name", "Bayi Adı", "Bayi Adi", "Dealer Name", "Customer Name"],
    "District": ["District", "İlçe", "Ilce"],
    "City": ["City", "Şehir", "Sehir", "İl", "Il"],
    "Territory": ["Territory", "Region", "Bölge", "Bolge"],
    "Territory Manager": ["Territory Manager", "Territory_Manager", "Bölge Müdürü", "Bolge Muduru"],
    "Area Sales Manager": ["Area Sales Manager", "Area_Sales_Manager", "ASM", "Satış Temsilcisi", "Satis Temsilcisi"],
    "Dealer/Acenta": ["Dealer/Acenta", "Dealer_Acenta", "Dealer", "Acenta", "Bayi Tipi", "Dealer or Agency", "Counterparty"],
    "Supply city for fuel": ["Supply city for fuel", "Supply_city_for_fuel", "Supply City", "İkmal Şehri", "Ikmal Sehri"],
}

EXTRA_LINE_ALIASES = {
    "volume": "Volume Total",
    "volume total": "Volume Total",
    "fuel volume": "Fuel Volume",
    "gas volume": "Gas Volume",
    "fuel gross sales": "Fuel Gross Sales",
    "gas gross sales": "Gas Gross Sales",
    "gross sales": "Gross Sales Total",
    "gross sales total": "Gross Sales Total",
    "sales price": "Gross Sales Total",
    "satis fiyati": "Gross Sales Total",
    "tl net deger": "Gross Sales Total",
    "net deger": "Gross Sales Total",
    "discount": "Discount Included in Invoice Total",
    "indirim": "Discount Included in Invoice Total",
    "cogs": "COGS Total",
    "cogs total": "COGS Total",
    "fuel cogs": "Fuel COGS",
    "gas cogs": "Gas COGS",
    "gross margin": "Gross Margin",
    "ebitda": "EBITDA",
    "net income": "Net Income",
    "net income working capital cost": "Net Income-Working Capital Cost",
    "net income-working capital cost": "Net Income-Working Capital Cost",
    "working capital cost": "Working Capital Cost",
    "tangible total": "Tangible_Total",
    "intangible total": "Intangible_Total",
    "ats commission fee": "ATS Commision Fee",
    "ats commision fee": "ATS Commision Fee",
    "cards income": "Cards Income",
    "card income": "Cards Income",
}

ACCOUNT_TO_LINE = {
    "602101101": "ATS Commision Fee",
    "611500151": "ATS Discount",
    "602101102": "ATS Income",
    "760300118": "Loyalty Card Expenses",
    "760400133": "Rent",
    "760400137": "Rent",
    "649101100": "Rent Income",
    "679100102": "Gain on sale of fixed assets All",
    "600500102": "Insurance Income All",
    "602100801": "Late Payment Charges All",
    "602100701": "Price Difference All",
    "602300101": "Market Commission Income",
    "679100302": "Penalty Charge",
    "600500101": "EMRA Fee All",
    "602100901": "Rebate",
}

DEPARTMENT_KEYWORDS = {
    "bayilik": "BAYİLİK SATIŞLARI/DEALERSHIP SALES",
    "dealership": "BAYİLİK SATIŞLARI/DEALERSHIP SALES",
    "vis sales": "ATS SATIŞLARI/VIS SALES",
    "ats satis": "ATS SATIŞLARI/VIS SALES",
    "corporate": "KURUMSAL İLETİŞİM/CORPORATE COMMUNI",
    "kurumsal": "KURUMSAL İLETİŞİM/CORPORATE COMMUNI",
    "marketing": "PAZARLAMA/MARKETING",
    "pazarlama": "PAZARLAMA/MARKETING",
    "sales support": "SATIŞ DESTEK/SALES SUPPORT",
    "satis destek": "SATIŞ DESTEK/SALES SUPPORT",
    "automation": "OTOMASYON/AUTOMATION",
    "otomasyon": "OTOMASYON/AUTOMATION",
    "engineering": "MÜHENDİSLİK/ENGINEERING",
    "muhendislik": "MÜHENDİSLİK/ENGINEERING",
    "accounting": "MUHASEBE/ACCOUNTING",
    "muhasebe": "MUHASEBE/ACCOUNTING",
    "administrative": "İDARİ İŞLER/ADMINISTRATIVE",
    "idari": "İDARİ İŞLER/ADMINISTRATIVE",
    "human resource": "İNSAN KAYNAKLARI/HR",
    "insan kaynaklari": "İNSAN KAYNAKLARI/HR",
    "it": "BİLGİ İŞLEM/IT",
    "bilgi islem": "BİLGİ İŞLEM/IT",
    "general admin": "GENEL YÖNETİM/GENERAL ADMIN",
    "genel yonetim": "GENEL YÖNETİM/GENERAL ADMIN",
    "office": "OFİS/OFFICE",
    "ofis": "OFİS/OFFICE",
    "supply": "İKMAL/SUPPLY",
    "ikmal": "İKMAL/SUPPLY",
    "terminal": "TESİS/TERMINALS",
    "tesis": "TESİS/TERMINALS",
    "hsse": "SEÇ-G/HSSE",
    "sec g": "SEÇ-G/HSSE",
    "legal": "HUKUK/LEGAL",
    "hukuk": "HUKUK/LEGAL",
}

# ------------------------------------------------------------
# Utility functions
# ------------------------------------------------------------

def normalize_key(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("ı", "i")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def build_alias_map() -> Dict[str, str]:
    result: Dict[str, str] = {}
    for canonical, aliases in INFO_ALIASES.items():
        result[normalize_key(canonical)] = canonical
        for alias in aliases:
            result[normalize_key(alias)] = canonical
    return result


def build_line_alias_map() -> Dict[str, str]:
    result: Dict[str, str] = {}
    for line in LINE_INFO:
        result[normalize_key(line)] = line
        result[normalize_key(line.replace("_", " "))] = line
        result[normalize_key(line.replace("/", " "))] = line
        result[normalize_key(line.replace("-", " "))] = line
    for alias, canonical in EXTRA_LINE_ALIASES.items():
        result[normalize_key(alias)] = canonical
    return result


INFO_ALIAS_MAP = build_alias_map()
LINE_ALIAS_MAP = build_line_alias_map()


def resolve_info_col(col: object) -> str:
    key = normalize_key(col)
    return INFO_ALIAS_MAP.get(key, str(col).strip())


def resolve_line_name(value: object) -> Optional[str]:
    key = normalize_key(value)
    if not key:
        return None
    return LINE_ALIAS_MAP.get(key)


def coerce_numeric(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")

    s = series.astype(str).str.strip()
    s = s.str.replace("\u00a0", "", regex=False)
    s = s.str.replace(" ", "", regex=False)
    s = s.str.replace("−", "-", regex=False)

    # Parentheses as negative: (1,234.56)
    neg_mask = s.str.match(r"^\(.*\)$", na=False)
    s = s.str.replace("(", "", regex=False).str.replace(")", "", regex=False)

    # European number format: 1.234.567,89
    euro_mask = s.str.contains(r"\.\d{3}", regex=True, na=False) & s.str.contains(",", regex=False, na=False)
    s = s.where(~euro_mask, s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    s = s.where(euro_mask, s.str.replace(",", ".", regex=False))

    out = pd.to_numeric(s, errors="coerce")
    out = out.where(~neg_mask, -out.abs())
    return out


def blank_to_na(series: pd.Series) -> pd.Series:
    return series.replace(["", "nan", "NaN", "None", "<NA>", "NaT"], np.nan)


def safe_unique(df: pd.DataFrame, col: str) -> List[str]:
    if col not in df.columns:
        return []
    values = blank_to_na(df[col].astype(str).str.strip()).dropna().unique().tolist()
    return sorted(values)


def first_existing_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    lookup = {normalize_key(c): c for c in df.columns}
    for candidate in candidates:
        key = normalize_key(candidate)
        if key in lookup:
            return lookup[key]
    return None


def dedupe_columns(columns: List[Any]) -> List[str]:
    result = []
    counts: Dict[str, int] = {}
    for i, col in enumerate(columns):
        base = str(col).strip() if pd.notna(col) and str(col).strip() else f"Column_{i+1}"
        base = base.replace("\n", " ").strip()
        if base.lower().startswith("unnamed"):
            base = f"Column_{i+1}"
        count = counts.get(base, 0)
        if count:
            new_col = f"{base}_{count+1}"
        else:
            new_col = base
        counts[base] = count + 1
        result.append(new_col)
    return result


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [resolve_info_col(c) for c in out.columns]
    out.columns = dedupe_columns(list(out.columns))
    return out


def detect_currency_from_text(value: object, default_currency: str) -> str:
    text = str(value).upper()
    if "USD" in text or "$" in text:
        return "USD"
    if "TL" in text or "TRY" in text or "₺" in text:
        return "TL"
    return default_currency


def detect_product_from_text(value: object) -> str:
    text = normalize_key(value)
    if any(x in text for x in ["lpg", "autogas", "otogaz", "gaz"]):
        return "Gas"
    if any(x in text for x in ["gasoline", "benzin"]):
        return "Fuel"
    if any(x in text for x in ["diesel", "motorin", "fuel"]):
        return "Fuel"
    if "total" in text:
        return "Total"
    return "Total"


def line_type(line: str) -> str:
    return LINE_INFO.get(line, {}).get("type", "Unmapped")


def sign_for_line(line: str) -> int:
    ltype = line_type(line)
    if ltype in ["Costs", "Expenses", "Discounts", "Amortization"]:
        return -1
    return 1


def apply_sign_policy(df: pd.DataFrame, sign_mode: str) -> pd.DataFrame:
    out = df.copy()
    out["Value"] = coerce_numeric(out["Value"]).fillna(0.0)
    if sign_mode == "Tip bazlı otomatik işaret ver":
        out["Value"] = out.apply(lambda r: abs(float(r["Value"])) * sign_for_line(str(r["P&L Line"])), axis=1)
    return out


def safe_get_wide(wide: pd.DataFrame, line: str) -> pd.Series:
    if line in wide.columns:
        return pd.to_numeric(wide[line], errors="coerce").fillna(0.0)
    return pd.Series(0.0, index=wide.index)


def format_money(value: float, currency: str) -> str:
    symbol = "₺" if currency == "TL" else "$" if currency == "USD" else ""
    if pd.isna(value) or np.isinf(value):
        value = 0.0
    return f"{symbol}{value:,.0f}"


def format_number(value: float) -> str:
    if pd.isna(value) or np.isinf(value):
        value = 0.0
    return f"{value:,.0f}"


def format_ratio(value: float) -> str:
    if pd.isna(value) or np.isinf(value):
        return "-"
    return f"{value:.2%}"


def format_per_volume(value: float, currency: str) -> str:
    symbol = "₺" if currency == "TL" else "$" if currency == "USD" else ""
    if pd.isna(value) or np.isinf(value):
        return "-"
    return f"{symbol}{value:,.4f}"


def load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------
# Reading uploaded files with selectable header row
# ------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_excel_sheets(file_bytes: bytes) -> List[str]:
    return pd.ExcelFile(BytesIO(file_bytes)).sheet_names


@st.cache_data(show_spinner=False)
def read_excel_raw(file_bytes: bytes, sheet_name: str) -> pd.DataFrame:
    return pd.read_excel(BytesIO(file_bytes), sheet_name=sheet_name, header=None)


@st.cache_data(show_spinner=False)
def read_csv_raw(file_bytes: bytes) -> pd.DataFrame:
    encodings = ["utf-8-sig", "utf-8", "cp1254", "latin1"]
    last_error: Optional[Exception] = None
    for enc in encodings:
        try:
            return pd.read_csv(BytesIO(file_bytes), encoding=enc, header=None)
        except Exception as exc:
            last_error = exc
    raise last_error or ValueError("CSV okunamadı")


def read_uploaded_raw(file, sheet_name: Optional[str]) -> pd.DataFrame:
    file_bytes = file.getvalue()
    name = file.name.lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        sheets = get_excel_sheets(file_bytes)
        return read_excel_raw(file_bytes, sheet_name or sheets[0])
    if name.endswith(".csv"):
        return read_csv_raw(file_bytes)
    raise ValueError("Sadece Excel veya CSV dosyası destekleniyor.")


def make_dataframe_from_header(raw: pd.DataFrame, header_row: int) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    header_row = max(0, min(int(header_row), len(raw) - 1))
    columns = dedupe_columns(raw.iloc[header_row].tolist())
    df = raw.iloc[header_row + 1 :].copy()
    df.columns = columns
    df = df.dropna(how="all")
    df = df.loc[:, ~df.columns.astype(str).str.match(r"^Column_\d+$") | df.notna().any(axis=0).values]
    return standardize_columns(df)


def guess_header_row(raw: pd.DataFrame, max_rows: int = 20) -> int:
    known_keywords = [
        "product", "ürün", "urun", "malzeme", "tanim", "tanım", "net", "deger", "değer",
        "satis", "satış", "indirim", "station", "istasyon", "counterparty", "ftrl", "miktar",
        "year", "month", "quarter", "city", "territory", "name",
    ]
    best_row = 0
    best_score = -1
    for idx in range(min(len(raw), max_rows)):
        values = raw.iloc[idx].dropna().astype(str).tolist()
        row_text = " ".join(values)
        norm = normalize_key(row_text)
        keyword_score = sum(1 for kw in known_keywords if normalize_key(kw) in norm)
        non_empty_score = len(values) / max(1, raw.shape[1])
        unique_score = len(set(values)) / max(1, len(values)) if values else 0
        score = keyword_score * 10 + non_empty_score * 3 + unique_score
        if score > best_score:
            best_score = score
            best_row = idx
    return best_row


# ------------------------------------------------------------
# Period parsing and enrichment
# ------------------------------------------------------------

def parse_period_columns(df: pd.DataFrame, default_year: Optional[int] = None, default_month: Optional[int] = None) -> pd.DataFrame:
    out = df.copy()

    if "Date" in out.columns:
        out["Date"] = pd.to_datetime(out["Date"], errors="coerce", dayfirst=True)
    else:
        out["Date"] = pd.NaT

    if "Year_Month_Quarter" in out.columns:
        extracted = out["Year_Month_Quarter"].astype(str).str.extract(
            r"(?P<Year>\d{4})[-_/ ]*Q(?P<QuarterNo>\d{1})[-_/ ]*(?P<Month>\d{1,2})"
        )
        if "Year" not in out.columns:
            out["Year"] = pd.to_numeric(extracted["Year"], errors="coerce")
        else:
            out["Year"] = pd.to_numeric(out["Year"], errors="coerce").fillna(pd.to_numeric(extracted["Year"], errors="coerce"))
        if "Month" not in out.columns:
            out["Month"] = pd.to_numeric(extracted["Month"], errors="coerce")
        else:
            out["Month"] = pd.to_numeric(out["Month"], errors="coerce").fillna(pd.to_numeric(extracted["Month"], errors="coerce"))

    if "Year" in out.columns:
        out["Year"] = pd.to_numeric(out["Year"], errors="coerce")
    else:
        out["Year"] = out["Date"].dt.year

    if "Month" in out.columns:
        out["Month"] = pd.to_numeric(out["Month"], errors="coerce")
    else:
        out["Month"] = out["Date"].dt.month

    if default_year:
        out["Year"] = out["Year"].fillna(default_year)
    if default_month:
        out["Month"] = out["Month"].fillna(default_month)

    missing_date = out["Date"].isna()
    if missing_date.any():
        year = out["Year"].fillna(default_year or datetime.now().year).astype(int)
        month = out["Month"].fillna(default_month or 1).astype(int)
        fallback = pd.to_datetime({"year": year, "month": month, "day": 1}, errors="coerce")
        out.loc[missing_date, "Date"] = fallback.loc[missing_date]

    if "Quarter" not in out.columns:
        out["Quarter"] = "Q" + out["Date"].dt.quarter.astype("Int64").astype(str)
    else:
        q = out["Quarter"].astype(str).str.replace(".0", "", regex=False).str.strip()
        out["Quarter"] = np.where(q.str.upper().str.startswith("Q"), q, "Q" + q)

    out["Year"] = out["Date"].dt.year.astype("Int64")
    out["Month"] = out["Date"].dt.month.astype("Int64")
    out["Month_Label"] = out["Date"].dt.strftime("%Y-%m")
    out["Quarter_Label"] = out["Date"].dt.year.astype("Int64").astype(str) + "-Q" + out["Date"].dt.quarter.astype("Int64").astype(str)
    out["Year_Label"] = out["Date"].dt.year.astype("Int64").astype(str)
    iso = out["Date"].dt.isocalendar()
    out["Week_Label"] = iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)
    out["Day_Label"] = out["Date"].dt.strftime("%Y-%m-%d")
    out["Year_Month_Quarter"] = out["Year"].astype(str) + "-Q" + out["Date"].dt.quarter.astype(str) + "-" + out["Month"].astype(str)
    return out


def selected_period_column(df: pd.DataFrame, period_level: str) -> Tuple[pd.DataFrame, str]:
    out = df.copy()
    col = {
        "Senelik": "Year_Label",
        "Çeyreklik": "Quarter_Label",
        "Aylık": "Month_Label",
        "Haftalık": "Week_Label",
        "Günlük": "Day_Label",
    }.get(period_level, "Month_Label")
    out["Selected_Period"] = out[col].astype(str)
    return out, "Selected_Period"


# ------------------------------------------------------------
# Mapping helpers
# ------------------------------------------------------------

def make_empty_long() -> pd.DataFrame:
    cols = INFO_COLS + ["Currency", "Product", "P&L Line", "P&L Type", "Value", "Source Type", "Source File", "Is Calculated"]
    return pd.DataFrame(columns=cols)


def options_with_none(columns: List[str]) -> List[str]:
    return ["— seçilmedi —"] + list(columns)


def select_default(columns: List[str], saved: Optional[str] = None, candidates: Optional[List[str]] = None) -> int:
    opts = options_with_none(columns)
    if saved and saved in columns:
        return opts.index(saved)
    if candidates:
        lookup = {normalize_key(c): c for c in columns}
        for cand in candidates:
            key = normalize_key(cand)
            if key in lookup:
                return opts.index(lookup[key])
    return 0


def clean_selected(value: str) -> Optional[str]:
    return None if value == "— seçilmedi —" else value


def guess_mapping_for_source(source_type: str, columns: List[str]) -> Dict[str, Any]:
    lookup = {normalize_key(c): c for c in columns}

    def first(cands: List[str]) -> Optional[str]:
        for cand in cands:
            key = normalize_key(cand)
            if key in lookup:
                return lookup[key]
        return None

    mapping: Dict[str, Any] = {
        "mode": "Kolon mapping / wide source",
        "info_map": {},
        "line_map": {},
        "smart_map": {},
        "long_line_col": None,
        "long_value_col": None,
        "product_col": first(["Product", "Ürün", "Urun", "Ürün Açıklaması", "Product Group"]),
        "currency_col": first(["Currency", "Currency_Type", "Para Birimi", "PB"]),
        "default_year": datetime.now().year,
        "default_month": datetime.now().month,
    }

    for info in INFO_COLS:
        candidates = INFO_ALIASES.get(info, []) + [info]
        mapping["info_map"][info] = first(candidates)

    if "ZSD50" in source_type:
        mapping["product_col"] = first(["Product", "Ürün Açıklaması", "Urun Aciklamasi", "Ürün", "Malzeme", "Tanım", "Tanim"])
        mapping["smart_map"] = {
            "Volume by product": first(["Ftrl.mkt.", "Ftrl mkt", "Miktar", "Invoice Quantity", "Billing Quantity", "Net ağırlık", "Net agirlik"]),
            "Gross Sales by product": first(["Satış Fiyatı", "Satis Fiyati", "Gross Sales", "TL-Net Değer", "TL Net Deger", "Net Değer", "Net Deger"]),
            "COGS by product": first(["Maliyet", "COGS", "Cost", "Akpet Fuel Cost", "Akpet Gas Cost"]),
        }
        mapping["line_map"] = {
            "Discount Included in Invoice Total": first(["İndirim", "Indirim", "Discount"]),
            "Additive": first(["Katkı,Opr.", "Katki Opr", "Katkı", "Katki", "Additive"]),
        }

    return mapping


def normalize_dealer_master(df: pd.DataFrame, mapping: Dict[str, Any]) -> pd.DataFrame:
    info_map = mapping.get("info_map", {})
    out = pd.DataFrame()
    for canonical, source_col in info_map.items():
        if canonical in ["Date", "Year", "Quarter", "Month", "Year_Month_Quarter"]:
            continue
        if source_col and source_col in df.columns:
            out[canonical] = df[source_col]
    if "İstasyon" not in out.columns and "Name" not in out.columns:
        return pd.DataFrame()
    for col in out.columns:
        out[col] = out[col].astype(str).str.strip()
    keys = [c for c in ["İstasyon", "Name"] if c in out.columns]
    return out.drop_duplicates(subset=keys) if keys else out.drop_duplicates()


def classify_smart_product_line(base: str, product_value: object) -> str:
    product = detect_product_from_text(product_value)
    if base == "Volume by product":
        return "Gas Volume" if product == "Gas" else "Fuel Volume"
    if base == "Gross Sales by product":
        return "Gas Gross Sales" if product == "Gas" else "Fuel Gross Sales"
    if base == "COGS by product":
        return "Gas COGS" if product == "Gas" else "Fuel COGS"
    return base


def map_account_or_department(row: pd.Series) -> Optional[str]:
    row_text = " ".join([str(v) for v in row.values if pd.notna(v)])
    norm_text = normalize_key(row_text)
    digits = re.sub(r"\D", "", row_text)

    for acc, line in ACCOUNT_TO_LINE.items():
        if acc in digits:
            return line
    for keyword, line in DEPARTMENT_KEYWORDS.items():
        if normalize_key(keyword) in norm_text:
            return line

    if "transport" in norm_text and "income" in norm_text:
        return "Transport Income fuel only"
    if "shipping" in norm_text or "logistic" in norm_text:
        return "Fuel Variable Logistic Expenses"
    if "storage" in norm_text or "customs" in norm_text or "pipeline" in norm_text or "facility" in norm_text:
        return "Fuel Variable Process Expenses All"
    if "amort" in norm_text and "intangible" in norm_text:
        return "Intangible_Total"
    if "amort" in norm_text and "tangible" in norm_text:
        return "Tangible_Total"
    return None


def normalize_pnl_source(
    df: pd.DataFrame,
    mapping: Dict[str, Any],
    source_type: str,
    source_file: str,
    default_currency: str,
    sign_mode: str,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return pnl_long, dealer_master, audit dataframe."""
    if df.empty:
        return make_empty_long(), pd.DataFrame(), pd.DataFrame()

    mapping_mode = mapping.get("mode", "Kolon mapping / wide source")
    default_year = mapping.get("default_year")
    default_month = mapping.get("default_month")

    if source_type == "Dealer Master / Akpet Dealer List" or mapping_mode == "Dealer master mapping":
        return make_empty_long(), normalize_dealer_master(df, mapping), pd.DataFrame()

    # Build base info frame
    info_map = mapping.get("info_map", {})
    base = pd.DataFrame(index=df.index)
    for canonical in INFO_COLS:
        source_col = info_map.get(canonical)
        if source_col and source_col in df.columns:
            base[canonical] = df[source_col]
        else:
            base[canonical] = np.nan

    # Long/premapped source mode
    rows: List[pd.DataFrame] = []
    unmapped_records: List[Dict[str, Any]] = []

    product_col = mapping.get("product_col")
    currency_col = mapping.get("currency_col")

    if product_col and product_col in df.columns:
        product_series = df[product_col].apply(detect_product_from_text)
    else:
        product_series = pd.Series("Total", index=df.index)

    if currency_col and currency_col in df.columns:
        currency_series = df[currency_col].apply(lambda x: detect_currency_from_text(x, default_currency))
    else:
        currency_series = pd.Series(default_currency, index=df.index)

    if mapping_mode == "Long P&L / pre-mapped source":
        line_col = mapping.get("long_line_col")
        value_col = mapping.get("long_value_col")
        if line_col and value_col and line_col in df.columns and value_col in df.columns:
            tmp = base.copy()
            tmp["P&L Line"] = df[line_col].apply(lambda x: resolve_line_name(x) or str(x).strip())
            tmp["Value"] = df[value_col]
            tmp["Product"] = product_series
            tmp["Currency"] = currency_series
            rows.append(tmp)

    elif mapping_mode == "FBL3N account/department auto mapping":
        value_col = mapping.get("long_value_col") or first_existing_column(df, ["Amount", "Tutar", "Local Currency Amount", "Amount in local currency", "Balance", "Bakiye", "Debit/Credit", "Debit", "Credit"])
        if value_col and value_col in df.columns:
            tmp = base.copy()
            tmp["P&L Line"] = df.apply(map_account_or_department, axis=1)
            tmp["Value"] = df[value_col]
            tmp["Product"] = product_series
            tmp["Currency"] = currency_series
            tmp = tmp[tmp["P&L Line"].notna()]
            rows.append(tmp)

    else:
        # Wide mapping: each selected source column becomes a P&L line.
        for line, source_col in mapping.get("line_map", {}).items():
            if source_col and source_col in df.columns:
                tmp = base.copy()
                tmp["P&L Line"] = line
                tmp["Value"] = df[source_col]
                tmp["Product"] = product_series
                tmp["Currency"] = currency_series
                rows.append(tmp)

        # Smart ZSD50 mapping: split one metric into Fuel/Gas line based on Product.
        for smart_name, source_col in mapping.get("smart_map", {}).items():
            if source_col and source_col in df.columns:
                tmp = base.copy()
                raw_product = df[product_col] if product_col and product_col in df.columns else product_series
                tmp["P&L Line"] = raw_product.apply(lambda x: classify_smart_product_line(smart_name, x))
                tmp["Value"] = df[source_col]
                tmp["Product"] = product_series
                tmp["Currency"] = currency_series
                rows.append(tmp)

        mapped_cols = set([c for c in mapping.get("line_map", {}).values() if c] + [c for c in mapping.get("smart_map", {}).values() if c])
        numeric_candidates = []
        for c in df.columns:
            if c in mapped_cols:
                continue
            vals = coerce_numeric(df[c])
            if vals.notna().sum() > 0 and vals.abs().sum() != 0:
                numeric_candidates.append(c)
        for c in numeric_candidates[:50]:
            unmapped_records.append({
                "Source File": source_file,
                "Column": c,
                "Numeric Non-null Rows": int(coerce_numeric(df[c]).notna().sum()),
                "Sample Sum": float(coerce_numeric(df[c]).fillna(0).sum()),
                "Note": "Bu numerik kolon henüz P&L satırına maplenmedi.",
            })

    if not rows:
        return make_empty_long(), pd.DataFrame(), pd.DataFrame(unmapped_records)

    out = pd.concat(rows, ignore_index=True)
    out = parse_period_columns(out, default_year=default_year, default_month=default_month)

    for col in INFO_COLS:
        if col not in out.columns:
            out[col] = np.nan
    out["Currency"] = out["Currency"].fillna(default_currency).astype(str)
    out["Product"] = out["Product"].fillna("Total").astype(str)
    out["P&L Line"] = out["P&L Line"].astype(str).str.strip()
    out = out[out["P&L Line"].isin(P_AND_L_LINES)]
    out["P&L Type"] = out["P&L Line"].apply(line_type)
    out["Source Type"] = source_type
    out["Source File"] = source_file
    out["Is Calculated"] = False
    out = apply_sign_policy(out, sign_mode)
    out = out[out["Value"].notna()]

    return out[INFO_COLS + ["Currency", "Product", "P&L Line", "P&L Type", "Value", "Source Type", "Source File", "Is Calculated"]], pd.DataFrame(), pd.DataFrame(unmapped_records)


def enrich_with_dealer_master(pnl: pd.DataFrame, dealer_master: pd.DataFrame) -> pd.DataFrame:
    if pnl.empty or dealer_master.empty:
        return pnl

    key = "İstasyon" if "İstasyon" in pnl.columns and "İstasyon" in dealer_master.columns else None
    if key is None and "Name" in pnl.columns and "Name" in dealer_master.columns:
        key = "Name"
    if key is None:
        return pnl

    enrich_cols = [
        c for c in [
            "Contract Beginning", "Contract Expiration", "Name", "District", "City",
            "Territory", "Territory Manager", "Area Sales Manager", "Dealer/Acenta", "Supply city for fuel",
        ]
        if c in dealer_master.columns and c != key
    ]
    dealer = dealer_master[[key] + enrich_cols].dropna(subset=[key]).drop_duplicates(subset=[key])
    result = pnl.merge(dealer, on=key, how="left", suffixes=("", "__dealer"))

    for col in enrich_cols:
        dealer_col = f"{col}__dealer"
        if dealer_col in result.columns:
            if col not in result.columns:
                result[col] = result[dealer_col]
            else:
                result[col] = result[col].where(blank_to_na(result[col].astype(str)).notna(), result[dealer_col])
            result = result.drop(columns=[dealer_col])
    return result


# ------------------------------------------------------------
# Calculated P&L lines
# ------------------------------------------------------------

def add_calculated_lines(pnl: pd.DataFrame) -> pd.DataFrame:
    if pnl.empty:
        return pnl

    raw = pnl.copy()
    # Avoid duplicating old calculated lines on refresh.
    raw = raw[~((raw["Is Calculated"] == True) | (raw["P&L Line"].isin(CALCULATED_LINES)))]

    group_cols = [c for c in INFO_COLS + ["Currency"] if c in raw.columns]
    # Product is not in group for calculated total P&L; calculations are station-period-currency level.
    group_cols = [c for c in group_cols if c != "Product"]

    wide = raw.pivot_table(index=group_cols, columns="P&L Line", values="Value", aggfunc="sum", fill_value=0).reset_index()
    wide.columns.name = None

    # Input totals if source does not provide total lines.
    if "Volume Total" not in wide.columns or safe_get_wide(wide, "Volume Total").abs().sum() == 0:
        wide["Volume Total"] = safe_get_wide(wide, "Fuel Volume") + safe_get_wide(wide, "Gas Volume")
    if "Gross Sales Total" not in wide.columns or safe_get_wide(wide, "Gross Sales Total").abs().sum() == 0:
        wide["Gross Sales Total"] = safe_get_wide(wide, "Fuel Gross Sales") + safe_get_wide(wide, "Gas Gross Sales")
    if "COGS Total" not in wide.columns or safe_get_wide(wide, "COGS Total").abs().sum() == 0:
        wide["COGS Total"] = safe_get_wide(wide, "Fuel COGS") + safe_get_wide(wide, "Gas COGS")

    wide["Gross Margin"] = (
        safe_get_wide(wide, "Gross Sales Total")
        + safe_get_wide(wide, "Discount Included in Invoice Total")
        + safe_get_wide(wide, "Discount Premium")
        + safe_get_wide(wide, "Rebate")
        + safe_get_wide(wide, "Additive")
        + safe_get_wide(wide, "ATS Commision Fee")
        + safe_get_wide(wide, "ATS Discount")
        + safe_get_wide(wide, "ATS Income")
        + safe_get_wide(wide, "ATS Disc given to Customers")
        + safe_get_wide(wide, "COGS Total")
    )

    wide["Process & Logistic Variable Expenses"] = (
        safe_get_wide(wide, "Fuel Variable Process Expenses All")
        + safe_get_wide(wide, "Fuel Variable Logistic Expenses")
        + safe_get_wide(wide, "Autogas Variable Logistic Expenses")
    )
    wide["Process & Logistic Variable Expenses-Level OP1"] = (
        safe_get_wide(wide, "Gross Margin")
        + safe_get_wide(wide, "Process & Logistic Variable Expenses")
        + safe_get_wide(wide, "Transport Income fuel only")
    )
    wide["Terminal costs -Level OP2"] = (
        safe_get_wide(wide, "Process & Logistic Variable Expenses-Level OP1")
        + safe_get_wide(wide, "TESİS/TERMINALS")
    )
    wide["Direct Expenses From Related Departments-Level OP3"] = (
        safe_get_wide(wide, "BAYİLİK SATIŞLARI/DEALERSHIP SALES")
        + safe_get_wide(wide, "ATS SATIŞLARI/VIS SALES")
        + safe_get_wide(wide, "KURUMSAL İLETİŞİM/CORPORATE COMMUNI")
        + safe_get_wide(wide, "PAZARLAMA/MARKETING")
        + safe_get_wide(wide, "SATIŞ DESTEK/SALES SUPPORT")
        + safe_get_wide(wide, "OTOMASYON/AUTOMATION")
        + safe_get_wide(wide, "MÜHENDİSLİK/ENGINEERING")
    )
    wide["Card Expenses/Incomes"] = (
        safe_get_wide(wide, "Loyalty Card Expenses")
        + safe_get_wide(wide, "Card Cost All")
        + safe_get_wide(wide, "Cards Income")
    )
    wide["Rent Expenses/Incomes"] = safe_get_wide(wide, "Rent") + safe_get_wide(wide, "Rent Income")
    wide["Engineering Expenses"] = safe_get_wide(wide, "Engineering Expenses All")
    wide["Indirect Expenses From Unrelated Departments"] = (
        safe_get_wide(wide, "MUHASEBE/ACCOUNTING")
        + safe_get_wide(wide, "İDARİ İŞLER/ADMINISTRATIVE")
        + safe_get_wide(wide, "İNSAN KAYNAKLARI/HR")
        + safe_get_wide(wide, "BİLGİ İŞLEM/IT")
        + safe_get_wide(wide, "GENEL YÖNETİM/GENERAL ADMIN")
        + safe_get_wide(wide, "OFİS/OFFICE")
        + safe_get_wide(wide, "İKMAL/SUPPLY")
        + safe_get_wide(wide, "SEÇ-G/HSSE")
        + safe_get_wide(wide, "HUKUK/LEGAL")
    )
    wide["Incomes Total"] = (
        safe_get_wide(wide, "Gain on sale of fixed assets All")
        + safe_get_wide(wide, "Insurance Income All")
        + safe_get_wide(wide, "Late Payment Charges All")
        + safe_get_wide(wide, "Price Difference All")
        + safe_get_wide(wide, "Market Commission Income")
        + safe_get_wide(wide, "Penalty Charge")
        + safe_get_wide(wide, "EMRA Fee All")
        + safe_get_wide(wide, "Transport Income fuel only")
    )
    wide["EBITDA"] = (
        safe_get_wide(wide, "Terminal costs -Level OP2")
        + safe_get_wide(wide, "Direct Expenses From Related Departments-Level OP3")
        + safe_get_wide(wide, "Card Expenses/Incomes")
        + safe_get_wide(wide, "Rent Expenses/Incomes")
        + safe_get_wide(wide, "Engineering Expenses")
        + safe_get_wide(wide, "Indirect Expenses From Unrelated Departments")
        + safe_get_wide(wide, "Incomes Total")
    )
    wide["Amortizations"] = safe_get_wide(wide, "Tangible_Total") + safe_get_wide(wide, "Intangible_Total")
    wide["Net Income"] = safe_get_wide(wide, "EBITDA") + safe_get_wide(wide, "Amortizations")
    wide["Net Income-Working Capital Cost"] = safe_get_wide(wide, "Net Income") + safe_get_wide(wide, "Working Capital Cost")

    derived_lines = [
        "Volume Total", "Gross Sales Total", "COGS Total",
        "Gross Margin", "Process & Logistic Variable Expenses", "Process & Logistic Variable Expenses-Level OP1",
        "Terminal costs -Level OP2", "Direct Expenses From Related Departments-Level OP3",
        "Card Expenses/Incomes", "Rent Expenses/Incomes", "Engineering Expenses",
        "Indirect Expenses From Unrelated Departments", "Incomes Total", "EBITDA",
        "Amortizations", "Net Income", "Net Income-Working Capital Cost",
    ]

    calc = wide[group_cols + derived_lines].melt(id_vars=group_cols, value_vars=derived_lines, var_name="P&L Line", value_name="Value")
    calc["Product"] = "Total"
    calc["P&L Type"] = calc["P&L Line"].apply(line_type)
    calc["Source Type"] = "Calculated"
    calc["Source File"] = "Calculated"
    calc["Is Calculated"] = True
    for col in INFO_COLS:
        if col not in calc.columns:
            calc[col] = np.nan

    # Replace calculated/total lines with the formula result to prevent double counting.
    # Example: if ZSD50 already has Gross Sales Total, the formula keeps that value
    # but the raw line is removed before appending the calculated line.
    raw_without_replaced_lines = raw[~raw["P&L Line"].isin(derived_lines)].copy()
    combined = pd.concat([raw_without_replaced_lines, calc[raw.columns]], ignore_index=True)
    return combined


# ------------------------------------------------------------
# Aggregation and display helpers
# ------------------------------------------------------------

def aggregate_long(df: pd.DataFrame, group_cols: List[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=group_cols + ["P&L Line", "Value"])
    cols = [c for c in group_cols if c in df.columns] + ["P&L Line"]
    return df.groupby(cols, dropna=False, as_index=False)["Value"].sum()


def make_wide(df: pd.DataFrame, index_cols: List[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    idx = [c for c in index_cols if c in df.columns]
    wide = df.pivot_table(index=idx, columns="P&L Line", values="Value", aggfunc="sum", fill_value=0).reset_index()
    wide.columns.name = None
    for line in SUMMARY_LINES:
        if line not in wide.columns:
            wide[line] = 0.0
    wide["Gross Margin %"] = np.where(wide["Gross Sales Total"] != 0, wide["Gross Margin"] / wide["Gross Sales Total"], np.nan)
    wide["EBITDA %"] = np.where(wide["Gross Sales Total"] != 0, wide["EBITDA"] / wide["Gross Sales Total"], np.nan)
    wide["Net Income %"] = np.where(wide["Gross Sales Total"] != 0, wide["Net Income"] / wide["Gross Sales Total"], np.nan)
    wide["Net Income / Volume"] = np.where(wide["Volume Total"] != 0, wide["Net Income"] / wide["Volume Total"], np.nan)
    return wide


def pnl_statement(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Order", "P&L Line", "P&L Type", "Value"])
    stmt = df.groupby(["P&L Line", "P&L Type"], as_index=False)["Value"].sum()
    order_map = {line: i + 1 for i, line in enumerate(PNL_ORDER)}
    stmt["Order"] = stmt["P&L Line"].map(order_map).fillna(9999).astype(int)
    return stmt.sort_values(["Order", "P&L Line"])[["Order", "P&L Line", "P&L Type", "Value"]]


def download_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


def style_numeric_table(df: pd.DataFrame):
    fmt = {}
    for col in df.columns:
        if col.endswith("%"):
            fmt[col] = "{:.2%}"
        elif col in SUMMARY_LINES or col in P_AND_L_LINES or "Income" in col or "Sales" in col or "COGS" in col or "Margin" in col or "EBITDA" in col or "Volume" in col:
            fmt[col] = "{:,.2f}"
    return df.style.format(fmt)


# ------------------------------------------------------------
# Admin mapping UI
# ------------------------------------------------------------

def mapping_ui_for_file(file, idx: int, saved_config: Dict[str, Any]) -> Tuple[Optional[pd.DataFrame], Dict[str, Any], Dict[str, Any]]:
    file_bytes = file.getvalue()
    file_name = file.name
    file_key = f"file_{idx}_{normalize_key(file_name)}"

    with st.expander(f"{idx + 1}. {file_name}", expanded=True):
        sheet_name = None
        if file_name.lower().endswith((".xlsx", ".xlsm", ".xls")):
            sheets = get_excel_sheets(file_bytes)
            default_sheet = 0
            saved_sheet = saved_config.get(file_name, {}).get("sheet_name")
            if saved_sheet in sheets:
                default_sheet = sheets.index(saved_sheet)
            sheet_name = st.selectbox("Excel sayfası", sheets, index=default_sheet, key=f"{file_key}_sheet")

        raw = read_uploaded_raw(file, sheet_name)
        guessed = guess_header_row(raw)
        saved_header = saved_config.get(file_name, {}).get("header_row")
        header_row = st.number_input(
            "Başlık satırı indexi — ekrandaki ZSD50 örneğinde gerçek başlık satırı 1 olabilir",
            min_value=0,
            max_value=max(0, min(50, len(raw) - 1)),
            value=int(saved_header if saved_header is not None else guessed),
            step=1,
            key=f"{file_key}_header",
        )

        preview_cols = st.columns(2)
        with preview_cols[0]:
            st.caption("Ham dosya ilk 8 satır")
            st.dataframe(raw.head(8), use_container_width=True, height=230)
        df = make_dataframe_from_header(raw, int(header_row))
        with preview_cols[1]:
            st.caption("Seçilen başlık satırı sonrası okunan veri")
            st.dataframe(df.head(8), use_container_width=True, height=230)

        source_type = st.selectbox("Kaynak tipi", SOURCE_TYPES, key=f"{file_key}_source")
        default_currency = st.selectbox("Varsayılan para birimi", CURRENCY_OPTIONS, index=0, key=f"{file_key}_currency")
        sign_mode = st.selectbox("İşaret politikası", SIGN_MODES, index=0, key=f"{file_key}_sign")

        saved_by_source = saved_config.get("by_source_type", {}).get(source_type, {})
        guessed_mapping = guess_mapping_for_source(source_type, list(df.columns))
        base_mapping = {**guessed_mapping, **saved_by_source}
        base_mapping.setdefault("info_map", guessed_mapping.get("info_map", {}))
        base_mapping.setdefault("line_map", guessed_mapping.get("line_map", {}))
        base_mapping.setdefault("smart_map", guessed_mapping.get("smart_map", {}))

        if source_type == "Dealer Master / Akpet Dealer List":
            mapping_mode_options = ["Dealer master mapping"]
        elif source_type == "FBL3N Accounting Records":
            mapping_mode_options = ["FBL3N account/department auto mapping", "Kolon mapping / wide source", "Long P&L / pre-mapped source"]
        else:
            mapping_mode_options = ["Kolon mapping / wide source", "Long P&L / pre-mapped source", "FBL3N account/department auto mapping"]

        saved_mode = base_mapping.get("mode", mapping_mode_options[0])
        mode_index = mapping_mode_options.index(saved_mode) if saved_mode in mapping_mode_options else 0
        mapping_mode = st.selectbox("Mapping modu", mapping_mode_options, index=mode_index, key=f"{file_key}_mode")

        columns = list(df.columns)
        mapping: Dict[str, Any] = {
            "mode": mapping_mode,
            "info_map": {},
            "line_map": {},
            "smart_map": {},
            "product_col": None,
            "currency_col": None,
            "long_line_col": None,
            "long_value_col": None,
            "default_year": datetime.now().year,
            "default_month": datetime.now().month,
        }

        st.markdown("##### Ortak bilgi kolonları")
        c_year, c_month = st.columns(2)
        with c_year:
            mapping["default_year"] = st.number_input("Dosyada yıl yoksa varsayılan yıl", min_value=2020, max_value=2100, value=int(base_mapping.get("default_year") or datetime.now().year), key=f"{file_key}_default_year")
        with c_month:
            mapping["default_month"] = st.number_input("Dosyada ay yoksa varsayılan ay", min_value=1, max_value=12, value=int(base_mapping.get("default_month") or datetime.now().month), key=f"{file_key}_default_month")

        info_cols_left, info_cols_right = st.columns(2)
        for n, info in enumerate(INFO_COLS):
            container = info_cols_left if n % 2 == 0 else info_cols_right
            with container:
                saved = base_mapping.get("info_map", {}).get(info)
                default_idx = select_default(columns, saved=saved, candidates=INFO_ALIASES.get(info, []) + [info])
                mapping["info_map"][info] = clean_selected(st.selectbox(info, options_with_none(columns), index=default_idx, key=f"{file_key}_info_{info}"))

        st.markdown("##### Ürün / para birimi")
        c1, c2 = st.columns(2)
        with c1:
            mapping["product_col"] = clean_selected(st.selectbox(
                "Ürün kolonu — Fuel/Gas ayırmak için",
                options_with_none(columns),
                index=select_default(columns, saved=base_mapping.get("product_col"), candidates=["Product", "Ürün Açıklaması", "Ürün", "Malzeme", "Tanım"]),
                key=f"{file_key}_product_col",
            ))
        with c2:
            mapping["currency_col"] = clean_selected(st.selectbox(
                "Para birimi kolonu",
                options_with_none(columns),
                index=select_default(columns, saved=base_mapping.get("currency_col"), candidates=["Currency", "Currency_Type", "Para Birimi"]),
                key=f"{file_key}_currency_col",
            ))

        if mapping_mode == "Long P&L / pre-mapped source":
            l1, l2 = st.columns(2)
            with l1:
                mapping["long_line_col"] = clean_selected(st.selectbox(
                    "P&L Line / Heading kolonu",
                    options_with_none(columns),
                    index=select_default(columns, saved=base_mapping.get("long_line_col"), candidates=["P&L Line", "Attribute.1", "Heading", "Kalem"]),
                    key=f"{file_key}_long_line",
                ))
            with l2:
                mapping["long_value_col"] = clean_selected(st.selectbox(
                    "Value / Amount kolonu",
                    options_with_none(columns),
                    index=select_default(columns, saved=base_mapping.get("long_value_col"), candidates=["Value", "Amount", "Tutar", "Değer", "Balance"]),
                    key=f"{file_key}_long_value",
                ))

        elif mapping_mode == "FBL3N account/department auto mapping":
            mapping["long_value_col"] = clean_selected(st.selectbox(
                "FBL3N tutar kolonu",
                options_with_none(columns),
                index=select_default(columns, saved=base_mapping.get("long_value_col"), candidates=["Amount", "Tutar", "Local Currency Amount", "Amount in local currency", "Balance", "Bakiye"]),
                key=f"{file_key}_fbl3n_amount",
            ))
            st.info("Bu modda hesap numarası / cost center / açıklama alanları satır bazında taranır ve P&L satırı otomatik bulunur.")

        elif mapping_mode == "Kolon mapping / wide source":
            st.markdown("##### ZSD50 gibi wide kaynaklar için akıllı mapping")
            s1, s2, s3 = st.columns(3)
            smart_options = {
                "Volume by product": ["Ftrl.mkt.", "Miktar", "Invoice Quantity", "Billing Quantity", "Net ağırlık", "Net agirlik"],
                "Gross Sales by product": ["Satış Fiyatı", "Satis Fiyati", "Gross Sales", "TL-Net Değer", "TL Net Deger", "Net Değer"],
                "COGS by product": ["Maliyet", "COGS", "Cost", "Akpet Fuel Cost", "Akpet Gas Cost"],
            }
            for j, (smart_name, candidates) in enumerate(smart_options.items()):
                container = [s1, s2, s3][j]
                with container:
                    saved = base_mapping.get("smart_map", {}).get(smart_name)
                    mapping["smart_map"][smart_name] = clean_selected(st.selectbox(
                        smart_name,
                        options_with_none(columns),
                        index=select_default(columns, saved=saved, candidates=candidates),
                        key=f"{file_key}_smart_{smart_name}",
                    ))

            st.markdown("##### Direkt P&L satır mapping")
            important_lines = [
                "Volume Total", "Gross Sales Total", "Discount Included in Invoice Total", "Discount Premium", "Rebate", "Additive",
                "ATS Commision Fee", "ATS Discount", "ATS Income", "ATS Disc given to Customers", "COGS Total",
                "Fuel Variable Process Expenses All", "Fuel Variable Logistic Expenses", "Transport Income fuel only",
                "Autogas Variable Logistic Expenses", "Loyalty Card Expenses", "Card Cost All", "Cards Income", "Rent", "Rent Income",
                "Tangible_Total", "Intangible_Total", "Working Capital Cost",
            ]
            col_a, col_b = st.columns(2)
            for n, line in enumerate(important_lines):
                container = col_a if n % 2 == 0 else col_b
                with container:
                    saved = base_mapping.get("line_map", {}).get(line)
                    mapping["line_map"][line] = clean_selected(st.selectbox(
                        line,
                        options_with_none(columns),
                        index=select_default(columns, saved=saved, candidates=[line]),
                        key=f"{file_key}_line_{line}",
                    ))

        file_meta = {
            "file_name": file_name,
            "sheet_name": sheet_name,
            "header_row": int(header_row),
            "source_type": source_type,
            "default_currency": default_currency,
            "sign_mode": sign_mode,
        }
        return df, mapping, file_meta


# ------------------------------------------------------------
# Dashboard UI
# ------------------------------------------------------------

def dashboard_ui(master: pd.DataFrame) -> None:
    st.sidebar.header("Filtreler")
    currency_values = safe_unique(master, "Currency") or CURRENCY_OPTIONS
    currency = st.sidebar.radio("Para birimi", currency_values, horizontal=True)
    period_level = st.sidebar.selectbox("Dönem", PERIOD_LEVELS, index=2)

    df = master[master["Currency"].astype(str).eq(currency)].copy()
    df, period_col = selected_period_column(df, period_level)

    period_values = safe_unique(df, period_col)
    selected_periods = st.sidebar.multiselect("Dönem seçimi", period_values, default=period_values)
    if selected_periods:
        df = df[df[period_col].astype(str).isin(selected_periods)]

    for col, label in DASHBOARD_FILTERS:
        vals = safe_unique(df, col)
        if vals:
            selected = st.sidebar.multiselect(label, vals)
            if selected:
                df = df[df[col].astype(str).isin(selected)]

    stmt = pnl_statement(df)

    def val(line: str) -> float:
        if stmt.empty:
            return 0.0
        return float(stmt.loc[stmt["P&L Line"].eq(line), "Value"].sum())

    total_volume = val("Volume Total")
    gross_sales = val("Gross Sales Total")
    gross_margin = val("Gross Margin")
    ebitda = val("EBITDA")
    net_income = val("Net Income")
    net_wcc = val("Net Income-Working Capital Cost")

    st.subheader("Genel Dashboard")
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Volume Total", format_number(total_volume))
    k2.metric("Gross Sales", format_money(gross_sales, currency))
    k3.metric("Gross Margin", format_money(gross_margin, currency), format_ratio(gross_margin / gross_sales if gross_sales else np.nan))
    k4.metric("EBITDA", format_money(ebitda, currency), format_ratio(ebitda / gross_sales if gross_sales else np.nan))
    k5.metric("Net Income", format_money(net_income, currency), format_ratio(net_income / gross_sales if gross_sales else np.nan))
    k6.metric("Net Inc. / Volume", format_per_volume(net_income / total_volume if total_volume else np.nan, currency))

    tabs = st.tabs(["📊 Trend", "⛽ İstasyon", "⚖️ Karşılaştırma", "📑 P&L Detay", "🧪 Veri Kontrol"])

    with tabs[0]:
        timeline = make_wide(aggregate_long(df, [period_col]), [period_col])
        if timeline.empty:
            st.info("Seçili filtrelerde veri yok.")
        else:
            metric = st.selectbox("Trend metriği", ["Gross Sales Total", "Gross Margin", "EBITDA", "Net Income", "Net Income-Working Capital Cost"], index=3)
            fig = px.line(timeline.sort_values(period_col), x=period_col, y=metric, markers=True, title=f"{metric} Trend")
            fig.update_layout(height=480)
            st.plotly_chart(fig, use_container_width=True)

    with tabs[1]:
        station_cols = [c for c in ["İstasyon", "Name", "City", "Territory", "Territory Manager", "Area Sales Manager", "Dealer/Acenta"] if c in df.columns]
        station_wide = make_wide(aggregate_long(df, station_cols), station_cols)
        if station_wide.empty:
            st.info("İstasyon verisi bulunamadı.")
        else:
            label = "Name" if "Name" in station_wide.columns else "İstasyon"
            rank_metric = st.selectbox("Sıralama metriği", ["Net Income", "EBITDA", "Gross Margin", "Net Income-Working Capital Cost"], index=0)
            top_bottom = pd.concat([
                station_wide.sort_values(rank_metric, ascending=False).head(10).assign(Group="Top 10"),
                station_wide.sort_values(rank_metric, ascending=True).head(10).assign(Group="Bottom 10"),
            ])
            fig = px.bar(top_bottom, y=label, x=rank_metric, color="Group", orientation="h", title="Top / Bottom 10")
            fig.update_layout(height=520)
            st.plotly_chart(fig, use_container_width=True)
            show_cols = [c for c in station_cols + SUMMARY_LINES + ["Gross Margin %", "EBITDA %", "Net Income %", "Net Income / Volume"] if c in station_wide.columns]
            st.dataframe(style_numeric_table(station_wide[show_cols]), use_container_width=True, height=520)
            st.download_button("İstasyon özet CSV indir", download_csv(station_wide[show_cols]), "station_summary.csv", "text/csv")

    with tabs[2]:
        dims = [c for c in ["City", "Territory", "Territory Manager", "Area Sales Manager", "Dealer/Acenta", "İstasyon", "Name"] if c in df.columns]
        if not dims:
            st.info("Karşılaştırma boyutu bulunamadı.")
        else:
            dim = st.selectbox("Karşılaştırma kırılımı", dims)
            comp = make_wide(aggregate_long(df, [dim]), [dim])
            if comp.empty:
                st.info("Veri yok.")
            else:
                metric = st.selectbox("Metrik", ["Volume Total", "Gross Sales Total", "Gross Margin", "EBITDA", "Net Income", "Net Income / Volume"], index=4)
                n = st.slider("Kayıt sayısı", 5, 100, 25)
                fig = px.bar(comp.sort_values(metric, ascending=False).head(n), x=metric, y=dim, orientation="h", title=f"{dim} bazında {metric}")
                fig.update_layout(height=620)
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(style_numeric_table(comp.sort_values(metric, ascending=False)), use_container_width=True, height=520)

    with tabs[3]:
        st.dataframe(style_numeric_table(stmt), use_container_width=True, height=680)
        st.download_button("P&L statement CSV indir", download_csv(stmt), "pnl_statement.csv", "text/csv")

    with tabs[4]:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Master satır", f"{len(master):,}")
        c2.metric("Filtre sonrası", f"{len(df):,}")
        c3.metric("İstasyon", f"{df['İstasyon'].nunique():,}" if "İstasyon" in df.columns else "-")
        c4.metric("P&L satırı", f"{df['P&L Line'].nunique():,}" if "P&L Line" in df.columns else "-")
        st.markdown("##### Kaynak dosya / P&L line özeti")
        source_summary = df.groupby(["Source Type", "Source File", "P&L Line"], dropna=False)["Value"].sum().reset_index()
        st.dataframe(source_summary, use_container_width=True, height=420)
        st.markdown("##### Ham master örneği")
        st.dataframe(df.head(1000), use_container_width=True, height=360)


# ------------------------------------------------------------
# Main app
# ------------------------------------------------------------

st.title("⛽ Franchise Station P&L")
st.caption("Admin çoklu kaynak dosyaları bir kez mapler ve master P&L raporu oluşturur. Kullanıcılar sadece güncel dashboardı görür.")

manifest = load_json(MANIFEST_FILE, {})
mapping_config = load_json(MAPPING_FILE, {"by_source_type": {}})

with st.sidebar:
    st.header("Giriş")
    view_mode = st.radio("Mod", ["Dashboard", "Admin Panel"], index=0)

if view_mode == "Admin Panel":
    password = st.sidebar.text_input("Admin şifresi", type="password")
    if password != ADMIN_PASSWORD:
        st.warning("Admin paneli için şifre gir.")
        st.stop()

    st.subheader("Admin Panel — Çoklu dosya upload & mapping")
    st.info("Önce her dosyada doğru başlık satırını seç, sonra kolonları P&L satırlarına map et. Mapping kaynak tipine göre kaydedilir; sonraki yüklemelerde otomatik gelir.")

    uploaded_files = st.file_uploader("Kaynak Excel/CSV dosyalarını yükle", type=["xlsx", "xlsm", "xls", "csv"], accept_multiple_files=True)

    if uploaded_files:
        normalized_parts: List[pd.DataFrame] = []
        dealer_parts: List[pd.DataFrame] = []
        audit_parts: List[pd.DataFrame] = []
        new_mapping_config = mapping_config.copy()
        new_mapping_config.setdefault("by_source_type", {})
        file_records = []

        for i, file in enumerate(uploaded_files):
            df, mapping, meta = mapping_ui_for_file(file, i, mapping_config)
            if df is None:
                continue
            pnl_part, dealer_part, audit_part = normalize_pnl_source(
                df=df,
                mapping=mapping,
                source_type=meta["source_type"],
                source_file=meta["file_name"],
                default_currency=meta["default_currency"],
                sign_mode=meta["sign_mode"],
            )
            if not pnl_part.empty:
                normalized_parts.append(pnl_part)
            if not dealer_part.empty:
                dealer_parts.append(dealer_part)
            if not audit_part.empty:
                audit_parts.append(audit_part)

            new_mapping_config.setdefault(meta["file_name"], {})
            new_mapping_config[meta["file_name"]] = {"sheet_name": meta.get("sheet_name"), "header_row": meta.get("header_row")}
            new_mapping_config["by_source_type"][meta["source_type"]] = mapping
            file_records.append({**meta, "mapped_rows": int(len(pnl_part)), "dealer_rows": int(len(dealer_part))})

        st.divider()
        st.markdown("### Mapping sonucu ön kontrol")
        if normalized_parts:
            preview = pd.concat(normalized_parts, ignore_index=True)
            st.success(f"Maplenen P&L satırı: {len(preview):,}")
            st.dataframe(preview.head(500), use_container_width=True, height=360)
        else:
            st.error("Henüz maplenen P&L satırı yok. ZSD50 için başlık satırını ve en az bir tutar/miktar kolonunu seçmelisin.")

        if audit_parts:
            st.warning("Aşağıdaki numerik kolonlar maplenmedi; önemliyse bir P&L satırına bağla.")
            st.dataframe(pd.concat(audit_parts, ignore_index=True), use_container_width=True, height=320)

        if st.button("✅ Master P&L raporunu oluştur / güncelle", type="primary"):
            if not normalized_parts:
                st.error("Master rapor oluşmadı. En az bir kaynak dosyada mapping yapılmalı.")
            else:
                master = pd.concat(normalized_parts, ignore_index=True)
                dealer_master = pd.concat(dealer_parts, ignore_index=True).drop_duplicates() if dealer_parts else pd.DataFrame()
                master = enrich_with_dealer_master(master, dealer_master)
                master = add_calculated_lines(master)
                master.to_pickle(MASTER_FILE)
                save_json(MAPPING_FILE, new_mapping_config)
                save_json(MANIFEST_FILE, {
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "rows": int(len(master)),
                    "files": file_records,
                })
                st.success(f"Master rapor güncellendi. Satır: {len(master):,}")
                st.dataframe(master.head(1000), use_container_width=True, height=420)
    else:
        st.info("Dosyaları yükleyince mapping ekranı açılacak.")

else:
    if not MASTER_FILE.exists():
        st.warning("Henüz admin tarafından oluşturulmuş master P&L raporu yok.")
        st.stop()
    master_df = pd.read_pickle(MASTER_FILE)
    if manifest:
        st.caption(f"Son güncelleme: {manifest.get('updated_at', '-')} | Master satır: {manifest.get('rows', '-')}")
    dashboard_ui(master_df)
