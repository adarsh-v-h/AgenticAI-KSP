"""Tests for media_resolver — Step 5 Media Viewer feature."""
import asyncio

import pytest

from pipeline.media_resolver import collect_case_master_ids, resolve_media


def _run_async(coro):
    """Helper to run async code in tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_collect_case_master_ids_basic():
    """Test basic CaseMasterID extraction from results."""
    results = [
        {"case_master_id": 1, "name": "case1"},
        {"CaseMasterID": 2, "name": "case2"},
        {"case_master_id": 1, "name": "case1_dup"},
    ]
    assert collect_case_master_ids(results) == [1, 2]


def test_collect_case_master_ids_no_column():
    """Test when results have no CaseMasterID column."""
    results = [{"name": "case1"}, {"name": "case2"}]
    assert collect_case_master_ids(results) == []


def test_collect_case_master_ids_invalid_values():
    """Test filtering out invalid values."""
    results = [
        {"case_master_id": None},
        {"case_master_id": "not_a_number"},
        {"case_master_id": 1.5},
        {"case_master_id": 3},
    ]
    assert collect_case_master_ids(results) == [1, 3]


def test_collect_case_master_ids_empty():
    """Test empty results list."""
    assert collect_case_master_ids([]) == []


def test_resolve_media_empty_results():
    """Test resolve_media with empty results."""
    result = _run_async(resolve_media([]))
    assert result == []


def test_resolve_media_no_case_master_ids():
    """Test resolve_media when results have no case_master_id."""
    results = [{"name": "case1"}]
    result = _run_async(resolve_media(results))
    assert result == []


def test_resolve_media_returns_unavailable_url(monkeypatch):
    """Test that resolve_media returns /api/media/unavailable URL format."""
    mock_rows = [
        {
            "media_id": 1,
            "case_master_id": 100,
            "media_type": "image",
            "file_name": "photo.jpg",
            "stratus_folder_id": "folder1",
            "stratus_file_id": "file123",
            "description": "Crime scene photo",
        }
    ]

    async def mock_execute_query(sql, params):
        return mock_rows

    monkeypatch.setattr("pipeline.media_resolver.execute_query", mock_execute_query)

    results = [{"case_master_id": 100}]
    media = _run_async(resolve_media(results))

    assert len(media) == 1
    assert media[0]["media_type"] == "image"
    assert media[0]["url"].startswith("https://picsum.photos/seed/file123/680/450")
    assert media[0]["description"] == "Crime scene photo"
    assert media[0]["case_master_id"] == 100


def test_resolve_media_multiple_files(monkeypatch):
    """Test resolve_media with multiple media files for multiple CaseMasterIDs."""
    mock_rows = [
        {
            "media_id": 1,
            "case_master_id": 100,
            "media_type": "image",
            "file_name": "photo1.jpg",
            "stratus_folder_id": "folder1",
            "stratus_file_id": "file1",
            "description": "Photo 1",
        },
        {
            "media_id": 2,
            "case_master_id": 100,
            "media_type": "video",
            "file_name": "video1.mp4",
            "stratus_folder_id": "folder1",
            "stratus_file_id": "file2",
            "description": "Video 1",
        },
        {
            "media_id": 3,
            "case_master_id": 200,
            "media_type": "audio",
            "file_name": "audio1.mp3",
            "stratus_folder_id": "folder2",
            "stratus_file_id": "file3",
            "description": "",
        },
    ]

    async def mock_execute_query(sql, params):
        return mock_rows

    monkeypatch.setattr("pipeline.media_resolver.execute_query", mock_execute_query)

    results = [{"case_master_id": 100}, {"case_master_id": 200}]
    media = _run_async(resolve_media(results))

    assert len(media) == 3
    urls = [m["url"] for m in media]
    assert any(u.startswith("https://picsum.photos/seed/file1/680/450") for u in urls)
    assert any(u.startswith("https://samplelib.com/lib/preview/mp4/") for u in urls)
    assert any(u.startswith("https://www.soundhelix.com/examples/mp3/") for u in urls)


def test_resolve_media_falls_back_on_unknown_type(monkeypatch):
    """Test resolve_media falls back to unavailable URL for unsupported media types."""
    mock_rows = [
        {
            "media_id": 4,
            "case_master_id": 300,
            "media_type": "document",
            "file_name": "report.pdf",
            "stratus_folder_id": "folder3",
            "stratus_file_id": "file999",
            "description": "Investigation report",
        }
    ]

    async def mock_execute_query(sql, params):
        return mock_rows

    monkeypatch.setattr("pipeline.media_resolver.execute_query", mock_execute_query)

    results = [{"case_master_id": 300}]
    media = _run_async(resolve_media(results))

    assert len(media) == 1
    assert media[0]["url"] == "/api/media/unavailable?file=file999"
