"""
Context compactor service - Handles smart message history trimming and summarization via low-cost Haiku model calls
"""
import json
import urllib.request
from typing import List, Dict, Tuple, Optional
from botai.config import settings
from botai.services.key_rotator import key_rotator

class ContextCompactor:
    """Summarizes and trims message threads to optimize token consumption cost-effectively"""

    def __init__(self):
        self.api_url = 'https://api.anthropic.com/v1/messages'
        self.version_header = '2023-06-01'

    def summarize_history(self, messages_list: List[Dict]) -> Optional[str]:
        """Generates a high-density 2-3 sentence summary of older messages using the cheap Haiku model"""
        active_key = key_rotator.get_key()
        if not active_key:
            return None

        try:
            summary_prompt = (
                "You are an assistant that summarizes the provided conversation history into a very brief, "
                "high-density summary (2-3 sentences max) highlighting key contexts, decisions, and facts."
            )
            payload = json.dumps({
                'model': 'claude-haiku-4-5',
                'max_tokens': 300,
                'system': summary_prompt,
                'messages': messages_list + [{'role': 'user', 'content': 'Summarize the context of this conversation so far in 2-3 sentences.'}]
            }).encode('utf-8')

            req = urllib.request.Request(
                self.api_url,
                data=payload,
                headers={
                    'Content-Type': 'application/json',
                    'x-api-key': active_key,
                    'anthropic-version': self.version_header
                }
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_json = json.loads(resp.read().decode('utf-8'))
                if resp_json.get('content') and resp_json['content'][0].get('text'):
                    return resp_json['content'][0]['text']
        except Exception as se:
            print(f"[ContextCompactor] Summarization failed: {se}")
        return None

    def compact_messages(self, messages: List[Dict], threshold: int = 12, keep_count: int = 6) -> Tuple[List[Dict], Optional[str]]:
        """
        Trims and compacts messages if length is beyond the threshold limit.
        Returns a tuple: (compacted_messages, context_summary_str)
        """
        if len(messages) <= threshold:
            return messages, None

        # Truncate oldest messages, retaining the most recent ones
        messages_to_summarize = messages[:-keep_count]
        recent_messages = messages[-keep_count:]
        
        # Ensure the conversation doesn't start with a response from the assistant
        if recent_messages and recent_messages[0].get('role') == 'assistant':
            recent_messages = recent_messages[1:]

        summary = self.summarize_history(messages_to_summarize)
        return recent_messages, summary

# Initialize global instance
context_compactor = ContextCompactor()
