"""A focused part of the Prefab delivery desk."""

from prefab_ui.components import Card, Grid, Metric
from prefab_ui.rx import STATE


def metrics() -> None:
    with Grid(columns={"default": 1, "sm": 3}, gap=4):
        for label, value, description, colour in [
            (
                "On the counter",
                STATE.snapshot.active_cart_count,
                "Carts in progress",
                "butter",
            ),
            (
                "Out of the oven",
                STATE.snapshot.confirmed_order_count,
                "Confirmed orders",
                "tomato",
            ),
            (
                "From the house notes",
                STATE.snapshot.faq_lookup_count,
                "FAQ tool lookups",
                "sky",
            ),
        ]:
            with Card(css_class=f"comic-panel metric-panel {colour}"):
                Metric(label=label, value=str(value), description=description)
