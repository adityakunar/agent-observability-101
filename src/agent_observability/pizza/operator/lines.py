"""Format item variants and prices for both cart and order tickets."""

from agent_observability.pizza.domain import Cart


def item_lines(cart: Cart) -> list[dict[str, str]]:
    """Render business distinctions an operator needs to verify an edit."""
    return [
        {
            "title": f"{item.quantity} × {item.name}",
            "variant": " · ".join(
                part
                for part in (
                    item.size.value.title() if item.size else "",
                    f"{item.crust.value.title()} crust" if item.crust else "",
                )
                if part
            ),
            "unit_price": f"€{item.unit_price:.2f} each",
            "line_total": f"€{item.line_total:.2f}",
        }
        for item in cart.items
    ]
