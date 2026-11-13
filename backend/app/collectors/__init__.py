"""Collectors: one adapter per source. Only services may call these."""

from app.collectors.baostock_collector import SOURCE_KEY, StockFact, fetch_stock_facts

__all__ = ["SOURCE_KEY", "StockFact", "fetch_stock_facts"]
