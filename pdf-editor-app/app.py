from flask import Flask, render_template, request, send_file, jsonify
from werkzeug.utils import secure_filename
import os
from PyPDF2 import PdfReader, PdfWriter, PdfMerger
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image
import io
from docx import Document
import tempfile
from datetime import datetime
import base64
import fitz  # PyMuPDF for PDF rendering

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'outputs'
app.config['TEMP_FOLDER'] = 'temp'

# Create necessary directories
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)
os.makedirs(app.config['TEMP_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'docx', 'doc', 'txt'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Route: Home page
@app.route('/')
def index():
    return render_template('index.html')

# Route: Upload and convert to PDF
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{timestamp}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)
        
        # Process based on file type
        file_ext = filename.rsplit('.', 1)[1].lower()
        
        try:
            if file_ext == 'pdf':
                # Return PDF info for editing
                pdf_reader = PdfReader(filepath)
                num_pages = len(pdf_reader.pages)
                
                # Generate actual thumbnails
                thumbnails = generate_pdf_thumbnails(filepath, num_pages)
                
                return jsonify({
                    'success': True,
                    'file_type': 'pdf',
                    'filename': unique_filename,
                    'original_name': filename,
                    'num_pages': num_pages,
                    'thumbnails': thumbnails,
                    'message': 'PDF uploaded successfully'
                })
            else:
                # Convert to PDF
                output_filename = convert_to_pdf(filepath, file_ext, filename)
                return jsonify({
                    'success': True,
                    'file_type': 'converted',
                    'output_file': output_filename,
                    'original_name': filename,
                    'message': 'File converted to PDF successfully'
                })
        except Exception as e:
            return jsonify({'error': f'Error processing file: {str(e)}'}), 500
    
    return jsonify({'error': 'Invalid file type'}), 400

def generate_pdf_thumbnails(filepath, num_pages):
    """Generate base64 thumbnails for PDF pages"""
    thumbnails = []
    try:
        doc = fitz.open(filepath)
        for page_num in range(min(num_pages, 20)):  # Limit to 20 pages
            page = doc[page_num]
            pix = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5))  # Scale down
            img_data = pix.tobytes("png")
            img_base64 = base64.b64encode(img_data).decode('utf-8')
            thumbnails.append(f"data:image/png;base64,{img_base64}")
        doc.close()
    except Exception as e:
        print(f"Error generating thumbnails: {e}")
        # Return placeholder if thumbnail generation fails
        for i in range(min(num_pages, 20)):
            thumbnails.append(None)
    return thumbnails

