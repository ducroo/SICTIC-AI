from lib.logger import get_logger
from lib.adapters.apify import ApifyAdapter

logger = get_logger(__name__)

class WebSearchAdapter:
    def __init__(self):
        self.apify = ApifyAdapter()
        
    def search(self, query: str, num_results: int = 10):
        try:
            logger.info(f"Querying Google Search via Apify for: {query}")
            run_input = {
                "queries": query,
                "maxPagesPerQuery": 1
            }
            results = self.apify.run_actor("apify/google-search-scraper", run_input)
            
            parsed_results = []
            for item in results:
                organic = item.get("organicResults", [])
                for result in organic:
                    parsed_results.append({
                        "title": result.get("title", ""),
                        "link": result.get("url", ""),
                        "snippet": result.get("description", "")
                    })
                    
            return parsed_results[:num_results]
        except Exception as e:
            logger.error(f"Web Search failed for query '{query}': {e}")
            raise RuntimeError(f"Web Search error: {e}")
