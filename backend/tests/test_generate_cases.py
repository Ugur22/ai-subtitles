import asyncio
from unittest.mock import AsyncMock, MagicMock

from evals.generate_cases import generate_cases, main, sample_chunks
from evals import generate_cases as generate_cases_module


def _chunk(index, start, text):
    return {"chunk_index": index, "start_time": float(start), "chunk_text": text}


def _fake_client(rows):
    client = MagicMock()
    execute_result = MagicMock()
    execute_result.data = rows
    query = client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value
    query.execute.return_value = execute_result
    return client


def _fake_provider(generate_side_effect=None, generate_return="a question?"):
    provider = MagicMock()
    if generate_side_effect is not None:
        provider.generate = AsyncMock(side_effect=generate_side_effect)
    else:
        provider.generate = AsyncMock(return_value=generate_return)
    return provider


def test_even_sampling_covers_full_range():
    chunks = [_chunk(i, i * 10, "long enough chunk text here") for i in range(20)]
    sampled = sample_chunks(chunks, count=5, min_chunk_chars=10)

    assert len(sampled) == 5
    indices = [c["chunk_index"] for c in sampled]
    assert indices[0] == 0
    assert indices[-1] == 19
    assert indices == sorted(indices)


def test_short_chunks_are_excluded_from_sampling():
    chunks = [
        _chunk(0, 0, "too short"),
        _chunk(1, 10, "this one is long enough to be sampled"),
        _chunk(2, 20, "short"),
        _chunk(3, 30, "also long enough to be sampled here"),
    ]
    sampled = sample_chunks(chunks, count=10, min_chunk_chars=20)

    assert {c["chunk_index"] for c in sampled} == {1, 3}


def test_one_failing_chunk_does_not_stop_the_rest(monkeypatch):
    rows = [_chunk(i, i * 10, "long enough chunk text for sampling") for i in range(3)]
    monkeypatch.setattr(generate_cases_module, "supabase", MagicMock(return_value=_fake_client(rows)))

    def side_effect(messages, temperature=0.7, max_tokens=60):
        if "10.0s" in messages[0]["content"]:
            raise RuntimeError("provider exploded")
        return "a generated question?"

    provider = _fake_provider(generate_side_effect=side_effect)
    monkeypatch.setattr(generate_cases_module.llm_manager, "get_provider", MagicMock(return_value=provider))

    result = asyncio.run(generate_cases(
        video_hash="hash-1", user_id="user-1", count=3, window=30, min_chunk_chars=10, provider_name=None
    ))

    assert result["generated"] == 2
    assert result["skipped"] == 1


def test_generated_case_shape_is_valid(monkeypatch):
    rows = [_chunk(0, 42, "long enough chunk text for sampling here")]
    monkeypatch.setattr(generate_cases_module, "supabase", MagicMock(return_value=_fake_client(rows)))
    provider = _fake_provider(generate_return="Where did this happen?")
    monkeypatch.setattr(generate_cases_module.llm_manager, "get_provider", MagicMock(return_value=provider))

    result = asyncio.run(generate_cases(
        video_hash="hash-1", user_id="user-1", count=1, window=30, min_chunk_chars=10, provider_name=None
    ))

    assert result["generated"] == 1
    case = result["candidates"][0]
    assert case["video_hash"] == "hash-1"
    assert case["user_id"] == "user-1"
    assert case["question"] == "Where did this happen?"
    assert case["expected_start_seconds"] == 42
    assert case["acceptable_window_seconds"] == 30


def test_no_chunks_available_exits_nonzero(monkeypatch, tmp_path):
    monkeypatch.setattr(generate_cases_module, "supabase", MagicMock(return_value=_fake_client([])))
    monkeypatch.setattr(
        "sys.argv",
        ["generate_cases.py", "--video-hash", "hash-1", "--user-id", "user-1", "--out", str(tmp_path / "out.json")],
    )

    assert main() == 1


def test_all_generations_failing_exits_nonzero(monkeypatch, tmp_path):
    rows = [_chunk(0, 10, "long enough chunk text for sampling here")]
    monkeypatch.setattr(generate_cases_module, "supabase", MagicMock(return_value=_fake_client(rows)))
    provider = _fake_provider(generate_side_effect=RuntimeError("boom"))
    monkeypatch.setattr(generate_cases_module.llm_manager, "get_provider", MagicMock(return_value=provider))
    out_path = tmp_path / "out.json"
    monkeypatch.setattr(
        "sys.argv",
        ["generate_cases.py", "--video-hash", "hash-1", "--user-id", "user-1", "--out", str(out_path)],
    )

    assert main() == 1
    assert out_path.read_text().strip() == "[]"
