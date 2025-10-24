import streamlit as st
import yfinance as yf
import datetime as dt
import pandas as pd

# List of stock tickers to display (preselected in the multiselect)
TICKERS = [
    "AAPL", "AMZN", "APP", "ABT", "PEP", "TSLA", "NVDA", "AMD",
    "SNOW", "NET", "PLTR", "MU", "ORCL", "TSM"
]

@st.cache_data(ttl=60 * 60)  # cache results for 1 hour
def get_previous_trading_day_data(ticker_symbol: str):
    """
    Fetches the most recent trading day's data available from yfinance.
    We fetch 5 days to ensure we get the last trading day,
    even if run on a weekend or holiday.
    Returns a pandas Series for the last row or None.
    """
    try:
        stock = yf.Ticker(ticker_symbol)
        hist = stock.history(period="5d")
        if not hist.empty:
            return hist.iloc[-1]
    except Exception:
        # Let the caller handle reporting
        return None
    return None

def format_price(v):
    try:
        return f"${v:.2f}"
    except Exception:
        return "N/A"

# --- Streamlit App Layout ---
st.set_page_config(page_title="EOD Stock Dashboard", layout="wide")
st.title("EOD Stock Dashboard")
st.caption("Displaying Open, High, Low, and Close for the Previous Trading Day")

# Allow user to pick which tickers to display; defaults to the predefined list
selected_tickers = st.multiselect(
    "Select tickers to display",
    options=TICKERS,
    default=TICKERS
)

if not selected_tickers:
    st.warning("No tickers selected. Please choose one or more tickers to display data.")
else:
    st.divider()
    
    all_data = []
    with st.spinner("Fetching data for selected tickers..."):
        for ticker in selected_tickers:
            data = get_previous_trading_day_data(ticker)

            if data is None or (hasattr(data, "empty") and data.empty):
                st.warning(f"No data returned for {ticker}. The ticker might be delisted or incorrect.")
                continue

            try:
                data_date = data.name.strftime("%Y-%m-%d")
            except Exception:
                data_date = str(data.name)

            all_data.append({
                "Ticker": ticker,
                "Date": data_date,
                "Open": data.get("Open"),
                "High": data.get("High"),
                "Low": data.get("Low"),
                "Close": data.get("Close")
            })

    if all_data:
        df = pd.DataFrame(all_data)
        st.dataframe(
            df,
            column_config={
                "Open": st.column_config.NumberColumn(format="$%.2f"),
                "High": st.column_config.NumberColumn(format="$%.2f"),
                "Low": st.column_config.NumberColumn(format="$%.2f"),
                "Close": st.column_config.NumberColumn(format="$%.2f"),
            },
            use_container_width=True,
            hide_index=True,
        )