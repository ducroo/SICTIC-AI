import shutil
import subprocess
from pathlib import Path
from lib.env import get_env_var
from lib.logger import get_logger

logger = get_logger(__name__)
IGNORED_COPY_NAMES = {"__pycache__", ".DS_Store"}


def _is_skill_dir(path: Path) -> bool:
    return path.is_dir() and (path / "SKILL.md").is_file()

def run_cmd(cmd: list[str], cwd: Path) -> str:
    """Executes a shell command and returns the output."""
    try:
        result = subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"Command {' '.join(cmd)} failed: {e.stderr}")
        raise RuntimeError(f"Git operation failed: {e.stderr}")


def _copy_skill_contents(repo_item: Path, workspace_item: Path) -> None:
    if workspace_item.exists() or workspace_item.is_symlink():
        if workspace_item.is_symlink() or workspace_item.is_file():
            workspace_item.unlink()
        else:
            shutil.rmtree(workspace_item)
    shutil.copytree(
        repo_item,
        workspace_item,
        ignore=shutil.ignore_patterns("__pycache__", ".DS_Store", "*.pyc"),
    )


def _reconcile_workspace_copies(repo_dir: Path, workspace_dir: Path) -> list[str]:
    """
    Enforces a strict 1:1 mapping between REPO_PATH/skills and WORKSPACE_PATH.
    1. Removes old symlink installs.
    2. Moves unmanaged raw folders from workspace to repo when possible.
    3. Copies repository skills into the workspace.
    """
    repo_skills = repo_dir / "skills"
    
    if not workspace_dir.exists():
        workspace_dir.mkdir(parents=True, exist_ok=True)
        
    logs = []
        
    # 1. Scan workspace: remove old links and ingest raw folders.
    for item in workspace_dir.iterdir():
        if item.name.startswith(".") or item.name == "__pycache__":
            continue
            
        if item.is_symlink():
            item.unlink()
            logs.append(f"Removed workspace symlink: {item.name}")
        elif item.is_dir():
            if not _is_skill_dir(item):
                logs.append(f"Skipped unmanaged non-skill workspace folder: {item.name}")
                continue
            repo_item = repo_skills / item.name
            if repo_item.exists():
                continue

            target_path = repo_item
            shutil.move(str(item), str(target_path))
            logs.append(f"Ingested raw skill into repo: {item.name}")

    # 2. Scan repo: copy all skills into the workspace.
    for repo_item in repo_skills.iterdir():
        if (
            not _is_skill_dir(repo_item)
            or repo_item.name.startswith(".")
            or repo_item.name in IGNORED_COPY_NAMES
        ):
            continue
            
        workspace_item = workspace_dir / repo_item.name
        _copy_skill_contents(repo_item, workspace_item)
        logs.append(f"Copied repo skill into workspace: {repo_item.name}")
            
    if not logs:
        logs.append("Workspace and repo skill copies are synchronized.")
        
    return logs

async def sictic_git_sync(action: str, message: str = "") -> str:
    """Main orchestration for git sync and workspace skill copies."""
    repo_dir = Path(get_env_var("REPO_PATH"))
    workspace_dir = Path(get_env_var("WORKSPACE_PATH"))
    
    output = []
    
    output.append("--- Workspace Copy Reconciliation ---")
    reconcile_logs = _reconcile_workspace_copies(repo_dir, workspace_dir)
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
        _reconcile_workspace_copies(repo_dir, workspace_dir)
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
