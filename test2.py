import streamlit as st
import json
import textwrap

# --- Helper Function ---
def escape_markdown(text):
    """Escapes special Markdown characters in a string for safe rendering."""
    if not isinstance(text, str):
        return text
    # Escape $, (, ), and ~
    return text.replace('$', '\\$').replace('(', '\\(').replace(')', '\\)').replace('~', '\\~')

# --- VIEW MODE ---
def display_view_market_note_card():
    """Displays the data in a read-only, formatted Markdown view."""
    data = st.session_state.editable_data
    with st.container(border=True):
        # Header with Edit button on the right
        title_col, button_col = st.columns([0.91, 0.09])
        with title_col:
            st.header(escape_markdown(data.get('marketNote', '')))
        with button_col:
            st.write("") # Add vertical space to align button
            if st.button("✏️ Edit"):
                st.session_state.mode = 'edit'
                st.rerun()

        if "basicContext" in data:
            st.subheader(escape_markdown(data["basicContext"].get('tickerDate', '')))
        st.markdown(f"**Confidence:** {escape_markdown(data.get('confidence', 'N/A'))}")
        with st.expander("Show Screener Briefing"):
            st.info(escape_markdown(data.get('screener_briefing', 'N/A')))
        st.divider()

        # Columns
        col1, col2 = st.columns(2)
        with col1:
            with st.container(border=True):
                st.markdown("##### Fundamental Context")
                fund = data.get("fundamentalContext", {})
                st.markdown(textwrap.dedent(f"""
                    - **Valuation:** {escape_markdown(fund.get('valuation', 'N/A'))}
                    - **Analyst Sentiment:** {escape_markdown(fund.get('analystSentiment', 'N/A'))}
                    - **Insider Activity:** {escape_markdown(fund.get('insiderActivity', 'N/A'))}
                    - **Peer Performance:** {escape_markdown(fund.get('peerPerformance', 'N/A'))}
                """))
            with st.container(border=True):
                st.markdown("##### Behavioral & Sentiment")
                sent = data.get("behavioralSentiment", {})
                st.markdown(textwrap.dedent(f"""
                    - **Buyer vs. Seller:** {escape_markdown(sent.get('buyerVsSeller', 'N/A'))}
                    - **Emotional Tone:** {escape_markdown(sent.get('emotionalTone', 'N/A'))}
                    - **News Reaction:** {escape_markdown(sent.get('newsReaction', 'N/A'))}
                """))
        with col2:
            with st.container(border=True):
                st.markdown("##### Basic Context")
                ctx = data.get("basicContext", {})
                st.markdown(textwrap.dedent(f"""
                    - **Company:** {escape_markdown(ctx.get('companyDescription', 'N/A'))}
                    - **Sector:** {escape_markdown(ctx.get('sector', 'N/A'))}
                    - **Recent Catalyst:** {escape_markdown(ctx.get('recentCatalyst', 'N/A'))}
                """))
            with st.container(border=True):
                st.markdown("##### Technical Structure")
                tech = data.get("technicalStructure", {})
                st.markdown(textwrap.dedent(f"""
                    - **Major Support:** {escape_markdown(tech.get('majorSupport', 'N/A'))}
                    - **Major Resistance:** {escape_markdown(tech.get('majorResistance', 'N/A'))}
                    - **Key Action:** {escape_markdown(tech.get('keyAction', 'N/A'))}
                """))
        st.divider()

        # Trade Plans
        st.subheader("Trade Plans")
        def render_plan(plan_data):
            st.markdown(f"#### {escape_markdown(plan_data.get('planName', 'N/A'))}")
            if "scenario" in plan_data and plan_data['scenario']:
                st.info(f"**Scenario:** {escape_markdown(plan_data['scenario'])}")
            st.markdown(textwrap.dedent(f"""
                - **Known Participants:** {escape_markdown(plan_data.get('knownParticipant', 'N/A'))}
                - **Expected Participants:** {escape_markdown(plan_data.get('expectedParticipant', 'N/A'))}
            """))
            st.success(f"**Trigger:** {escape_markdown(plan_data.get('trigger', 'N/A'))}")
            st.error(f"**Invalidation:** {escape_markdown(plan_data.get('invalidation', 'N/A'))}")

        primary_plan_tab, alternative_plan_tab = st.tabs(["Primary Plan", "Alternative Plan"])
        with primary_plan_tab:
            if "openingTradePlan" in data:
                render_plan(data["openingTradePlan"])
        with alternative_plan_tab:
            if "alternativePlan" in data:
                render_plan(data["alternativePlan"])

