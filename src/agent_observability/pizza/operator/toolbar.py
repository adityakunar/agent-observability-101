"""A focused part of the Prefab delivery desk."""

from prefab_ui.actions import Fetch
from prefab_ui.components import Alert, AlertDescription, Badge, Button, If, Row, Text
from prefab_ui.rx import STATE


def toolbar(refresh: Fetch) -> None:
    with Row(gap=3, align="center", css_class="desk-toolbar"):
        Text("THE DELIVERY DESK", css_class="eyebrow")
        with If("!refresh_error"):
            Text(f"Last checked {STATE.snapshot.checked_at}", css_class="live-note")
        with If(STATE.refresh_error):
            Badge("Connection lost · showing last received values", variant="warning")
        Button("Refresh now", variant="outline", on_click=refresh)

    with If(STATE.refresh_error):
        with Alert(variant="warning"):
            AlertDescription(
                "Could not refresh. These are the last received values; check the server and try again."
            )
