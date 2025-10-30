import streamlit as st
from PIL import Image
import google.generativeai as genai
import random
from google.api_core import exceptions

def configure_api():
    """
    Checks for and loads the list of Gemini API keys from Streamlit secrets.
    """
    try:
        # Check if the list of keys exists and is not empty
        if "gemini" in st.secrets and "api_keys" in st.secrets["gemini"] and st.secrets["gemini"]["api_keys"]:
            st.session_state.api_keys = st.secrets["gemini"]["api_keys"]
            return True
        else:
            raise KeyError("API keys list is missing or empty.")
    except (KeyError, AttributeError):
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

def get_gemini_response(input_prompt, image_parts):
    """
    Gets the response from the Gemini model using a single randomly selected API key.

    Args:
        input_prompt (str): The text prompt to send to the model.
        image_parts (list): A list of image data parts for the model.

    Returns:
        str: The text response from the model or an error message.
    """
    try:
        # Pick one API key at random from the list in session state
        api_key = random.choice(st.session_state.api_keys)
        st.info("Using a randomly selected API key for this attempt...")

        # Configure the genai library with the chosen key
        genai.configure(api_key=api_key)

        # Select the model and generate content
        model = genai.GenerativeModel('gemini-2.5-pro')
        response = model.generate_content([input_prompt, *image_parts])
        return response.text

    except exceptions.ResourceExhausted as e:
        st.error("The randomly selected API key is rate-limited. Please wait a moment and try again.")
        return "API call failed due to rate limiting. Clicking the button again will select another random key."

    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")
        return "Failed to get a response from the API. Please check your keys, API quota, and try again."

# --- Streamlit App ---

st.set_page_config(page_title="AI Image Parser", layout="centered")

st.title("🖼️ AI Image to Text Converter")

st.write(
    "Upload multiple scrolling screenshots (PNG, JPG, etc.). The AI will "
    "extract and combine the text into a single block."
)

# Configure the API at the start
if not configure_api():
    st.stop()

uploaded_files = st.file_uploader(
    "Choose one or more images...",
    type=["png", "jpg", "jpeg", "bmp", "tiff"],
    accept_multiple_files=True
)

if uploaded_files:
    st.subheader("Uploaded Images")
    image_parts = []
    for uploaded_file in uploaded_files:
        # To get the bytes data
        bytes_data = uploaded_file.getvalue()
        st.image(bytes_data, caption=f"Processing: {uploaded_file.name}", use_container_width=True)
        image_parts.append({
            "mime_type": uploaded_file.type,
            "data": bytes_data  
        })

    if st.button("Extract and Combine Text"):
        with st.spinner("AI is reading the images..."):
            input_prompt = """
            You are an expert in optical character recognition.
            The user has provided one or more images that are sequential parts of a single, long document.
            Your task is to extract all the text from these images and combine it into one continuous block of text.
            Maintain the original order and formatting as much as possible.
            """

            # Ensure we have image parts before calling the API
            if image_parts:
                combined_text = get_gemini_response(input_prompt, image_parts)
                st.subheader("📄 Combined Extracted Text")
                st.code(combined_text, language=None)
            else:
                st.warning("Something went wrong with processing the images.")

else:
    st.info("Please upload one or more image files to begin.")