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


def orders_tab() -> None:
    with Tab("Orders"):
        with If(STATE.snapshot.order_count == 0):
            with Card(css_class="comic-panel empty-panel"):
                Heading("The oven is waiting.", level=3)
                Text("Confirmed orders appear here with their delivery address and full total.")
        with ForEach("snapshot.orders") as order:
            with Card(css_class="comic-panel ticket"):
                with CardContent():
                    with Column(gap=4):
                        with Row(gap=3, align="center", css_class="ticket-heading"):
                            Heading(f"Order {order.order_id}", level=3)
                            Badge(str(order.status), variant=str(order.variant))
                            Text(str(order.total), css_class="price")
                        Muted("Order total including delivery")
                        with ForEach(order.lines) as line:
                            with Row(gap=3, css_class="cart-line"):
                                with Column(gap=1):
                                    Text(str(line.title), css_class="order-items")
                                    with If(line.variant):
                                        Muted(str(line.variant))
                                with Column(gap=1, css_class="line-prices"):
                                    Text(str(line.line_total))
                                    Muted(str(line.unit_price))
                        Text(str(order.address), css_class="address-line")
                        with Row(gap=3, css_class="ticket-breakdown"):
                            Text(f"Food subtotal {order.subtotal}")
                            Text(f"Deal saving {order.discount}")
                        with Row(gap=3, css_class="ticket-totals"):
                            Text(f"Food total {order.food_total}")
                            Text(f"Delivery {order.delivery_fee}")
                            Badge(str(order.delivery_note), variant="outline")
                        Muted(f"From cart {order.session_id}")
