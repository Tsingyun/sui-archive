# SUI Archive — Automation Pipeline
"""
Automated Bilibili dynamic archiving system.

Modules:
    config          — Centralized configuration
    bilibili_api    — Bilibili API client with retry
    quick_check     — Lightweight update detection
    fetcher         — Incremental post + image fetcher
    db_writer       — SQLite incremental writer
    orchestrator    — Pipeline coordinator
"""
