"""
RAG System — VectorStore, EmbeddingGenerator, Retriever, ReRanker, CitationEngine.
Uses sentence-transformers for local embeddings (no external API cost).
Falls back gracefully if sentence-transformers is not installed.
"""
import json
import math
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from bson import ObjectId
from botai.config import settings
from botai.config.mongodb_config import get_db


# ── Embedding Generator ─────────────────────────────────────────────────────────

class EmbeddingGenerator:
    """Generates text embeddings using sentence-transformers (local, free)."""

    def __init__(self):
        self._model = None
        self._available = False
        self._try_load()

    def _try_load(self):
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(settings.RAG_EMBEDDING_MODEL)
            self._available = True
            print(f"[RAG] Embedding model loaded: {settings.RAG_EMBEDDING_MODEL}")
        except ImportError:
            print("[RAG] sentence-transformers not installed. RAG embeddings disabled. "
                  "Run: pip install sentence-transformers")
        except Exception as e:
            print(f"[RAG] Failed to load embedding model: {e}")

    @property
    def available(self) -> bool:
        return self._available

    def embed(self, text: str) -> Optional[List[float]]:
        """Generate embedding vector for a text string."""
        if not self._available or not self._model:
            return None
        try:
            vector = self._model.encode(text, convert_to_numpy=True)
            return vector.tolist()
        except Exception as e:
            print(f"[EmbeddingGenerator] embed error: {e}")
            return None

    def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Generate embeddings for multiple texts."""
        if not self._available or not self._model:
            return [None] * len(texts)
        try:
            vectors = self._model.encode(texts, convert_to_numpy=True)
            return [v.tolist() for v in vectors]
        except Exception as e:
            print(f"[EmbeddingGenerator] embed_batch error: {e}")
            return [None] * len(texts)


# ── Cosine Similarity ────────────────────────────────────────────────────────────

def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── VectorStore ──────────────────────────────────────────────────────────────────

class VectorStore:
    """Stores and queries embeddings in MongoDB embeddings collection."""

    def __init__(self, embedding_gen: EmbeddingGenerator):
        self._gen = embedding_gen

    def add(self, user_id: str, file_id: str, chunks: List[Dict]) -> int:
        """
        Embed and store document chunks.
        Returns the number of chunks successfully stored.
        """
        if not self._gen.available:
            print("[VectorStore] Embeddings not available — skipping indexing")
            return 0

        db = get_db()
        if db is None:
            return 0

        texts = [c.get('text', '') for c in chunks]
        vectors = self._gen.embed_batch(texts)

        docs = []
        for chunk, vector in zip(chunks, vectors):
            if vector is None:
                continue
            docs.append({
                'user_id':     ObjectId(user_id) if isinstance(user_id, str) else user_id,
                'file_id':     ObjectId(file_id) if isinstance(file_id, str) else file_id,
                'text':        chunk.get('text', ''),
                'chunk_index': chunk.get('chunk_index', 0),
                'vector':      vector,
                'created_at':  datetime.now()
            })

        if docs:
            try:
                db.embeddings.insert_many(docs)
                return len(docs)
            except Exception as e:
                print(f"[VectorStore] add error: {e}")
        return 0

    def search(self, user_id: str, query: str, top_k: int = None) -> List[Dict]:
        """Find top-k most similar chunks to a query."""
        top_k = top_k or settings.RAG_TOP_K
        if not self._gen.available:
            return []

        query_vec = self._gen.embed(query)
        if query_vec is None:
            return []

        db = get_db()
        if db is None:
            return []

        try:
            u_id = ObjectId(user_id) if isinstance(user_id, str) else user_id
            # Load all vectors for user (for small-scale cosine search)
            records = list(db.embeddings.find({'user_id': u_id}, {'_id': 1, 'text': 1, 'vector': 1, 'file_id': 1}))

            scored = []
            for r in records:
                vec = r.get('vector')
                if vec:
                    score = _cosine_similarity(query_vec, vec)
                    scored.append({'text': r['text'], 'file_id': str(r['file_id']), 'score': score})

            scored.sort(key=lambda x: x['score'], reverse=True)
            return scored[:top_k]
        except Exception as e:
            print(f"[VectorStore] search error: {e}")
            return []


# ── RAG Service ──────────────────────────────────────────────────────────────────

class RAGService:
    """Main RAG service — indexing and query pipeline."""

    def __init__(self):
        self.embed_gen   = EmbeddingGenerator()
        self.vector_store = VectorStore(self.embed_gen)

    def index_file(self, file_id: str, user_id: str) -> Dict:
        """Read a file's parsed text from DB, chunk it, and index embeddings."""
        try:
            from botai.capabilities.file_processing.service import file_processor, chunk_manager
            db = get_db()
            if db is None:
                return {'error': 'Database unavailable'}

            file_doc = db.files.find_one({'_id': ObjectId(file_id)})
            if not file_doc:
                return {'error': 'File not found'}

            file_path = file_doc.get('path', '')
            filename  = file_doc.get('filename', '')
            with open(file_path, 'rb') as f:
                file_bytes = f.read()

            processed = file_processor.process(file_bytes, filename)
            text = processed.get('text', '')
            if not text or len(text) < 20:
                return {'error': 'No usable text extracted from file'}

            chunks = chunk_manager.chunk(text)
            count  = self.vector_store.add(user_id, file_id, chunks)

            return {
                'success':       True,
                'file_id':       file_id,
                'chunks_indexed': count,
                'char_count':    len(text)
            }
        except Exception as e:
            print(f"[RAGService] index_file error: {e}")
            return {'error': str(e)}

    def query(self, query: str, user_id: str, conversation_id: str = None) -> Dict:
        """Run a RAG query — retrieve relevant chunks + generate a grounded answer."""
        if not self.embed_gen.available:
            return {'error': 'RAG embeddings not available. Install sentence-transformers.', 'chunks': []}

        chunks = self.vector_store.search(user_id, query)
        if not chunks:
            return {'answer': None, 'chunks': [], 'message': 'No indexed documents found for this user'}

        # Build context from top chunks
        context = '\n\n'.join(
            f"[Chunk {i+1} (score={c['score']:.3f})]:\n{c['text']}"
            for i, c in enumerate(chunks)
        )

        # Generate grounded answer via Claude
        try:
            from botai.services.key_rotator import key_rotator
            import urllib.request
            key = key_rotator.get_key()
            prompt = (
                f"Using ONLY the following context, answer the question.\n\n"
                f"CONTEXT:\n{context}\n\n"
                f"QUESTION: {query}\n\n"
                "If the answer is not in the context, say so clearly."
            )
            payload = json.dumps({
                'model': 'claude-haiku-4-5',
                'max_tokens': 800,
                'messages': [{'role': 'user', 'content': prompt}]
            }).encode('utf-8')
            req = urllib.request.Request(
                'https://api.anthropic.com/v1/messages',
                data=payload,
                headers={'Content-Type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01'}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                answer = data.get('content', [{}])[0].get('text', '')
        except Exception as e:
            answer = f'[Answer generation failed: {e}]'

        return {
            'query':       query,
            'answer':      answer,
            'chunks':      chunks,
            'chunk_count': len(chunks),
            'rag_enabled': True
        }


rag_service = RAGService()