@app.route('/render-page/<filename>/<int:page_num>')
def render_page(filename, page_num):
    """Render a specific PDF page as image"""
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
    
    try:
        doc = fitz.open(filepath)
        if page_num >= len(doc):
            return jsonify({'error': 'Page not found'}), 404
        
        page = doc[page_num]
        
        # Render at higher resolution for editing
        zoom = 2.0  # Increase quality
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        
        img_data = pix.tobytes("png")
        img_base64 = base64.b64encode(img_data).decode('utf-8')
        
        # Get page dimensions
        rect = page.rect
        
        doc.close()
        
        return jsonify({
            'success': True,
            'image': f"data:image/png;base64,{img_base64}",
            'width': int(rect.width * zoom),
            'height': int(rect.height * zoom),
            'original_width': int(rect.width),
            'original_height': int(rect.height)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def convert_to_pdf(filepath, file_ext, original_name):
    """Convert various file types to PDF"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    base_name = original_name.rsplit('.', 1)[0]
    output_filename = f"{base_name}_converted_{timestamp}.pdf"
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
    
    if file_ext in ['png', 'jpg', 'jpeg', 'gif']:
        # Convert image to PDF
        img = Image.open(filepath)
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        img.save(output_path, 'PDF', resolution=100.0)
    
    elif file_ext == 'docx':
        # Convert DOCX to PDF (basic conversion)
        doc = Document(filepath)
        pdf = canvas.Canvas(output_path, pagesize=letter)
        width, height = letter
        y_position = height - 50
        
        for para in doc.paragraphs:
            if y_position < 50:
                pdf.showPage()
                y_position = height - 50
            text = para.text
            # Wrap text
            for i in range(0, len(text), 80):
                if y_position < 50:
                    pdf.showPage()
                    y_position = height - 50
                pdf.drawString(50, y_position, text[i:i+80])
                y_position -= 15
        
        pdf.save()
    
    elif file_ext == 'txt':
        # Convert TXT to PDF
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
        
        pdf = canvas.Canvas(output_path, pagesize=letter)
        width, height = letter
        y_position = height - 50
        
        for line in text.split('\n'):
            if y_position < 50:
                pdf.showPage()
                y_position = height - 50
            # Wrap long lines
            for i in range(0, len(line), 80):
                if y_position < 50:
                    pdf.showPage()
                    y_position = height - 50
                pdf.drawString(50, y_position, line[i:i+80])
                y_position -= 15
        
        pdf.save()
    
    return output_filename

# Route: Get PDF info and pages
@app.route('/get-pdf-info/<filename>')
def get_pdf_info(filename):
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
    
    try:
        pdf_reader = PdfReader(filepath)
        num_pages = len(pdf_reader.pages)
        
        pages_info = []
        for i in range(num_pages):
            page = pdf_reader.pages[i]
            pages_info.append({
                'page_number': i,
                'width': float(page.mediabox.width),
                'height': float(page.mediabox.height),
                'rotation': page.get('/Rotate', 0)
            })
        
        return jsonify({
            'success': True,
            'num_pages': num_pages,
            'pages': pages_info
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Route: Create PDF from text
@app.route('/create-pdf', methods=['POST'])
def create_pdf():
    data = request.json
    text_content = data.get('content', '')
    title = data.get('title', 'Document')
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_filename = f"created_{timestamp}.pdf"
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
    
    pdf = canvas.Canvas(output_path, pagesize=letter)
    width, height = letter
    
    # Add title
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(50, height - 50, title)
    
    # Add content
    pdf.setFont("Helvetica", 12)
    y_position = height - 100
    
    for line in text_content.split('\n'):
        if y_position < 50:
            pdf.showPage()
            pdf.setFont("Helvetica", 12)
            y_position = height - 50
        # Wrap long lines
        for i in range(0, len(line) if line else 1, 80):
            if y_position < 50:
                pdf.showPage()
                pdf.setFont("Helvetica", 12)
                y_position = height - 50
            pdf.drawString(50, y_position, line[i:i+80] if line else "")
            y_position -= 15
    
    pdf.save()
    
    return jsonify({
        'success': True,
        'output_file': output_filename,
        'message': 'PDF created successfully'
    })

# Route: Apply multiple edits to PDF
@app.route('/apply-edits', methods=['POST'])
def apply_edits():
    data = request.json
    filename = data.get('filename')
    edits = data.get('edits', [])
    
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
    
    try:
        # Create working copy
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        working_file = filepath
        
        # Apply each edit sequentially
        for edit in edits:
            operation = edit.get('operation')
            
            if operation == 'add_text':
                working_file = add_text_to_pdf(
                    working_file,
                    edit.get('text', ''),
                    edit.get('page', 0),
                    edit.get('x', 100),
                    edit.get('y', 100),
                    edit.get('font_size', 12),
                    edit.get('color', '#000000'),
                    edit.get('original_width', 612),
                    edit.get('original_height', 792)
                )
            
            elif operation == 'rotate':
                working_file = rotate_pdf_page(
                    working_file,
                    edit.get('page', 0),
                    edit.get('angle', 90)
                )
            
            elif operation == 'delete_page':
                working_file = delete_pdf_page(
                    working_file,
                    edit.get('page', 0)
                )
            
            elif operation == 'add_image':
                working_file = add_image_to_pdf(
                    working_file,
                    edit.get('image_data'),
                    edit.get('page', 0),
                    edit.get('x', 100),
                    edit.get('y', 100),
                    edit.get('width', 100),
                    edit.get('height', 100)
                )
            
            elif operation == 'draw_shape':
                working_file = add_shape_to_pdf(
                    working_file,
                    edit.get('shape', 'rectangle'),
                    edit.get('page', 0),
                    edit.get('x', 100),
                    edit.get('y', 100),
                    edit.get('width', 100),
                    edit.get('height', 100),
                    edit.get('color', '#000000')
                )
        
        # Move final result to output folder
        base_name = filename.rsplit('_', 1)[0] if '_' in filename else filename.rsplit('.', 1)[0]
        output_filename = f"{base_name}_edited_{timestamp}.pdf"
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
        
        # Copy the final working file to output
        if working_file != filepath:
            import shutil
            shutil.copy(working_file, output_path)
        else:
            import shutil
            shutil.copy(filepath, output_path)
        
        return jsonify({
            'success': True,
            'output_file': output_filename,
            'message': 'PDF edited successfully'
        })
    
    except Exception as e:
        return jsonify({'error': f'Error editing PDF: {str(e)}'}), 500

def add_text_to_pdf(filepath, text, page_num, x, y, font_size=12, color='#000000', orig_width=612, orig_height=792):
    """Add text overlay to PDF with proper coordinate conversion"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    output_path = os.path.join(app.config['TEMP_FOLDER'], f"temp_{timestamp}.pdf")
    
    # Read existing PDF to get actual page size
    existing_pdf = PdfReader(filepath)
    if page_num >= len(existing_pdf.pages):
        return filepath
    
    page = existing_pdf.pages[page_num]
    page_width = float(page.mediabox.width)
    page_height = float(page.mediabox.height)
    
    # Create text overlay
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=(page_width, page_height))
    can.setFont("Helvetica", font_size)
    
    # Convert hex color to RGB
    try:
        hex_color = color.lstrip('#')
        r, g, b = tuple(int(hex_color[i:i+2], 16)/255.0 for i in (0, 2, 4))
        can.setFillColorRGB(r, g, b)
    except:
        can.setFillColorRGB(0, 0, 0)
    
    # Convert coordinates (y is flipped in PDF)
    pdf_y = page_height - y
    
    can.drawString(x, pdf_y, text)
    can.save()
    packet.seek(0)
    
    # Merge with existing PDF
    overlay_pdf = PdfReader(packet)
    output = PdfWriter()
    
    # Add pages
    for i, pg in enumerate(existing_pdf.pages):
        if i == page_num:
            pg.merge_page(overlay_pdf.pages[0])
        output.add_page(pg)
    
    # Write output
    with open(output_path, 'wb') as f:
        output.write(f)
    
    return output_path

def rotate_pdf_page(filepath, page_num, angle):
    """Rotate a specific page"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    output_path = os.path.join(app.config['TEMP_FOLDER'], f"temp_{timestamp}.pdf")
    
    pdf_reader = PdfReader(filepath)
    pdf_writer = PdfWriter()
    
    for i, page in enumerate(pdf_reader.pages):
        if i == page_num:
            page.rotate(angle)
        pdf_writer.add_page(page)
    
    with open(output_path, 'wb') as f:
        pdf_writer.write(f)
    
    return output_path

def delete_pdf_page(filepath, page_num):
    """Delete a specific page"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    output_path = os.path.join(app.config['TEMP_FOLDER'], f"temp_{timestamp}.pdf")
    
    pdf_reader = PdfReader(filepath)
    pdf_writer = PdfWriter()
    
    for i, page in enumerate(pdf_reader.pages):
        if i != page_num:
            pdf_writer.add_page(page)
    
    with open(output_path, 'wb') as f:
        pdf_writer.write(f)
    
    return output_path

def add_image_to_pdf(filepath, image_data, page_num, x, y, width, height):
    """Add image overlay to PDF"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    output_path = os.path.join(app.config['TEMP_FOLDER'], f"temp_{timestamp}.pdf")
    
    # Decode base64 image
    image_bytes = base64.b64decode(image_data.split(',')[1])
    image = Image.open(io.BytesIO(image_bytes))
    
    # Read existing PDF
    existing_pdf = PdfReader(filepath)
    page = existing_pdf.pages[page_num]
    page_width = float(page.mediabox.width)
    page_height = float(page.mediabox.height)
    
    # Create image overlay
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=(page_width, page_height))
    
    pdf_y = page_height - y - height
    can.drawImage(ImageReader(image), x, pdf_y, width=width, height=height, preserveAspectRatio=True)
    can.save()
    packet.seek(0)
    
    # Merge
    overlay_pdf = PdfReader(packet)
    output = PdfWriter()
    
    for i, pg in enumerate(existing_pdf.pages):
        if i == page_num:
            pg.merge_page(overlay_pdf.pages[0])
        output.add_page(pg)
    
    with open(output_path, 'wb') as f:
        output.write(f)
    
    return output_path

def add_shape_to_pdf(filepath, shape, page_num, x, y, width, height, color):
    """Add shape to PDF"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    output_path = os.path.join(app.config['TEMP_FOLDER'], f"temp_{timestamp}.pdf")
    
    existing_pdf = PdfReader(filepath)
    page = existing_pdf.pages[page_num]
    page_width = float(page.mediabox.width)
    page_height = float(page.mediabox.height)
    
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=(page_width, page_height))
    
    # Convert color
    try:
        hex_color = color.lstrip('#')
        r, g, b = tuple(int(hex_color[i:i+2], 16)/255.0 for i in (0, 2, 4))
        can.setStrokeColorRGB(r, g, b)
        can.setFillColorRGB(r, g, b, alpha=0.3)
    except:
        can.setStrokeColorRGB(0, 0, 0)
    
    pdf_y = page_height - y - height
    
    if shape == 'rectangle':
        can.rect(x, pdf_y, width, height, stroke=1, fill=1)
    elif shape == 'circle':
        radius = min(width, height) / 2
        can.circle(x + radius, pdf_y + radius, radius, stroke=1, fill=1)
    elif shape == 'line':
        can.line(x, pdf_y, x + width, pdf_y + height)
    
    can.save()
    packet.seek(0)
    
    overlay_pdf = PdfReader(packet)
    output = PdfWriter()
    
    for i, pg in enumerate(existing_pdf.pages):
        if i == page_num:
            pg.merge_page(overlay_pdf.pages[0])
        output.add_page(pg)
    
    with open(output_path, 'wb') as f:
        output.write(f)
    
    return output_path

