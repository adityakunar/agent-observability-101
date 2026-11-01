"""A focused part of the Prefab delivery desk."""

from prefab_ui.components import (
    Badge,
    Card,
    CardContent,
    Column,
    Grid,
    Heading,
    Muted,
    Row,
    Tab,
    Text,
)

from agent_observability.pizza.menu_data import MENU


def menu_tab() -> None:
    with Tab("Menu"):
        Text("The house favourites", css_class="section-caption")
        with Grid(columns={"default": 1, "md": 2}, gap=4):
            for item in MENU:
                with Card(css_class="comic-panel menu-ticket"):
                    with CardContent():
                        with Column(gap=3):
                            with Row(gap=3, align="center", css_class="ticket-heading"):
                                Heading(item.name, level=3)
                                Badge(item.category.value, variant="outline")
                            Text(item.description)
                            Text(
                                " · ".join(
                                    f"{size.value.title()} €{price:.2f}"
                                    for size, price in item.prices.items()
                                )
                                if item.prices
                                else f"€{item.price:.2f}",
                                css_class="menu-price",
                            )
                            Muted("Allergens: " + (", ".join(item.allergens) or "None listed"))
