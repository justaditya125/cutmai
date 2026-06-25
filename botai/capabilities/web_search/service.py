"""
Web Search Engine — SearchManager, WebScraper, SourceValidator, CitationGenerator
Wraps the existing file_handler URL scraper with enhanced capabilities.
"""
import re
import socket
import urllib.request
import urllib.error
from urllib.parse import urlparse
from datetime import datetime
from typing import Dict, List, Optional
from bs4 import BeautifulSoup


def _is_private_ip(hostname: str) -> bool:
    """Check if hostname resolves to a private/reserved IP address (SSRF protection)."""
    if not hostname:
        return True
    try:
        ips = socket.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in ips:
            ip = sockaddr[0]
            if family == socket.AF_INET:
                parts = ip.split('.')
                if parts[0] == '10':
                    return True
                if parts[0] == '172' and 16 <= int(parts[1]) <= 31:
                    return True
                if parts[0] == '192' and parts[1] == '168':
                    return True
                if parts[0] == '127':
                    return True
                if parts[0] == '0':
                    return True
                if parts[0] == '169' and parts[1] == '254':
                    return True
            elif family == socket.AF_INET6:
                if ip in ('::1',) or ip.startswith('fc') or ip.startswith('fd'):
                    return True
        return False
    except (socket.gaierror, ValueError, IndexError):
        return True


def validate_url_safety(url: str) -> Dict:
    """Validate a URL is safe to fetch (not SSRF). Returns {safe, error}."""
    try:
        parsed = urlparse(url)
    except Exception:
        return {'safe': False, 'error': 'Invalid URL format'}

    if parsed.scheme not in ('http', 'https'):
        return {'safe': False, 'error': f'Only HTTP/HTTPS URLs allowed, got: {parsed.scheme}'}

    hostname = parsed.hostname
    if not hostname:
        return {'safe': False, 'error': 'No hostname in URL'}

    if _is_private_ip(hostname):
        return {'safe': False, 'error': f'URL points to private/reserved IP: {hostname}'}

    blocked_hosts = {'localhost', '127.0.0.1', '0.0.0.0', '::1', '169.254.169.254'}
    if hostname.lower() in blocked_hosts:
        return {'safe': False, 'error': f'URL points to blocked host: {hostname}'}

    return {'safe': True, 'error': None}


class WebScraper:
    """Enhanced URL scraper that wraps the existing FileHandler.fetch_url_text."""

    TIMEOUT = 15
    MAX_CONTENT_CHARS = 20000

    def scrape(self, url: str) -> Dict:
        """Scrape a URL and return structured content with metadata."""
        safety = validate_url_safety(url)
        if not safety['safe']:
            return {'url': url, 'error': safety['error'], 'success': False}

        try:
            from botai.services.file_handler import FileHandler
            text = FileHandler.fetch_url_text(url)
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
            safety = validate_url_safety(url)
            if not safety['safe']:
                return url
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
    BLOCKED_DOMAINS = {'spam-domain.com'}

    def validate(self, url: str) -> Dict:
        """Return trust score and flags for a URL."""
        score = 50
        flags = []

        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower() + parsed.path.lower()
        except Exception:
            netloc = url.lower()

        if any(d in netloc for d in self.TRUSTED_DOMAINS):
            score += 30
            flags.append('trusted_domain')

        if any(d in netloc for d in self.BLOCKED_DOMAINS):
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

    def search_many(self, urls: List[str], max_urls: int = 10) -> List[Dict]:
        return [self.search(url) for url in urls[:max_urls]]


# Global singletons
search_manager     = SearchManager()
citation_generator = CitationGenerator()
web_scraper        = WebScraper()
source_validator   = SourceValidator()
