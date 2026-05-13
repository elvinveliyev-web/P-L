import os
from io import BytesIO
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import streamlit as st


# ============================================================
# STEP 1 - ZSD50 / ZSD50G SALES MAPPING TEST APP
# Amaç:
# 1) ZSD50 dosyasını doğru header ile oku
# 2) İstasyon bazında P&L long format üret
# 3) Gross Sales / Discount / COGS / Gross Margin kontrol et
# 4) Admin yükler, kullanıcı sadece son master raporu görür
# ============================================================

st.set_page_config(
    page_title="Step 1 - ZSD50 P&L Mapping",
    page_icon="⛽",
    layout="wide",
)

DATA_DIR = "pnl_app_data"
MASTER_FILE = os.path.join(DATA_DIR, "zsd50_step1_master.csv")
os.makedirs(DATA_DIR, exist_ok=True)

ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "admin123") if hasattr(st, "secrets") else "admin123"


# ------------------------------------------------------------
# Column helpers
# ------------------------------------------------------------

def clean_col_name(col) -> str:
    return str(col).replace("\u00a0", " ").strip()


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [clean_col_name(c) for c in df.columns]
    # If duplicate column names exist, make them unique
    seen = {}
    new_cols = []
    for c in df.columns:
        if c not in seen:
            seen[c] = 0
            new_cols.append(c)
        else:
            seen[c] += 1
            new_cols.append(f"{c}_{seen[c]}")
    df.columns = new_cols
    return df


def find_col(df: pd.DataFrame, aliases: List[str], required: bool = True) -> Optional[str]:
    cols = list(df.columns)
    lower_map = {clean_col_name(c).lower(): c for c in cols}

    for alias in aliases:
        key = clean_col_name(alias).lower()
        if key in lower_map:
            return lower_map[key]

    # soft contains search
    for alias in aliases:
        key = clean_col_name(alias).lower()
        for c in cols:
            if key in clean_col_name(c).lower():
                return c

    if required:
        raise ValueError(f"Zorunlu kolon bulunamadı. Aranan kolonlar: {aliases}")
    return None


