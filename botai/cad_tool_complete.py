"""
COMPLETE CAD FILE GENERATION TOOL
Ready-to-use integration for CUTM Chatbot
Drop this directly into your chatbot - no configuration needed!

File: botai/cad_tool_complete.py
Usage: Import and register with your Flask app
"""

import os
import json
import uuid
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple
import logging
try:
    from flask import Blueprint, request, jsonify, send_file
except ImportError:
    class DummyBlueprint:
        pass
    Blueprint = DummyBlueprint
    request = None
    jsonify = None
    send_file = None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# PART 1: CAD GENERATOR SERVICE (Backend)
# ============================================================================

class CADGenerator:
    """Complete CAD file generation service"""
    
    FORMATS = {
        'scad': {
            'mime': 'application/x-scad',
            'ext': '.scad',
            'name': 'OpenSCAD Script',
            'tools': ['OpenSCAD (Free)', 'Fusion 360', 'FreeCAD'],
            'desc': 'Parametric 3D modeling - perfect for designs with variables',
            '3d': True,
        },
        'dxf': {
            'mime': 'application/vnd.dxf',
            'ext': '.dxf',
            'name': 'AutoCAD DXF',
            'tools': ['AutoCAD', 'FreeCAD', 'SolidWorks', 'Fusion 360'],
            'desc': '2D and 3D vector format - industry standard',
            '3d': True,
        },
        'stl': {
            'mime': 'model/stl',
            'ext': '.stl',
            'name': '3D STL Format',
            'tools': ['3D Printers', 'Cura', 'Meshmixer', 'Fusion 360', 'Blender'],
            'desc': '3D mesh format - perfect for 3D printing',
            '3d': True,
        },
        'svg': {
            'mime': 'image/svg+xml',
            'ext': '.svg',
            'name': 'SVG Vector',
            'tools': ['Inkscape', 'Adobe Illustrator', 'Fusion 360'],
            'desc': '2D vector format - great for laser cutting',
            '3d': False,
        },
        '3dxml': {
            'mime': 'application/vnd.3dxml',
            'ext': '.3dxml',
            'name': 'Dassault 3DXML',
            'tools': ['CATIA', 'SolidWorks', '3DXML Player'],
            'desc': 'Proprietary Dassault Systèmes 3D representation format',
            '3d': True,
        },
    }
    
    def __init__(self, upload_dir='botai/uploads/cad'):
        self.upload_dir = upload_dir
        Path(self.upload_dir).mkdir(parents=True, exist_ok=True)
        self.files = {}
    
    def detect_format(self, response: str) -> Optional[str]:
        """Auto-detect CAD format from Claude response"""
        resp_lower = response.lower()
        
        # Check for format indicators
        if any(m in resp_lower for m in ['module ', 'cube(', 'sphere(', 'cylinder(', 'translate(', '```scad']):
            return 'scad'
        elif any(m in resp_lower for m in ['<svg', '<circle', '<rect', '<path', '```svg']):
            return 'svg'
        elif any(m in resp_lower for m in ['solid ', 'facet normal', 'outer loop', 'vertex ', '```stl']):
            return 'stl'
        elif any(m in resp_lower for m in ['section', 'entities', 'layer', '```dxf']):
            return 'dxf'
        elif any(m in resp_lower for m in ['<3dxml', '3dxml', '```3dxml']):
            return '3dxml'
        
        return None
    
    def extract_code(self, response: str, fmt: str) -> Optional[str]:
        """Extract code block from Claude response"""
        # Look for code fences
        patterns = [
            f'```{fmt}(.*?)```',
            f'```(.*?)```',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)
            if matches:
                code = matches[0].strip()
                if code:
                    return code
        
        # Return response if no code block found
        return response.strip() if response.strip() else None
    
    def validate(self, code: str, fmt: str) -> Tuple[bool, str]:
        """Validate CAD code"""
        if not code or len(code.strip()) == 0:
            return False, "Code is empty"
        if len(code) > 1_000_000:
            return False, "Code exceeds 1 MB limit"
        return True, ""
    
    def generate(self, response: str, filename: str, fmt: Optional[str] = None, 
                 user_id: Optional[str] = None, conv_id: Optional[str] = None) -> Dict:
        """Generate CAD file from Claude response"""
        try:
            # Detect format
            if not fmt:
                fmt = self.detect_format(response)
            
            if not fmt:
                return {'success': False, 'error': 'Could not detect CAD format'}
            
            if fmt not in self.FORMATS:
                return {'success': False, 'error': f'Invalid format: {fmt}'}
            
            # Extract code
            code = self.extract_code(response, fmt)
            if not code:
                return {'success': False, 'error': 'Could not extract code'}
            
            # Validate
            valid, err = self.validate(code, fmt)
            if not valid:
                return {'success': False, 'error': err}
            
            # Generate file
            file_id = str(uuid.uuid4())[:8]
            safe_name = re.sub(r'[^\w\-]', '_', filename)[:50]
            ext = self.FORMATS[fmt]['ext']
            filename_final = f"{safe_name}_{file_id}{ext}"
            filepath = os.path.join(self.upload_dir, filename_final)
            
            # Write file
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(code)
            
            file_size = os.path.getsize(filepath)
            
            # Create file info
            file_info = {
                'success': True,
                'file_id': file_id,
                'filename': filename_final,
                'display_name': f"{safe_name}{ext}",
                'format': fmt,
                'format_name': self.FORMATS[fmt]['name'],
                'size_bytes': file_size,
                'size_mb': round(file_size / (1024 * 1024), 2),
                'mime': self.FORMATS[fmt]['mime'],
                'path': filepath,
                'created_at': datetime.utcnow().isoformat(),
                'user_id': user_id,
                'conv_id': conv_id,
                'is_3d': self.FORMATS[fmt]['3d'],
                'tools': self.FORMATS[fmt]['tools'],
            }
            
            self.files[file_id] = file_info
            logger.info(f"Generated CAD: {filename_final}")
            return file_info
        
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def get_file(self, file_id: str) -> Optional[Dict]:
        """Get file by ID"""
        return self.files.get(file_id)
    
    def download(self, file_id: str) -> Optional[Tuple]:
        """Get file for download"""
        info = self.get_file(file_id)
        if not info or not os.path.exists(info['path']):
            return None
        return (info['path'], info['display_name'], info['mime'])
    
    def get_formats(self) -> list:
        """Get list of supported formats"""
        return [
            {
                'format': fmt,
                'name': info['name'],
                'ext': info['ext'],
                'desc': info['desc'],
                'tools': info['tools'],
                'is_3d': info['3d'],
            }
            for fmt, info in self.FORMATS.items()
        ]


