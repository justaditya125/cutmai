"""
Data Analysis Engine — DataAnalyzer, StatisticsEngine, VisualizationEngine, InsightGenerator
Analyzes uploaded CSV/XLSX files and generates statistics + Chart.js configs.
"""
import json
import io
from typing import Dict, List, Optional
from bson import ObjectId
from botai.config.mongodb_config import get_db


class StatisticsEngine:
    """Computes basic statistical summaries from tabular data."""

    def summarize(self, headers: List[str], rows: List[List]) -> Dict:
        """Return column-wise statistics for numeric columns."""
        stats = {}
        for col_idx, header in enumerate(headers):
            values = []
            for row in rows:
                if col_idx < len(row):
                    try:
                        values.append(float(row[col_idx]))
                    except (ValueError, TypeError):
                        pass

            if values:
                values.sort()
                n = len(values)
                mean = sum(values) / n
                variance = sum((v - mean) ** 2 for v in values) / n
                stats[header] = {
                    'count': n,
                    'min':   round(min(values), 4),
                    'max':   round(max(values), 4),
                    'mean':  round(mean, 4),
                    'std':   round(variance ** 0.5, 4),
                    'sum':   round(sum(values), 4),
                    'median': round(values[n // 2], 4)
                }
            else:
                # Categorical column
                unique_vals = list(set(str(row[col_idx]) for row in rows if col_idx < len(row)))
                stats[header] = {
                    'type':        'categorical',
                    'unique_count': len(unique_vals),
                    'sample':      unique_vals[:5]
                }
        return stats


class VisualizationEngine:
    """Generates Chart.js-compatible JSON configs from tabular data."""

    def suggest_chart(self, headers: List[str], rows: List[List],
                      label_col: int = 0, value_col: int = 1) -> Dict:
        """Auto-generate a bar chart config from tabular data."""
        labels = [str(row[label_col]) for row in rows[:20] if len(row) > label_col]
        values = []
        for row in rows[:20]:
            if len(row) > value_col:
                try:
                    values.append(float(row[value_col]))
                except (ValueError, TypeError):
                    values.append(0)

        return {
            'type':   'bar',
            'title':  f'{headers[value_col]} by {headers[label_col]}' if len(headers) > value_col else 'Data Chart',
            'labels': labels,
            'datasets': [{
                'label': headers[value_col] if len(headers) > value_col else 'Values',
                'data':  values
            }]
        }


class InsightGenerator:
    """Uses Claude API to generate natural-language insights from statistics."""

    def generate(self, stats: Dict, query: str = '') -> str:
        """Ask Claude to interpret the statistics and generate insights."""
        try:
            from botai.services.key_rotator import key_rotator
            import urllib.request
            key = key_rotator.get_key()
            if not key:
                return 'No API key available for insight generation.'

            stats_text = json.dumps(stats, indent=2)
            prompt = (
                f"Here are statistical summaries from a dataset:\n\n{stats_text}\n\n"
                f"{'User query: ' + query if query else ''}\n\n"
                "Provide 3-5 clear, actionable insights from this data in bullet points. "
                "Highlight any notable patterns, outliers, or correlations."
            )
            payload = json.dumps({
                'model': 'claude-haiku-4-5',
                'max_tokens': 500,
                'messages': [{'role': 'user', 'content': prompt}]
            }).encode('utf-8')

            req = urllib.request.Request(
                'https://api.anthropic.com/v1/messages',
                data=payload,
                headers={'Content-Type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01'}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                return data.get('content', [{}])[0].get('text', '')
        except Exception as e:
            print(f"[InsightGenerator] error: {e}")
            return f'Could not generate insights: {e}'


class DataAnalyzer:
    """Main entry point — loads a file from MongoDB and runs full analysis."""

    def __init__(self):
        self.stats_engine = StatisticsEngine()
        self.viz_engine   = VisualizationEngine()
        self.insight_gen  = InsightGenerator()

    def analyze(self, file_id: str, user_id: str, query: str = '') -> Dict:
        """Load a file, parse it as tabular data, return stats + chart + insights."""
        try:
            # Try to load from disk using file metadata in MongoDB
            db = get_db()
            if db is None:
                return {'error': 'Database unavailable'}

            file_doc = db.files.find_one({
                '_id':     ObjectId(file_id),
                'user_id': ObjectId(user_id) if isinstance(user_id, str) else user_id
            })
            if not file_doc:
                return {'error': 'File not found or access denied'}

            file_path = file_doc.get('path')
            filename  = file_doc.get('filename', '')
            ext       = filename.lower().split('.')[-1]

            headers, rows = [], []
            with open(file_path, 'rb') as f:
                file_bytes = f.read()

            if ext == 'csv':
                headers, rows = self._parse_csv(file_bytes)
            elif ext in ('xlsx', 'xls'):
                headers, rows = self._parse_excel(file_bytes, ext)
            else:
                return {'error': f'Unsupported file type for data analysis: .{ext}'}

            stats   = self.stats_engine.summarize(headers, rows)
            chart   = self.viz_engine.suggest_chart(headers, rows)
            insight = self.insight_gen.generate(stats, query)

            return {
                'filename':    filename,
                'row_count':   len(rows),
                'col_count':   len(headers),
                'headers':     headers,
                'statistics':  stats,
                'chart_config': chart,
                'insights':    insight
            }
        except Exception as e:
            print(f"[DataAnalyzer] error: {e}")
            return {'error': str(e)}

    def _parse_csv(self, file_bytes: bytes):
        import csv
        reader = csv.reader(io.StringIO(file_bytes.decode('utf-8', errors='replace')))
        rows = list(reader)
        return (rows[0] if rows else []), (rows[1:] if len(rows) > 1 else [])

    def _parse_excel(self, file_bytes: bytes, ext: str):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ws = wb.active
        all_rows = [[str(cell.value or '') for cell in row] for row in ws.iter_rows()]
        return (all_rows[0] if all_rows else []), (all_rows[1:] if len(all_rows) > 1 else [])


data_analyzer = DataAnalyzer()
