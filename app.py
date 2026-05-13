import re
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st


# ============================================================
# FRANCHISE STATION P&L APP
# SAP CSV / Excel upload -> Station based P&L dashboard
# ============================================================

st.set_page_config(
    page_title="Franchise Station P&L",
    page_icon="⛽",
    layout="wide",
    initial_sidebar_state="expanded",
)


# -----------------------------
# Configuration
# -----------------------------

PREFERRED_SHEET_NAMES = [
    "Summary_Total_YTD_MonthlyQuerry",
    "Summary_Total_YTD_MonthlyQuery",
    "Main_Report",
    "Data",
]

COL_ALIASES = {
    "Year_Month_Quarter": ["Year_Month_Quarter", "Year Month Quarter", "year_month_quarter"],
    "Year": ["Year", "year"],
    "Quarter": ["Quarter", "quarter"],
    "Contract_Beginning": ["Contract_Beginning", "Contract Beginning"],
    "Contract_Expiration": ["Contract_Expiration", "Contract Expiration"],
    "İstasyon": ["İstasyon", "Istasyon", "Station", "station_code", "Station_Code"],
    "Name": ["Name", "Station_Name", "station_name", "Bayi_Unvani"],
    "District": ["District", "İlçe", "Ilce"],
    "City": ["City", "Şehir", "Sehir", "Il"],
    "Territory": ["Territory", "Region", "Bölge", "Bolge"],
    "Territory_Manager": ["Territory_Manager", "Territory Manager", "Bölge_Müdürü", "Bolge_Muduru"],
    "Area_Sales_Manager": ["Area_Sales_Manager", "Area Sales Manager", "Satış_Temsilcisi", "Satis_Temsilcisi"],
    "Dealer/Acenta": ["Dealer/Acenta", "Dealer_Acenta", "Dealer", "Acenta", "Bayi_Tipi"],
    "Supply_city_for_fuel": ["Supply_city_for_fuel", "Supply city for fuel", "Supply_City"],
    "Attribute.1": ["Attribute.1", "Attribute_1", "P&L_Line", "PNL_Line", "Metric", "Kalem"],
    "Attribute.2": ["Attribute.2", "Attribute_2", "Product_Currency", "Product", "Ürün"],
    "Currency_Type": ["Currency_Type", "Currency", "Para_Birimi"],
    "Value": ["Value", "Amount", "Tutar", "Deger"],
    "Date": ["Date", "Tarih", "Posting_Date", "Document_Date"],
    "Month": ["Month", "Ay"],
    "Week": ["Week", "Hafta"],
}

DIMENSION_COLS = [
    "İstasyon",
    "Name",
    "City",
    "District",
    "Territory",
    "Territory_Manager",
    "Area_Sales_Manager",
    "Dealer/Acenta",
    "Supply_city_for_fuel",
]

FILTER_DIMENSIONS = [
    ("City", "Şehir"),
    ("Territory", "Bölge"),
    ("Dealer/Acenta", "Bayi Tipi"),
    ("Territory_Manager", "Bölge Müdürü"),
    ("Area_Sales_Manager", "Satış Temsilcisi"),
    ("İstasyon", "İstasyon Kodu"),
    ("Name", "İstasyon / Bayi Adı"),
]

PNL_ORDER = [
    "Volume",
    "Gross_Sales",
    "Discount_Included_in_Invoice",
    "Discount_Premium",
    "Rebate",
    "Additive",
    "Hi-Tec",
    "ATS_Commision_Fee",
    "ATS_Discount",
    "ATS_Income",
    "_ATS_Income",
    "ATS_Disc_given_to_Customers",
    "COGS",
    "Gross_Margin",
    "Direct_Expenses_From_Station",
    "Transportation_Cost",
    "Process_&_Logistic_Variable_Expenses",
    "Process_&_Logistic_Variable_Expenses-Level_OP1",
    "Incomes",
    "Net_Trading_Margin_1",
    "Terminal_Cost",
    "Terminal_costs_-Level_OP2",
    "Net_Trading_Margin_2",
    "Expenses_From_Related_Departments",
    "Direct_Expenses_From_Related_Departments-Level_OP3",
    "Expenses_From_Unrelated_Departments",
    "Indirect_Expenses_From_Unrelated_Departments",
    "EBITDA",
    "Amortizations",
    "Tangible",
    "Intangible",
    "Net_Income",
    "Working_Capital_Cost",
    "Net_Income-Working_Capital_Cost",
    "Margin_Share",
    "Card_Expenses/Incomes",
    "Rent_Expenses/Incomes",
    "Engineering_Expenses",
    "Fuel_Variable_Process_Expenses_All",
    "Fuel_Variable_Logistic_Expenses",
    "Transport_Income_fuel_only",
    "Autogas_Variable_Logistic_Expenses",
    "Loyalty_Card_Expenses",
    "Card_Cost_All",
    "Cards_Income",
    "Rent",
    "Rent_Income",
    "BAYİLİK_SATIŞLARI/DEALERSHIP_SALES",
    "ATS_SATIŞLARI/VIS_SALES",
    "KURUMSAL_İLETİŞİM/CORPORATE_COMMUNI",
    "PAZARLAMA/MARKETING",
    "SATIŞ_DESTEK/SALES_SUPPORT",
    "OTOMASYON/AUTOMATION",
    "MÜHENDİSLİK/ENGINEERING",
    "Engineering_Expenses_All",
    "MUHASEBE/ACCOUNTING",
    "İDARİ_İŞLER/ADMINISTRATIVE",
    "İNSAN_KAYNAKLARI/HR",
    "BİLGİ_İŞLEM/IT",
    "GENEL_YÖNETİM/GENERAL_ADMIN",
    "OFİS/OFFICE",
    "İKMAL/SUPPLY",
    "TESİS/TERMINALS",
    "SEÇ-G/HSSE",
    "HUKUK/LEGAL",
    "Gain_on_sale_of_fixed_assets_All",
    "Insurance_Income_All",
    "Late_Payment_Charges_All",
    "Price_Difference_All",
    "Market_Commission_Income",
    "Penalty_Charge",
    "EMRA_Fee_All",
]

