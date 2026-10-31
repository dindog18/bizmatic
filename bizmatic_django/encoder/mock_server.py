"""Synthetic stdio MCP fixture for isolated tests and local walkthroughs. No ERP access."""
import asyncio
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel


class ReceiptResult(BaseModel):
    saved: bool
    product_code: str
    quantity: int
    warehouse_id: int
    request_key: str

server = FastMCP("Bizmatic synthetic Encoder fixture")


@server.tool()
def encode_receipt(product_code: str, quantity: int, warehouse_id: int, request_key: str = "") -> ReceiptResult:
    """Return synthetic receipt data. request_key demonstrates an idempotency parameter."""
    if quantity < 0:
        raise ValueError("Quantity must be nonnegative")
    return ReceiptResult(saved=True, product_code=product_code, quantity=quantity, warehouse_id=warehouse_id, request_key=request_key)


@server.tool()
async def slow_operation() -> dict:
    """Synthetic timeout fixture."""
    await asyncio.sleep(10)
    return {"done": True}


if __name__ == "__main__":
    server.run(transport="stdio")
