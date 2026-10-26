"""Load the snapshot only when a customer asks for delivery."""

import csv
import re
import unicodedata
from difflib import get_close_matches
from pathlib import Path

from .types import DeliveryAddress


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).casefold()
    return "".join(c for c in text if c.isalnum())


class LocalAddressLookup:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._streets: dict[str, list[DeliveryAddress]] | None = None

    async def search(self, street: str, house_number: str) -> list[DeliveryAddress]:
        if not street.strip() or not house_number.strip():
            raise ValueError("Provide a street name and house number.")
        if self._streets is None:
            streets: dict[str, list[DeliveryAddress]] = {}
            with self.path.open(encoding="utf-8", newline="") as stream:
                for row in csv.DictReader(stream):
                    address = DeliveryAddress.model_validate(row)
                    streets.setdefault(_normalise(address.street), []).append(address)
            self._streets = streets
        key = _normalise(street)
        matches = (
            [key]
            if key in self._streets
            else get_close_matches(key, self._streets, n=3, cutoff=0.65)
        )
        number = _normalise(house_number)
        candidates = [
            address
            for match in matches
            for address in self._streets[match]
            if _normalise(address.house_number) == number
            or re.match(re.escape(number) + r"[^0-9]", _normalise(address.house_number))
        ]
        return candidates[:5]
