from __future__ import annotations

from pathlib import PurePosixPath

from lib.insights.locking import write_if_changed
from lib.insights.manifest import (
    dataset_revisions,
    load_insight_manifest,
    save_insight_entry,
)
from lib.insights.paths import (
    insight_base,
    insight_directory,
    insight_filename,
    insight_manifest_path,
    model_slug,
)
from lib.insights.selection import find_any, find_reusable, is_reusable
from lib.logger import get_logger
from lib.storage import get_storage

logger = get_logger(__name__)


class InsightFile:
    """Facade for insight paths, content, selection, and freshness."""

    def __init__(
        self,
        dataset: str,
        skill: str,
        model: str,
        identifier: str | None = None,
        subdir: bool = False,
        source_datasets: list[str] | None = None,
        prompt_key: str | None = None,
        *,
        run_id: str | None = None,
        _path_override: str | None = None,
    ):
        self.dataset = dataset
        self.skill = skill
        self.model = model
        self.identifier = identifier
        self.subdir = subdir
        self.run_id = run_id
        self.source_datasets = source_datasets or [dataset]
        self.prompt_key = prompt_key or ""
        self._path_override = _path_override

    @property
    def directory(self) -> str:
        return insight_directory(
            self.dataset,
            self.skill,
            subdir=self.subdir,
            run_id=self.run_id,
        )

    @property
    def filename(self) -> str:
        return insight_filename(
            self.dataset,
            self.skill,
            self.model,
            identifier=self.identifier,
            subdir=self.subdir,
        )

    @property
    def path(self) -> str:
        return self._path_override or f"{self.directory}/{self.filename}"

    @property
    def _base_name(self) -> str:
        return insight_base(
            self.dataset,
            self.skill,
            identifier=self.identifier,
            subdir=self.subdir,
        )

    @property
    def _manifest_path(self) -> str:
        return insight_manifest_path(self.dataset)

    def exists(self) -> bool:
        return get_storage().exists(self.path)

    def content(self) -> str:
        return get_storage().read_text(self.path)

    def find_reusable(self) -> InsightFile | None:
        return find_reusable(self)

    def find_any(self) -> InsightFile | None:
        return find_any(self)

    def is_reusable(self) -> bool:
        return is_reusable(self)

    def save(self, content: str) -> None:
        storage = get_storage()
        if model_slug(self.model) == "manual":
            write_if_changed(storage, self.path, content)
            return

        revisions = self._dataset_revisions()
        if revisions is None:
            write_if_changed(storage, self.path, content)
            logger.warning(
                "Saved %s without freshness metadata because at least one "
                "source dataset has no indexed revision.",
                self.path,
            )
            return

        write_if_changed(storage, self.path, content)
        save_insight_entry(
            storage,
            manifest_path=self._manifest_path,
            insight_path=self.path,
            model=model_slug(self.model),
            revisions=revisions,
            prompt_key=self.prompt_key,
        )

    def _candidate(self, model: str) -> InsightFile:
        return InsightFile(
            dataset=self.dataset,
            skill=self.skill,
            model=model,
            identifier=self.identifier,
            subdir=self.subdir,
            run_id=self.run_id,
            source_datasets=self.source_datasets,
            prompt_key=self.prompt_key,
        )

    def _candidate_from_filename(self, filename: str) -> InsightFile:
        prefix = f"{self._base_name}-"
        candidate_model = PurePosixPath(filename).stem[len(prefix) :]
        return InsightFile(
            dataset=self.dataset,
            skill=self.skill,
            model=candidate_model,
            identifier=self.identifier,
            subdir=self.subdir,
            run_id=self.run_id,
            source_datasets=self.source_datasets,
            prompt_key=self.prompt_key,
            _path_override=f"{self.directory}/{filename}",
        )

    def _dataset_revisions(self) -> dict[str, str] | None:
        return dataset_revisions(get_storage(), self.source_datasets)

    def _load_manifest(self) -> dict:
        return load_insight_manifest(get_storage(), self._manifest_path)