PNL_DISPLAY = {
    "Volume": "Volume",
    "Gross_Sales": "Gross Sales",
    "Discount_Included_in_Invoice": "Discount Included in Invoice",
    "Discount_Premium": "Discount Premium",
    "Rebate": "Rebate",
    "Additive": "Additive",
    "Hi-Tec": "Hi-Tec",
    "ATS_Commision_Fee": "ATS Commission Fee",
    "ATS_Discount": "ATS Discount",
    "ATS_Income": "ATS Income",
    "_ATS_Income": "ATS Income",
    "ATS_Disc_given_to_Customers": "ATS Discount Given to Customers",
    "COGS": "COGS",
    "Gross_Margin": "Gross Margin",
    "Direct_Expenses_From_Station": "Direct Expenses From Station",
    "Transportation_Cost": "Transportation Cost",
    "Process_&_Logistic_Variable_Expenses": "Process & Logistic Variable Expenses",
    "Process_&_Logistic_Variable_Expenses-Level_OP1": "Process & Logistic Variable Expenses - OP1",
    "Incomes": "Incomes",
    "Net_Trading_Margin_1": "Net Trading Margin 1",
    "Terminal_Cost": "Terminal Cost",
    "Terminal_costs_-Level_OP2": "Terminal Costs - OP2",
    "Net_Trading_Margin_2": "Net Trading Margin 2",
    "Expenses_From_Related_Departments": "Expenses From Related Departments",
    "Direct_Expenses_From_Related_Departments-Level_OP3": "Direct Expenses From Related Departments - OP3",
    "Expenses_From_Unrelated_Departments": "Expenses From Unrelated Departments",
    "Indirect_Expenses_From_Unrelated_Departments": "Indirect Expenses From Unrelated Departments",
    "EBITDA": "EBITDA",
    "Amortizations": "Amortizations",
    "Tangible": "Tangible Amortization",
    "Intangible": "Intangible Amortization",
    "Net_Income": "Net Income",
    "Working_Capital_Cost": "Working Capital Cost",
    "Net_Income-Working_Capital_Cost": "Net Income - Working Capital Cost",
    "Margin_Share": "Margin Share",
    "Card_Expenses/Incomes": "Card Expenses / Incomes",
    "Rent_Expenses/Incomes": "Rent Expenses / Incomes",
    "Engineering_Expenses": "Engineering Expenses",
}

SUMMARY_LINES = [
    "Volume",
    "Gross_Sales",
    "COGS",
    "Gross_Margin",
    "Net_Trading_Margin_1",
    "Net_Trading_Margin_2",
    "EBITDA",
    "Amortizations",
    "Net_Income",
    "Working_Capital_Cost",
    "Net_Income-Working_Capital_Cost",
]

PRODUCT_MAP = {
    "Total": "Total",
    "Diesel": "Diesel",
    "Gasoline": "Gasoline",
    "LPG": "LPG",
    "Other": "Other",
}


# -----------------------------
# Helper functions
# -----------------------------

