"""
Cost Estimator & Token Counter
Calculates exact API costs per request using the model registry pricing.
"""
from typing import Dict, Optional
from botai.config import settings


class TokenCounter:
    """Counts and tracks tokens for a request."""

    def __init__(self):
        self._model_registry = settings.MODEL_REGISTRY

    def estimate_prompt_tokens(self, text: str) -> int:
        """Rough token estimate: ~4 chars per token (Anthropic average)."""
        return max(1, len(text) // 4)

    def count_messages_tokens(self, messages: list) -> int:
        """Sum estimated tokens across a messages array."""
        total = 0
        for msg in messages:
            content = msg.get('content', '')
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        total += self.estimate_prompt_tokens(block.get('text', ''))
            elif isinstance(content, str):
                total += self.estimate_prompt_tokens(content)
        return total


class CostEstimator:
    """Calculates USD cost for token usage using per-model pricing."""

    def __init__(self):
        self._registry = settings.MODEL_REGISTRY

    def estimate(self, model_id: str, input_tokens: int, output_tokens: int) -> Dict:
        """
        Return a cost breakdown dict for a given model and token counts.
        Falls back to Sonnet pricing if model not in registry.
        """
        config = self._registry.get(model_id, self._registry.get('claude-sonnet-4-5', {}))
        input_cost_per_1m  = config.get('input_cost_per_1m',  3.0)
        output_cost_per_1m = config.get('output_cost_per_1m', 15.0)

        input_cost  = (input_tokens  * input_cost_per_1m)  / 1_000_000
        output_cost = (output_tokens * output_cost_per_1m) / 1_000_000
        total_cost  = input_cost + output_cost

        return {
            'model':         model_id,
            'input_tokens':  input_tokens,
            'output_tokens': output_tokens,
            'total_tokens':  input_tokens + output_tokens,
            'input_cost':    round(input_cost,  6),
            'output_cost':   round(output_cost, 6),
            'total_cost':    round(total_cost,  6),
            'currency':      'USD'
        }

    def estimate_batch(self, records: list) -> Dict:
        """Aggregate cost across a list of {model, input_tokens, output_tokens} records."""
        total_input  = 0
        total_output = 0
        total_cost   = 0.0
        by_model: Dict[str, Dict] = {}

        for r in records:
            model = r.get('model', 'claude-haiku-4-5')
            inp   = r.get('input_tokens', 0)
            out   = r.get('output_tokens', 0)
            est   = self.estimate(model, inp, out)

            total_input  += inp
            total_output += out
            total_cost   += est['total_cost']

            if model not in by_model:
                by_model[model] = {'input_tokens': 0, 'output_tokens': 0, 'total_cost': 0.0}
            by_model[model]['input_tokens']  += inp
            by_model[model]['output_tokens'] += out
            by_model[model]['total_cost']    += est['total_cost']

        return {
            'total_input_tokens':  total_input,
            'total_output_tokens': total_output,
            'total_tokens':        total_input + total_output,
            'total_cost_usd':      round(total_cost, 6),
            'by_model':            by_model
        }


# Global singletons
token_counter  = TokenCounter()
cost_estimator = CostEstimator()
