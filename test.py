import streamlit as st
import requests
import pandas as pd
import sqlite3
import json
import os
import re

# --- Capital.com API Functions ---
def create_session(api_key, identifier, password, logger):
    """Creates a new session with Capital.com and returns tokens."""
    session_url = "https://api-capital.backend-capital.com/api/v1/session"
    headers = {'X-CAP-API-KEY': api_key, 'Content-Type': 'application/json'}
    payload = {"identifier": identifier, "password": password}
    try:
        response = requests.post(session_url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        cst = response.headers.get('CST')
        xst = response.headers.get('X-SECURITY-TOKEN')
        if cst and xst:
            logger.info("Session created successfully.")
            return cst, xst
        else:
            logger.error("Session failed: Tokens not found in response headers.")
            return None, None
    except requests.exceptions.RequestException as e:
        logger.error(f"Session creation request failed: {e}")
        return None, None

def get_current_price(epic, cst, xst, logger):
    """Retrieves the current mid-price for a specific market epic."""
    url = f"https://api-capital.backend-capital.com/api/v1/markets/{epic}"
    headers = {'X-SECURITY-TOKEN': xst, 'CST': cst}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        snapshot = data.get('snapshot', {})
        bid = snapshot.get('bid')
        offer = snapshot.get('offer')
        if bid is not None and offer is not None:
            return (bid + offer) / 2
        else:
            logger.warning(f"Market {epic} found, but price is missing.")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"API Request failed for market details of {epic}: {e}")
        return None

# --- Database Function ---
def get_eod_levels_from_db(logger):
    """Fetches S/R levels from the EOD cards in the database."""
    DATABASE_FILE = "analysis_database.db"
    if not os.path.exists(DATABASE_FILE):
        logger.error(f"Database file not found at: {DATABASE_FILE}")
        return None

    eod_levels = {}
    parsed_count = 0
    failed_tickers = []
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT ticker, company_overview_card_json FROM stocks WHERE company_overview_card_json IS NOT NULL")
        rows = cursor.fetchall()
        total_stocks = len(rows)
        logger.info(f"Found {total_stocks} stocks with EOD cards in the database.")

        for ticker, card_json in rows:
            try:
                card = json.loads(card_json)
                tech_structure = card.get('technicalStructure', {})
                
                support_str = str(tech_structure.get('majorSupport', ''))
                resistance_str = str(tech_structure.get('majorResistance', ''))

                support_match = re.search(r'(\d+\.?\d*)', support_str)
                resistance_match = re.search(r'(\d+\.?\d*)', resistance_str)

                if support_match and resistance_match:
                    support = float(support_match.group(1))
                    resistance = float(resistance_match.group(1))
                    eod_levels[ticker] = {"support": support, "resistance": resistance}
                    parsed_count += 1
                else:
                    if ticker not in failed_tickers: failed_tickers.append(ticker)

            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.warning(f"Could not process card for {ticker}. Error: {e}")
                if ticker not in failed_tickers: failed_tickers.append(ticker)
        
        logger.info(f"Successfully parsed S/R levels for {parsed_count}/{total_stocks} stocks.")
        if failed_tickers:
            logger.warning(f"Failed to parse levels for: {', '.join(failed_tickers)}")
        return eod_levels

    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        return None
    finally:
        if conn:
            conn.close()

# --- Streamlit App UI ---

st.set_page_config(page_title="Proximity Filter Tester", layout="wide")
st.title("Pre-Market Proximity Filter Tester")
st.caption("A tool to test filtering stocks based on their proximity to S/R levels from the EOD database.")

# --- Logger Setup ---
class UILogger:
    def __init__(self, container):
        self.container = container
    def info(self, msg):
        self.container.info(msg)
    def warning(self, msg):
        self.container.warning(msg)
    def error(self, msg):
        self.container.error(msg)

log_container = st.expander("Logs", expanded=True)
logger = UILogger(log_container)

# --- Sidebar Setup ---
with st.sidebar:
    st.header("1. Credentials")
    capital_secrets = st.secrets.get("capital_com", {})
    api_key = capital_secrets.get("X_CAP_API_KEY")
    identifier = capital_secrets.get("identifier")
    password = capital_secrets.get("password")

    if not all([api_key, identifier, password]):
        st.error("Credentials not found in st.secrets.")
        st.stop()
    else:
        st.success("Credentials loaded.")

    st.header("2. Test Parameters")
    eod_data = get_eod_levels_from_db(logger)

    if not eod_data:
        st.error("Could not load EOD data from database. Halting.")
        st.stop()

    st.subheader("EOD Levels Loaded from DB")
    st.json(eod_data)

    proximity_pct_slider = st.slider(
        "Proximity Filter Threshold (%)", 
        min_value=0.1, max_value=10.0, value=2.5, step=0.1, 
        help="Filter for stocks trading within this percentage distance of a major S/R level."
    )

    st.header("3. Actions")
    run_test_button = st.button("Run Proximity Filter Test", use_container_width=True)

# --- Main Application Logic ---
if run_test_button:
    logger.info("--- Starting Proximity Filter Test ---")
    
    with st.spinner("Creating Capital.com session..."):
        cst, xst = create_session(api_key, identifier, password, logger)

    if cst and xst:
        results = []
        processed_count = 0
        kept_count = 0
        
        with st.spinner(f"Fetching prices and filtering {len(eod_data)} tickers..."):
            for ticker, levels in eod_data.items():
                logger.info(f"Processing {ticker}...")
                live_price = get_current_price(ticker, cst, xst, logger)
                
                if live_price is None:
                    logger.warning(f"Could not get live price for {ticker}. Skipping.")
                    continue
                
                processed_count += 1
                support = levels['support']
                resistance = levels['resistance']
                
                dist_to_s = abs(live_price - support)
                dist_to_r = abs(live_price - resistance)
                
                proximity_pct = (min(dist_to_s, dist_to_r) / live_price) * 100
                
                status = "KEEP" if proximity_pct <= proximity_pct_slider else "FILTER"
                if status == "KEEP":
                    kept_count += 1
                
                results.append({
                    "Ticker": ticker,
                    "Status": status,
                    "Proximity (%)": f"{proximity_pct:.2f}",
                    "Live Price": f"${live_price:.2f}",
                    "Support": f"${support:.2f}",
                    "Resistance": f"${resistance:.2f}",
                })
        
        # Store results in session state to persist them
        st.session_state['test_results'] = results
        st.session_state['processed_count'] = processed_count
        st.session_state['kept_count'] = kept_count
        st.session_state['threshold'] = proximity_pct_slider
        st.rerun() # Rerun to display results outside the button block
    else:
        logger.error("Test failed: Could not create a session.")

# --- Display Results Area ---
if 'test_results' in st.session_state:
    st.header("Filter Results")
    
    results = st.session_state['test_results']
    processed_count = st.session_state['processed_count']
    kept_count = st.session_state['kept_count']
    threshold = st.session_state['threshold']

    if results:
        st.success(f"**Test Complete.** Processed {processed_count} tickers with live prices. Found **{kept_count}** stocks matching the **{threshold}%** proximity filter.")
        df_results = pd.DataFrame(results).sort_values(by="Proximity (%)").reset_index(drop=True)
        st.dataframe(df_results, use_container_width=True)
    else:
        st.warning(f"**Test Complete.** Processed {processed_count} tickers, but **none** passed the **{threshold}%** proximity filter. Try increasing the threshold.")
    
    logger.info("--- Test Complete ---")
