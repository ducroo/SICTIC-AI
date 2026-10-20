import pytest

from lib.datasets.models import Chunk
from lib.people.dossier import (
    MAX_FULL_DOCUMENT_CHARACTERS,
    build_person_dossier,
    is_personal_document,
    person_in_filename,
)


@pytest.fixture(autouse=True)
def parsed_dataset_path(mocker, mock_env):
    from lib.people.model import Person
    mocker.patch("lib.people.dossier.persons_in_dataset", return_value=[Person(full_name="Stefan Klauser")])
    mocker.patch(
        "lib.people.dossier.dataset_parsed_path",
        return_value="docling_data/datasets2md/aisot",
    )


def _chunk(document_name: str, text: str = "Stefan Klauser is mentioned.") -> Chunk:
    return Chunk(
        chunk_id=f"{document_name}-1",
        document_name=document_name,
        page_number=1,
        last_modified=0.0,
        text=text,
        score=1.0,
    )


def test_person_in_filename_requires_name_tokens():
    assert person_in_filename("CV Stefan Klauser.pdf", "Stefan Klauser")
    assert person_in_filename("S Klauser passport.pdf", "Stefan Klauser")
    assert not person_in_filename("Beekee Investor Pitch.pdf", "Bee Kee")
    assert not person_in_filename("Klauser customer contract.pdf", "Stefan Klauser")


def test_personal_document_uses_precise_phrases():
    assert is_personal_document("CVs of founders.pdf")
    assert is_personal_document("curriculum_vitae.pdf")
    assert is_personal_document("criminal record.pdf")
    assert is_personal_document("reference letter.pdf")
    assert not is_personal_document("customer contract.pdf")
    assert not is_personal_document("employment regulations.pdf")
    assert not is_personal_document("background information.pdf")


@pytest.mark.asyncio
async def test_personal_document_expands_once(mocker):
    chunks = [
        _chunk("CVs of founders.pdf"),
        _chunk("CVs of founders.pdf", "Stefan Klauser has another mention."),
    ]
    mocker.patch(
        "lib.people.dossier.get_filtered_chunks",
        return_value=chunks,
    )
    storage = mocker.patch("lib.people.dossier.get_storage").return_value
    storage.exists.return_value = True
    storage.read_text.return_value = "Complete founder CV document."

    dossier, mentions = await build_person_dossier(
        "aisot",
        "Stefan Klauser",
        "Who is Stefan Klauser?",
    )

    assert len(dossier) == 1
    assert dossier[0].text == "Complete founder CV document."
    assert mentions == []
    storage.read_text.assert_called_once()


@pytest.mark.asyncio
async def test_pdf_and_markdown_resumes_expand_from_their_parsed_paths(mocker):
    chunks = [
        _chunk(
            "resumes/Peter-Herger-2025-CV.pdf",
            "Peter Herger is mentioned in his CV.",
        ),
        _chunk(
            "resumes/Peter Herger-resume.md",
            "Peter Herger is mentioned in his resume.",
        ),
    ]
    mocker.patch(
        "lib.people.dossier.get_filtered_chunks",
        return_value=chunks,
    )
    storage = mocker.patch("lib.people.dossier.get_storage").return_value
    parsed_documents = {
        (
            "docling_data/datasets2md/aisot/"
            "resumes/Peter-Herger-2025-CV.pdf.md"
        ): "Complete PDF resume.",
        (
            "docling_data/datasets2md/aisot/"
            "resumes/Peter Herger-resume.md"
        ): "Complete Markdown resume.",
    }
    storage.exists.side_effect = parsed_documents.__contains__
    storage.read_text.side_effect = parsed_documents.__getitem__

    dossier, mentions = await build_person_dossier(
        "aisot",
        "Peter Herger",
        "Who is Peter Herger?",
    )

    assert [document.document_name for document in dossier] == [
        "resumes/Peter Herger-resume.md",
        "resumes/Peter-Herger-2025-CV.pdf",
    ]
    assert [document.text for document in dossier] == [
        "Complete Markdown resume.",
        "Complete PDF resume.",
    ]
    assert mentions == []


