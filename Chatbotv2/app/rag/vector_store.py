import logging
import os
import shutil
import time

import chromadb
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)

CHROMA_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "chroma_db")

# Use ChromaDB's default ONNX-based embedding (no torch needed, ~50MB vs ~500MB)
# ONNXMiniLM is fast, lightweight, and multilingual-capable
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

_client = None
_collection = None
_embedding_fn = None

def get_vector_store(retry=True):
    global _client, _collection, _embedding_fn
    
    if _embedding_fn is None:
        logger.info("Initializing ONNX embedding model (lightweight)...")
        _embedding_fn = embedding_functions.ONNXMiniLM_L6_V2()
    
    if _collection is None:
        try:
            if _client is None:
                logger.debug("Connecting to ChromaDB at %s...", CHROMA_DATA_PATH)
                _client = chromadb.PersistentClient(path=CHROMA_DATA_PATH)
            _collection = _client.get_or_create_collection(name="dietitian_rag", embedding_function=_embedding_fn)
        except Exception as e:
            err_msg = str(e)
            logger.error("CHROMA_ERROR: %s", err_msg)
            
            should_wipe = any(x in err_msg for x in [
                "embeddings already exists", 
                "sqlite3.OperationalError", 
                "default_tenant", 
                "Could not connect",
                "dimensionality",
            ])
            
            if retry and should_wipe:
                logger.warning("CRASH DETECTED: %s. Deep-cleaning %s...", err_msg, CHROMA_DATA_PATH)
                try:
                    _client = None 
                    _collection = None
                    if os.path.exists(CHROMA_DATA_PATH):
                        shutil.rmtree(CHROMA_DATA_PATH)
                        logger.info("Folder deleted successfully.")
                    time.sleep(1)
                    os.makedirs(CHROMA_DATA_PATH, exist_ok=True)
                    return get_vector_store(retry=False)
                except Exception as wipe_err:
                    logger.error("Deep-clean failed: %s", wipe_err)
            raise
    return _collection

def add_documents(chunks: list[dict]):
    if not chunks: return
    collection = get_vector_store()
    ids = [c["id"] for c in chunks]
    texts = [c["text"] for c in chunks]
    metadatas = [c["metadata"] for c in chunks]
    
    batch_size = 500
    for i in range(0, len(chunks), batch_size):
        end = min(i + batch_size, len(chunks))
        collection.add(ids=ids[i:end], documents=texts[i:end], metadatas=metadatas[i:end])
    logger.info("Added %d documents to vector store", len(chunks))

def query_documents(query_text: str, n_results: int = 5):
    collection = get_vector_store()
    results = collection.query(query_texts=[query_text], n_results=n_results)
    return results

def get_collection_stats():
    try:
        collection = get_vector_store()
        return {"count": collection.count()}
    except Exception:
        return {"count": 0, "error": "Database not initialized"}
