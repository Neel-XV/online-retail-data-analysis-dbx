"""
Online Retail Analytics Dashboard
----------------------------------
Databricks App (Streamlit) that serves the Gold-layer tables produced by the
Online Retail medallion pipeline (online_retail_bronze -> _silver -> gold_*).

Tables expected (adjust CATALOG / SCHEMA below to match where the notebook
saved them):
    gold_customer_analytics
    gold_product_performance
    gold_sales_timeseries
    gold_geographic_performance
    gold_daily_metrics
"""

import os

import pandas as pd
import plotly.express as px
import streamlit as st
from databricks import sql
from databricks.sdk.core import Config

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
# If the notebook wrote tables with a fully qualified 3-level name (e.g. via
# Unity Catalog), set CATALOG / SCHEMA here (or via env vars of the same
# name in app.yaml) so the queries below resolve correctly. Leave CATALOG
# blank if you're using the legacy hive_metastore / a single default schema
# and the tables are resolvable by name alone.
CATALOG = os.getenv("CATALOG", "workspace")
SCHEMA = os.getenv("SCHEMA", "default")


def qualified(table: str) -> str:
    """Build a fully qualified table name from CATALOG/SCHEMA if provided."""
    if CATALOG:
        return f"{CATALOG}.{SCHEMA}.{table}"
    if SCHEMA:
        return f"{SCHEMA}.{table}"
    return table


TBL_CUSTOMER = qualified("gold_customer_analytics")
TBL_PRODUCT = qualified("gold_product_performance")
TBL_TIMESERIES = qualified("gold_sales_timeseries")
TBL_GEO = qualified("gold_geographic_performance")
TBL_DAILY = qualified("gold_daily_metrics")

st.set_page_config(
    page_title="Online Retail Analytics",
    page_icon="🛒",
    layout="wide",
)

# --------------------------------------------------------------------------
# SQL warehouse connection
# --------------------------------------------------------------------------
cfg = Config()  # Reads DATABRICKS_HOST / app service-principal auth automatically


@st.cache_resource
def get_connection():
    warehouse_id = os.getenv("DATABRICKS_WAREHOUSE_ID")
    if not warehouse_id:
        st.error(
            "DATABRICKS_WAREHOUSE_ID is not set. Add it to app.yaml (see the "
            "'sql_warehouse' resource) so the app knows which warehouse to query."
        )
        st.stop()
    http_path = f"/sql/1.0/warehouses/{warehouse_id}"
    server_hostname = cfg.host.replace("https://", "").replace("http://", "")
    return sql.connect(
        server_hostname=server_hostname,
        http_path=http_path,
        credentials_provider=lambda: cfg.authenticate,
    )


@st.cache_data(ttl=600, show_spinner="Querying Databricks SQL warehouse…")
def run_query(query: str) -> pd.DataFrame:
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute(query)
        return cursor.fetchall_arrow().to_pandas()


# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------
st.sidebar.title("🛒 Online Retail Analytics")
st.sidebar.caption("Served from the Gold layer via Databricks Apps")
if st.sidebar.button("🔄 Refresh data", use_container_width=True):
    st.cache_data.clear()
    st.rerun()
st.sidebar.divider()
st.sidebar.markdown(
    "**Tables**\n\n"
    f"- `{TBL_CUSTOMER}`\n"
    f"- `{TBL_PRODUCT}`\n"
    f"- `{TBL_TIMESERIES}`\n"
    f"- `{TBL_GEO}`\n"
    f"- `{TBL_DAILY}`"
)

# --------------------------------------------------------------------------
# Header KPIs
# --------------------------------------------------------------------------
st.title("Online Retail Analytics Dashboard")

kpi_df = run_query(
    f"""
    SELECT
        ROUND(SUM(Monetary), 2)   AS TotalRevenue,
        COUNT(*)                 AS TotalCustomers,
        ROUND(AVG(Monetary), 2)  AS AvgCustomerValue,
        ROUND(AVG(Frequency), 1) AS AvgFrequency,
        ROUND(AVG(Recency), 1)   AS AvgRecency
    FROM {TBL_CUSTOMER}
    """
)
orders_df = run_query(f"SELECT SUM(DailyOrders) AS TotalOrders FROM {TBL_DAILY}")

k = kpi_df.iloc[0]
total_orders = orders_df.iloc[0]["TotalOrders"]

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Revenue", f"£{k['TotalRevenue']:,.0f}")
c2.metric("Customers", f"{int(k['TotalCustomers']):,}")
c3.metric("Total Orders", f"{int(total_orders):,}")
c4.metric("Avg Customer Value", f"£{k['AvgCustomerValue']:,.2f}")
c5.metric("Avg Recency (days)", f"{k['AvgRecency']:.0f}")

st.divider()

