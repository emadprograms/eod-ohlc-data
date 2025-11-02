import streamlit as st
import yfinance as yf
import datetime as dt
import pandas as pd
import numpy as np

# --- Ticker Grouping ---
STOCK_TICKERS = [
    "AAPL", "AMZN", "APP", "ABT", "PEP", "TSLA", "NVDA", "AMD",
    "SNOW", "NET", "PLTR", "MU", "ORCL", "TSM"
]
ETF_TICKERS = [
    "SPY", "QQQ", "IWM", "DIA", "TLT", "XLK", "XLF", "XLP", "XLE",
    "SMH", "XLI", "XLV", "UUP", "GLD"
]
ALL_TICKERS = sorted(STOCK_TICKERS + ETF_TICKERS)


# --- DATA FETCHING ---
@st.cache_data(ttl=60 * 15)
def fetch_intraday_data(tickers_list, day, interval="5m"):
    """Fetches intraday data for a list of tickers for a specific day."""
    start_time = dt.datetime.combine(day, dt.time(4, 0))
    end_time = dt.datetime.combine(day, dt.time(20, 0))
    
    try:
        data = yf.download(
            tickers=tickers_list,
            start=start_time,
            end=end_time,
            interval=interval,
            group_by='ticker',
            progress=False
        )
        
        if data.empty:
            return pd.DataFrame()

        if len(tickers_list) > 1:
            stacked_data = data.stack(level=0).rename_axis(['Datetime', 'Ticker']).reset_index()
        else:
            data['Ticker'] = tickers_list[0]
            stacked_data = data.reset_index()

        stacked_data = stacked_data[['Datetime', 'Ticker', 'Open', 'High', 'Low', 'Close', 'Volume']]
        stacked_data = stacked_data[stacked_data['Volume'] > 0]
        
        return stacked_data

    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return pd.DataFrame()

# --- ANALYSIS FUNCTIONS ---
def calculate_vwap(df):
    """Calculates the Volume Weighted Average Price (VWAP)."""
    q = df['Volume'] * (df['High'] + df['Low'] + df['Close']) / 3
    return q.cumsum() / df['Volume'].cumsum()

def calculate_volume_profile(df, bins=30):
    """Calculates POC, VAH, and VAL from a simple volume profile."""
    price_range = np.linspace(df['Low'].min(), df['High'].max(), bins)
    volume_at_price = np.zeros(bins)
    
    for _, row in df.iterrows():
        price_indices = np.where((price_range >= row['Low']) & (price_range <= row['High']))
        if len(price_indices[0]) > 0:
            volume_at_price[price_indices] += row['Volume'] / len(price_indices[0])
            
    poc_index = np.argmax(volume_at_price)
    poc = price_range[poc_index]
    
    total_volume = np.sum(volume_at_price)
    target_volume = total_volume * 0.70
    
    current_volume = volume_at_price[poc_index]
    low_index, high_index = poc_index, poc_index
    
    while current_volume < target_volume and (low_index > 0 or high_index < len(volume_at_price) - 1):
        low_index_next = low_index - 1
        high_index_next = high_index + 1
        
        vol_low = volume_at_price[low_index_next] if low_index_next >= 0 else -1
        vol_high = volume_at_price[high_index_next] if high_index_next < len(volume_at_price) else -1

        if vol_low > vol_high:
            current_volume += vol_low
            low_index = low_index_next
        else:
            current_volume += vol_high
            high_index = high_index_next
            
    vah = price_range[high_index]
    val = price_range[low_index]
    
    return poc, vah, val

def calculate_opening_range(df, duration_minutes=30):
    """Calculates the opening range and provides a narrative."""
    market_open_time = dt.time(9, 30)
    opening_range_end_time = (dt.datetime.combine(dt.date.today(), market_open_time) + dt.timedelta(minutes=duration_minutes)).time()
    
    or_df = df[df['Datetime'].dt.time >= market_open_time]
    or_df = or_df[or_df['Datetime'].dt.time < opening_range_end_time]
    
    if or_df.empty:
        return np.nan, np.nan, "No data in opening range."
        
    orh = or_df['High'].max()
    orl = or_df['Low'].min()
    
    after_or_df = df[df['Datetime'].dt.time >= opening_range_end_time]
    if after_or_df.empty:
        return orh, orl, "Session ended within opening range."
        
    breakout_up = (after_or_df['High'] > orh).any()
    breakdown_down = (after_or_df['Low'] < orl).any()
    
    if breakout_up and not breakdown_down:
        narrative = "Price broke above the opening range and held."
    elif breakdown_down and not breakout_up:
        narrative = "Price broke below the opening range and held."
    elif breakout_up and breakdown_down:
        narrative = "Price broke out in both directions (choppy)."
    else:
        narrative = "Price remained contained within the opening range."
        
    return orh, orl, narrative

def find_key_volume_events(df, std_dev_multiplier=2.5):
    """Identifies bars with unusually high volume."""
    volume_mean = df['Volume'].mean()
    volume_std = df['Volume'].std()
    volume_threshold = volume_mean + (volume_std * std_dev_multiplier)
    
    high_volume_df = df[df['Volume'] > volume_threshold]
    events = []
    for _, row in high_volume_df.iterrows():
        time_str = row['Datetime'].strftime('%H:%M')
        direction = "Up" if row['Close'] > row['Open'] else "Down"
        events.append(f"{time_str}: High volume on a {direction} bar.")
    return events if events else ["No significant volume events detected."]

