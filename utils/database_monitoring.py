"""Monitoring utilities for database operations"""

import time
from typing import Dict, Any, Optional
from threading import Lock
from utils.logger import logger


class QueryMonitor:
    _instance = None
    _lock = Lock()

    def __init__(self):
        self.active_queries: Dict[str, Dict[str, Any]] = {}
        self.query_history: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = QueryMonitor()
        return cls._instance

    def start_query(
        self,
        query_id: str,
        query: str,
        params: Optional[tuple] = None,
        context: Optional[Dict] = None,
    ):
        """Start monitoring a query"""
        self.active_queries[query_id] = {
            "start_time": time.time(),
            "query": query[:1000],  # Truncate long queries
            "params": params,
            "context": context,
        }

    def end_query(
        self, query_id: str, status: str = "completed", error: Optional[str] = None
    ):
        """End monitoring a query"""
        if query_id in self.active_queries:
            query_info = self.active_queries.pop(query_id)
            duration = time.time() - query_info["start_time"]

            # Log slow queries
            if duration > 5:  # Threshold for slow queries
                logger.warning(
                    f"Slow query detected (took {duration:.2f}s):\n"
                    f"Query: {query_info['query']}\n"
                    f"Params: {query_info['params']}\n"
                    f"Context: {query_info['context']}"
                )

            # Store in history
            self.query_history[query_id] = {
                **query_info,
                "end_time": time.time(),
                "duration": duration,
                "status": status,
                "error": error,
            }

            # Keep history size manageable
            if len(self.query_history) > 1000:
                oldest_key = min(
                    self.query_history.keys(),
                    key=lambda k: self.query_history[k]["start_time"],
                )
                self.query_history.pop(oldest_key)

    def check_stuck_queries(self, timeout: int = 30) -> Dict[str, Dict[str, Any]]:
        """Check for queries that might be stuck"""
        current_time = time.time()
        stuck_queries = {}

        for query_id, info in self.active_queries.items():
            duration = current_time - info["start_time"]
            if duration > timeout:
                stuck_queries[query_id] = {**info, "duration": duration}
                logger.error(
                    f"Potentially stuck query detected (running for {duration:.2f}s):\n"
                    f"Query: {info['query']}\n"
                    f"Params: {info['params']}\n"
                    f"Context: {info['context']}"
                )

        return stuck_queries

    def get_query_stats(self) -> Dict[str, Any]:
        """Get statistics about query execution"""
        return {
            "active_queries": len(self.active_queries),
            "total_queries_tracked": len(self.query_history),
            "slow_queries": sum(
                1 for q in self.query_history.values() if q["duration"] > 5
            ),
            "failed_queries": sum(
                1 for q in self.query_history.values() if q["status"] == "error"
            ),
            "avg_duration": sum(q["duration"] for q in self.query_history.values())
            / len(self.query_history)
            if self.query_history
            else 0,
        }
