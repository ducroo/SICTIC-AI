import asyncio
import argparse
from skills.ranking.ranking_persons import ranking_persons

async def main():
    parser = argparse.ArgumentParser(description="Ranking module for SICTIC-AI")
    parser.add_argument("--target", type=str, default="persons", choices=["persons"], help="What entity to rank")
    parser.add_argument("--objective", type=str, required=True, help="The objective/criteria for ranking")
    parser.add_argument("--query", type=str, default="", help="Semantic search query to fetch candidates")
    parser.add_argument("--top_k", type=int, default=8, help="Number of top candidates to return")
    
    args = parser.parse_args()

    if args.target == "persons":
        result = await ranking_persons(
            objective=args.objective,
            query=args.query,
            top_k=args.top_k
        )
        print("\n\n" + result)
    else:
        print(f"Target '{args.target}' is not yet implemented.")

if __name__ == "__main__":
    asyncio.run(main())