def get_vwap_interaction(df, vwap_series):
    """Determines if VWAP acted as support or resistance."""
    if (df['Low'] > vwap_series).all():
        return "Support"
    elif (df['High'] < vwap_series).all():
        return "Resistance"
    else:
        return "Mixed (acted as both support and resistance)"

# --- Core Processing Logic ---
def generate_analysis_text(tickers_to_process, analysis_date):
    """Performs all analysis and returns a single formatted string."""
    all_data_df = fetch_intraday_data(tickers_to_process, analysis_date, interval="5m")

    if all_data_df.empty:
        return f"No data found for any tickers on {analysis_date}. It may be a weekend or holiday."

    full_analysis_text = []
    errors = []

    for ticker in tickers_to_process:
        df_ticker = all_data_df[all_data_df['Ticker'] == ticker.upper()].copy()
        
        if df_ticker.empty:
            continue
        
        df_ticker.reset_index(drop=True, inplace=True)
        
        try:
            open_price = df_ticker['Open'].iloc[0]
            close_price = df_ticker['Close'].iloc[-1]
            hod_price = df_ticker['High'].max()
            lod_price = df_ticker['Low'].min()
            
            vwap_series = calculate_vwap(df_ticker)
            session_vwap_final = vwap_series.iloc[-1]
            poc, vah, val = calculate_volume_profile(df_ticker)
            orh, orl, or_narrative = calculate_opening_range(df_ticker)
            key_volume_events = find_key_volume_events(df_ticker)
            
            close_vs_vwap = "Above" if close_price > session_vwap_final else "Below"
            vwap_interaction = get_vwap_interaction(df_ticker, vwap_series)

            ticker_summary = f"""
Summary: {ticker} | {analysis_date}
==================================================
- Date: {analysis_date}
- Ticker: {ticker}
- Open: {open_price:.2f}
- High: {hod_price:.2f}
- Low: {lod_price:.2f}
- Close: {close_price:.2f}
- POC: {poc:.2f}
- VAH: {vah:.2f}
- VAL: {val:.2f}
- VWAP: {session_vwap_final:.2f}
- ORL: {orl:.2f}
- ORH: {orh:.2f}

Key Volume Events:
"""
            for event in key_volume_events:
                ticker_summary += f"- {event}\n"
            ticker_summary += f"\nOpening Range Narrative: {or_narrative}\n"
            ticker_summary += f"VWAP Interaction: Price closed {close_vs_vwap} VWAP, which acted as {vwap_interaction}."
            
            full_analysis_text.append(ticker_summary.strip())

        except Exception as e:
            errors.append(f"An error occurred during analysis for {ticker}: {e}")

    final_text = "\n\n".join(full_analysis_text)
    if errors:
        final_text += "\n\n--- ERRORS ---\n" + "\n".join(errors)
        
    return final_text

# --- Streamlit App Layout ---
def run_streamlit_app():
    st.set_page_config(page_title="Intraday Analysis Processor", layout="wide")
    st.title("Intraday Analysis Processor")
    st.caption("Fetches 5-minute data and performs objective intraday analysis.")

    stock_tab, etf_tab = st.tabs(["Stocks Processor", "ETFs Processor"])

    # --- Stocks Tab ---
    with stock_tab:
        st.header("Process Stock Tickers")
        
        selected_stocks = st.multiselect(
            "Select stock tickers to process",
            options=STOCK_TICKERS,
            default=STOCK_TICKERS,
            key="stock_multiselect"
        )

        selected_date_stocks = st.date_input(
            "Select Date for Stocks", 
            dt.date.today() - dt.timedelta(days=1),
            key="stock_date_input"
        )

        if st.button("Process Selected Stocks", key="stock_process_button", use_container_width=True):
            if not selected_stocks:
                st.warning("Please select at least one stock ticker to process.")
            else:
                with st.spinner(f"Fetching and processing data for {len(selected_stocks)} stocks..."):
                    final_text_to_copy = generate_analysis_text(selected_stocks, selected_date_stocks)
                    
                    if final_text_to_copy:
                        st.subheader("Combined Analysis for AI (Stocks)")
                        st.info("Click the copy icon in the top-right of the box below to copy all text.")
                        st.code(final_text_to_copy, language="text")
                    else:
                        st.error("Processing failed to generate any output for the selected stocks.")

    # --- ETFs Tab ---
    with etf_tab:
        st.header("Process ETF Tickers")

        selected_etfs = st.multiselect(
            "Select ETF tickers to process",
            options=ETF_TICKERS,
            default=ETF_TICKERS,
            key="etf_multiselect"
        )

        selected_date_etfs = st.date_input(
            "Select Date for ETFs", 
            dt.date.today() - dt.timedelta(days=1),
            key="etf_date_input"
        )

        if st.button("Process Selected ETFs", key="etf_process_button", use_container_width=True):
            if not selected_etfs:
                st.warning("Please select at least one ETF ticker to process.")
            else:
                with st.spinner(f"Fetching and processing data for {len(selected_etfs)} ETFs..."):
                    final_text_to_copy = generate_analysis_text(selected_etfs, selected_date_etfs)
                    
                    if final_text_to_copy:
                        st.subheader("Combined Analysis for AI (ETFs)")
                        st.info("Click the copy icon in the top-right of the box below to copy all text.")
                        st.code(final_text_to_copy, language="text")
                    else:
                        st.error("Processing failed to generate any output for the selected ETFs.")

# --- Main Execution Logic ---
# This makes the file a runnable Streamlit page.
run_streamlit_app()