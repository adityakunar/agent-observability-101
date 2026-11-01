"""A focused part of the Prefab delivery desk."""

from prefab_ui.components import (
    Badge,
    Card,
    CardContent,
    Column,
    ForEach,
    Heading,
    If,
    Muted,
    Row,
    Tab,
    Text,
)
from prefab_ui.rx import STATE


def carts_tab() -> None:
    with Tab("Active Carts"):
        with If(STATE.snapshot.active_cart_count == 0):
            with Card(css_class="comic-panel empty-panel"):
                Heading("Nothing on the counter yet.", level=3)
                Text(
                    "Send a customer request in the chat. Their cart appears here as items are added."
                )
        with ForEach("snapshot.active_carts") as cart:
            with Card(css_class="comic-panel ticket"):
                with CardContent():
                    with Column(gap=4):
                        with Row(gap=3, align="center", css_class="ticket-heading"):
                            Heading("Order in progress", level=3)
                            Badge(str(cart.check), variant=str(cart.variant))
                        with ForEach(cart.lines) as line:
                            with Row(gap=3, css_class="cart-line"):
                                with Column(gap=1):
                                    Text(str(line.title), css_class="order-items")
                                    with If(line.variant):
                                        Muted(str(line.variant))
                                with Column(gap=1, css_class="line-prices"):
                                    Text(str(line.line_total))
                                    Muted(str(line.unit_price))
                        Text(str(cart.address), css_class="address-line")
                        with Row(gap=3, css_class="ticket-breakdown"):
                            Text(f"Food subtotal {cart.subtotal}")
                            Text(f"Deal saving {cart.discount}")
                        with Row(gap=3, css_class="ticket-totals"):
                            Text("Food total", css_class="eyebrow")
                            Text(str(cart.total), css_class="price")
                            Badge(str(cart.deal), variant="outline")
                        with If(cart.delivery_ready):
                            with Row(gap=3, css_class="ticket-breakdown"):
                                Text(f"Delivery {cart.delivery_fee}")
                                Text(
                                    f"Total with delivery {cart.grand_total}",
                                    css_class="quote-total",
                                )
                            Muted("Review the quote with the customer before confirming.")
                        Muted(f"Cart {cart.session_id}")
