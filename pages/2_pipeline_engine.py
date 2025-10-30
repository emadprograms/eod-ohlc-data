import streamlit as st
import sqlite3
import os
import re
import json
import time
import requests
import pandas as pd
# yfinance is no longer needed for this file
from datetime import date, datetime, timedelta, timezone # Added timezone
try:
    from pytz import timezone as pytz_timezone
    US_EASTERN = pytz_timezone('US/Eastern')
    BAHRAIN_TZ = pytz_timezone('Asia/Bahrain') # Added Bahrain timezone
except ImportError:
    from datetime import timezone
    # This will be logged as a warning in the UI
    st.warning("`pytz` library not found. Pre-market/display time checks may be less accurate. Consider `pip install pytz`.")
    US_EASTERN = timezone(timedelta(hours=-5)) # Fallback to EST
    BAHRAIN_TZ = timezone(timedelta(hours=3)) # Fallback to Bahrain time +03:00

from deepdiff import DeepDiff
import random # --- ADDED FOR RANDOM KEY SELECTION ---

# --- Constants ---
DATABASE_FILE = "analysis_database.db"
MODEL_NAME = "gemini-2.5-pro"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent"

# --- *** NEW: Load Gemini API Keys from Secrets *** ---
gemini_secrets = st.secrets.get("gemini", {})
API_KEYS = gemini_secrets.get("api_keys", []) # Get the list of keys
# --- End New Section ---


