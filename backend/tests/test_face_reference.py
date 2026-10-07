"""Unit tests for the outlier-robust face-tag reference embedding."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.chat import _robust_mean_embedding  # noqa: E402


def _near(base, seed, noise=0.05):
    rng = np.random.default_rng(seed)
    return base + rng.normal(0, noise, base.shape)


def _unit_axis(i, dim=32):
    v = np.zeros(dim)
    v[i] = 1.0
    return v


def test_outlier_is_dropped():
    base = _unit_axis(0)
    tags = [_near(base, s) for s in range(5)] + [_unit_axis(7)]
    ref, ignored = _robust_mean_embedding(tags, 0.5)
    assert ignored == 1
    assert float(ref @ base) > 0.99


def test_too_few_tags_keeps_everything():
    tags = [_unit_axis(0), _near(_unit_axis(0), 1), _unit_axis(7)]
    _, ignored = _robust_mean_embedding(tags, 0.5)
    assert ignored == 0


def test_never_drops_more_than_half():
    tags = [_unit_axis(i) for i in range(6)]
    _, ignored = _robust_mean_embedding(tags, 0.99)
    assert ignored == 0


def test_empty_returns_none():
    assert _robust_mean_embedding([], 0.5) == (None, 0)
