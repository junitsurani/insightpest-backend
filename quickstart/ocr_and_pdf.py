from flask import Blueprint, request, jsonify
from app import db
from app.models.user import BankStatement, ProcessingStatus, Transaction, TransactionStatus
import fitz  # PyMuPDF
from PIL import Image
import pytesseract

# Set the tesseract_cmd to the Tesseract executable path
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def extract_text_from_image(pdf_document):
    all_text = ""
    for page_number in range(len(pdf_document)):
        page = pdf_document.load_page(page_number)
        pix = page.get_pixmap()
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        text = pytesseract.image_to_string(img)
        all_text += text + "\n"
    return all_text

def extract_text_from_pdf(pdf_document):
    all_text = ""
    for page_number in range(len(pdf_document)):
        page = pdf_document.load_page(page_number)
        text = page.get_text("text")
        if not text.strip():
            return None
        all_text += text + "\n"
    return all_text

def upload_pdf():
    if 'pdf_file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['pdf_file']
    
    if file.filename == '' or not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Invalid file or not a PDF'}), 400
    
    try:
        # Save file content to memory
        file_content = file.read()
        
        # Debug print
        print("File size:", len(file_content), "bytes")
        
        # Create PDF document from memory buffer
        pdf_document = fitz.open(stream=file_content, filetype="pdf")
        
        # Debug print
        print("Number of pages:", len(pdf_document))
        
        # Extract text from PDF
        full_text = extract_text_from_pdf(pdf_document) or extract_text_from_image(pdf_document)
        
        if not full_text.strip():
            return jsonify({'error': 'No text could be extracted from the PDF'}), 400
            
        return jsonify({'text': full_text}), 200
        
    except Exception as e:
        print(f"Error processing PDF: {str(e)}")
        return jsonify({'error': 'Error processing PDF file'}), 500
    finally:
        if 'pdf_document' in locals():
            pdf_document.close()

# Add main execution block
if __name__ == "__main__":
    # Initialize Flask Blueprint
    ocr_pdf_bp = Blueprint('ocr_pdf', __name__)
    ocr_pdf_bp.route('/upload-pdf', methods=['POST'])(upload_pdf)