# --- EDIT MODE ---
def display_editable_market_note_card():
    """Displays the data in an editable layout with input widgets."""
    data = st.session_state.editable_data
    with st.container(border=True):
        # Header with Save button on the right
        title_col, button_col = st.columns([0.91, 0.09])
        with title_col:
             data['marketNote'] = st.text_input("Market Note Title", data.get('marketNote', ''), label_visibility="collapsed")
        with button_col:
            st.write("") # Add vertical space to align button
            if st.button("💾 Save"):
                st.session_state.mode = 'view'
                st.rerun()
        
        if "basicContext" in data:
            data["basicContext"]['tickerDate'] = st.text_input("Ticker | Date", data["basicContext"].get('tickerDate', ''))
        data['confidence'] = st.text_area("Confidence", data.get('confidence', ''))
        with st.expander("Edit Screener Briefing", expanded=True):
            data['screener_briefing'] = st.text_area("Screener Briefing", data.get('screener_briefing', ''), height=150, label_visibility="collapsed")
        st.divider()

        # Columns
        col1, col2 = st.columns(2)
        with col1:
            with st.container(border=True):
                st.markdown("##### Fundamental Context")
                fund = data.setdefault("fundamentalContext", {})
                fund['valuation'] = st.text_input("Valuation", fund.get('valuation', ''))
                fund['analystSentiment'] = st.text_area("Analyst Sentiment", fund.get('analystSentiment', ''), height=100)
                fund['insiderActivity'] = st.text_area("Insider Activity", fund.get('insiderActivity', ''), height=100)
                fund['peerPerformance'] = st.text_area("Peer Performance", fund.get('peerPerformance', ''), height=100)
            with st.container(border=True):
                st.markdown("##### Behavioral & Sentiment")
                sent = data.setdefault("behavioralSentiment", {})
                sent['buyerVsSeller'] = st.text_area("Buyer vs. Seller", sent.get('buyerVsSeller', ''), height=100)
                sent['emotionalTone'] = st.text_input("Emotional Tone", sent.get('emotionalTone', ''))
                sent['newsReaction'] = st.text_area("News Reaction", sent.get('newsReaction', ''), height=100)
        with col2:
            with st.container(border=True):
                st.markdown("##### Basic Context")
                ctx = data.setdefault("basicContext", {})
                ctx['companyDescription'] = st.text_area("Company Description", ctx.get('companyDescription', ''), height=100)
                ctx['sector'] = st.text_input("Sector", ctx.get('sector', ''))
                ctx['recentCatalyst'] = st.text_area("Recent Catalyst", ctx.get('recentCatalyst', ''))
            with st.container(border=True):
                st.markdown("##### Technical Structure")
                tech = data.setdefault("technicalStructure", {})
                tech['majorSupport'] = st.text_input("Major Support", tech.get('majorSupport', ''))
                tech['majorResistance'] = st.text_input("Major Resistance", tech.get('majorResistance', ''))
                tech['keyAction'] = st.text_area("Key Action", tech.get('keyAction', ''), height=200)
        st.divider()

        # Trade Plans
        st.subheader("Trade Plans")
        def render_editable_plan(plan_data, plan_key):
            plan_data['planName'] = st.text_input("Plan Name", plan_data.get('planName', ''), key=f"{plan_key}_name")
            plan_data['scenario'] = st.text_area("Scenario", plan_data.get('scenario', ''), key=f"{plan_key}_scenario", help="Optional scenario description.")
            plan_data['knownParticipant'] = st.text_area("Known Participants", plan_data.get('knownParticipant', ''), key=f"{plan_key}_known")
            plan_data['expectedParticipant'] = st.text_area("Expected Participants", plan_data.get('expectedParticipant', ''), key=f"{plan_key}_expected")
            plan_data['trigger'] = st.text_area("Trigger", plan_data.get('trigger', ''), key=f"{plan_key}_trigger")
            plan_data['invalidation'] = st.text_area("Invalidation", plan_data.get('invalidation', ''), key=f"{plan_key}_invalidation")

        primary_plan_tab, alternative_plan_tab = st.tabs(["Primary Plan", "Alternative Plan"])
        with primary_plan_tab:
            render_editable_plan(data.setdefault("openingTradePlan", {}), "primary")
        with alternative_plan_tab:
            render_editable_plan(data.setdefault("alternativePlan", {}), "alternative")

# --- Streamlit App ---
st.set_page_config(layout="wide")
st.title("Market Note Analysis")

