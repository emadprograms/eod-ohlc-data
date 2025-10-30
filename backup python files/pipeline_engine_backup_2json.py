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
# --- US Market Timezone Constants ---
PREMARKET_START_HOUR = 4
PREMARKET_END_HOUR = 9
PREMARKET_END_MINUTE = 30


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
         
    if not current_api_key: 
        logger.log("Error: No API Key provided for this call, selecting one at random.")
        current_api_key = random.choice(API_KEYS) # Select random key if none provided
        
    for i in range(max_retries):
        gemini_api_url = f"{API_URL}?key={current_api_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}], "systemInstruction": {"parts": [{"text": system_prompt}]}}
        headers = {'Content-Type': 'application/json'}
        current_key_index = API_KEYS.index(current_api_key) if current_api_key in API_KEYS else -1
        try:
            response = requests.post(gemini_api_url, headers=headers, data=json.dumps(payload), timeout=90)
            if response.status_code in [429, 503]:
                logger.log(f"API Error {response.status_code} on Key #{current_key_index + 1}. Switching...")
                if current_key_index != -1 and len(API_KEYS) > 1:
                    # Switch to a new *random* key to avoid sequential failures
                    new_key_index = random.randint(0, len(API_KEYS) - 1)
                    # Ensure we don't pick the same key if possible
                    if len(API_KEYS) > 1:
                        while new_key_index == current_key_index:
                            new_key_index = random.randint(0, len(API_KEYS) - 1)
                    current_api_key = API_KEYS[new_key_index]
                    logger.log(f"   ...Switched to random Key #{new_key_index + 1}.")
                else: logger.log("   ...Cannot switch (only one key?). Retrying same key.")
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
def update_stock_note(ticker_to_update: str, new_raw_text: str, api_key_to_use: str, logger: AppLogger):
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
        prompt = f"""[Historical Notes for {ticker_to_update}]\n(MAJOR structural levels.)\n{historical_notes}\n\n[Yesterday's Company Overview Card for {ticker_to_update}]\n(Update dynamic parts based on Today's EOD Action relative to MAJOR levels. Preserve statics.)\n{json.dumps(previous_overview_card_dict, indent=2)}\n\n[Today's New Price Action Summary]\n(Objective 5-minute data for full day.)\n{new_raw_text}\n\n[Task for Today: {trade_date} (EOD)]\nGenerate NEW card JSON. Focus on MAJOR levels & update PLANS for TOMORROW.\n**CRITICAL:** 1. PRESERVE STATIC: Copy `fundamentalContext`, `sector`, `companyDescription`. 2. RESPECT MAJOR LEVELS: `majorSupport`/`majorResistance` READ-ONLY unless decisively broken (2-3 day confirm). 3. UPDATE `keyAction`: APPEND EOD action relative to MAJOR levels. 4. UPDATE PLANS: Update BOTH plans based on EOD `keyAction` at MAJOR levels for TOMORROW. 5. UPDATE OTHER DYNAMICS: Update other fields supporting plans/`keyAction`. Minor levels only in `keyAction`/`tradingRange`. 6. `confidence` Rationale: Base on plan clarity relative to MAJOR levels.\n[Output Format] ONLY single valid JSON object. No markdown."""
        
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

# ---
# --- Capital.com Authentication & Data Functions (Imported from Tester) ---
# ---

@st.cache_resource(ttl=1800) # Cache session for 30 minutes
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


