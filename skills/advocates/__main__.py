import argparse
import asyncio
from skills.advocates.advocates import advocates

def main():
    parser = argparse.ArgumentParser(description="Find SICTIC members to act as advocates for an event.")
    parser.add_argument("event_name", type=str, help="Short name of the event")
    parser.add_argument("event_description", type=str, help="Detailed description of the event and skills required")
    parser.add_argument("--target-members", type=str, nargs="+", default=None, help="Optional list of member IDs to restrict the search to")
    parser.add_argument("--exclude-members", type=str, nargs="+", default=None, help="Optional list of member IDs to exclude from the search")
    parser.add_argument("--top-k", type=int, default=10, help="Number of top advocates to return")
    
    args = parser.parse_args()
    
    try:
        result = asyncio.run(advocates(
            event_name=args.event_name,
            event_description=args.event_description,
            target_members=args.target_members,
            exclude_members=args.exclude_members,
            top_k=args.top_k
        ))
        print("\n--- Advocates Result ---\n")
        print(result)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
