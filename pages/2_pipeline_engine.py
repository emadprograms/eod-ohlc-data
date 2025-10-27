import streamlit as st
import sqlite3
import os
import re
import json
import time
import requests
import pandas as pd
from datetime import date
from deepdiff import DeepDiff # Import DeepDiff

# --- Constants ---
DATABASE_FILE = "analysis_database.db"
# Model name confirmed from your 'check_models.py' output
MODEL_NAME = "gemini-2.5-pro" 
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent"

API_KEYS = [
    "AIzaSyAqpeu5F69PkcggYFjRk5saI-NqEu6sK_0",
    "AIzaSyB9c_F5ma0zWzkILWjGKj9EnSFLQpd-zKw",
    "AIzaSyAxg5Keaofj9EGmUB5llDL2aRMEqqAcv5g",
    "AIzaSyCaQdJRth9rS3cxSSpPvyqjO2GodFEDIgw",
]

# This is the 6-part "Company Overview Card" JSON template.
# This is the "Living Document" that the AI will update daily.
DEFAULT_COMPANY_OVERVIEW_JSON = """
{
  "marketNote": "Company Name (TICKER)",
  "confidence": "Medium - Awaiting new data",
  "screener_briefing": "No analysis yet. Awaiting first data run.",
  "basicContext": {
    "tickerDate": "TICKER | YYYY-MM-DD",
    "sector": "e.g., Technology",
    "companyDescription": "e.g., Designs and sells...",
    "priceTrend": "e.g., Describe current trend...",
    "recentCatalyst": "e.g., Earnings next week, Post-CPI drift, etc."
  },
  "technicalStructure": {
    "tradingRange": "e.g., $150 support - $160 resistance",
    "support": "Key support levels",
    "resistance": "Key resistance levels",
    "pattern": "e.g., Consolidation, Breakout, etc.",
    "keyAction": "How price interacted with key levels today",
    "volumeMomentum": "Volume confirmation/denial of key level action"
  },
  "fundamentalContext": {
    "valuation": "e.g., Premium, Fair, Discounted",
    "analystSentiment": "e.g., Avg target $180",
    "insiderActivity": "e.g., Consistent net selling",
    "peerPerformance": "e.g., Outperforming sector"
  },
  "behavioralSentiment": {
    "buyerVsSeller": "Describe balance of power based on key level interaction",
    "emotionalTone": "e.g., Confident, Anxious, Complacent",
    "newsReaction": "e.g., Absorbed bad news well"
  },
  "biasStrategy": {
    "bias": "e.g., Bullish, Bearish, Neutral",
    "triggersBullish": "e.g., Breakout above $160",
    "triggersBearish": "e.g., Failure below $150",
    "riskZones": "e.g., Thesis fails below $145",
    "timingAwareness": "e.g., Fed meeting next week"
  },
  "sentimentSummary": [
    "Your high-level summary line 1.",
    "Your high-level summary line 2."
  ]
}
""" # Updated field descriptions in template for clarity

# --- Logger Class ---
class AppLogger:
    """Helper to log messages to the Streamlit UI (inside an expander) or console."""
    def __init__(self, st_container=None):
        self.st_container = st_container
        
    def log(self, message):
        """Logs a message to the appropriate output."""
        if self.st_container:
            # Use markdown for potentially better formatting of changes
            self.st_container.markdown(message, unsafe_allow_html=True) 
        else:
            print(message)

# --- 1. Parsing Function (Unchanged) ---
def parse_raw_summary(raw_text: str) -> dict:
    """
    Parses the structured text summary from the 'Processor' app into a dictionary
    for database storage. This is Step 1: "Parse".
    """
    data = {"raw_text_summary": raw_text}
    
    # Helper function for safe regex search
    def find_value(pattern, text, type_conv=float):
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                # Group 1 is the price/value (excluding the $)
                return type_conv(match.group(1).replace(',', '')) 
            except ValueError:
                return None
        return None

    # --- Extracting data using regex based on the Streamlit output format ---
    
    data['ticker'] = find_value(r"Summary: (\w+)", raw_text, type_conv=str)
    data['date'] = find_value(r"\| ([\d\-]+)", raw_text, type_conv=str)
    data['open'] = find_value(r"Open: \$([\d\.]+)", raw_text)
    data['close'] = find_value(r"Close: \$([\d\.]+)", raw_text)
    data['high'] = find_value(r"High of Day \(HOD\): \$([\d\.]+)", raw_text)
    data['low'] = find_value(r"Low of Day \(LOD\): \$([\d\.]+)", raw_text)
    data['poc'] = find_value(r"Point of Control \(POC\): \$([\d\.]+)", raw_text)
    data['vah'] = find_value(r"Value Area High \(VAH\): \$([\d\.]+)", raw_text)
    data['val'] = find_value(r"Value Area Low \(VAL\): \$([\d\.]+)", raw_text)
    data['vwap'] = find_value(r"Session VWAP: \$([\d\.]+)", raw_text)
    or_match = re.search(r"Opening Range: \$([\d\.]+) - \$([\d\.]+)", raw_text)
    if or_match:
        orl_match = re.search(r"Opening Range: \$([\d\.]+) -", raw_text)
        orh_match = re.search(r" - \$([\d\.]+)", raw_text)
        data['orl'] = float(orl_match.group(1)) if orl_match and orl_match.group(1) else None
        data['orh'] = float(orh_match.group(1)) if orh_match and orh_match.group(1) else None
    else:
        data['orl'] = None
        data['orh'] = None
    return data

