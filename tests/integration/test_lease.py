from crypto_trader.runtime.lease import LeaseManager


async def test_single_engine_acquires_renews_and_releases(database):
    mgr = LeaseManager(database.session_factory)
    lease = await mgr.acquire("exec", "engine_a", ttl_seconds=10)
    assert lease is not None
    assert await mgr.is_held("exec", lease.token) is True
    assert await mgr.renew("exec", lease.token, ttl_seconds=10) is True
    assert await mgr.release("exec", lease.token) is True
    assert await mgr.is_held("exec", lease.token) is False


async def test_dual_engine_lease_blocks_second_writer(database):
    mgr = LeaseManager(database.session_factory)
    first = await mgr.acquire("exec", "engine_a", ttl_seconds=30)
    assert first is not None
    second = await mgr.acquire("exec", "engine_b", ttl_seconds=30)
    assert second is None
    # first is still live
    assert await mgr.is_held("exec", first.token) is True


async def test_expired_lease_can_be_recovered(database):
    mgr = LeaseManager(database.session_factory)
    first = await mgr.acquire("exec", "engine_a", ttl_seconds=0.001)
    assert first is not None
    import asyncio
    await asyncio.sleep(0.01)
    second = await mgr.acquire("exec", "engine_b", ttl_seconds=30)
    assert second is not None
    assert second.owner_id == "engine_b"
    assert second.token != first.token


async def test_same_owner_extends_active_lease(database):
    mgr = LeaseManager(database.session_factory)
    first = await mgr.acquire("exec", "engine_a", ttl_seconds=30)
    extended = await mgr.acquire("exec", "engine_a", ttl_seconds=60)
    assert extended is not None
    assert extended.token == first.token
    assert extended.expires_at > first.expires_at
