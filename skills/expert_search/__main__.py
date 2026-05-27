import argparse
import asyncio
from skills.expert_search.expert_search import expert_search

def main():
    parser = argparse.ArgumentParser(description="Find expert individuals for a startup using ranking_persons.")
    parser.add_argument("startup_name", type=str, help="Name of the startup")
    parser.add_argument("--target-experts", type=str, nargs="+", default=None, help="Optional list of expert IDs to restrict the search to")
    parser.add_argument("--exclude-experts", type=str, nargs="+", default=None, help="Optional list of expert IDs to exclude from the search")
    parser.add_argument("--top-k", type=int, default=8, help="Number of top experts to return")
    
    args = parser.parse_args()
    
    try:
        result = asyncio.run(expert_search(
            startup_name=args.startup_name,
            target_experts=args.target_experts,
            exclude_experts=args.exclude_experts,
            top_k=args.top_k
        ))
        print("\n--- Expert Search Result ---\n")
        print(result)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
