import os
import typer
from lib.batch_audit.batch_audit import batch_audit
from lib.logger import get_logger

logger = get_logger(__name__)

app = typer.Typer(help="Core batch-processing CLI for due diligence checklists.")

@app.command()
def main(
    dataset_name: str = typer.Argument(..., help="Name of the dataset (e.g., avientus)."),
    checklist_path: str = typer.Argument(..., help="Path to the checklist markdown file.")
):
    try:
        if not os.path.isfile(checklist_path):
            logger.error(f"Checklist file not found: {checklist_path}")
            raise typer.Exit(code=1)
            
        with open(checklist_path, 'r', encoding='utf-8') as f:
            checklist_string = f.read()
            
        result = batch_audit(dataset_name=dataset_name, checklist_string=checklist_string)
        
        # Output final result to console
        print(result)
        
    except typer.Exit:
        raise
    except Exception as e:
        logger.error(str(e))
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
