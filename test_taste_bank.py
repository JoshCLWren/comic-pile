#!/usr/bin/env python3

"""Test script to verify Taste Bank signals functionality."""

import asyncio
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.models import Base, TasteBankSignal

async def test_taste_bank_signals():
    # Create engine and session
    engine = create_async_engine("postgresql+asyncpg://comicpile:comicpile_password@localhost:5435/comicpile", echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    # Create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Create a Taste Bank signal directly
    async with async_session() as session:
        # Create signal
        signal = TasteBankSignal(
            user_id=1,  # Assume user ID 1 exists
            signal_type="recommendation",
            verdict="confirmed",
            evidence="test evidence",
            recorded_at=datetime.now()
        )
        session.add(signal)
        await session.commit()
        await session.refresh(signal)
        
        print(f"Created signal with ID: {signal.id}")
        print(f"Signal type: {signal.signal_type}")
        print(f"Verdict: {signal.verdict}")
        print(f"Evidence: {signal.evidence}")
        print(f"Recorded at: {signal.recorded_at}")
        
        # Test idempotent repeated responses
        signal.verdict = "sometimes"
        signal.evidence = "updated evidence"
        signal.updated_at = datetime.now()
        await session.commit()
        await session.refresh(signal)
        
        print(f"\nUpdated signal:")
        print(f"Verdict: {signal.verdict}")
        print(f"Evidence: {signal.evidence}")

async def main():
    await test_taste_bank_signals()

if __name__ == "__main__":
    asyncio.run(main())