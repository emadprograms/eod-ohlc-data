import streamlit as st
from PIL import Image
import pytesseract

def parse_image_to_text(image_source):
    """
    Parses text from an image source (like an uploaded file) using Tesseract OCR.

    Args:
        image_source: A file-like object or path to an image.

    Returns:
        str: The extracted text from the image.
             Returns an error message on failure.
    """
    try:
        # The Image.open function can handle the uploaded file object directly.
        text = pytesseract.image_to_string(Image.open(image_source))
        return text
    except Exception as e:
        return f"An error occurred while parsing the image: {e}"

# --- Streamlit App ---

st.set_page_config(page_title="Image to Text", layout="centered")

st.title("🖼️ Image to Text Converter")

st.write(
    "Upload an image file (PNG, JPG, BMP, etc.) and the application will "
    "extract the text from it using Optical Character Recognition (OCR)."
)

uploaded_file = st.file_uploader("Choose an image...", type=["png", "jpg", "jpeg", "bmp", "tiff"])

if uploaded_file is not None:
    # Display the uploaded image
    st.image(uploaded_file, caption='Uploaded Image', use_column_width=True)

    with st.spinner("Extracting text from the image..."):
        # Perform OCR
        extracted_text = parse_image_to_text(uploaded_file)

        st.subheader("📄 Extracted Text")

        if extracted_text:
            st.text_area("Result", extracted_text, height=250)
        else:
            st.warning("No text could be extracted from the image.")

else:
    st.info("Please upload an image file to begin.")