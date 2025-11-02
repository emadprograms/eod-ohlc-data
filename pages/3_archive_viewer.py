import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

DATABASE_FILE = "analysis_database.db"
ETF_LIST = ["SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "VIX", "USO", "UNG"]

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    try:
        return sqlite3.connect(DATABASE_FILE)
    except sqlite3.Error as e:
        st.error(f"Database connection error: {e}")
        return None

def get_categories_for_date(date_str):
    """Fetches all unique categories (tickers) from the data_archive table for a specific date."""
    conn = get_db_connection()
    if conn:
        try:
            query = "SELECT DISTINCT ticker FROM data_archive WHERE date = ? ORDER BY ticker"
            df = pd.read_sql_query(query, conn, params=(date_str,))
            return df['ticker'].tolist()
        except Exception as e:
            st.error(f"Error fetching categories for date: {e}")
            return []
        finally:
            conn.close()
    return []

def get_entries_for_date_and_categories(date_str, categories):
    """Fetches all entries for a given date and list of categories."""
    if not categories:
        return pd.DataFrame()
    
    conn = get_db_connection()
    if conn:
        try:
            query = f"""
                SELECT *
                FROM data_archive
                WHERE date = ? AND ticker IN ({','.join('?' for _ in categories)})
                ORDER BY ticker;
            """
            params = [date_str] + categories
            df = pd.read_sql_query(query, conn, params=params)
            return df
        except Exception as e:
            st.error(f"Error fetching entries: {e}")
            return pd.DataFrame()
        finally:
            conn.close()
    return pd.DataFrame()


# --- Streamlit App ---

st.set_page_config(page_title="Archive Viewer", layout="wide")
st.title("📚 Archive Viewer")
st.write("Browse and review saved entries for a specific date.")

# --- 1. Date Selection ---
selected_date = st.date_input("1. Select a Date to Review", value=datetime.now())
date_str = selected_date.strftime('%Y-%m-%d')

# --- 2. Fetch and Classify Categories for the selected date ---
categories_for_date = get_categories_for_date(date_str)

if not categories_for_date:
    st.info(f"No entries found in the archive for {date_str}.")
    st.stop()

# --- Classification Logic ---
news_categories = [
    cat for cat in categories_for_date if 
    cat.startswith('news_') or "Briefing" in cat or "Summary" in cat
]
etf_categories = [cat for cat in categories_for_date if cat in ETF_LIST]
stock_categories = [
    cat for cat in categories_for_date 
    if cat not in news_categories and cat not in etf_categories
]

# --- 3. UI for Filtering by Type ---
st.write("### 2. Filter by Type")
filter_option = st.radio(
    "Filter by type:",
    options=['All', 'News', 'Stocks', 'ETFs'],
    horizontal=True,
    label_visibility="collapsed"
)

categories_to_show = []
if filter_option == 'All':
    categories_to_show = categories_for_date
elif filter_option == 'News':
    categories_to_show = news_categories
elif filter_option == 'Stocks':
    categories_to_show = stock_categories
elif filter_option == 'ETFs':
    categories_to_show = etf_categories

if not categories_to_show:
    st.info(f"No '{filter_option}' entries found for {date_str}.")
else:
    st.write("### 3. Select Categories to View")
    # Multi-select with all options pre-selected by default
    selected_categories = st.multiselect(
        "Categories:",
        options=categories_to_show,
        default=categories_to_show,
        label_visibility="collapsed"
    )

    if selected_categories:
        with st.spinner(f"Fetching entries for {date_str}..."):
            entries_df = get_entries_for_date_and_categories(date_str, selected_categories)
            
            st.divider()
            st.write(f"### Displaying {len(entries_df)} Entries for {date_str}")

            if not entries_df.empty:
                for index, row in entries_df.iterrows():
                    # Clean up the display name for news items
                    display_name = row['ticker'].replace('news_', '').replace('-', ' ').replace('_', ' ')
                    expander_title = f"{display_name}"
                    
                    with st.expander(expander_title):
                        st.code(row['raw_text_summary'], language=None)
            else:
                st.warning("No entries found for the selected categories on this date.")
    else:
        st.info("Select one or more categories to display their entries.")
