import shutil
import subprocess
from pathlib import Path
from lib.env import get_env_var
from lib.logger import get_logger

logger = get_logger(__name__)
MANAGED_LINK_MARKER = ".sictic-symlink-dir"

def run_cmd(cmd: list[str], cwd: Path) -> str:
    """Executes a shell command and returns the output."""
    try:
        result = subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"Command {' '.join(cmd)} failed: {e.stderr}")
        raise RuntimeError(f"Git operation failed: {e.stderr}")


def _is_managed_link_dir(workspace_item: Path, repo_item: Path) -> bool:
    marker = workspace_item / MANAGED_LINK_MARKER
    return (
        workspace_item.is_dir()
        and not workspace_item.is_symlink()
        and marker.exists()
        and marker.read_text(encoding="utf-8").strip() == str(repo_item)
    )


def _link_skill_contents(repo_item: Path, workspace_item: Path) -> None:
    workspace_item.mkdir(parents=True, exist_ok=True)
    (workspace_item / MANAGED_LINK_MARKER).write_text(
        f"{repo_item}\n",
        encoding="utf-8",
    )
    for child in repo_item.iterdir():
        if child.name in {"__pycache__", ".DS_Store"} or child.suffix == ".pyc":
            continue
        target = workspace_item / child.name
        if target.exists() or target.is_symlink():
            continue
        target.symlink_to(child)


def _reconcile_symlinks(repo_dir: Path, workspace_dir: Path) -> list[str]:
    """
    Enforces a strict 1:1 mapping between REPO_PATH/skills and WORKSPACE_PATH.
    1. Removes broken symlinks.
    2. Preserves managed workspace folders whose contents link to repo skills.
    3. Moves unmanaged raw folders from workspace to repo when possible.
    4. Creates missing managed folders for new repo skills.
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
            repo_item = repo_skills / item.name
            if _is_managed_link_dir(item, repo_item):
                continue

            # It's a raw folder! Ingest it into the repo
            target_path = repo_item
            if target_path.exists():
                logs.append(f"Warning: Cannot ingest '{item.name}'. Folder already exists in repo.")
                continue
                
            # Move the folder to the repo
            shutil.move(str(item), str(target_path))
            _link_skill_contents(target_path, item)
            logs.append(f"Ingested raw skill to repo and linked contents: {item.name}")

    # 2. Scan Repo: Expose all skills via symlinks
    for repo_item in repo_skills.iterdir():
        if not repo_item.is_dir() or repo_item.name.startswith(".") or repo_item.name == "__pycache__":
            continue
            
        workspace_link = workspace_dir / repo_item.name
        if not workspace_link.exists():
            _link_skill_contents(repo_item, workspace_link)
            logs.append(f"Created missing workspace links for repo skill: {repo_item.name}")
            
    if not logs:
        logs.append("Workspace and repo skill links are synchronized.")
        
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
