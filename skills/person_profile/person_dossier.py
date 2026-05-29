from typing import Tuple, Dict, List
from lib.storage import get_storage
from lib.logger import get_logger
from lib.slugify import slugify
from skills.dataset_chat.dataset_search import dataset_search
from skills.dataset_chat.core.models import Chunk

logger = get_logger(__name__)

async def get_filtered_chunks(dataset_name: str, name: str, query: str) -> list:
    """
    Retrieve chunks for a person from a dataset and apply a content filter 
    to ensure the person is actually mentioned.
    """
    logger.info(f"Collating profile chunks for '{name}' in dataset '{dataset_name}'...")
    
    chunks = await dataset_search(
        dataset_name=dataset_name,
        query=query,
        max_chunks=500
    )
    
    if not chunks:
        return []

    # Filter chunks based on name words
    filter_words = [w.lower() for w in name.split() if w.strip()]
    
    content_filtered = []
    for chunk in chunks:
        if all(fw in chunk.text.lower() for fw in filter_words):
            content_filtered.append(chunk)

    return content_filtered

def is_dossier_document(doc_name: str, person_name: str) -> bool:
    """
    Determines if a document is a dedicated dossier file for a person based on keywords or name matching.
    """
    doc_lower = doc_name.lower()
    
    # 1. Keyword matching
    dossier_keywords = [
        "cv", "resume", "passport", "id_card", "identity", "certificate", 
        "criminal", "medical", "employment", "contract", "background", "reference"
    ]
    if any(keyword in doc_lower for keyword in dossier_keywords):
        return True
        
    # 2. Name anchoring
    name_parts = [p.lower() for p in person_name.split() if p.strip()]
    if name_parts:
        # Check if any significant part of the name is in the filename
        # E.g., "Gubser", "Urs"
        if any(part in doc_lower for part in name_parts if len(part) > 2):
             return True
             
    # Also check slugified name
    slugged_name = slugify(person_name)
    if slugged_name and slugged_name in doc_lower:
        return True
        
    return False

async def build_person_dossier(dataset_name: str, person_name: str, query: str) -> Tuple[List[Chunk], List[Chunk]]:
    """
    Retrieves and logically splits Qdrant chunks into a dedicated 'dossier' (full docs)
    and 'mentions' (isolated chunks), excluding any LinkedIn data.
    """
    logger.info(f"[{dataset_name}] Building dossier for '{person_name}'...")
    dataset_slug = slugify(dataset_name)
    
    dossier: List[Chunk] = []
    mentions: List[Chunk] = []
    
    filtered_chunks = await get_filtered_chunks(dataset_name, person_name, query)
    
    if not filtered_chunks:
        return dossier, mentions
        
    # Reverse to get chronological/least-to-most relevant order based on how Qdrant returns them
    filtered_chunks.reverse()
    
    storage = get_storage()
    seen_dossier_docs = set()
    
    for c in filtered_chunks:
        doc_name = c.document_name
        
        # Actively exclude LinkedIn data
        if "linkedin" in doc_name.lower():
            continue
            
        # If we already pulled this full document into the dossier, skip processing its chunks
        if doc_name in seen_dossier_docs:
            continue
            
        is_dossier = is_dossier_document(doc_name, person_name)
        # Qdrant stores the original document name. The Markdown parser appends .md
        full_md_path = f"datasets2md/{dataset_slug}/{doc_name}.md"
        
        if is_dossier and storage.exists(full_md_path):
            full_text = storage.read_text(full_md_path)
            full_chunk = Chunk(
                chunk_id=f"{doc_name}-all",
                document_name=doc_name,
                page_number="all",
                last_modified=c.last_modified,
                text=full_text,
                score=c.score
            )
            dossier.append(full_chunk)
            seen_dossier_docs.add(doc_name)
        else:
            mentions.append(c)
            
    logger.info(f"[{dataset_name}] Dossier built: {len(dossier)} full docs, {len(mentions)} mentions.")
    return dossier, mentions
