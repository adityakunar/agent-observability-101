"""A focused part of the Prefab delivery desk."""

from prefab_ui.actions import Fetch, SetState
from prefab_ui.components import (
    Alert,
    AlertDescription,
    Badge,
    Button,
    Card,
    CardContent,
    Column,
    Dialog,
    ForEach,
    If,
    Markdown,
    Muted,
    Row,
    Tab,
    Text,
)
from prefab_ui.rx import RESULT, STATE


def sources_tab() -> None:
    with Tab("FAQ Sources"):
        Text("What came back from the house notes", css_class="section-caption")
        Muted(
            "Retrieved passages help you check the answer; a lookup alone does not prove the reply is correct."
        )
        with If(STATE.snapshot.faq_lookup_count == 0):
            with Card(css_class="comic-panel empty-panel"):
                Text(
                    "Ask about ingredients, allergens or opening hours in the chat to see the source lookups here."
                )
        with ForEach("snapshot.faq_activity") as lookup:
            with Card(css_class="comic-panel source-ticket"):
                with CardContent():
                    with Column(gap=3):
                        with Row(gap=3, align="center", css_class="source-row"):
                            Text(str(lookup.question), css_class="source-arguments")
                            Badge(str(lookup.status), variant=str(lookup.variant))
                            Muted(str(lookup.timestamp))
                        with ForEach(lookup.passages) as passage:
                            with Column(gap=1, css_class="source-passage"):
                                Muted(str(passage.where))
                                Text(str(passage.text))
                        with ForEach(lookup.documents) as document:
                            with Dialog(
                                title=str(document.filename),
                                description="Original FAQ document",
                            ):
                                Button(
                                    "Open source",
                                    variant="outline",
                                    on_click=[
                                        SetState("source_body", ""),
                                        SetState("source_error", False),
                                        Fetch.get(
                                            "/desk/sources/" + str(document.filename),
                                            on_success=SetState("source_body", RESULT.body),
                                            on_error=SetState("source_error", True),
                                        ),
                                    ],
                                )
                                with If(STATE.source_error):
                                    with Alert(variant="warning"):
                                        AlertDescription(
                                            "Could not read this source. Close and try again."
                                        )
                                with If("!source_error && !source_body"):
                                    Text("Loading source…")
                                Markdown(str(STATE.source_body), css_class="source-document")
