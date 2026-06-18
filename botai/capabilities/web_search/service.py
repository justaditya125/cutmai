"""
Web Search Engine — SearchManager, WebScraper, SourceValidator, CitationGenerator
Wraps the existing file_handler URL scraper with enhanced capabilities.
"""
import re
import urllib.request
import urllib.error
from datetime import datetime
from typing import Dict, List, Optional
from bs4 import BeautifulSoup


class WebScraper:
    """Enhanced URL scraper that wraps the existing FileHandler.fetch_url_text."""

    TIMEOUT = 15
    MAX_CONTENT_CHARS = 20000

    def scrape(self, url: str) -> Dict:
        """Scrape a URL and return structured content with metadata."""
        try:
            # Reuse existing scraper from file_handler
            from botai.services.file_handler import FileHandler
            text = FileHandler.fetch_url_text(url)

            # Also try to extract title separately
            title = self._extract_title(url)

            return {
                'url':        url,
                'title':      title,
                'content':    text[:self.MAX_CONTENT_CHARS],
                'char_count': len(text),
                'scraped_at': datetime.now().isoformat(),
                'success':    bool(text and '[Error' not in text[:50])
            }
        except Exception as e:
            return {'url': url, 'error': str(e), 'success': False}

    def _extract_title(self, url: str) -> str:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'CUTMAI-Bot/1.0'})
            with urllib.request.urlopen(req, timeout=self.TIMEOUT) as resp:
                raw = resp.read(8192)
                soup = BeautifulSoup(raw, 'html.parser')
                title_tag = soup.find('title')
                return title_tag.get_text().strip() if title_tag else url
        except Exception:
            return url


class SourceValidator:
    """Validates and scores source URLs for trustworthiness."""

    TRUSTED_DOMAINS = {
        '.edu', '.gov', '.ac.in', '.ac.uk', 'wikipedia.org',
        'scholar.google.com', 'pubmed.ncbi.nlm.nih.gov', 'arxiv.org'
    }
    BLOCKED_DOMAINS = {'spam-domain.com'}  # extend as needed

    def validate(self, url: str) -> Dict:
        """Return trust score and flags for a URL."""
        score = 50  # baseline
        flags = []

        if any(d in url for d in self.TRUSTED_DOMAINS):
            score += 30
            flags.append('trusted_domain')

        if any(d in url for d in self.BLOCKED_DOMAINS):
            score = 0
            flags.append('blocked_domain')

        if url.startswith('https://'):
            score += 10
            flags.append('https')

        return {
            'url':         url,
            'trust_score': min(100, score),
            'flags':       flags,
            'is_trusted':  score >= 60
        }


class CitationGenerator:
    """Generates citation blocks for scraped web content."""

    def generate(self, url: str, title: str = None, accessed_at: str = None) -> Dict:
        """Generate a formatted citation for a URL."""
        if not accessed_at:
            accessed_at = datetime.now().strftime('%Y-%m-%d')
        if not title:
            title = url

        citation = f'[Source: "{title}" — {url} (Accessed: {accessed_at})]'
        return {
            'url':         url,
            'title':       title,
            'accessed_at': accessed_at,
            'citation':    citation,
            'apa_style':   f'{title}. Retrieved {accessed_at}, from {url}'
        }

    def generate_multi(self, sources: List[Dict]) -> List[Dict]:
        """Generate citations for multiple sources."""
        return [self.generate(s.get('url', ''), s.get('title'), s.get('accessed_at')) for s in sources]


class SearchManager:
    """Orchestrates web search — scrape, validate, and generate citations."""

    def __init__(self):
        self.scraper   = WebScraper()
        self.validator = SourceValidator()
        self.citer     = CitationGenerator()

    def search(self, url: str, query: str = '') -> Dict:
        """
        Scrape a URL, validate it, and return content + citation.
        For multi-URL batch, use search_many().
        """
        validation = self.validator.validate(url)
        if not validation['is_trusted'] and validation['trust_score'] < 20:
            return {'error': f'URL blocked by source validator: {url}', 'url': url}

        scraped   = self.scraper.scrape(url)
        citation  = self.citer.generate(url, scraped.get('title'))

        return {
            **scraped,
            'validation': validation,
            'citation':   citation,
            'query':      query
        }

    def search_many(self, urls: List[str]) -> List[Dict]:
        return [self.search(url) for url in urls]


# Global singletons
search_manager     = SearchManager()
citation_generator = CitationGenerator()
web_scraper        = WebScraper()
source_validator   = SourceValidator()
