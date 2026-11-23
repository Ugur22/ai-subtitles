import json

from evals.diarization_compare import compare_results, compare_turns, main


def _t(start, end, speaker):
    return {"start": start, "end": end, "speaker": speaker}


TWO_SPEAKERS = [_t(0, 10, "SPEAKER_00"), _t(10, 20, "SPEAKER_01"), _t(20, 30, "SPEAKER_00")]


def test_identical_runs_fully_agree():
    report = compare_turns(TWO_SPEAKERS, TWO_SPEAKERS)
    assert report["unmatched_shared_speech"] == 0
    assert report["mapping"] == {"SPEAKER_00": "SPEAKER_00", "SPEAKER_01": "SPEAKER_01"}
    assert report["shared_speech_seconds"] == 30


def test_swapped_labels_are_not_disagreement():
    swapped = [_t(0, 10, "B"), _t(10, 20, "A"), _t(20, 30, "B")]
    report = compare_turns(TWO_SPEAKERS, swapped)
    assert report["mapping"] == {"SPEAKER_00": "B", "SPEAKER_01": "A"}
    assert report["unmatched_shared_speech"] == 0


def test_split_speaker_counts_the_smaller_half_as_unmatched():
    split = [_t(0, 10, "X"), _t(10, 20, "Y"), _t(20, 25, "Z"), _t(25, 30, "Z")]
    report = compare_turns(TWO_SPEAKERS, split)
    assert report["speakers"] == {"a": 2, "b": 3}
    assert report["unmatched_shared_speech"] == round(10 / 30, 4)


def test_one_speaker_against_two():
    one = [_t(0, 30, "SPEAKER_00")]
    report = compare_turns(one, TWO_SPEAKERS)
    assert report["mapping"] == {"SPEAKER_00": "SPEAKER_00"}
    assert report["unmatched_shared_speech"] == round(10 / 30, 4)


def test_overlapping_turns_within_one_side_are_all_counted():
    a = [_t(0, 100, "A"), _t(10, 20, "B")]
    b = [_t(50, 60, "X"), _t(15, 18, "Y")]
    report = compare_turns(a, b)
    assert report["shared_speech_seconds"] == 16
    assert report["mapping"] == {"A": "X", "B": "Y"}


def test_no_shared_speech_has_no_score():
    report = compare_turns([_t(0, 5, "A")], [_t(10, 15, "B")])
    assert report["unmatched_shared_speech"] is None
    assert report["mapping"] == {}


def test_compare_cli_reads_result_files(tmp_path, capsys):
    base = {"label": "pyannote-3.1", "pyannote_version": "3.1.1", "wall_seconds": 40.0, "turns": TWO_SPEAKERS}
    cand = {**base, "label": "community-1", "pyannote_version": "4.0.1", "wall_seconds": 30.0}
    (tmp_path / "a.json").write_text(json.dumps(base))
    (tmp_path / "b.json").write_text(json.dumps(cand))

    assert main([str(tmp_path / "a.json"), str(tmp_path / "b.json")]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == compare_results(base, cand)
    assert report["wall_seconds"] == {"a": 40.0, "b": 30.0}
    assert report["speech_seconds"] == {"a": 30, "b": 30}
