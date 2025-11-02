"""
This module provides functions to display market note data in a Streamlit application.
It offers two main display modes: a read-only view and an editable view.

- `display_view_market_note_card`: Renders market data in a static, formatted card
  for viewing purposes. It includes sections for fundamental context, behavioral sentiment,
  technical structure, and trade plans.

- `display_editable_market_note_card`: Renders the market data in an interactive form
  with input widgets, allowing users to edit the information. The edited data
  is returned by the function.

A helper function `escape_markdown` is also included to safely render text within
Markdown components by escaping special characters.
"""

import streamlit as st
import textwrap

# --- Helper Function ---
def escape_markdown(text):
    """Escapes special Markdown characters in a string for safe rendering."""
    if not isinstance(text, str):
        return text
    # Escape $ and ~
    return text.replace('$', '\\$').replace('~', '\\~')

# --- VIEW MODE ---
def display_view_market_note_card(card_data):
    """Displays the data in a read-only, formatted Markdown view."""
    data = card_data
    with st.container(border=True):
        # Header with Edit button on the right
        title_col, button_col = st.columns([0.95, 0.05])
        with title_col:
            st.header(escape_markdown(data.get('marketNote', '')))
        with button_col:
            st.write("") # Add vertical space to align button
            if st.button("✏️", help="Edit card"):
                st.session_state.edit_mode = True
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
def display_editable_market_note_card(card_data):
    """Displays the data in an editable layout with input widgets."""
    data = card_data
    with st.container(border=True):
        # Header with Save button on the right
        title_col, button_col = st.columns([0.95, 0.05])
        with title_col:
             data['marketNote'] = st.text_input("Market Note Title", data.get('marketNote', ''), label_visibility="collapsed")
        with button_col:
            st.write("") # Add vertical space to align button
            if st.button("💾", help="Save and switch to view mode"):
                st.session_state.edit_mode = False
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
            if 'scenario' in plan_data or plan_key == 'alternative':
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
    return data

# --- ECONOMY CARD ---
def display_view_economy_card(card_data, key_prefix="eco_view"):
    """Displays the Economy card data in a read-only, formatted Markdown view."""
    data = card_data
    # Wrap the entire card in an expander
    with st.expander("Global Economy Card", expanded=True):
        with st.container(border=True):
            title_col, button_col = st.columns([0.95, 0.05])
            with title_col:
                # Use markdown for a regular bold font size title
                st.markdown(f"**{escape_markdown(data.get('marketNarrative', 'Market Narrative N/A'))}**")
            with button_col:
                st.write("")
                if st.button("✏️", key=f"{key_prefix}_edit_button", help="Edit economy card"):
                    st.session_state.edit_mode_economy = True
                    st.rerun()

            st.markdown(f"**Market Bias:** {escape_markdown(data.get('marketBias', 'N/A'))}")

            st.markdown("---")
            col1, col2 = st.columns(2)

            # Column 1: Key Economic Events and Index Analysis
            with col1:
                with st.container(border=True):
                    st.markdown("##### Key Economic Events")
                    events = data.get("keyEconomicEvents", {})
                    st.markdown("**Last 24h:**")
                    st.info(escape_markdown(events.get('last_24h', 'N/A')))
                    st.markdown("**Next 24h:**")
                    st.warning(escape_markdown(events.get('next_24h', 'N/A')))

                with st.container(border=True):
                    st.markdown("##### Index Analysis")
                    indices = data.get("indexAnalysis", {})
                    for index, analysis in indices.items():
                        if analysis and analysis.strip():
                            st.markdown(f"**{index.replace('_', ' ')}**")
                            st.write(escape_markdown(analysis))

            # Column 2: Sector Rotation and Inter-Market Analysis
            with col2:
                with st.container(border=True):
                    st.markdown("##### Sector Rotation")
                    rotation = data.get("sectorRotation", {})
                    st.markdown(f"**Leading:** {escape_markdown(', '.join(rotation.get('leadingSectors', [])) or 'N/A')}")
                    st.markdown(f"**Lagging:** {escape_markdown(', '.join(rotation.get('laggingSectors', [])) or 'N/A')}")
                    st.markdown("**Analysis:**")
                    st.write(escape_markdown(rotation.get('rotationAnalysis', 'N/A')))

                with st.container(border=True):
                    st.markdown("##### Inter-Market Analysis")
                    intermarket = data.get("interMarketAnalysis", {})
                    for asset, analysis in intermarket.items():
                        if analysis and analysis.strip():
                            st.markdown(f"**{asset.replace('_', ' ')}**")
                            st.write(escape_markdown(analysis))

            st.markdown("---")
            st.markdown("##### Market Key Action")
            st.text(escape_markdown(data.get('marketKeyAction', 'N/A')))


