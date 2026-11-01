"""Validate the editable menu once, then share its records with tools and UI."""

import json

from agent_observability.utilities.resources import project_path

from .domain import Deal, MenuItem

catalog = json.loads(project_path("resources/menu.json").read_text())
MENU = [MenuItem.model_validate(item) for item in catalog["menu"]]
DEALS = [Deal.model_validate(deal) for deal in catalog["deals"]]
MENU_BY_ID = {item.id: item for item in MENU}
DEALS_BY_ID = {deal.id: deal for deal in DEALS}