# Default JSON structure - This is the primary "Company Overview Card"
DEFAULT_COMPANY_OVERVIEW_JSON = """
{
  "marketNote": "Executor's Battle Card: TICKER",
  "confidence": "Medium - Awaiting confirmation",
  "screener_briefing": "AI Updates: High-level bias for screener. Ignore for trade decisions.",
  "basicContext": {
    "tickerDate": "TICKER | YYYY-MM-DD",
    "sector": "Set in Static Editor / Preserved",
    "companyDescription": "Set in Static Editor / Preserved",
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
    "valuation": "AI RULE: READ-ONLY (Set during initialization/manual edit)",
    "analystSentiment": "AI RULE: READ-ONLY (Set during initialization/manual edit)",
    "insiderActivity": "AI RULE: READ-ONLY (Set during initialization/manual edit)",
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

# --- NEW: Default JSON structure for the Economy Card ---
DEFAULT_ECONOMY_CARD_JSON = """
{
  "marketNarrative": "AI Updates: The current dominant story driving the market.",
  "marketBias": "Neutral",
  "marketKeyAction": "AI RULE: APPEND today's macro developments to continue the story.",
  "keyEconomicEvents": {
    "last_24h": "AI Updates: Summary of recent major data releases and their impact.",
    "next_24h": "AI Updates: List of upcoming high-impact events."
  },
  "sectorRotation": {
    "leadingSectors": [],
    "laggingSectors": [],
    "rotationAnalysis": "AI Updates: Analysis of which sectors are showing strength/weakness."
  },
  "indexAnalysis": {
    "SPY": "AI Updates: Summary of SPY's current position relative to its own major levels.",
    "QQQ": "AI Updates: Summary of QQQ's current position relative to its own major levels."
  },
  "interMarketAnalysis": {
    "bonds": "AI Updates: Analysis of bond market (e.g., TLT performance, yield movements) and its implication for equities.",
    "commodities": "AI Updates: Analysis of key commodities (e.g., Gold/GLD, Oil/USO) for inflation/safety signals.",
    "currencies": "AI Updates: Analysis of the US Dollar (e.g., UUP/DXY) and its impact on risk assets.",
    "crypto": "AI Updates: Analysis of Crypto (e.g., BTC) as a speculative risk gauge."
  },
  "marketInternals": {
    "volatility": "AI Updates: VIX analysis (e.g., 'VIX is falling, suggesting decreasing fear.')."
  }
}
"""


# --- US Market Timezone Constants ---
PREMARKET_START_HOUR = 4
PREMARKET_END_HOUR = 9
PREMARKET_END_MINUTE = 30
# --- NEW: Define the core epics for pre-market inter-market analysis ---
CORE_INTERMARKET_EPICS = [
    "SPY", "US100", "US30", "IWM", "VIX", "TLT", "GOLD", "OIL_CRUDE", 
    "BTCUSD", "XLK", "XLF", "XLV", "SMH"
]


# --- Logger Class ---
class AppLogger:
    def __init__(self, st_container=None):
        self.st_container = st_container
    def log(self, message):
        safe_message = str(message).replace('<', '&lt;').replace('>', '&gt;')
        if self.st_container: self.st_container.markdown(safe_message, unsafe_allow_html=True)
        else: print(message)
    def log_code(self, data, language='json'):
        try:
            if isinstance(data, dict): formatted_data = json.dumps(data, indent=2, ensure_ascii=False)
            elif isinstance(data, str):
                 try: formatted_data = json.dumps(json.loads(data), indent=2, ensure_ascii=False)
                 except: formatted_data = data
            else: formatted_data = str(data)
            escaped_data = formatted_data.replace('`', '\\`')
            log_message = f"```{language}\n{escaped_data}\n```"
            if self.st_container: self.st_container.markdown(log_message, unsafe_allow_html=False)
            else: print(log_message)
        except Exception as e: self.log(f"Err format log: {e}"); self.log(str(data))

# --- Parsing Function (For EOD) ---
def parse_raw_summary(raw_text: str) -> dict:
    """
    Parses the structured text summary from the 'Processor' app (for EOD).
    """
    data = {"raw_text_summary": raw_text}
    def find_value(pattern, text, type_conv=float):
        match = re.search(pattern, text, re.DOTALL)
        if match:
            val_str = match.group(1).replace(',', '').strip();
            if not val_str: return None
            try: return type_conv(val_str)
            except:
                if type_conv == str: return val_str
                return None
        return None
    data['ticker'] = find_value(r"Summary:\s*(\w+)", raw_text, str)
    data['date'] = find_value(r"\|\s*([\d\-]+)", raw_text, str)
    data['open'] = find_value(r"Open:\s*\$([\d\.]+)", raw_text)
    data['close'] = find_value(r"Close:\s*\$([\d\.]+)", raw_text)
    data['high'] = find_value(r"High.*:\s*\$([\d\.]+)", raw_text)
    data['low'] = find_value(r"Low.*:\s*\$([\d\.]+)", raw_text)
    data['poc'] = find_value(r"POC.*:\s*\$([\d\.]+)", raw_text)
    data['vah'] = find_value(r"VAH.*:\s*\$([\d\.]+)", raw_text)
    data['val'] = find_value(r"VAL.*:\s*\$([\d\.]+)", raw_text)
    data['vwap'] = find_value(r"VWAP.*:\s*\$([\d\.]+)", raw_text)
    or_match = re.search(r"Opening Range:\s*\$([\d\.]+)\s*-\s*\$([\d\.]+)", raw_text)
    data['orl'] = float(or_match.group(1)) if or_match else None
    data['orh'] = float(or_match.group(2)) if or_match else None
    return data

# --- Gemini API Call Function ---
def call_gemini_api(prompt: str, api_key: str, system_prompt: str, logger: AppLogger, max_retries=5) -> str:
    """
    Calls the Gemini API, handles key switching and retries.
    """
    current_api_key = api_key
    # Check if API_KEYS list is available and has keys
    if not API_KEYS or len(API_KEYS) == 0:
         logger.log("Error: No Gemini API keys found in st.secrets.")
         return None
         
    if not current_api_key or current_api_key not in API_KEYS: 
        logger.log("Warning: Provided API key invalid or missing, selecting one at random.")
        current_api_key = random.choice(API_KEYS) # Select random key
        
    for i in range(max_retries):
        gemini_api_url = f"{API_URL}?key={current_api_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}], "systemInstruction": {"parts": [{"text": system_prompt}]}}
        headers = {'Content-Type': 'application/json'}
        current_key_index = API_KEYS.index(current_api_key) # Will raise ValueError if key not in list, but we checked
        try:
            response = requests.post(gemini_api_url, headers=headers, data=json.dumps(payload), timeout=90)
            if response.status_code in [429, 503]:
                logger.log(f"API Error {response.status_code} on Key #{current_key_index + 1}. Switching...")
                if len(API_KEYS) > 1:
                    new_key_index = random.randint(0, len(API_KEYS) - 1)
                    while new_key_index == current_key_index:
                        new_key_index = random.randint(0, len(API_KEYS) - 1)
                    current_api_key = API_KEYS[new_key_index]
                    logger.log(f"   ...Switched to random Key #{new_key_index + 1}.")
                else: logger.log("   ...Cannot switch (only one key). Retrying same key.")
                delay = 2**i; logger.log(f"   ...Retry in {delay}s..."); time.sleep(delay); continue
            elif response.status_code != 200:
                logger.log(f"API Error {response.status_code}: {response.text} (Key #{current_key_index + 1})")
                if i < max_retries - 1: delay = 2**i; logger.log(f"   ...Retry in {delay}s..."); time.sleep(delay); continue
                else: logger.log("   ...Final fail."); return None
            result = response.json()
            candidates = result.get("candidates")
            if candidates and len(candidates) > 0:
                content = candidates[0].get("content")
                if content:
                    parts = content.get("parts")
                    if parts and len(parts) > 0:
                        text_part = parts[0].get("text")
                        if text_part is not None:
                            return text_part.strip()
            logger.log(f"Invalid API response (Key #{current_key_index + 1}): {json.dumps(result, indent=2)}")
            if i < max_retries - 1: delay = 2**i; logger.log(f"   ...Retry in {delay}s..."); time.sleep(delay); continue
            else: return None
        except requests.exceptions.Timeout:
             logger.log(f"API Timeout (Key #{current_key_index + 1}). Retry {i+1}/{max_retries}...")
             if i < max_retries - 1: time.sleep(2**i)
        except requests.exceptions.RequestException as e:
            logger.log(f"API Request fail: {e} (Key #{current_key_index + 1}). Retry {i+1}/{max_retries}...");
            if i < max_retries - 1: time.sleep(2**i)
    logger.log(f"API failed after {max_retries} retries."); return None

# --- Workflow #1: Daily Note Generator (Unchanged) ---
def update_stock_note(ticker_to_update: str, new_raw_text: str, macro_context_summary: str, api_key_to_use: str, logger: AppLogger):
    """
    Updates the main EOD card in the database based on the EOD processor text.
    """
    logger.log(f"--- Starting EOD update for {ticker_to_update} ---")
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
        logger.log("1. Parsing raw summary..."); parsed_data = parse_raw_summary(new_raw_text)
        trade_date = parsed_data.get('date', date.today().isoformat())
        ticker_from_parse = parsed_data.get('ticker')
        if not ticker_from_parse: logger.log(f"Warn: No Ticker parsed for {ticker_to_update}. Using provided.");
        elif ticker_from_parse != ticker_to_update: logger.log(f"Warn: Ticker mismatch ({ticker_from_parse} vs {ticker_to_update}). Using {ticker_from_parse}."); ticker_to_update = ticker_from_parse
        if not ticker_to_update: logger.log("Error: No ticker."); return
        
        logger.log("2. Archiving raw data...");
        archive_columns = ['ticker','date','raw_text_summary','open','high','low','close','poc','vah','val','vwap','orl','orh']
        parsed_data['ticker'] = ticker_to_update
        archive_values = tuple(parsed_data.get(col) for col in archive_columns)
        cursor.execute(f"INSERT OR REPLACE INTO data_archive ({','.join(archive_columns)}) VALUES ({','.join(['?']*len(archive_columns))})", archive_values)
        conn.commit(); logger.log("   ...archived.")
        
        logger.log("3. Fetching Historical Notes & Yesterday's EOD Card...");
        cursor.execute("SELECT historical_level_notes, company_overview_card_json FROM stocks WHERE ticker = ?", (ticker_to_update,))
        company_data = cursor.fetchone(); previous_overview_card_dict={}; historical_notes=""
        if company_data:
            historical_notes = company_data["historical_level_notes"] or ""
            if company_data['company_overview_card_json']:
                try: previous_overview_card_dict = json.loads(company_data['company_overview_card_json']); logger.log("   ...found yesterday's EOD card.")
                except: logger.log(f"   ...Warn: Parse fail yesterday's EOD card."); previous_overview_card_dict = json.loads(DEFAULT_COMPANY_OVERVIEW_JSON.replace("TICKER", ticker_to_update))
            else: logger.log(f"   ...No prior EOD card. Creating new."); previous_overview_card_dict = json.loads(DEFAULT_COMPANY_OVERVIEW_JSON.replace("TICKER", ticker_to_update))
        else:
            logger.log(f"   ...No DB entry. Creating row.");
            try: cursor.execute("INSERT OR IGNORE INTO stocks (ticker) VALUES (?)", (ticker_to_update,)); conn.commit(); logger.log(f"   ...Created row.")
            except Exception as insert_err: logger.log(f"   ...Error creating row: {insert_err}"); return
            previous_overview_card_dict = json.loads(DEFAULT_COMPANY_OVERVIEW_JSON.replace("TICKER", ticker_to_update))

        logger.log("4. Building EOD Note Generator Prompt...");
        note_generator_system_prompt = (
            "You are an expert market structure analyst focused ONLY on participant motivation at MAJOR levels. Maintain 'Company Overview Card' JSON. Get [Historical Notes], [Yesterday's Card], [Today's EOD Action]. Generate NEW EOD card JSON. Prioritize structure unless levels decisively broken. Append `keyAction`. Update plans. Preserve `fundamentalContext`, `sector`, `description`. Output ONLY valid JSON."
        )
        
        prompt = f"""
        [Overall Market Context for Today]
        (Use this to inform the 'why' behind the price action. e.g., if the market was risk-off, a stock holding support is more significant.)
        {macro_context_summary or "No overall market context was provided."}

        [Historical Notes for {ticker_to_update}]
        (CRITICAL STATIC CONTEXT: These define the MAJOR structural levels.)
        {historical_notes}

        [Yesterday's Company Overview Card for {ticker_to_update}] 
        (This defines the ESTABLISHED structure, plans, and the story so far in `keyAction`. Update this cautiously based on MAJOR level interaction.) 
        {json.dumps(previous_overview_card_dict, indent=2)}

        [Today's New Price Action Summary]
        (Objective 5-minute data representing the full completed trading day.)
        {new_raw_text}

        [Your Task for Today: {trade_date} (End of Day Update)]
        Generate the NEW, UPDATED "Company Overview Card" JSON reflecting the completed day's action. Focus on MAJOR level interactions and updating the trade PLANS for TOMORROW.
        
        **CRITICAL INSTRUCTIONS (LEVELS ARE PARAMOUNT):**
        1.  **PRESERVE STATIC FIELDS:** Copy `fundamentalContext`, `sector`, `companyDescription` **UNCHANGED** from [Yesterday's Card].
        2.  **RESPECT ESTABLISHED STRUCTURE & LEVELS:**
            * **Bias:** Maintain the `bias` from [Yesterday's Card] unless [Today's Action] *decisively breaks AND closes beyond* a MAJOR support/resistance level defined in yesterday's `riskZones` or `historical_level_notes`. Consolidation within the established range does NOT change the bias.
            * **Major S/R:** Keep the MAJOR `support`/`resistance` levels from `historical_level_notes` and [Yesterday's Card] unless today's action *clearly invalidates* them.
            * **Minor S/R:** Acknowledge *new* intraday levels (LOD, HOD, POC, VWAP) in `tradingRange` and `keyAction`, describing how price reacted to them. DO NOT automatically promote these to major levels.
            * **Pattern:** Only update `technicalStructure.pattern` if today's action *completes* or *decisively breaks* the pattern.
            * **Interpret Contextually:** Consolidation near highs after an uptrend = Bullish continuation unless MAJOR support fails. Consolidation near lows after downtrend = Bearish continuation unless MAJOR resistance breaks.
        3.  **UPDATE `keyAction` (Level-Focused):** APPEND today's action relative to MAJOR levels to the existing `keyAction`. How did price interact with the pre-defined levels?
        4.  **UPDATE `volumeMomentum` (Level-Focused):** Describe ONLY how volume confirmed or denied the `keyAction` *at those specific levels*.
        5.  **UPDATE PLANS:** Based on the new `keyAction` at MAJOR levels, update BOTH `openingTradePlan` and `alternativePlan` for TOMORROW.
        6.  **`confidence` Rationale:** Base confidence on how well today's action *respected* the established structure and levels. High confidence = structure held/confirmed. Low confidence = structure decisively broke.
        
        [Output Format Constraint]
        Output ONLY the single, complete, updated JSON object. Ensure it is valid JSON. Do not include ```json markdown.
        """
        
        logger.log(f"5. Calling EOD AI Analyst...");
        ai_response_text = call_gemini_api(prompt, api_key_to_use, note_generator_system_prompt, logger)
        if not ai_response_text: logger.log("Error: No AI response."); return
        
        logger.log("6. Received EOD Card JSON. Parsing & Comparing...");
        json_match = re.search(r"```json\s*([\s\S]+?)\s*```", ai_response_text); ai_response_text = json_match.group(1) if json_match else ai_response_text.strip()
        new_overview_card_dict = None
        try:
            full_parsed_json = json.loads(ai_response_text)
            if isinstance(full_parsed_json, list) and full_parsed_json: new_overview_card_dict = full_parsed_json[0]
            elif isinstance(full_parsed_json, dict): new_overview_card_dict = full_parsed_json
            else: raise json.JSONDecodeError("Not dict/list.", ai_response_text, 0)
        except Exception as e: logger.log(f"Invalid JSON: {e}\n{ai_response_text}"); return
        
        required_keys=['marketNote','confidence','screener_briefing','basicContext','technicalStructure','fundamentalContext','behavioralSentiment','openingTradePlan','alternativePlan']
        required_plan=['planName','knownParticipant','expectedParticipant','trigger','invalidation']; required_alt=required_plan+['scenario']
        missing_keys=[k for k in required_keys if k not in new_overview_card_dict]
        opening_plan_dict=new_overview_card_dict.get('openingTradePlan',{}); alt_plan_dict=new_overview_card_dict.get('alternativePlan',{})
        missing_open=[k for k in required_plan if k not in opening_plan_dict]
        missing_alt=[k for k in required_alt if k not in alt_plan_dict]
        if missing_keys or missing_open or missing_alt: logger.log(f"Missing keys: T({missing_keys}), O({missing_open}), A({missing_alt}). Abort.\n{json.dumps(new_overview_card_dict, indent=2)}"); return
        
        logger.log("   ...JSON parsed & validated.")
        try: # DeepDiff
            diff=DeepDiff(previous_overview_card_dict, new_overview_card_dict, ignore_order=True, view='tree')
            if not diff: logger.log("   ...No changes.")
            else:
                changes_log="   **Changes detected:**\n"; changes_found=False
                if 'values_changed' in diff:
                    changes_log+="| Field | Old | New |\n|---|---|---|\n"; changes_found=True
                    for change in diff['values_changed']:
                        path=change.path().replace("root","").replace("['",".").replace("']","").strip('.'); path=path or"(root)"
                        old=change.t1; new=change.t2; old_s=json.dumps(old,ensure_ascii=False) if isinstance(old,(dict,list)) else str(old); new_s=json.dumps(new,ensure_ascii=False) if isinstance(new,(dict,list)) else str(new)
                        old_s=(old_s[:50]+'...') if len(old_s)>53 else old_s; new_s=(new_s[:50]+'...') if len(new_s)>53 else new_s
                        changes_log+=f"| `{path}` | `{old_s}` | `{new_s}` |\n"
                if not changes_found and ('dictionary_item_added' in diff or 'dictionary_item_removed' in diff): changes_log+="   ...Structural changes only.\n"
                elif changes_found: logger.log(changes_log)
        except Exception as e: logger.log(f"   ...Error comparing: {e}.")
        
        logger.log(f"   ...AI Confidence: `{new_overview_card_dict.get('confidence','N/A')}`")
        logger.log(f"   ...AI Briefing: `{new_overview_card_dict.get('screener_briefing','N/A')}`")
        logger.log(f"   ...AI Plan: `{new_overview_card_dict.get('openingTradePlan',{}).get('planName','N/A')}`")
        
        logger.log("7. Saving NEW EOD Card..."); today_str=date.today().isoformat()
        new_json_str=json.dumps(new_overview_card_dict, indent=2)
        cursor.execute("UPDATE stocks SET company_overview_card_json=?, last_updated=? WHERE ticker=?", (new_json_str, today_str, ticker_to_update))
        if cursor.rowcount==0: logger.log(f"   ...Warn: Update fail {ticker_to_update} (row 0). Init first.")
        else: conn.commit(); logger.log(f"--- Success EOD update {ticker_to_update} ---")
    except Exception as e: logger.log(f"Unexpected error in EOD update: `{e}`")
    finally:
        if conn: conn.close()



# --- NEW: Workflow for Economy Card EOD Update ---
def update_economy_card(manual_summary: str, etf_summaries_text: str, api_key_to_use: str, logger: AppLogger):
    """
    Updates the global Economy Card in the database using AI.
    """
    logger.log("--- Starting Economy Card EOD Update ---")
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        logger.log("1. Fetching previous day's Economy Card...")
        cursor.execute("SELECT economy_card_json FROM market_context WHERE context_id = 1")
        eco_data = cursor.fetchone()
        
        previous_economy_card_dict = {}
        if eco_data and eco_data['economy_card_json']:
            try:
                previous_economy_card_dict = json.loads(eco_data['economy_card_json'])
                logger.log("   ...found previous Economy Card.")
            except json.JSONDecodeError:
                logger.log("   ...Warn: Could not parse previous card, starting from default.")
                previous_economy_card_dict = json.loads(DEFAULT_ECONOMY_CARD_JSON)
        else:
            logger.log("   ...No previous card found, starting from default.")
            previous_economy_card_dict = json.loads(DEFAULT_ECONOMY_CARD_JSON)

        logger.log("2. Building Economy Card Update Prompt...")
        
        system_prompt = (
            "You are a macro-economic strategist. Your task is to update the global 'Economy Card' JSON. "
            "You will receive the previous card, a manual summary from the user, and EOD data for key ETFs. "
            "Your primary goal is to synthesize this information into an updated macro view. "
            "CRITICAL: You MUST append to the `marketKeyAction` field to continue the narrative, not replace it. "
            "Output ONLY the single, valid JSON object."
        )

        prompt = f"""
        [CONTEXT & INSTRUCTIONS]
        Your task is to generate the updated "Economy Card" JSON for today, {date.today().isoformat()}.
        Synthesize all the provided information to create a comprehensive macro-economic outlook.

        **CRITICAL RULE: APPEND, DON'T REPLACE.**
        You MUST append today's analysis to the `marketKeyAction` field from the [Previous Day's Card]. Do not erase the existing story. Start a new line with today's date.

        [DATA]
        1.  **Previous Day's Economy Card:**
            (This is the established macro context and narrative.)
            {json.dumps(previous_economy_card_dict, indent=2)}

        2.  **User's Manual Daily Summary:**
            (This is the user's high-level take on the day's events. Give this high importance for the `marketNarrative`.)
            "{manual_summary}"

        3.  **Today's EOD ETF Data Summaries:**
            (This is the objective price and volume data for key market indices and sectors.)
            {etf_summaries_text}

        [YOUR TASK]
        Generate the new, updated "Economy Card" JSON.
        - Update `marketNarrative` and `marketBias` based on all inputs.
        - APPEND to `marketKeyAction`.
        - Update `sectorRotation` and based on the ETF data.
        - Update `keyEconomicEvents` and `marketInternals` if new information is available.
        - **Update `indexAnalysis` for SPY, QQQ, IWM, and DIA** based on their respective EOD data summaries.
        - **Update the `interMarketAnalysis` section.** Analyze the data for assets like TLT (Bonds), GLD (Gold), UUP (Dollar), and BTC (Crypto) to describe the broader capital flow story. Is money flowing to safety (bonds/gold up) or into risk (equities/crypto up)?
        - Output ONLY the single, complete, updated JSON object.
        """

        logger.log("3. Calling Macro Strategist AI...")
        ai_response_text = call_gemini_api(prompt, api_key_to_use, system_prompt, logger)

        if not ai_response_text:
            logger.log("Error: No response from Macro AI. Aborting update.")
            return

        logger.log("4. Parsing and validating new Economy Card...")
        json_match = re.search(r"```json\s*([\s\S]+?)\s*```", ai_response_text)
        ai_response_text = json_match.group(1) if json_match else ai_response_text.strip()

        try:
            new_economy_card_dict = json.loads(ai_response_text)
            # Basic validation
            if "marketNarrative" not in new_economy_card_dict or "sectorRotation" not in new_economy_card_dict:
                raise ValueError("Validation failed: Key fields missing from AI response.")
            
            logger.log("   ...JSON parsed and validated.")
            logger.log(f"   ...New Market Narrative: {new_economy_card_dict.get('marketNarrative', 'N/A')}")

            logger.log("5. Saving new Economy Card to database...")
            new_json_str = json.dumps(new_economy_card_dict, indent=2)
            cursor.execute("UPDATE market_context SET economy_card_json = ?, last_updated = ? WHERE context_id = 1",
                           (new_json_str, date.today().isoformat()))
            conn.commit()
            logger.log("--- Success: Economy Card EOD update complete! ---")

        except (json.JSONDecodeError, ValueError) as e:
            logger.log(f"Error processing AI response: {e}")
            logger.log_code(ai_response_text, 'text')

    except Exception as e:
        logger.log(f"An unexpected error occurred in update_economy_card: {e}")
    finally:
        if conn:
            conn.close()




# --- UPDATED: Workflow 2a-Part1 - Generate Pre-Market Economy Card ---
def generate_premarket_economy_card(premarket_macro_news: str, logger: AppLogger, cst: str, xst: str):
    """
    Creates a temporary, tactical Pre-Market Economy Card using EOD card, manual news, AND live ETF data.
    """
    logger.log("--- Starting Pre-Market Economy Card Generation ---")
    conn = None
    try:
        # --- Step 1: Fetch Live Pre-Market Data for Core Inter-Market Epics ---
        logger.log(f"1. Fetching live pre-market data for {len(CORE_INTERMARKET_EPICS)} core epics...")
        etf_pm_summaries = []
        for i, epic in enumerate(CORE_INTERMARKET_EPICS):
            logger.log(f"   ...Processing {epic}...")
            bid, offer = get_capital_current_price(epic, cst, xst, logger)
            if bid and offer:
                live_price = (bid + offer) / 2
                df_5m = get_capital_price_bars(epic, cst, xst, "MINUTE_5", logger)
                if df_5m is not None: # Can be an empty DataFrame
                    summary = process_premarket_bars_to_summary(epic, df_5m, live_price, logger)
                    etf_pm_summaries.append(summary)
            if i < len(CORE_INTERMARKET_EPICS) - 1: time.sleep(0.33)
        
        etf_pm_summaries_text = "\n".join(etf_pm_summaries)
        if not etf_pm_summaries_text:
            logger.log("   ...Warning: Could not fetch any live pre-market data. Context will be limited.")

        # --- Step 2: Fetch EOD Economy Card ---
        conn = sqlite3.connect(DATABASE_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        logger.log("2. Fetching latest EOD Economy Card from DB...")
        cursor.execute("SELECT economy_card_json FROM market_context WHERE context_id = 1")
        eco_data = cursor.fetchone()
        
        eod_economy_card_dict = {}
        if eco_data and eco_data['economy_card_json']:
            try:
                eod_economy_card_dict = json.loads(eco_data['economy_card_json'])
                st.session_state['eod_economy_card'] = eod_economy_card_dict # Cache it
                logger.log("   ...found EOD Economy Card.")
            except json.JSONDecodeError:
                logger.log("   ...Warn: Could not parse EOD card. Pre-market context will be limited.")
                st.session_state['premarket_economy_card'] = None
                return False
        else:
            logger.log("   ...Warn: No EOD Economy Card in DB. Pre-market context will be limited.")
            st.session_state['premarket_economy_card'] = None
            return False

        # --- Step 3: Build AI Prompt ---
        logger.log("3. Building Pre-Market Economy Card Prompt...")
        
        system_prompt = (
            "You are a macro-economic strategist creating a TACTICAL update for the market open. "
            "You will receive the strategic EOD card, manual news, and LIVE pre-market data for major indices, bonds, commodities, and sectors. "
            "Your task is to synthesize this into a temporary 'Pre-Market Economy Card' reflecting the immediate situation. "
            "Output ONLY the single, valid JSON object."
        )

        prompt = f"""
        [CONTEXT & INSTRUCTIONS]
        Your task is to generate a temporary "Pre-Market Economy Card" JSON for today's open.
        This is a TACTICAL update. Synthesize all available data to determine the market's immediate bias for the opening bell.

        [DATA]
        1.  **Strategic EOD Economy Card (Yesterday's Close):**
            (This is the established macro context.)
            {json.dumps(eod_economy_card_dict, indent=2)}

        2.  **Live Pre-Market Data (Objective Action):**
            (This is the most important data for determining the immediate tactical bias. How are the indices, bonds, gold, oil, and key sectors behaving right now?)
            {etf_pm_summaries_text or "No live pre-market data available."}

        3.  **New Pre-Market Macro News/Events (Manual Input):**
            (Use this to add color and reasoning to the objective data.)
            "{premarket_macro_news or 'No major overnight macro news reported.'}"

        [YOUR TASK]
        Generate the new, temporary "Pre-Market Economy Card" JSON.
        - Create a new, concise `marketNarrative` for the open based on the live data and news.
        - Adjust the `marketBias` based on the strength and direction of the pre-market movements across all asset classes.
        - Update the `interMarketAnalysis` section with a tactical summary of what the live data implies (e.g., "Bonds (TLT) are down and Tech (XLK) is up, confirming a risk-on bias for the open.").
        - Do NOT modify the `marketKeyAction`; that is a historical log.
        - Output ONLY the single, complete, updated JSON object.
        """

        logger.log("4. Calling Pre-Market Macro AI...")
        key_to_use = random.choice(API_KEYS)
        ai_response_text = call_gemini_api(prompt, key_to_use, system_prompt, logger)

        if not ai_response_text:
            logger.log("Error: No response from Macro AI. Aborting update.")
            st.session_state['premarket_economy_card'] = None
            return False

        logger.log("5. Parsing and saving new Pre-Market Economy Card to session state...")
        json_match = re.search(r"```json\s*([\s\S]+?)\s*```", ai_response_text)
        ai_response_text = json_match.group(1) if json_match else ai_response_text.strip()

        try:
            premarket_economy_card_dict = json.loads(ai_response_text)
            st.session_state['premarket_economy_card'] = premarket_economy_card_dict
            logger.log("--- Success: Pre-Market Economy Card generated and saved to session state. ---")
            return True
        except json.JSONDecodeError as e:
            logger.log(f"Error processing AI response: {e}")
            logger.log_code(ai_response_text, 'text')
            st.session_state['premarket_economy_card'] = None
            return False

    except Exception as e:
        logger.log(f"An unexpected error occurred in generate_premarket_economy_card: {e}")
        st.session_state['premarket_economy_card'] = None
        return False
    finally:
        if conn:
            conn.close()


            
# ---
# --- Capital.com Authentication & Data Functions (Imported from Tester) ---
# ---

# --- FIX: Removed @st.cache_resource ---
def create_capital_session(_logger: AppLogger): # Logger marked to be ignored by cache
    """
    Creates a new session with Capital.com using st.secrets.
    Caches the session tokens.
    """
    _logger.log("Attempting to create new Capital.com session...")
    capital_com_secrets = st.secrets.get("capital_com", {})
    api_key = capital_com_secrets.get("X_CAP_API_KEY")
    identifier = capital_com_secrets.get("identifier")
    password = capital_com_secrets.get("password")

    if not all([api_key, identifier, password]):
        _logger.log("<span style='color:red;'>Error: Capital.com secrets not found.</span>")
        _logger.log("Add `[capital_com]` section to `.streamlit/secrets.toml`")
        return None, None, None
    
    # --- FIX: Removed Markdown from URL ---
    session_url = "https://api-capital.backend-capital.com/api/v1/session"
    headers = {'X-CAP-API-KEY': api_key, 'Content-Type': 'application/json'}
    payload = {"identifier": identifier, "password": password}
    
    try:
        response = requests.post(session_url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        cst_token = response.headers.get('CST')
        security_token = response.headers.get('X-SECURITY-TOKEN')
        data = response.json(); account_info = data.get('accountInfo', {});
        balance = account_info.get('balance'); account_id = data.get('accountId')
        
        if cst_token and security_token:
            _logger.log(f"<span style='color:green;'>Capital.com session created. (Balance: ${balance})</span>")
            return cst_token, security_token, balance
        else:
            _logger.log(f"Session failed: Tokens missing. Headers: {response.headers}"); return None, None, None
    except requests.exceptions.HTTPError as e:
        _logger.log(f"<span style='color:red;'>Session failed (HTTP Error): {e.response.status_code}</span>")
        try: _logger.log_code(e.response.json())
        except: _logger.log_code(e.response.text, 'text')
        return None, None, None
    except Exception as e:
        _logger.log(f"<span style='color:red;'>Session failed (Error): {e}</span>"); return None, None, None

def get_capital_current_price(epic: str, cst: str, xst: str, logger: AppLogger):
    """Gets the live bid/offer for a single epic."""
    # --- FIX: Removed Markdown from URL ---
    url = f"https://api-capital.backend-capital.com/api/v1/markets/{epic}"
    headers = {'X-SECURITY-TOKEN': xst, 'CST': cst}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()
        snapshot = data.get('snapshot')
        if snapshot and 'bid' in snapshot and 'offer' in snapshot:
            return snapshot['bid'], snapshot['offer']
        else:
            logger.log(f"   ...Warn ({epic}): Live price not in snapshot. {data}")
            return None, None
    except Exception as e:
        if hasattr(e, 'response') and e.response.status_code == 404:
            logger.log(f"   ...Warn ({epic}): Market not found (404). Check EPIC name.")
        else:
            logger.log(f"   ...Error fetching live price for {epic}: {e}")
        return None, None

def get_capital_price_bars(epic: str, cst: str, xst: str, resolution: str, logger: AppLogger) -> pd.DataFrame | None:
    """
    Fetches price bars for a given resolution, filtering for today's pre-market.
    """
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(hours=16) # Fetch last 16 hours
    
    price_params = {"resolution": resolution, 'max': 1000, 'from': start_date.strftime('%Y-%m-%dT%H:%M:%S'), 'to': end_date.strftime('%Y-%m-%dT%H:%M:%S')}
    headers = {'X-SECURITY-TOKEN': xst, 'CST': cst}
    # --- FIX: Removed Markdown from URL ---
    price_history_url = f"https://api-capital.backend-capital.com/api/v1/prices/{epic}"
    
    try:
        response = requests.get(price_history_url, headers=headers, params=price_params, timeout=10)
        response.raise_for_status()
        price_data = response.json()
        prices = price_data.get('prices', [])
        if not prices:
            logger.log(f"   ...No price bars returned for {epic} (resolution: {resolution}).")
            return None
            
        data = {
            'SnapshotTime': [p.get('snapshotTime') for p in prices],
            'Open': [p.get('openPrice', {}).get('bid') for p in prices],
            'High': [p.get('highPrice', {}).get('bid') for p in prices],
            'Low': [p.get('lowPrice', {}).get('bid') for p in prices],
            'Close': [p.get('closePrice', {}).get('bid') for p in prices],
            'Volume': [p.get('lastTradedVolume') for p in prices]
        }
        df = pd.DataFrame(data)
        df['SnapshotTime'] = pd.to_datetime(df['SnapshotTime'], errors='coerce', utc=True)
        df.dropna(subset=['SnapshotTime', 'Close', 'Open', 'High', 'Low', 'Volume'], inplace=True)
        
        if df.empty:
            logger.log(f"   ...Price bars for {epic} were empty after cleaning.")
            return None
        
        # Filter to *today's* pre-market (4:00 - 9:30 ET)
        df['ET_Time'] = df['SnapshotTime'].dt.tz_convert(US_EASTERN)
        today_et = datetime.now(US_EASTERN).date()
        pm_start = US_EASTERN.localize(datetime(today_et.year, today_et.month, today_et.day, PREMARKET_START_HOUR, 0))
        pm_end = US_EASTERN.localize(datetime(today_et.year, today_et.month, today_et.day, PREMARKET_END_HOUR, PREMARKET_END_MINUTE))
        
        df_premarket = df[(df['ET_Time'] >= pm_start) & (df['ET_Time'] < pm_end)].copy()
        
        if df_premarket.empty:
            logger.log(f"   ...No bars found for {epic} within today's pre-market window ({pm_start.strftime('%Y-%m-%d %H:%M')} to {pm_end.strftime('%H:%M')}).")
            return pd.DataFrame() # Return EMPTY dataframe instead of None
            
        logger.log(f"   ...Successfully extracted {len(df_premarket)} pre-market bars for {epic}.")
        return df_premarket

    except Exception as e:
        logger.log(f"   ...Error fetching/processing price bars for {epic}: {e}")
        return None

# --- NEW: Pre-Market Processor ---
def process_premarket_bars_to_summary(ticker: str, df_pm: pd.DataFrame, live_price: float, logger: AppLogger) -> str:
    """
    Analyzes the 5-min pre-market DataFrame and creates a detailed text summary
    in the same format as the EOD Processor.
    """
    logger.log(f"   ...Processing {len(df_pm)} pre-market bars for {ticker}...")
    try:
        if df_pm.empty:
            return f"Pre-Market Story: {ticker} | {date.today().isoformat()} (No pre-market bars found. Current price is ${live_price:.2f})"

        pm_open = df_pm['Open'].iloc[0]
        pm_high = df_pm['High'].max()
        pm_low = df_pm['Low'].min()
        pm_close = live_price # Use the live price as the "current close"
        total_volume = df_pm['Volume'].sum()
        
        if total_volume > 0:
            pm_vwap = (df_pm['Close'] * df_pm['Volume']).sum() / total_volume
        else:
            pm_vwap = pm_close
        
        pm_poc = pm_close; pm_val = pm_low; pm_vah = pm_high
        
        if not df_pm.empty and total_volume > 0 and len(df_pm) > 1:
            try:
                unique_prices = df_pm['Close'].nunique()
                bins_calc = min(20, unique_prices - 1 if unique_prices > 1 else 1)
                
                if bins_calc > 0:
                    price_bins = pd.cut(df_pm['Close'], bins=bins_calc)
                    volume_by_price = df_pm.groupby(price_bins)['Volume'].sum()
                    if not volume_by_price.empty:
                        poc_range = volume_by_price.idxmax()
                        pm_poc = poc_range.mid
                        target_volume = total_volume * 0.7
                        poc_bin_index = volume_by_price.index.get_loc(poc_range)
                        current_volume = volume_by_price.iloc[poc_bin_index]
                        pm_val_bin_index, pm_vah_bin_index = poc_bin_index, poc_bin_index

                        while current_volume < target_volume and (pm_val_bin_index > 0 or pm_vah_bin_index < len(volume_by_price) - 1):
                            next_up_index = pm_vah_bin_index + 1
                            next_down_index = pm_val_bin_index - 1
                            vol_up = volume_by_price.iloc[next_up_index] if next_up_index < len(volume_by_price) else 0
                            vol_down = volume_by_price.iloc[next_down_index] if next_down_index >= 0 else 0
                            if vol_up == 0 and vol_down == 0: break
                            if vol_up > vol_down:
                                current_volume += vol_up; pm_vah_bin_index = next_up_index
                            else:
                                current_volume += vol_down; pm_val_bin_index = next_down_index
                        
                        pm_val = volume_by_price.index[pm_val_bin_index].left
                        pm_vah = volume_by_price.index[pm_vah_bin_index].right
            except Exception as e:
                 logger.log(f"      ...Warn: Could not calculate POC/VAH for {ticker}: {e}")
        
        trend_desc = "Consolidating."
        price_range = pm_high - pm_low
        if price_range > 0.001: 
            percent_of_range = (pm_close - pm_low) / price_range
            if percent_of_range > 0.7: trend_desc = "Trending higher near PMH."
            elif percent_of_range < 0.3: trend_desc = "Trending lower near PML."
        
        summary_text = f"""
        Pre-Market Story: {ticker} | {date.today().isoformat()}
        Open (PM): ${pm_open:.2f}
        High (PMH): ${pm_high:.2f}
        Low (PML): ${pm_low:.2f}
        Current Price: ${pm_close:.2f}
        Session VWAP (PM): ${pm_vwap:.2f}
        Value Area (PM): ${pm_val:.2f} - ${pm_vah:.2f}
        Point of Control (POC) (PM): ${pm_poc:.2f}
        Total Volume (PM): {total_volume}
        Key Action: Price opened PM at ${pm_open:.2f}, set a range between ${pm_low:.2f} and ${pm_high:.2f}. {trend_desc} Currently trading at ${pm_close:.2f} ({'above' if pm_close > pm_vwap else 'below'} PM VWAP).
        """
        return re.sub(r'\s+', ' ', summary_text).strip()
    
    except Exception as e:
        logger.log(f"   ...Error in process_premarket_bars_to_summary for {ticker}: {e}")
        return f"Pre-Market Summary: {ticker} | {date.today().isoformat()} (Live Price: ${live_price:.2f}. Error processing bars.)"



# --- Workflow 2a-Part2 - Generate Pre-Market Tactical Cards (UPDATED with Economy Card) ---
def generate_premarket_tactical_cards(selected_tickers: list, overnight_news: str, premarket_economy_card: dict, logger: AppLogger, cst: str, xst: str):
    logger.log("--- Starting Workflow 2a-Part2: Generate Pre-Market Company Cards ---")
    premarket_cards_output = {}
    if not selected_tickers: logger.log("No tickers selected."); return False

    economy_card_text = "Not available."
    if premarket_economy_card:
        try:
            economy_card_text = json.dumps(premarket_economy_card, indent=2)
            logger.log("   ...Pre-Market Economy Card context loaded.")
        except Exception as e:
            logger.log(f"   ...Warn: Could not serialize Pre-Market Economy Card: {e}")
            economy_card_text = str(premarket_economy_card)

    try:
        conn = sqlite3.connect(DATABASE_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
        
        logger.log(f"Fetching EOD cards for {len(selected_tickers)} selected tickers...")
        placeholders = ','.join('?' * len(selected_tickers))
        cursor.execute(f"SELECT ticker, historical_level_notes, company_overview_card_json FROM stocks WHERE ticker IN ({placeholders}) AND company_overview_card_json IS NOT NULL AND company_overview_card_json != '' AND json_valid(company_overview_card_json)", selected_tickers)
        eod_card_rows = cursor.fetchall()
        
        eod_cards_map = {row['ticker']: (row['historical_level_notes'] or "", row['company_overview_card_json']) for row in eod_card_rows}
        
        if len(eod_card_rows) != len(selected_tickers):
             found_tickers = eod_cards_map.keys()
             missing = [t for t in selected_tickers if t not in found_tickers]
             logger.log(f"Warn: No valid EOD cards for: {', '.join(missing)}.")
             if not eod_card_rows: logger.log("Error: No EOD cards found."); return False
        
        logger.log("Fetching Capital.com data (Live Price & 5-min Bars)...")
        live_prices = {}
        bar_dataframes = {}
        
        for i, ticker in enumerate(selected_tickers):
             if ticker in eod_cards_map:
                 bid, offer = get_capital_current_price(ticker, cst, xst, logger)
                 if bid and offer:
                     live_prices[ticker] = (bid + offer) / 2
                 
                 df_5m = get_capital_price_bars(ticker, cst, xst, "MINUTE_5", logger) # Use 5-min bars
                 if df_5m is not None: # Can be empty DF, that's fine
                     bar_dataframes[ticker] = df_5m
                 
                 if i < len(selected_tickers) - 1: time.sleep(0.33)

        logger.log(f"   ...Live prices found for {len(live_prices)} / {len(selected_tickers)} tickers.")
        logger.log(f"   ...5-min bars found for {len(bar_dataframes)} / {len(selected_tickers)} tickers.")

        pre_market_synthesizer_system_prompt = (
             "You are an expert market structure analyst creating a TACTICAL plan for the OPENING BELL. Your core philosophy is analyzing participant motivation at MAJOR levels. You will be given historical notes, a strategic EOD card, and live pre-market data. Your task is to generate a new 'Pre-Market Tactical Card' in JSON format. Analyze the pre-market gap and price action against the major levels and update the trade plans accordingly. Preserve static fields like `fundamentalContext` and `majorSupport`/`majorResistance`. Update all dynamic fields to reflect the immediate pre-market reality. Handle 'Blue Sky Breakout' scenarios as long-oriented opportunities. Output ONLY the single, valid JSON object."
        )

        processed_count = 0
        logger.log(f"Starting AI synthesis loop for {len(eod_card_rows)} tickers with EOD cards...")
        for i, row in enumerate(eod_card_rows):
            ticker = row['ticker']
            logger.log(f"\n--- Processing Ticker: {ticker} ---")
            historical_notes_pm = row['historical_level_notes'] or ""
            eod_card_json_str = row['company_overview_card_json']
            try:
                eod_card_dict = json.loads(eod_card_json_str)
                logger.log("**Base EOD Card (Input):**"); logger.log_code(eod_card_dict)
            except Exception as e: logger.log(f"   ...Skip {ticker}: Invalid EOD JSON. Err: {e}"); continue

            live_price = live_prices.get(ticker)
            df_pm = bar_dataframes.get(ticker)

            if not live_price or df_pm is None:
                 logger.log(f"   ...**STOPPING AI Call for {ticker}: Missing Live Price or 5-min Bar Data Fetch Failed.**")
                 logger.log(f"      (Live Price found: {bool(live_price)}, Bar Data fetch status: {'Success (May be Empty)' if isinstance(df_pm, pd.DataFrame) else 'Failed (None)'})")
                 continue

            logger.log(f"**Processing {len(df_pm)} 5-min bars for Pre-Market Story...**")
            pre_market_story_text = process_premarket_bars_to_summary(ticker, df_pm, live_price, logger)
            logger.log("**Generated Pre-Market Story (Input):**")
            logger.log_code(pre_market_story_text, 'text')
            
            live_price_for_prompt = f"~${live_price:.2f}"
            time_str = datetime.now(US_EASTERN).strftime('%Y-%m-%d %H:%M:%S %Z')
            pre_market_context_str = f"Current Price: {live_price_for_prompt} (@ {time_str})."
            try:
                 basic_context=eod_card_dict.get("basicContext",{}); price_trend=basic_context.get("priceTrend","")
                 y_close_str = str(price_trend).split("|")[0].replace("~","").replace("$","").strip()
                 if y_close_str: y_close=float(y_close_str); gap_pct=((live_price-y_close)/y_close)*100; pre_market_context_str += f" Gap: {gap_pct:+.2f}%."
            except Exception as e: logger.log(f"      ...Warn: Error calculating gap: {e}")
            logger.log(f"**Live Price / Gap String (Input):** `{pre_market_context_str}`")
            logger.log(f"**Overnight Company News (Input):** `{overnight_news or 'N/A'}`")

            prompt = f"""
            [CONTEXT]
            1.  **Pre-Market Economy Card (Current Macro View):**
                {economy_card_text}
            
            2.  **Historical Notes for {ticker} (Major Levels):**
                {historical_notes_pm}

            3.  **Yesterday's EOD Company Card for {ticker} (Base Strategy):**
                {json.dumps(eod_card_dict, indent=2)}

            [LIVE DATA]
            - **Live Price/Gap:** {pre_market_context_str}
            - **Pre-Market Story (from 5-min bars):** {pre_market_story_text}
            - **Company-Specific News:** {overnight_news or "N/A"}

            [TASK]
            Generate the NEW "Pre-Market Tactical Card" JSON for {ticker} for the open ({date.today().isoformat()}).
            Your analysis MUST consider the Pre-Market Economy Card. For example, if the macro view is risk-off, be more skeptical of bullish breakouts.

            **CRITICAL INSTRUCTIONS:**
            1.  **MACRO-AWARE ANALYSIS:** Your primary task is to analyze the live pre-market gap relative to the major levels, WITHIN THE CONTEXT of the Pre-Market Economy Card.
            2.  **HANDLE "BLUE SKY" BREAKOUTS:** If the live price is above ALL `majorResistance` levels, identify this as a "Blue Sky Breakout". Your plan should be long-oriented (e.g., use former resistance as support), with the alternative being a "Failed Breakout".
            3.  **PRESERVE STATICS:** Preserve `fundamentalContext`, `sector`, `companyDescription`, `majorSupport`, and `majorResistance` fields from the EOD card.
            4.  **UPDATE DYNAMIC FIELDS:** Update all other fields (`marketNote`, `confidence`, `screener_briefing`, etc.) to reflect the immediate tactical situation.
            5.  **OUTPUT FORMAT:** Output ONLY the single, complete, updated JSON object. Do not include ```json markdown.
            """
            logger.log("**Full Prompt Sent to Pre-Market AI:**"); logger.log_code(prompt, language='text')

            key_to_use = random.choice(API_KEYS)
            logger.log(f"Calling Pre-Market AI (key #{API_KEYS.index(key_to_use)+1})...")
            ai_response_text = call_gemini_api(prompt, key_to_use, pre_market_synthesizer_system_prompt, logger)

            if ai_response_text:
                logger.log("**Raw AI Response (Pre-Market):**"); logger.log_code(ai_response_text, language='text')
                json_match = re.search(r"```json\s*([\s\S]+?)\s*```", ai_response_text); ai_response_text = json_match.group(1) if json_match else ai_response_text.strip()
                try:
                    premarket_card_dict = json.loads(ai_response_text)
                    logger.log("**Parsed AI Response (Tactical Card):**"); logger.log_code(premarket_card_dict)
                    
                    if 'preMarketContext' not in premarket_card_dict: premarket_card_dict['preMarketContext'] = {}
                    premarket_card_dict['preMarketContext']['livePrice'] = live_price_for_prompt
                    premarket_card_dict['preMarketContext']['overnightNews'] = overnight_news or "N/A"
                    ai_summary_for_ctx = premarket_card_dict.get('screener_briefing', "AI Summary missing")
                    ai_key_action = premarket_card_dict.get('technicalStructure',{}).get('keyAction', "N/A")
                    premarket_card_dict['preMarketContext']['tacticalSummary'] = f"Briefing: {ai_summary_for_ctx} | Recent Key Action: {ai_key_action}"

                    req_keys_pm=['marketNote','confidence','screener_briefing','basicContext','technicalStructure','fundamentalContext','behavioralSentiment','openingTradePlan','alternativePlan','preMarketContext']
                    req_plan_pm=['planName','knownParticipant','expectedParticipant','trigger','invalidation']; req_alt_pm=req_plan_pm+['scenario']; req_pm_ctx=['livePrice','overnightNews','tacticalSummary']
                    miss_keys_pm=[k for k in req_keys_pm if k not in premarket_card_dict]
                    pm_open_plan = premarket_card_dict.get('openingTradePlan', {})
                    pm_alt_plan = premarket_card_dict.get('alternativePlan', {})
                    pm_ctx = premarket_card_dict.get('preMarketContext', {})
                    miss_open_pm=[k for k in req_plan_pm if k not in pm_open_plan]
                    miss_alt_pm=[k for k in req_alt_pm if k not in pm_alt_plan]
                    miss_pm_ctx=[k for k in req_pm_ctx if k not in pm_ctx]

                    if miss_keys_pm or miss_open_pm or miss_alt_pm or miss_pm_ctx:
                         logger.log(f"      ...Error {ticker}: Validation Failed! Missing: T({miss_keys_pm}), O({miss_open_pm}), A({miss_alt_pm}), PM({miss_pm_ctx}).")
                         logger.log("**Problematic Parsed PreMarket JSON:**"); logger.log_code(premarket_card_dict)
                    else:
                        premarket_cards_output[ticker] = premarket_card_dict
                        processed_count += 1
                        logger.log(f"      ...Success: Tactical card for {ticker} generated.")
                except json.JSONDecodeError as e:
                    logger.log(f"      ...Error {ticker}: AI response not valid JSON. Error: {e}")
            else:
                 logger.log(f"      ...Error {ticker}: No response from Pre-Market AI.")
            if i < len(eod_card_rows) - 1: time.sleep(0.75)

        st.session_state['premarket_cards'] = premarket_cards_output
        logger.log(f"--- Workflow 2a-Part2 Complete: Generated pre-market cards for {processed_count}/{len(eod_card_rows)} tickers ---")
        return True

    except Exception as e: logger.log(f"Unexpected error in generate_premarket_cards: {e}"); st.session_state['premarket_cards'] = {}; return False
    finally:
        if conn: conn.close()


# --- Constants for Tactical Screener ---
REQUIRED_PREMARKET_CARD_KEYS = ['marketNote', 'confidence', 'preMarketContext', 'technicalStructure', 'openingTradePlan', 'alternativePlan']
MARKDOWN_FENCE_PATTERN = r"^\s*```[a-zA-Z]*\s*\n?|\n?\s*```\s*$"
SCREENER_ERROR_PREFIX = "Screener Error: "

# --- Workflow 2b: Tactical Screener ---
def run_tactical_screener(market_condition: str, pre_market_cards: dict, economy_card: dict, api_key_to_use: str, logger: AppLogger):
    """
    Ranks pre-market tactical setups using macro context from the economy card.
    Uses "Acceptance vs. Rejection" philosophy based on EMH.
    """
    logger.log("--- Starting Workflow 2b: Final Tactical Screener Ranking ---")
    
    if not pre_market_cards:
        logger.log("Error: No Pre-Market Cards provided.")
        return f"{SCREENER_ERROR_PREFIX}No pre-market cards provided."
    
    logger.log(f"1. Preparing {len(pre_market_cards)} pre-market cards...")
    
    # Build economy context for the prompt
    economy_context_text = "Not available."
    if economy_card:
        try:
            economy_context_text = json.dumps(economy_card, indent=2)
            logger.log("   ...Economy Card context loaded for screener.")
        except Exception as e:
            logger.log(f"   ...Warn: Could not serialize Economy Card to JSON: {e}")
            economy_context_text = str(economy_card)
    else:
        logger.log("   ...Warn: No Economy Card provided. Screener will lack macro context.")
    
    logger.log("2. Building FINAL 'Smarter Ranking' Prompt...")
    
    screener_system_prompt_final = (
        "You are an expert Head Trader using Efficient Market Hypothesis (EMH) for opening trades. Core philosophy: 'Acceptance vs. Rejection'.\n"
        "**Core Philosophy:** PreMarket shows new 'fair value'. Trade is ACCEPTANCE (moves beyond) or REJECTION (fails/reverses). Gap TO major level = high-prob REJECTION.\n"
        "**Macro Context:** You MUST consider the global economy card. If macro is risk-off, be skeptical of bullish breakouts. If risk-on, favor continuation patterns.\n"
        "**Reasoning:** 1. Read macro context from Economy Card. 2. Read `preMarketContext` for each stock. 3. Compare `livePrice` to `majorSupport`/`Resistance` -> Accept/Reject? 4. Select matching plan (`opening` or `alternative`). 5. Rank by clarity of 'trap' AND alignment with macro. 6. Output 'Trade Briefing'.\n"
        "**Output Format:** For EACH ranked stock:\n"
        "### **[Rank]. [Ticker]**\n"
        "- **Selected Plan:** [Name of ACTIVE plan]\n"
        "- **Macro Alignment:** [How this setup aligns or conflicts with the macro view]\n"
        "- **Rationale (Acceptance vs. Rejection):** [Explain WHY: gap, level, trapped participants]\n"
        "- **Full Plan Details:** [JSON object: trigger, invalidation, knownP, expectedP of selected plan]\n"
        "- **Key Risk:** [Main risk invalidating plan]\n"
        "Output ONLY the ranked list in structured Markdown."
    )
    
    # Prepare candidate list
    candidate_list_text = ""
    valid_count = 0
    
    for ticker, card_dict in pre_market_cards.items():
        if isinstance(card_dict, dict):
            if all(key in card_dict for key in REQUIRED_PREMARKET_CARD_KEYS):
                candidate_list_text += f"\n--- Candidate: {ticker} ---\n{json.dumps(card_dict, indent=2)}\n--- End Candidate: {ticker} ---\n"
                valid_count += 1
            else:
                logger.log(f"   ...Skip {ticker}: Pre-market card invalid structure.")
        else:
            logger.log(f"   ...Skip {ticker}: Invalid data type.")
    
    if not candidate_list_text:
        logger.log("Error: No valid cards to send.")
        return f"{SCREENER_ERROR_PREFIX}No valid cards after validation."
    
    logger.log(f"   ...Sending {valid_count} candidates with macro context.")
    
    # Build the final prompt with economy card context
    prompt_final = f"""[Context]
- **Global Economy Card (Macro View):**
{economy_context_text}

- **Overall Market Condition (User Input):** "{market_condition}"

[Data]
- **Candidate Stocks (Full JSON 'Pre-Market Tactical Cards'):**
{candidate_list_text}

[Action]
Provide ranked list using 'Trade Briefing' Markdown format for EACH stock. 
**CRITICAL:** Your ranking MUST consider the macro context from the Economy Card. For example, if the economy card shows risk-off sentiment (bonds up, equities weak), prioritize short setups or rejection patterns. If risk-on, favor acceptance/breakout patterns.
Ensure 'Full Plan Details' is valid JSON."""
    
    key = api_key_to_use
    key_idx = API_KEYS.index(key) if key in API_KEYS else -1
    logger.log(f"3. Calling Final Screener AI (key #{key_idx + 1})...")
    
    ranked_list_details_text = call_gemini_api(prompt_final, key, screener_system_prompt_final, logger)
    
    if not ranked_list_details_text:
        logger.log("Error: No response from Screener AI.")
        return f"{SCREENER_ERROR_PREFIX}AI did not return a response."
    
    logger.log("4. Received detailed ranked list.")
    logger.log("**Raw AI Response (Screener):**")
    logger.log_code(ranked_list_details_text, language='markdown')
    logger.log("--- FINAL SCREENER COMPLETE ---")
    
    # Clean up markdown code fences if present
    cleaned_list = re.sub(MARKDOWN_FENCE_PATTERN, "", ranked_list_details_text).strip()
    
    return cleaned_list


# --- 5. Streamlit Application UI (5 Tabs) ---

st.set_page_config(page_title="Analyst Pipeline Engine (FINAL)", layout="wide")
st.title("Analyst Pipeline Engine (Capital.com Pre-Market)") # Updated title

# --- NEW: UI Validation Check for Gemini API Keys ---
if not API_KEYS or not isinstance(API_KEYS, list) or len(API_KEYS) == 0:
    st.error("Error: Gemini API keys not found in st.secrets.")
    st.info("Please add your Gemini API keys to your `.streamlit/secrets.toml` file in a list format:")
    st.code("""
[gemini]
api_keys = [
    "AIzaSy...key1",
    "AIzaSy...key2",
]
    """)
    st.stop() # Stop the app if no keys are loaded
else:
    # This message can be removed if it's too noisy
    # st.success(f"Successfully loaded {len(API_KEYS)} Gemini API keys from st.secrets.")
    pass


# --- Helper Functions (Unchanged) ---
def get_all_tickers_from_db():
    if not os.path.exists(DATABASE_FILE): return []
    conn=None; tickers=[]
    try: conn=sqlite3.connect(DATABASE_FILE); tickers=pd.read_sql_query("SELECT DISTINCT ticker FROM stocks ORDER BY ticker ASC",conn)['ticker'].tolist()
    except Exception as e: st.error(f"Err fetch tickers:{e}")
    finally:
        if conn: conn.close()
    return tickers

def extract_json_field(json_string, field_path, default="N/A"):
    if not json_string or pd.isna(json_string): return default
    try:
        data=json.loads(json_string); keys=field_path.split('.'); value=data
        for i, key in enumerate(keys):
            if not isinstance(value, dict):
                 if key.isdigit() and isinstance(value, list) and int(key) < len(value): value = value[int(key)]
                 else: return default
            else: value = value.get(key)
            if value is None: return default
        if isinstance(value, list): return " ".join(map(str, value)) or default
        return str(value) if value is not None else default
    except Exception: return "JSON Err"

# --- Initialize session state ---
if 'premarket_cards' not in st.session_state: st.session_state['premarket_cards'] = {}
# --- NEW: Add economy cards to session state ---
if 'eod_economy_card' not in st.session_state: st.session_state['eod_economy_card'] = None
if 'last_selected_tickers' not in st.session_state: st.session_state['last_selected_tickers'] = []
for key in ['premarket_cards', 'eod_economy_card', 'premarket_economy_card', 'proximity_scan_results', 'last_selected_tickers']:
    if key not in st.session_state: st.session_state[key] = {} if 'cards' in key or 'results' in key else [] if 'tickers' in key else None
# Cache Capital.com session
if 'capital_session' not in st.session_state: 
    # Store string isoformat for session state safety
    st.session_state['capital_session'] = {"cst": None, "xst": None, "time_utc_iso": None} 


# --- Define 5 Tabs ---
tab_editor, tab_runner_eod, tab_preflight, tab_viewer, tab_screener = st.tabs([
    "Context & EOD Card Editor", # Combined Editor
    "Pipeline Runner (EOD)",     # Workflow 1
    "Pre-Flight Check",          # Workflow 2a
    "Battle Card Viewer",        # Comparison Viewer
    "Trade Screener (Tactical)"  # Workflow 2b
])

# --- TAB 1: Context & EOD Card Editor (Unchanged) ---
with tab_editor:
    st.header("Context & EOD Card Editor")
    st.caption("Set `Historical Notes` & review/edit EOD Cards.")

    # --- NEW: Economy Card Editor ---
    st.markdown("---")
    st.subheader("Global Economy Card")
    st.caption("This is the single, global context card for the entire market.")
    
    conn_eco = None
    try:
        conn_eco = sqlite3.connect(DATABASE_FILE)
        cursor_eco = conn_eco.cursor()
        cursor_eco.execute("SELECT economy_card_json FROM market_context WHERE context_id = 1")
        eco_data = cursor_eco.fetchone()
        
        eco_json_text = DEFAULT_ECONOMY_CARD_JSON
        if eco_data and eco_data[0]:
            try:
                eco_json_text = json.dumps(json.loads(eco_data[0]), indent=2)
            except (json.JSONDecodeError, TypeError):
                eco_json_text = eco_data[0] # Show raw text if it's not valid JSON

        with st.form("economy_card_form"):
            edited_eco_json = st.text_area("Economy Card JSON:", value=eco_json_text, height=400, key="eco_json_editor")
            if st.form_submit_button("Save Economy Card", use_container_width=True):
                try:
                    # Validate JSON before saving
                    valid_json = json.loads(edited_eco_json)
                    json_to_save = json.dumps(valid_json, indent=2)
                    cursor_eco.execute("UPDATE market_context SET economy_card_json = ?, last_updated = ? WHERE context_id = 1", (json_to_save, date.today().isoformat()))
                    conn_eco.commit()
                    st.success("Global Economy Card saved successfully!")
                    st.rerun()
                except json.JSONDecodeError:
                    st.error("Invalid JSON format. Please correct and try again.")
                except sqlite3.Error as e:
                    st.error(f"Database error saving economy card: {e}")

    except sqlite3.Error as e:
        st.error(f"Database error loading economy card: {e}")
    finally:
        if conn_eco:
            conn_eco.close()
    # --- END NEW SECTION ---

    st.markdown("---")
    st.subheader("Individual Stock Cards")
    if not os.path.exists(DATABASE_FILE): st.error(f"DB not found.")
    else:
        all_tickers = get_all_tickers_from_db(); col1, col2 = st.columns([2,1])
        with col1: options = [""] + all_tickers; selected_ticker = st.selectbox("Ticker:", options, key="selected_ticker_editor")
        with col2: new_ticker = st.text_input("Or Add:", key="new_ticker_editor_text")
        ticker_edit = new_ticker.upper() if new_ticker else selected_ticker
        if new_ticker and selected_ticker: st.warning("Clear one."); ticker_edit = ""
        if ticker_edit:
            st.markdown("---"); st.subheader(f"Edit: ${ticker_edit}")
            conn=None
            try:
                conn=sqlite3.connect(DATABASE_FILE); conn.row_factory=sqlite3.Row; cursor=conn.cursor()
                cursor.execute("SELECT historical_level_notes, company_overview_card_json FROM stocks WHERE ticker=?", (ticker_edit,)); data=cursor.fetchone()
                notes = data["historical_level_notes"] if data and data["historical_level_notes"] else ""
                json_txt = DEFAULT_COMPANY_OVERVIEW_JSON.replace("TICKER", ticker_edit)
                # --- FIX: Correct indentation for try/except ---
                if data and data["company_overview_card_json"]:
                    try:
                        json_txt = json.dumps(json.loads(data["company_overview_card_json"]), indent=2)
                    except:
                        json_txt = data["company_overview_card_json"]
                # --- End FIX ---
                with st.expander("Static: Historical Notes", expanded=True):
                    with st.form(f"notes_form_{ticker_edit}"):
                        notes_val = st.text_area("Notes:", value=notes, key=f"hist_{ticker_edit}", height=200)
                        if st.form_submit_button("Save Notes", use_container_width=True):
                            try: 
                                cursor.execute("INSERT INTO stocks (ticker,historical_level_notes,last_updated) VALUES(?,?,?) ON CONFLICT(ticker) DO UPDATE SET historical_level_notes=excluded.historical_level_notes, last_updated=excluded.last_updated", (ticker_edit, notes_val, date.today().isoformat()))
                                conn.commit(); st.success("Notes saved!"); 
                                # if new_ticker: st.session_state.new_ticker_editor_text = "" # This was the error
                                st.rerun()
                            except sqlite3.Error as e: st.error(f"DB err: {e}")
                st.markdown("---"); st.subheader("Dynamic: EOD Card (Editable)"); st.caption("Review/correct AI's EOD JSON.")
                json_edit = st.text_area("EOD JSON:", value=json_txt, height=600, key=f"json_{ticker_edit}")
                if st.button("Save EOD Card", use_container_width=True):
                    try: 
                        valid=json.loads(json_edit); json_save=json.dumps(valid, indent=2); 
                        cursor.execute("INSERT INTO stocks (ticker,company_overview_card_json,last_updated) VALUES(?,?,?) ON CONFLICT(ticker) DO UPDATE SET company_overview_card_json=excluded.company_overview_card_json, last_updated=excluded.last_updated", (ticker_edit, json_save, date.today().isoformat()))
                        conn.commit(); st.success("EOD Card saved!"); st.rerun()
                    except json.JSONDecodeError: st.error("Invalid JSON.")
                    except sqlite3.Error as e: st.error(f"DB err: {e}")
            except sqlite3.Error as e: st.error(f"DB err: {e}")
            finally:
                if conn: conn.close()

# --- TAB 2: Pipeline Runner (EOD - Workflow 1) (RESTRUCTURED) ---
with tab_runner_eod:
    st.header("Pipeline Runner (EOD Update)")
    st.caption("Run EOD updates for individual stocks and the global economy card.")
    st.info(f"{len(API_KEYS)} Gemini API keys available in rotation.")

    col_stocks, col_economy = st.columns(2)

    # --- Column 1: Individual Stock Updates ---
    with col_stocks:
        st.subheader("1. Individual Stock Updates")
        st.caption("`INPUT:` EOD Summary Text + Previous Day's Company Card + Historical Notes")
        macro_context_input = st.text_area("Overall Market/Company News Summary:", height=120, key="eod_macro_context", help="A summary of the day's overall market sentiment or major news affecting your universe of stocks. This context will be given to the AI for EACH stock update.")
        raw_txt_stocks = st.text_area("Paste Stock EOD Summaries:", height=300, key="eod_raw_stocks", help="Paste the text output from the processor app for individual stocks like AAPL, MSFT, etc.")
        if st.button("Run Stock EOD Updates", use_container_width=True, key="run_eod_stocks"):
            if not raw_txt_stocks: st.warning("Paste stock summary text.")
            elif not os.path.exists(DATABASE_FILE): st.error("Database file not found.")
            else:
                summaries = re.split(r"(Summary:\s*\w+\s*\|)", raw_txt_stocks)
                processed = []
                if len(summaries) > 1 and not summaries[0].strip().startswith("Summary:"):
                    if summaries[0].strip(): st.warning("Ignoring text before first summary.")
                    summaries = summaries[1:]
                for i in range(0, len(summaries), 2):
                    if i + 1 < len(summaries): processed.append(summaries[i] + summaries[i+1])
                
                if not processed: st.warning("No valid stock summaries found.")
                else:
                    st.success(f"Found {len(processed)} stock summaries.")
                    logs_stocks = st.expander("Stock Update Logs", True)
                    logger_stocks = AppLogger(logs_stocks)
                    t_start = time.time()
                    for i, s in enumerate(processed):
                        key = random.choice(API_KEYS)
                        ticker = parse_raw_summary(s).get('ticker')
                        if not ticker:
                            logger_stocks.log(f"SKIP: Could not parse ticker from summary: {s[:100]}...")
                            continue
                        try:
                            # Pass the new macro context summary to the function
                            update_stock_note(ticker, s, macro_context_input, key, logger_stocks)
                        except Exception as e:
                            logger_stocks.log(f"!!! EOD ERROR for {ticker}: {e}")
                        if i < len(processed) - 1:
                            logger_stocks.log("   ...waiting 1s...")
                            time.sleep(1)
                    t_end = time.time()
                    logger_stocks.log(f"--- Stock EOD Updates Done (Total Time: {t_end - t_start:.2f}s) ---")
                    st.info("Stock updates complete.")

    # --- Column 2: Global Economy Card Update ---
    with col_economy:
        st.subheader("2. Global Economy Card Update")
        st.caption("`INPUT:` Manual Macro Summary + ETF/Inter-Market EOD Summaries + Previous Day's Economy Card")
        manual_macro_summary = st.text_area("Your Manual Daily Macro Summary:", height=100, key="eod_manual_macro", help="Your high-level take on the day's market action and news.")
        raw_txt_etfs = st.text_area("Paste ETF EOD Summaries:", height=200, key="eod_raw_etfs", help="Paste the text output from the processor app for key ETFs like SPY, QQQ, XLF, etc.")
        
        if st.button("Run Economy Card EOD Update", use_container_width=True, key="run_eod_economy"):
            if not manual_macro_summary or not raw_txt_etfs:
                st.warning("Please provide both a manual summary and ETF summaries.")
            elif not os.path.exists(DATABASE_FILE):
                st.error("Database file not found.")
            else:
                logs_economy = st.expander("Economy Card Update Logs", True)
                logger_economy = AppLogger(logs_economy)
                key_eco = random.choice(API_KEYS)
                with st.spinner("Updating Economy Card..."):
                    try:
                        update_economy_card(manual_macro_summary, raw_txt_etfs, key_eco, logger_economy)
                        st.success("Economy Card update process finished.")
                    except Exception as e:
                        logger_economy.log(f"!!! ECONOMY CARD EOD ERROR: {e}")
                        st.error("An error occurred during the Economy Card update.")


# --- TAB 3: Pre-Flight Check (Workflow 2a) (RESTRUCTURED) ---
with tab_preflight:
    st.header("Tactical Update: Pre-Flight Check")
    logger_pf = AppLogger(st.expander("Logs", True))
    
    # Step 1: Capital.com Auth
    st.subheader("1. Capital.com Status")
    if not st.session_state.capital_session.get("cst"):
        if st.button("Create Capital.com Session", use_container_width=True):
            cst, xst, _ = create_capital_session(logger_pf)
            if cst: st.session_state.capital_session = {"cst": cst, "xst": xst, "time_utc_iso": datetime.now(timezone.utc).isoformat()}; st.rerun()
        st.stop()
    else:
        st.success(f"Capital.com session active.")

    # Step 2: Generate Pre-Market Economy Card (Independent)
    st.markdown("---")
    st.subheader("2. Generate Pre-Market Economy Card")
    premarket_macro_news_input = st.text_area("Enter Pre-Market Macro News:", placeholder="e.g., UK CPI hotter than expected, German ZEW survey weak...", height=100, key="pm_macro_news")
    if st.button("Generate Pre-Market Economy Card", use_container_width=True, key="gen_pm_eco_card"):
        with st.spinner("Generating Pre-Market Economy Card..."):
            generate_premarket_economy_card(
                premarket_macro_news_input, 
                logger_pf, 
                st.session_state.capital_session["cst"], 
                st.session_state.capital_session["xst"]
            )
        if st.session_state.premarket_economy_card:
            st.success("Pre-Market Economy Card generated successfully.")
        else:
            st.error("Failed to generate Pre-Market Economy Card.")

    # Display the generated card for confirmation
    if st.session_state.premarket_economy_card:
        with st.expander("View Generated Pre-Market Economy Card", expanded=False):
            st.json(st.session_state.premarket_economy_card)

    # Step 3: Company Card Workflow
    st.markdown("---")
    st.subheader("3. Company Card Workflow")
    
    # Sub-step A: Automated Proximity Scan
    st.markdown("##### **Step 3a: Scan for Proximity**")
    proximity_pct = st.slider("Proximity Filter (%)", 0.1, 10.0, 2.5, 0.1, help="Filter for stocks trading within this % distance of a major S/R level.")
    if st.button("Scan All Tickers for Proximity", use_container_width=True):
        with st.spinner("Scanning all tickers..."):
            conn = sqlite3.connect(DATABASE_FILE)
            all_eod_cards = pd.read_sql_query("SELECT ticker, company_overview_card_json FROM stocks WHERE company_overview_card_json IS NOT NULL", conn)
            conn.close()
            
            scan_results = []
            for _, row in all_eod_cards.iterrows():
                ticker, card_json = row['ticker'], row['company_overview_card_json']
                try:
                    card = json.loads(card_json)
                    support_str = str(card.get('technicalStructure', {}).get('majorSupport', ''))
                    resist_str = str(card.get('technicalStructure', {}).get('majorResistance', ''))
                    s_match, r_match = re.search(r'(\d+\.?\d*)', support_str), re.search(r'(\d+\.?\d*)', resist_str)
                    if not (s_match and r_match): continue
                    support, resistance = float(s_match.group(1)), float(r_match.group(1))
                    
                    bid, offer = get_capital_current_price(ticker, st.session_state.capital_session["cst"], st.session_state.capital_session["xst"], logger_pf)
                    if not bid: continue
                    live_price = (bid + offer) / 2
                    
                    prox_pct = (min(abs(live_price - support), abs(live_price - resistance)) / live_price) * 100
                    if prox_pct <= proximity_pct:
                        scan_results.append({"Ticker": ticker, "Proximity (%)": f"{prox_pct:.2f}", "Live Price": f"${live_price:.2f}", "Support": f"${support:.2f}", "Resistance": f"${resistance:.2f}"})
                except Exception as e:
                    logger_pf.log(f"Error scanning {ticker}: {e}")
            
            st.session_state.proximity_scan_results = sorted(scan_results, key=lambda x: float(x['Proximity (%)']))
            st.rerun()

    # Sub-step B: Manual Curation & Generation
    if st.session_state.proximity_scan_results:
        st.markdown("##### **Step 3b: Curate and Generate Cards**")
        st.dataframe(pd.DataFrame(st.session_state.proximity_scan_results), use_container_width=True)
        
        interesting_tickers = [res['Ticker'] for res in st.session_state.proximity_scan_results]
        
        with st.form("curation_form"):
            curated_tickers = st.multiselect("Select tickers to generate cards for:", options=interesting_tickers, default=st.session_state.get('last_selected_tickers', []))
            overnight_news = st.text_area("Enter Company-Specific News:", placeholder="e.g., SNOW beat earnings...", height=100)
            submitted = st.form_submit_button("Generate Pre-Market Battle Cards", use_container_width=True)

            if submitted:
                if not curated_tickers:
                    st.warning("Please select at least one ticker.")
                else:
                    st.session_state['last_selected_tickers'] = curated_tickers
                    active_economy_card = st.session_state.premarket_economy_card or st.session_state.eod_economy_card
                    
                    if not active_economy_card:
                        st.error("No active Economy Card. Please generate the Pre-Market Economy Card in Step 2, or ensure an EOD card exists.")
                    else:
                        with st.spinner(f"Generating cards for {len(curated_tickers)} tickers..."):
                            generate_premarket_tactical_cards(curated_tickers, overnight_news, active_economy_card, logger_pf, st.session_state.capital_session["cst"], st.session_state.capital_session["xst"])
                        st.success("Card generation complete. See Viewer and Screener tabs.")


# --- TAB 4: Battle Card Viewer (Unchanged) ---
with tab_viewer:
    st.header("Review: Battle Card Viewer")
    st.caption("Compare EOD Card vs Pre-Market Card.")
    if not os.path.exists(DATABASE_FILE): st.error("DB missing.")
    else:
        all_tickers_v = get_all_tickers_from_db()
        pm_tickers = list(st.session_state.get('premarket_cards',{}).keys())
        opts_v = [""] + sorted(pm_tickers) + sorted([t for t in all_tickers_v if t not in pm_tickers])
        if not all_tickers_v: st.warning("No tickers in DB.")
        else:
            if 'selected_ticker_viewer' not in st.session_state: st.session_state['selected_ticker_viewer']=""
            sel_ticker_v = st.selectbox("Ticker:", options=opts_v, key="selected_ticker_viewer")
            if sel_ticker_v:
                col1_v, col2_v = st.columns(2)
                with col1_v: # EOD Card
                    st.subheader("EOD Card (DB)"); conn_eod=None
                    try:
                        conn_eod=sqlite3.connect(DATABASE_FILE); cur=conn_eod.cursor(); cur.execute("SELECT company_overview_card_json FROM stocks WHERE ticker=?", (sel_ticker_v,)); row=cur.fetchone()
                        if row and row[0]:
                            try: st.json(json.loads(row[0]), expanded=False)
                            except json.JSONDecodeError: st.error("Invalid EOD JSON."); st.code(row[0])
                        else: st.warning("No EOD card.")
                    except sqlite3.Error as e: st.error(f"DB err EOD: {e}")
                    finally:
                        if conn_eod: conn_eod.close()
                with col2_v: # Pre-Market Card
                    st.subheader("Pre-Market Card (Memory)");
                    if sel_ticker_v in st.session_state.get('premarket_cards',{}):
                        pm_card_v = st.session_state['premarket_cards'][sel_ticker_v]
                        if isinstance(pm_card_v, dict):
                             st.json(pm_card_v, expanded=True)
                        else:
                             st.error("PM card data invalid."); st.code(str(pm_card_v))
                        st.markdown("---"); st.subheader("Key Data for Screener"); st.caption("(From Pre-Market Card)")
                        def get_v_field(d,p,df="N/A"): # Local helper
                            if not isinstance(d, dict): return df
                            k=p.split('.'); v=d
                            try:
                                for key in k: v=v.get(key) if isinstance(v,dict) else None
                                if isinstance(v,list): return " ".join(map(str,v)) or df
                                return str(v) if v is not None else df
                            except: return df
                        if isinstance(pm_card_v, dict):
                            fields_v = {
                                "Confidence":'confidence',"Briefing":'screener_briefing',
                                "Open Plan":'openingTradePlan.planName',"Alt Plan":'alternativePlan.planName',
                                "Action":'technicalStructure.keyAction',"Support":'technicalStructure.majorSupport',
                                "Resistance":'technicalStructure.majorResistance',"Live Price":'preMarketContext.livePrice',
                                "PM Summary":'preMarketContext.tacticalSummary'
                            }
                            for name, path in fields_v.items(): st.markdown(f"**{name}:** `{get_v_field(pm_card_v, path)}`")
                        else:
                             st.warning("Cannot extract fields, PM card invalid.")
                    else: st.info("No Pre-Market card generated.")


# --- TAB 5: Trade Screener (Workflow 2b) (COMPLETE & CORRECTED) ---
with tab_screener:
    st.header("Action: Trade Screener (Workflow 2b)")
    st.caption("Ranks tactical setups from Pre-Flight Check using macro and micro context.")
    st.caption("`INPUT:` Active Economy Card + All Generated Pre-Market Company Cards + User's Market Condition Text")
    
    # --- NEW: Display Economy Card Context ---
    st.subheader("Market Context for Screener")
    # Determine which economy card is active for the screener
    active_economy_card = st.session_state.get('premarket_economy_card') or st.session_state.get('eod_economy_card')

    if active_economy_card:
        card_type = "Pre-Market" if st.session_state.get('premarket_economy_card') else "EOD"
        with st.expander(f"Using {card_type} Economy Card", expanded=False):
            st.json(active_economy_card)
    else:
        st.warning("No Economy Card has been generated yet. Screener will lack macro context.")

    st.markdown("---")

    pm_cards_avail = st.session_state.get('premarket_cards',{})
    if not pm_cards_avail: st.error("Generate Pre-Market Cards first in 'Pre-Flight Check' tab."); st.stop()
    
    st.info(f"**{len(pm_cards_avail)} Pre-Market Cards ready for ranking.**")
    
    col1_s, col2_s = st.columns([3,1])
    with col1_s: market_cond_s = st.text_area("Market Condition:", placeholder="e.g., Risk-on after soft CPI, watching tech.", height=100, key="scr_market")
    with col2_s: conf_filter_s = st.selectbox("Filter Confidence:", ["All","High","Medium","Low"], key="scr_conf")
    
    if st.button("Run TACTICAL Screener", use_container_width=True, key="run_scr"):
        if not market_cond_s: st.warning("Provide Market Condition.")
        else:
            cards_scr = {};
            if conf_filter_s=="All": cards_scr=pm_cards_avail
            else: cards_scr={t:c for t,c in pm_cards_avail.items() if str(c.get('confidence','')).startswith(conf_filter_s)}
            
            if not cards_scr: st.warning(f"No cards match filter '{conf_filter_s}'.")
            else:
                logs_scr = st.expander("Logs", True); logger_scr = AppLogger(logs_scr)
                key_scr = random.choice(API_KEYS)
                with st.spinner(f"AI ranking {len(cards_scr)} cards with full context..."):
                    # --- CORRECTED FUNCTION CALL ---
                    # Pass the active_economy_card to the screener function
                    result_scr = run_tactical_screener(
                        market_condition=market_cond_s, 
                        pre_market_cards=cards_scr, 
                        economy_card=active_economy_card, # Pass the economy card
                        api_key_to_use=key_scr, 
                        logger=logger_scr
                    )
                st.markdown("---"); st.subheader(f"Ranked Briefings (Filter: {conf_filter_s})")
                if result_scr: st.markdown(result_scr, unsafe_allow_html=True)
                else: st.error("Screener failed to return results.")


# --- Command Line Test Example (Unchanged) ---
if __name__ == "__main__":
    print("Run with: streamlit run pipeline_engine.py")