# --- 2. Gemini API Call Function (Unchanged) ---
def call_gemini_api(prompt: str, api_key: str, system_prompt: str, logger: AppLogger, max_retries=5) -> str:
    """
    Calls the Gemini API with the specified prompt and a specific API key.
    Implements exponential backoff and retries.
    """
    
    if not api_key:
        logger.log("Error: No API Key was provided for this call.")
        return None
        
    gemini_api_url = f"{API_URL}?key={api_key}"
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
    }
    headers = {'Content-Type': 'application/json'}
    
    for i in range(max_retries):
        try:
            # Increased timeout for the larger Pro model and complex prompts
            response = requests.post(gemini_api_url, headers=headers, data=json.dumps(payload), timeout=60) 
            
            if response.status_code != 200:
                if response.status_code in [429, 500, 503] and i < max_retries - 1:
                    logger.log(f"API Error {response.status_code}. Retrying in {2**i}s... (Attempt {i+1}/{max_retries})")
                    time.sleep(2**i)
                    continue
                else:
                    logger.log(f"Final API Error {response.status_code}: {response.text}")
                    return None
            
            result = response.json()
            
            # Defensive coding to check nested structure before accessing 'text'
            candidates = result.get("candidates")
            if candidates and len(candidates) > 0:
                content = candidates[0].get("content")
                if content:
                    parts = content.get("parts")
                    if parts and len(parts) > 0:
                         text_part = parts[0].get("text")
                         if text_part is not None: # Check if text exists
                            return text_part.strip()

            # If any part of the structure is missing or text is None, log error
            logger.log(f"Error: API response format is invalid or empty. Response: {json.dumps(result, indent=2)}") 
            return None


        except requests.exceptions.RequestException as e:
            logger.log(f"API Request failed: {e}. Retrying in {2**i}s... (Attempt {i+1}/{max_retries})")
            time.sleep(2**i)
            
    logger.log(f"Error: Failed to get response from Gemini API after {max_retries} retries.")
    return None


