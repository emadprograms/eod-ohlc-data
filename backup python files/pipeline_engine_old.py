import sqlite3
import os

DATABASE_FILE = "analysis_database.db"

# SQL for the 'stocks' table (The "Company File")
# This is the FINAL schema for the "Single Living Document" workflow.
# It holds the static context AND the AI's full "living document".
SQL_CREATE_STOCKS_TABLE = """
CREATE TABLE IF NOT EXISTS stocks (
    ticker TEXT PRIMARY KEY,
    
    -- STATIC CONTEXT (Set by Human in "Static Context Editor")
    company_description TEXT,
    sector TEXT,
    analyst_target REAL,
    insider_activity_summary TEXT,
    historical_level_notes TEXT,
    upcoming_catalysts TEXT,
    
    -- DYNAMIC AI OUTPUT (The "Living Document", updated daily by AI in Workflow #1)
    company_overview_card_json TEXT, -- This is the full 6-part "Market Note" JSON

    -- METADATA
    last_updated TEXT
);
"""

# SQL for the 'data_archive' table (Unchanged)
# This is the "dumb" archive of raw 5-min data summaries. The AI never reads this.
SQL_CREATE_ARCHIVE_TABLE = """
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
    orh REAL
);
"""

def create_database():
    """
Signature: create_database()
Description:
Connects to the SQLite database file and creates the 'stocks' and 'data_archive'
tables based on the final "Single Living Document" architecture.
This script should be run once after deleting any old database files.
"""
    if os.path.exists(DATABASE_FILE):
        print(f"Database file '{DATABASE_FILE}' already exists.")
        print("Please delete the old database file before running this setup script to ensure the correct schema.")
        return

    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        print("Creating 'stocks' table (for Static Context & Living Document)...")
        cursor.execute(SQL_CREATE_STOCKS_TABLE)
        
        print("Creating 'data_archive' table (for Raw 5-min Summaries)...")
        cursor.execute(SQL_CREATE_ARCHIVE_TABLE)
        
        conn.commit()
        print("\nDatabase and tables created successfully!")
        print(f"File '{DATABASE_FILE}' is ready.")

    except sqlite3.Error as e:
        print(f"An SQLite error occurred: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")

if __name__ == "__main__":
    create_database()