# --------------------------------------------------------------------------
# Tabs
# --------------------------------------------------------------------------
tab_overview, tab_segments, tab_products, tab_geo = st.tabs(
    ["📈 Revenue Trends", "🎯 Customer Segments", "📦 Product Performance", "🌍 Geography"]
)

# --- Revenue Trends -------------------------------------------------------
with tab_overview:
    daily = run_query(
        f"""
        SELECT Date, DailyRevenue, DailyOrders, MovingAvg7Days, MovingAvg30Days
        FROM {TBL_DAILY}
        ORDER BY Date
        """
    )
    daily["Date"] = pd.to_datetime(daily["Date"])

    fig = px.line(
        daily,
        x="Date",
        y=["DailyRevenue", "MovingAvg7Days", "MovingAvg30Days"],
        title="Daily Revenue with 7-Day / 30-Day Moving Averages",
        labels={"value": "Revenue (£)", "variable": "Series"},
    )
    st.plotly_chart(fig, use_container_width=True)

    monthly = run_query(
        f"""
        SELECT Year, Month, SUM(TotalRevenue) AS MonthlyRevenue, SUM(TotalOrders) AS MonthlyOrders
        FROM {TBL_TIMESERIES}
        GROUP BY Year, Month
        ORDER BY Year, Month
        """
    )
    monthly["Period"] = (
        monthly["Year"].astype(int).astype(str) + "-" + monthly["Month"].astype(int).astype(str).str.zfill(2)
    )

    col1, col2 = st.columns(2)
    with col1:
        fig2 = px.bar(monthly, x="Period", y="MonthlyRevenue", title="Monthly Revenue")
        st.plotly_chart(fig2, use_container_width=True)
    with col2:
        fig3 = px.bar(monthly, x="Period", y="MonthlyOrders", title="Monthly Orders")
        st.plotly_chart(fig3, use_container_width=True)

# --- Customer Segments ------------------------------------------------
with tab_segments:
    seg = run_query(
        f"""
        SELECT
            CustomerSegment,
            COUNT(*)                 AS CustomerCount,
            ROUND(AVG(Monetary), 2)  AS AvgSpending,
            ROUND(AVG(Frequency), 1) AS AvgFrequency,
            ROUND(AVG(Recency), 1)   AS AvgRecency,
            ROUND(SUM(Monetary), 2)  AS TotalRevenue
        FROM {TBL_CUSTOMER}
        GROUP BY CustomerSegment
        ORDER BY TotalRevenue DESC
        """
    )
    seg["RevenueShare"] = (seg["TotalRevenue"] / seg["TotalRevenue"].sum() * 100).round(2)

    col1, col2 = st.columns([2, 3])
    with col1:
        fig4 = px.pie(
            seg, names="CustomerSegment", values="CustomerCount",
            title="Customers by Segment", hole=0.4,
        )
        st.plotly_chart(fig4, use_container_width=True)
    with col2:
        fig5 = px.bar(
            seg.sort_values("TotalRevenue"),
            x="TotalRevenue", y="CustomerSegment", orientation="h",
            title="Revenue by Customer Segment",
        )
        st.plotly_chart(fig5, use_container_width=True)

    st.subheader("Segment Detail")
    st.dataframe(seg, use_container_width=True, hide_index=True)

# --- Product Performance ------------------------------------------------
with tab_products:
    top_n = st.slider("Number of top products to show", 5, 30, 15)
    products = run_query(
        f"""
        SELECT StockCode, Description, TotalRevenue, TotalQuantitySold,
               UniqueCustomers, UniqueOrders, AvgUnitPrice
        FROM {TBL_PRODUCT}
        ORDER BY TotalRevenue DESC
        LIMIT {top_n}
        """
    )
    fig6 = px.bar(
        products.sort_values("TotalRevenue"),
        x="TotalRevenue", y="Description", orientation="h",
        title=f"Top {top_n} Products by Revenue",
    )
    st.plotly_chart(fig6, use_container_width=True)
    st.dataframe(products, use_container_width=True, hide_index=True)

# --- Geography ------------------------------------------------------------
with tab_geo:
    geo = run_query(
        f"""
        SELECT Country,
               SUM(TotalRevenue)     AS TotalRevenue,
               SUM(UniqueCustomers)  AS TotalCustomers,
               SUM(TotalOrders)      AS TotalOrders
        FROM {TBL_GEO}
        GROUP BY Country
        ORDER BY TotalRevenue DESC
        """
    )
    fig7 = px.bar(
        geo.head(15).sort_values("TotalRevenue"),
        x="TotalRevenue", y="Country", orientation="h",
        title="Top 15 Countries by Revenue",
    )
    st.plotly_chart(fig7, use_container_width=True)
    st.dataframe(geo, use_container_width=True, hide_index=True)

st.caption(
    "Data refreshes from the Gold layer every 10 minutes (cached), or on demand via the sidebar."
)