# --- 3. Workflow #1: The "Daily Note Generator" (FINAL "Single Document" Version) ---
def update_stock_note(ticker_to_update: str, new_raw_text: str, api_key_to_use: str, logger: AppLogger):
    """
    This is the FINAL "Note Update Engine" (Workflow #1).
    It generates the NEW 6-part "Company Overview Card" JSON by synthesizing
    yesterday's card, the static context, and today's 5-min data, with a focus on levels.
    """
    logger.log(f"--- Starting update for {ticker_to_update} ---")
    
    conn = None
    try:
        # --- Connect to the database ---
        conn = sqlite3.connect(DATABASE_FILE)
        # Use Row factory to get results as dictionaries
        conn.row_factory = sqlite3.Row 
        cursor = conn.cursor()

        # --- Step 1: Parse ---
        logger.log("1. Parsing raw summary...")
        parsed_data = parse_raw_summary(new_raw_text)
        trade_date = parsed_data.get('date', date.today().isoformat())
        
        if not parsed_data.get('ticker'):
            logger.log("Error: Could not parse Ticker from raw text. Aborting.")
            return

        # --- Step 2: Load (to data_archive) ---
        logger.log("2. Archiving raw data...")
        archive_columns = [
            'ticker', 'date', 'raw_text_summary', 'open', 'high', 'low', 'close',
            'poc', 'vah', 'val', 'vwap', 'orl', 'orh'
        ]
        archive_values = tuple(parsed_data.get(col, None) for col in archive_columns)
        
        cursor.execute(f"""
            INSERT OR REPLACE INTO data_archive ({', '.join(archive_columns)})
            VALUES ({', '.join(['?'] * len(archive_columns))})
        """, archive_values)
        conn.commit()
        logger.log("   ...archived successfully.")

        # --- Step 3: Fetch Static Context AND Yesterday's "Company Overview Card" ---
        logger.log("3. Fetching Static Context & Yesterday's 'Company Overview Card'...")
        cursor.execute("SELECT * FROM stocks WHERE ticker = ?", (ticker_to_update,))
        company_data = cursor.fetchone() # This is now a dict-like object
        
        previous_overview_card_dict = {} # Keep the dictionary version for comparison
        static_context_dict = {}

        if company_data:
            # Load the static context from the database
            static_context_dict = {
                "sector": company_data["sector"],
                "companyDescription": company_data["company_description"],
                "analystSentiment": company_data["analyst_target"],
                "insiderActivity": company_data["insider_activity_summary"],
                "historical_level_notes": company_data["historical_level_notes"],
                "upcoming_catalysts": company_data["upcoming_catalysts"]
            }
            
            # Load yesterday's "Company Overview Card" (the full 6-part JSON)
            if company_data['company_overview_card_json']:
                try:
                    # Store as dictionary for comparison later
                    previous_overview_card_dict = json.loads(company_data['company_overview_card_json']) 
                    logger.log("   ...found yesterday's 'Company Overview Card'.")
                except json.JSONDecodeError:
                    logger.log(f"   ...Warning: Could not parse yesterday's card for {ticker_to_update}. AI will use default template.")
                    previous_overview_card_dict = json.loads(DEFAULT_COMPANY_OVERVIEW_JSON.replace("TICKER", ticker_to_update))
            else:
                logger.log(f"   ...No prior 'Company Overview Card' found for {ticker_to_update}. AI will create a new one.")
                previous_overview_card_dict = json.loads(DEFAULT_COMPANY_OVERVIEW_JSON.replace("TICKER", ticker_to_update))
        else:
            logger.log(f"   ...No static context found for {ticker_to_update}. AI will use default template.")
            # We still need to run, so initialize a new card
            previous_overview_card_dict = json.loads(DEFAULT_COMPANY_OVERVIEW_JSON.replace("TICKER", ticker_to_update))


        # --- Step 4: Build FINAL "Note Generator" Prompt (The "Brain") ---
        logger.log("4. Building 'Note Generator' Prompt for Gemini AI...")
        
        # System persona for the "Note Update Engine"
        note_generator_system_prompt = (
            "You are an expert market structure and participant motivation analyst. "
            "You focus ONLY on how price interacts with key structural levels. " # Emphasize level focus
            "You are the 'Database Manager' for a portfolio manager. "
            "You will be given [Static Context] (human-set fundamental/historical data, ESPECIALLY historical_level_notes), "
            "[Yesterday's Company Overview Card] (the full 6-part 'living document' defining the current structure), "
            "and [Today's New Price Action Summary] (objective 5-min data).\n"
            "Your task is to synthesize ALL THREE data sources to generate the NEW, UPDATED 'Company Overview Card' JSON for today. "
            "Prioritize maintaining the established structural narrative unless key levels are decisively broken. " # Add priority
            "Your output MUST be a single, valid JSON object."
        )
        
        # --- FINAL PROMPT with ENHANCED ANTI-RECENCY BIAS & LEVEL FOCUS ---
        prompt = f"""
        [Static Context for {ticker_to_update}]
        (Pay SPECIAL attention to historical_level_notes for MAJOR support/resistance.)
        {json.dumps(static_context_dict, indent=2)}

        [Yesterday's Company Overview Card for {ticker_to_update}] 
        (This defines the ESTABLISHED structure, bias, and key levels. Update cautiously.) 
        {json.dumps(previous_overview_card_dict, indent=2)}

        [Today's New Price Action Summary]
        (Objective 5-minute data: HOD, LOD, POC, VWAP, Opening Range action.)
        {new_raw_text}

        [Your Task for Today: {trade_date}]
        Generate the NEW, UPDATED "Company Overview Card" JSON. Focus primarily on how today's action interacted with established levels.
        
        **CRITICAL INSTRUCTIONS (LEVELS ARE PARAMOUNT):**
        1.  **PRESERVE STATIC FIELDS:** You *must* copy `fundamentalContext`, `sector`, and `companyDescription` **UNCHANGED** from [Yesterday's Card] / [Static Context].
        2.  **RESPECT ESTABLISHED STRUCTURE & LEVELS:**
            * **Bias:** Maintain the `bias` from [Yesterday's Card] unless [Today's Action] *decisively breaks AND closes beyond* a MAJOR support/resistance level defined in yesterday's `riskZones` or `historical_level_notes`. Consolidation within the established range does NOT change the bias.
            * **Major S/R:** Keep the MAJOR `support`/`resistance` levels from `historical_level_notes` and [Yesterday's Card] unless today's action *clearly invalidates* them (strong break, close beyond, high volume confirmation).
            * **Minor S/R:** Acknowledge *new* intraday levels (LOD, HOD, POC, VWAP) in `tradingRange` and `keyAction`, describing how price reacted to them (e.g., "Tested LOD support at $152 and held," "Rejected from HOD resistance at $158"). DO NOT automatically promote these to major levels in the main `support`/`resistance` fields.
            * **Pattern:** Only update the `technicalStructure.pattern` if today's action *completes* or *decisively breaks* the pattern described in [Yesterday's Card].
            * **Interpret Contextually:** Consolidation near highs after an uptrend = Bullish continuation unless MAJOR support fails. Consolidation near lows after downtrend = Bearish continuation unless MAJOR resistance breaks.
        3.  **UPDATE DYNAMIC FIELDS (Level-Focused):**
            * **`technicalStructure.keyAction`:** Describe ONLY how price interacted with the most important pre-defined S/R levels or pattern boundaries today. (e.g., "Successfully defended major $150 support mentioned in historical notes," "Failed breakout above yesterday's $160 resistance trigger").
            * **`technicalStructure.volumeMomentum`:** Describe ONLY how volume confirmed or denied the `keyAction` *at those specific levels*. (e.g., "High volume confirmed the defense of $150 support," "Low volume on the test of $160 resistance suggests weak conviction").
            * **Other Dynamics:** Update `confidence`, `screener_briefing`, `basicContext` (date, trend, catalyst), `behavioralSentiment`, `biasStrategy` (triggers/risk zones based on today's action near levels), and `sentimentSummary` based on the level-focused interpretation, respecting Instruction #2.

        **Detailed Update Logic (Level-Focused):**
        1.  Update `basicContext` (date, trend, catalyst) reflecting today's action *relative to established levels*.
        2.  Update `technicalStructure` (`tradingRange`, `pattern`, `keyAction`, `volumeMomentum`, minor S/R changes) focusing *only* on level interaction. Preserve major S/R unless invalidated.
        3.  Update `behavioralSentiment` based on *who won the battle at the key levels* today.
        4.  Update `biasStrategy` (`bias`, `triggers`, `riskZones`) respecting Instruction #2. Bias changes *only* on decisive level breaks. Triggers might adjust based on today's action near levels.
        5.  Calculate `confidence` (Top Level) with rationale, based on how well today's action *respected* the established structure and levels. High confidence = structure held/confirmed. Low confidence = structure decisively broke.
        6.  Write `screener_briefing` (Top Level) focusing on the most critical level interaction and its implication for tomorrow.
        7.  Update `sentimentSummary` reflecting the level-focused analysis and continuity/change.

        [Output Format Constraint]
        Output ONLY the single, complete, updated JSON object. Ensure it is valid JSON. Do not include ```json markdown.
        """

        # --- Step 5: Ask AI ---
        key_index = API_KEYS.index(api_key_to_use) if api_key_to_use in API_KEYS else -1
        logger.log(f"5. Calling Gemini AI using key #{key_index + 1}...")
        
        ai_response_text = call_gemini_api(prompt, api_key_to_use, note_generator_system_prompt, logger)
        
        if not ai_response_text:
            logger.log("Error: No response from AI. Aborting update.")
            return

        # --- Step 6: Analyze (Parse AI's JSON Response) ---
        logger.log("6. Received new 'Company Overview Card' JSON from AI. Parsing...") 
        
        # Clean the response (remove markdown ```json ... ``` tags)
        json_match = re.search(r"```json\s*([\s\S]+?)\s*```", ai_response_text)
        if json_match:
            ai_response_text = json_match.group(1)
            
        ai_response_text = ai_response_text.strip()
        new_overview_card_dict = None # This will be the new dictionary

        try:
            full_parsed_json = json.loads(ai_response_text)
            
            if isinstance(full_parsed_json, list) and len(full_parsed_json) > 0:
                new_overview_card_dict = full_parsed_json[0]
                logger.log("   ...AI returned a list. Extracted first object.")
            elif isinstance(full_parsed_json, dict):
                new_overview_card_dict = full_parsed_json
            else:
                raise json.JSONDecodeError("Parsed JSON is not a dictionary or a non-empty list.", ai_response_text, 0)

        except json.JSONDecodeError as e:
            logger.log(f"Error: AI response was not valid JSON. Aborting update. Error: {e}\nResponse:\n{ai_response_text}")
            return

        # Validate the new JSON
        required_keys = ['marketNote', 'confidence', 'screener_briefing', 'basicContext', 'technicalStructure', 'fundamentalContext', 'behavioralSentiment', 'biasStrategy', 'sentimentSummary']
        if not all(key in new_overview_card_dict for key in required_keys):
            # Try to salvage by adding missing keys with default values if possible? Or just fail. Let's fail for now.
            missing = [k for k in required_keys if k not in new_overview_card_dict]
            logger.log(f"Error: AI response is missing required keys: {', '.join(missing)}. Aborting update. Response: {json.dumps(new_overview_card_dict, indent=2)}")
            return
            
        logger.log("   ...JSON parsed and validated successfully.")
        
        # --- Log the specific changes ---
        logger.log("   ...Comparing yesterday's card to today's AI-generated card:")
        try:
            # Exclude fields we expect to change daily anyway for cleaner diff log? Maybe not needed with table format.
            diff = DeepDiff(previous_overview_card_dict, new_overview_card_dict, 
                            ignore_order=True, report_repetition=True, view='tree')
                            # Example: exclude=['basicContext.tickerDate']) 
            
            if not diff:
                logger.log("   ...No changes detected between yesterday's card and today's AI output.")
            else:
                changes_log = "   **Changes detected:**\n"
                
                # Check for changed values
                if 'values_changed' in diff:
                    changes_log += "| Field Path | Old Value | New Value |\n"
                    changes_log += "|---|---|---|\n"
                    for change in diff['values_changed']:
                        # Use simpler path representation
                        formatted_path = change.path(output_format=' いや ').replace("root['", "").replace("']", "").replace("['", ".").replace("'", "")
                        
                        old_val = change.t1
                        new_val = change.t2
                        # Handle potential long strings or lists/dicts in values for display
                        old_val_str = json.dumps(old_val) if isinstance(old_val, (dict, list)) else str(old_val)
                        new_val_str = json.dumps(new_val) if isinstance(new_val, (dict, list)) else str(new_val)
                        # Truncate long values for readability in the log table
                        old_val_str = (old_val_str[:50] + '...') if len(old_val_str) > 53 else old_val_str
                        new_val_str = (new_val_str[:50] + '...') if len(new_val_str) > 53 else new_val_str
                        
                        changes_log += f"| `{formatted_path}` | `{old_val_str}` | `{new_val_str}` |\n"
                
                # Optionally log added/removed items if needed (simpler format)
                if 'dictionary_item_added' in diff:
                     changes_log += "\n   **Fields Added:** " + ", ".join([item.path() for item in diff['dictionary_item_added']]) + "\n"
                if 'dictionary_item_removed' in diff:
                     changes_log += "\n   **Fields Removed:** " + ", ".join([item.path() for item in diff['dictionary_item_removed']]) + "\n"
                # Add handling for other diff types like 'iterable_item_added/removed' if necessary

                logger.log(changes_log)

        except Exception as diff_e:
            logger.log(f"   ...Error comparing JSONs with DeepDiff: {diff_e}. Falling back to basic log.")
            # Fallback log
            logger.log(f"   ...AI Confidence: `{new_overview_card_dict.get('confidence', 'N/A')}`")
            summary = new_overview_card_dict.get('screener_briefing', 'N/A')
            logger.log(f"   ...AI Screener Briefing: `{summary}`")

        # --- Step 7: Update (stocks table) ---
        logger.log("7. Saving the NEW 'Company Overview Card' to database...") 
        today_str = date.today().isoformat()
        
        # Convert the *validated* object back to a string for saving
        new_overview_card_json_string = json.dumps(new_overview_card_dict, indent=2)
        
        # This query *only* updates the "Company Overview Card" and metadata 
        cursor.execute("""
            UPDATE stocks 
            SET 
                company_overview_card_json = ?,
                last_updated = ?
            WHERE 
                ticker = ?
        """, (new_overview_card_json_string, today_str, ticker_to_update))
        
        # Check if the update worked (in case it was a new ticker)
        if cursor.rowcount == 0:
             logger.log(f"   ...Ticker `{ticker_to_update}` not found in 'stocks' table. It must be initialized in the 'Static Context Editor' first.")
             # Note: We still archived the data, but we can't update the overview card. 
        else:
            conn.commit()
            logger.log(f"--- Successfully updated `{ticker_to_update}` for {today_str} ---")

    except sqlite3.Error as e:
        logger.log(f"An SQLite error occurred: `{e}`. Check if 'database_setup.py' was run.")
    except Exception as e:
        logger.log(f"An unexpected error occurred: `{e}`")
    finally:
        if conn:
            conn.close()