# Route: Merge PDFs
@app.route('/merge-pdfs', methods=['POST'])
def merge_pdfs():
    files = request.files.getlist('files')
    
    if len(files) < 2:
        return jsonify({'error': 'Please upload at least 2 PDFs to merge'}), 400
    
    try:
        merger = PdfMerger()
        
        for file in files:
            if file and allowed_file(file.filename):
                merger.append(file)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"merged_{timestamp}.pdf"
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
        
        merger.write(output_path)
        merger.close()
        
        return jsonify({
            'success': True,
            'output_file': output_filename,
            'message': 'PDFs merged successfully'
        })
    except Exception as e:
        return jsonify({'error': f'Error merging PDFs: {str(e)}'}), 500

# Route: Compress PDF
@app.route('/compress-pdf', methods=['POST'])
def compress_pdf():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    
    try:
        pdf_reader = PdfReader(file)
        pdf_writer = PdfWriter()
        
        for page in pdf_reader.pages:
            page.compress_content_streams()
            pdf_writer.add_page(page)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"compressed_{timestamp}.pdf"
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
        
        with open(output_path, 'wb') as f:
            pdf_writer.write(f)
        
        return jsonify({
            'success': True,
            'output_file': output_filename,
            'message': 'PDF compressed successfully'
        })
    except Exception as e:
        return jsonify({'error': f'Error compressing PDF: {str(e)}'}), 500

# Route: Download file
@app.route('/download/<filename>')
def download_file(filename):
    filepath = os.path.join(app.config['OUTPUT_FOLDER'], filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return jsonify({'error': 'File not found'}), 404

# Route: Clean up old files
@app.route('/cleanup')
def cleanup_files():
    import time
    current_time = time.time()
    
    for folder in [app.config['UPLOAD_FOLDER'], app.config['OUTPUT_FOLDER'], app.config['TEMP_FOLDER']]:
        for filename in os.listdir(folder):
            filepath = os.path.join(folder, filename)
            if os.path.isfile(filepath):
                file_age = current_time - os.path.getmtime(filepath)
                if file_age > 3600:  # 1 hour
                    os.remove(filepath)
    
    return jsonify({'success': True, 'message': 'Cleanup completed'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)