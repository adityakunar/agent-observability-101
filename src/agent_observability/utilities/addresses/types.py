from typing import Protocol

from pydantic import BaseModel, ConfigDict


class DeliveryAddress(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    street: str
    house_number: str
    postcode: str
    city: str

    @property
    def label(self) -> str:
        return f"{self.street} {self.house_number}, {self.postcode[:4]} {self.postcode[4:]} {self.city}"


class AddressLookup(Protocol):
    async def search(self, street: str, house_number: str) -> list[DeliveryAddress]: ...