# --- 4. Workflow #2: The Screener Engine (FINAL "Single Document" Version) ---
def run_screener(market_condition: str, confidence_filter: str, api_key_to_use: str, logger: AppLogger):
    """
    This screener is CORRECTED. It programmatically filters by confidence,
    then passes the ENTIRE 6-part JSON card for each finalist to the AI.
    """
    logger.log("--- Starting FINAL Trade Screener Engine ---")
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        # Step 1: Filter/Compile List - Programmatically extract data
        
        # This query gets the FULL "Company Overview Card" JSON 
        # for all stocks that match the confidence filter.
        query = """
            SELECT 
                ticker, 
                company_overview_card_json
            FROM stocks 
            WHERE company_overview_card_json IS NOT NULL 
              AND company_overview_card_json != '' 
              AND json_valid(company_overview_card_json) -- Ensure JSON is valid before trying to extract
        """
        params = []
        
        if confidence_filter != "All":
            # Filter by the new top-level 'confidence' field
            # Use LIKE to match "High - [Rationale]"
            query += " AND json_extract(company_overview_card_json, '$.confidence') LIKE ?"
            params.append(f"{confidence_filter}%")
            
        cursor.execute(query, params)
        # List of (ticker, full_json_string) tuples
        candidate_rows = cursor.fetchall() 

        if not candidate_rows:
            logger.log(f"Error: No valid 'Company Overview Cards' found matching filter '{confidence_filter}'.")
            return "No candidates found matching your filter."
        
        logger.log(f"1. Found {len(candidate_rows)} candidates matching filter '{confidence_filter}'.")

        # Step 2: Build FINAL "Smarter Ranking" Prompt
        logger.log("2. Building 'Smarter Ranking' Prompt for Gemini AI...")
        
        # --- Prompt asks for rationale for EACH ---
        screener_system_prompt = (
            "You are an expert market structure analyst focused ONLY on participant motivation (trapped/committed). "
            "You will be given the 'Overall Market Condition' and a list of 'Candidate Stocks', each with its FULL 'Company Overview Card' (a 6-part JSON). " 
            "Your job is to read the *entire card* for each candidate to understand its full context (fundamentals, technicals, bias). "
            "Then, rank them from 1 (best) down, based ONLY on the clarity of the participant imbalance and alignment with the Market Condition. "
            "The #1 setup must offer the highest probability edge for an opening trade tomorrow. "
            "For EACH candidate in your ranked list, provide a 1-line concise rationale focusing on *who* is motivated/trapped. " 
            "Output ONLY the ranked list as plain text (e.g., '1. TICKER: Rationale...\\n2. TICKER: Rationale...')." 
        )
        
        # We are sending the FULL JSON card for each candidate.
        candidate_list_text = ""
        valid_candidates_count = 0
        for ticker, full_json_string in candidate_rows:
            try:
                # Try parsing to ensure it's valid before sending
                parsed_json = json.loads(full_json_string)
                formatted_json = json.dumps(parsed_json, indent=2)
                
                candidate_list_text += f"\n--- Candidate: {ticker} ---\n"
                candidate_list_text += formatted_json
                candidate_list_text += f"\n--- End Candidate: {ticker} ---\n"
                valid_candidates_count += 1
            except json.JSONDecodeError:
                logger.log(f"   ...Skipping candidate {ticker} due to invalid JSON in database.")
                continue # Skip this candidate

        if valid_candidates_count == 0:
             logger.log(f"Error: Although rows were found, none contained valid JSON for the screener.")
             return "No valid candidate data found for screener."

        logger.log(f"   ...Sending {valid_candidates_count} valid candidates to the AI.")

        # --- UPDATED ACTION IN PROMPT ---
        prompt = f"""
        [Data]
        - **Overall Market Condition:** "{market_condition}"
        - **Candidate Stocks (Full JSON "Company Overview Cards"):** {candidate_list_text}

        [Action]
        Provide the ranked list (plain text), starting with #1. Include a 1-line rationale for EACH stock. 
        """
        
        # --- Step 3: Ask AI ---
        key_index = API_KEYS.index(api_key_to_use) if api_key_to_use in API_KEYS else -1
        logger.log(f"3. Calling Gemini AI using key #{key_index + 1}...")
        
        ranked_list_text = call_gemini_api(prompt, api_key_to_use, screener_system_prompt, logger)
        
        if not ranked_list_text:
            logger.log("Error: No response from AI. Aborting screener.")
            return "AI failed to return a ranked list."

        logger.log("4. Received ranked list from AI.")
        logger.log("--- SCREENER COMPLETE ---")
        # Format the output slightly better for display if it's just plain text lines
        # Assuming AI returns lines like "1. TICKER: Rationale"
        formatted_ranked_list = ranked_list_text.replace('\n', '\n\n') # Add double newline for markdown
        return formatted_ranked_list


    except sqlite3.Error as e:
        # Check for specific JSON errors if possible
        if "malformed JSON" in str(e):
             logger.log(f"An SQLite JSON error occurred: {e}. Check the data in 'Company Overview Card Editor' for invalid JSON.")
        else:
            logger.log(f"An SQLite error occurred: {e}. Check if 'database_setup.py' was run.")
        return f"Database Error: {e}"
    except Exception as e:
        logger.log(f"An unexpected error occurred: {e}")
        return f"Unexpected Error: {e}"
    finally:
        if conn:
            conn.close()


