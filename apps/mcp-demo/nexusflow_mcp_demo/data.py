"""Fixed demonstration records. Not CRM data.

These match the API's internal demo dataset (apps/api/app/agents/tools/customers.py); the API
test suite fails if the two drift apart.
"""

SOURCE = "NexusFlow demo MCP data"

DEMO_CUSTOMERS = (
    {
        "company": "Acme Corporation",
        "aliases": ("acme",),
        "segment": "Enterprise",
        "status": "active",
        "account_owner": "Maya Chen",
        "region": "North America",
    },
    {
        "company": "Northstar Labs",
        "aliases": ("northstar",),
        "segment": "Mid-Market",
        "status": "onboarding",
        "account_owner": "Daniel Okafor",
        "region": "Europe",
    },
    {
        "company": "Atlas Retail",
        "aliases": ("atlas",),
        "segment": "SMB",
        "status": "at_risk",
        "account_owner": "Priya Nair",
        "region": "Asia Pacific",
    },
)


def find_customer(company: str) -> dict | None:
    lowered = company.casefold()
    for record in DEMO_CUSTOMERS:
        if any(name in lowered for name in (record["company"].casefold(), *record["aliases"])):
            return record
    return None
