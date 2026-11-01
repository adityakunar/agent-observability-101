"""The header of the delivery desk: title and short description."""

from prefab_ui.components import Badge, Column, Heading, Text


def hero() -> None:
    with Column(gap=4, css_class="hero-copy"):
        Text("LANTERN PIZZA / AMSTERDAM", css_class="eyebrow")
        Heading("Every customer order in view.", css_class="hero-title")
        Text(
            "Follow customer carts, incoming orders and the sources your assistant uses.",
            css_class="hero-description",
        )
        Text("From first request to confirmed order.", css_class="speech-bubble")
        Badge("Fictional restaurant · No real deliveries", variant="outline")
