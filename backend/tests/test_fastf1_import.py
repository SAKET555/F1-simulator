"""Baseline test – ensure fastf1 imports and cache dir can be created."""
import importlib
import os
from pathlib import Path


def test_fastf1_importable():
    mod = importlib.import_module("fastf1")
    assert mod is not None


def test_cache_dir_creation(tmp_path):
    import fastf1
    cache_dir = tmp_path / "f1cache"
    cache_dir.mkdir()
    fastf1.Cache.enable_cache(str(cache_dir))
    assert cache_dir.exists()
