import streamlit as st
import yfinance as yf
import datetime as dt
import pandas as pd
import numpy as np

# List of all available stock tickers
TICKERS = [
    "AAPL", "AMZN", "APP", "ABT", "PEP", "TSLA", "NVDA", "AMD",
    "SNOW", "NET", "PLTR", "MU", "ORCL", "TSM", "SPY", "QQQ",
    "IWM", "DIA", "TLT", "XLK", "XLF", "XLP", "XLE",
    "SMH", "XLI", "XLV", "UUP", "GLD"
]

# --- DATA FETCHING (FROM YOUR PROMPT) ---

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
        data = yf.download(
            tickers=tickers_list,
            start=start_date,
            end=end_date,
            interval=interval,
            ignore_tz=True, # Ignore timezone info for simplicity
            progress=False # Suppress yfinance progress bar in logs
        )
        
        if data.empty:
            return pd.DataFrame() # Return empty if no data (e.g., market holiday)

        # "Stack" the DataFrame
        # If only one ticker is downloaded, the columns are not a multi-index.
        if len(tickers_list) > 1:
            stacked_data = data.stack(level=1)
        else:
            # For a single ticker, add the 'Ticker' column manually
            data['Ticker'] = tickers_list[0]
            stacked_data = data
        
        # Reset the index to turn 'Datetime' and 'Ticker' into columns
        stacked_data = stacked_data.reset_index()
        
        # Rename 'level_0' to 'Datetime' for clarity
        stacked_data = stacked_data.rename(columns={'level_0': 'Datetime'})

        # Ensure Ticker is uppercase
        stacked_data['Ticker'] = stacked_data['Ticker'].str.upper()
        
        # Reorder columns for a logical layout
        cols = ['Ticker', 'Datetime', 'Open', 'High', 'Low', 'Close', 'Volume']
        
        # Filter to just the columns we have (Adj Close is often present but not needed)
        final_cols = [col for col in cols if col in stacked_data.columns]
        stacked_data = stacked_data[final_cols]
        
        # Filter out rows with no volume or NA values
        stacked_data = stacked_data.dropna(subset=['Open', 'High', 'Low', 'Close', 'Volume'])
        stacked_data = stacked_data[stacked_data['Volume'] > 0]
        
        return stacked_data

    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return pd.DataFrame()

# --- NEW ANALYSIS FUNCTIONS ("PROCESSOR") ---

def calculate_vwap(df):
    """Calculates the Volume Weighted Average Price (VWAP) series."""
    # Ensure Volume is not zero to avoid division by zero
    if df['Volume'].sum() == 0:
        return pd.Series([np.nan] * len(df), index=df.index)
    tp = (df['High'] + df['Low'] + df['Close']) / 3
    tpv = tp * df['Volume']
    vwap_series = tpv.cumsum() / df['Volume'].cumsum()
    return vwap_series

def calculate_volume_profile(df, bins=50):
    """
    Calculates Volume Profile: POC, VAH, and VAL.
    Uses the midpoint of H-L as the price for volume binning.
    """
    if df.empty or df['Volume'].sum() == 0:
        return np.nan, np.nan, np.nan
        
    # Use (High+Low)/2 for a more accurate price representation
    price_mid = (df['High'] + df['Low']) / 2
    
    # Create price bins
    price_bins = pd.cut(price_mid, bins=bins)
    
    # Group by price bins and sum volume
    grouped = df.groupby(price_bins)['Volume'].sum()
    
    # 1. Find Point of Control (POC)
    poc_bin = grouped.idxmax()
    poc_price = poc_bin.mid
    
    # 2. Find Value Area (70% of volume)
    total_volume = grouped.sum()
    target_volume = total_volume * 0.70
    
    # Sort bins by volume, high to low
    sorted_by_vol = grouped.sort_values(ascending=False)
    
    # Cumulatively sum volume
    cumulative_vol = sorted_by_vol.cumsum()
    
    # Find the bins that are part of the value area
    value_area_bins = sorted_by_vol[cumulative_vol <= target_volume]
    
    # 3. Find VAH and VAL
    val_price = value_area_bins.index.min().left
    vah_price = value_area_bins.index.max().right
    
    return poc_price, vah_price, val_price

