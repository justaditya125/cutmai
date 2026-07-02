"""
Anthropic Claude API service - Handles chat, vision, and streaming requests via urllib
"""
import json
import urllib.request
import urllib.error
from typing import List, Dict, Iterator, Optional
from botai.config import settings
from botai.services.key_rotator import key_rotator

class AnthropicService:
    """Service to interact with the Anthropic messages API"""

    def __init__(self):
        self.api_url = 'https://api.anthropic.com/v1/messages'
        self.version_header = '2023-06-01'

    def _make_request(self, payload_dict: dict, active_key: str) -> urllib.request.Request:
        """Helper to create urllib Request object with required headers"""
        payload_bytes = json.dumps(payload_dict).encode('utf-8')
        return urllib.request.Request(
            self.api_url,
            data=payload_bytes,
            headers={
                'Content-Type': 'application/json',
                'x-api-key': active_key,
                'anthropic-version': self.version_header
            }
        )

    def stream_message(self, messages: List[Dict], system_instructions: str = '',
                       model: Optional[str] = None, max_tokens: Optional[int] = None,
                       thinking_enabled: bool = False) -> Iterator[Dict]:
        """
        Stream Claude's response.
        Yields dictionaries representing delta events:
          - {'type': 'thinking', 'text': ...}
          - {'type': 'delta', 'text': ...}
          - {'type': 'usage', 'input_tokens': ..., 'output_tokens': ...}
          - {'type': 'error', 'text': ...}
        """
        model = model or settings.DEFAULT_MODEL
        max_tokens = max_tokens or settings.DEFAULT_MAX_TOKENS

        payload_dict = {
            'model': model,
            'max_tokens': min(max_tokens, settings.MODEL_REGISTRY.get(model, {}).get('max_tokens', 4000)),
            'messages': messages,
            'stream': True
        }
        if system_instructions:
            payload_dict['system'] = system_instructions
        if thinking_enabled:
            payload_dict['thinking'] = {
                'type': 'enabled',
                'budget_tokens': 1024
            }

        # Try keys up to the number of loaded keys in rotation
        attempts = 0
        max_attempts = max(1, len(key_rotator.keys))
        last_error = None

        while attempts < max_attempts:
            active_key = key_rotator.get_key()
            if not active_key:
                yield {'type': 'error', 'text': 'No API keys configured'}
                return

            try:
                req = self._make_request(payload_dict, active_key)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    for raw_line in resp:
                        line = raw_line.decode('utf-8').strip()
                        if not line or not line.startswith('data:'):
                            continue
                        
                        payload_str = line[5:].strip()
                        if payload_str == '[DONE]':
                            break
                            
                        try:
                            chunk = json.loads(payload_str)
                            event_type = chunk.get('type', '')
                            
                            if event_type == 'content_block_delta':
                                delta = chunk.get('delta', {})
                                delta_type = delta.get('type', '')
                                
                                if delta_type == 'thinking_delta':
                                    delta_thinking = delta.get('thinking', '')
                                    if delta_thinking:
                                        yield {'type': 'thinking', 'text': delta_thinking}
                                else:
                                    delta_text = delta.get('text', '')
                                    if delta_text:
                                        yield {'type': 'delta', 'text': delta_text}
                                        
                            elif event_type == 'message_delta':
                                usage = chunk.get('usage', {})
                                yield {'type': 'usage', 'output_tokens': usage.get('output_tokens', 0)}
                                
                            elif event_type == 'message_start':
                                usage = chunk.get('message', {}).get('usage', {})
                                yield {'type': 'usage', 'input_tokens': usage.get('input_tokens', 0)}
                        except Exception:
                            continue
                # Success, break the retry loop
                return

            except urllib.error.HTTPError as e:
                last_error = str(e)
                # 429: Rate Limit, 401: Unauthorized, 403: Forbidden - mark key as unhealthy
                if e.code in [401, 403, 429]:
                    key_rotator.mark_unhealthy(active_key)
                print(f"[AnthropicService] Key failed during stream (HTTP {e.code}). Retrying with next key...")
                attempts += 1
            except Exception as e:
                last_error = str(e)
                print(f"[AnthropicService] Unexpected key error during stream: {e}. Retrying...")
                attempts += 1

        # If all attempts failed
        yield {'type': 'error', 'text': 'All API keys failed. Please try again later.'}

    def get_message(self, messages: List[Dict], system_instructions: str = '',
                    model: Optional[str] = None, max_tokens: Optional[int] = None) -> Dict:
        """
        Sends non-streaming message to Claude.
        Returns a dict containing response text and usage.
        """
        model = model or settings.DEFAULT_MODEL
        max_tokens = max_tokens or settings.DEFAULT_MAX_TOKENS

        payload_dict = {
            'model': model,
            'max_tokens': min(max_tokens, settings.MODEL_REGISTRY.get(model, {}).get('max_tokens', 4000)),
            'messages': messages
        }
        if system_instructions:
            payload_dict['system'] = system_instructions

        attempts = 0
        max_attempts = max(1, len(key_rotator.keys))
        last_exception = None

        while attempts < max_attempts:
            active_key = key_rotator.get_key()
            if not active_key:
                raise RuntimeError("No API keys configured")

            try:
                req = self._make_request(payload_dict, active_key)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    response_json = json.loads(resp.read().decode('utf-8'))
                    return {
                        'text': response_json['content'][0]['text'],
                        'input_tokens': response_json.get('usage', {}).get('input_tokens', 0),
                        'output_tokens': response_json.get('usage', {}).get('output_tokens', 0),
                        'model': response_json.get('model', model)
                    }
            except urllib.error.HTTPError as e:
                last_exception = e
                if e.code in [401, 403, 429]:
                    key_rotator.mark_unhealthy(active_key)
                print(f"[AnthropicService] Key failed during non-stream (HTTP {e.code}). Retrying...")
                attempts += 1
            except Exception as e:
                last_exception = e
                print(f"[AnthropicService] Key error during non-stream: {e}. Retrying...")
                attempts += 1

        raise last_exception or RuntimeError("All Anthropic API requests failed.")

    def analyze_image(self, image_b64: str, media_type: str, prompt: str,
                      model: Optional[str] = None) -> Dict:
        """
        Claude Vision API integration.
        Sends Base64 image + instruction prompt.
        """
        model = model or settings.DEFAULT_MODEL
        payload_dict = {
            'model': model,
            'max_tokens': 2048,
            'messages': [{
                'role': 'user',
                'content': [
                    {
                        'type': 'image',
                        'source': {
                            'type': 'base64',
                            'media_type': media_type,
                            'data': image_b64
                        }
                    },
                    {
                        'type': 'text',
                        'text': prompt
                    }
                ]
            }]
        }

        attempts = 0
        max_attempts = max(1, len(key_rotator.keys))
        last_exception = None

        while attempts < max_attempts:
            active_key = key_rotator.get_key()
            if not active_key:
                raise RuntimeError("No API keys configured")

            try:
                req = self._make_request(payload_dict, active_key)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    response_json = json.loads(resp.read().decode('utf-8'))
                    return response_json
            except urllib.error.HTTPError as e:
                last_exception = e
                if e.code in [401, 403, 429]:
                    key_rotator.mark_unhealthy(active_key)
                print(f"[AnthropicService] Key failed during vision request (HTTP {e.code}). Retrying...")
                attempts += 1
            except Exception as e:
                last_exception = e
                print(f"[AnthropicService] Key error during vision: {e}. Retrying...")
                attempts += 1

        raise last_exception or RuntimeError("All vision API requests failed.")

# Initialize global instance
anthropic_service = AnthropicService()
