from services.language_lock import pick_dominant_language, _sample_chunks


def test_music_opening_guessed_english_does_not_outvote_dialogue():
    votes = [("en", 0.55), ("it", 0.98), ("it", 0.97), ("ko", 0.4), ("it", 0.95)]
    assert pick_dominant_language(votes) == "it"


def test_all_weak_votes_returns_none():
    assert pick_dominant_language([("en", 0.3), ("ko", 0.2)]) is None


def test_sampling_is_capped_and_spread():
    chunks = [str(i) for i in range(40)]
    sampled = _sample_chunks(chunks)
    assert len(sampled) == 8 and sampled[0] == "0" and sampled[-1] == "35"