# --- 5. Streamlit Application UI ---

st.set_page_config(page_title="Analyst Pipeline Engine (FINAL)", layout="wide")
st.title("Analyst Pipeline Engine (Single Company Overview Card)") 

# --- Helper Function to get all tickers ---
def get_all_tickers_from_db():
    if not os.path.exists(DATABASE_FILE):
        return []
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        # Ensure we only get tickers, even if other data is null
        df_tickers = pd.read_sql_query("SELECT DISTINCT ticker FROM stocks ORDER BY ticker ASC", conn)
        return df_tickers['ticker'].tolist()
    except Exception as e:
        st.error(f"Error fetching tickers: {e}")
        return []
    finally:
        if conn:
            conn.close()

# --- Helper to safely parse JSON and extract a field ---
def extract_json_field(json_string, field_path):
    if not json_string or pd.isna(json_string):
        return None
    try:
        data = json.loads(json_string)
        # Navigate the path (e.g., 'biasStrategy.bias')
        keys = field_path.split('.')
        value = data
        for key in keys:
            # Check if intermediate key exists and is a dictionary
            if value is None or not isinstance(value, dict): 
                return None # Path does not exist
            value = value.get(key)
        
        # Join list-based summaries
        if isinstance(value, list):
            # Ensure all items are strings before joining
            return " ".join(map(str, value)) 
        # Safely convert non-string primitives to string
        if value is not None and not isinstance(value, str):
             return str(value)
        return value
    except (json.JSONDecodeError, TypeError, AttributeError): # Added AttributeError
        return "JSON Err"

# --- Define Tabs ---
tab_editor, tab_runner, tab_screener, tab_battle_card_viewer = st.tabs([ 
    "Company Overview Card Editor", 
    "Pipeline Runner (Daily)", 
    "Trade Screener",
    "Battle Card Viewer" 
])