def to_number(s: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce")

    return pd.to_numeric(
        s.astype(str)
        .str.replace("\u00a0", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False),
        errors="coerce",
    )


def safe_str_series(s: pd.Series) -> pd.Series:
    return s.astype(str).replace({"nan": "", "NaT": "", "<NA>": ""}).str.strip()


def read_uploaded_file(uploaded_file, sheet_name: Optional[str], header_excel_row: int) -> pd.DataFrame:
    file_bytes = uploaded_file.getvalue()
    lower = uploaded_file.name.lower()

    # header_excel_row is 1-based for user; pandas header is 0-based
    header_idx = max(int(header_excel_row) - 1, 0)

    if lower.endswith(".csv"):
        df = pd.read_csv(BytesIO(file_bytes), header=header_idx)
    elif lower.endswith((".xlsx", ".xlsm", ".xls")):
        df = pd.read_excel(BytesIO(file_bytes), sheet_name=sheet_name, header=header_idx)
    else:
        raise ValueError("Sadece CSV / XLSX / XLSM / XLS dosyası desteklenir.")

    return normalize_columns(df)


def get_excel_sheet_names(uploaded_file) -> List[str]:
    file_bytes = uploaded_file.getvalue()
    lower = uploaded_file.name.lower()
    if lower.endswith((".xlsx", ".xlsm", ".xls")):
        return pd.ExcelFile(BytesIO(file_bytes)).sheet_names
    return ["CSV"]


# ------------------------------------------------------------
# ZSD50 mapping logic
# ------------------------------------------------------------

def detect_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    return {
        "date": find_col(df, ["Ftrl.trh.", "Faturalama tarihi", "Fatura Tarihi", "Date", "Tarih"]),
        "due_date": find_col(df, ["Vade Trh", "Vade Tarihi"], required=False),
        "station": find_col(df, ["İstasyon", "Istasyon", "Station"]),
        "name": find_col(df, ["Ad 1", "Name", "Bayi Adı", "Dealer Name"], required=False),
        "dealer_type": find_col(df, ["Kanal", "Dealer/Acenta", "Dealer_Acenta", "Dealer or Agency"], required=False),
        "supply_city": find_col(df, ["Br.Tanım", "Br.Tanim", "Supply city for fuel", "Supply City"], required=False),
        "material": find_col(df, ["Malzeme", "Material"], required=False),
        "description": find_col(df, ["Tanım", "Tanim", "Ürün Açıklaması", "Urun Aciklamasi"], required=False),
        "product": find_col(df, ["Product", "Ürün", "Urun"]),
        "volume": find_col(df, ["Ftrl.mkt.", "Ftrl.mkt", "Faturalanan miktar", "Volume", "Miktar"]),
        "gross_sales_tl": find_col(df, ["Satış Fiyatı", "Satis Fiyati", "Gross Sales", "Brüt Satış"]),
        "discount_tl": find_col(df, ["İndirim", "Indirim", "Discount"]),
        "net_sales_tl": find_col(df, ["TL-Net Değer", "TL-Net Deger", "TL Net Değer", "Net Değer"], required=False),
        "additive_tl": find_col(df, ["Katkı,Opr.", "Katki,Opr.", "Additive"], required=False),
        "cogs_tl": find_col(df, ["Toplam Maliyet", "Total Cost", "COGS", "Maliyet"]),
        "rate": find_col(df, ["Rate", "Kur"], required=False),
        "net_sales_usd": find_col(df, ["USD NET DEĞER", "USD NET DEGER", "USD Net"], required=False),
        "cogs_usd": find_col(df, ["USD MALİYET", "USD MALIYET", "USD Cost"], required=False),
        "invoice_no": find_col(df, ["Ftr.Matbu No", "Ftr.blg", "Fatura No"], required=False),
    }


def classify_product_group(product_value: str) -> str:
    """
    Bu step'te ürün filtresi için kullanılır.
    P&L'deki Fuel/Gas ayrımı ise kaynak dosya tipine göre yapılır:
    - ZSD50 = Fuel
    - ZSD50G = Gas
    """
    p = str(product_value).upper()
    if "GASOLINE" in p or "BENZ" in p:
        return "Gasoline"
    if "ECTO" in p or "DIESEL" in p or "MOTOR" in p:
        return "Diesel"
    return "Other"


def amount_in_currency(df: pd.DataFrame, tl_col: str, rate_col: Optional[str], currency: str) -> pd.Series:
    tl = to_number(df[tl_col]).fillna(0)

    if currency == "TL":
        return tl

    if rate_col and rate_col in df.columns:
        rate = to_number(df[rate_col]).replace(0, np.nan)
        return (tl / rate).fillna(0)

    return pd.Series(0, index=df.index)


def make_long_line(base: pd.DataFrame, line_name: str, value: pd.Series, currency: str) -> pd.DataFrame:
    out = base.copy()
    out["P&L Line"] = line_name
    out["Currency"] = currency
    out["Value"] = pd.to_numeric(value, errors="coerce").fillna(0)
    return out


def map_zsd50_to_pnl_long(
    df: pd.DataFrame,
    source_kind: str,
    cogs_sign_policy: str,
    include_usd: bool,
) -> pd.DataFrame:
    cols = detect_columns(df)

    # Keep only real transaction rows.
    # Uploaded ZSD50 has extra blank/control rows after the transaction block.
    trans = df[
        df[cols["station"]].notna()
        & df[cols["date"]].notna()
        & df[cols["volume"]].notna()
    ].copy()

    if trans.empty:
        raise ValueError("Gerçek satış satırı bulunamadı. Header satırı veya kolon mapping yanlış olabilir.")

    trans[cols["date"]] = pd.to_datetime(trans[cols["date"]], errors="coerce")
    trans = trans[trans[cols["date"]].notna()].copy()

    source_line_prefix = "Fuel" if source_kind == "ZSD50 Fuel" else "Gas"

    base = pd.DataFrame(index=trans.index)
    base["Date"] = trans[cols["date"]]
    base["Year"] = base["Date"].dt.year
    base["Quarter"] = "Q" + base["Date"].dt.quarter.astype(str)
    base["Month"] = base["Date"].dt.strftime("%Y-%m")
    base["Day"] = base["Date"].dt.strftime("%Y-%m-%d")
    base["Year_Month_Quarter"] = (
        base["Year"].astype(str)
        + "-"
        + base["Quarter"].astype(str)
        + "-"
        + base["Date"].dt.month.astype(str)
    )

    base["İstasyon"] = safe_str_series(trans[cols["station"]])
    base["Name"] = safe_str_series(trans[cols["name"]]) if cols["name"] else ""
    base["Dealer/Acenta"] = safe_str_series(trans[cols["dealer_type"]]) if cols["dealer_type"] else ""
    base["Supply city for fuel"] = safe_str_series(trans[cols["supply_city"]]) if cols["supply_city"] else ""
    base["Product"] = safe_str_series(trans[cols["product"]])
    base["Product Group"] = base["Product"].apply(classify_product_group)
    base["Source"] = source_kind
    base["Raw Row Count"] = 1

    lines = []

    currencies = ["TL", "USD"] if include_usd else ["TL"]

    for currency in currencies:
        volume = to_number(trans[cols["volume"]]).fillna(0)
        gross_sales = amount_in_currency(trans, cols["gross_sales_tl"], cols["rate"], currency)
        discount = amount_in_currency(trans, cols["discount_tl"], cols["rate"], currency)

        if cols["additive_tl"]:
            additive = amount_in_currency(trans, cols["additive_tl"], cols["rate"], currency)
        else:
            additive = pd.Series(0, index=trans.index)

        if currency == "USD" and cols["cogs_usd"]:
            cogs_raw = to_number(trans[cols["cogs_usd"]]).fillna(0)
        else:
            cogs_raw = amount_in_currency(trans, cols["cogs_tl"], cols["rate"], currency)

        if cogs_sign_policy == "Maliyeti negatife çevir":
            cogs = -cogs_raw.abs()
        elif cogs_sign_policy == "Maliyeti pozitif bırak":
            cogs = cogs_raw
        else:
            cogs = cogs_raw

        lines.append(make_long_line(base, f"{source_line_prefix} Volume", volume, currency))
        lines.append(make_long_line(base, f"{source_line_prefix} Gross Sales", gross_sales, currency))
        lines.append(make_long_line(base, "Discount Included in Invoice Total", discount, currency))
        lines.append(make_long_line(base, "Additive", additive, currency))
        lines.append(make_long_line(base, f"{source_line_prefix} COGS", cogs, currency))

        # Totals for this source. In Step 1 only one source is uploaded, so total equals the source prefix.
        lines.append(make_long_line(base, "Volume Total", volume, currency))
        lines.append(make_long_line(base, "Gross Sales Total", gross_sales, currency))
        lines.append(make_long_line(base, "COGS Total", cogs, currency))

        gross_margin = gross_sales + discount + additive + cogs
        lines.append(make_long_line(base, "Gross Margin", gross_margin, currency))

        # Control rows are useful for checking if the ZSD50 net value reconciles.
        if cols["net_sales_tl"]:
            if currency == "USD" and cols["net_sales_usd"]:
                net_from_file = to_number(trans[cols["net_sales_usd"]]).fillna(0)
            else:
                net_from_file = amount_in_currency(trans, cols["net_sales_tl"], cols["rate"], currency)

            calculated_net = gross_sales + discount + additive
            check_diff = calculated_net - net_from_file

            lines.append(make_long_line(base, "CONTROL - Net Sales From File", net_from_file, currency))
            lines.append(make_long_line(base, "CONTROL - Calculated Net Sales", calculated_net, currency))
            lines.append(make_long_line(base, "CONTROL - Net Sales Difference", check_diff, currency))

    pnl_long = pd.concat(lines, ignore_index=True)

    # Drop zero-value control/detail rows? Keep for Step 1 audit; later we can remove control lines from dashboard.
    return pnl_long


# ------------------------------------------------------------
# Aggregation helpers
# ------------------------------------------------------------

def load_master() -> pd.DataFrame:
    if not os.path.exists(MASTER_FILE):
        return pd.DataFrame()
    df = pd.read_csv(MASTER_FILE)
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    return df


def save_master(df: pd.DataFrame) -> None:
    df.to_csv(MASTER_FILE, index=False, encoding="utf-8-sig")


def aggregate_pnl(df: pd.DataFrame, group_cols: List[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    group_cols = [c for c in group_cols if c in df.columns]
    out = (
        df.groupby(group_cols + ["P&L Line"], dropna=False, as_index=False)["Value"]
        .sum()
    )
    return out


def pivot_pnl(df_long: pd.DataFrame, index_cols: List[str]) -> pd.DataFrame:
    if df_long.empty:
        return pd.DataFrame()

    index_cols = [c for c in index_cols if c in df_long.columns]
    piv = df_long.pivot_table(
        index=index_cols,
        columns="P&L Line",
        values="Value",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()
    piv.columns.name = None

    for col in [
        "Volume Total",
        "Gross Sales Total",
        "Discount Included in Invoice Total",
        "Additive",
        "COGS Total",
        "Gross Margin",
        "CONTROL - Net Sales Difference",
    ]:
        if col not in piv.columns:
            piv[col] = 0.0

    piv["Gross Margin %"] = np.where(
        piv["Gross Sales Total"] != 0,
        piv["Gross Margin"] / piv["Gross Sales Total"],
        np.nan,
    )

    piv["Gross Margin / Volume"] = np.where(
        piv["Volume Total"] != 0,
        piv["Gross Margin"] / piv["Volume Total"],
        np.nan,
    )

    return piv


def fmt_money(v: float, currency: str) -> str:
    if pd.isna(v):
        v = 0
    symbol = "₺" if currency == "TL" else "$"
    return f"{symbol}{v:,.0f}"


def fmt_num(v: float) -> str:
    if pd.isna(v):
        v = 0
    return f"{v:,.0f}"


# ------------------------------------------------------------
# UI
# ------------------------------------------------------------

st.title("⛽ Step 1 - ZSD50 / ZSD50G P&L Mapping")
st.caption("Bu ekran sadece ilk adım içindir: ZSD50 satış dosyasını P&L formatına doğru çevirip kontrol ediyoruz.")

with st.expander("Bu adımda sabitlediğimiz mapping", expanded=True):
    st.markdown(
        """
        **Bu dosyada header Excel 2. satırda.** Bu nedenle varsayılan header satırı `2` seçildi.

        İlk mapping:
        - `Ftrl.trh.` → Tarih
        - `İstasyon` → İstasyon kodu
        - `Ad 1` → Bayi / istasyon adı
        - `Kanal` → Dealer/Acenta
        - `Br.Tanım` → Supply city for fuel
        - `Product` → Ürün
        - `Ftrl.mkt.` → Volume
        - `Satış Fiyatı` → Gross Sales
        - `İndirim` → Discount Included in Invoice
        - `Katkı,Opr.` → Additive
        - `Toplam Maliyet` → COGS
        - `TL-Net Değer` → kontrol amaçlı net satış
        - `Rate`, `USD NET DEĞER`, `USD MALİYET` → USD kontrol / çevrim

        **Önemli varsayım:** ZSD50 = Fuel, ZSD50G = Gas.  
        Bu yüzden bu dosyada `Gasoline` ürünü LPG/Gas gibi değil, Fuel içindeki benzin ürünü gibi değerlendirilir.
        """
    )

mode = st.sidebar.radio("Ekran", ["Dashboard", "Admin Panel"], index=0)

if mode == "Admin Panel":
    st.subheader("🔐 Admin Panel - ZSD50 dosyasını yükle ve master oluştur")

    password = st.text_input("Admin şifresi", type="password")
    if password != ADMIN_PASSWORD:
        st.warning("Admin paneline girmek için şifre gir.")
        st.stop()

    uploaded = st.file_uploader("ZSD50 / ZSD50G dosyasını yükle", type=["xlsx", "xlsm", "xls", "csv"])

    if uploaded is None:
        st.info("Önce ZSD50 dosyasını yükle.")
        st.stop()

    sheet_name = None
    if uploaded.name.lower().endswith((".xlsx", ".xlsm", ".xls")):
        sheets = get_excel_sheet_names(uploaded)
        sheet_name = st.selectbox("Excel sayfası", sheets, index=0)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        header_excel_row = st.number_input("Header Excel satırı", min_value=1, max_value=20, value=2, step=1)
    with c2:
        source_kind = st.selectbox("Kaynak tipi", ["ZSD50 Fuel", "ZSD50G Gas"], index=0)
    with c3:
        cogs_sign_policy = st.selectbox(
            "Maliyet işareti",
            ["Maliyeti negatife çevir", "Maliyeti pozitif bırak", "Dosyadaki gibi bırak"],
            index=0,
            help="P&L formülünde COGS toplama dahil edildiği için genellikle negatif olmalı.",
        )
    with c4:
        include_usd = st.checkbox("USD satırlarını da üret", value=True)

    try:
        raw_df = read_uploaded_file(uploaded, sheet_name, header_excel_row)
        cols = detect_columns(raw_df)

        st.markdown("#### Okunan kolonlar")
        st.write(list(raw_df.columns))

        st.markdown("#### İlk 10 satır")
        st.dataframe(raw_df.head(10), use_container_width=True)

        st.markdown("#### Otomatik kolon mapping")
        mapping_table = pd.DataFrame(
            [{"Alan": k, "Bulunan kolon": v} for k, v in cols.items()]
        )
        st.dataframe(mapping_table, use_container_width=True)

        if st.button("✅ ZSD50 master P&L oluştur / güncelle", type="primary"):
            pnl_long = map_zsd50_to_pnl_long(
                raw_df,
                source_kind=source_kind,
                cogs_sign_policy=cogs_sign_policy,
                include_usd=include_usd,
            )
            save_master(pnl_long)

            st.success(f"Master oluşturuldu: {len(pnl_long):,} P&L satırı")

            st.markdown("#### P&L long format örneği")
            st.dataframe(pnl_long.head(100), use_container_width=True)

            control = pivot_pnl(
                pnl_long[pnl_long["Currency"].eq("TL")],
                ["Currency"],
            )
            st.markdown("#### TL kontrol özeti")
            st.dataframe(control, use_container_width=True)

    except Exception as exc:
        st.error(f"Hata: {exc}")
        st.stop()

else:
    master = load_master()

    if master.empty:
        st.info("Henüz master rapor oluşturulmadı. Admin Panel’den ZSD50 dosyasını yükleyip master oluştur.")
        st.stop()

    st.subheader("📊 ZSD50 Mapping Dashboard")

    # Filters
    st.sidebar.header("Filtreler")

    currencies = sorted(master["Currency"].dropna().unique().tolist())
    currency = st.sidebar.selectbox("Para birimi", currencies, index=0 if "TL" in currencies else 0)

    df = master[master["Currency"].eq(currency)].copy()

    months = sorted(df["Month"].dropna().unique().tolist())
    selected_months = st.sidebar.multiselect("Ay", months, default=months)

    if selected_months:
        df = df[df["Month"].isin(selected_months)]

    product_groups = sorted(df["Product Group"].dropna().unique().tolist())
    selected_product_groups = st.sidebar.multiselect("Ürün grubu", product_groups, default=product_groups)
    if selected_product_groups:
        df = df[df["Product Group"].isin(selected_product_groups)]

    dealer_types = sorted(df["Dealer/Acenta"].dropna().unique().tolist())
    selected_dealer_types = st.sidebar.multiselect("Dealer/Acenta", dealer_types, default=dealer_types)
    if selected_dealer_types:
        df = df[df["Dealer/Acenta"].isin(selected_dealer_types)]

    stations = sorted(df["İstasyon"].dropna().unique().tolist())
    selected_stations = st.sidebar.multiselect("İstasyon", stations)
    if selected_stations:
        df = df[df["İstasyon"].isin(selected_stations)]

    # Remove control lines from main financial summary, but keep them for check tab
    financial_df = df[~df["P&L Line"].str.startswith("CONTROL", na=False)].copy()

    total = pivot_pnl(financial_df, ["Currency"])
    total_row = total.iloc[0] if not total.empty else pd.Series(dtype=float)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Volume Total", fmt_num(total_row.get("Volume Total", 0)))
    k2.metric("Gross Sales Total", fmt_money(total_row.get("Gross Sales Total", 0), currency))
    k3.metric("Discount", fmt_money(total_row.get("Discount Included in Invoice Total", 0), currency))
    k4.metric("COGS Total", fmt_money(total_row.get("COGS Total", 0), currency))
    k5.metric("Gross Margin", fmt_money(total_row.get("Gross Margin", 0), currency))

    margin_pct = total_row.get("Gross Margin %", np.nan)
    margin_per_vol = total_row.get("Gross Margin / Volume", np.nan)
    r1, r2 = st.columns(2)
    r1.metric("Gross Margin %", "-" if pd.isna(margin_pct) else f"{margin_pct:.2%}")
    r2.metric("Gross Margin / Volume", "-" if pd.isna(margin_per_vol) else f"{margin_per_vol:,.4f}")

    tab1, tab2, tab3, tab4 = st.tabs(["İstasyon Özeti", "Ay Trend", "P&L Statement", "Kontrol"])

    with tab1:
        st.markdown("#### İstasyon bazında özet")
        station_long = aggregate_pnl(financial_df, ["İstasyon", "Name", "Dealer/Acenta"])
        station_summary = pivot_pnl(station_long, ["İstasyon", "Name", "Dealer/Acenta"])
        station_summary = station_summary.sort_values("Gross Margin", ascending=False)

        st.dataframe(station_summary, use_container_width=True, height=600)

        csv = station_summary.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            "İstasyon özetini CSV indir",
            data=csv,
            file_name="zsd50_station_summary.csv",
            mime="text/csv",
        )

    with tab2:
        st.markdown("#### Ay bazında trend")
        month_long = aggregate_pnl(financial_df, ["Month"])
        month_summary = pivot_pnl(month_long, ["Month"]).sort_values("Month")

        st.dataframe(month_summary, use_container_width=True)

        if not month_summary.empty:
            chart_df = month_summary.set_index("Month")[["Gross Sales Total", "COGS Total", "Gross Margin"]]
            st.line_chart(chart_df)

    with tab3:
        st.markdown("#### Toplam P&L statement")
        statement = (
            financial_df.groupby("P&L Line", as_index=False)["Value"]
            .sum()
            .sort_values("P&L Line")
        )

        order = [
            "Fuel Volume", "Gas Volume", "Volume Total",
            "Fuel Gross Sales", "Gas Gross Sales", "Gross Sales Total",
            "Discount Included in Invoice Total", "Additive",
            "Fuel COGS", "Gas COGS", "COGS Total",
            "Gross Margin",
        ]
        order_map = {x: i for i, x in enumerate(order)}
        statement["Order"] = statement["P&L Line"].map(order_map).fillna(999).astype(int)
        statement = statement.sort_values(["Order", "P&L Line"])

        st.dataframe(statement[["P&L Line", "Value"]], use_container_width=True)

    with tab4:
        st.markdown("#### Net satış kontrolü")
        control_df = df[df["P&L Line"].str.startswith("CONTROL", na=False)].copy()
        control_pivot = pivot_pnl(control_df, ["Currency"])

        st.write(
            "Kontrol mantığı: `Satış Fiyatı + İndirim + Katkı,Opr.` ile dosyadaki `TL-Net Değer` karşılaştırılır. "
            "Fark sıfıra yakın olmalı."
        )
        st.dataframe(control_pivot, use_container_width=True)

        diff = control_pivot["CONTROL - Net Sales Difference"].sum() if not control_pivot.empty and "CONTROL - Net Sales Difference" in control_pivot.columns else 0
        st.metric("Net satış kontrol farkı", fmt_money(diff, currency))

        st.markdown("#### Master long format örneği")
        st.dataframe(df.head(500), use_container_width=True, height=400)

st.sidebar.divider()
st.sidebar.caption("Step 1: Sadece ZSD50/ZSD50G satış mapping testidir. Dealer master, FBL3N, rebate ve ATS sonraki adımlarda eklenecek.")