def calculate_opening_range(df, minutes=30):
    """Calculates Opening Range High/Low and a narrative."""
    if df.empty:
        return np.nan, np.nan, "No data."

    start_time = df['Datetime'].min()
    # FIX: Use pandas.Timedelta for compatibility with pandas.Timestamp
    end_time = start_time + pd.Timedelta(minutes=minutes)
    
    opening_range_df = df[df['Datetime'] < end_time]
    if opening_range_df.empty:
        return np.nan, np.nan, "No opening range data."
        
    orl = opening_range_df['Low'].min()
    orh = opening_range_df['High'].max()
    
    rest_of_day_df = df[df['Datetime'] >= end_time]
    if rest_of_day_df.empty:
        return orh, orl, "Market closed after opening range."

    # Check for breaks
    broke_low = rest_of_day_df['Low'].min() < orl
    broke_high = rest_of_day_df['High'].max() > orh
    
    time_broke_low_series = rest_of_day_df[rest_of_day_df['Low'] < orl]['Datetime']
    time_broke_high_series = rest_of_day_df[rest_of_day_df['High'] > orh]['Datetime']

    time_broke_low = time_broke_low_series.min() if not time_broke_low_series.empty else pd.NaT
    time_broke_high = time_broke_high_series.min() if not time_broke_high_series.empty else pd.NaT

    # Build the narrative
    narrative = ""
    if not broke_low and not broke_high:
        narrative = "Price remained entirely inside the Opening Range (Balance Day)."
    elif broke_high and not broke_low:
        narrative = f"Price held the ORL as support and broke out above ORH at {time_broke_high.strftime('%H:%M')}, trending higher."
    elif not broke_high and broke_low:
        narrative = f"Price held the ORH as resistance and broke down below ORL at {time_broke_low.strftime('%H:%M')}, trending lower."
    elif broke_high and broke_low:
        if pd.isna(time_broke_low) or pd.isna(time_broke_high):
             narrative = "Price broke both ORH and ORL, but timing data is incomplete."
        elif time_broke_low < time_broke_high:
            narrative = f"Price broke below ORL at {time_broke_low.strftime('%H:%M')}, then reversed and broke above ORH at {time_broke_high.strftime('%H:%M')}."
        else:
            narrative = f"Price broke above ORH at {time_broke_high.strftime('%H:%M')}, then reversed and broke below ORL at {time_broke_low.strftime('%H:%M')}."
            
    return orh, orl, narrative

def find_key_volume_events(df, count=3):
    """Finds the top N volume candles and describes their context."""
    if df.empty:
        return []
    hod = df['High'].max()
    lod = df['Low'].min()
    sorted_by_vol = df.sort_values(by='Volume', ascending=False)
    top_events = sorted_by_vol.head(count)
    
    events_list = []
    for index, row in top_events.iterrows():
        time = row['Datetime'].strftime('%H:%M')
        price = row['Close']
        vol = row['Volume']
        
        # Build context narrative
        action_parts = []
        if row['High'] >= hod:
            action_parts.append("Set High-of-Day")
        if row['Low'] <= lod:
            action_parts.append("Set Low-of-Day")
        
        if row['Close'] > row['Open']:
            action_parts.append("Strong Up-Bar")
        elif row['Close'] < row['Open']:
            action_parts.append("Strong Down-Bar")
        else:
            action_parts.append("Neutral Bar")
            
        brief_action = " | ".join(action_parts)
        
        formatted_string = f"{time} @ ${price:.2f} (Vol: {vol:,.0f}) - [{brief_action}]"
        events_list.append(formatted_string)
        
    return events_list

def get_vwap_interaction(df, vwap_series):
    """Analyzes how price interacted with VWAP."""
    if df.empty or vwap_series.isnull().all():
        return "N/A"
    crosses = ((df['Close'] > vwap_series) & (df['Close'].shift(1) < vwap_series)) | \
              ((df['Close'] < vwap_series) & (df['Close'].shift(1) > vwap_series))
    num_crosses = crosses.sum()
    
    if num_crosses > 4:
        return "Crossed multiple times"
    elif (df['Low'] > vwap_series).all():
        return "Support"
    elif (df['High'] < vwap_series).all():
        return "Resistance"
    else:
        return "Mixed (acted as both support and resistance)"

# --- Streamlit App Layout ---
st.set_page_config(page_title="Intraday Analysis Processor", layout="wide")
st.title("Intraday Analysis Processor")
st.caption("Fetches 5-minute data and performs objective intraday analysis for all selected tickers.")