# --- Workflow 2a - Generate Pre-Market Tactical Cards (REWRITTEN for Capital.com) ---
def generate_premarket_tactical_cards(selected_tickers: list, overnight_news: str, logger: AppLogger, cst: str, xst: str):
    logger.log("--- Starting Workflow 2a: Generate Pre-Market Tactical Cards ---")
    premarket_cards_output = {}
    if not selected_tickers: logger.log("No tickers selected."); return False

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
             "You are an expert market structure analyst creating a TACTICAL plan for the OPENING BELL. Focus ONLY on participant motivation at MAJOR levels from [Historical Notes]/[EOD Card]. You get [Historical Notes], [Yesterday's EOD Card], [Pre-Market Story], [Live Price/Gap], [Overnight News]. Generate NEW 'Pre-Market Tactical Card' JSON. ANALYZE GAP/STORY vs MAJOR LEVELS & UPDATE TRADE PLANS based on Acceptance vs Rejection. PRESERVE `fundamentalContext`, `sector`, `companyDescription`, `majorSupport`, `majorResistance`. UPDATE ALL OTHER dynamic fields (`confidence`, `screener_briefing`, `keyAction` [APPEND pre-market story], etc.) to reflect pre-market reality. Prioritize current price/nearest major level for plans. Discard irrelevant EOD plans if gap is large. Output ONLY single, valid JSON."
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

            # --- *** STOP CONDITION (Per Ticker) *** ---
            live_price = live_prices.get(ticker)
            df_pm = bar_dataframes.get(ticker) # Can be None if fetch failed, or Empty if no PM bars found

            if not live_price or df_pm is None: # Critical fail if NO live price OR bar fetch FAILED (None)
                 logger.log(f"   ...**STOPPING AI Call for {ticker}: Missing Live Price or 5-min Bar Data Fetch Failed.**")
                 logger.log(f"      (Live Price found: {bool(live_price)}, Bar Data fetch status: {'Success (Empty)' if isinstance(df_pm, pd.DataFrame) else 'Failed (None)'})")
                 continue

            # --- Process data and build prompt (df_pm can be empty, that's OK) ---
            logger.log(f"**Processing {len(df_pm)} 5-min bars for Pre-Market Story...**")
            pre_market_story_text = process_premarket_bars_to_summary(ticker, df_pm, live_price, logger) # Pass live_price
            logger.log("**Generated Pre-Market Story (Input):**")
            logger.log_code(pre_market_story_text, 'text')
            
            live_price_for_prompt = f"~${live_price:.2f}"
            time_str = datetime.now(US_EASTERN).strftime('%Y-%m-%d %H:%M:%S %Z')
            pre_market_context_str = f"Current Price: {live_price_for_prompt} (@ {time_str})."
            try: # Calculate gap
                 basic_context=eod_card_dict.get("basicContext",{}); price_trend=basic_context.get("priceTrend","")
                 y_close_str = str(price_trend).split("|")[0].replace("~","").replace("$","").strip()
                 if y_close_str: y_close=float(y_close_str); gap_pct=((live_price-y_close)/y_close)*100; pre_market_context_str += f" Gap: {gap_pct:+.2f}%."
            except Exception as e: logger.log(f"      ...Warn: Error calculating gap: {e}")
            logger.log(f"**Live Price / Gap String (Input):** `{pre_market_context_str}`")
            logger.log(f"**Overnight News (Input):** `{overnight_news or 'N/A'}`")

            prompt = f"""
            [Historical Notes for {ticker}]
            (MAJOR structural levels)
            {historical_notes_pm}

            [Yesterday's EOD Card for {ticker}]
            (Base JSON)
            {json.dumps(eod_card_dict, indent=2)}

            [Pre-Market Data / News for {ticker}]
            - Live Price/Gap: {pre_market_context_str}
            - Pre-Market Story (from 5-min bars): {pre_market_story_text}
            - General News: {overnight_news or "N/A"}

            [Task]
            Generate NEW "Pre-Market Tactical Card" JSON for open ({date.today().isoformat()}).
            FOCUS ON GAP & PRE-MARKET STORY vs MAJOR LEVELS. Update PLANS based on current price.
            PRESERVE statics (`fundamentalContext`, `sector`, `companyDescription`, `majorSupport`, `majorResistance`).
            UPDATE ALL OTHER dynamic fields (`confidence`, `screener_briefing`, `keyAction` [APPEND PM story], etc.) to reflect tactical situation.
            
            [Output Format Constraint]
            Output ONLY single, valid JSON object. No ```json markdown.
            """
            logger.log("**Full Prompt Sent to Pre-Market AI:**"); logger.log_code(prompt, language='text')

            key_to_use = random.choice(API_KEYS) # --- USE RANDOM KEY ---
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

                    # Re-Validate
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
            if i < len(eod_card_rows) - 1: time.sleep(0.75) # Reduce delay slightly

        st.session_state['premarket_cards'] = premarket_cards_output
        logger.log(f"--- Workflow 2a Complete: Generated pre-market cards for {processed_count}/{len(eod_card_rows)} tickers ---")
        return True

    except Exception as e: logger.log(f"Unexpected error in generate_premarket_cards: {e}"); st.session_state['premarket_cards'] = {}; return False
    finally:
        if conn: conn.close()


