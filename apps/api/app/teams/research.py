"""Fixed demonstration research signals. No web access; not current external research."""

SOURCE = "NexusFlow demonstration research dataset"
NOTICE = "Synthetic demonstration data, not current external research."

DEMO_RESEARCH = {
    "Acme Corporation": (
        "Expanding enterprise operations",
        "Increasing automation investment",
        "Consolidating workflow tooling",
    ),
    "Northstar Labs": ("Scaling a new product line", "Hiring operations staff"),
    "Atlas Retail": ("Reducing discretionary spend", "Evaluating vendor consolidation"),
}


def research_signals(company: str) -> dict:
    signals = DEMO_RESEARCH.get(company)
    return {
        "company": company,
        "found": signals is not None,
        "signals": list(signals or ()),
        "source": SOURCE,
        "notice": NOTICE,
    }
