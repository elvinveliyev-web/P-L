from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st


# ============================================================
# FRANCHISE STATION P&L APP - ADMIN UPLOAD + USER DASHBOARD
# ============================================================
# Mantık:
# 1) Dosyaları sadece admin yükler.
# 2) Admin farklı kaynak dosyalarını yükler: ZSD50/ZSD50G, Dealer List,
#    FBL3N, Discount Premium, Rebate, ATS, Amortization, manuel P&L vb.
# 3) Uygulama bu dosyaları ortak uzun formata çevirir.
# 4) Hesaplanan P&L satırlarını üretir ve tek master raporu kaydeder.
# 5) Normal kullanıcı sadece son güncellenmiş dashboard/raporu görür.

st.set_page_config(
    page_title="Franchise Station P&L",
    page_icon="⛽",
    layout="wide",
    initial_sidebar_state="expanded",
)

DATA_DIR = Path("pnl_app_data")
UPLOAD_DIR = DATA_DIR / "uploaded_sources"
MASTER_FILE = DATA_DIR / "master_pnl_report.pkl"
MANIFEST_FILE = DATA_DIR / "manifest.json"
DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

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
SIGN_MODES = [
    "Dosyadaki işaretleri koru",
    "Tip bazlı otomatik işaret ver",
]

# ------------------------------------------------------------
# P&L metadata and formulas
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
    "Tangible_Total": {"type": "Amortization", "source": "Accounting Department Fuel Reports"},
    "Intangible_Total": {"type": "Amortization", "source": "Accounting Department Gas Reports"},
    "Working Capital Cost": {"type": "Expenses", "source": "Manual / Calculated"},
    # Calculated lines
    "Gross Margin": {"type": "Calculated Area", "source": "Calculated"},
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
    "EBITDA": {"type": "Calculated Area", "source": "Calculated"},
    "Net Income": {"type": "Calculated Area", "source": "Calculated"},
    "Net Income-Working Capital Cost": {"type": "Calculated Area", "source": "Calculated"},
    "Margin Share-Diesel-Old": {"type": "Calculated Area", "source": "Calculated / Manual"},
    "Margin Share-Diesel-New": {"type": "Calculated Area", "source": "Calculated / Manual"},
    "Margin Share-Gasoline-Old": {"type": "Calculated Area", "source": "Calculated / Manual"},
    "Margin Share-Gasoline-New": {"type": "Calculated Area", "source": "Calculated / Manual"},
}

CALCULATED_LINES = {
    line for line, meta in LINE_INFO.items() if meta.get("type") == "Calculated Area"
}

PNL_ORDER = [
    "Volume Total",
    "Fuel Volume",
    "Gas Volume",
    "Gross Sales Total",
    "Fuel Gross Sales",
    "Gas Gross Sales",
    "Discount Included in Invoice Total",
    "Discount Premium",
    "Rebate",
    "Additive",
    "ATS Commision Fee",
    "ATS Discount",
    "ATS Income",
    "ATS Disc given to Customers",
    "COGS Total",
    "Fuel COGS",
    "Gas COGS",
    "Gross Margin",
    "Fuel Variable Process Expenses All",
    "Fuel Variable Logistic Expenses",
    "Transport Income fuel only",
    "Autogas Variable Logistic Expenses",
    "Process & Logistic Variable Expenses",
    "Process & Logistic Variable Expenses-Level OP1",
    "TESİS/TERMINALS",
    "Terminal costs -Level OP2",
    "BAYİLİK SATIŞLARI/DEALERSHIP SALES",
    "ATS SATIŞLARI/VIS SALES",
    "KURUMSAL İLETİŞİM/CORPORATE COMMUNI",
    "PAZARLAMA/MARKETING",
    "SATIŞ DESTEK/SALES SUPPORT",
    "OTOMASYON/AUTOMATION",
    "MÜHENDİSLİK/ENGINEERING",
    "Direct Expenses From Related Departments-Level OP3",
    "Loyalty Card Expenses",
    "Card Cost All",
    "Cards Income",
    "Card Expenses/Incomes",
    "Rent",
    "Rent Income",
    "Rent Expenses/Incomes",
    "Engineering Expenses All",
    "Engineering Expenses",
    "MUHASEBE/ACCOUNTING",
    "İDARİ İŞLER/ADMINISTRATIVE",
    "İNSAN KAYNAKLARI/HR",
    "BİLGİ İŞLEM/IT",
    "GENEL YÖNETİM/GENERAL ADMIN",
    "OFİS/OFFICE",
    "İKMAL/SUPPLY",
    "SEÇ-G/HSSE",
    "HUKUK/LEGAL",
    "Indirect Expenses From Unrelated Departments",
    "Gain on sale of fixed assets All",
    "Insurance Income All",
    "Late Payment Charges All",
    "Price Difference All",
    "Market Commission Income",
    "Penalty Charge",
    "EMRA Fee All",
    "Incomes Total",
    "EBITDA",
    "Tangible_Total",
    "Intangible_Total",
    "Amortizations",
    "Net Income",
    "Working Capital Cost",
    "Net Income-Working Capital Cost",
    "Margin Share-Diesel-Old",
    "Margin Share-Diesel-New",
    "Margin Share-Gasoline-Old",
    "Margin Share-Gasoline-New",
]

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

INFO_ALIASES = {
    "Year_Month_Quarter": ["Year_Month_Quarter", "Year Month Quarter", "YearMonthQuarter"],
    "Year": ["Year", "Yıl", "Yil"],
    "Quarter": ["Quarter", "Çeyrek", "Ceyrek"],
    "Month": ["Month", "Ay"],
    "Date": ["Date", "Tarih", "Posting Date", "Document Date", "Fatura Tarihi"],
    "Contract Beginning": ["Contract Beginning", "Contract_Beginning"],
    "Contract Expiration": ["Contract Expiration", "Contract_Expiration"],
    "İstasyon": ["İstasyon", "Istasyon", "Station", "Station Code", "Station_Code", "Bayi Kodu", "Bayi"],
    "Name": ["Name", "Station Name", "Station_Name", "Bayi Adı", "Bayi Adi", "Dealer Name"],
    "District": ["District", "İlçe", "Ilce"],
    "City": ["City", "Şehir", "Sehir", "İl", "Il"],
    "Territory": ["Territory", "Region", "Bölge", "Bolge"],
    "Territory Manager": ["Territory Manager", "Territory_Manager", "Bölge Müdürü", "Bolge Muduru"],
    "Area Sales Manager": ["Area Sales Manager", "Area_Sales_Manager", "ASM", "Satış Temsilcisi", "Satis Temsilcisi"],
    "Dealer/Acenta": ["Dealer/Acenta", "Dealer_Acenta", "Dealer", "Acenta", "Bayi Tipi", "Dealer or Agency"],
    "Supply city for fuel": ["Supply city for fuel", "Supply_city_for_fuel", "Supply City", "İkmal Şehri", "Ikmal Sehri"],
}