@pytest.mark.asyncio
async def test_generic_document_remains_a_chunk(mocker):
    chunk = _chunk("Customer Contract Examples.pdf")
    mocker.patch(
        "lib.people.dossier.get_filtered_chunks",
        return_value=[chunk],
    )
    storage = mocker.patch("lib.people.dossier.get_storage").return_value

    dossier, mentions = await build_person_dossier(
        "aisot",
        "Stefan Klauser",
        "Who is Stefan Klauser?",
    )

    assert dossier == []
    assert mentions == [chunk]
    storage.read_text.assert_not_called()


@pytest.mark.asyncio
async def test_oversized_personal_document_remains_a_chunk(mocker):
    chunk = _chunk("Stefan Klauser CV.pdf")
    mocker.patch(
        "lib.people.dossier.get_filtered_chunks",
        return_value=[chunk],
    )
    storage = mocker.patch("lib.people.dossier.get_storage").return_value
    storage.exists.return_value = True
    storage.read_text.return_value = "x" * (MAX_FULL_DOCUMENT_CHARACTERS + 1)

    dossier, mentions = await build_person_dossier(
        "aisot",
        "Stefan Klauser",
        "Who is Stefan Klauser?",
    )

    assert dossier == []
    assert mentions == [chunk]


def test_unique_ordered_combinations_and_short_exact_names():
    from lib.people.dossier import _unique_name_phrases
    names = ("Valentina Carla Mercedes Gasser", "Maarten Lucas Steven du Croo de Jongh", "Li Bo")
    variants = _unique_name_phrases(names, 8)
    assert "valentina gasser" in variants[0]
    assert "lucas du croo de jongh" in variants[1]
    assert "du de" not in variants[1]
    assert "li bo" in variants[2]
    assert "gasser valentina" not in variants[0]


def test_all_shared_combinations_are_ambiguous_even_short_exact_names():
    from lib.people.dossier import _unique_name_phrases
    variants = _unique_name_phrases(("Valentina Carla Gasser", "Valentina Maria Gasser"), 8)
    assert all("valentina gasser" not in names for names in variants)
    assert "valentina carla gasser" in variants[0]
    assert not _unique_name_phrases(("Li Bo", "Li Ming Bo"), 8)[0]
    assert not any(_unique_name_phrases(("Stefan Klauser", "Stefan Klauser"), 8))


def test_full_word_normalization():
    from lib.people.dossier import _phrase_pattern, _matches_phrase
    pattern = _phrase_pattern(frozenset({"valentina gasser"}))
    assert _matches_phrase(pattern, "CV_VALENTINA-GASSER.pdf")
    assert _matches_phrase(pattern, "Valentina\nGasser")
    assert not _matches_phrase(pattern, "Valentina Gassert")
    assert not _matches_phrase(pattern, "Valentina Gasser2")
    assert not _matches_phrase(pattern, "NotValentina Gasser")
    assert not _matches_phrase(pattern, "Valentina is friends with Gasser")


@pytest.mark.asyncio
async def test_scan_recovers_short_names_filenames_and_contacts_without_semantic_search(mocker):
    from lib.people.dossier import get_filtered_chunks
    from lib.people.model import Person
    target = Person(full_name="Valentina Carla Mercedes Gasser", email_addresses=["v@example.com"],
                    linkedin_id="valentina-gasser")
    mocker.patch("lib.people.dossier.persons_in_dataset", return_value=[target])
    sync = mocker.patch("lib.people.dossier.sync_datasets")
    chunks = [
        _chunk("CV_Valentina_Gasser.pdf", "Work history without a name"),
        _chunk("letter.pdf", "Valentina Gasser wrote this."),
        _chunk("email.pdf", "Contact v@example.com"),
        _chunk("link.pdf", "https://www.linkedin.com/in/valentina-gasser/"),
        _chunk("other.pdf", "Valentina Gassert wrote this."),
    ]
    mocker.patch("lib.people.dossier.iter_parsed_chunks", return_value=iter(chunks))
    result = await get_filtered_chunks("aisot", target.full_name, "unused", person=target)
    assert result == chunks[:4]
    sync.assert_awaited_once_with(["aisot"], raise_on_error=True)


