import os
import shutil
import subprocess
from pathlib import Path
from lib.env import get_env_var
from lib.logger import get_logger

logger = get_logger(__name__)

def run_cmd(cmd: list[str], cwd: Path) -> str:
    """Executes a shell command and returns the output."""
    try:
        result = subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"Command {' '.join(cmd)} failed: {e.stderr}")
        raise RuntimeError(f"Git operation failed: {e.stderr}")

def _reconcile_symlinks(repo_dir: Path, workspace_dir: Path) -> list[str]:
    """
    Enforces a strict 1:1 mapping between REPO_PATH/skills and WORKSPACE_PATH.
    1. Removes broken symlinks.
    2. Moves raw folders from workspace to repo and replaces with symlinks.
    3. Creates missing symlinks for new repo folders.
    """
    repo_skills = repo_dir / "skills"
    
    if not workspace_dir.exists():
        workspace_dir.mkdir(parents=True, exist_ok=True)
        
    logs = []
        
    # 1. Scan workspace: Clean dead links and ingest raw folders
    for item in workspace_dir.iterdir():
        if item.name.startswith(".") or item.name == "__pycache__":
            continue
            
        if item.is_symlink():
            target = item.resolve()
            if not target.exists():
                item.unlink()
                logs.append(f"Removed broken symlink: {item.name}")
        elif item.is_dir():
            # It's a raw folder! Ingest it into the repo
            target_path = repo_skills / item.name
            if target_path.exists():
                logs.append(f"Warning: Cannot ingest '{item.name}'. Folder already exists in repo.")
                continue
                
            # Move the folder to the repo
            shutil.move(str(item), str(target_path))
            # Create the symlink pointing back to it
            item.symlink_to(target_path)
            logs.append(f"Ingested raw skill to repo and symlinked: {item.name}")

    # 2. Scan Repo: Expose all skills via symlinks
    for repo_item in repo_skills.iterdir():
        if not repo_item.is_dir() or repo_item.name.startswith(".") or repo_item.name == "__pycache__":
            continue
            
        workspace_link = workspace_dir / repo_item.name
        if not workspace_link.exists():
            workspace_link.symlink_to(repo_item)
            logs.append(f"Created missing symlink for repo skill: {repo_item.name}")
            
    if not logs:
        logs.append("Workspace and Repo symlinks are perfectly perfectly synchronized.")
        
    return logs

async def sictic_git_sync(action: str, message: str = "") -> str:
    """Main orchestration for git sync and symlink parity."""
    repo_dir = Path(get_env_var("REPO_PATH"))
    workspace_dir = Path(get_env_var("WORKSPACE_PATH"))
    
    output = []
    
    # Always reconcile symlinks first!
    output.append("--- Symlink Reconciliation ---")
    reconcile_logs = _reconcile_symlinks(repo_dir, workspace_dir)
    output.extend(reconcile_logs)
    output.append("------------------------------")
    
    if action == "reconcile":
        return "\n".join(output)
        
    if action == "status":
        status = run_cmd(["git", "status", "-s"], cwd=repo_dir)
        if not status:
            output.append("Git working tree is clean.")
        else:
            output.append("Pending Git changes:\n" + status)
        return "\n".join(output)
        
    if action == "pull":
        pull_log = run_cmd(["git", "pull"], cwd=repo_dir)
        output.append("Git Pull Result:\n" + pull_log)
        # Re-reconcile just in case the pull brought in new folders or deleted old ones
        _reconcile_symlinks(repo_dir, workspace_dir)
        return "\n".join(output)
        
    if action == "push":
        # Check if there is anything to commit
        status = run_cmd(["git", "status", "-s"], cwd=repo_dir)
        if not status:
            output.append("Nothing to commit. Git working tree is clean.")
            return "\n".join(output)
            
        run_cmd(["git", "add", "."], cwd=repo_dir)
        commit_log = run_cmd(["git", "commit", "-m", message], cwd=repo_dir)
        output.append("Git Commit Result:\n" + commit_log)
        
        push_log = run_cmd(["git", "push"], cwd=repo_dir)
        output.append("Git Push Result:\n" + push_log)
        
        return "\n".join(output)

    return "Invalid action."
