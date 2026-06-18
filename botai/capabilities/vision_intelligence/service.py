"""
Vision Intelligence Engine
Extends the existing /api/claude/vision endpoint with structured analysis,
OCR extraction, and diagram interpretation capabilities.
"""
import json
import urllib.request
from typing import Dict
from botai.services.key_rotator import key_rotator


def _call_claude_vision(image_b64: str, media_type: str, prompt: str) -> str:
    """Shared helper to call Claude Vision API with a custom prompt."""
    active_key = key_rotator.get_key()
    if not active_key:
        return '[Error: No API key available]'
    payload = json.dumps({
        'model': 'claude-haiku-4-5',
        'max_tokens': 1024,
        'messages': [{
            'role': 'user',
            'content': [
                {'type': 'image', 'source': {'type': 'base64', 'media_type': media_type, 'data': image_b64}},
                {'type': 'text', 'text': prompt}
            ]
        }]
    }).encode('utf-8')
    req = urllib.request.Request(
        'https://api.anthropic.com/v1/messages',
        data=payload,
        headers={'Content-Type': 'application/json', 'x-api-key': active_key, 'anthropic-version': '2023-06-01'}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
        return data.get('content', [{}])[0].get('text', '')


class VisionEngine:
    """Structured image analysis using Claude Vision API."""

    def analyze(self, image_b64: str, media_type: str = 'image/jpeg') -> Dict:
        """Return structured analysis: description, objects, colors, type."""
        if not image_b64:
            return {'error': 'No image provided'}
        try:
            prompt = (
                "Analyze this image and return a JSON object with these exact fields:\n"
                "{\n"
                '  "description": "one paragraph description",\n'
                '  "objects": ["list", "of", "objects"],\n'
                '  "colors": ["dominant", "colors"],\n'
                '  "image_type": "photograph|diagram|chart|screenshot|drawing|other",\n'
                '  "has_text": true/false,\n'
                '  "content_summary": "brief summary"\n'
                "}\n"
                "Return ONLY the JSON object, no other text."
            )
            raw = _call_claude_vision(image_b64, media_type, prompt)
            # Parse JSON response
            import re
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {'description': raw, 'raw': True}
        except Exception as e:
            print(f"[VisionEngine] analyze error: {e}")
            return {'error': str(e)}


class OCREngine:
    """Extract text from images using Claude Vision."""

    def extract_text(self, image_b64: str, media_type: str = 'image/jpeg') -> Dict:
        """Extract all readable text from an image."""
        if not image_b64:
            return {'error': 'No image provided'}
        try:
            prompt = (
                "Extract ALL text visible in this image. "
                "Preserve formatting, line breaks, and structure as much as possible. "
                "If there is a table, format it as a markdown table. "
                "Return ONLY the extracted text, nothing else."
            )
            text = _call_claude_vision(image_b64, media_type, prompt)
            return {
                'text':       text,
                'char_count': len(text),
                'has_content': bool(text.strip())
            }
        except Exception as e:
            print(f"[OCREngine] error: {e}")
            return {'error': str(e)}


class ImageAnalyzer:
    """High-level image analyzer combining Vision and OCR."""

    def __init__(self):
        self.vision = VisionEngine()
        self.ocr    = OCREngine()

    def full_analysis(self, image_b64: str, media_type: str = 'image/jpeg') -> Dict:
        """Run both structural analysis and OCR on an image."""
        vision_result = self.vision.analyze(image_b64, media_type)
        ocr_result    = self.ocr.extract_text(image_b64, media_type)
        return {
            'visual_analysis': vision_result,
            'extracted_text':  ocr_result.get('text', ''),
            'media_type':      media_type
        }


class DiagramInterpreter:
    """Interprets diagrams, flowcharts, and architecture images."""

    def interpret(self, image_b64: str, media_type: str = 'image/jpeg') -> Dict:
        """Interpret a diagram and return structured description."""
        try:
            prompt = (
                "This image appears to be a diagram, flowchart, or architecture drawing. "
                "Please:\n"
                "1. Identify the type of diagram\n"
                "2. Describe the main components/nodes\n"
                "3. Describe the relationships/flows between components\n"
                "4. Summarize the overall purpose of the diagram\n"
                "Structure your response clearly with headers."
            )
            interpretation = _call_claude_vision(image_b64, media_type, prompt)
            return {
                'interpretation': interpretation,
                'media_type':     media_type
            }
        except Exception as e:
            print(f"[DiagramInterpreter] error: {e}")
            return {'error': str(e)}


# Global singletons
vision_engine        = VisionEngine()
ocr_engine           = OCREngine()
image_analyzer       = ImageAnalyzer()
diagram_interpreter  = DiagramInterpreter()