json_input = st.text_area("JSON Data Input", value="""
{
  "marketNote": "Executor's Battle Card: Apple Inc. (AAPL)",
  "confidence": "High - The bullish structure remains intact. Price continues to consolidate in a tight range well above the major breakout level ($264-$265), confirming buyer control and acceptance of higher prices.",
  "screener_briefing": "Bias: Strongly Bullish. Following a major breakout, price is coiling in a multi-day consolidation at the highs. This absorption of supply above key support demonstrates buyer commitment ahead of the earnings catalyst.",
  "basicContext": { "tickerDate": "AAPL | 2025-10-29", "sector": "Information Technology", "companyDescription": "Designs, manufactures, and sells smartphones (iPhone), personal computers (Mac), tablets (iPad), wearables (Apple Watch), and accessories.", "recentCatalyst": "Major Catalyst Event: Earnings report scheduled for October 30, 2025. This is the primary driver." },
  "technicalStructure": { "majorSupport": "$264-$265 (Old Resistance / New Support), $255 (Key POC / retest level), $244-$245 (bounce zone).", "majorResistance": "None Defined / Price Discovery.", "keyAction": "Cumulative 5-day story: After failing at $264, price washed to $255 support where buyers absorbed selling. Buyers then drove price back to and through the $264-$265 major resistance zone on Oct 27. On Oct 28, the market paused in a narrow inside day, confirming acceptance above the breakout level. On Oct 29, buyers initially pushed to a new high of $271.41 but were met by sellers. The subsequent pullback was shallow, finding firm support at $267.11, well above the critical $264-$265 support. The session closed within the consolidation range, representing a second day of tight balance. This coiling action above major support demonstrates buyers are absorbing profit-taking ahead of earnings, maintaining structural control." },
  "fundamentalContext": { "valuation": "Premium / Overvalued. Morningstar's Fair Value Estimate is $210 (as of Oct 21). The stock is trading at a premium P/E multiple (~36x) vs. its history and peers.", "analystSentiment": "Bullish. You noted the $255 analyst price was hit. Recent upgrades (pre-Oct 24) include Evercore with a $290 target and Loop Capital with a $315 target, citing strong iPhone 17 demand.", "insiderActivity": "Consistent net selling. In the last 3 months (as of Oct 23), there have been 0 open market buys vs. 13 sells by officers, totaling over 650,000 shares sold.", "peerPerformance": "Strong Outperformer. As of mid-October, the stock had gained ~19% in the prior three months, significantly outpacing the broader technology sector." },
  "behavioralSentiment": { "buyerVsSeller": "Buyers remain in control. While sellers defended the $271 level intraday, their inability to push price anywhere near the key $264-$265 breakout level confirms buyers are absorbing all available supply.", "emotionalTone": "Anticipation / Coiling. The market has moved from confident absorption to a tight balance, indicating participants are now poised and waiting for the earnings catalyst to resolve the consolidation.", "newsReaction": "Resilient. A breakdown on 'bad tariff news' to $244 was quickly absorbed, leading to a 4-day rally and the eventual breakout, showing strong underlying demand." },
  "openingTradePlan": { "planName": "Long Continuation / Consolidation Break (Primary)", "knownParticipant": "Committed Breakout Buyers (above $264) and short-term buyers defending the consolidation low (~$267).", "expectedParticipant": "Momentum Traders and event-driven buyers looking for a positive earnings reaction to break the consolidation highs.", "trigger": "A sustained break above the consolidation high (~$271.41) signals continuation. A dip towards the consolidation low (~$267.11) that is met with strong buying offers a tactical entry, with the primary line of defense being the major support at $264-$265.", "invalidation": "Plan fails if price breaks down *below* $264 and is accepted back into the prior range, signaling a failed breakout." },
  "alternativePlan": { "planName": "Short Failed Breakout (Secondary / Contrarian)", "scenario": "This plan remains secondary and activates only on a negative catalyst (e.g., poor earnings) that causes the bullish consolidation structure to fail decisively.", "knownParticipant": "Trapped sellers from the $264 level; profit-takers who become sellers if support breaks.", "expectedParticipant": "Aggressive Responsive Sellers reacting to a negative catalyst; longs liquidating on a failed breakout.", "trigger": "Price fails to hold above $265 and breaks back below $264 on high selling volume. This would confirm a 'look above and fail' pattern and invalidate the entire breakout structure.", "invalidation": "Plan is invalid as long as price is accepted and holds above the $264-$265 major support zone." }
}
""", height=250)

if st.button("Generate Report Card"):
    try:
        st.session_state.editable_data = json.loads(json_input)
        st.session_state.card_visible = True
        st.session_state.mode = 'view'  # Default to view mode
    except json.JSONDecodeError:
        st.error("Invalid JSON format. Please check the input data.")
        st.session_state.card_visible = False

# Main display logic
if st.session_state.get("card_visible", False):
    # The button logic is now inside the display functions
    if st.session_state.get('mode', 'view') == 'view':
        display_view_market_note_card()
    else: # mode == 'edit'
        display_editable_market_note_card()

    # Expander to show the live JSON data
    with st.expander("Show Updated JSON Data"):
        st.json(st.session_state.editable_data)