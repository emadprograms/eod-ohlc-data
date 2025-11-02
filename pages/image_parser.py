import streamlit as st
from PIL import Image
import google.generativeai as genai
import random
from google.api_core import exceptions
import logging
from datetime import datetime
import pytesseract
import os
import re
import sqlite3

# --- Session State Initialization ---
if 'logs' not in st.session_state:
    st.session_state.logs = []
if 'reset_counter' not in st.session_state:
    st.session_state.reset_counter = 0
if 'extraction_finished' not in st.session_state:
    st.session_state.extraction_finished = False
if 'final_text' not in st.session_state:
    st.session_state.final_text = ""

# --- Logger Setup ---
# We will store logs in the session state to persist them across reruns.
def log_message(message, level='INFO'):
    """Appends a formatted log message to the session state list."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    st.session_state.logs.append(f"{timestamp} - {level} - {message}")

def configure_api():
    """
    Checks for and loads the list of Gemini API keys from Streamlit secrets.
    """
    try:
        log_message("Attempting to configure API keys from secrets.")
        if "gemini" in st.secrets and "api_keys" in st.secrets["gemini"] and st.secrets["gemini"]["api_keys"]:
            st.session_state.api_keys = st.secrets["gemini"]["api_keys"]
            log_message(f"Successfully loaded {len(st.session_state.api_keys)} API keys.")
            return True
        else:
            raise KeyError("API keys list is missing or empty.")
    except (KeyError, AttributeError) as e:
        log_message(f"API key configuration failed: {e}", level='ERROR')
        st.error("Google API Keys not found or incorrectly formatted in secrets.")
        st.code(
            "Ensure your .streamlit/secrets.toml file has:\n\n"
            "[gemini]\n"
            "api_keys = [\n"
            '    "YOUR_API_KEY_1",\n'
            '    "YOUR_API_KEY_2",\n'
            "]"
        )
        return False

def make_gemini_call(prompt, image_parts=None):
    """
    Makes a single call to the Gemini API using a random key.

    Args:
        prompt (str): The text prompt.
        image_parts (list, optional): A list containing image data. Defaults to None.

    Returns:
        str: The text response from the model or an error message.
    """
    try:
        if not st.session_state.api_keys:
            log_message("No API keys available to make a request.", level='ERROR')
            return "Error: No API keys configured."

        api_key = random.choice(st.session_state.api_keys)
        key_identifier = f"{api_key[:4]}...{api_key[-4:]}"
        log_message(f"Using a randomly selected API key: {key_identifier}")

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')

        content = [prompt]
        if image_parts:
            content.extend(image_parts)

        log_message(f"Generating content with model 'gemini-2.5-flash'.")
        response = model.generate_content(content)
        log_message("Successfully received response from API.")
        return response.text

    except exceptions.ResourceExhausted as e:
        log_message(f"API key {key_identifier} is rate-limited. {e}", level='WARNING')
        return f"ERROR: API_RATE_LIMITED - {e}"
    except Exception as e:
        log_message(f"An unexpected error occurred with key {key_identifier}: {e}", level='ERROR')
        return f"ERROR: UNEXPECTED - {e}"

# --- Streamlit App ---

st.set_page_config(page_title="AI Image Parser", layout="centered")

st.title("🖼️ AI Image to Text Converter")

st.write(
    "Upload multiple scrolling screenshots (PNG, JPG, etc.). The AI will "
    "extract and combine the text into a single block."
)

if not configure_api():
    st.stop()

def reset_app():
    """
    Increments a counter to reset the file_uploader and clears other state.
    """
    st.session_state.reset_counter += 1
    st.session_state.logs = []
    st.session_state.extraction_finished = False
    st.session_state.final_text = ""
    log_message("Application reset by user.")
    # The script will rerun automatically after the on_click callback.

uploaded_files = st.file_uploader(
    "Choose one or more images...",
    type=["png", "jpg", "jpeg", "bmp", "tiff"],
    accept_multiple_files=True,
    # The key is now dynamic, changing it resets the widget
    key=f"image_uploader_{st.session_state.reset_counter}"
)

if uploaded_files:
    st.subheader("Uploaded Images")
    for uploaded_file in uploaded_files:
        st.image(uploaded_file, caption=uploaded_file.name, use_container_width=True)

    tab_ai, tab_tesseract = st.tabs(["Parse using AI", "Parse using Pillow & Tesseract"])

    with tab_ai:
        st.header("AI-Powered Extraction")
        st.write("This method uses a multimodal AI model to 'see' the image and extract text. It can be more accurate for complex layouts but is slower and more expensive.")
        if st.button("Extract and Combine Text with AI"):
            log_message("'Extract and Combine Text (AI)' button clicked.")
            individual_texts = []
            has_error = False

            # 1. Make one API call per image to extract text
            with st.spinner("Step 1/2: Extracting text from each image using AI..."):
                for i, uploaded_file in enumerate(uploaded_files):
                    log_message(f"Processing image {i+1}/{len(uploaded_files)}: {uploaded_file.name}")
                    st.info(f"Processing image {i+1}/{len(uploaded_files)}: {uploaded_file.name}")

                    image_part = {
                        "mime_type": uploaded_file.type,
                        "data": uploaded_file.getvalue()
                    }
                    extract_prompt = "Extract all text from this image. Do not add any commentary or introductory text, just return the raw text."
                    
                    extracted_text = make_gemini_call(extract_prompt, [image_part])

                    if extracted_text.startswith("ERROR:"):
                        st.error(f"Failed to process image {uploaded_file.name}. Reason: {extracted_text}")
                        log_message(f"Error processing {uploaded_file.name}: {extracted_text}", level='ERROR')
                        has_error = True
                        break
                    
                    individual_texts.append(extracted_text)
                    log_message(f"Successfully extracted text from image {i+1}.")

            # 2. If all extractions were successful, make a final call to combine them
            if not has_error and individual_texts:
                with st.spinner("Step 2/2: Combining all extracted text using AI..."):
                    log_message("Starting final AI call to combine texts.")
                    
                    # Prepare the text snippets for the final prompt
                    text_to_combine = ""
                    for i, text in enumerate(individual_texts):
                        text_to_combine += f"--- START OF TEXT FROM IMAGE {i+1} ---\n"
                        text_to_combine += text
                        text_to_combine += f"\n--- END OF TEXT FROM IMAGE {i+1} ---\n\n"

                    combine_prompt = (
                        "You are an expert text editor. The user has provided several blocks of text extracted from sequential images. "
                        "Your task is to merge these text blocks into a single, coherent, and continuous document. "
                        "Remove the '--- START/END OF TEXT ---' markers and seamlessly join the content. "
                        "Preserve the original formatting and paragraphs as much as possible. "
                        "Do not add any commentary, just return the final combined text.\n\n"
                        f"{text_to_combine}"
                    )

                    final_text = make_gemini_call(combine_prompt)

                    if final_text.startswith("ERROR:"):
                        st.error(f"Failed to combine the texts. Reason: {final_text}")
                        log_message(f"Error in final combination call: {final_text}", level='ERROR')
                    else:
                        st.subheader("📄 Combined Extracted Text (AI)")
                        st.code(final_text, language=None)
                        st.session_state.final_text = final_text # Save for download
                        log_message("Successfully combined all texts.")
                    # Mark the process as finished to show the reset button
                    st.session_state.extraction_finished = True
            elif not individual_texts and not has_error:
                st.warning("No text could be extracted from the uploaded images.")
                log_message("No text was extracted from any image.", level='WARNING')
                # Mark the process as finished to show the reset button
                st.session_state.extraction_finished = True

    with tab_tesseract:
        st.header("High-Speed Extraction with Tesseract")
        st.write("This method uses local OCR (Tesseract) to quickly extract text, then uses AI to intelligently combine the results. It's much faster but may struggle with unusual fonts or layouts.")
        if st.button("Extract and Combine with Tesseract + AI"):
            log_message("'Extract and Combine Text (Pillow/Tesseract)' button clicked.")
            individual_texts = []
            has_error = False

            # 1. Use Tesseract to extract text from each image
            with st.spinner("Step 1/2: Extracting text from each image using Tesseract..."):
                for i, uploaded_file in enumerate(uploaded_files):
                    try:
                        log_message(f"Processing image {i+1}/{len(uploaded_files)} with Tesseract: {uploaded_file.name}")
                        st.info(f"Processing image {i+1}/{len(uploaded_files)}: {uploaded_file.name}")
                        
                        image = Image.open(uploaded_file)
                        extracted_text = pytesseract.image_to_string(image, lang='eng')
                        
                        if not extracted_text.strip():
                            log_message(f"Tesseract found no text in image {i+1}.", level='WARNING')
                            st.warning(f"Tesseract found no text in {uploaded_file.name}.")
                        
                        individual_texts.append(extracted_text)
                        log_message(f"Successfully extracted text from image {i+1} using Tesseract.")
                    except Exception as e:
                        st.error(f"Failed to process image {uploaded_file.name} with Tesseract. Reason: {e}")
                        log_message(f"Error processing {uploaded_file.name} with Tesseract: {e}", level='ERROR')
                        has_error = True
                        break
            
            # 2. If all extractions were successful, make a final call to combine them
            if not has_error and any(text.strip() for text in individual_texts):
                with st.spinner("Step 2/2: Combining all extracted text using AI..."):
                    log_message("Starting final AI call to combine Tesseract texts.")
                    
                    text_to_combine = ""
                    for i, text in enumerate(individual_texts):
                        text_to_combine += f"--- START OF TEXT FROM IMAGE {i+1} ---\n"
                        text_to_combine += text
                        text_to_combine += f"\n--- END OF TEXT FROM IMAGE {i+1} ---\n\n"

                    combine_prompt = (
                        "You are an expert text editor. The user has provided several blocks of text extracted from sequential images using an OCR tool. "
                        "Your task is to merge these text blocks into a single, coherent, and continuous document. "
                        "The OCR may have made some errors or included artifacts. Clean these up where obvious. "
                        "Remove the '--- START/END OF TEXT ---' markers and seamlessly join the content. "
                        "Preserve the original formatting and paragraphs as much as possible. "
                        "Do not add any commentary, just return the final combined text.\n\n"
                        f"{text_to_combine}"
                    )

                    final_text = make_gemini_call(combine_prompt)

                    if final_text.startswith("ERROR:"):
                        st.error(f"Failed to combine the texts. Reason: {final_text}")
                        log_message(f"Error in final Tesseract combination call: {final_text}", level='ERROR')
                    else:
                        st.subheader("📄 Combined Extracted Text (Tesseract + AI)")
                        st.code(final_text, language=None)
                        st.session_state.final_text = final_text # Save for download
                        log_message("Successfully combined all Tesseract texts.")
                    # Mark the process as finished to show the reset button
                    st.session_state.extraction_finished = True
            elif not any(text.strip() for text in individual_texts) and not has_error:
                st.warning("No text could be extracted from the uploaded images using Tesseract.")
                log_message("No text was extracted from any image using Tesseract.", level='WARNING')
                # Mark the process as finished to show the reset button
                st.session_state.extraction_finished = True

    # --- Save and Reset Section ---
    if st.session_state.final_text:
        # Use columns for a more compact layout
        col1, col2 = st.columns(2)
        with col1:
            save_date = st.date_input("Select Date", value=datetime.now())
        with col2:
            category_options = ["Market Open Briefing", "Market Close Summary", "Other..."]
            category = st.selectbox("Select Category", options=category_options)

        custom_category = ""
        if category == "Other...":
            custom_category = st.text_input("Enter Custom Category Name", help="Provide a name for your custom category.")

        # The button is now below the inputs and uses the default style
        if st.button("💾 Save Text", use_container_width=True):
            # Determine the final category name, ensuring it's not "Other..."
            final_category_base = custom_category if category == "Other..." and custom_category else category
            
            if final_category_base and final_category_base != "Other...":
                
                # --- Classify and format the category for DB insertion ---
                news_categories = ["Market Open Briefing", "Market Close Summary"]
                is_news = (category in news_categories) or (category == "Other..." and custom_category)
                
                if is_news:
                    # Sanitize and prefix news items
                    clean_category = re.sub(r'[^\w\-]', '_', final_category_base.replace(' ', '-'))
                    db_category = f"news_{clean_category}"
                else:
                    # Assume it's a stock/ETF ticker, use it directly
                    db_category = final_category_base

                # --- Database Integration ---
                db_file = "analysis_database.db"
                conn = None
                try:
                    conn = sqlite3.connect(db_file)
                    c = conn.cursor()
                    
                    # Use INSERT OR REPLACE to handle unique constraints gracefully.
                    c.execute(
                        """
                        INSERT OR REPLACE INTO data_archive (date, ticker, raw_text_summary) 
                        VALUES (?, ?, ?)
                        """,
                        (save_date.strftime('%Y-%m-%d'), db_category, st.session_state.final_text)
                    )
                    conn.commit()
                    
                    st.success(f"✅ Text saved to database under category: '{final_category_base}'")
                    log_message(f"Saved text to database for date {save_date.strftime('%Y-%m-%d')} with category '{db_category}'")

                except sqlite3.Error as e:
                    st.error(f"Database error: {e}")
                    log_message(f"Failed to save to database: {e}", level='ERROR')
                finally:
                    if conn:
                        conn.close()
                # --- End Database Integration ---
            else:
                st.warning("Please select a valid category or enter a name for 'Other...'.")

    st.divider()
    # Only show the reset button after an extraction has been attempted
    if st.session_state.get('extraction_finished', False):
        st.button("Start Over with New Images", on_click=reset_app, use_container_width=True)

else:
    st.info("Please upload one or more image files to begin.")

# --- Log Display ---
with st.expander("View Logs", expanded=True):
    st.code("\n".join(st.session_state.logs[::-1]), language='log')
    if st.button("Clear Logs"):
        st.session_state.logs = []
        st.rerun()