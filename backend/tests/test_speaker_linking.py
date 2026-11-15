import numpy as np

from speaker_diarization import DEFAULT_LINK_MODEL, ChunkedSpeakerDiarizer


def _voice(angle_degrees):
    angle = np.radians(angle_degrees)
    return np.array([np.cos(angle), np.sin(angle), 0.0])


def _group(index, voices):
    """One diarization group: {local label: (voice vector or None, start offset)}."""
    base = index * 900
    return {
        "segments": [
            {"start": base + offset, "end": base + offset + 5, "speaker": label}
            for label, (_vector, offset) in voices.items()
        ],
        "speaker_embeddings": {
            label: vector for label, (vector, _offset) in voices.items() if vector is not None
        },
    }


def _link(groups, threshold=0.7):
    diarizer = ChunkedSpeakerDiarizer(chunk_duration=900, similarity_threshold=threshold)
    return diarizer._match_speakers(groups)


# cos(40 deg) = 0.77, cos(90 deg) = 0.0: the same person drifts a little between
# groups, a different person is far away.
TOKYO, PROFESSOR = 0, 90


def test_same_voice_in_every_group_becomes_one_speaker():
    groups = [
        _group(0, {"SPEAKER_00": (_voice(TOKYO), 0), "SPEAKER_01": (_voice(PROFESSOR), 10)}),
        _group(1, {"SPEAKER_03": (_voice(PROFESSOR + 20), 0), "SPEAKER_07": (_voice(TOKYO + 20), 10)}),
        _group(2, {"SPEAKER_02": (_voice(TOKYO - 15), 0)}),
    ]

    mapping, count = _link(groups)

    assert count == 2
    assert mapping[0]["SPEAKER_00"] == mapping[1]["SPEAKER_07"] == mapping[2]["SPEAKER_02"] == "SPEAKER_00"
    assert mapping[0]["SPEAKER_01"] == mapping[1]["SPEAKER_03"] == "SPEAKER_01"


def test_two_speakers_of_one_group_are_never_merged():
    groups = [
        _group(0, {"SPEAKER_00": (_voice(0), 0), "SPEAKER_01": (_voice(5), 10)}),
        _group(1, {"SPEAKER_00": (_voice(2), 0)}),
    ]

    mapping, count = _link(groups)

    assert count == 2
    assert mapping[0]["SPEAKER_00"] != mapping[0]["SPEAKER_01"]


def test_result_does_not_depend_on_group_order():
    groups = [
        _group(0, {"SPEAKER_00": (_voice(0), 0), "SPEAKER_01": (_voice(90), 10)}),
        _group(1, {"SPEAKER_00": (_voice(25), 0), "SPEAKER_01": (_voice(60), 10)}),
        _group(2, {"SPEAKER_00": (_voice(45), 0)}),
    ]

    # Global labels follow time, and each group's times are fixed by its index.
    assert _link(groups)[0] == _link(groups[::-1])[0][::-1]


def test_speaker_without_embedding_keeps_its_own_label():
    groups = [
        _group(0, {"SPEAKER_00": (_voice(0), 0)}),
        _group(1, {"SPEAKER_00": (_voice(10), 0), "SPEAKER_04": (None, 10)}),
    ]

    mapping, count = _link(groups)

    assert count == 2
    assert mapping[1]["SPEAKER_04"] not in (mapping[0]["SPEAKER_00"], mapping[1]["SPEAKER_00"])


def test_lower_threshold_links_more_and_global_labels_follow_first_appearance():
    groups = [
        _group(0, {"SPEAKER_05": (_voice(0), 30), "SPEAKER_02": (_voice(90), 0)}),
        _group(1, {"SPEAKER_00": (_voice(-55), 0)}),  # 0.57 to the 0 deg voice, negative to 90 deg
    ]

    _, strict = _link(groups, threshold=0.7)
    mapping, loose = _link(groups, threshold=0.5)

    assert (strict, loose) == (3, 2)
    assert mapping[0]["SPEAKER_02"] == "SPEAKER_00"    # starts at 0 s
    assert mapping[0]["SPEAKER_05"] == mapping[1]["SPEAKER_00"] == "SPEAKER_01"


def test_calibration_log_reports_best_scores_and_threshold_sweep(capsys):
    groups = [
        _group(0, {"SPEAKER_00": (_voice(0), 0)}),
        _group(1, {"SPEAKER_00": (_voice(50), 0)}),
    ]

    _link(groups)
    out = capsys.readouterr().out

    assert "[SpeakerLink] g0 SPEAKER_00 5.0s best: g1=0.643" in out
    assert "speakers per threshold: 0.3=1 0.4=1 0.5=1 0.6=1 0.7=2 (using 0.7)" in out


def test_speaker_with_no_speech_gets_no_label_and_no_segments():
    groups = [
        _group(0, {"SPEAKER_00": (_voice(0), 0)}),
        _group(1, {"SPEAKER_00": (_voice(10), 0)}),
    ]
    groups[0]["segments"].append({"start": 50.0, "end": 50.0, "speaker": "SPEAKER_11"})

    diarizer = ChunkedSpeakerDiarizer(chunk_duration=900)
    mapping, count = diarizer._match_speakers(groups)
    unified = diarizer._unify_segments(groups, mapping)

    assert count == 1
    assert "SPEAKER_11" not in mapping[0]
    assert {seg["speaker"] for seg in unified} == {"SPEAKER_00"}


def test_defaults_link_with_wespeaker_at_the_measured_gap():
    diarizer = ChunkedSpeakerDiarizer()

    assert diarizer.link_model == DEFAULT_LINK_MODEL == "pyannote/wespeaker-voxceleb-resnet34-LM"
    assert diarizer.similarity_threshold == 0.5


def test_negative_segment_does_not_cancel_real_speech():
    groups = [
        _group(0, {"SPEAKER_00": (_voice(0), 0)}),
        _group(1, {"SPEAKER_00": (_voice(90), 0)}),
    ]
    groups[0]["segments"].append({"start": 10.0, "end": 4.0, "speaker": "SPEAKER_00"})

    mapping, count = _link(groups)

    assert count == 2
    assert "SPEAKER_00" in mapping[0]


def test_near_silent_speaker_is_dropped_and_one_second_is_kept(capsys):
    groups = [
        _group(0, {"SPEAKER_00": (_voice(0), 0)}),
        _group(1, {"SPEAKER_00": (_voice(90), 0)}),
    ]
    groups[0]["segments"] += [
        {"start": 40.0, "end": 40.37, "speaker": "SPEAKER_11"},
        {"start": 60.0, "end": 60.02, "speaker": "SPEAKER_11"},
    ]
    groups[1]["segments"].append({"start": 950.0, "end": 951.0, "speaker": "SPEAKER_04"})

    diarizer = ChunkedSpeakerDiarizer(chunk_duration=900)
    mapping, count = diarizer._match_speakers(groups)
    unified = diarizer._unify_segments(groups, mapping)

    assert "SPEAKER_11" not in mapping[0]
    assert "SPEAKER_04" in mapping[1]
    assert count == 3
    assert len({seg["speaker"] for seg in unified}) == count
    assert "[SpeakerLink] dropped g0 SPEAKER_11 (0.4 s of speech)" in capsys.readouterr().out
