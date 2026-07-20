"""
Unit tests for database caching in chat_store.py
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch

# Import the cache and functions from chat_store
from db.chat_store import (
    LRUCache,
    clear_caches,
    _session_owner_cache,
    _session_messages_cache,
    _officer_sessions_cache,
    get_session_owner,
    create_session,
    update_session_timestamp,
    get_sessions_for_officer,
    verify_session_owner,
    save_message_pair,
    get_messages_for_session,
)


class TestLRUCache:
    """Tests for the LRUCache class itself"""
    
    def test_cache_put_and_get(self):
        cache = LRUCache(capacity=3, ttl_seconds=60)
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"
    
    def test_cache_miss(self):
        cache = LRUCache(capacity=3, ttl_seconds=60)
        assert cache.get("nonexistent") is None
    
    def test_cache_eviction_at_capacity(self):
        cache = LRUCache(capacity=2, ttl_seconds=60)
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")  # Should evict key1
        
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"
    
    def test_cache_lru_order(self):
        cache = LRUCache(capacity=2, ttl_seconds=60)
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        
        # Access key1 to make it most recently used
        cache.get("key1")
        
        # Add key3, should evict key2 (least recently used)
        cache.put("key3", "value3")
        
        assert cache.get("key1") == "value1"
        assert cache.get("key2") is None
        assert cache.get("key3") == "value3"
    
    def test_cache_ttl_expiration(self):
        import time
        cache = LRUCache(capacity=3, ttl_seconds=0.1)
        cache.put("key1", "value1")
        
        # Should be in cache immediately
        assert cache.get("key1") == "value1"
        
        # Wait for TTL to expire
        time.sleep(0.15)
        
        # Should be expired now
        assert cache.get("key1") is None
    
    def test_cache_delete(self):
        cache = LRUCache(capacity=3, ttl_seconds=60)
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        
        cache.delete("key1")
        
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"
    
    def test_cache_clear(self):
        cache = LRUCache(capacity=3, ttl_seconds=60)
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        
        cache.clear()
        
        assert cache.get("key1") is None
        assert cache.get("key2") is None
    
    def test_cache_update_existing_key(self):
        cache = LRUCache(capacity=3, ttl_seconds=60)
        cache.put("key1", "value1")
        cache.put("key1", "value2")  # Update
        
        assert cache.get("key1") == "value2"


class TestCacheFunctions:
    """Tests for cache-aware database functions"""
    
    @pytest.mark.asyncio
    async def test_get_session_owner_cache_hit(self):
        # Prime the cache
        _session_owner_cache.put("sess-123", 456)
        
        # Should return from cache without hitting DB
        with patch("db.chat_store.execute_query") as mock_query:
            result = await get_session_owner("sess-123")
            assert result == 456
            mock_query.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_get_session_owner_cache_miss(self):
        clear_caches()
        
        # Mock DB query
        with patch("db.chat_store.execute_query") as mock_query:
            mock_query.return_value = [{"officer_id": 789}]
            
            result = await get_session_owner("sess-456")
            
            assert result == 789
            mock_query.assert_called_once()
            
            # Should now be in cache
            assert _session_owner_cache.get("sess-456") == 789
    
    @pytest.mark.asyncio
    async def test_get_session_owner_not_found(self):
        clear_caches()
        
        with patch("db.chat_store.execute_query") as mock_query:
            mock_query.return_value = []
            
            result = await get_session_owner("nonexistent")
            
            assert result is None
            # Should not cache None results
            assert _session_owner_cache.get("nonexistent") is None
    
    @pytest.mark.asyncio
    async def test_create_session_caches_owner(self):
        clear_caches()
        
        with patch("db.chat_store.execute_write") as mock_write:
            mock_write.return_value = None
            
            await create_session("sess-new", 123, "Test Session")
            
            # Should cache the ownership
            assert _session_owner_cache.get("sess-new") == 123
    
    @pytest.mark.asyncio
    async def test_create_session_invalidates_officer_sessions(self):
        clear_caches()
        
        # Prime officer sessions cache
        _officer_sessions_cache.put((123, 30), [{"session_id": "old"}])
        
        with patch("db.chat_store.execute_write") as mock_write:
            mock_write.return_value = None
            
            await create_session("sess-new", 123, "Test Session")
            
            # Officer's sessions list should be invalidated
            assert _officer_sessions_cache.get((123, 30)) is None
    
    @pytest.mark.asyncio
    async def test_update_session_timestamp_invalidates_officer_sessions(self):
        clear_caches()
        
        # Prime caches
        _session_owner_cache.put("sess-123", 456)
        _officer_sessions_cache.put((456, 30), [{"session_id": "sess-123"}])
        
        with patch("db.chat_store.execute_write") as mock_write:
            mock_write.return_value = None
            
            await update_session_timestamp("sess-123")
            
            # Officer's sessions list should be invalidated
            assert _officer_sessions_cache.get((456, 30)) is None
    
    @pytest.mark.asyncio
    async def test_get_sessions_for_officer_cache_hit(self):
        clear_caches()
        
        # Prime cache
        expected = [{"session_id": "sess-1", "title": "Test"}]
        _officer_sessions_cache.put((123, 30), expected)
        
        with patch("db.chat_store.execute_query") as mock_query:
            result = await get_sessions_for_officer(123, 30)
            
            assert result == expected
            mock_query.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_get_sessions_for_officer_cache_miss(self):
        clear_caches()
        
        with patch("db.chat_store.execute_query") as mock_query:
            mock_query.return_value = [
                {
                    "session_id": "sess-1",
                    "title": "Test",
                    "created_at": None,
                    "updated_at": None,
                    "message_count": 5
                }
            ]
            
            result = await get_sessions_for_officer(123, 30)
            
            assert len(result) == 1
            assert result[0]["session_id"] == "sess-1"
            mock_query.assert_called_once()
            
            # Should now be cached
            cached = _officer_sessions_cache.get((123, 30))
            assert cached is not None
            assert len(cached) == 1
    
    @pytest.mark.asyncio
    async def test_verify_session_owner_uses_cache(self):
        clear_caches()
        
        # Prime cache
        _session_owner_cache.put("sess-123", 456)
        
        with patch("db.chat_store.execute_query") as mock_query:
            result = await verify_session_owner("sess-123", 456)
            
            assert result is True
            mock_query.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_verify_session_owner_wrong_owner(self):
        clear_caches()
        
        # Prime cache with different owner
        _session_owner_cache.put("sess-123", 456)
        
        result = await verify_session_owner("sess-123", 789)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_save_message_pair_invalidates_messages_cache(self):
        clear_caches()
        
        # Prime messages cache
        _session_messages_cache.put("sess-123", [{"message_id": 1, "content": "old"}])
        
        with patch("db.chat_store.execute_write") as mock_write:
            mock_write.return_value = 42  # message_id
            
            await save_message_pair(
                session_id="sess-123",
                question="Test question",
                answer_text="Test answer",
                sql_generated="",
                has_table=False,
                has_media=False,
                graph_available=False,
                table_data=[],
                media_attachments=[]
            )
            
            # Messages cache should be invalidated
            assert _session_messages_cache.get("sess-123") is None
    
    @pytest.mark.asyncio
    async def test_get_messages_for_session_cache_hit(self):
        clear_caches()
        
        # Prime cache
        expected = [{"message_id": 1, "role": "user", "content": "Hello"}]
        _session_messages_cache.put("sess-123", expected)
        
        with patch("db.chat_store.execute_query") as mock_query:
            result = await get_messages_for_session("sess-123")
            
            assert result == expected
            mock_query.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_get_messages_for_session_cache_miss(self):
        clear_caches()
        
        with patch("db.chat_store.execute_query") as mock_query:
            mock_query.return_value = [
                {
                    "message_id": 1,
                    "role": "user",
                    "content": "Hello",
                    "sql_generated": "",
                    "has_table": False,
                    "has_media": False,
                    "graph_available": False,
                    "table_data_json": None,
                    "follow_ups_json": None,
                    "created_at": None
                }
            ]
            
            result = await get_messages_for_session("sess-123")
            
            assert len(result) == 1
            assert result[0]["content"] == "Hello"
            mock_query.assert_called_once()
            
            # Should now be cached
            cached = _session_messages_cache.get("sess-123")
            assert cached is not None
            assert len(cached) == 1


class TestClearCaches:
    """Test the clear_caches function"""
    
    def test_clear_caches_clears_all(self):
        # Prime all caches
        _session_owner_cache.put("sess-1", 123)
        _session_messages_cache.put("sess-1", [{"msg": "test"}])
        _officer_sessions_cache.put((123, 30), [{"session": "test"}])
        
        clear_caches()
        
        # All should be empty
        assert _session_owner_cache.get("sess-1") is None
        assert _session_messages_cache.get("sess-1") is None
        assert _officer_sessions_cache.get((123, 30)) is None
