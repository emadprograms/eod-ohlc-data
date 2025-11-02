import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import os
import shutil
import json

DATABASE_FILE = "analysis_database.db"
ETF_LIST = ["SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "VIX", "USO", "UNG"]

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    try:
        return sqlite3.connect(DATABASE_FILE)
    except sqlite3.Error as e:
        st.error(f"Database connection error: {e}")
        return None

def get_categories_for_date_range(start_date, end_date):
    """Fetches all unique categories (tickers) from the data_archive table for a specific date range."""
    conn = get_db_connection()
    if conn:
        try:
            query = "SELECT DISTINCT ticker FROM data_archive WHERE date BETWEEN ? AND ? ORDER BY ticker"
            df = pd.read_sql_query(query, conn, params=(start_date, end_date))
            return df['ticker'].tolist()
        except Exception as e:
            st.error(f"Error fetching categories for date range: {e}")
            return []
        finally:
            conn.close()
    return []

def get_entries_for_date_range_and_categories(start_date, end_date, categories):
    """Fetches all entries for a given date range and list of categories."""
    if not categories:
        return pd.DataFrame()
    
    conn = get_db_connection()
    if conn:
        try:
            query = f"""
                SELECT *
                FROM data_archive
                WHERE date BETWEEN ? AND ? AND ticker IN ({','.join('?' for _ in categories)})
                ORDER BY date DESC, ticker;
            """
            params = [start_date, end_date] + categories
            df = pd.read_sql_query(query, conn, params=params)
            return df
        except Exception as e:
            st.error(f"Error fetching entries: {e}")
            return pd.DataFrame()
        finally:
            conn.close()
    return pd.DataFrame()

def create_database_snapshot():
    """Copies the current database to a timestamped file in the backups folder."""
    source_db = DATABASE_FILE
    backup_dir = "database_backups"
    
    if not os.path.exists(source_db):
        return None, f"Source database '{source_db}' not found."

    try:
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        backup_filename = f"analysis_database_{timestamp}.db"
        backup_path = os.path.join(backup_dir, backup_filename)
        
        shutil.copy2(source_db, backup_path) # copy2 preserves metadata
        return backup_path, None
    except Exception as e:
        return None, str(e)

def get_table_data(table_name, start_date=None, end_date=None):
    """Fetches data from a specific table, with optional date filtering."""
    conn = get_db_connection()
    if conn:
        try:
            # Basic validation to prevent SQL injection
            if table_name not in ['stocks', 'data_archive', 'market_context']:
                raise ValueError("Invalid table name provided.")
            
            query = f"SELECT * FROM {table_name}"
            params = []

            if start_date and end_date:
                date_column = ''
                if table_name == 'data_archive':
                    date_column = 'date'
                elif table_name in ['stocks', 'market_context']:
                    date_column = 'last_updated'
                
                if date_column:
                    query += f" WHERE {date_column} BETWEEN ? AND ?"
                    params.extend([start_date, end_date])

            query += " ORDER BY 1 DESC" # Order by the first column, typically the ID or primary key
            df = pd.read_sql_query(query, conn, params=params)
            return df
        except Exception as e:
            st.error(f"Error fetching data for table '{table_name}': {e}")
            return pd.DataFrame()
        finally:
            conn.close()
    return pd.DataFrame()

def delete_entry_by_id(entry_id):
    """Deletes an entry from the data_archive table by its archive_id."""
    conn = get_db_connection()
    if conn:
        try:
            c = conn.cursor()
            c.execute("DELETE FROM data_archive WHERE archive_id = ?", (entry_id,))
            conn.commit()
            return c.rowcount > 0  # Return True if a row was deleted
        except Exception as e:
            st.error(f"Error deleting entry: {e}")
            return False
        finally:
            conn.close()
    return False

# --- Streamlit App ---

st.set_page_config(page_title="Data Manager", layout="wide")
st.title("📦 Data Manager")
st.write("Browse, review, and manage saved entries in the database.")

# --- Create Tabs ---
tab_viewer, tab_admin = st.tabs(["Viewer", "Admin"])

# --- Viewer Tab ---
with tab_viewer:
    st.header("Database Viewer")
    
    view_table = st.selectbox(
        "Select data to view:",
        options=['data_archive', 'stocks', 'market_context'],
        format_func=lambda x: {
            'data_archive': 'Archived Text (News, etc.)',
            'stocks': 'Stock Overviews',
            'market_context': 'Global Economy Card'
        }.get(x, x)
    )

    st.divider()

    # --- UI for 'data_archive' ---
    if view_table == 'data_archive':
        st.write("#### 1. Select Date Range")
        col1, col2 = st.columns(2)
        with col1:
            from_date = st.date_input("From", value=datetime.now(), key="viewer_from")
        with col2:
            to_date = st.date_input("To", value=datetime.now(), key="viewer_to")

        if from_date > to_date:
            st.error("Error: 'From' date cannot be after 'To' date.")
        else:
            from_date_str = from_date.strftime('%Y-%m-%d')
            to_date_str = to_date.strftime('%Y-%m-%d')
            categories_for_range = get_categories_for_date_range(from_date_str, to_date_str)

            if not categories_for_range:
                st.info(f"No 'data_archive' entries found for the selected date range.")
            else:
                news_categories = [cat for cat in categories_for_range if cat.startswith('news_') or "Briefing" in cat or "Summary" in cat]
                etf_categories = [cat for cat in categories_for_range if cat in ETF_LIST]
                stock_categories = [cat for cat in categories_for_range if cat not in news_categories and cat not in etf_categories]

                st.write("#### 2. Filter by Type")
                filter_option = st.radio("Filter by type:", options=['All', 'News', 'Stocks', 'ETFs'], horizontal=True, label_visibility="collapsed")
                
                categories_to_show = {'All': categories_for_range, 'News': news_categories, 'Stocks': stock_categories, 'ETFs': etf_categories}.get(filter_option, [])

                if not categories_to_show:
                    st.info(f"No '{filter_option}' entries found for the selected date range.")
                else:
                    st.write("#### 3. Select Categories to View")
                    selected_categories = st.multiselect("Categories:", options=categories_to_show, default=categories_to_show, label_visibility="collapsed")
                    if selected_categories:
                        with st.spinner(f"Fetching entries..."):
                            entries_df = get_entries_for_date_range_and_categories(from_date_str, to_date_str, selected_categories)
                            st.write(f"##### Displaying {len(entries_df)} Entries")
                            if not entries_df.empty:
                                for index, row in entries_df.iterrows():
                                    display_name = row['ticker'].replace('news_', '').replace('-', ' ').replace('_', ' ')
                                    with st.expander(f"{display_name} ({row['date']})"):
                                        st.code(row['raw_text_summary'], language=None)

    # --- UI for 'stocks' ---
    elif view_table == 'stocks':
        stock_data = get_table_data('stocks')
        if not stock_data.empty:
            tickers = stock_data['ticker'].tolist()
            selected_tickers = st.multiselect("Select one or more stocks to view:", options=tickers, default=tickers)
            
            if selected_tickers:
                st.divider()
                selected_df = stock_data[stock_data['ticker'].isin(selected_tickers)]
                for index, row in selected_df.iterrows():
                    with st.expander(f"{row['ticker']} (Last Updated: {row['last_updated']})"):
                        try:
                            card_json = json.loads(row['company_overview_card_json'])
                            st.json(card_json)
                        except (json.JSONDecodeError, TypeError):
                            st.write("Could not display JSON. Raw data:")
                            st.code(row['company_overview_card_json'])
        else:
            st.info("No data found in the 'stocks' table.")

    # --- UI for 'market_context' ---
    elif view_table == 'market_context':
        context_data = get_table_data('market_context')
        if not context_data.empty:
            st.subheader("Global Economy Card")
            last_updated = context_data['last_updated'].iloc[0]
            st.caption(f"Last Updated: {last_updated}")
            try:
                card_json = json.loads(context_data['economy_card_json'].iloc[0])
                st.json(card_json)
            except (json.JSONDecodeError, TypeError):
                st.write("Could not display JSON. Raw data:")
                st.code(context_data['economy_card_json'].iloc[0])
        else:
            st.info("No data found in the 'market_context' table.")


# --- Admin Tab ---
with tab_admin:
    st.header("Database Administration")
    
    # --- Snapshot Section ---
    st.info("Create a point-in-time snapshot of the entire database. This is useful for creating backups.", icon="📸")
    if st.button("Create Database Snapshot", use_container_width=True):
        with st.spinner("Creating snapshot..."):
            backup_path, error = create_database_snapshot()
            if error:
                st.error(f"Snapshot failed: {error}")
            else:
                st.success(f"✅ Snapshot created successfully at `{backup_path}`")
    
    st.divider()

    # --- Database Inspector ---
    st.subheader("Database Inspector")
    
    admin_col1, admin_col2, admin_col3 = st.columns(3)
    with admin_col1:
        table_to_view = st.selectbox("Select Table", options=['stocks', 'data_archive', 'market_context'])
    with admin_col2:
        admin_from_date = st.date_input("From", value=None, key="admin_from")
    with admin_col3:
        admin_to_date = st.date_input("To", value=None, key="admin_to")

    # Date range validation
    date_filter_active = admin_from_date and admin_to_date
    if date_filter_active and admin_from_date > admin_to_date:
        st.error("'From' date cannot be after 'To' date.")
    else:
        from_str = admin_from_date.strftime('%Y-%m-%d') if admin_from_date else None
        to_str = admin_to_date.strftime('%Y-%m-%d') if admin_to_date else None

        with st.spinner(f"Loading '{table_to_view}' table..."):
            table_df = get_table_data(table_to_view, from_str, to_str)
            if not table_df.empty:
                st.dataframe(table_df, use_container_width=True)
            else:
                st.warning(f"The '{table_to_view}' table is currently empty or no data matches the filter.")

    st.divider()
    
    st.subheader("Delete an Entry from 'data_archive'")
    st.write("Use the `archive_id` from the `data_archive` table above to select an entry to delete.")
    
    del_col1, del_col2 = st.columns([1, 3])
    with del_col1:
        entry_id_to_delete = st.number_input("Enter Archive ID to Delete", min_value=1, step=1, value=None)
    
    with del_col2:
        st.write("") 
        st.write("")
        if st.button("Delete Entry", type="primary"):
            if entry_id_to_delete:
                if 'confirm_delete' not in st.session_state:
                    st.session_state.confirm_delete = False
                if st.session_state.confirm_delete:
                    if delete_entry_by_id(entry_id_to_delete):
                        st.success(f"✅ Successfully deleted entry with ID: {entry_id_to_delete}")
                        st.session_state.confirm_delete = False
                        st.rerun()
                    else:
                        st.error("Failed to delete the entry. It may have already been removed.")
                else:
                    st.session_state.confirm_delete = True
                    st.warning(f"You are about to delete entry with ID {entry_id_to_delete}. Click 'Delete Entry' again to confirm.")
            else:
                st.error("Please enter a valid Archive ID.")