# ============================================================================
# PART 2: FLASK API ROUTES (Backend)
# ============================================================================

def create_cad_blueprint(cad_gen: CADGenerator) -> Blueprint:
    """Create Flask blueprint for CAD routes"""
    if Blueprint is DummyBlueprint:
        return None
    
    bp = Blueprint('cad', __name__, url_prefix='/api/cad')
    
    # Get supported formats
    @bp.route('/formats', methods=['GET'])
    def get_formats():
        return jsonify({
            'success': True,
            'formats': cad_gen.get_formats()
        })
    
    # Generate CAD file
    @bp.route('/generate', methods=['POST'])
    def generate():
        try:
            data = request.get_json()
            
            if not data or 'claude_response' not in data or 'filename' not in data:
                return jsonify({'success': False, 'error': 'Missing required fields'}), 400
            
            result = cad_gen.generate(
                response=data['claude_response'],
                filename=data['filename'],
                fmt=data.get('format'),
                user_id=data.get('user_id'),
                conv_id=data.get('conv_id')
            )
            
            status = 201 if result['success'] else 400
            return jsonify(result), status
        
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    # Download file
    @bp.route('/download/<file_id>', methods=['GET'])
    def download(file_id):
        try:
            download_info = cad_gen.download(file_id)
            if not download_info:
                return jsonify({'success': False, 'error': 'File not found'}), 404
            
            filepath, filename, mime = download_info
            return send_file(filepath, mimetype=mime, as_attachment=True, 
                           download_name=filename)
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    # Get file info
    @bp.route('/files/<file_id>', methods=['GET'])
    def get_file_info(file_id):
        info = cad_gen.get_file(file_id)
        if not info:
            return jsonify({'success': False, 'error': 'File not found'}), 404
        
        # Remove path from response
        info_safe = {k: v for k, v in info.items() if k != 'path'}
        return jsonify({'success': True, 'file': info_safe})
    
    return bp