def display_editable_economy_card(card_data, key_prefix="eco_edit"):
    """Displays the Economy card data in an editable layout."""
    data = card_data
    with st.container(border=True):
        title_col, button_col = st.columns([0.95, 0.05])
        with title_col:
            data['marketNarrative'] = st.text_area(
                "Market Narrative", data.get('marketNarrative', ''), key=f"{key_prefix}_narrative", label_visibility="collapsed"
            )
        with button_col:
            st.write("")
            if st.button("💾", key=f"{key_prefix}_save_button", help="Save and switch to view mode"):
                st.session_state.edit_mode_economy = False
                st.rerun()

        data['marketBias'] = st.text_input(
            "Market Bias",
            data.get('marketBias', 'Neutral'),
            key=f"{key_prefix}_bias"
        )

        st.markdown("---")
        col1, col2 = st.columns(2)

        with col1:
            with st.container(border=True):
                st.markdown("##### Key Economic Events")
                events = data.setdefault("keyEconomicEvents", {})
                events['last_24h'] = st.text_area("Last 24h", events.get('last_24h', ''), height=100, key=f"{key_prefix}_events_last")
                events['next_24h'] = st.text_area("Next 24h", events.get('next_24h', ''), height=100, key=f"{key_prefix}_events_next")

            with st.container(border=True):
                st.markdown("##### Sector Rotation")
                rotation = data.setdefault("sectorRotation", {})
                rotation['leadingSectors'] = st.text_input("Leading Sectors (comma-separated)", ', '.join(rotation.get('leadingSectors', [])), key=f"{key_prefix}_sector_lead").split(', ')
                rotation['laggingSectors'] = st.text_input("Lagging Sectors (comma-separated)", ', '.join(rotation.get('laggingSectors', [])), key=f"{key_prefix}_sector_lag").split(', ')
                rotation['rotationAnalysis'] = st.text_area("Rotation Analysis", rotation.get('rotationAnalysis', ''), height=150, key=f"{key_prefix}_sector_analysis")

        with col2:
            with st.container(border=True):
                st.markdown("##### Index Analysis")
                indices = data.setdefault("indexAnalysis", {})
                for index_key in list(indices.keys()):
                    if indices.get(index_key, '').strip():
                        indices[index_key] = st.text_area(f"{index_key.replace('_', ' ')} Analysis", indices.get(index_key, ''), height=100, key=f"{key_prefix}_index_{index_key}")

            with st.container(border=True):
                st.markdown("##### Inter-Market Analysis")
                intermarket = data.setdefault("interMarketAnalysis", {})
                for asset_key in list(intermarket.keys()):
                    if intermarket.get(asset_key, '').strip():
                        intermarket[asset_key] = st.text_area(f"{asset_key.replace('_', ' ')} Analysis", intermarket.get(asset_key, ''), height=100, key=f"{key_prefix}_intermarket_{asset_key}")

        st.markdown("---")
        st.markdown("##### Market Key Action")
        data['marketKeyAction'] = st.text_area("Market Key Action (Log)", data.get('marketKeyAction', ''), height=200, key=f"{key_prefix}_key_action")

    return data