def find_column(df: pd.DataFrame, canonical_name: str) -> Optional[str]:
    aliases = COL_ALIASES.get(canonical_name, [canonical_name])
    lower_map = {str(c).strip().lower(): c for c in df.columns}

    for alias in aliases:
        if alias in df.columns:
            return alias
        key = str(alias).strip().lower()
        if key in lower_map:
            return lower_map[key]

    return None


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    for canonical in COL_ALIASES:
        actual = find_column(df, canonical)
        if actual is not None:
            rename_map[actual] = canonical

    df = df.rename(columns=rename_map)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def safe_to_numeric(s: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s):
        return s.astype(float)

    cleaned = (
        s.astype(str)
        .str.replace("\u00a0", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def parse_periods(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "Value" in df.columns:
        df["Value"] = safe_to_numeric(df["Value"]).fillna(0)

    # Optional real date column. Use this when SAP gives daily data.
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce", dayfirst=True)
    elif "Year_Month_Quarter" in df.columns:
        # Expected example: 2025-Q1-1, 2025-Q4-12
        extracted = (
            df["Year_Month_Quarter"]
            .astype(str)
            .str.extract(r"(?P<Year>\d{4})-Q(?P<QuarterNo>\d)-(?P<Month>\d{1,2})")
        )

        if "Year" not in df.columns:
            df["Year"] = pd.to_numeric(extracted["Year"], errors="coerce")
        else:
            df["Year"] = pd.to_numeric(df["Year"], errors="coerce").fillna(
                pd.to_numeric(extracted["Year"], errors="coerce")
            )

        df["Month"] = pd.to_numeric(extracted["Month"], errors="coerce")
        df["QuarterNo"] = pd.to_numeric(extracted["QuarterNo"], errors="coerce")

        df["Date"] = pd.to_datetime(
            dict(
                year=pd.to_numeric(df["Year"], errors="coerce").fillna(1900).astype(int),
                month=df["Month"].fillna(1).astype(int),
                day=1,
            ),
            errors="coerce",
        )
    elif "Year" in df.columns and "Month" in df.columns:
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce")
        df["Month"] = pd.to_numeric(df["Month"], errors="coerce")
        df["Date"] = pd.to_datetime(
            dict(
                year=df["Year"].fillna(1900).astype(int),
                month=df["Month"].fillna(1).astype(int),
                day=1,
            ),
            errors="coerce",
        )
    else:
        df["Date"] = pd.NaT

    if "Year" not in df.columns:
        df["Year"] = df["Date"].dt.year

    if "Quarter" not in df.columns:
        df["Quarter"] = "Q" + df["Date"].dt.quarter.astype("Int64").astype(str)

    df["Year"] = pd.to_numeric(df["Year"], errors="coerce").astype("Int64")
    df["Month"] = df["Date"].dt.month.astype("Int64")
    df["Month_Label"] = df["Date"].dt.strftime("%Y-%m")
    df["Quarter_Label"] = df["Date"].dt.year.astype("Int64").astype(str) + "-Q" + df["Date"].dt.quarter.astype("Int64").astype(str)
    df["Year_Label"] = df["Date"].dt.year.astype("Int64").astype(str)

    iso = df["Date"].dt.isocalendar()
    df["ISO_Year"] = iso.year.astype("Int64")
    df["ISO_Week"] = iso.week.astype("Int64")
    df["Week_Label"] = df["ISO_Year"].astype(str) + "-W" + df["ISO_Week"].astype(str).str.zfill(2)
    df["Day_Label"] = df["Date"].dt.strftime("%Y-%m-%d")

    return df


def make_period_column(df: pd.DataFrame, period_level: str) -> Tuple[pd.DataFrame, str]:
    df = df.copy()

    if period_level == "Günlük":
        period_col = "Day_Label"
    elif period_level == "Haftalık":
        period_col = "Week_Label"
    elif period_level == "Aylık":
        period_col = "Month_Label"
    elif period_level == "Çeyreklik":
        period_col = "Quarter_Label"
    else:
        period_col = "Year_Label"

    df["Selected_Period"] = df[period_col]
    return df, "Selected_Period"


def available_values(df: pd.DataFrame, col: str) -> List[str]:
    if col not in df.columns:
        return []
    vals = (
        df[col]
        .dropna()
        .astype(str)
        .replace(["nan", "NaT", "<NA>"], np.nan)
        .dropna()
        .unique()
        .tolist()
    )
    return sorted(vals)


def format_amount(value: float, currency: str) -> str:
    if pd.isna(value):
        value = 0
    symbol = "₺" if currency == "TL" else "$" if currency == "USD" else ""
    return f"{symbol}{value:,.0f}"


def format_ratio(value: float) -> str:
    if pd.isna(value) or np.isinf(value):
        return "-"
    return f"{value:.2%}"


def format_per_volume(value: float, currency: str) -> str:
    if pd.isna(value) or np.isinf(value):
        return "-"
    symbol = "₺" if currency == "TL" else "$" if currency == "USD" else ""
    return f"{symbol}{value:,.4f}"


def build_attribute2_filter(currency: str, products: List[str]) -> List[str]:
    if not products:
        products = ["Total"]

    selected = []
    for product in products:
        prefix = PRODUCT_MAP.get(product, product)

        # For total P&L, use the official total metric to avoid double-counting.
        if prefix == "Total":
            selected.append(f"Total_{currency}")
        else:
            selected.append(f"{prefix}_{currency}")

    return selected


def filter_currency_product(df: pd.DataFrame, currency: str, products: List[str]) -> pd.DataFrame:
    df = df.copy()

    attr2_values = build_attribute2_filter(currency, products)

    if "Attribute.2" in df.columns:
        df = df[df["Attribute.2"].astype(str).isin(attr2_values)]

    if "Currency_Type" in df.columns:
        # Keep only relevant currency rows. Some calculated / control rows may have blank or "-"
        # and are intentionally excluded from P&L sums.
        df = df[df["Currency_Type"].astype(str).eq(currency)]

    return df


def apply_dimension_filters(df: pd.DataFrame, selected_filters: Dict[str, List[str]]) -> pd.DataFrame:
    result = df.copy()

    for col, selected in selected_filters.items():
        if col in result.columns and selected:
            result = result[result[col].astype(str).isin(selected)]

    return result


def aggregate_pnl(
    df: pd.DataFrame,
    group_cols: List[str],
    currency: str,
    products: List[str],
) -> pd.DataFrame:
    base = filter_currency_product(df, currency, products)

    required = ["Attribute.1", "Value"]
    for col in required:
        if col not in base.columns:
            return pd.DataFrame()

    group_cols = [c for c in group_cols if c in base.columns]
    agg_cols = group_cols + ["Attribute.1"]

    pnl = (
        base.groupby(agg_cols, dropna=False, as_index=False)["Value"]
        .sum()
        .rename(columns={"Attribute.1": "P&L Line"})
    )

    return pnl


def make_pnl_table(pnl_long: pd.DataFrame, index_cols: List[str]) -> pd.DataFrame:
    if pnl_long.empty:
        return pd.DataFrame()

    index_cols = [c for c in index_cols if c in pnl_long.columns]

    wide = (
        pnl_long.pivot_table(
            index=index_cols,
            columns="P&L Line",
            values="Value",
            aggfunc="sum",
            fill_value=0,
        )
        .reset_index()
    )

    wide.columns.name = None

    for line in SUMMARY_LINES:
        if line not in wide.columns:
            wide[line] = 0.0

    wide["Gross_Margin_%"] = np.where(wide["Gross_Sales"] != 0, wide["Gross_Margin"] / wide["Gross_Sales"], np.nan)
    wide["EBITDA_%"] = np.where(wide["Gross_Sales"] != 0, wide["EBITDA"] / wide["Gross_Sales"], np.nan)
    wide["Net_Income_%"] = np.where(wide["Gross_Sales"] != 0, wide["Net_Income"] / wide["Gross_Sales"], np.nan)

    wide["Gross_Margin_per_Volume"] = np.where(wide["Volume"] != 0, wide["Gross_Margin"] / wide["Volume"], np.nan)
    wide["EBITDA_per_Volume"] = np.where(wide["Volume"] != 0, wide["EBITDA"] / wide["Volume"], np.nan)
    wide["Net_Income_per_Volume"] = np.where(wide["Volume"] != 0, wide["Net_Income"] / wide["Volume"], np.nan)

    return wide


def make_ordered_pnl_statement(pnl_long: pd.DataFrame) -> pd.DataFrame:
    if pnl_long.empty:
        return pd.DataFrame(columns=["Order", "P&L Line", "Display Line", "Value"])

    stmt = (
        pnl_long.groupby("P&L Line", as_index=False)["Value"]
        .sum()
    )

    order_map = {line: i + 1 for i, line in enumerate(PNL_ORDER)}
    stmt["Order"] = stmt["P&L Line"].map(order_map).fillna(9999).astype(int)
    stmt["Display Line"] = stmt["P&L Line"].map(PNL_DISPLAY).fillna(stmt["P&L Line"])
    stmt = stmt.sort_values(["Order", "P&L Line"])

    return stmt[["Order", "P&L Line", "Display Line", "Value"]]


def downloadable_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


@st.cache_data(show_spinner=False)
def load_csv_from_bytes(file_bytes: bytes) -> pd.DataFrame:
    encodings = ["utf-8-sig", "utf-8", "cp1254", "latin1"]
    last_error = None

    for enc in encodings:
        try:
            return pd.read_csv(BytesIO(file_bytes), encoding=enc)
        except Exception as exc:
            last_error = exc

    raise last_error


@st.cache_data(show_spinner=False)
def load_excel_sheet_names(file_bytes: bytes) -> List[str]:
    xls = pd.ExcelFile(BytesIO(file_bytes))
    return xls.sheet_names


@st.cache_data(show_spinner=False)
def load_excel_from_bytes(file_bytes: bytes, sheet_name: str) -> pd.DataFrame:
    return pd.read_excel(BytesIO(file_bytes), sheet_name=sheet_name)


@st.cache_data(show_spinner=False)
def prepare_dataframe(file_name: str, file_bytes: bytes, sheet_name: Optional[str]) -> pd.DataFrame:
    lower = file_name.lower()

    if lower.endswith(".csv"):
        df = load_csv_from_bytes(file_bytes)
    elif lower.endswith((".xlsx", ".xlsm", ".xls")):
        df = load_excel_from_bytes(file_bytes, sheet_name or 0)
    else:
        raise ValueError("Desteklenmeyen dosya tipi. Lütfen CSV veya Excel yükleyin.")

    df = standardize_columns(df)
    df = parse_periods(df)

    for col in ["Attribute.1", "Attribute.2", "Currency_Type"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    for col in DIMENSION_COLS:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    return df


def show_kpi(label: str, value: float, currency: str, help_text: Optional[str] = None, amount: bool = True):
    display = format_amount(value, currency) if amount else f"{value:,.0f}"
    st.metric(label, display, help=help_text)


def style_summary_table(df: pd.DataFrame, currency: str) -> pd.io.formats.style.Styler:
    money_cols = [
        "Gross_Sales",
        "COGS",
        "Gross_Margin",
        "Net_Trading_Margin_1",
        "Net_Trading_Margin_2",
        "EBITDA",
        "Amortizations",
        "Net_Income",
        "Working_Capital_Cost",
        "Net_Income-Working_Capital_Cost",
    ]

    ratio_cols = ["Gross_Margin_%", "EBITDA_%", "Net_Income_%"]
    per_volume_cols = ["Gross_Margin_per_Volume", "EBITDA_per_Volume", "Net_Income_per_Volume"]

    fmt = {"Volume": "{:,.0f}"}
    fmt.update({col: "{:,.0f}" for col in money_cols if col in df.columns})
    fmt.update({col: "{:.2%}" for col in ratio_cols if col in df.columns})
    fmt.update({col: "{:,.4f}" for col in per_volume_cols if col in df.columns})

    return df.style.format(fmt)


# -----------------------------
# UI
# -----------------------------

st.title("⛽ Franchise Station P&L Dashboard")
st.caption("SAP CSV / Excel yükle → istasyon, şehir, bölge, bayi tipi, bölge müdürü ve satış temsilcisi bazında P&L analiz et.")

with st.expander("Beklenen veri formatı", expanded=False):
    st.markdown(
        """
        Uygulama şu uzun formatı esas alır:

        `Year_Month_Quarter, Year, Quarter, Contract_Beginning, Contract_Expiration, İstasyon, Name, District, City,
        Territory, Territory_Manager, Area_Sales_Manager, Dealer/Acenta, Supply_city_for_fuel, Attribute.1,
        Attribute.2, Currency_Type, Value`

        Örnek `Attribute.1`: `Volume`, `Gross_Sales`, `COGS`, `Gross_Margin`, `EBITDA`, `Net_Income`  
        Örnek `Attribute.2`: `Total_TL`, `Diesel_TL`, `Gasoline_TL`, `LPG_TL`, `Total_USD`
        """
    )

uploaded_file = st.file_uploader(
    "SAP'den aldığın CSV veya Excel dosyasını yükle",
    type=["csv", "xlsx", "xlsm", "xls"],
)

if uploaded_file is None:
    st.info("Başlamak için SAP’den aldığın CSV/Excel dosyasını yükle. Büyük dosyalarda CSV daha hızlı çalışır.")
    st.stop()

file_bytes = uploaded_file.getvalue()
sheet_name = None

if uploaded_file.name.lower().endswith((".xlsx", ".xlsm", ".xls")):
    try:
        sheet_names = load_excel_sheet_names(file_bytes)
        default_index = 0
        for preferred in PREFERRED_SHEET_NAMES:
            if preferred in sheet_names:
                default_index = sheet_names.index(preferred)
                break

        sheet_name = st.sidebar.selectbox("Excel sayfası", sheet_names, index=default_index)
    except Exception as exc:
        st.error(f"Excel sayfaları okunamadı: {exc}")
        st.stop()

try:
    with st.spinner("Veri okunuyor ve hazırlanıyor..."):
        df = prepare_dataframe(uploaded_file.name, file_bytes, sheet_name)
except Exception as exc:
    st.error(f"Dosya okunamadı: {exc}")
    st.stop()

missing = [c for c in ["Attribute.1", "Attribute.2", "Currency_Type", "Value"] if c not in df.columns]
if missing:
    st.error(f"Eksik zorunlu kolonlar: {missing}")
    st.stop()

# Sidebar filters
st.sidebar.header("Filtreler")

currency_values = available_values(df, "Currency_Type")
currency_values = [c for c in currency_values if c in ["TL", "USD"]] or ["TL", "USD"]
currency = st.sidebar.radio("Para Birimi", currency_values, horizontal=True)

period_level = st.sidebar.selectbox(
    "Dönem",
    ["Senelik", "Çeyreklik", "Aylık", "Haftalık", "Günlük"],
    index=2,
)

df, period_col = make_period_column(df, period_level)

if period_level in ["Günlük", "Haftalık"]:
    if df["Date"].isna().all() or df["Date"].dt.day.nunique(dropna=True) <= 1:
        st.sidebar.warning("Yüklenen veri günlük/haftalık detay içermiyorsa bu kırılım aylık veri üzerinden sınırlı görünür.")

period_values = available_values(df, period_col)
selected_periods = st.sidebar.multiselect(
    "Dönem seçimi",
    options=period_values,
    default=period_values,
)

product_options = ["Total", "Diesel", "Gasoline", "LPG", "Other"]
selected_products = st.sidebar.multiselect(
    "Ürün",
    options=product_options,
    default=["Total"],
    help="Total seçildiğinde resmi Total_TL / Total_USD satırları kullanılır. Ürün seçersen ürün bazlı P&L toplanır.",
)

selected_filters: Dict[str, List[str]] = {}
for col, label in FILTER_DIMENSIONS:
    values = available_values(df, col)
    if values:
        selected_filters[col] = st.sidebar.multiselect(label, options=values)

filtered = df.copy()

if selected_periods:
    filtered = filtered[filtered[period_col].astype(str).isin(selected_periods)]

filtered = apply_dimension_filters(filtered, selected_filters)

# Main filtered P&L data
pnl_total_long = aggregate_pnl(filtered, [], currency, selected_products)
pnl_statement = make_ordered_pnl_statement(pnl_total_long)

station_group_cols = [c for c in ["İstasyon", "Name", "City", "Territory", "Territory_Manager", "Area_Sales_Manager", "Dealer/Acenta"] if c in filtered.columns]
station_long = aggregate_pnl(filtered, station_group_cols, currency, selected_products)
station_summary = make_pnl_table(station_long, station_group_cols)

timeline_long = aggregate_pnl(filtered, [period_col], currency, selected_products)
timeline_summary = make_pnl_table(timeline_long, [period_col])

# KPI extraction
def get_line_value(line: str) -> float:
    if pnl_statement.empty:
        return 0.0
    s = pnl_statement.loc[pnl_statement["P&L Line"].eq(line), "Value"]
    return float(s.sum()) if not s.empty else 0.0

total_volume = get_line_value("Volume")
gross_sales = get_line_value("Gross_Sales")
gross_margin = get_line_value("Gross_Margin")
ebitda = get_line_value("EBITDA")
net_income = get_line_value("Net_Income")
net_income_wcc = get_line_value("Net_Income-Working_Capital_Cost")

gross_margin_pct = gross_margin / gross_sales if gross_sales else np.nan
ebitda_pct = ebitda / gross_sales if gross_sales else np.nan
net_income_pct = net_income / gross_sales if gross_sales else np.nan
net_income_per_liter = net_income / total_volume if total_volume else np.nan

# Tabs
tab_dashboard, tab_station, tab_compare, tab_pnl_detail, tab_quality = st.tabs(
    [
        "📊 Dashboard",
        "⛽ İstasyon Bazlı Analiz",
        "⚖️ Karşılaştırma",
        "📑 P&L Detay",
        "🧪 Veri Kontrol",
    ]
)

with tab_dashboard:
    st.subheader("Genel Özet")

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    with k1:
        show_kpi("Volume", total_volume, currency, amount=False)
    with k2:
        show_kpi("Gross Sales", gross_sales, currency)
    with k3:
        show_kpi("Gross Margin", gross_margin, currency)
    with k4:
        show_kpi("EBITDA", ebitda, currency)
    with k5:
        show_kpi("Net Income", net_income, currency)
    with k6:
        st.metric("Net Income / Volume", format_per_volume(net_income_per_liter, currency))

    r1, r2, r3 = st.columns(3)
    r1.metric("Gross Margin %", format_ratio(gross_margin_pct))
    r2.metric("EBITDA %", format_ratio(ebitda_pct))
    r3.metric("Net Income %", format_ratio(net_income_pct))

    st.divider()

    c1, c2 = st.columns([1.2, 1])

    with c1:
        st.markdown("#### Dönemsel Trend")
        if not timeline_summary.empty:
            metric_to_plot = st.selectbox(
                "Trend metriği",
                ["Gross_Sales", "Gross_Margin", "EBITDA", "Net_Income", "Net_Income-Working_Capital_Cost"],
                index=3,
            )

            fig = px.line(
                timeline_summary.sort_values(period_col),
                x=period_col,
                y=metric_to_plot,
                markers=True,
                title=f"{metric_to_plot} Trend",
            )
            fig.update_layout(height=430, xaxis_title="Dönem", yaxis_title=currency)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Trend için veri bulunamadı.")

    with c2:
        st.markdown("#### En Kârlı / En Zarar Eden İstasyonlar")
        if not station_summary.empty:
            rank_metric = st.selectbox(
                "Sıralama metriği",
                ["Net_Income", "EBITDA", "Gross_Margin", "Net_Income-Working_Capital_Cost"],
                index=0,
            )
            top_bottom = pd.concat(
                [
                    station_summary.sort_values(rank_metric, ascending=False).head(10).assign(Group="Top 10"),
                    station_summary.sort_values(rank_metric, ascending=True).head(10).assign(Group="Bottom 10"),
                ],
                ignore_index=True,
            )

            label_col = "Name" if "Name" in top_bottom.columns else "İstasyon"
            fig = px.bar(
                top_bottom,
                y=label_col,
                x=rank_metric,
                color="Group",
                orientation="h",
                title=f"Top / Bottom - {rank_metric}",
            )
            fig.update_layout(height=430, yaxis_title="", xaxis_title=currency)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("İstasyon sıralaması için veri bulunamadı.")

    st.markdown("#### İstasyon Özet Tablosu")
    if not station_summary.empty:
        show_cols = [
            c for c in [
                "İstasyon",
                "Name",
                "City",
                "Territory",
                "Territory_Manager",
                "Area_Sales_Manager",
                "Dealer/Acenta",
                "Volume",
                "Gross_Sales",
                "Gross_Margin",
                "Gross_Margin_%",
                "EBITDA",
                "EBITDA_%",
                "Net_Income",
                "Net_Income_%",
                "Net_Income_per_Volume",
                "Net_Income-Working_Capital_Cost",
            ]
            if c in station_summary.columns
        ]

        st.dataframe(
            style_summary_table(station_summary[show_cols], currency),
            use_container_width=True,
            height=520,
        )

        st.download_button(
            "İstasyon özetini CSV indir",
            data=downloadable_csv(station_summary[show_cols]),
            file_name="station_pnl_summary.csv",
            mime="text/csv",
        )
    else:
        st.info("Özet tablo için veri bulunamadı.")

with tab_station:
    st.subheader("İstasyon Bazlı P&L")

    if "İstasyon" not in filtered.columns:
        st.error("İstasyon kolonu bulunamadı.")
    else:
        station_options = available_values(filtered, "İstasyon")
        if not station_options:
            st.info("Seçili filtrelerde istasyon bulunamadı.")
        else:
            selected_station = st.selectbox("İstasyon seç", station_options)

            station_df = filtered[filtered["İstasyon"].astype(str).eq(selected_station)]
            station_name = station_df["Name"].dropna().astype(str).iloc[0] if "Name" in station_df.columns and not station_df["Name"].dropna().empty else selected_station
            st.markdown(f"### {selected_station} - {station_name}")

            station_pnl_long = aggregate_pnl(station_df, [], currency, selected_products)
            station_statement = make_ordered_pnl_statement(station_pnl_long)

            s1, s2 = st.columns([1, 1])

            with s1:
                display_stmt = station_statement.copy()
                display_stmt["Value"] = display_stmt["Value"].round(2)
                st.dataframe(
                    display_stmt[["Order", "Display Line", "Value"]],
                    use_container_width=True,
                    height=620,
                )

            with s2:
                station_timeline_long = aggregate_pnl(station_df, [period_col], currency, selected_products)
                station_timeline = make_pnl_table(station_timeline_long, [period_col])

                if not station_timeline.empty:
                    fig = px.line(
                        station_timeline.sort_values(period_col),
                        x=period_col,
                        y=["Gross_Margin", "EBITDA", "Net_Income"],
                        markers=True,
                        title="İstasyon P&L Trend",
                    )
                    fig.update_layout(height=420, xaxis_title="Dönem", yaxis_title=currency)
                    st.plotly_chart(fig, use_container_width=True)

                    fig2 = px.bar(
                        station_timeline.sort_values(period_col),
                        x=period_col,
                        y="Volume",
                        title="Volume Trend",
                    )
                    fig2.update_layout(height=320, xaxis_title="Dönem", yaxis_title="Volume")
                    st.plotly_chart(fig2, use_container_width=True)

with tab_compare:
    st.subheader("İstasyon / Şehir / Bölge Karşılaştırma")

    compare_dimension_options = [
        c for c in ["İstasyon", "Name", "City", "Territory", "Territory_Manager", "Area_Sales_Manager", "Dealer/Acenta"]
        if c in filtered.columns
    ]

    if not compare_dimension_options:
        st.info("Karşılaştırma için uygun kolon bulunamadı.")
    else:
        compare_dim = st.selectbox("Karşılaştırma kırılımı", compare_dimension_options)
        compare_long = aggregate_pnl(filtered, [compare_dim], currency, selected_products)
        compare_table = make_pnl_table(compare_long, [compare_dim])

        if compare_table.empty:
            st.info("Karşılaştırma için veri bulunamadı.")
        else:
            compare_metric = st.selectbox(
                "Karşılaştırma metriği",
                [
                    "Volume",
                    "Gross_Sales",
                    "Gross_Margin",
                    "Gross_Margin_%",
                    "EBITDA",
                    "EBITDA_%",
                    "Net_Income",
                    "Net_Income_%",
                    "Net_Income_per_Volume",
                    "Net_Income-Working_Capital_Cost",
                ],
                index=6,
            )

            top_n = st.slider("Gösterilecek kayıt sayısı", 5, 50, 20)

            chart_data = compare_table.sort_values(compare_metric, ascending=False).head(top_n)
            fig = px.bar(
                chart_data,
                x=compare_metric,
                y=compare_dim,
                orientation="h",
                title=f"{compare_dim} bazında {compare_metric}",
            )
            fig.update_layout(height=600, yaxis_title="", xaxis_title=currency if "%" not in compare_metric else "%")
            st.plotly_chart(fig, use_container_width=True)

            st.dataframe(
                style_summary_table(compare_table.sort_values(compare_metric, ascending=False), currency),
                use_container_width=True,
                height=520,
            )

with tab_pnl_detail:
    st.subheader("P&L Detay")

    st.markdown("#### Toplam P&L Statement")
    if pnl_statement.empty:
        st.info("P&L detay için veri bulunamadı.")
    else:
        display_statement = pnl_statement.copy()
        display_statement["Value"] = display_statement["Value"].round(2)
        st.dataframe(
            display_statement[["Order", "P&L Line", "Display Line", "Value"]],
            use_container_width=True,
            height=650,
        )

        st.download_button(
            "P&L detayını CSV indir",
            data=downloadable_csv(display_statement),
            file_name="pnl_statement_detail.csv",
            mime="text/csv",
        )

    st.markdown("#### Ham filtrelenmiş veri örneği")
    st.dataframe(filtered.head(500), use_container_width=True, height=300)

with tab_quality:
    st.subheader("Veri Kontrol")

    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Satır Sayısı", f"{len(df):,}")
    q2.metric("Filtre Sonrası Satır", f"{len(filtered):,}")
    q3.metric("İstasyon Sayısı", f"{df['İstasyon'].nunique():,}" if "İstasyon" in df.columns else "-")
    q4.metric("P&L Kalemi", f"{df['Attribute.1'].nunique():,}" if "Attribute.1" in df.columns else "-")

    st.markdown("#### Kolonlar")
    st.write(list(df.columns))

    st.markdown("#### Attribute.1 / P&L Kalemleri")
    if "Attribute.1" in df.columns:
        attr1_table = (
            df["Attribute.1"]
            .value_counts(dropna=False)
            .reset_index()
            .rename(columns={"index": "P&L Line", "Attribute.1": "Row Count"})
        )
        st.dataframe(attr1_table, use_container_width=True, height=360)

    st.markdown("#### Attribute.2 / Ürün-Para Birimi")
    if "Attribute.2" in df.columns:
        attr2_table = (
            df["Attribute.2"]
            .value_counts(dropna=False)
            .reset_index()
            .rename(columns={"index": "Product Currency", "Attribute.2": "Row Count"})
        )
        st.dataframe(attr2_table, use_container_width=True, height=260)

    st.markdown("#### Eksik Değer Kontrolü")
    null_table = (
        df.isna()
        .sum()
        .reset_index()
        .rename(columns={"index": "Column", 0: "Missing Count"})
    )
    null_table["Missing %"] = null_table["Missing Count"] / len(df)
    st.dataframe(null_table, use_container_width=True, height=320)

st.sidebar.divider()
st.sidebar.caption("Not: Büyük SAP dosyalarında CSV, Excel'e göre daha hızlı çalışır.")
