"""Bundled resources and snapshot rebuilding work independently of the shell directory."""

import csv
import io
import subprocess
import sys
import zipfile

from agent_observability.pizza.operator.app import pizza_operator
from agent_observability.utilities.addresses import LocalAddressLookup
from agent_observability.utilities.resources import project_path


def _archive(path, rows):
    fields = [
        "woonplaats_naam",
        "postcode",
        "status",
        "huisnummer",
        "huisletter",
        "toevoeging",
        "openbare_ruimte_naam",
        "nummeraanduiding_hoofdadres_identificatie",
    ]
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("verblijfsobject.csv", text.getvalue())


async def test_lookup_and_prefab_assets_work_from_another_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lookup = LocalAddressLookup(project_path("resources/addresses/amsterdam-1012.csv"))
    matches = await lookup.search("Damrk", "1")
    assert matches[0].label == "Damrak 1, 1012 LG Amsterdam"
    view = pizza_operator().to_json()
    assert "data:image/jpeg;base64," in str(view["view"])
    assert view["css"]


def test_bootstrap_filters_and_deduplicates_into_a_new_directory(tmp_path):
    row = {
        "woonplaats_naam": "Amsterdam",
        "postcode": "1012LG",
        "status": "Verblijfsobject in gebruik",
        "huisnummer": "1",
        "huisletter": "A",
        "toevoeging": "2",
        "openbare_ruimte_naam": "Damrak",
        "nummeraanduiding_hoofdadres_identificatie": "address-1",
    }
    archive = tmp_path / "addresses.zip"
    _archive(
        archive,
        [
            row,
            row,
            {**row, "postcode": "1013AB"},
            {**row, "woonplaats_naam": "Rotterdam"},
            {**row, "status": "Verblijfsobject ingetrokken"},
        ],
    )
    output = tmp_path / "new" / "snapshot.csv"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_observability.utilities.addresses.bootstrap",
            str(archive),
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    with output.open() as stream:
        assert list(csv.DictReader(stream)) == [
            {
                "id": "address-1",
                "street": "Damrak",
                "house_number": "1A-2",
                "postcode": "1012LG",
                "city": "Amsterdam",
            }
        ]


def test_empty_bootstrap_preserves_the_existing_snapshot(tmp_path):
    archive = tmp_path / "empty.zip"
    _archive(archive, [])
    output = tmp_path / "snapshot.csv"
    output.write_text("existing snapshot\n")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_observability.utilities.addresses.bootstrap",
            str(archive),
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0 and "No matching addresses" in result.stderr
    assert output.read_text() == "existing snapshot\n"
