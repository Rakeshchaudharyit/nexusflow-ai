import operator
from decimal import Decimal, InvalidOperation, localcontext
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.errors import ToolExecutionError
from app.agents.tools.base import ToolDefinition, ToolExecutionContext

Operation = Literal["add", "subtract", "multiply", "divide"]
# Bounded operands keep results exact at 28 significant digits.
Operand = Annotated[Decimal, Field(ge=-(10**12), le=10**12, allow_inf_nan=False)]

OPERATIONS = {
    "add": operator.add,
    "subtract": operator.sub,
    "multiply": operator.mul,
    "divide": operator.truediv,
}


class CalculatorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Operation
    left: Operand
    right: Operand


def format_decimal(value: Decimal) -> str:
    if value == value.to_integral_value():
        return str(value.quantize(Decimal(1)))
    return format(value.quantize(Decimal("1e-10")).normalize(), "f")


class CalculatorTool:
    """Applies one arithmetic operation to two bounded decimals. No expression evaluation."""

    definition = ToolDefinition(
        name="calculator",
        description="Add, subtract, multiply or divide two numbers.",
        input_model=CalculatorInput,
    )

    def execute(self, arguments: CalculatorInput, context: ToolExecutionContext) -> dict:
        if arguments.operation == "divide" and arguments.right == 0:
            raise ToolExecutionError("Division by zero is not allowed.", code="division_by_zero")
        with localcontext() as decimal_context:
            decimal_context.prec = 28
            try:
                result = OPERATIONS[arguments.operation](arguments.left, arguments.right)
            except InvalidOperation as error:
                raise ToolExecutionError("The calculation could not be performed.") from error
        return {
            "operation": arguments.operation,
            "left": format_decimal(arguments.left),
            "right": format_decimal(arguments.right),
            "result": format_decimal(result),
        }
