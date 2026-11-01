"""Extract active Amsterdam 1012 addresses from the OpenAddresses Netherlands archive."""

import argparse
import csv
import io
import zipfile
from pathlib import Path

from agent_observability.utilities.resources import project_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--output", type=Path, default=project_path("resources/addresses/amsterdam-1012.csv")
    )
    args = parser.parse_args()
    destination = args.output
    addresses: dict[tuple[str, str, str], dict[str, str]] = {}
    with zipfile.ZipFile(args.archive) as archive, archive.open("verblijfsobject.csv") as stream:
        for row in csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig")):
            if (
                row["woonplaats_naam"] != "Amsterdam"
                or not row["postcode"].startswith("1012")
                or not row["status"].startswith("Verblijfsobject in gebruik")
            ):
                continue
            number = row["huisnummer"] + row["huisletter"]
            if row["toevoeging"]:
                number += "-" + row["toevoeging"]
            key = row["openbare_ruimte_naam"], number, row["postcode"]
            addresses[key] = {
                "id": row["nummeraanduiding_hoofdadres_identificatie"],
                "street": key[0],
                "house_number": key[1],
                "postcode": key[2],
                "city": "Amsterdam",
            }
    if not addresses:
        raise SystemExit("No matching addresses; existing snapshot left unchanged.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["id", "street", "house_number", "postcode", "city"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(addresses[key] for key in sorted(addresses))
    print(f"Saved {len(addresses)} real addresses to {destination}")


if __name__ == "__main__":
    main()
