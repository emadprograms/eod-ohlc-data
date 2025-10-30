import sqlite3
import os

DATABASE_FILE = "analysis_database.db"

def create_database():
    """Creates the SQLite database and the necessary tables if they don't exist."""
    
    if os.path.exists(DATABASE_FILE):
        print(f"Database file '{DATABASE_FILE}' already exists.")
        # Optional: Add logic here if you want to modify existing tables instead
        # For this final version, we assume a clean start.
        # return 
        
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        print("Database connected.")

        # --- Create 'stocks' table (SIMPLIFIED) ---
        # Stores the static historical notes and the AI's dynamic "living document" JSON
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS stocks (
            ticker TEXT PRIMARY KEY,
            historical_level_notes TEXT,      -- Your critical, static historical context
            company_overview_card_json TEXT,  -- The AI's full 6-part JSON output (Living Document)
            last_updated TEXT                 -- Last date the AI updated the JSON
        )
        """)
        print("Table 'stocks' created or already exists.")

        # --- Create 'data_archive' table (Unchanged) ---
        # Stores the raw 5-minute summary text and parsed data for historical reference
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS data_archive (
            archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            date TEXT,
            raw_text_summary TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            poc REAL,
            vah REAL,
            val REAL,
            vwap REAL,
            orl REAL,
            orh REAL,
            UNIQUE(ticker, date) -- Prevent duplicate entries for the same day
        )
        """)
        print("Table 'data_archive' created or already exists.")

        # --- Create 'market_context' table ---
        # Stores the single, global "Economy Card"
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS market_context (
            context_id INTEGER PRIMARY KEY CHECK (context_id = 1), -- Ensures only one row
            economy_card_json TEXT,
            last_updated TEXT
        )
        """)
        print("Table 'market_context' created or already exists.")

        # --- Initialize the single row for the economy card ---
        cursor.execute("""
        INSERT OR IGNORE INTO market_context (context_id, economy_card_json, last_updated)
        VALUES (1, NULL, NULL)
        """)
        print("Initialized market_context row.")

        conn.commit()
        print("Database schema created successfully.")
        
        conn.commit()
        print("Database schema created successfully.")

    except sqlite3.Error as e:
        print(f"An error occurred: {e}")
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")

if __name__ == "__main__":
    create_database()