# --- TAB 1: Company Overview Card Editor (FINAL - All-in-One) ---
with tab_editor:
    st.header("Company Overview Card Editor (Your 'Human-in-the-Loop' View)")
    st.caption("Use this tab to set TRULY STATIC context AND to review/edit the AI's 'Company Overview Card'.") 

    if not os.path.exists(DATABASE_FILE):
        st.error(f"Database file '{DATABASE_FILE}' not found. Run 'final_database_setup.py' first.")
    else:
        all_tickers = get_all_tickers_from_db()
        
        col1, col2 = st.columns([2,1])
        with col1:
            options = [""] + all_tickers
            # Use session state to preserve selection across reruns
            if 'selected_ticker_editor' not in st.session_state:
                st.session_state['selected_ticker_editor'] = ""
            selected_ticker = st.selectbox("Select Ticker to Edit:", options=options, key="selected_ticker_editor")
        with col2:
            new_ticker_input = st.text_input("Or Add New Ticker:", placeholder="e.g., MSFT", key="new_ticker_input_editor")
            
        ticker_to_edit = new_ticker_input.upper() if new_ticker_input else selected_ticker
        
        # Ensure only one is active
        if new_ticker_input and selected_ticker:
             st.warning("Please clear either 'Select Ticker' or 'Add New Ticker'.")
             ticker_to_edit = "" # Prevent editing if both are set

        if ticker_to_edit:
            st.markdown("---")
            st.subheader(f"Editing Context for: ${ticker_to_edit}")
            
            conn = None
            try:
                conn = sqlite3.connect(DATABASE_FILE)
                conn.row_factory = sqlite3.Row # Get dicts
                cursor = conn.cursor()
                
                # Load existing data
                cursor.execute("SELECT * FROM stocks WHERE ticker = ?", (ticker_to_edit,))
                data = cursor.fetchone()
                
                # Set defaults for static context
                default_static_data = {
                    "company_description": "", "sector": "", "analyst_target": 0.0,
                    "insider_activity_summary": "", "historical_level_notes": "", "upcoming_catalysts": ""
                }
                if data:
                    default_static_data.update(dict(data))
                
                # Set default for the JSON company overview card 
                default_json_text = DEFAULT_COMPANY_OVERVIEW_JSON.replace("TICKER", ticker_to_edit)
                if data and data["company_overview_card_json"]:
                    try:
                        # Attempt to pretty-print if valid JSON
                        loaded_json = json.loads(data["company_overview_card_json"])
                        default_json_text = json.dumps(loaded_json, indent=2)
                    except json.JSONDecodeError:
                         # Fallback to raw text if not valid JSON
                        default_json_text = data["company_overview_card_json"] 

                # --- Section 1: Static Context Editor (The Form) ---
                with st.expander("Section 1: Static Context Editor (Your Long-Term Memory)", expanded=True): # Expand by default
                    # Use unique keys based on the ticker to avoid state issues when switching tickers
                    form_key = f"static_context_form_{ticker_to_edit}"
                    with st.form(key=form_key):
                        st.caption("Set the TRULY STATIC context here. The AI reads this but will not change it.")
                        # Use value for form elements
                        sector_val = st.text_input("Sector:", value=default_static_data["sector"], key=f"sector_{ticker_to_edit}")
                        analyst_target_val = st.number_input("Analyst Target Price:", value=default_static_data["analyst_target"], key=f"analyst_target_{ticker_to_edit}", format="%.2f", step=0.01)
                        company_description_val = st.text_area("Company Description:", value=default_static_data["company_description"], key=f"company_description_{ticker_to_edit}", height=100)
                        insider_activity_val = st.text_area("Insider Activity Summary:", value=default_static_data["insider_activity_summary"], key=f"insider_activity_{ticker_to_edit}", height=100)
                        historical_notes_val = st.text_area("Historical Level Notes (CRITICAL):", value=default_static_data["historical_level_notes"], key=f"historical_notes_{ticker_to_edit}", height=150,
                                      help="e.g., 'Failed at $180 last month', 'Major support at $150'")
                        catalysts_val = st.text_area("Upcoming Catalysts:", value=default_static_data["upcoming_catalysts"], key=f"catalysts_{ticker_to_edit}", height=100)
                        
                        submitted_static = st.form_submit_button("Save Static Context", use_container_width=True)
                        
                        if submitted_static:
                            try:
                                # Use INSERT OR REPLACE (UPSERT)
                                cursor.execute("""
                                    INSERT INTO stocks (
                                        ticker, company_description, sector, analyst_target, 
                                        insider_activity_summary, historical_level_notes, upcoming_catalysts, last_updated
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                    ON CONFLICT(ticker) DO UPDATE SET
                                        company_description = excluded.company_description,
                                        sector = excluded.sector,
                                        analyst_target = excluded.analyst_target,
                                        insider_activity_summary = excluded.insider_activity_summary,
                                        historical_level_notes = excluded.historical_level_notes,
                                        upcoming_catalysts = excluded.upcoming_catalysts,
                                        last_updated = excluded.last_updated;
                                """, (
                                    ticker_to_edit, company_description_val, sector_val, 
                                    analyst_target_val, insider_activity_val, 
                                    historical_notes_val, catalysts_val, date.today().isoformat()
                                ))
                                
                                conn.commit()
                                st.success(f"Successfully saved static context for ${ticker_to_edit}!")
                                # Clear the 'new ticker' input if it was used
                                if new_ticker_input: 
                                     st.session_state['new_ticker_input_editor'] = ""
                                st.rerun() # Rerun to refresh the ticker list and clear form state
                            
                            except sqlite3.Error as e:
                                st.error(f"Database error: {e}")
                
                st.markdown("---")

                # --- Section 2: AI's 'Company Overview Card' Editor (The JSON Editor) --- 
                st.subheader("Section 2: AI's 'Company Overview Card' (Editable)") 
                st.caption("This is the AI's 6-part 'Company Overview Card' that it generated. Review it and correct any mistakes before running the screener.")
                
                # Use a unique key for the text_area as well
                json_text_to_edit = st.text_area("Company Overview Card JSON:", value=default_json_text, height=600, key=f"json_editor_{ticker_to_edit}")

                if st.button("Save 'Company Overview Card' (Your Override)", use_container_width=True): 
                    try:
                        # 1. Validate the JSON
                        valid_json = json.loads(json_text_to_edit) 
                        
                        # Re-stringify to ensure consistent formatting
                        json_string_to_save = json.dumps(valid_json, indent=2)

                        # 2. Save to DB (This updates the AI's card)
                        # Ensure the record exists before updating JSON (use UPSERT logic indirectly)
                        cursor.execute("""
                            INSERT INTO stocks (ticker, company_overview_card_json, last_updated)
                            VALUES (?, ?, ?)
                            ON CONFLICT(ticker) DO UPDATE SET
                                company_overview_card_json = excluded.company_overview_card_json,
                                last_updated = excluded.last_updated;
                        """, (ticker_to_edit, json_string_to_save, date.today().isoformat()))
                        
                        conn.commit()
                        st.success(f"Successfully saved (overwrote) 'Company Overview Card' for ${ticker_to_edit}!") 
                        # Force a rerun to ensure the editor reloads the *saved* version
                        st.rerun() 
                    
                    except json.JSONDecodeError:
                        st.error("Invalid JSON: The text could not be parsed. Please check your syntax (commas, quotes, brackets).")
                    except sqlite3.Error as e:
                        st.error(f"Database error: {e}")
                        
            except sqlite3.Error as e:
                st.error(f"Database error: {e}")
            finally:
                if conn:
                    conn.close()

