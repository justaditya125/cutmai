/**
 * FILE HANDLER - Client-side file upload logic
 */

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(String(str)));
    return div.innerHTML;
}

class FileManager {
    constructor() {
        this.files = [];
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.loadFiles();
    }

    setupEventListeners() {
        // Upload button
        document.getElementById('upload-btn').addEventListener('click', () => {
            document.getElementById('upload-modal').classList.remove('hidden');
        });

        // Drop zone
        const dropZone = document.getElementById('drop-zone');
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.style.background = '#e0f2f7';
        });

        dropZone.addEventListener('dragleave', () => {
            dropZone.style.background = '#f9f9f9';
        });

        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.style.background = '#f9f9f9';
            this.handleFiles(e.dataTransfer.files);
        });

        // File input
        document.getElementById('file-input').addEventListener('change', (e) => {
            this.handleFiles(e.target.files);
        });
    }

    handleFiles(files) {
        for (let file of files) {
            this.uploadFile(file);
        }
    }

    uploadFile(file) {
        const reader = new FileReader();

        reader.onload = (e) => {
            const fileData = e.target.result;
            const bytes = new Uint8Array(fileData);
            let base64 = '';
            const CHUNK_SIZE = 8192;
            for (let i = 0; i < bytes.length; i += CHUNK_SIZE) {
                base64 += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK_SIZE));
            }
            base64 = btoa(base64);
            const token = typeof SESSION === 'function' ? SESSION() : '';

            fetch('/api/files/upload', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    filename: file.name,
                    file_data_b64: base64,
                    session_token: token
                })
            })
            .then(res => res.json())
            .then(data => {
                if (data.file_id) {
                    console.log('✓ File uploaded:', data.filename);
                    this.loadFiles();
                } else {
                    console.error('Error:', data.error);
                }
            })
            .catch(err => console.error('Upload error:', err));
        };

        reader.readAsArrayBuffer(file);
    }

    loadFiles() {
        const token = typeof SESSION === 'function' ? SESSION() : '';
        fetch(`/api/files/list?session_token=${encodeURIComponent(token)}`)
            .then(res => res.json())
            .then(data => {
                this.renderFiles(data.files || []);
            })
            .catch(err => console.error('Error loading files:', err));
    }

    renderFiles(files) {
        const filesList = document.getElementById('files-list');
        const mainList = document.getElementById('main-files-list');

        filesList.innerHTML = '';
        mainList.innerHTML = '';

        if (files.length === 0) {
            filesList.innerHTML = '<p>No files uploaded</p>';
            mainList.innerHTML = '<p>No files uploaded</p>';
            return;
        }

        files.forEach(file => {
            const safeId = escapeHtml(file.file_id);
            const safeName = escapeHtml(file.filename);
            const safeType = escapeHtml(file.file_type);
            const html = `
                <div class="file-item" data-file-id="${safeId}">
                    <div class="file-info">
                        <div class="file-name">📄 ${safeName}</div>
                        <div class="file-meta">
                            ${safeType} • ${file.size_mb} MB • ${new Date(file.created_at).toLocaleDateString()}
                        </div>
                    </div>
                    <div class="file-actions">
                        <button class="btn-small" onclick="fileManager.copyFileRef('${safeId}')">Copy Ref</button>
                        <button class="btn-small btn-delete" onclick="fileManager.deleteFile('${safeId}')">Delete</button>
                    </div>
                </div>
            `;
            filesList.innerHTML += html;
            mainList.innerHTML += html;
        });
    }

    copyFileRef(fileId) {
        const file = document.querySelector(`[data-file-id="${fileId}"]`);
        const filename = file?.querySelector('.file-name')?.textContent || 'file';
        const ref = `@${filename.replace('📄 ', '')}`;
        navigator.clipboard.writeText(ref);
        alert('Copied: ' + ref);
    }

    deleteFile(fileId) {
        if (!confirm('Delete this file?')) return;

        const token = typeof SESSION === 'function' ? SESSION() : '';
        fetch('/api/files/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_id: fileId, session_token: token })
        })
        .then(res => res.json())
        .then(data => {
            console.log('✓ File deleted');
            this.loadFiles();
        })
        .catch(err => console.error('Delete error:', err));
    }
}

function closeModal() {
    document.getElementById('upload-modal').classList.add('hidden');
}

// Initialize
const fileManager = new FileManager();