@pytest.mark.asyncio
async def test_ambiguous_names_need_contact_evidence(mocker):
    from lib.people.dossier import get_filtered_chunks
    from lib.people.model import Person
    one = Person(full_name="Valentina Carla Gasser", email_addresses=["one@example.com"])
    two = Person(full_name="Valentina Maria Gasser", email_addresses=["two@example.com"])
    mocker.patch("lib.people.dossier.persons_in_dataset", return_value=[one, two])
    mocker.patch("lib.people.dossier.sync_datasets")
    chunks = [_chunk("a.pdf", "Valentina Gasser"),
              _chunk("b.pdf", "Valentina Gasser one@example.com"),
              _chunk("c.pdf", "Valentina Gasser two@example.com")]
    mocker.patch("lib.people.dossier.iter_parsed_chunks", return_value=iter(chunks))
    assert await get_filtered_chunks("aisot", one.full_name, "", person=one) == [chunks[1]]


@pytest.mark.asyncio
async def test_short_name_document_expands_and_deduplicates(mocker):
    from lib.people.model import Person
    person = Person(full_name="Valentina Carla Mercedes Gasser")
    mocker.patch("lib.people.dossier.persons_in_dataset", return_value=[person])
    mocker.patch("lib.people.dossier.sync_datasets")
    cv = _chunk("CV_Valentina_Gasser.pdf", "Professional history")
    passage = _chunk("meeting.pdf", "Valentina Gasser participated.")
    second = passage.model_copy(update={"chunk_id": "meeting-2", "page_number": 2})
    mocker.patch("lib.people.dossier.iter_parsed_chunks", return_value=iter([cv, cv, passage, passage, second]))
    storage = mocker.patch("lib.people.dossier.get_storage").return_value
    storage.exists.return_value = True
    storage.read_text.return_value = "Full resume"
    dossier, mentions = await build_person_dossier("aisot", person.full_name, "", person=person)
    assert len(dossier) == 1
    assert len(mentions) == 2
    assert {c.chunk_id for c in mentions} == {passage.chunk_id, second.chunk_id}
    storage.read_text.assert_called_once()


@pytest.mark.asyncio
async def test_missing_roster_and_sync_failure_are_not_empty_evidence(mocker):
    from lib.people.dossier import get_filtered_chunks
    read = mocker.patch("lib.people.dossier.persons_in_dataset", side_effect=FileNotFoundError("roster"))
    with pytest.raises(FileNotFoundError):
        await get_filtered_chunks("aisot", "Stefan Klauser", "")
    read.side_effect = None
    read.return_value = []
    mocker.patch("lib.people.dossier.sync_datasets", side_effect=RuntimeError("ingestion"))
    with pytest.raises(RuntimeError, match="ingestion"):
        await get_filtered_chunks("aisot", "Stefan Klauser", "")


def test_enriched_person_keeps_roster_identity(mocker):
    from lib.people.dossier import _identity_filter, _matches_phrase
    from lib.people.model import Person
    mocker.patch("lib.people.dossier.persons_in_dataset", return_value=[Person(full_name="Jane Doe")])
    enriched = Person(full_name="Jane Doe", linkedin_id="jane-doe")
    target, pattern = _identity_filter("aisot", enriched.full_name, enriched)
    assert target is enriched
    assert _matches_phrase(pattern, "Jane Doe")


@pytest.mark.asyncio
async def test_large_named_document_keeps_nameless_pages_once(mocker):
    mocker.patch("lib.people.dossier.sync_datasets")
    a = _chunk("Stefan Klauser CV.pdf", "Relevant experience")
    b = a.model_copy(update={"chunk_id": "second", "page_number": 2, "text": "More experience"})
    mocker.patch("lib.people.dossier.iter_parsed_chunks", return_value=iter([a, b, a]))
    storage = mocker.patch("lib.people.dossier.get_storage").return_value
    storage.exists.return_value = True
    storage.read_text.return_value = "x" * (MAX_FULL_DOCUMENT_CHARACTERS + 1)
    dossier, mentions = await build_person_dossier("aisot", "Stefan Klauser", "")
    assert not dossier
    assert {c.chunk_id for c in mentions} == {a.chunk_id, b.chunk_id}
    assert len(mentions) == 2
    storage.read_text.assert_called_once()