EXTRA_LINE_ALIASES = {
    "volume": "Volume Total",
    "volume total": "Volume Total",
    "fuel volume": "Fuel Volume",
    "gas volume": "Gas Volume",
    "gross sales": "Gross Sales Total",
    "gross sales total": "Gross Sales Total",
    "fuel gross sales": "Fuel Gross Sales",
    "gas gross sales": "Gas Gross Sales",
    "cogs": "COGS Total",
    "cogs total": "COGS Total",
    "fuel cogs": "Fuel COGS",
    "gas cogs": "Gas COGS",
    "gross margin": "Gross Margin",
    "ebitda": "EBITDA",
    "net income": "Net Income",
    "net_income": "Net Income",
    "net income working capital cost": "Net Income-Working Capital Cost",
    "net income-working capital cost": "Net Income-Working Capital Cost",
    "working capital cost": "Working Capital Cost",
    "tangible total": "Tangible_Total",
    "intangible total": "Intangible_Total",
    "ats commission fee": "ATS Commision Fee",
    "ats commision fee": "ATS Commision Fee",
    "cards income": "Cards Income",
    "card income": "Cards Income",
    "rent expenses incomes": "Rent Expenses/Incomes",
    "card expenses incomes": "Card Expenses/Incomes",
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
    "sec-g": "SEÇ-G/HSSE",
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
    text = text.lower()
    text = text.replace("ı", "i")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def build_alias_map() -> Dict[str, str]:
    alias_map: Dict[str, str] = {}
    for canonical, aliases in INFO_ALIASES.items():
        alias_map[normalize_key(canonical)] = canonical
        for alias in aliases:
            alias_map[normalize_key(alias)] = canonical
    return alias_map


INFO_ALIAS_MAP = build_alias_map()


def build_line_alias_map() -> Dict[str, str]:
    alias_map: Dict[str, str] = {}
    for line in LINE_INFO:
        alias_map[normalize_key(line)] = line
        alias_map[normalize_key(line.replace("_", " "))] = line
        alias_map[normalize_key(line.replace("/", " "))] = line
        alias_map[normalize_key(line.replace("-", " "))] = line
    for alias, canonical in EXTRA_LINE_ALIASES.items():
        alias_map[normalize_key(alias)] = canonical
    return alias_map


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

    # Handle European format: 1.234.567,89
    euro_mask = s.str.contains(r"\.\d{3}", regex=True) & s.str.contains(",", regex=False)
    s = s.where(~euro_mask, s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    # Handle simple comma decimal
    s = s.where(euro_mask, s.str.replace(",", ".", regex=False))

    return pd.to_numeric(s, errors="coerce")


def first_existing_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    lookup = {normalize_key(c): c for c in df.columns}
    for candidate in candidates:
        key = normalize_key(candidate)
        if key in lookup:
            return lookup[key]
    return None


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result.columns = [resolve_info_col(c) for c in result.columns]
    result.columns = [str(c).strip() for c in result.columns]
    return result


def detect_currency_from_text(value: object, default_currency: str) -> str:
    text = str(value).upper()
    if "USD" in text or "$" in text:
        return "USD"
    if "TL" in text or "TRY" in text or "₺" in text:
        return "TL"
    return default_currency


def detect_product_from_text(value: object) -> str:
    text = normalize_key(value)
    if "gasoline" in text or "benzin" in text:
        return "Gasoline"
    if "diesel" in text or "motorin" in text or "fuel" in text:
        return "Fuel"
    if "lpg" in text or "autogas" in text or "gas" in text:
        return "Gas"
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
    result = df.copy()
    result["Value"] = coerce_numeric(result["Value"]).fillna(0.0)
    if sign_mode == "Tip bazlı otomatik işaret ver":
        result["Value"] = result.apply(
            lambda r: abs(float(r["Value"])) * sign_for_line(str(r["P&L Line"])),
            axis=1,
        )
    return result


def parse_period_columns(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()

    if "Date" in result.columns:
        result["Date"] = pd.to_datetime(result["Date"], errors="coerce", dayfirst=True)
    else:
        result["Date"] = pd.NaT

    if "Year_Month_Quarter" in result.columns:
        extracted = result["Year_Month_Quarter"].astype(str).str.extract(
            r"(?P<Year>\d{4})[-_/ ]*Q(?P<QuarterNo>\d{1})[-_/ ]*(?P<Month>\d{1,2})"
        )
        if "Year" not in result.columns:
            result["Year"] = pd.to_numeric(extracted["Year"], errors="coerce")
        else:
            result["Year"] = pd.to_numeric(result["Year"], errors="coerce").fillna(
                pd.to_numeric(extracted["Year"], errors="coerce")
            )
        if "Month" not in result.columns:
            result["Month"] = pd.to_numeric(extracted["Month"], errors="coerce")
        else:
            result["Month"] = pd.to_numeric(result["Month"], errors="coerce").fillna(
                pd.to_numeric(extracted["Month"], errors="coerce")
            )

    if "Year" in result.columns:
        result["Year"] = pd.to_numeric(result["Year"], errors="coerce")
    else:
        result["Year"] = result["Date"].dt.year

    if "Month" in result.columns:
        result["Month"] = pd.to_numeric(result["Month"], errors="coerce")
    else:
        result["Month"] = result["Date"].dt.month

    # If Date is missing but Year/Month exists, create first day of month.
    missing_date = result["Date"].isna()
    if missing_date.any():
        tmp_year = result["Year"].fillna(datetime.now().year).astype(int)
        tmp_month = result["Month"].fillna(1).astype(int)
        fallback_date = pd.to_datetime(
            {"year": tmp_year, "month": tmp_month, "day": 1},
            errors="coerce",
        )
        result.loc[missing_date, "Date"] = fallback_date.loc[missing_date]

    if "Quarter" not in result.columns:
        result["Quarter"] = "Q" + result["Date"].dt.quarter.astype("Int64").astype(str)
    else:
        result["Quarter"] = result["Quarter"].astype(str).str.replace(".0", "", regex=False)
        result["Quarter"] = np.where(
            result["Quarter"].str.upper().str.startswith("Q"),
            result["Quarter"],
            "Q" + result["Quarter"],
        )

    result["Year"] = result["Date"].dt.year.astype("Int64")
    result["Month"] = result["Date"].dt.month.astype("Int64")
    result["Month_Label"] = result["Date"].dt.strftime("%Y-%m")
    result["Quarter_Label"] = result["Date"].dt.year.astype("Int64").astype(str) + "-Q" + result["Date"].dt.quarter.astype("Int64").astype(str)
    result["Year_Label"] = result["Date"].dt.year.astype("Int64").astype(str)
    iso = result["Date"].dt.isocalendar()
    result["Week_Label"] = iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)
    result["Day_Label"] = result["Date"].dt.strftime("%Y-%m-%d")
    result["Year_Month_Quarter"] = result["Year"].astype(str) + "-Q" + result["Date"].dt.quarter.astype(str) + "-" + result["Month"].astype(str)
    return result


def selected_period_column(df: pd.DataFrame, period_level: str) -> Tuple[pd.DataFrame, str]:
    result = df.copy()
    col = {
        "Senelik": "Year_Label",
        "Çeyreklik": "Quarter_Label",
        "Aylık": "Month_Label",
        "Haftalık": "Week_Label",
        "Günlük": "Day_Label",
    }.get(period_level, "Month_Label")
    result["Selected_Period"] = result[col].astype(str)
    return result, "Selected_Period"


def blank_to_na(series: pd.Series) -> pd.Series:
    return series.replace(["", "nan", "NaN", "None", "<NA>", "NaT"], np.nan)


def safe_unique(df: pd.DataFrame, col: str) -> List[str]:
    if col not in df.columns:
        return []
    values = blank_to_na(df[col].astype(str).str.strip()).dropna().unique().tolist()
    return sorted(values)


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


# ------------------------------------------------------------
# File reading
# ------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_excel_sheets(file_bytes: bytes) -> List[str]:
    return pd.ExcelFile(BytesIO(file_bytes)).sheet_names


@st.cache_data(show_spinner=False)
def read_excel_cached(file_bytes: bytes, sheet_name: str) -> pd.DataFrame:
    return pd.read_excel(BytesIO(file_bytes), sheet_name=sheet_name)


@st.cache_data(show_spinner=False)
def read_csv_cached(file_bytes: bytes) -> pd.DataFrame:
    encodings = ["utf-8-sig", "utf-8", "cp1254", "latin1"]
    last_error: Optional[Exception] = None
    for enc in encodings:
        try:
            return pd.read_csv(BytesIO(file_bytes), encoding=enc)
        except Exception as exc:
            last_error = exc
    raise last_error or ValueError("CSV okunamadı")


def read_uploaded_dataframe(file, sheet_name: Optional[str]) -> pd.DataFrame:
    name = file.name.lower()
    file_bytes = file.getvalue()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        return read_excel_cached(file_bytes, sheet_name or get_excel_sheets(file_bytes)[0])
    if name.endswith(".csv"):
        return read_csv_cached(file_bytes)
    raise ValueError("Sadece CSV veya Excel dosyası destekleniyor.")


# ------------------------------------------------------------
# Normalization from many source files into one P&L long table
# ------------------------------------------------------------

def make_empty_long() -> pd.DataFrame:
    cols = INFO_COLS + [
        "Currency",
        "Product",
        "P&L Line",
        "P&L Type",
        "Value",
        "Source Type",
        "Source File",
        "Is Calculated",
    ]
    return pd.DataFrame(columns=cols)


def normalize_dealer_master(raw_df: pd.DataFrame) -> pd.DataFrame:
    df = standardize_columns(raw_df)
    keep = [c for c in INFO_COLS if c in df.columns and c not in ["Date", "Year", "Quarter", "Month", "Year_Month_Quarter"]]
    if "İstasyon" not in keep and "Name" not in keep:
        return pd.DataFrame()
    dealer = df[keep].copy()
    for col in dealer.columns:
        dealer[col] = dealer[col].astype(str).str.strip()
    dealer = dealer.drop_duplicates(subset=[c for c in ["İstasyon", "Name"] if c in dealer.columns])
    return dealer


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
    raw_df: pd.DataFrame,
    source_type: str,
    source_file: str,
    default_currency: str,
    sign_mode: str,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return normalized pnl_long and optional dealer_master."""
    df = standardize_columns(raw_df)
    if df.empty:
        return make_empty_long(), pd.DataFrame()

    if source_type == "Dealer Master / Akpet Dealer List":
        return make_empty_long(), normalize_dealer_master(df)

    df = parse_period_columns(df)

    # Common currency/product fields
    currency_col = first_existing_column(df, ["Currency", "Currency_Type", "Para Birimi", "PB"])
    attr2_col = first_existing_column(df, ["Attribute.2", "Attribute_2", "Product_Currency", "Product Currency", "Ürün Para Birimi"])
    product_col = first_existing_column(df, ["Product", "Ürün", "Urun"])

    if currency_col:
        df["Currency"] = df[currency_col].astype(str).apply(lambda x: detect_currency_from_text(x, default_currency))
    elif attr2_col:
        df["Currency"] = df[attr2_col].astype(str).apply(lambda x: detect_currency_from_text(x, default_currency))
    else:
        df["Currency"] = default_currency

    if product_col:
        df["Product"] = df[product_col].astype(str).apply(detect_product_from_text)
    elif attr2_col:
        df["Product"] = df[attr2_col].astype(str).apply(detect_product_from_text)
    else:
        df["Product"] = "Total"

    line_col = first_existing_column(df, ["P&L Line", "PNL Line", "Attribute.1", "Attribute_1", "Heading", "Kalem", "Metric"])
    value_col = first_existing_column(df, ["Value", "Amount", "Tutar", "Deger", "Değer", "Balance", "Bakiye"])

    id_cols = [c for c in INFO_COLS + ["Currency", "Product"] if c in df.columns]

    normalized = make_empty_long()

    # Case 1: already long format
    if line_col and value_col:
        tmp = df[id_cols + [line_col, value_col]].copy()
        tmp = tmp.rename(columns={line_col: "Raw Line", value_col: "Value"})
        tmp["P&L Line"] = tmp["Raw Line"].apply(lambda x: resolve_line_name(x) or str(x).strip())
        normalized = tmp.drop(columns=["Raw Line"])

    # Case 2: wide format where columns are P&L lines
    if normalized.empty:
        wide_line_cols = []
        for c in df.columns:
            if c in id_cols:
                continue
            if resolve_line_name(c):
                wide_line_cols.append(c)
        if wide_line_cols:
            tmp = df.melt(
                id_vars=[c for c in id_cols if c in df.columns],
                value_vars=wide_line_cols,
                var_name="Raw Line",
                value_name="Value",
            )
            tmp["P&L Line"] = tmp["Raw Line"].apply(lambda x: resolve_line_name(x) or str(x).strip())
            normalized = tmp.drop(columns=["Raw Line"])

    # Case 3: accounting rows with account / cost center / description + amount
    if normalized.empty:
        amount_col = value_col or first_existing_column(
            df,
            ["Local Currency Amount", "Amount in local currency", "Debit/Credit", "Debit", "Credit", "LC Amount"],
        )
        if amount_col:
            tmp = df[id_cols + [amount_col]].copy()
            tmp["P&L Line"] = df.apply(map_account_or_department, axis=1)
            tmp = tmp.rename(columns={amount_col: "Value"})
            tmp = tmp[tmp["P&L Line"].notna()]
            normalized = tmp

    if normalized.empty:
        return make_empty_long(), pd.DataFrame()

    for col in INFO_COLS:
        if col not in normalized.columns:
            normalized[col] = np.nan

    normalized["Currency"] = normalized.get("Currency", default_currency).fillna(default_currency).astype(str)
    normalized["Product"] = normalized.get("Product", "Total").fillna("Total").astype(str)
    normalized["P&L Line"] = normalized["P&L Line"].astype(str).str.strip()
    normalized = normalized[normalized["P&L Line"].ne("")]
    normalized["P&L Type"] = normalized["P&L Line"].apply(line_type)
    normalized["Source Type"] = source_type
    normalized["Source File"] = source_file
    normalized["Is Calculated"] = False
    normalized = apply_sign_policy(normalized, sign_mode)

    normalized = normalized[INFO_COLS + [
        "Currency",
        "Product",
        "P&L Line",
        "P&L Type",
        "Value",
        "Source Type",
        "Source File",
        "Is Calculated",
    ]]

    return normalized, pd.DataFrame()


def enrich_with_dealer_master(pnl: pd.DataFrame, dealer_master: pd.DataFrame) -> pd.DataFrame:
    if pnl.empty or dealer_master.empty:
        return pnl

    key = "İstasyon" if "İstasyon" in dealer_master.columns and "İstasyon" in pnl.columns else None
    if key is None and "Name" in dealer_master.columns and "Name" in pnl.columns:
        key = "Name"
    if key is None:
        return pnl

    enrich_cols = [
        c for c in [
            "Contract Beginning",
            "Contract Expiration",
            "Name",
            "District",
            "City",
            "Territory",
            "Territory Manager",
            "Area Sales Manager",
            "Dealer/Acenta",
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
                main = blank_to_na(result[col].astype(str).str.strip())
                result[col] = main.fillna(result[dealer_col])
            result = result.drop(columns=[dealer_col])

    return result


# ------------------------------------------------------------
# Calculations
# ------------------------------------------------------------

def add_calculated_rows(base: pd.DataFrame) -> pd.DataFrame:
    if base.empty:
        return base

    base = base.copy()
    group_cols = [
        c for c in INFO_COLS + ["Currency", "Product"]
        if c in base.columns and c not in ["Date"]
    ]

    # Calculations should be per period/station/currency/product.
    pivot = base.groupby(group_cols + ["P&L Line"], dropna=False)["Value"].sum().unstack("P&L Line", fill_value=0.0)

    def val(line: str) -> pd.Series:
        if line in pivot.columns:
            return pivot[line].astype(float)
        return pd.Series(0.0, index=pivot.index)

    calc: Dict[str, pd.Series] = {}

    calc["Gross Margin"] = (
        val("Gross Sales Total")
        + val("Discount Included in Invoice Total")
        + val("Discount Premium")
        + val("Rebate")
        + val("Additive")
        + val("ATS Commision Fee")
        + val("ATS Discount")
        + val("ATS Income")
        + val("ATS Disc given to Customers")
        + val("COGS Total")
    )

    calc["Card Expenses/Incomes"] = (
        val("Loyalty Card Expenses") + val("Card Cost All") + val("Cards Income")
    )
    calc["Rent Expenses/Incomes"] = val("Rent") + val("Rent Income")
    calc["Engineering Expenses"] = val("Engineering Expenses All")
    calc["Indirect Expenses From Unrelated Departments"] = (
        val("MUHASEBE/ACCOUNTING")
        + val("İDARİ İŞLER/ADMINISTRATIVE")
        + val("İNSAN KAYNAKLARI/HR")
        + val("BİLGİ İŞLEM/IT")
        + val("GENEL YÖNETİM/GENERAL ADMIN")
        + val("OFİS/OFFICE")
        + val("İKMAL/SUPPLY")
        + val("TESİS/TERMINALS")
        + val("SEÇ-G/HSSE")
        + val("HUKUK/LEGAL")
    )
    calc["Incomes Total"] = (
        val("Gain on sale of fixed assets All")
        + val("Insurance Income All")
        + val("Late Payment Charges All")
        + val("Price Difference All")
        + val("Market Commission Income")
        + val("Penalty Charge")
        + val("EMRA Fee All")
        + val("Transport Income fuel only")
    )
    calc["Amortizations"] = val("Tangible_Total") + val("Intangible_Total")
    calc["Process & Logistic Variable Expenses"] = (
        val("Fuel Variable Process Expenses All")
        + val("Fuel Variable Logistic Expenses")
        + val("Transport Income fuel only")
        + val("Autogas Variable Logistic Expenses")
    )
    calc["Process & Logistic Variable Expenses-Level OP1"] = (
        calc["Gross Margin"] + calc["Process & Logistic Variable Expenses"]
    )
    calc["Terminal costs -Level OP2"] = (
        calc["Process & Logistic Variable Expenses-Level OP1"] + val("TESİS/TERMINALS")
    )
    calc["Direct Expenses From Related Departments-Level OP3"] = (
        val("BAYİLİK SATIŞLARI/DEALERSHIP SALES")
        + val("ATS SATIŞLARI/VIS SALES")
        + val("KURUMSAL İLETİŞİM/CORPORATE COMMUNI")
        + val("PAZARLAMA/MARKETING")
        + val("SATIŞ DESTEK/SALES SUPPORT")
        + val("OTOMASYON/AUTOMATION")
        + val("MÜHENDİSLİK/ENGINEERING")
    )
    calc["EBITDA"] = (
        calc["Terminal costs -Level OP2"]
        + calc["Direct Expenses From Related Departments-Level OP3"]
        + calc["Card Expenses/Incomes"]
        + calc["Rent Expenses/Incomes"]
        + calc["Engineering Expenses"]
        + calc["Indirect Expenses From Unrelated Departments"]
        + calc["Incomes Total"]
    )
    calc["Net Income"] = calc["EBITDA"] + calc["Amortizations"]
    calc["Net Income-Working Capital Cost"] = calc["Net Income"] + val("Working Capital Cost")

    calc_df = pd.DataFrame(calc).reset_index()
    calc_long = calc_df.melt(
        id_vars=group_cols,
        value_vars=list(calc.keys()),
        var_name="P&L Line",
        value_name="Value",
    )
    calc_long["P&L Type"] = "Calculated Area"
    calc_long["Source Type"] = "Calculated"
    calc_long["Source File"] = "System Formula"
    calc_long["Is Calculated"] = True
    calc_long["Date"] = pd.to_datetime(calc_long.get("Date", pd.NaT), errors="coerce") if "Date" in calc_long.columns else pd.NaT

    for col in INFO_COLS:
        if col not in calc_long.columns:
            calc_long[col] = np.nan

    calc_long = calc_long[INFO_COLS + [
        "Currency",
        "Product",
        "P&L Line",
        "P&L Type",
        "Value",
        "Source Type",
        "Source File",
        "Is Calculated",
    ]]

    result = pd.concat([base, calc_long], ignore_index=True)
    result = parse_period_columns(result)
    return result


def build_master_report(
    uploaded_files: List,
    file_options: Dict[str, Dict[str, str]],
    replace_calculated: bool,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pnl_parts: List[pd.DataFrame] = []
    dealer_parts: List[pd.DataFrame] = []
    audit_rows: List[Dict[str, object]] = []

    for idx, file in enumerate(uploaded_files):
        opts = file_options[file.name]
        df = read_uploaded_dataframe(file, opts.get("sheet_name"))
        pnl, dealer = normalize_pnl_source(
            raw_df=df,
            source_type=opts["source_type"],
            source_file=file.name,
            default_currency=opts["currency"],
            sign_mode=opts["sign_mode"],
        )

        if not pnl.empty:
            pnl_parts.append(pnl)
        if not dealer.empty:
            dealer_parts.append(dealer)

        audit_rows.append(
            {
                "File": file.name,
                "Source Type": opts["source_type"],
                "Rows In File": len(df),
                "Normalized P&L Rows": len(pnl),
                "Dealer Rows": len(dealer),
                "Sheet": opts.get("sheet_name") or "CSV",
                "Default Currency": opts["currency"],
                "Sign Mode": opts["sign_mode"],
            }
        )

    pnl_all = pd.concat(pnl_parts, ignore_index=True) if pnl_parts else make_empty_long()
    dealer_all = pd.concat(dealer_parts, ignore_index=True) if dealer_parts else pd.DataFrame()
    if not dealer_all.empty:
        pnl_all = enrich_with_dealer_master(pnl_all, dealer_all)

    pnl_all = parse_period_columns(pnl_all)
    if replace_calculated:
        pnl_base = pnl_all[~pnl_all["P&L Line"].isin(CALCULATED_LINES)].copy()
    else:
        pnl_base = pnl_all.copy()

    master = add_calculated_rows(pnl_base)
    audit = pd.DataFrame(audit_rows)
    unmapped = (
        master[master["P&L Type"].eq("Unmapped")]
        .groupby(["P&L Line", "Source Type", "Source File"], dropna=False)["Value"]
        .agg(["count", "sum"])
        .reset_index()
    ) if not master.empty else pd.DataFrame()

    return master, audit, unmapped


def save_master_report(master: pd.DataFrame, audit: pd.DataFrame) -> None:
    master.to_pickle(MASTER_FILE)
    manifest = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rows": int(len(master)),
        "stations": int(master["İstasyon"].nunique(dropna=True)) if "İstasyon" in master.columns else 0,
        "audit": audit.to_dict(orient="records") if not audit.empty else [],
    }
    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def load_master_report() -> pd.DataFrame:
    if MASTER_FILE.exists():
        return pd.read_pickle(MASTER_FILE)
    return pd.DataFrame()


def load_manifest() -> Dict[str, object]:
    if MANIFEST_FILE.exists():
        try:
            return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def line_dictionary() -> pd.DataFrame:
    rows = []
    order_map = {line: i + 1 for i, line in enumerate(PNL_ORDER)}
    for line, meta in LINE_INFO.items():
        rows.append(
            {
                "Order": order_map.get(line, 9999),
                "P&L Line": line,
                "Type": meta.get("type", ""),
                "Default Source": meta.get("source", ""),
                "Is Calculated": line in CALCULATED_LINES,
            }
        )
    return pd.DataFrame(rows).sort_values(["Order", "P&L Line"])


# ------------------------------------------------------------
# Reporting functions
# ------------------------------------------------------------

def aggregate_long(df: pd.DataFrame, group_cols: List[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    group_cols = [c for c in group_cols if c in df.columns]
    return df.groupby(group_cols + ["P&L Line"], dropna=False, as_index=False)["Value"].sum()


def make_wide(df: pd.DataFrame, index_cols: List[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    index_cols = [c for c in index_cols if c in df.columns]
    wide = df.pivot_table(index=index_cols, columns="P&L Line", values="Value", aggfunc="sum", fill_value=0).reset_index()
    wide.columns.name = None
    for line in SUMMARY_LINES:
        if line not in wide.columns:
            wide[line] = 0.0
    wide["Gross Margin %"] = np.where(wide["Gross Sales Total"] != 0, wide["Gross Margin"] / wide["Gross Sales Total"], np.nan)
    wide["EBITDA %"] = np.where(wide["Gross Sales Total"] != 0, wide["EBITDA"] / wide["Gross Sales Total"], np.nan)
    wide["Net Income %"] = np.where(wide["Gross Sales Total"] != 0, wide["Net Income"] / wide["Gross Sales Total"], np.nan)
    wide["Net Income / Volume"] = np.where(wide["Volume Total"] != 0, wide["Net Income"] / wide["Volume Total"], np.nan)
    wide["Gross Margin / Volume"] = np.where(wide["Volume Total"] != 0, wide["Gross Margin"] / wide["Volume Total"], np.nan)
    return wide


def pnl_statement(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Order", "P&L Line", "P&L Type", "Value"])
    order_map = {line: i + 1 for i, line in enumerate(PNL_ORDER)}
    stmt = df.groupby(["P&L Line", "P&L Type"], dropna=False, as_index=False)["Value"].sum()
    stmt["Order"] = stmt["P&L Line"].map(order_map).fillna(9999).astype(int)
    return stmt.sort_values(["Order", "P&L Line"])[["Order", "P&L Line", "P&L Type", "Value"]]


def get_line_value(stmt: pd.DataFrame, line: str) -> float:
    if stmt.empty:
        return 0.0
    return float(stmt.loc[stmt["P&L Line"].eq(line), "Value"].sum())


def style_numeric_table(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    money_cols = [c for c in df.columns if c in SUMMARY_LINES or c in ["Gross Margin", "EBITDA", "Net Income"]]
    pct_cols = [c for c in df.columns if "%" in c]
    per_volume_cols = [c for c in df.columns if "/ Volume" in c]
    fmt = {"Volume Total": "{:,.0f}"}
    fmt.update({c: "{:,.0f}" for c in money_cols})
    fmt.update({c: "{:.2%}" for c in pct_cols})
    fmt.update({c: "{:,.4f}" for c in per_volume_cols})
    return df.style.format(fmt)


def download_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


# ------------------------------------------------------------
# Admin UI
# ------------------------------------------------------------

def admin_login_ui() -> bool:
    st.sidebar.divider()
    st.sidebar.subheader("Admin")
    if st.session_state.get("is_admin"):
        st.sidebar.success("Admin girişi aktif")
        if st.sidebar.button("Admin çıkış"):
            st.session_state["is_admin"] = False
            st.rerun()
        return True

    password = st.sidebar.text_input("Admin şifresi", type="password")
    if st.sidebar.button("Admin girişi"):
        if password == ADMIN_PASSWORD:
            st.session_state["is_admin"] = True
            st.rerun()
        else:
            st.sidebar.error("Şifre hatalı")
    return False


def render_admin_panel() -> None:
    st.header("🔐 Admin Paneli")
    st.caption("Bu bölüm sadece admin içindir. Kullanıcılar upload alanını görmez; sadece son güncellenmiş dashboardı görür.")

    current_manifest = load_manifest()
    if current_manifest:
        st.success(
            f"Mevcut master rapor: {current_manifest.get('updated_at', '-')} | "
            f"Satır: {current_manifest.get('rows', 0):,} | "
            f"İstasyon: {current_manifest.get('stations', 0):,}"
        )

    with st.expander("P&L hesaplama sözlüğü / kaynak yapısı", expanded=False):
        st.dataframe(line_dictionary(), use_container_width=True, height=420)

    replace_calculated = st.checkbox(
        "Hesaplanan P&L satırlarını sistem yeniden hesaplasın",
        value=True,
        help="Önerilen kullanım: Açık. Böylece Gross Margin, EBITDA, Net Income gibi satırlar kaynak dosyalardan değil formüllerden üretilir.",
    )

    uploaded_files = st.file_uploader(
        "Kaynak dosyaları yükle: Sales, Dealer List, FBL3N, Discount Premium, Rebate, ATS, Amortization, manuel dosyalar",
        type=["xlsx", "xlsm", "xls", "csv"],
        accept_multiple_files=True,
    )

    file_options: Dict[str, Dict[str, str]] = {}

    if uploaded_files:
        st.subheader("Dosya eşleştirme")
        for i, file in enumerate(uploaded_files):
            with st.expander(f"{i + 1}. {file.name}", expanded=i == 0):
                file_bytes = file.getvalue()
                sheet_name: Optional[str] = None
                if file.name.lower().endswith((".xlsx", ".xlsm", ".xls")):
                    try:
                        sheets = get_excel_sheets(file_bytes)
                        sheet_name = st.selectbox("Excel sayfası", sheets, key=f"sheet_{file.name}_{i}")
                    except Exception as exc:
                        st.error(f"Excel sayfaları okunamadı: {exc}")

                source_type = st.selectbox("Kaynak tipi", SOURCE_TYPES, key=f"source_{file.name}_{i}")
                currency = st.selectbox("Varsayılan para birimi", CURRENCY_OPTIONS, key=f"currency_{file.name}_{i}")
                sign_mode = st.selectbox(
                    "İşaret politikası",
                    SIGN_MODES,
                    key=f"sign_{file.name}_{i}",
                    help="SAP/FBL3N tutarları zaten eksi-artı geliyorsa 'Dosyadaki işaretleri koru'. Tüm tutarlar pozitif geliyorsa tip bazlı otomatik işaret ver.",
                )

                try:
                    preview = read_uploaded_dataframe(file, sheet_name)
                    st.write(f"Satır: {len(preview):,} | Kolon: {len(preview.columns):,}")
                    st.dataframe(preview.head(20), use_container_width=True, height=220)
                except Exception as exc:
                    st.error(f"Önizleme okunamadı: {exc}")

                file_options[file.name] = {
                    "sheet_name": sheet_name or "",
                    "source_type": source_type,
                    "currency": currency,
                    "sign_mode": sign_mode,
                }

        if st.button("✅ Master P&L raporunu oluştur / güncelle", type="primary"):
            with st.spinner("Kaynak dosyalar normalize ediliyor, hesaplamalar yapılıyor ve master rapor kaydediliyor..."):
                try:
                    master, audit, unmapped = build_master_report(uploaded_files, file_options, replace_calculated)
                    if master.empty:
                        st.error("Master rapor oluşmadı. Dosyalarda P&L line + Value veya tanınan wide kolonlar bulunamadı.")
                    else:
                        save_master_report(master, audit)
                        st.success("Master P&L raporu güncellendi. Artık tüm kullanıcılar yeni dashboardı görebilir.")
                        st.subheader("Yükleme özeti")
                        st.dataframe(audit, use_container_width=True)
                        if not unmapped.empty:
                            st.warning("Bazı satırlar P&L kalemine maplenemedi. Aşağıdaki tabloyu kontrol et.")
                            st.dataframe(unmapped, use_container_width=True, height=300)
                        st.download_button(
                            "Master normalize raporu CSV indir",
                            data=download_csv(master),
                            file_name="master_pnl_report.csv",
                            mime="text/csv",
                        )
                except Exception as exc:
                    st.exception(exc)

    st.divider()
    danger_col, _ = st.columns([1, 3])
    with danger_col:
        if st.button("Mevcut master raporu sil", type="secondary"):
            if MASTER_FILE.exists():
                MASTER_FILE.unlink()
            if MANIFEST_FILE.exists():
                MANIFEST_FILE.unlink()
            st.warning("Master rapor silindi.")
            st.rerun()


# ------------------------------------------------------------
# Dashboard UI
# ------------------------------------------------------------

def render_dashboard(master: pd.DataFrame) -> None:
    manifest = load_manifest()
    st.title("⛽ Franchise Station P&L Dashboard")
    if manifest:
        st.caption(
            f"Son güncelleme: {manifest.get('updated_at', '-')} | "
            f"Master satır: {manifest.get('rows', 0):,} | "
            f"İstasyon: {manifest.get('stations', 0):,}"
        )
    else:
        st.caption("Son güncelleme bilgisi bulunamadı.")

    if master.empty:
        st.info("Henüz yayınlanmış master P&L raporu yok. Admin panelinden kaynak dosyalar yüklenip master rapor oluşturulmalı.")
        return

    master = parse_period_columns(master)

    st.sidebar.header("Filtreler")
    currency_values = safe_unique(master, "Currency") or CURRENCY_OPTIONS
    currency = st.sidebar.radio("Para Birimi", currency_values, horizontal=True)

    product_values = safe_unique(master, "Product") or ["Total"]
    default_products = ["Total"] if "Total" in product_values else product_values[:1]
    products = st.sidebar.multiselect("Ürün", product_values, default=default_products)

    period_level = st.sidebar.selectbox("Dönem", PERIOD_LEVELS, index=2)
    master, period_col = selected_period_column(master, period_level)
    period_values = safe_unique(master, period_col)
    selected_periods = st.sidebar.multiselect("Dönem seçimi", period_values, default=period_values)

    filtered = master.copy()
    filtered = filtered[filtered["Currency"].astype(str).eq(currency)]
    if products:
        filtered = filtered[filtered["Product"].astype(str).isin(products)]
    if selected_periods:
        filtered = filtered[filtered[period_col].astype(str).isin(selected_periods)]

    for col, label in DASHBOARD_FILTERS:
        vals = safe_unique(filtered, col)
        if vals:
            selected = st.sidebar.multiselect(label, vals)
            if selected:
                filtered = filtered[filtered[col].astype(str).isin(selected)]

    tabs = st.tabs(["📊 Dashboard", "⛽ İstasyon", "⚖️ Karşılaştırma", "📑 P&L Statement", "🧪 Veri Kontrol"])

    stmt = pnl_statement(filtered)
    volume = get_line_value(stmt, "Volume Total")
    gross_sales = get_line_value(stmt, "Gross Sales Total")
    gross_margin = get_line_value(stmt, "Gross Margin")
    op1 = get_line_value(stmt, "Process & Logistic Variable Expenses-Level OP1")
    op2 = get_line_value(stmt, "Terminal costs -Level OP2")
    ebitda = get_line_value(stmt, "EBITDA")
    net_income = get_line_value(stmt, "Net Income")
    net_income_wcc = get_line_value(stmt, "Net Income-Working Capital Cost")

    gross_margin_pct = gross_margin / gross_sales if gross_sales else np.nan
    ebitda_pct = ebitda / gross_sales if gross_sales else np.nan
    net_income_pct = net_income / gross_sales if gross_sales else np.nan
    net_income_per_volume = net_income / volume if volume else np.nan

    with tabs[0]:
        st.subheader("Genel Özet")
        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("Volume", format_number(volume))
        k2.metric("Gross Sales", format_money(gross_sales, currency))
        k3.metric("Gross Margin", format_money(gross_margin, currency), format_ratio(gross_margin_pct))
        k4.metric("EBITDA", format_money(ebitda, currency), format_ratio(ebitda_pct))
        k5.metric("Net Income", format_money(net_income, currency), format_ratio(net_income_pct))
        k6.metric("Net Income / Volume", format_per_volume(net_income_per_volume, currency))

        m1, m2, m3 = st.columns(3)
        m1.metric("OP1", format_money(op1, currency))
        m2.metric("OP2", format_money(op2, currency))
        m3.metric("Net Income - WCC", format_money(net_income_wcc, currency))

        st.divider()
        c1, c2 = st.columns([1.2, 1])

        with c1:
            st.markdown("#### Dönemsel Trend")
            timeline = make_wide(aggregate_long(filtered, [period_col]), [period_col])
            if not timeline.empty:
                metric = st.selectbox(
                    "Trend metriği",
                    ["Gross Sales Total", "Gross Margin", "EBITDA", "Net Income", "Net Income-Working Capital Cost"],
                    index=3,
                )
                fig = px.line(timeline.sort_values(period_col), x=period_col, y=metric, markers=True)
                fig.update_layout(height=430, xaxis_title="Dönem", yaxis_title=currency)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Trend verisi yok.")

        with c2:
            st.markdown("#### Top / Bottom İstasyon")
            station_cols = [c for c in ["İstasyon", "Name", "City", "Territory", "Territory Manager", "Area Sales Manager", "Dealer/Acenta"] if c in filtered.columns]
            station_wide = make_wide(aggregate_long(filtered, station_cols), station_cols)
            if not station_wide.empty:
                rank_metric = st.selectbox("Sıralama metriği", ["Net Income", "EBITDA", "Gross Margin", "Net Income-Working Capital Cost"], index=0)
                label = "Name" if "Name" in station_wide.columns else "İstasyon"
                chart = pd.concat(
                    [
                        station_wide.sort_values(rank_metric, ascending=False).head(10).assign(Group="Top 10"),
                        station_wide.sort_values(rank_metric, ascending=True).head(10).assign(Group="Bottom 10"),
                    ]
                )
                fig = px.bar(chart, y=label, x=rank_metric, color="Group", orientation="h")
                fig.update_layout(height=430, yaxis_title="", xaxis_title=currency)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("İstasyon verisi yok.")

        st.markdown("#### İstasyon Özet Tablosu")
        if not station_wide.empty:
            show_cols = [c for c in station_cols + SUMMARY_LINES + ["Gross Margin %", "EBITDA %", "Net Income %", "Net Income / Volume"] if c in station_wide.columns]
            st.dataframe(style_numeric_table(station_wide[show_cols]), use_container_width=True, height=520)
            st.download_button("İstasyon özet CSV indir", download_csv(station_wide[show_cols]), "station_summary.csv", "text/csv")

    with tabs[1]:
        st.subheader("İstasyon Bazlı Analiz")
        stations = safe_unique(filtered, "İstasyon")
        if not stations:
            st.info("Seçili filtrelerde istasyon yok.")
        else:
            selected_station = st.selectbox("İstasyon seç", stations)
            station_df = filtered[filtered["İstasyon"].astype(str).eq(selected_station)]
            name = station_df["Name"].dropna().astype(str).iloc[0] if "Name" in station_df.columns and not station_df["Name"].dropna().empty else selected_station
            st.markdown(f"### {selected_station} - {name}")
            station_stmt = pnl_statement(station_df)

            s1, s2 = st.columns([1, 1])
            with s1:
                st.dataframe(station_stmt, use_container_width=True, height=650)
            with s2:
                station_timeline = make_wide(aggregate_long(station_df, [period_col]), [period_col])
                if not station_timeline.empty:
                    fig = px.line(
                        station_timeline.sort_values(period_col),
                        x=period_col,
                        y=["Gross Margin", "EBITDA", "Net Income"],
                        markers=True,
                    )
                    fig.update_layout(height=430, xaxis_title="Dönem", yaxis_title=currency)
                    st.plotly_chart(fig, use_container_width=True)

                    fig2 = px.bar(station_timeline.sort_values(period_col), x=period_col, y="Volume Total")
                    fig2.update_layout(height=320, xaxis_title="Dönem", yaxis_title="Volume")
                    st.plotly_chart(fig2, use_container_width=True)

    with tabs[2]:
        st.subheader("Karşılaştırma")
        compare_options = [c for c in ["İstasyon", "Name", "City", "Territory", "Territory Manager", "Area Sales Manager", "Dealer/Acenta"] if c in filtered.columns]
        if not compare_options:
            st.info("Karşılaştırma için kolon yok.")
        else:
            dim = st.selectbox("Kırılım", compare_options)
            comp = make_wide(aggregate_long(filtered, [dim]), [dim])
            if comp.empty:
                st.info("Karşılaştırma verisi yok.")
            else:
                metric = st.selectbox(
                    "Metrik",
                    ["Volume Total", "Gross Sales Total", "Gross Margin", "Gross Margin %", "EBITDA", "EBITDA %", "Net Income", "Net Income %", "Net Income / Volume"],
                    index=6,
                )
                top_n = st.slider("Gösterilecek kayıt", 5, 100, 25)
                chart = comp.sort_values(metric, ascending=False).head(top_n)
                fig = px.bar(chart, y=dim, x=metric, orientation="h")
                fig.update_layout(height=650, yaxis_title="", xaxis_title=currency)
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(style_numeric_table(comp.sort_values(metric, ascending=False)), use_container_width=True, height=520)

    with tabs[3]:
        st.subheader("P&L Statement")
        st.dataframe(stmt, use_container_width=True, height=700)
        st.download_button("P&L statement CSV indir", download_csv(stmt), "pnl_statement.csv", "text/csv")

        st.markdown("#### Kaynak kırılımı")
        src = filtered.groupby(["Source Type", "Source File", "P&L Line"], dropna=False, as_index=False)["Value"].sum()
        st.dataframe(src, use_container_width=True, height=360)

    with tabs[4]:
        st.subheader("Veri Kontrol")
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Master Satır", f"{len(master):,}")
        q2.metric("Filtre Sonrası", f"{len(filtered):,}")
        q3.metric("İstasyon", f"{filtered['İstasyon'].nunique(dropna=True):,}" if "İstasyon" in filtered.columns else "-")
        q4.metric("P&L Kalemi", f"{filtered['P&L Line'].nunique(dropna=True):,}" if "P&L Line" in filtered.columns else "-")

        st.markdown("#### P&L Kalemleri")
        line_counts = filtered.groupby(["P&L Line", "P&L Type"], dropna=False).agg(Row_Count=("Value", "size"), Value=("Value", "sum")).reset_index()
        st.dataframe(line_counts.sort_values("P&L Line"), use_container_width=True, height=360)

        unmapped = filtered[filtered["P&L Type"].eq("Unmapped")]
        if not unmapped.empty:
            st.warning("Maplenemeyen P&L satırları var. Admin kaynak dosya/mapping kontrolü yapmalı.")
            st.dataframe(unmapped.head(500), use_container_width=True, height=300)

        with st.expander("Ham normalize veri örneği"):
            st.dataframe(filtered.head(1000), use_container_width=True, height=420)
            st.download_button("Filtrelenmiş ham veri CSV indir", download_csv(filtered), "filtered_master_rows.csv", "text/csv")


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

is_admin = admin_login_ui()
master_data = load_master_report()

if is_admin:
    mode = st.sidebar.radio("Görünüm", ["Dashboard", "Admin Paneli"], index=1)
else:
    mode = "Dashboard"

if mode == "Admin Paneli" and is_admin:
    render_admin_panel()
else:
    render_dashboard(master_data)
