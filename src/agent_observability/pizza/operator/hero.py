"""A focused part of the Prefab delivery desk."""

from prefab_ui.components import Badge, Column, Grid, Heading, Image, Text


def hero(illustration: str) -> None:
    with Grid(columns={"default": 1, "md": 2}, gap=6, css_class="comic-hero"):
        with Column(gap=4, css_class="hero-copy"):
            Text("LANTERN PIZZA / AMSTERDAM", css_class="eyebrow")
            Heading("Every customer order in view.", css_class="hero-title")
            Text(
                "Follow customer carts, incoming orders and the sources your assistant uses.",
                css_class="hero-description",
            )
            Text("From first request to confirmed order.", css_class="speech-bubble")
            Badge("Fictional restaurant · No real deliveries", variant="outline")
        Image(
            src=illustration,
            alt="A cook prepares pizza and hands it to a cyclist beside an Amsterdam canal.",
            width="100%",
            css_class="comic-illustration",
        )
