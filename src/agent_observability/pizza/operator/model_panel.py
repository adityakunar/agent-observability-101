"""A focused part of the Prefab delivery desk."""

from prefab_ui.components import Badge, Card, CardContent, Column, Grid, Metric, Muted, Row, Text
from prefab_ui.rx import STATE


def model_panel() -> None:
    server = STATE.model_server
    with Card(css_class="comic-panel"):
        with CardContent():
            with Column(gap=3):
                with Row(gap=3, align="center"):
                    Text("MODEL SERVER", css_class="eyebrow")
                    Badge(str(server.status), variant="outline")
                with Grid(columns={"default": 2, "sm": 4}, gap=3):
                    Metric(label="Generation", value=str(server.generation))
                    Metric(label="Prompt processing", value=str(server.prompt))
                    Metric(label="Requests served", value=str(server.requests))
                    Metric(label="MLX memory", value=str(server.memory))
                Muted("Reported by rapid-mlx for the whole server, not per conversation.")