# --- Workflow #2b: The Screener Engine (Unchanged) ---
def run_tactical_screener(market_condition: str, pre_market_cards: dict, api_key_to_use: str, logger: AppLogger):
    # ... (This function remains identical, it just needs the pre_market_cards dict) ...
    logger.log("--- Starting Workflow 2b: Final Tactical Screener Ranking ---")
    if not pre_market_cards: logger.log("Error: No Pre-Market Cards provided."); return "Error: No pre-market cards."
    logger.log(f"1. Preparing {len(pre_market_cards)} pre-market cards...");
    logger.log("2. Building FINAL 'Smarter Ranking' Prompt...")
    screener_system_prompt_final = ( # Prompt asking for detailed briefing
            "You are an expert Head Trader using Efficient Market Hypothesis (EMH) for opening trades. Core philosophy: 'Acceptance vs. Rejection'.\n"
            "**Core Philosophy:** PreMarket shows new 'fair value'. Trade is ACCEPTANCE (moves beyond) or REJECTION (fails/reverses). Gap TO major level = high-prob REJECTION.\n"
            "**Reasoning:** 1. Read `preMarketContext`. 2. Compare `livePrice` to `majorSupport`/`Resistance` -> Accept/Reject? 3. Select matching plan (`opening` or `alternative`). 4. Rank by clarity of 'trap'. 5. Output 'Trade Briefing'.\n"
            "**Output Format:** For EACH ranked stock:\n"
            "### **[Rank]. [Ticker]**\n"
            "- **Selected Plan:** [Name of ACTIVE plan]\n"
            "- **Rationale (Acceptance vs. Rejection):** [Explain WHY: gap, level, trapped participants]\n"
            "- **Full Plan Details:** [JSON object: trigger, invalidation, knownP, expectedP of selected plan]\n"
            "- **Key Risk:** [Main risk invalidating plan]\n"
            "Output ONLY the ranked list in structured Markdown."
        )
    candidate_list_text = ""; valid_count = 0
    for ticker, card_dict in pre_market_cards.items():
         if isinstance(card_dict, dict):
             req_keys_scr = ['marketNote','confidence','preMarketContext','technicalStructure','openingTradePlan','alternativePlan']
             if all(key in card_dict for key in req_keys_scr):
                 candidate_list_text += f"\n--- Candidate: {ticker} ---\n{json.dumps(card_dict, indent=2)}\n--- End Candidate: {ticker} ---\n"; valid_count += 1
             else: logger.log(f"   ...Skip {ticker}: Pre-market card invalid structure.")
         else: logger.log(f"   ...Skip {ticker}: Invalid data type.")
    if not candidate_list_text: logger.log("Error: No valid cards to send."); return "Error: No valid cards."
    logger.log(f"   ...Sending {valid_count} candidates.")
    prompt_final = f"""[Data]\n- **Overall Market Condition:** "{market_condition}"\n- **Candidate Stocks (Full JSON 'Pre-Market Tactical Cards'):**\n{candidate_list_text}\n\n[Action]\nProvide ranked list using 'Trade Briefing' Markdown format for EACH stock. Ensure 'Full Plan Details' is JSON."""
    key = api_key_to_use; key_idx = API_KEYS.index(key) if key in API_KEYS else -1
    logger.log(f"3. Calling Final Screener AI (key #{key_idx + 1})...");
    ranked_list_details_text = call_gemini_api(prompt_final, key, screener_system_prompt_final, logger)
    if not ranked_list_details_text: logger.log("Error: No response from Screener AI."); return "AI failed."
    logger.log("4. Received detailed ranked list.");
    logger.log("**Raw AI Response (Screener):**"); logger.log_code(ranked_list_details_text, language='markdown')
    logger.log("--- FINAL SCREENER COMPLETE ---")
    cleaned_list = re.sub(r"^\s*```[a-zA-Z]*\s*\n?|\n?\s*```\s*$", "", ranked_list_details_text).strip()
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
if 'last_selected_tickers' not in st.session_state: st.session_state['last_selected_tickers'] = []
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
    st.caption("Set `Historical Notes` & review/edit EOD Card.")
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
                if data and data["company_overview_card_json"]:
                    try:
                        json_txt = json.dumps(json.loads(data["company_overview_card_json"]), indent=2)
                    except:
                        json_txt = data["company_overview_card_json"]
                with st.expander("Static: Historical Notes", expanded=True):
                    with st.form(f"notes_form_{ticker_edit}"):
                        notes_val = st.text_area("Notes:", value=notes, key=f"hist_{ticker_edit}", height=200)
                        if st.form_submit_button("Save Notes", use_container_width=True):
                            try: 
                                cursor.execute("INSERT INTO stocks (ticker,historical_level_notes,last_updated) VALUES(?,?,?) ON CONFLICT(ticker) DO UPDATE SET historical_level_notes=excluded.historical_level_notes, last_updated=excluded.last_updated", (ticker_edit, notes_val, date.today().isoformat()))
                                conn.commit(); st.success("Notes saved!"); 
                                if new_ticker: st.session_state.new_ticker_editor_text = "" # Clear new ticker input
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

