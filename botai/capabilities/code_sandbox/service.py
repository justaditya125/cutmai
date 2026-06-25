"""
Code Execution Sandbox (DISABLED by default — requires Docker)
Provides safe code execution in isolated Docker containers.
Set ENABLE_CODE_SANDBOX=True in .env and ensure Docker is installed to activate.
"""
from typing import Dict


class SandboxManager:
    """Manages sandboxed code execution. Requires Docker."""

    SUPPORTED_LANGUAGES = ['python', 'javascript', 'bash']

    def execute(self, code: str, language: str, timeout_secs: int = None) -> Dict:
        """
        Execute code in an isolated Docker container.
        Returns: {stdout, stderr, exit_code, execution_ms, success}
        """
        from botai.config import settings
        timeout = timeout_secs or settings.SANDBOX_TIMEOUT_SECS
        timeout = min(timeout, 30)  # Enforce 30-second max timeout

        if language not in self.SUPPORTED_LANGUAGES:
            return {'error': f'Unsupported language: {language}. Supported: {self.SUPPORTED_LANGUAGES}'}

        if not self._is_docker_available():
            return {'error': 'Docker is not available on this server. ENABLE_CODE_SANDBOX=False.'}

        # Validate code safety first
        from botai.capabilities.code_sandbox.validator import SecurityValidator
        validator = SecurityValidator()
        check = validator.validate(code, language)
        if not check['is_safe']:
            return {'error': f'Code rejected by security validator: {check["reason"]}'}

        try:
            return self._run_in_container(code, language, timeout, settings.SANDBOX_MEMORY_MB)
        except Exception as e:
            print(f"[SandboxManager] execution error: {e}")
            return {'error': str(e), 'success': False}

    def _is_docker_available(self) -> bool:
        import subprocess
        try:
            subprocess.run(['docker', 'info'], capture_output=True, timeout=5)
            return True
        except Exception:
            return False

    def _run_in_container(self, code: str, language: str, timeout: int, memory_mb: int) -> Dict:
        import subprocess, time, tempfile, os

        # Map language to Docker image
        images = {
            'python':     'python:3.11-slim',
            'javascript': 'node:18-slim',
            'bash':       'bash:5'
        }
        image = images.get(language, 'python:3.11-slim')

        # File extensions
        exts = {'python': 'py', 'javascript': 'js', 'bash': 'sh'}
        ext = exts.get(language, 'py')

        # Write code to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix=f'.{ext}', delete=False) as f:
            f.write(code)
            tmp_path = f.name

        try:
            cmd_map = {
                'python':     ['python', f'/code/{os.path.basename(tmp_path)}'],
                'javascript': ['node', f'/code/{os.path.basename(tmp_path)}'],
                'bash':       ['bash', f'/code/{os.path.basename(tmp_path)}']
            }
            cmd = [
                'docker', 'run', '--rm',
                '--memory', f'{memory_mb}m',
                '--network', 'none',
                '--cpus', '0.5',
                '-v', f'{os.path.dirname(tmp_path)}:/code:ro',
                image
            ] + cmd_map[language]

            start = time.monotonic()
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            elapsed_ms = (time.monotonic() - start) * 1000

            return {
                'stdout':       proc.stdout[:10000],
                'stderr':       proc.stderr[:2000],
                'exit_code':    proc.returncode,
                'execution_ms': round(elapsed_ms, 2),
                'success':      proc.returncode == 0,
                'language':     language
            }
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


class SecurityValidator:
    """Validates code for dangerous patterns before sandbox execution."""

    BLOCKED_KEYWORDS = {
        'python': [
            'os.system', 'os.popen', 'subprocess', '__import__',
            '__builtins__', '__subclasses__', 'shutil.rmtree',
        ],
        'javascript': [
            'require', 'process', 'fs.', 'child_process',
            'eval(', 'Function('
        ],
        'bash': [
            'rm -rf', 'curl', 'wget', 'ssh', 'sudo', 'chmod',
            'mkfs', 'dd if=', '> /dev'
        ]
    }

    # Python keywords that must be whole-word matched (not substrings)
    _PYTHON_WORD_KEYWORDS = {'import', 'exec', 'eval', 'compile', 'open', 'socket', 'urllib', 'requests'}

    def validate(self, code: str, language: str) -> Dict:
        import re as _re
        code_lower = code.lower()
        keywords = self.BLOCKED_KEYWORDS.get(language, [])
        for keyword in keywords:
            if keyword.lower() in code_lower:
                return {'is_safe': False, 'reason': f'Blocked pattern: {keyword}'}
        if language == 'python':
            for kw in self._PYTHON_WORD_KEYWORDS:
                if _re.search(r'\b' + _re.escape(kw) + r'\b', code_lower):
                    return {'is_safe': False, 'reason': f'Blocked pattern: {kw}'}
        return {'is_safe': True, 'reason': None}


class ResourceLimiter:
    """Enforces resource limits for sandbox containers."""

    def get_limits(self, user_tier: str = 'standard') -> Dict:
        limits = {
            'standard': {'memory_mb': 64,  'timeout_secs': 10, 'max_output_kb': 100},
            'premium':  {'memory_mb': 128, 'timeout_secs': 20, 'max_output_kb': 500}
        }
        return limits.get(user_tier, limits['standard'])


sandbox_manager   = SandboxManager()
resource_limiter  = ResourceLimiter()
