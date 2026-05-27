import asyncio
import argparse
from skills.sictic_git_sync.sictic_git_sync import sictic_git_sync

async def main():
    parser = argparse.ArgumentParser(description="Synchronize OpenClaw workspace skills with the SICTIC-AI Git repository.")
    parser.add_argument("--action", type=str, choices=["push", "pull", "status", "reconcile"], required=True, 
                        help="The synchronization action to perform.")
    parser.add_argument("--message", type=str, default="auto-sync skills", 
                        help="Commit message for 'push' action.")
    
    args = parser.parse_args()
    
    result = await sictic_git_sync(action=args.action, message=args.message)
    print("\n" + result)

if __name__ == "__main__":
    asyncio.run(main())
