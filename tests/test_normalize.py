from music_wiki.core.normalize import clean_name, match_key, split_feat


def test_clean_name_trims_and_collapses():
    assert clean_name("  IU   Official ") == "IU Official"
    assert clean_name(None) is None


def test_match_key_is_casefolded():
    assert match_key("The Beatles") == match_key("the beatles")


def test_split_feat_extracts_artists():
    assert split_feat("Lilac (feat. SUGA)") == ("Lilac", ["SUGA"])
    assert split_feat("Song [Feat. A & B]") == ("Song", ["A", "B"])


def test_split_feat_passthrough_when_absent():
    assert split_feat("Plain Title") == ("Plain Title", [])
