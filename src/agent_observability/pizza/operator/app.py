"""Compose the delivery desk from focused sections and shared state."""

from prefab_ui.actions import Fetch, SetInterval, SetState
from prefab_ui.app import PrefabApp
from prefab_ui.components import Column, Tabs, Text
from prefab_ui.rx import RESULT

from agent_observability.pizza.state import DELIVERY_FEE, DELIVERY_MINUTES

from .assets import illustration, stylesheet
from .carts_tab import carts_tab
from .hero import hero
from .metrics import metrics
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
    with PrefabApp(
        title="Lantern Pizza · The delivery desk",
        state={
            "snapshot": get_operator_snapshot(),
            "refresh_error": False,
            "source_body": "",
            "source_error": False,
        },
        css_class="lantern",
        css=[stylesheet()],
        mode="light",
        on_mount=SetInterval(duration=3000, on_tick=refresh),
    ) as ui:
        with Column(gap=6, css_class="delivery-desk"):
            hero(illustration())
            metrics()
            toolbar(refresh)
            with Tabs(css_class="comic-tabs"):
                carts_tab()
                orders_tab()
                sources_tab()
            Text(
                f"Amsterdam 1012 · €{DELIVERY_FEE:.2f} delivery · {DELIVERY_MINUTES} minutes estimated",
                css_class="desk-footer",
            )
    return ui