# --- TAB 2: Pipeline Runner (EOD - Workflow 1) (Unchanged) ---
with tab_runner_eod:
    st.header("Pipeline Runner (EOD Update)")
    st.caption("Paste EOD summaries from Processor.")
    st.success("AI generates NEW EOD card.")
    st.info(f"{len(API_KEYS)} keys in rotation.")
    raw_txt = st.text_area("Paste EOD Summaries:", height=300, key="eod_raw")
    if st.button("Run EOD Update", use_container_width=True, key="run_eod"):
        if not raw_txt: st.warning("Paste text.")
        elif not os.path.exists(DATABASE_FILE): st.error("DB missing.")
        else:
            summaries=re.split(r"(Summary:\s*\w+\s*\|)", raw_txt); processed=[]
            if len(summaries)>1 and not summaries[0].strip().startswith("Summary:"):
                 if summaries[0].strip(): st.warning("Ignore text before first summary.")
                 summaries = summaries[1:]
            for i in range(0, len(summaries), 2):
                 if i + 1 < len(summaries): processed.append(summaries[i] + summaries[i+1])
            if not processed: st.warning("No summaries found (check format).")
            else:
                st.success(f"Found {len(processed)} summaries."); logs=st.expander("Logs", True); logger=AppLogger(logs); t_start=time.time()
                for i, s in enumerate(processed):
                    key=random.choice(API_KEYS) # --- USE RANDOM KEY ---
                    ticker=parse_raw_summary(s).get('ticker')
                    if not ticker: logger.log(f"SKIP EOD: No ticker {s[:100]}..."); continue
                    try: update_stock_note(ticker, s, key, logger)
                    except Exception as e: logger.log(f"!!! EOD ERR {ticker}: {e}")
                    if i<len(processed)-1: logger.log("   ...wait 1s..."); time.sleep(1)
                t_end=time.time(); logger.log("--- EOD DONE ---"); logger.log(f"Time: {t_end-t_start:.2f}s."); st.info("EOD done.")

