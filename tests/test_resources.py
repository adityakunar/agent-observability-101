"""Bundled resources load independently of the current directory."""

from agent_observability.pizza.operator.app import pizza_operator


def test_menu_and_prefab_assets_work_from_another_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    view = pizza_operator().to_json()
    assert "Every customer order in view." in str(view["view"])
    assert view["css"]