# --- TAB 2: Pipeline Runner (FINAL "Single Document" Version) ---
with tab_runner:
    st.header("Pipeline Runner (Workflow #1 - Daily)")
    st.caption("This is your DAILY task. Paste the full output from the 'Intraday Analysis Processor' app here.")
    st.success("This will have the AI Analyst read your Static Context and yesterday's 'Company Overview Card' to generate the NEW 'Company Overview Card' for today.") 
    st.info(f"Using {len(API_KEYS)} API keys in rotation for rate limit avoidance.")

    raw_text_input = st.text_area("Paste Raw Text Summaries Here:", height=300, placeholder="Paste the entire text block from the other app...")

    if st.button("Run Pipeline Update", use_container_width=True):
        if not raw_text_input:
            st.warning("Please paste the raw text summaries before running.")
        elif not os.path.exists(DATABASE_FILE):
            st.error(f"Database file '{DATABASE_FILE}' not found. Please run 'final_database_setup.py' first.")
        else:
            # --- Start Processing ---
            # Split the text based on the "Data Extraction Summary:" header
            summaries = re.split(r"(Data Extraction Summary:)", raw_text_input)
            processed_summaries = []
            
            # Re-join the header with its content
            if summaries and summaries[0].strip() == "":
                summaries = summaries[1:] 
            for i in range(0, len(summaries), 2):
                if i + 1 < len(summaries):
                    full_summary = summaries[i] + summaries[i+1]
                    processed_summaries.append(full_summary)
            
            if not processed_summaries:
                st.warning("Could not find any 'Data Extraction Summary:' headers in the pasted text.")
            else:
                st.success(f"Found {len(processed_summaries)} summaries to process.")
                log_container = st.expander("Processing Logs", expanded=True)
                logger = AppLogger(st_container=log_container)
                
                total_start_time = time.time()
                
                for i, summary_text in enumerate(processed_summaries):
                    # Parse just to get the ticker
                    ticker = parse_raw_summary(summary_text).get('ticker')
                    if not ticker:
                        logger.log(f"SKIPPING: Could not parse ticker from summary chunk:\n{summary_text[:100]}...")
                        continue
                    
                    try:
                        # Select key for rotation
                        key_to_use = API_KEYS[i % len(API_KEYS)]
                        
                        # --- THIS IS THE FINAL, AUTOMATED FUNCTION ---
                        update_stock_note(ticker, summary_text, key_to_use, logger)
                        
                    except Exception as e:
                        logger.log(f"!!! CRITICAL ERROR updating {ticker}: {e}")
                        
                    # Wait 1 second between calls to respect API rate limits
                    if i < len(processed_summaries) - 1:
                        logger.log(f"   ...waiting 1 second to avoid API rate limits...")
                        time.sleep(1)
                        
                total_end_time = time.time()
                logger.log(f"--- PIPELINE RUN COMPLETE ---")
                logger.log(f"Total time: {total_end_time - total_start_time:.2f} seconds.")
                st.info("Pipeline run complete. Go to the 'Company Overview Card Editor' to review and edit the AI's work.")


# --- TAB 3: Trade Screener (FINAL "Single Document" Version) ---
with tab_screener:
    st.header("Trade Screener (Workflow #2)")
    st.caption("This will filter all 'Company Overview Cards' by 'Confidence', then feed the FULL 6-part JSON card for each finalist to the AI for informed ranking.") 
    st.warning("Make sure you have reviewed and corrected any AI mistakes in the 'Company Overview Card Editor' tab before running this.")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        market_condition_input = st.text_area(
            "Overall Market Condition (Critical Context for AI):", 
            height=150, 
            placeholder="E.g., The SPY closed above its POC for the third day..."
        )
    with col2:
        confidence_filter = st.selectbox(
            "Filter by Confidence:",
            options=["All", "High", "Medium", "Low"],
            help="Filters setups based on the AI's 'confidence' field (e.g., 'High - ...')."
        )

    if st.button("Run Screener", use_container_width=True):
        if not market_condition_input:
            st.warning("Please provide a summary of the Overall Market Condition.")
        elif not os.path.exists(DATABASE_FILE):
            st.error(f"Database file '{DATABASE_FILE}' not found. Please run 'final_database_setup.py' first.")
        else:
            screener_log_container = st.expander("Screener Logs", expanded=True)
            screener_logger = AppLogger(st_container=screener_log_container)
            
            # Always use the first key for the screener (a single call)
            key_to_use = API_KEYS[0] 
            
            with st.spinner("Analyzing all 'Company Overview Cards' and generating ranked list..."): 
                
                # --- This function is now FINAL and sends the FULL card ---
                ranked_result = run_screener(market_condition_input, confidence_filter, key_to_use, screener_logger)
            
            st.markdown("---")
            st.subheader(f"Final Ranked Trade Setups (Confidence: {confidence_filter})")
            # Display the result using st.markdown to render potential newlines correctly
            st.markdown(ranked_result) 

