"""Compose the operator UI from focused sections and shared state."""

from prefab_ui.actions import Fetch, SetInterval, SetState
from prefab_ui.app import PrefabApp
from prefab_ui.components import Column, Tabs, Text
from prefab_ui.rx import RESULT

from .assets import illustration, stylesheet
from .carts_tab import carts_tab
from .hero import hero
from .menu_tab import menu_tab
from .metrics import metrics
from .model_panel import model_panel
from .model_server import UNAVAILABLE
from .orders_tab import orders_tab
from .snapshot import get_operator_snapshot
from .sources_tab import sources_tab
from .toolbar import toolbar


def pizza_operator() -> PrefabApp:
    """Follow customer carts, incoming orders and the assistant's FAQ sources."""
    refresh = Fetch.get(
        "/desk/snapshot",
        on_success=[SetState("snapshot", RESULT), SetState("refresh_error", False)],
        on_error=SetState("refresh_error", True),
    )
    refresh_model = Fetch.get("/desk/model-server", on_success=SetState("model_server", RESULT))
    with PrefabApp(
        title="Lantern Pizza · The delivery desk",
        state={
            "snapshot": get_operator_snapshot(),
            "refresh_error": False,
            "source_body": "",
            "source_error": False,
            "model_server": {**UNAVAILABLE, "status": "Checking…"},
        },
        css_class="lantern",
        css=[stylesheet()],
        mode="light",
        on_mount=SetInterval(duration=3000, on_tick=[refresh, refresh_model]),
    ) as ui:
        with Column(gap=6, css_class="delivery-desk"):
            hero(illustration())
            metrics()
            model_panel()
            toolbar(refresh)
            with Tabs(css_class="comic-tabs"):
                carts_tab()
                orders_tab()
                sources_tab()
                menu_tab()
            Text(
                "Amsterdam 1012 · €1.99 delivery · 30–40 minutes estimated", css_class="desk-footer"
            )
    return ui
