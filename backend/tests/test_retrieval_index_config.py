from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from services import transcript_embedding_service as module
from services.transcript_embedding_service import TranscriptEmbeddingService, prepare_embedding_query


class _Encoder:
    def __init__(self):
        self.texts = []

    def encode(self, texts, **_kwargs):
        self.texts.extend(texts)
        return np.array([[1.0] + [0.0] * 383 for _ in texts])


class _Store:
    def __init__(self):
        self.rows = []
        self.calls = []
        self.reject_replace = False

    def table(self, name):
        self.table_name = name
        self.filters = {}
        return self

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        data = [row for row in self.rows if row['table'] == self.table_name
                and all(row.get(key) == value for key, value in self.filters.items())]
        return SimpleNamespace(data=deepcopy(data), count=len(data))

    def rpc(self, name, params):
        self.calls.append((name, deepcopy(params)))
        table = 'transcript_embeddings_v2' if 'transcript' in name else 'audio_event_embeddings_v2'
        scope = {
            'user_id': params['p_user_id'],
            'video_hash': params['target_video_hash'],
            'embedding_model': params['p_embedding_model'],
        }
        if 'transcript' in name:
            scope['index_config'] = params['target_index_config']
        matching = lambda row: row['table'] == table and all(row.get(key) == value for key, value in scope.items())

        def execute():
            if name.startswith('replace_'):
                if self.reject_replace:
                    raise ValueError('database rejected invalid replacement')
                self.rows = [row for row in self.rows if not matching(row)]
                self.rows += [{**deepcopy(row), **scope, 'table': table} for row in params['p_rows']]
                return SimpleNamespace(data=len(params['p_rows']))
            return SimpleNamespace(data=[{**row, 'similarity': 1.0} for row in self.rows if matching(row)])

        return SimpleNamespace(execute=execute)


@pytest.fixture
def indexed(monkeypatch):
    store = _Store()
    encoder = _Encoder()
    service = TranscriptEmbeddingService()
    service._embedding_model = encoder
    monkeypatch.setattr(module, 'supabase', lambda: store)
    monkeypatch.setattr(module.settings, 'TEXT_EMBEDDING_MODEL', 'BAAI/bge-small-en-v1.5')
    return service, store, encoder


def _segments(count):
    return [{'id': str(i), 'start': float(i), 'end': float(i + 1), 'text': f'line {i}',
             'audio_events': [{'event_type': 'laughter', 'confidence': 0.9}]} for i in range(count)]


def test_query_instruction_is_only_used_for_bge():
    assert prepare_embedding_query('hello', 'BAAI/bge-small-en-v1.5').endswith(': hello')
    assert prepare_embedding_query('hello', 'all-MiniLM-L6-v2') == 'hello'


def test_indexes_are_isolated_by_owner_model_and_chunk_configuration(indexed, monkeypatch):
    service, store, encoder = indexed
    segments = _segments(10)
    assert service.index_transcript_chunks('video', segments, 'owner', chunk_size=2, index_config='chunk_size_2') == 5
    assert service.index_transcript_chunks('video', segments, 'owner', chunk_size=5, index_config='chunk_size_5') == 2
    assert service.index_transcript_chunks('video', segments, 'other', chunk_size=2, index_config='chunk_size_2') == 5
    monkeypatch.setattr(module.settings, 'TEXT_EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
    assert service.index_transcript_chunks('video', segments, 'owner', chunk_size=2, index_config='chunk_size_2') == 5
    monkeypatch.setattr(module.settings, 'TEXT_EMBEDDING_MODEL', 'BAAI/bge-small-en-v1.5')

    results = service.search_transcript_chunks('video', 'question', 'owner', index_config='chunk_size_5')
    assert len(results) == 2
    assert all(result['metadata']['segment_count'] == 5 for result in results)
    assert not service.transcript_chunks_exist('different', 'owner')
    assert service.transcript_chunks_exist('video', 'owner', index_config='chunk_size_2')
    assert not service.transcript_chunks_exist('video', 'owner')
    assert encoder.texts[-1].endswith(': question')
    assert all(not text.startswith('Represent this sentence') for text in encoder.texts[:-1])


def test_shorter_rebuild_replaces_only_the_selected_index_and_removes_tail(indexed):
    service, store, _ = indexed
    service.index_transcript_chunks('video', _segments(12), 'owner')
    service.index_transcript_chunks('video', _segments(12), 'other')
    assert service.index_transcript_chunks('video', _segments(3), 'owner', force_reindex=True) == 1
    assert len(service.search_transcript_chunks('video', 'question', 'owner')) == 1
    assert len(service.search_transcript_chunks('video', 'question', 'other')) == 4
    assert service.index_transcript_chunks('video', [], 'owner', force_reindex=True) == 0
    assert not service.transcript_chunks_exist('video', 'owner')


def test_failed_atomic_replacement_propagates_error_without_deleting_existing_rows(indexed):
    service, store, _ = indexed
    service.index_transcript_chunks('video', _segments(3), 'owner')
    before = deepcopy(store.rows)
    store.reject_replace = True
    with pytest.raises(ValueError, match='invalid replacement'):
        service.index_transcript_chunks('video', _segments(6), 'owner', force_reindex=True)
    assert store.rows == before


def test_audio_rebuild_is_model_scoped_and_clears_removed_events(indexed, monkeypatch):
    service, store, _ = indexed
    service.index_audio_events('video', _segments(3), 'owner')
    monkeypatch.setattr(module.settings, 'TEXT_EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
    assert not service.audio_events_exist('video', 'owner')
    service.index_audio_events('video', _segments(2), 'owner')
    monkeypatch.setattr(module.settings, 'TEXT_EMBEDDING_MODEL', 'BAAI/bge-small-en-v1.5')
    assert service.index_audio_events('video', _segments(1), 'owner', force_reindex=True) == 1
    assert len(service.search_audio_events('video', 'laughter', 'owner')) == 1
    service.index_audio_events('video', [], 'owner', force_reindex=True)
    assert not service.audio_events_exist('video', 'owner')
    monkeypatch.setattr(module.settings, 'TEXT_EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
    assert len(service.search_audio_events('video', 'laughter', 'owner')) == 2


def test_mismatched_chunk_name_is_rejected_before_writing(indexed):
    service, store, _ = indexed
    with pytest.raises(ValueError, match='must match'):
        service.index_transcript_chunks('video', _segments(6), 'owner', chunk_size=2)
    assert store.calls == []