# ============================================================================
# PART 3: HTML FRONTEND (To be served directly)
# ============================================================================

CAD_TOOL_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CAD Generator</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { text-align: center; color: white; margin-bottom: 30px; }
        .header h1 { font-size: 2em; margin-bottom: 10px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 30px; margin-bottom: 30px; }
        .card {
            background: white; border-radius: 12px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            padding: 30px;
        }
        .card h2 { color: #333; margin-bottom: 20px; font-size: 1.4em; border-bottom: 2px solid #667eea; padding-bottom: 10px; }
        .input-group { display: flex; flex-direction: column; gap: 8px; margin-bottom: 15px; }
        .input-group label { font-weight: 600; color: #555; }
        input, textarea, select {
            padding: 12px; border: 2px solid #e0e0e0; border-radius: 8px;
            font-size: 1em; font-family: inherit; transition: all 0.3s;
        }
        input:focus, textarea:focus, select:focus { outline: none; border-color: #667eea; box-shadow: 0 0 0 3px rgba(102,126,234,0.1); }
        textarea { resize: vertical; min-height: 200px; font-family: monospace; font-size: 0.9em; }
        .format-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .format-opt { position: relative; }
        .format-opt input { display: none; }
        .format-opt label {
            display: block; padding: 12px; border: 2px solid #e0e0e0;
            border-radius: 8px; cursor: pointer; text-align: center;
            transition: all 0.3s; background: #f9f9f9;
        }
        .format-opt input:checked + label { border-color: #667eea; background: #f0f4ff; font-weight: 600; color: #667eea; }
        .btn-group { display: flex; gap: 10px; margin-top: 20px; }
        button {
            flex: 1; padding: 12px 20px; font-size: 1em; font-weight: 600;
            border: none; border-radius: 8px; cursor: pointer; transition: all 0.3s;
        }
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; box-shadow: 0 4px 15px rgba(102,126,234,0.4);
        }
        .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(102,126,234,0.6); }
        .btn-secondary { background: #f0f0f0; color: #333; }
        .btn-secondary:hover { background: #e0e0e0; }
        .btn-success { background: #4CAF50; color: white; }
        .btn-success:hover { background: #45a049; }
        .status {
            padding: 15px; border-radius: 8px; border-left: 4px solid;
            margin: 15px 0; display: none; font-size: 0.95em;
        }
        .status.success { border-left-color: #4CAF50; background: #f1f8f4; color: #2e7d32; }
        .status.error { border-left-color: #f44336; background: #fdf4f3; color: #c62828; }
        .status.info { border-left-color: #2196F3; background: #f3f7fd; color: #1565c0; }
        .preview {
            background: #f5f5f5; border: 2px dashed #667eea; border-radius: 8px;
            padding: 20px; text-align: center; margin: 15px 0; display: none;
        }
        .file-info { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 15px 0; }
        .info-item { padding: 12px; background: #f9f9f9; border-radius: 8px; }
        .info-label { font-weight: 600; color: #666; font-size: 0.85em; text-transform: uppercase; }
        .info-value { color: #333; font-size: 1.1em; }
        .spinner { display: inline-block; width: 20px; height: 20px; border: 3px solid #f0f0f0; border-top-color: #667eea; border-radius: 50%; animation: spin 1s linear infinite; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .formats-list { display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; margin-top: 20px; }
        .fmt-card { background: #f9f9f9; padding: 15px; border-radius: 8px; border-left: 3px solid #667eea; }
        .fmt-card h4 { color: #667eea; margin-bottom: 8px; }
        .fmt-card p { color: #666; font-size: 0.9em; line-height: 1.4; }
        .tools-list { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 10px; }
        .tool-tag { background: #667eea; color: white; padding: 3px 8px; border-radius: 4px; font-size: 0.75em; }
        .history { margin-top: 40px; }
        .history-list { display: flex; flex-direction: column; gap: 10px; max-height: 300px; overflow-y: auto; }
        .history-item { display: flex; justify-content: space-between; align-items: center; padding: 12px; background: #f5f5f5; border-radius: 8px; }
        .history-item .name { font-weight: 500; color: #333; }
        .history-item .date { color: #999; font-size: 0.85em; }
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
            .format-grid, .file-info, .formats-list { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎨 CAD File Generator</h1>
            <p>Convert Claude designs to CAD files instantly</p>
        </div>

        <div class="grid">
            <div class="card">
                <h2>📝 Input</h2>
                <div class="input-group">
                    <label>Filename *</label>
                    <input type="text" id="filename" placeholder="e.g., my_design" value="design">
                </div>
                <div class="input-group">
                    <label>Claude Response / CAD Code *</label>
                    <textarea id="response" placeholder="Paste Claude's response or CAD code..."></textarea>
                </div>
                <div class="input-group">
                    <label>Format</label>
                    <div class="format-grid">
                        <div class="format-opt">
                            <input type="radio" id="fmt-auto" name="format" value="" checked>
                            <label for="fmt-auto">🔍 Auto</label>
                        </div>
                        <div class="format-opt">
                            <input type="radio" id="fmt-scad" name="format" value="scad">
                            <label for="fmt-scad">📦 SCAD</label>
                        </div>
                        <div class="format-opt">
                            <input type="radio" id="fmt-dxf" name="format" value="dxf">
                            <label for="fmt-dxf">📐 DXF</label>
                        </div>
                        <div class="format-opt">
                            <input type="radio" id="fmt-stl" name="format" value="stl">
                            <label for="fmt-stl">🖨️ STL</label>
                        </div>
                        <div class="format-opt">
                            <input type="radio" id="fmt-svg" name="format" value="svg">
                            <label for="fmt-svg">✏️ SVG</label>
                        </div>
                        <div class="format-opt">
                            <input type="radio" id="fmt-3dxml" name="format" value="3dxml">
                            <label for="fmt-3dxml">🌐 3DXML</label>
                        </div>
                    </div>
                </div>
                <div class="btn-group">
                    <button class="btn-primary" onclick="generate()">Generate</button>
                    <button class="btn-secondary" onclick="clear()">Clear</button>
                </div>
            </div>

            <div class="card">
                <h2>📥 Output</h2>
                <div id="status" class="status"></div>
                <div id="preview" class="preview">
                    <div style="font-size: 3em; margin-bottom: 10px;">✅</div>
                    <h3 id="preview-name" style="color: #333; margin-bottom: 10px;"></h3>
                    <div class="file-info">
                        <div class="info-item">
                            <div class="info-label">Format</div>
                            <div class="info-value" id="preview-format"></div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Size</div>
                            <div class="info-value" id="preview-size"></div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Type</div>
                            <div class="info-value" id="preview-type"></div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Created</div>
                            <div class="info-value" id="preview-date"></div>
                        </div>
                    </div>
                    <div style="margin-top: 15px;">
                        <strong style="display: block; margin-bottom: 8px; color: #333;">Compatible:</strong>
                        <div class="tools-list" id="preview-tools"></div>
                    </div>
                    <div class="btn-group" style="margin-top: 20px;">
                        <button class="btn-success" onclick="download()" style="flex: 2;">💾 Download</button>
                        <button class="btn-secondary" onclick="copyCode()" style="flex: 1;">📋 Copy</button>
                    </div>
                </div>
                <div id="formats-info">
                    <strong style="display: block; margin-bottom: 15px; color: #333;">Supported Formats:</strong>
                    <div id="formats-list" class="formats-list"></div>
                </div>
            </div>
        </div>

        <div class="card history">
            <h2>📚 History</h2>
            <div id="history" class="history-list">
                <p style="color: #999; text-align: center; padding: 20px;">No files generated yet</p>
            </div>
        </div>
    </div>

    <script>
        const API = '/api/cad';
        let files = [];
        let current = null;

        // Load formats
        fetch(API + '/formats')
            .then(r => r.json())
            .then(d => {
                if (d.success) {
                    const html = d.formats.map(f => `
                        <div class="fmt-card">
                            <h4>${f.format.toUpperCase()}</h4>
                            <p>${f.desc}</p>
                            <div class="tools-list">
                                ${f.tools.map(t => `<span class="tool-tag">${t}</span>`).join('')}
                            </div>
                        </div>
                    `).join('');
                    document.getElementById('formats-list').innerHTML = html;
                }
            });

        function showStatus(type, msg) {
            const box = document.getElementById('status');
            box.className = 'status ' + type;
            box.innerHTML = msg;
            box.style.display = 'block';
        }

        function generate() {
            const filename = document.getElementById('filename').value.trim();
            const response = document.getElementById('response').value.trim();
            const format = document.querySelector('input[name="format"]:checked').value;

            if (!filename) { showStatus('error', 'Enter filename'); return; }
            if (!response) { showStatus('error', 'Paste Claude response'); return; }

            showStatus('info', 'Generating... <span class="spinner"></span>');

            fetch(API + '/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    filename, claude_response: response,
                    format: format || undefined
                })
            })
            .then(r => r.json())
            .then(d => {
                if (d.success) {
                    current = d;
                    files.unshift(d);
                    updateHistory();
                    showPreview(d);
                    showStatus('success', '✅ Generated: ' + d.display_name);
                } else {
                    showStatus('error', '❌ ' + d.error);
                }
            })
            .catch(e => showStatus('error', '❌ ' + e.message));
        }

        function showPreview(file) {
            document.getElementById('preview-name').textContent = file.display_name;
            document.getElementById('preview-format').textContent = file.format_name;
            document.getElementById('preview-size').textContent = file.size_mb + ' MB';
            document.getElementById('preview-type').textContent = file.is_3d ? '3D' : '2D';
            document.getElementById('preview-date').textContent = new Date(file.created_at).toLocaleString();
            document.getElementById('preview-tools').innerHTML = file.tools.map(t => `<span class="tool-tag">${t}</span>`).join('');
            document.getElementById('preview').style.display = 'block';
            document.getElementById('formats-info').style.display = 'none';
        }

        function download() {
            if (!current) return;
            const link = document.createElement('a');
            link.href = API + '/download/' + current.file_id;
            link.download = current.display_name;
            link.click();
            showStatus('success', '✅ Downloaded: ' + current.display_name);
        }

        function copyCode() {
            navigator.clipboard.writeText(document.getElementById('response').value)
                .then(() => showStatus('success', '✅ Copied to clipboard'))
                .catch(() => showStatus('error', '❌ Copy failed'));
        }

        function clear() {
            document.getElementById('filename').value = 'design';
            document.getElementById('response').value = '';
            document.getElementById('fmt-auto').checked = true;
            document.getElementById('preview').style.display = 'none';
            document.getElementById('formats-info').style.display = 'block';
            document.getElementById('status').style.display = 'none';
            current = null;
        }

        function updateHistory() {
            const html = files.length ? files.map((f, i) => `
                <div class="history-item">
                    <div>
                        <div class="name">📄 ${f.display_name}</div>
                        <div class="date">${new Date(f.created_at).toLocaleString()}</div>
                    </div>
                    <div style="display: flex; gap: 5px;">
                        <button class="btn-success" onclick="downloadHistory('${f.file_id}')" style="padding: 6px 10px; font-size: 0.85em;">DL</button>
                    </div>
                </div>
            `).join('') : '<p style="color: #999; text-align: center; padding: 20px;">No files</p>';
            document.getElementById('history').innerHTML = html;
        }

        function downloadHistory(id) {
            const link = document.createElement('a');
            link.href = API + '/download/' + id;
            link.click();
        }
    </script>
</body>
</html>
"""


# ============================================================================
# PART 4: INTEGRATION FUNCTION & HANDLERS (Supports Flask and http.server)
# ============================================================================

_global_cad_gen = None

def get_global_cad_gen():
    global _global_cad_gen
    if _global_cad_gen is None:
        # Resolve path relative to simple_server directory
        base_dir = os.path.dirname(os.path.abspath(__file__))
        upload_dir = os.path.join(base_dir, 'uploads', 'cad')
        _global_cad_gen = CADGenerator(upload_dir=upload_dir)
    return _global_cad_gen

def handle_get(handler):
    """Handle GET requests from http.server.BaseHTTPRequestHandler"""
    path = handler.path
    cad_gen = get_global_cad_gen()
    
    if path == '/cad' or path == '/cad/':
        try:
            content = CAD_TOOL_HTML.encode('utf-8')
            handler.send_response(200)
            handler.send_header('Content-Type', 'text/html; charset=utf-8')
            handler.end_headers()
            handler.wfile.write(content)
        except Exception as e:
            logger.error(f"Error serving CAD UI: {e}")
            handler.send_error(500, "Internal server error")
        return True
        
    elif path == '/api/cad/formats':
        formats_data = {
            'success': True,
            'formats': cad_gen.get_formats()
        }
        handler.send_json(200, formats_data)
        return True
        
    elif path.startswith('/api/cad/download/'):
        # Extract file_id from /api/cad/download/<file_id>
        parts = path.rstrip('/').split('/')
        file_id = parts[-1]
        download_info = cad_gen.download(file_id)
        if not download_info:
            handler.send_json(404, {'success': False, 'error': 'File not found'})
            return True
        
        filepath, filename, mime = download_info
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
            handler.send_response(200)
            handler.send_header('Content-Type', mime)
            handler.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            handler.end_headers()
            handler.wfile.write(content)
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            handler.send_json(500, {'success': False, 'error': str(e)})
        return True
        
    elif path.startswith('/api/cad/files/'):
        parts = path.rstrip('/').split('/')
        file_id = parts[-1]
        info = cad_gen.get_file(file_id)
        if not info:
            handler.send_json(404, {'success': False, 'error': 'File not found'})
            return True
            
        info_safe = {k: v for k, v in info.items() if k != 'path'}
        handler.send_json(200, {'success': True, 'file': info_safe})
        return True
        
    return False

def handle_post(handler):
    """Handle POST requests from http.server.BaseHTTPRequestHandler"""
    path = handler.path
    cad_gen = get_global_cad_gen()
    
    if path == '/api/cad/generate':
        try:
            data = handler.read_body()
            if not data or 'claude_response' not in data or 'filename' not in data:
                handler.send_json(400, {'success': False, 'error': 'Missing required fields'})
                return True
                
            result = cad_gen.generate(
                response=data['claude_response'],
                filename=data['filename'],
                fmt=data.get('format'),
                user_id=data.get('user_id'),
                conv_id=data.get('conv_id')
            )
            
            status = 201 if result['success'] else 400
            handler.send_json(status, result)
        except Exception as e:
            logger.error(f"Error in CAD generate post: {e}")
            handler.send_json(500, {'success': False, 'error': str(e)})
        return True
        
    return False

def integrate_cad_tool(app=None):
    """
    MAIN INTEGRATION FUNCTION
    Call this from your app to enable CAD tool
    
    Usage in botai/simple_server.py:
    
        from cad_tool_complete import integrate_cad_tool
        integrate_cad_tool()
    """
    # Initialize CAD generator
    cad_gen = get_global_cad_gen()
    
    # If app is Flask (has register_blueprint)
    if app is not None and hasattr(app, 'register_blueprint'):
        try:
            bp = create_cad_blueprint(cad_gen)
            app.register_blueprint(bp)
            
            @app.route('/cad', methods=['GET'])
            def cad_ui():
                from flask import Response
                return Response(CAD_TOOL_HTML, mimetype='text/html')
        except Exception as e:
            logger.error(f"Failed to register with Flask app: {e}")
            
    print("✅ CAD Tool integrated successfully!")
    print("   📍 Access at: http://localhost:3000/cad")
    print("   📍 API at: /api/cad/*")
    
    return cad_gen


# ============================================================================
# TESTING & STANDALONE USE
# ============================================================================

if __name__ == '__main__':
    from flask import Flask, Response
    from flask_cors import CORS
    
    # Create test app
    app = Flask(__name__)
    CORS(app)
    
    # Integrate CAD tool
    integrate_cad_tool(app)
    
    print("=" * 60)
    print("🎨 CAD TOOL TEST SERVER")
    print("=" * 60)
    print("Starting server...")
    print()
    print("📍 Open browser at: http://localhost:3000/cad")
    print("📍 API endpoint: http://localhost:3000/api/cad/formats")
    print()
    print("To integrate into your chatbot:")
    print("  from cad_tool_complete import integrate_cad_tool")
    print("  integrate_cad_tool(app)")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=3000, debug=True)