# --- TAB 4: Battle Card Viewer (NEW - Replaces Archive Viewer) ---
with tab_battle_card_viewer:
    st.header("Battle Card Viewer (AI 'Company Overview Card' & Screener Input)") 
    st.caption("Inspect the AI's full analysis and see the exact data sent to the screener.")

    if not os.path.exists(DATABASE_FILE):
        st.error(f"Database file '{DATABASE_FILE}' not found. Run 'final_database_setup.py' first.")
    else:
        # Fetch tickers within this tab's scope
        conn_viewer = None
        all_tickers_bc = []
        try:
             conn_viewer = sqlite3.connect(DATABASE_FILE)
             # Only fetch tickers that actually have a JSON card
             df_tickers_bc = pd.read_sql_query("SELECT DISTINCT ticker FROM stocks WHERE company_overview_card_json IS NOT NULL AND company_overview_card_json != '' ORDER BY ticker ASC", conn_viewer) 
             all_tickers_bc = df_tickers_bc['ticker'].tolist()
        except Exception as e:
            st.error(f"Error fetching tickers for viewer: {e}")
        finally:
             if conn_viewer:
                 conn_viewer.close()

        if not all_tickers_bc:
            st.warning("No tickers found with Overview Cards. Run the 'Pipeline Runner' or initialize in the Editor.")
        else:
            options_bc = [""] + all_tickers_bc
            # Use session state for viewer selection as well
            if 'selected_ticker_bc' not in st.session_state:
                st.session_state['selected_ticker_bc'] = ""
            selected_ticker_bc = st.selectbox("Select Ticker to View:", options=options_bc, key="selected_ticker_bc")

            if selected_ticker_bc:
                conn_data = None
                try:
                    conn_data = sqlite3.connect(DATABASE_FILE)
                    # Fetch only the JSON for the selected ticker
                    cursor = conn_data.cursor()
                    cursor.execute("SELECT company_overview_card_json FROM stocks WHERE ticker = ?", (selected_ticker_bc,))
                    data_row = cursor.fetchone()

                    if data_row and data_row[0]:
                        json_string = data_row[0]
                        parsed_overview_json = None # For storing the parsed dict
                        
                        # --- Section 1: Full 'Company Overview Card' JSON --- 
                        st.subheader(f"Full 'Company Overview Card' JSON for ${selected_ticker_bc}") 
                        try:
                            # Pretty print the JSON
                            parsed_overview_json = json.loads(json_string)
                            st.json(parsed_overview_json, expanded=True) # Expand by default for viewing
                        except json.JSONDecodeError:
                            st.error("Could not parse the stored JSON. Displaying raw text:")
                            st.code(json_string, language='text')

                        st.markdown("---")
                        
                        # --- Section 2: Data Sent to Screener AI ---
                        st.subheader("Data Sent to Screener AI for this Ticker")
                        st.caption("This is the exact information the screener AI uses for ranking (extracted from the JSON above).")
                        
                        # Use the already parsed JSON if available
                        data_dict_for_extraction = parsed_overview_json if parsed_overview_json else {}
                        
                        # Define helper function inside, or ensure it's available
                        def get_screener_field(data_dict, path, default="N/A"):
                            keys = path.split('.')
                            value = data_dict
                            try:
                                for key in keys:
                                    # Navigate safely
                                    if not isinstance(value, dict): return default 
                                    value = value.get(key)
                                    if value is None: return default
                                # Format lists
                                if isinstance(value, list):
                                    return " ".join(map(str, value))
                                return str(value) if value is not None else default
                            except:
                                return default

                        # Extract the relevant fields for display
                        screener_data_to_display = {
                            "Confidence": get_screener_field(data_dict_for_extraction, 'confidence'),
                            "Screener Briefing": get_screener_field(data_dict_for_extraction, 'screener_briefing'),
                            "Bias": get_screener_field(data_dict_for_extraction, 'biasStrategy.bias'),
                            "Bullish Trigger": get_screener_field(data_dict_for_extraction, 'biasStrategy.triggersBullish'),
                            "Bearish Trigger": get_screener_field(data_dict_for_extraction, 'biasStrategy.triggersBearish'),
                            "Technical Pattern": get_screener_field(data_dict_for_extraction, 'technicalStructure.pattern'),
                            "Key Action": get_screener_field(data_dict_for_extraction, 'technicalStructure.keyAction'),
                            "Valuation": get_screener_field(data_dict_for_extraction, 'fundamentalContext.valuation'),
                            "Analyst Sentiment": get_screener_field(data_dict_for_extraction, 'fundamentalContext.analystSentiment'),
                            "Insider Activity": get_screener_field(data_dict_for_extraction, 'fundamentalContext.insiderActivity'),
                            "Sentiment Summary": get_screener_field(data_dict_for_extraction, 'sentimentSummary') 
                        }
                        
                        # Display as key-value pairs using markdown for clarity
                        for key, value in screener_data_to_display.items():
                             st.markdown(f"**{key}:** `{value}`")

                    else:
                        st.warning(f"No 'Company Overview Card' JSON found for ${selected_ticker_bc}. Run the 'Pipeline Runner'.")

                except sqlite3.Error as e:
                    st.error(f"Database error reading card for {selected_ticker_bc}: {e}")
                finally:
                    if conn_data:
                        conn_data.close()


# --- Command Line Test Example (Unchanged) ---
if __name__ == "__main__":
    
    print("This script is intended to be run with Streamlit:")
    print("streamlit run pipeline_engine.py")

