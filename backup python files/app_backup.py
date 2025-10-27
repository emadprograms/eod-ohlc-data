import streamlit as st
import yfinance as yf
import datetime as dt
import pandas as pd

# List of all available stock tickers
TICKERS = [
    "AAPL", "AMZN", "APP", "ABT", "PEP", "TSLA", "NVDA", "AMD",
    "SNOW", "NET", "PLTR", "MU", "ORCL", "TSM", "SPY", "QQQ",
    "IWM", "DIA", "VIX", "TLT", "XLK", "XLF", "XLP", "XLE",
    "SMH", "XLI", "XLV", "UUP", "GLD"
]

@st.cache_data(ttl=60 * 15)  # Cache data for 15 minutes
def fetch_intraday_data(tickers_list, day, interval="5m"):
    """
    Fetches intraday data for a list of tickers on a specific day
    and returns a single, long-format DataFrame.
    """
    start_date = day
    end_date = day + dt.timedelta(days=1)
    
    try:
        # Download data for all tickers at once.
        # yfinance returns a multi-index column DataFrame
        # e.g., ('Open', 'AAPL'), ('Open', 'MSFT'), ...
        data = yf.download(
            tickers=tickers_list,
            start=start_date,
            end=end_date,
            interval=interval
        )
        
        if data.empty:
            return pd.DataFrame() # Return empty if no data (e.g., market holiday)

        # "Stack" the DataFrame
        # This converts the wide format (multi-index columns) to a long format
        # The 'level=1' stacks the ticker symbols (which are at index 1 of the columns)
        # The result has a multi-index: (Datetime, Ticker)
        stacked_data = data.stack(level=1)
        
        # Reset the index to turn 'Datetime' and 'Ticker' into columns
        stacked_data = stacked_data.reset_index()
        
        # Rename 'level_0' to 'Datetime' for clarity
        stacked_data = stacked_data.rename(columns={'level_0': 'Datetime'})
        
        # Reorder columns for a logical layout
        cols = ['Ticker', 'Datetime', 'Open', 'High', 'Low', 'Close', 'Volume']
        
        # Filter to just the columns we have (Adj Close is often present but not needed)
        final_cols = [col for col in cols if col in stacked_data.columns]
        stacked_data = stacked_data[final_cols]
        
        return stacked_data

    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return pd.DataFrame()

# --- Streamlit App Layout ---
st.set_page_config(page_title="Intraday Data Exporter", layout="wide")
st.title("Intraday Data Exporter for AI Analyst")
st.caption("Fetches 5-minute data for selected tickers and combines into one DataFrame.")

# Allow user to pick which tickers to display;
# Default list is smaller for faster loading, but all tickers are available.
selected_tickers = st.multiselect(
    "Select tickers to display",
    options=TICKERS,
    default=TICKERS 
)

# Add a date picker
selected_date = st.date_input(
    "Select Date", 
    dt.date.today() - dt.timedelta(days=1) # Default to yesterday
)

if st.button("Fetch 5-Minute Data"):
    if not selected_tickers:
        st.warning("Please select at least one ticker.")
    else:
        with st.spinner(f"Fetching 5-min data for {len(selected_tickers)} tickers on {selected_date}..."):
            # Call the new function
            df = fetch_intraday_data(selected_tickers, selected_date, interval="5m")

            if not df.empty:
                st.info(f"Successfully fetched {len(df)} rows of data. You can copy this data from the table's toolbar (top-right).")
                
                # Display the single, combined DataFrame
                st.dataframe(
                    df,
                    column_config={
                        "Datetime": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss"),
                        "Open": st.column_config.NumberColumn(format="$%.2f"),
                        "High": st.column_config.NumberColumn(format="$%.2f"),
                        "Low": st.column_config.NumberColumn(format="$%.2f"),
                        "Close": st.column_config.NumberColumn(format="$%.2f"),
                        "Volume": st.column_config.NumberColumn(format="%d"), # Format volume as integer
                    },
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.warning(f"No 5-minute data found for the selected tickers on {selected_date}. This might be a weekend or market holiday.")