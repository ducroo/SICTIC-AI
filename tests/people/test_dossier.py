import pytest

from lib.datasets.models import Chunk
from lib.people.dossier import (
    MAX_FULL_DOCUMENT_CHARACTERS,
    build_person_dossier,
    is_personal_document,
    person_in_filename,
)


@pytest.fixture(autouse=True)
def parsed_dataset_path(mocker):
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
