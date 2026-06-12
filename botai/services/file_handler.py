"""
File handler service - Upload, validate, parse, store, fetch, and scraper utilities
"""
import os
import re
import shutil
import tempfile
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from bson import ObjectId
from bs4 import BeautifulSoup
from botai.config import settings
from botai.utils.validators import validate_file_type

class FileHandler:
    """Handles file uploads, validations, parsing, Google Drive fetching, and Web scraping"""
    
    @staticmethod
    def get_file_type(filename: str) -> str:
        """Determine file type by extension"""
        ext = filename.lower().split('.')[-1] if '.' in filename else ''
        for file_type, extensions in settings.ALLOWED_FILE_TYPES.items():
            if ext in extensions:
                return file_type
        return 'unknown'
    
    @staticmethod
    def validate_file(filename: str, file_size: int) -> tuple[bool, str]:
        """
        Validate file before upload
        Returns: (is_valid: bool, error_message: str)
        """
        if not filename:
            return False, "Filename is required"
        if file_size == 0:
            return False, "File is empty"
        if file_size > settings.MAX_FILE_SIZE_BYTES:
            max_mb = settings.MAX_FILE_SIZE_BYTES // (1024 * 1024)
            return False, f"File too large (max {max_mb}MB, got {file_size // (1024*1024)}MB)"
        
        file_type = FileHandler.get_file_type(filename)
        if file_type == 'unknown':
            ext = filename.split('.')[-1]
            return False, f"File type not allowed: .{ext}"
        
        return True, ""
    
    @staticmethod
    def save_file(file_data: bytes, filename: str, user_id: str, db) -> tuple[bool, str]:
        """
        Save uploaded file to disk and database
        Returns: (success: bool, file_id_or_error: str)
        """
        try:
            is_valid, error_msg = FileHandler.validate_file(filename, len(file_data))
            if not is_valid:
                return False, error_msg
            
            file_type = FileHandler.get_file_type(filename)
            dest_dir = settings.UPLOAD_DIR / file_type
            dest_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate unique filename
            unique_filename = f"{ObjectId()}_{filename}"
            dest_path = dest_dir / unique_filename
            
            # Save file to disk
            with open(dest_path, 'wb') as f:
                f.write(file_data)
            
            size_bytes = dest_path.stat().st_size
            
            # Save metadata to MongoDB
            file_id = ObjectId()
            file_doc = {
                '_id': file_id,
                'user_id': ObjectId(user_id),
                'filename': filename,
                'file_type': file_type,
                'size_bytes': size_bytes,
                'path': str(dest_path),
                'created_at': datetime.utcnow()
            }
            db.files.insert_one(file_doc)
            
            print(f"[FileHandler] File saved: {filename} ({file_type})")
            return True, str(file_id)
        except Exception as e:
            print(f"[FileHandler] Error uploading file: {e}")
            return False, f"Error uploading file: {str(e)}"
    
    @staticmethod
    def get_file_path(file_id: str, db) -> tuple[bool, str]:
        """
        Get file path from database
        Returns: (success: bool, path_or_error: str)
        """
        try:
            file_doc = db.files.find_one({'_id': ObjectId(file_id)})
            if not file_doc:
                return False, f"File not found: {file_id}"
            return True, file_doc['path']
        except Exception as e:
            return False, f"Error retrieving file: {str(e)}"
    
    @staticmethod
    def get_file_content(file_id: str, db) -> tuple[bool, str]:
        """
        Read file content (supports PDF, Word, Excel, CSV, and text-based files)
        Returns: (success: bool, content_or_error: str)
        """
        try:
            success, path = FileHandler.get_file_path(file_id, db)
            if not success:
                return False, path
            
            content = FileHandler.parse_file(path)
            if content.startswith('[') and content.endswith(']'):
                # Indicates error returned by parser
                return False, content
            return True, content[:10000]
        except Exception as e:
            return False, f"Error reading file: {str(e)}"
    
    @staticmethod
    def delete_file(file_id: str, user_id: str, db) -> tuple[bool, str]:
        """
        Delete file and metadata
        Returns: (success: bool, message_or_error: str)
        """
        try:
            file_doc = db.files.find_one({
                '_id': ObjectId(file_id),
                'user_id': ObjectId(user_id)
            })
            if not file_doc:
                return False, "File not found or access denied"
            
            # Delete physical file
            if os.path.exists(file_doc['path']):
                os.remove(file_doc['path'])
                print(f"[FileHandler] Deleted file: {file_doc['path']}")
            
            # Delete metadata
            db.files.delete_one({'_id': ObjectId(file_id)})
            return True, "File deleted successfully"
        except Exception as e:
            return False, f"Error deleting file: {str(e)}"
    
    @staticmethod
    def list_user_files(user_id: str, db) -> list:
        """
        Get all files uploaded by a user
        Returns: List of file documents
        """
        try:
            files = list(db.files.find({
                'user_id': ObjectId(user_id)
            }).sort('created_at', -1))
            return [
                {
                    'file_id': str(f['_id']),
                    'filename': f['filename'],
                    'file_type': f['file_type'],
                    'size_mb': round(f['size_bytes'] / (1024*1024), 2),
                    'created_at': f['created_at'].isoformat()
                }
                for f in files
            ]
        except Exception as e:
            print(f"[FileHandler] Error listing files: {e}")
            return []

    # ========== SCRAPING & TELEMETRY PARSING EXTENSIONS ==========

    @staticmethod
    def parse_file(filepath: str) -> str:
        """
        Extract readable plain text content from a file depending on its extension.
        Supports: PDF, DOCX, DOC, XLSX, XLS, and text files.
        """
        lower_path = filepath.lower()
        text = ""
        
        # PDF Parsing
        if lower_path.endswith('.pdf'):
            try:
                from pdfminer.high_level import extract_text as pdf_extract
                text = pdf_extract(filepath)
            except ImportError:
                text = "[PDF found but pdfminer.six not installed. Run: pip install pdfminer.six]"
            except Exception as e:
                text = f"[PDF extraction error: {e}]"
                
        # Word Doc Parsing
        elif lower_path.endswith('.docx') or lower_path.endswith('.doc'):
            try:
                import mammoth
                with open(filepath, 'rb') as f:
                    text = mammoth.extract_raw_text(f).value
            except ImportError:
                try:
                    from docx import Document
                    text = '\n'.join([p.text for p in Document(filepath).paragraphs])
                except ImportError:
                    text = "[Word file found but mammoth/python-docx not installed.]"
            except Exception as e:
                text = f"[Word extraction error: {e}]"
                
        # Excel XLSX Parsing
        elif lower_path.endswith('.xlsx'):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(filepath, data_only=True)
                sheets_text = []
                for sheet_name in wb.sheetnames:
                    sheet = wb[sheet_name]
                    sheet_lines = [f"--- Sheet: {sheet_name} ---"]
                    for row in sheet.iter_rows(values_only=True):
                        if row and any(cell is not None and str(cell).strip() != "" for cell in row):
                            row_str = " | ".join(str(cell).strip() if cell is not None else "" for cell in row)
                            sheet_lines.append(row_str)
                    if len(sheet_lines) > 1:
                        sheets_text.append("\n".join(sheet_lines))
                text = "\n\n".join(sheets_text)
            except Exception as e:
                text = f"[Excel extraction error (.xlsx): {e}]"
                
        # Excel XLS Parsing
        elif lower_path.endswith('.xls'):
            try:
                import xlrd
                wb = xlrd.open_workbook(filepath)
                sheets_text = []
                for sheet_idx in range(wb.nsheets):
                    sheet = wb.sheet_by_index(sheet_idx)
                    sheet_lines = [f"--- Sheet: {sheet.name} ---"]
                    for row_idx in range(sheet.nrows):
                        row = sheet.row_values(row_idx)
                        if row and any(cell is not None and str(cell).strip() != "" for cell in row):
                            row_str = " | ".join(str(cell).strip() if cell is not None else "" for cell in row)
                            sheet_lines.append(row_str)
                    if len(sheet_lines) > 1:
                        sheets_text.append("\n".join(sheet_lines))
                text = "\n\n".join(sheets_text)
            except Exception as e:
                text = f"[Excel extraction error (.xls): {e}]"
                
        # Plain Text / Scripts Parsing
        elif any(lower_path.endswith(ext) for ext in ['.txt', '.csv', '.md', '.py', '.js', '.json', '.xml', '.html', '.log']):
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
            except Exception as e:
                text = f"[Text read error: {e}]"
        else:
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    raw = f.read()
                text = raw if raw.strip() else ""
            except Exception:
                text = ""
        return text

    @staticmethod
    def extract_gdrive_file_id(url: str) -> str:
        """Extract Google Drive file/folder ID from multiple URL patterns"""
        patterns = [
            r'/file/d/([a-zA-Z0-9_-]{10,})',
            r'id=([a-zA-Z0-9_-]{10,})',
            r'/d/([a-zA-Z0-9_-]{10,})',
            r'/folders/([a-zA-Z0-9_-]{10,})',
        ]
        for pattern in patterns:
            m = re.search(pattern, url)
            if m:
                return m.group(1)
        return None

    @staticmethod
    def fetch_gdrive_text(url: str) -> str:
        """Download public Drive documents or folders using gdown and parse text content"""
        file_id = FileHandler.extract_gdrive_file_id(url)
        if not file_id:
            return "[Could not parse Google Drive file ID from the provided link.]"

        is_folder = '/folders/' in url
        tmp_dir = tempfile.mkdtemp()

        try:
            import gdown
        except ImportError:
            return "[gdown not installed. Run: pip install gdown]"

        # Google Drive Folder
        if is_folder:
            print(f"[Drive Fetcher] Downloading FOLDER ID: {file_id}")
            folder_path = os.path.join(tmp_dir, 'drive_folder')
            os.makedirs(folder_path, exist_ok=True)
            try:
                gdown.download_folder(id=file_id, output=folder_path, quiet=True, use_cookies=False)
            except Exception as e:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return f"[Google Drive folder download failed: {e}. Share the folder as 'Anyone with the link'.]"

            downloaded_files = []
            for root, dirs, files in os.walk(folder_path):
                for fname in files:
                    downloaded_files.append(os.path.join(root, fname))

            if not downloaded_files:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return "[Google Drive folder appears empty or is restricted. Share it as 'Anyone with the link'.]"

            print(f"[Drive Fetcher] Downloaded {len(downloaded_files)} files from folder")
            all_text = []
            for fpath in downloaded_files[:10]:
                fname = os.path.basename(fpath)
                t = FileHandler.parse_file(fpath)
                if t and t.strip():
                    all_text.append(f"--- File: {fname} ---\n{t.strip()}")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            combined = "\n\n".join(all_text)
            return combined[:10000] if combined else "[No readable text found in the Google Drive folder.]"

        # Google Drive Single File
        else:
            print(f"[Drive Fetcher] Downloading FILE ID: {file_id}")
            dest_file = os.path.join(tmp_dir, 'drive_file')
            try:
                gdown.download(id=file_id, output=dest_file, quiet=True, use_cookies=False)
            except Exception as e:
                # Try fallback download URL directly
                direct_url = f"https://docs.google.com/uc?export=download&id={file_id}"
                try:
                    req = urllib.request.Request(direct_url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, timeout=15) as response:
                        with open(dest_file, 'wb') as f:
                            f.write(response.read())
                except Exception as direct_err:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    return f"[Google Drive file download failed: {e} / {direct_err}. Make sure it is shared as 'Anyone with the link'.]"

            if not os.path.exists(dest_file) or os.path.getsize(dest_file) == 0:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return "[Google Drive file downloaded but appears empty or invalid.]"

            text = FileHandler.parse_file(dest_file)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return text[:8000] if text else "[Could not extract readable text content from the Google Drive file.]"

    @staticmethod
    def fetch_url_text(url: str) -> str:
        """Scrapes web page URL, strips standard headers/scripts, and returns page text context"""
        try:
            url = url.strip()
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5'
                }
            )
            with urllib.request.urlopen(req, timeout=8) as response:
                html = response.read()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Decompose script/style blocks
                for element in soup(["script", "style", "noscript", "iframe", "header", "footer", "nav"]):
                    element.decompose()
                    
                text = soup.get_text()
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                clean_text = '\n'.join(chunk for chunk in chunks if chunk)
                return clean_text[:6000]
        except Exception as e:
            print(f"[Web Fetcher] Error fetching {url}: {e}")
            return f"[Failed to retrieve webpage content from {url} due to error: {e}]"