# --- TAB 3: Pre-Flight Check (Workflow 2a) (UPDATED) ---
with tab_preflight:
    st.header("Tactical Update: Pre-Flight Check (Workflow 2a)")
    st.caption("Select tickers, add news, and generate temporary 'Pre-Market Tactical Cards' using Capital.com data.")
    
    # --- Capital.com Authentication ---
    st.subheader("Capital.com Status")
    capital_secrets = st.secrets.get("capital_com", {})
    if not all(capital_secrets.get(k) for k in ["X_CAP_API_KEY", "identifier", "password"]):
         st.error("Capital.com secrets not found in st.secrets. Add [capital_com] section.")
         st.code("""
[capital_com]
X_CAP_API_KEY = "YOUR_KEY"
identifier = "your_email@gmail.com"
password = "your_password"
         """)
         st.stop()
    
    session_data = st.session_state.capital_session
    session_time_utc_iso = session_data.get("time_utc_iso") # --- FIX: Read ISO string ---
    cst = session_data.get("cst")
    xst = session_data.get("xst")
    
    is_session_valid = False
    session_status_placeholder = st.empty()
    
    session_time_utc_dt = None
    if session_time_utc_iso and cst and xst:
        try:
            # --- FIX: Convert ISO string back to aware datetime ---
            session_time_utc_dt = datetime.fromisoformat(session_time_utc_iso)
            expiration_time_utc = session_time_utc_dt + timedelta(minutes=30)
            time_now_utc = datetime.now(timezone.utc) # Get aware current time
            
            if time_now_utc < expiration_time_utc: # Correct comparison
                 is_session_valid = True
                 # --- FIX: Use UTC for display as requested ---
                 session_status_placeholder.success(f"Capital.com session active (Expires ~ {expiration_time_utc.strftime('%H:%M:%S')} UTC)")
            else:
                 session_status_placeholder.warning(f"Capital.com session expired at {expiration_time_utc.strftime('%H:%M:%S')} UTC.")
        except Exception as e:
             session_status_placeholder.error(f"Error parsing session time: {e}")
             session_time_utc_iso = None # Force refresh
             
    if not is_session_valid:
        button_text = "Refresh Session" if session_time_utc_iso else "Create Capital.com Session"
        if st.button(button_text, use_container_width=True, key="create_refresh_session"):
             log_container_session = st.expander("Session Log", True)
             logger_session = AppLogger(log_container_session)
             with st.spinner("Creating session..."):
                 cst_new, xst_new, balance = create_capital_session(logger_session) # Call with _logger
                 if cst_new and xst_new:
                     # --- FIX: Store time as UTC ISO string ---
                     st.session_state.capital_session = {"cst": cst_new, "xst": xst_new, "time_utc_iso": datetime.now(timezone.utc).isoformat()}
                     st.rerun()
                 else:
                     st.error("Session creation failed. Check secrets/credentials.")
                     st.session_state.capital_session = {"cst":None, "xst":None, "time_utc_iso":None}
        st.stop()


    # --- Pre-Flight Inputs (Only show if session is valid) ---
    st.markdown("---")
    st.subheader("Generate Tactical Cards")
    if not os.path.exists(DATABASE_FILE): st.error("DB missing.")
    else:
        all_tickers_pf = get_all_tickers_from_db()
        if not all_tickers_pf: st.warning("No tickers in DB.")
        else:
            selected_tickers_pf = st.multiselect("1. Select Tickers (EPICs):", options=all_tickers_pf, default=st.session_state.get('last_selected_tickers',[]), key="pf_tickers",
                                               help="Ensure these are the exact Capital.com EPICS (e.g., 'AMD', 'AAPL').")
            news_pf = st.text_area("2. Overnight News:", placeholder="e.g., SNOW beat...", height=150, key="pf_news")
            if st.button("Generate Pre-Market Cards", use_container_width=True, key="gen_pm_cards"):
                if not selected_tickers_pf: st.warning("Select tickers.")
                else:
                    st.session_state['last_selected_tickers'] = selected_tickers_pf
                    logs_pf = st.expander("Logs", True); logger_pf = AppLogger(logs_pf)
                    with st.spinner("Fetching Capital.com data & synthesizing..."):
                        success = generate_premarket_tactical_cards(
                            selected_tickers_pf, news_pf, logger_pf,
                            cst=st.session_state.capital_session["cst"],
                            xst=st.session_state.capital_session["xst"]
                        )
                        if success: st.success("Pre-market gen complete."); st.info(f"Generated for {len(st.session_state.get('premarket_cards',{}))} tickers."); st.write("Tickers:", ", ".join(st.session_state.get('premarket_cards',{}).keys()))
                        else: st.error("Pre-market gen failed."); st.session_state['premarket_cards'] = {}


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


# --- TAB 5: Trade Screener (Workflow 2b) (Unchanged) ---
with tab_screener:
    st.header("Action: Trade Screener (Workflow 2b)")
    st.caption("Ranks tactical setups from Pre-Flight Check.")
    pm_cards_avail = st.session_state.get('premarket_cards',{})
    if not pm_cards_avail: st.error("Generate Pre-Market Cards first."); st.stop()
    st.info(f"**{len(pm_cards_avail)} Pre-Market Cards ready.**")
    col1_s, col2_s = st.columns([3,1])
    with col1_s: market_cond_s = st.text_area("Market Condition:", height=100, key="scr_market")
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
                key_scr = random.choice(API_KEYS) # --- USE RANDOM KEY ---
                with st.spinner(f"AI ranking {len(cards_scr)} cards..."):
                    result_scr = run_tactical_screener(market_cond_s, cards_scr, key_scr, logger_scr)
                st.markdown("---"); st.subheader(f"Ranked Briefings (Filter: {conf_filter_s})")
                if result_scr: st.markdown(result_scr, unsafe_allow_html=True)
                else: st.error("Screener failed.")


# --- Command Line Test Example (Unchanged) ---
if __name__ == "__main__":
    print("Run with: streamlit run pipeline_engine.py")