# --- Sidebar Controls ---
st.sidebar.header("Controls")

# Allow user to pick which tickers to display;
selected_tickers = st.sidebar.multiselect(
    "Select tickers to process",
    options=TICKERS,
    default=TICKERS 
)

# Add a date picker
selected_date = st.sidebar.date_input(
    "Select Date", 
    dt.date.today() - dt.timedelta(days=1) # Default to yesterday
)

if st.sidebar.button("Fetch & Process Data"):
    if not selected_tickers:
        st.warning("Please select at least one ticker to process.")
    else:
        with st.spinner(f"Fetching and processing data for {len(selected_tickers)} tickers..."):
            
            # 1. Fetch data for all selected tickers (for cache)
            all_data_df = fetch_intraday_data(selected_tickers, selected_date, interval="5m")

            if all_data_df.empty:
                st.error(f"No data found for any tickers on {selected_date}. It may be a weekend or holiday.")
            else:
                # --- NEW: String builder for copy-paste ---
                full_analysis_text = []

                # Loop through each selected ticker and build its analysis string
                for ticker in selected_tickers:
                    
                    df_ticker = all_data_df[all_data_df['Ticker'] == ticker.upper()].copy()
                    
                    if df_ticker.empty:
                        st.warning(f"No data found for {ticker} on {selected_date}.")
                        continue
                    
                    df_ticker.reset_index(drop=True, inplace=True)
                    
                    try:
                        # Perform all analysis calculations
                        open_price = df_ticker['Open'].iloc[0]
                        close_price = df_ticker['Close'].iloc[-1]
                        hod_price = df_ticker['High'].max()
                        hod_time_str = df_ticker.loc[df_ticker['High'].idxmax(), 'Datetime'].strftime('%H:%M')
                        lod_price = df_ticker['Low'].min()
                        lod_time_str = df_ticker.loc[df_ticker['Low'].idxmin(), 'Datetime'].strftime('%H:%M')
                        
                        vwap_series = calculate_vwap(df_ticker)
                        session_vwap_final = vwap_series.iloc[-1]
                        poc, vah, val = calculate_volume_profile(df_ticker)
                        orh, orl, or_narrative = calculate_opening_range(df_ticker)
                        key_volume_events = find_key_volume_events(df_ticker)
                        
                        close_vs_vwap = "Above" if close_price > session_vwap_final else "Below"
                        vwap_interaction = get_vwap_interaction(df_ticker, vwap_series)

                        # Build the string for this ticker
                        ticker_summary = f"""
Data Extraction Summary: {ticker} | {selected_date}
==================================================

1. Session Extremes & Timing:
   - Open: ${open_price:.2f}
   - Close: ${close_price:.2f}
   - High of Day (HOD): ${hod_price:.2f} (Set at {hod_time_str})
   - Low of Day (LOD): ${lod_price:.2f} (Set at {lod_time_str})

2. Volume Profile (Value References):
   - Point of Control (POC): ${poc:.2f} (Highest volume traded)
   - Value Area High (VAH): ${vah:.2f}
   - Value Area Low (VAL): ${val:.2f}

3. Key Intraday Volume Events:
"""
                        for event in key_volume_events:
                            ticker_summary += f"   - {event}\n"

                        ticker_summary += f"""
4. VWAP Relationship:
   - Session VWAP: ${session_vwap_final:.2f}
   - Close vs. VWAP: {close_vs_vwap}
   - Key Interactions: VWAP primarily acted as {vwap_interaction}.

5. Opening Range Analysis (First 30 Mins):
   - Opening Range: ${orl:.2f} - ${orh:.2f}
   - Outcome Narrative: {or_narrative}
"""
                        full_analysis_text.append(ticker_summary)

                    except Exception as e:
                        st.error(f"An error occurred during analysis for {ticker}: {e}")
                        st.exception(e)

                # After the loop, display the combined text in a code block with a copy button
                if full_analysis_text:
                    st.header("Combined Analysis for AI")
                    st.info("Click the copy icon in the top-right of the box below to copy all text.")
                    
                    # Join all individual ticker summaries into one block
                    final_text_to_copy = "\n\n".join(full_analysis_text)
                    
                    st.code(final_text_to_copy, language="text")