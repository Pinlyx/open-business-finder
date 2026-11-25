from open_business_finder.text import clean_text, fold


def test_fold_turkish_and_accents():
    assert fold("İzmir") == fold("izmir") == fold("IZMIR") == "izmir"
    assert fold("Şişli") == "sisli"
    assert fold("Kadıköy") == "kadikoy"
    assert fold("  Saint-Denis ") == "saint denis"
    assert fold("Straße") == "strasse"


def test_clean_text_drops_lone_surrogates_and_controls():
    assert clean_text("Cafe \ud83d") == "Cafe"
    assert clean_text("A\ud83dB\x00C") == "ABC"
    assert clean_text("ok \U0001F600") == "ok \U0001F600"  # a real emoji pair is kept
    assert clean_text("\ud800") is None
    assert clean_text(None) is None
    assert clean_text("   ") is None
    # the cleaned value must be encodable
    clean_text("x\udc00y").encode("utf-8")
