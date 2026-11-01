"""Address lookup and snapshot rebuilding for the demo."""

from agent_observability.utilities.resources import project_path

from .lookup import LocalAddressLookup as LocalAddressLookup
from .types import AddressLookup as AddressLookup
from .types import DeliveryAddress as DeliveryAddress

address_lookup: AddressLookup = LocalAddressLookup(
    project_path("resources/addresses/amsterdam-1012.csv")
)
