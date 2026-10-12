"""Observability (M10): run traces and spans.

Tracing is observational and best-effort: spans are collected in memory with monotonic
timing and written after the business transaction commits, so a tracing failure can never
change or fail a run.
"""
