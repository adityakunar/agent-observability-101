"""The UI asset loader keeps resource paths out of rendering code."""

from agent_observability.utilities.resources import project_path


def stylesheet() -> str:
    return project_path("resources/prefab/operator.css").read_text()
