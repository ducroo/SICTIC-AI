from lib.datasets.sparse import (
    encode_document,
    encode_query,
    token_id,
    tokenize,
)


def test_tokenize_lowercases_and_drops_stopwords():
    assert tokenize("The Company holds the Patent") == [
        "company",
        "holds",
        "patent",
    ]


def test_tokenize_keeps_domain_terms_and_numbers():
    tokens = tokenize("Art. 332 OR Inventionsabtretungserklärung")

    assert "332" in tokens
    assert "art" in tokens
    assert "inventionsabtretungserklärung" in tokens


def test_tokenize_drops_single_characters():
    assert tokenize("a b IP") == ["ip"]


def test_token_id_is_stable_and_fits_unsigned_32_bit():
    first = token_id("patent")

    assert first == token_id("patent")
    assert 0 <= first < 2**32
    assert first != token_id("patents")


def test_encode_document_returns_sorted_unique_indices():
    sparse = encode_document("patent assignment patent register")

    assert sparse.indices == sorted(sparse.indices)
    assert len(sparse.indices) == len(set(sparse.indices))
    assert len(sparse.indices) == len(sparse.values)


def test_encode_document_saturates_repeated_terms():
    once = encode_document("patent")
    many = encode_document("patent " * 10)
    index = token_id("patent")

    single_weight = once.values[once.indices.index(index)]
    repeated_weight = many.values[many.indices.index(index)]

    assert repeated_weight > single_weight
    # BM25 saturation keeps term frequency from scaling linearly.
    assert repeated_weight < single_weight * 10


def test_encode_document_weights_rare_terms_higher_in_long_text():
    short = encode_document("patent assignment")
    long = encode_document("patent assignment " + "filler content " * 100)
    index = token_id("patent")

    assert (
        long.values[long.indices.index(index)]
        < short.values[short.indices.index(index)]
    )


def test_encode_query_uses_unit_weights_per_distinct_term():
    sparse = encode_query("patent patent assignment")

    assert sparse.indices == sorted({token_id("patent"), token_id("assignment")})
    assert sparse.values == [1.0, 1.0]


def test_encoding_empty_or_stopword_only_text_is_falsy():
    assert not encode_document("")
    assert not encode_query("the and of")
