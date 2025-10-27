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

# --- NEW, FINAL JSON Structure ---
# This defines the "Company Overview Card" - the single living document.
DEFAULT_COMPANY_OVERVIEW_JSON = """
{
  "marketNote": "Executor's Battle Card: TICKER",
  "confidence": "Medium - Awaiting confirmation",
  "screener_briefing": "AI RULE: Ignore for trade decisions. High-level bias ONLY.",
  "basicContext": {
    "tickerDate": "TICKER | YYYY-MM-DD",
    "sector": "Set in Static Editor",
    "companyDescription": "Set in Static Editor",
    "priceTrend": "AI Updates: Cumulative trend relative to major levels",
    "recentCatalyst": "Set in Static Editor, AI may update if action confirms"
  },
  "technicalStructure": {
    "majorSupport": "AI RULE: READ-ONLY. Update only if decisively broken & confirmed over multiple days.",
    "majorResistance": "AI RULE: READ-ONLY. Update only if decisively broken & confirmed over multiple days.",
    "keyAction": "AI RULE: APPEND today's action relative to major levels to continue the 2-3 day story.",
    "pattern": "AI Updates: Current pattern based on cumulative action.",
    "volumeMomentum": "AI Updates: Volume qualifier for action AT key levels."
  },
  "fundamentalContext": {
    "valuation": "AI RULE: READ-ONLY (Copied from Static)",
    "analystSentiment": "AI RULE: READ-ONLY (Copied from Static)",
    "insiderActivity": "AI RULE: READ-ONLY (Copied from Static)",
    "peerPerformance": "AI Updates: How stock performed relative to peers today."
  },
  "behavioralSentiment": {
    "buyerVsSeller": "AI Updates: Who won the battle at MAJOR levels today?",
    "emotionalTone": "AI Updates: Current market emotion for this stock.",
    "newsReaction": "AI Updates: How did price react to news relative to levels?"
  },
  "openingTradePlan": {
    "planName": "AI Updates: Primary plan (e.g., 'Long from Major Support')",
    "knownParticipant": "AI Updates: Who is confirmed at the level?",
    "expectedParticipant": "AI Updates: Who acts if trigger hits?",
    "trigger": "AI Updates: Specific price action validating this plan.",
    "invalidation": "AI Updates: Price action proving this plan WRONG."
  },
  "alternativePlan": {
    "planName": "AI Updates: Competing plan (e.g., 'Failure at Major Resistance')",
    "scenario": "AI Updates: When does this plan become active?",
    "knownParticipant": "AI Updates: Who is confirmed if scenario occurs?",
    "expectedParticipant": "AI Updates: Who acts if trigger hits?",
    "trigger": "AI Updates: Specific price action validating this plan.",
    "invalidation": "AI Updates: Price action proving this plan WRONG."
  }
}
"""


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


