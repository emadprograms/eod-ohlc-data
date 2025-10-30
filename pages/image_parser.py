import streamlit as st
from PIL import Image
import google.generativeai as genai
import random
from google.api_core import exceptions
import logging
from datetime import datetime

# --- Logger Setup ---
# We will store logs in the session state to persist them across reruns.
if 'logs' not in st.session_state:
    st.session_state.logs = []

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
        model = genai.GenerativeModel('gemini-1.5-flash-latest')

        content = [prompt]
        if image_parts:
            content.extend(image_parts)

        log_message(f"Generating content with model 'gemini-1.5-flash-latest'.")
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

uploaded_files = st.file_uploader(
    "Choose one or more images...",
    type=["png", "jpg", "jpeg", "bmp", "tiff"],
    accept_multiple_files=True
)

if uploaded_files:
    st.subheader("Uploaded Images")
    for uploaded_file in uploaded_files:
        st.image(uploaded_file, caption=uploaded_file.name, use_container_width=True)

    if st.button("Extract and Combine Text"):
        log_message("'Extract and Combine Text' button clicked.")
        individual_texts = []
        has_error = False

        # 1. Make one API call per image to extract text
        with st.spinner("Step 1/2: Extracting text from each image..."):
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
            with st.spinner("Step 2/2: Combining all extracted text..."):
                log_message("Starting final API call to combine texts.")
                
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
                    st.subheader("📄 Combined Extracted Text")
                    st.code(final_text, language=None)
                    log_message("Successfully combined all texts.")
        elif not individual_texts and not has_error:
            st.warning("No text could be extracted from the uploaded images.")
            log_message("No text was extracted from any image.", level='WARNING')

else:
    st.info("Please upload one or more image files to begin.")

# --- Log Display ---
with st.expander("View Logs"):
    st.code("\n".join(st.session_state.logs[::-1]), language='log')
    if st.button("Clear Logs"):
        st.session_state.logs = []
        st.rerun()