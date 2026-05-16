import re
import urllib.parse
import unicodedata

def slugify(text: str) -> str:
    """
    Converts a string to a safe, ASCII-only filename/slug.
    - Decomposes accents/umlauts (e.g., Agnès -> Agnes, Trösch -> Trosch)
    - Strips emojis and other non-ASCII characters
    - Replaces whitespace and non-alphanumeric characters with hyphens
    - Converts to lowercase
    """
    if not text:
        return ""
        
    # Normalize unicode characters (decomposes accents into base letter + diacritic)
    # Then encode to ascii ignoring the diacritics/emojis, and decode back to string
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    
    text = urllib.parse.unquote(str(text)).lower()
    
    # Replace any non-alphanumeric character with a hyphen
    text = re.sub(r'[^\w]+', '-', text)
    
    # Also replace underscores with hyphens for consistency
    text = text.replace('_', '-')
    
    # Collapse multiple consecutive hyphens
    text = re.sub(r'-+', '-', text)
    
    return text.strip('-')
