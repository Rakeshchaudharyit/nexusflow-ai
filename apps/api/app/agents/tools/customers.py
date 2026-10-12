from pydantic import BaseModel, ConfigDict, Field

from app.agents.tools.base import ToolDefinition, ToolExecutionContext

DATA_SOURCE = "demonstration"

# Fixed demonstration records. They are not CRM data and are identical for every organization.
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


def match_demo_customer(text: str) -> dict | None:
    lowered = text.casefold()
    for record in DEMO_CUSTOMERS:
        names = (record["company"].casefold(), *record["aliases"])
        if any(name in lowered for name in names):
            return record
    return None


class CustomerLookupInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=200)


class CustomerLookupTool:
    definition = ToolDefinition(
        name="customer_lookup",
        description="Find a customer in the built-in demonstration dataset.",
        input_model=CustomerLookupInput,
    )

    def execute(self, arguments: CustomerLookupInput, context: ToolExecutionContext) -> dict:
        record = match_demo_customer(arguments.query)
        if record is None:
            return {
                "query": arguments.query,
                "found": False,
                "data_source": DATA_SOURCE,
                "available": [item["company"] for item in DEMO_CUSTOMERS],
            }
        customer = {key: value for key, value in record.items() if key != "aliases"}
        return {
            "query": arguments.query,
            "found": True,
            "data_source": DATA_SOURCE,
            "customer": customer,
        }