# --- 3. Workflow #1: The "Daily Note Generator" (NEW "Plan-Based" Logic) ---
def update_stock_note(ticker_to_update: str, new_raw_text: str, api_key_to_use: str, logger: AppLogger):
    """
    This is the FINAL "Note Update Engine" (Workflow #1).
    It generates the NEW full "Company Overview Card" JSON (the single living document) 
    by synthesizing yesterday's card, the static context, and today's 5-min data, 
    with a strong focus on established levels and updating trade plans.
    """
    logger.log(f"--- Starting update for {ticker_to_update} ---")
    
    conn = None
    try:
        # --- Connect to the database ---
        conn = sqlite3.connect(DATABASE_FILE)
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
        # ... (Archive logic remains the same) ...
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
        company_data = cursor.fetchone() 
        
        previous_overview_card_dict = {} 
        static_context_dict = {}

        if company_data:
            # Load static context
            static_context_dict = {
                "sector": company_data["sector"], "companyDescription": company_data["company_description"],
                "analystSentiment": company_data["analyst_target"], "insiderActivity": company_data["insider_activity_summary"],
                "historical_level_notes": company_data["historical_level_notes"], "upcoming_catalysts": company_data["upcoming_catalysts"]
            }
            # Load yesterday's card
            if company_data['company_overview_card_json']:
                try:
                    previous_overview_card_dict = json.loads(company_data['company_overview_card_json']) 
                    logger.log("   ...found yesterday's 'Company Overview Card'.")
                except json.JSONDecodeError:
                    logger.log(f"   ...Warning: Could not parse yesterday's card. Using default.")
                    previous_overview_card_dict = json.loads(DEFAULT_COMPANY_OVERVIEW_JSON.replace("TICKER", ticker_to_update))
            else:
                logger.log(f"   ...No prior card found. Creating new one.")
                previous_overview_card_dict = json.loads(DEFAULT_COMPANY_OVERVIEW_JSON.replace("TICKER", ticker_to_update))
        else:
            logger.log(f"   ...No static context or prior card found. Creating new card.")
            previous_overview_card_dict = json.loads(DEFAULT_COMPANY_OVERVIEW_JSON.replace("TICKER", ticker_to_update))


        # --- Step 4: Build REVISED "Note Generator" Prompt (Plan-Based) ---
        logger.log("4. Building REVISED 'Note Generator' Prompt for Gemini AI...")
        
        note_generator_system_prompt = (
            "You are an expert market structure and participant motivation analyst. You focus ONLY on how price interacts with MAJOR structural levels (`majorSupport`, `majorResistance`). "
            "You maintain the 'Company Overview Card' (a JSON 'living document') for a portfolio manager. "
            "You will be given [Static Context] (human-set data, esp. `historical_level_notes`), [Yesterday's Card] (the full JSON document), and [Today's Price Action] (5-min summary).\n"
            "Your task is to generate the NEW, UPDATED 'Company Overview Card' JSON for today. "
            "Prioritize maintaining the established structure unless MAJOR levels are decisively broken. Append to the `keyAction` story. Update the trade plans (`openingTradePlan`, `alternativePlan`) based on today's action relative to MAJOR levels. "
            "Output MUST be a single, valid JSON object."
        )
        
        # --- REVISED PROMPT focusing on Plans and cumulative KeyAction ---
        prompt = f"""
        [Static Context for {ticker_to_update}]
        (Contains MAJOR levels in historical_level_notes.)
        {json.dumps(static_context_dict, indent=2)}

        [Yesterday's Company Overview Card for {ticker_to_update}] 
        (This defines the ESTABLISHED structure, plans, and the story so far in `keyAction`. Update this cautiously based on MAJOR level interaction.) 
        {json.dumps(previous_overview_card_dict, indent=2)}

        [Today's New Price Action Summary]
        (Objective 5-minute data: HOD, LOD, POC, VWAP, Opening Range action.)
        {new_raw_text}

        [Your Task for Today: {trade_date}]
        Generate the NEW, UPDATED "Company Overview Card" JSON, focusing on MAJOR level interactions and updating the trade PLANS.
        
        **CRITICAL INSTRUCTIONS (LEVELS & PLANS ARE PARAMOUNT):**
        1.  **PRESERVE STATIC FIELDS:** Copy `sector`, `companyDescription` from [Static Context]. Copy the entire `fundamentalContext` block **UNCHANGED** from [Yesterday's Card].
        2.  **RESPECT MAJOR LEVELS (`majorSupport`/`majorResistance`):** These are READ-ONLY unless [Today's Action] *decisively breaks AND closes beyond* a level AND this break is confirmed over 2-3 days (as reflected in the evolving `keyAction`). Do NOT change them based on one day's HOD/LOD.
        3.  **UPDATE `keyAction` (The Story):** APPEND today's action to the existing `keyAction` narrative, focusing ONLY on how price interacted with `majorSupport`/`majorResistance` or significant levels mentioned in `historical_level_notes`. Keep the story cumulative over 2-3 days.
        4.  **UPDATE PLANS (`openingTradePlan` / `alternativePlan`):** This is your core task. Based on today's `keyAction` at MAJOR levels:
            * Which plan (opening or alternative) looks more likely for tomorrow?
            * Update `planName`, `trigger`, `invalidation` for BOTH plans based on today's closing price relative to major levels and VWAP/POC.
            * Update `knownParticipant` and `expectedParticipant` based on who showed commitment or got trapped at major levels today.
        5.  **UPDATE OTHER DYNAMIC FIELDS (Supporting the Plans):**
            * Update `technicalStructure` (`pattern`, `volumeMomentum` qualifying level action), `behavioralSentiment` (who won at major levels?), `basicContext` (date, trend, catalyst), `confidence` (based on clarity of plan setup), `screener_briefing` (summarizing the primary plan).
            * Do NOT add minor levels (today's HOD/LOD) to `majorSupport`/`majorResistance`. Mention them only in `keyAction` if relevant to a major level test.

        **Detailed Update Logic (Plan-Focused):**
        1.  Append to `keyAction` describing interaction with MAJOR levels.
        2.  Update BOTH `openingTradePlan` and `alternativePlan` (name, triggers, invalidations, participants) based on today's action relative to MAJOR levels.
        3.  Update supporting dynamic fields (`confidence`, `screener_briefing`, `basicContext`, `technicalStructure`, `behavioralSentiment`, `sentimentSummary`) to reflect the updated plans and `keyAction`.
        4.  Calculate `confidence` rationale based on the clarity of the setup for the *primary* plan (`openingTradePlan`) vs the `alternativePlan`. High confidence = primary plan strongly favored by today's action at major levels. Low = conflicting signals, neither plan clear.

        [Output Format Constraint]
        Output ONLY the single, complete, updated JSON object matching the structure defined in the DEFAULT_COMPANY_OVERVIEW_JSON. Ensure it is valid JSON. Do not include ```json markdown.
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
        
        # ... (Parsing and Validation logic remains largely the same, checking for the NEW required fields based on the template) ...
        # Clean the response
        json_match = re.search(r"```json\s*([\s\S]+?)\s*```", ai_response_text)
        if json_match:
            ai_response_text = json_match.group(1)
        ai_response_text = ai_response_text.strip()
        new_overview_card_dict = None 

        try:
            full_parsed_json = json.loads(ai_response_text)
            # Handle list vs dict response
            if isinstance(full_parsed_json, list) and len(full_parsed_json) > 0:
                new_overview_card_dict = full_parsed_json[0]
                logger.log("   ...AI returned a list. Extracted first object.")
            elif isinstance(full_parsed_json, dict):
                new_overview_card_dict = full_parsed_json
            else:
                raise json.JSONDecodeError("Parsed JSON not dict or non-empty list.", ai_response_text, 0)
        except json.JSONDecodeError as e:
            logger.log(f"Error: AI response not valid JSON. Error: {e}\nResponse:\n{ai_response_text}")
            return
            
        # Validate the new JSON structure (checking top-level and nested plan keys)
        required_top_keys = ['marketNote', 'confidence', 'screener_briefing', 'basicContext', 'technicalStructure', 'fundamentalContext', 'behavioralSentiment', 'openingTradePlan', 'alternativePlan']
        required_plan_keys = ['planName', 'knownParticipant', 'expectedParticipant', 'trigger', 'invalidation'] # 'scenario' only for alternative
        
        missing_keys = [k for k in required_top_keys if k not in new_overview_card_dict]
        if missing_keys:
            logger.log(f"Error: AI response missing required top-level keys: {', '.join(missing_keys)}. Aborting.")
            return
        
        missing_opening_plan_keys = [k for k in required_plan_keys if k not in new_overview_card_dict.get('openingTradePlan', {})]
        if missing_opening_plan_keys:
             logger.log(f"Error: AI response missing required keys in 'openingTradePlan': {', '.join(missing_opening_plan_keys)}. Aborting.")
             return

        # Check alternativePlan keys including 'scenario'
        required_alt_plan_keys = required_plan_keys + ['scenario']
        missing_alt_plan_keys = [k for k in required_alt_plan_keys if k not in new_overview_card_dict.get('alternativePlan', {})]
        if missing_alt_plan_keys:
             logger.log(f"Error: AI response missing required keys in 'alternativePlan': {', '.join(missing_alt_plan_keys)}. Aborting.")
             return

        logger.log("   ...JSON parsed and validated successfully.")
        
        # --- Log the specific changes ---
        # ... (DeepDiff logging remains the same) ...
        logger.log("   ...Comparing yesterday's card to today's AI-generated card:")
        try:
            diff = DeepDiff(previous_overview_card_dict, new_overview_card_dict, 
                            ignore_order=True, report_repetition=True, view='tree')
            if not diff:
                logger.log("   ...No changes detected.")
            else:
                changes_log = "   **Changes detected:**\n"
                if 'values_changed' in diff:
                    changes_log += "| Field Path | Old Value | New Value |\n"
                    changes_log += "|---|---|---|\n"
                    for change in diff['values_changed']:
                        formatted_path = change.path(output_format=' いや ').replace("root['", "").replace("']", "").replace("['", ".").replace("'", "")
                        old_val = change.t1
                        new_val = change.t2
                        old_val_str = json.dumps(old_val) if isinstance(old_val, (dict, list)) else str(old_val)
                        new_val_str = json.dumps(new_val) if isinstance(new_val, (dict, list)) else str(new_val)
                        old_val_str = (old_val_str[:50] + '...') if len(old_val_str) > 53 else old_val_str
                        new_val_str = (new_val_str[:50] + '...') if len(new_val_str) > 53 else new_val_str
                        changes_log += f"| `{formatted_path}` | `{old_val_str}` | `{new_val_str}` |\n"
                # Add logs for added/removed items if needed
                logger.log(changes_log)
        except Exception as diff_e:
            logger.log(f"   ...Error comparing JSONs: {diff_e}. Falling back to basic log.")
        
        # Log key outputs
        logger.log(f"   ...AI Confidence: `{new_overview_card_dict.get('confidence', 'N/A')}`")
        logger.log(f"   ...AI Screener Briefing: `{new_overview_card_dict.get('screener_briefing', 'N/A')}`")
        logger.log(f"   ...AI Opening Plan: `{new_overview_card_dict.get('openingTradePlan', {}).get('planName', 'N/A')}`")


        # --- Step 7: Update (stocks table) ---
        logger.log("7. Saving the NEW 'Company Overview Card' to database...") 
        today_str = date.today().isoformat()
        
        new_overview_card_json_string = json.dumps(new_overview_card_dict, indent=2)
        
        cursor.execute("""
            UPDATE stocks 
            SET company_overview_card_json = ?, last_updated = ?
            WHERE ticker = ?
        """, (new_overview_card_json_string, today_str, ticker_to_update))
        
        if cursor.rowcount == 0:
             logger.log(f"   ...Ticker `{ticker_to_update}` not found. Initialize in 'Static Context Editor'.")
        else:
            conn.commit()
            logger.log(f"--- Successfully updated `{ticker_to_update}` for {today_str} ---")

    # ... (Error handling remains the same) ...
    except sqlite3.Error as e:
        logger.log(f"An SQLite error occurred: `{e}`. Check if 'database_setup.py' was run.")
    except Exception as e:
        logger.log(f"An unexpected error occurred: `{e}`")
    finally:
        if conn:
            conn.close()


# --- 4. Workflow #2: The Screener Engine (REVISED for Plan-Based Ranking) ---
def run_screener(market_condition: str, confidence_filter: str, api_key_to_use: str, logger: AppLogger):
    """
    Screener revised to rank based on the clarity and potential of the 
    'openingTradePlan' vs 'alternativePlan' within the full card context.
    """
    logger.log("--- Starting REVISED Trade Screener Engine ---")
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        # Step 1: Filter/Compile List (Same confidence filter)
        logger.log(f"1. Filtering candidates by Confidence: '{confidence_filter}'...")
        # ... (Query to get full JSON card for filtered tickers remains the same) ...
        query = """
            SELECT ticker, company_overview_card_json
            FROM stocks 
            WHERE company_overview_card_json IS NOT NULL AND company_overview_card_json != '' AND json_valid(company_overview_card_json)
        """
        params = []
        if confidence_filter != "All":
            query += " AND json_extract(company_overview_card_json, '$.confidence') LIKE ?"
            params.append(f"{confidence_filter}%")
        cursor.execute(query, params)
        candidate_rows = cursor.fetchall() 

        if not candidate_rows:
            logger.log(f"Error: No valid cards found matching filter '{confidence_filter}'.")
            return "No candidates found."
        logger.log(f"   ...Found {len(candidate_rows)} candidates.")


        # Step 2: Build REVISED "Smarter Ranking" Prompt (Plan-Focused)
        logger.log("2. Building REVISED 'Smarter Ranking' Prompt for Gemini AI...")
        
        # --- REVISED System Prompt ---
        screener_system_prompt = (
            "You are an expert market structure analyst focused ONLY on participant motivation (trapped/committed) as revealed by price action AT MAJOR LEVELS. "
            "You will be given the 'Overall Market Condition' and a list of 'Candidate Stocks', each with its FULL 'Company Overview Card' JSON (including `openingTradePlan` and `alternativePlan`).\n"
            "Your job is to read the *entire card* for each candidate, paying close attention to the `openingTradePlan`, `alternativePlan`, `keyAction` (the story at major levels), and `confidence`.\n"
            "Then, rank the candidates from 1 (best) down, based ONLY on which stock's PRIMARY (`openingTradePlan`) offers the CLEAREST and HIGHEST PROBABILITY setup for an opening trade tomorrow, considering:\n"
            "   a) Alignment with the Overall Market Condition.\n"
            "   b) Clarity of participant motivation (who is trapped/committed based on `keyAction` at MAJOR levels).\n"
            "   c) Quality of the risk/reward implied by the plan's `trigger` vs `invalidation` relative to MAJOR levels.\n"
            "For EACH candidate in your ranked list, provide a 1-line concise rationale explaining WHY it was ranked there based on the primary plan's clarity/alignment/motivation. "
            "Output ONLY the ranked list as plain text (e.g., '1. TICKER: Rationale...\n2. TICKER: Rationale...')."
        )
        
        # We still send the FULL JSON card.
        candidate_list_text = ""
        valid_candidates_count = 0
        # ... (Loop to build candidate_list_text remains the same) ...
        for ticker, full_json_string in candidate_rows:
             try:
                 parsed_json = json.loads(full_json_string)
                 formatted_json = json.dumps(parsed_json, indent=2)
                 candidate_list_text += f"\n--- Candidate: {ticker} ---\n{formatted_json}\n--- End Candidate: {ticker} ---\n"
                 valid_candidates_count += 1
             except json.JSONDecodeError:
                 logger.log(f"   ...Skipping {ticker} due to invalid JSON.")
                 continue 

        if valid_candidates_count == 0:
             logger.log(f"Error: No valid JSON found for screener.")
             return "No valid candidate data found."
        logger.log(f"   ...Sending {valid_candidates_count} valid candidates.")


        # --- REVISED Action in Prompt ---
        prompt = f"""
        [Data]
        - **Overall Market Condition:** "{market_condition}"
        - **Candidate Stocks (Full JSON "Company Overview Cards"):** {candidate_list_text}

        [Action]
        Provide the ranked list (plain text), starting with #1. Include a 1-line rationale for EACH stock based on its primary opening plan's clarity, alignment, and participant motivation at major levels.
        """
        
        # --- Step 3: Ask AI ---
        key_index = API_KEYS.index(api_key_to_use) if api_key_to_use in API_KEYS else -1
        logger.log(f"3. Calling Gemini AI using key #{key_index + 1}...")
        
        # ... (API call and result handling remain the same) ...
        ranked_list_text = call_gemini_api(prompt, api_key_to_use, screener_system_prompt, logger)
        if not ranked_list_text:
            logger.log("Error: No response from AI.")
            return "AI failed to return a ranked list."
        logger.log("4. Received ranked list from AI.")
        logger.log("--- SCREENER COMPLETE ---")
        formatted_ranked_list = ranked_list_text.replace('\n', '\n\n') 
        return formatted_ranked_list

    # ... (Error handling remains the same) ...
    except sqlite3.Error as e:
        if "malformed JSON" in str(e):
             logger.log(f"SQLite JSON error: {e}. Check data in Editor.")
        else:
            logger.log(f"SQLite error: {e}. Check setup.")
        return f"Database Error: {e}"
    except Exception as e:
        logger.log(f"Unexpected error: {e}")
        return f"Unexpected Error: {e}"
    finally:
        if conn:
            conn.close()


# --- 5. Streamlit Application UI (Adjusted for New Structure) ---

st.set_page_config(page_title="Analyst Pipeline Engine (FINAL)", layout="wide")
st.title("Analyst Pipeline Engine (Plan-Based)") # Updated title

# ... (get_all_tickers_from_db remains the same) ...
def get_all_tickers_from_db():
    # ...
    if not os.path.exists(DATABASE_FILE): return []
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        df_tickers = pd.read_sql_query("SELECT DISTINCT ticker FROM stocks ORDER BY ticker ASC", conn)
        return df_tickers['ticker'].tolist()
    except Exception as e: st.error(f"Error fetching tickers: {e}"); return []
    finally: 
        if conn: conn.close()

# ... (extract_json_field remains the same) ...
def extract_json_field(json_string, field_path):
    # ...
    if not json_string or pd.isna(json_string): return None
    try:
        data = json.loads(json_string)
        keys = field_path.split('.')
        value = data
        for key in keys:
            if value is None or not isinstance(value, dict): return None 
            value = value.get(key)
        if isinstance(value, list): return " ".join(map(str, value)) 
        if value is not None and not isinstance(value, str): return str(value)
        return value
    except: return "JSON Err"


# --- Define Tabs ---
tab_editor, tab_runner, tab_screener, tab_battle_card_viewer = st.tabs([ 
    "Company Overview Card Editor", 
    "Pipeline Runner (Daily)", 
    "Trade Screener",
    "Battle Card Viewer" 
])

# --- TAB 1: Company Overview Card Editor (Unchanged from previous version) ---
with tab_editor:
    # ... (UI logic remains the same: Static context form + JSON editor for the main card) ...
    st.header("Company Overview Card Editor (Your 'Human-in-the-Loop' View)")
    st.caption("Use this tab to set TRULY STATIC context AND to review/edit the AI's 'Company Overview Card'.") 
    # ... (Rest of the editor UI code) ...
    if not os.path.exists(DATABASE_FILE):
        st.error(f"Database file '{DATABASE_FILE}' not found. Run 'final_database_setup.py' first.")
    else:
        all_tickers = get_all_tickers_from_db()
        col1, col2 = st.columns([2,1])
        with col1:
            options = [""] + all_tickers
            if 'selected_ticker_editor' not in st.session_state: st.session_state['selected_ticker_editor'] = ""
            selected_ticker = st.selectbox("Select Ticker to Edit:", options=options, key="selected_ticker_editor")
        with col2:
            new_ticker_input = st.text_input("Or Add New Ticker:", placeholder="e.g., MSFT", key="new_ticker_input_editor")
        ticker_to_edit = new_ticker_input.upper() if new_ticker_input else selected_ticker
        if new_ticker_input and selected_ticker: st.warning("Clear one selection."); ticker_to_edit = "" 
        
        if ticker_to_edit:
            st.markdown("---"); st.subheader(f"Editing Context for: ${ticker_to_edit}")
            conn = None
            try:
                conn = sqlite3.connect(DATABASE_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
                cursor.execute("SELECT * FROM stocks WHERE ticker = ?", (ticker_to_edit,)); data = cursor.fetchone()
                default_static_data = {"company_description": "", "sector": "", "analyst_target": 0.0, "insider_activity_summary": "", "historical_level_notes": "", "upcoming_catalysts": ""}
                if data: default_static_data.update(dict(data))
                default_json_text = DEFAULT_COMPANY_OVERVIEW_JSON.replace("TICKER", ticker_to_edit)
                if data and data["company_overview_card_json"]:
                    try: default_json_text = json.dumps(json.loads(data["company_overview_card_json"]), indent=2)
                    except: default_json_text = data["company_overview_card_json"] 

                with st.expander("Section 1: Static Context Editor", expanded=True):
                    form_key = f"static_context_form_{ticker_to_edit}"
                    with st.form(key=form_key):
                        st.caption("Set TRULY STATIC context.")
                        sector_val = st.text_input("Sector:", value=default_static_data["sector"], key=f"sector_{ticker_to_edit}")
                        analyst_target_val = st.number_input("Analyst Target:", value=default_static_data["analyst_target"], key=f"analyst_target_{ticker_to_edit}", format="%.2f", step=0.01)
                        company_description_val = st.text_area("Description:", value=default_static_data["company_description"], key=f"company_description_{ticker_to_edit}", height=100)
                        insider_activity_val = st.text_area("Insider Activity:", value=default_static_data["insider_activity_summary"], key=f"insider_activity_{ticker_to_edit}", height=100)
                        historical_notes_val = st.text_area("Historical Notes:", value=default_static_data["historical_level_notes"], key=f"historical_notes_{ticker_to_edit}", height=150)
                        catalysts_val = st.text_area("Catalysts:", value=default_static_data["upcoming_catalysts"], key=f"catalysts_{ticker_to_edit}", height=100)
                        submitted_static = st.form_submit_button("Save Static Context", use_container_width=True)
                        if submitted_static:
                            try:
                                cursor.execute("""
                                    INSERT INTO stocks (ticker, company_description, sector, analyst_target, insider_activity_summary, historical_level_notes, upcoming_catalysts, last_updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                    ON CONFLICT(ticker) DO UPDATE SET company_description=excluded.company_description, sector=excluded.sector, analyst_target=excluded.analyst_target, insider_activity_summary=excluded.insider_activity_summary, historical_level_notes=excluded.historical_level_notes, upcoming_catalysts=excluded.upcoming_catalysts, last_updated=excluded.last_updated;
                                """, (ticker_to_edit, company_description_val, sector_val, analyst_target_val, insider_activity_val, historical_notes_val, catalysts_val, date.today().isoformat()))
                                conn.commit(); st.success(f"Static context saved for ${ticker_to_edit}!"); 
                                if new_ticker_input: st.session_state['new_ticker_input_editor'] = ""
                                st.rerun() 
                            except sqlite3.Error as e: st.error(f"DB error: {e}")
                
                st.markdown("---")
                st.subheader("Section 2: AI's 'Company Overview Card' (Editable)") 
                st.caption("Review/correct the AI's full analysis.")
                json_text_to_edit = st.text_area("Company Overview Card JSON:", value=default_json_text, height=600, key=f"json_editor_{ticker_to_edit}")
                if st.button("Save 'Company Overview Card' (Your Override)", use_container_width=True): 
                    try:
                        valid_json = json.loads(json_text_to_edit) 
                        json_string_to_save = json.dumps(valid_json, indent=2)
                        cursor.execute("""
                            INSERT INTO stocks (ticker, company_overview_card_json, last_updated) VALUES (?, ?, ?)
                            ON CONFLICT(ticker) DO UPDATE SET company_overview_card_json=excluded.company_overview_card_json, last_updated=excluded.last_updated;
                        """, (ticker_to_edit, json_string_to_save, date.today().isoformat()))
                        conn.commit(); st.success(f"Overview Card saved for ${ticker_to_edit}!"); st.rerun() 
                    except json.JSONDecodeError: st.error("Invalid JSON.")
                    except sqlite3.Error as e: st.error(f"DB error: {e}")
            except sqlite3.Error as e: st.error(f"DB error: {e}")
            finally: 
                if conn: conn.close()


# --- TAB 2: Pipeline Runner (Unchanged from previous version) ---
with tab_runner:
    # ... (UI and logic remain the same) ...
    st.header("Pipeline Runner (Workflow #1 - Daily)")
    st.caption("Paste output from 'Intraday Analysis Processor'.")
    st.success("AI reads Static Context & yesterday's card, generates NEW card.")
    st.info(f"Using {len(API_KEYS)} API keys.")
    raw_text_input = st.text_area("Paste Raw Text Summaries:", height=300)
    if st.button("Run Pipeline Update", use_container_width=True):
        if not raw_text_input: st.warning("Paste text first.")
        elif not os.path.exists(DATABASE_FILE): st.error("DB not found.")
        else:
            summaries = re.split(r"(Data Extraction Summary:)", raw_text_input)
            processed_summaries = []
            if summaries and summaries[0].strip() == "": summaries = summaries[1:] 
            for i in range(0, len(summaries), 2):
                if i + 1 < len(summaries): processed_summaries.append(summaries[i] + summaries[i+1])
            if not processed_summaries: st.warning("No summaries found.")
            else:
                st.success(f"Found {len(processed_summaries)} summaries.")
                log_container = st.expander("Logs", expanded=True); logger = AppLogger(st_container)
                total_start_time = time.time()
                for i, summary_text in enumerate(processed_summaries):
                    ticker = parse_raw_summary(summary_text).get('ticker')
                    if not ticker: logger.log(f"SKIPPING: No ticker parsed."); continue
                    try:
                        key_to_use = API_KEYS[i % len(API_KEYS)]
                        update_stock_note(ticker, summary_text, key_to_use, logger)
                    except Exception as e: logger.log(f"!!! ERROR updating {ticker}: {e}")
                    if i < len(processed_summaries) - 1: logger.log(f"   ...waiting 1s..."); time.sleep(1)
                total_end_time = time.time()
                logger.log(f"--- PIPELINE COMPLETE ---"); logger.log(f"Time: {total_end_time - total_start_time:.2f}s.")
                st.info("Run complete. Review/edit in 'Editor' tab.")


# --- TAB 3: Trade Screener (Unchanged from previous version) ---
with tab_screener:
    # ... (UI and logic using the run_screener function remain the same) ...
    st.header("Trade Screener (Workflow #2)")
    st.caption("Filters by 'Confidence', feeds FULL cards to AI for ranking.")
    st.warning("Review/correct AI mistakes in 'Editor' tab first.")
    col1, col2 = st.columns([3, 1])
    with col1: market_condition_input = st.text_area("Overall Market Condition:", height=150)
    with col2: confidence_filter = st.selectbox("Filter Confidence:", ["All", "High", "Medium", "Low"])
    if st.button("Run Screener", use_container_width=True):
        if not market_condition_input: st.warning("Provide Market Condition.")
        elif not os.path.exists(DATABASE_FILE): st.error("DB not found.")
        else:
            screener_log_container = st.expander("Logs", expanded=True); screener_logger = AppLogger(screener_log_container)
            key_to_use = API_KEYS[0] 
            with st.spinner("Analyzing cards & ranking..."):
                ranked_result = run_screener(market_condition_input, confidence_filter, key_to_use, screener_logger)
            st.markdown("---"); st.subheader(f"Ranked Setups (Confidence: {confidence_filter})"); st.markdown(ranked_result) 


# --- TAB 4: Battle Card Viewer (Unchanged from previous version) ---
with tab_battle_card_viewer:
    # ... (UI and logic to display full card + screener fields remain the same) ...
    st.header("Battle Card Viewer") 
    st.caption("Inspect AI's full card & data sent to screener.")
    if not os.path.exists(DATABASE_FILE): st.error("DB not found.")
    else:
        conn_viewer = None; all_tickers_bc = []
        try:
             conn_viewer = sqlite3.connect(DATABASE_FILE)
             df_tickers_bc = pd.read_sql_query("SELECT DISTINCT ticker FROM stocks WHERE company_overview_card_json IS NOT NULL AND company_overview_card_json != '' ORDER BY ticker ASC", conn_viewer) 
             all_tickers_bc = df_tickers_bc['ticker'].tolist()
        except Exception as e: st.error(f"Error fetching tickers: {e}")
        finally: 
             if conn_viewer: conn_viewer.close()
        if not all_tickers_bc: st.warning("No cards found.")
        else:
            options_bc = [""] + all_tickers_bc
            if 'selected_ticker_bc' not in st.session_state: st.session_state['selected_ticker_bc'] = ""
            selected_ticker_bc = st.selectbox("Select Ticker:", options=options_bc, key="selected_ticker_bc")
            if selected_ticker_bc:
                conn_data = None
                try:
                    conn_data = sqlite3.connect(DATABASE_FILE)
                    cursor = conn_data.cursor()
                    cursor.execute("SELECT company_overview_card_json FROM stocks WHERE ticker = ?", (selected_ticker_bc,))
                    data_row = cursor.fetchone()
                    if data_row and data_row[0]:
                        json_string = data_row[0]; parsed_overview_json = None 
                        st.subheader(f"Full 'Company Overview Card' JSON for ${selected_ticker_bc}") 
                        try: parsed_overview_json = json.loads(json_string); st.json(parsed_overview_json, expanded=True) 
                        except: st.error("Invalid JSON."); st.code(json_string, language='text')
                        st.markdown("---")
                        st.subheader("Data Sent to Screener AI")
                        st.caption("Extracted from the JSON above.")
                        data_dict_for_extraction = parsed_overview_json if parsed_overview_json else {}
                        def get_screener_field(data_dict, path, default="N/A"): # Simplified version
                            keys = path.split('.'); value = data_dict
                            try:
                                for key in keys: value = value.get(key) if isinstance(value, dict) else None
                                if isinstance(value, list): return " ".join(map(str, value))
                                return str(value) if value is not None else default
                            except: return default
                        screener_data_to_display = { # Simplified list for brevity in example
                            "Confidence": get_screener_field(data_dict_for_extraction, 'confidence'),
                            "Screener Briefing": get_screener_field(data_dict_for_extraction, 'screener_briefing'),
                            "Bias": get_screener_field(data_dict_for_extraction, 'biasStrategy.bias'),
                            "Opening Plan": get_screener_field(data_dict_for_extraction, 'openingTradePlan.planName'),
                            "Alternative Plan": get_screener_field(data_dict_for_extraction, 'alternativePlan.planName'),
                        }
                        for key, value in screener_data_to_display.items(): st.markdown(f"**{key}:** `{value}`")
                    else: st.warning(f"No card found for ${selected_ticker_bc}.")
                except sqlite3.Error as e: st.error(f"DB error: {e}")
                finally: 
                    if conn_data: conn_data.close()


# --- Command Line Test Example (Unchanged) ---
if __name__ == "__main__":
    print("Run with: streamlit run pipeline_engine.py")

