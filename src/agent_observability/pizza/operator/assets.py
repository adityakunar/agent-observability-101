"""The UI asset loader keeps resource paths out of rendering code."""

import base64

from agent_observability.utilities.resources import project_path


def stylesheet() -> str:
    return project_path("resources/prefab/operator.css").read_text()


def illustration() -> str:
    # A data URL keeps the desk one self-contained page that works offline.
    image = project_path("resources/prefab/lantern-strip.jpg").read_bytes()
    return "data:image/jpeg;base64," + base64.b64encode(image).decode()
