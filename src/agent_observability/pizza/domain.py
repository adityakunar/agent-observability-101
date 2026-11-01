"""Business records and totals."""

from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from agent_observability.utilities.addresses import DeliveryAddress

from .enums import Category, Crust, OrderStatus, Size


class MenuItem(BaseModel):
    id: str
    name: str
    category: Category
    description: str
    prices: dict[Size, float] | None = None  # pizza items vary by size
    price: float | None = None  # flat price for non-pizza items
    available: bool = True
    allergens: list[str] = Field(default_factory=list)


class CartItem(BaseModel):
    line_id: str = Field(default_factory=lambda: uuid4().hex)
    item_id: str
    name: str
    category: Category
    size: Size | None = None
    crust: Crust | None = None
    quantity: int = 1
    unit_price: float
    line_total: float


class Deal(BaseModel):
    id: str
    name: str
    description: str
    required_categories: dict[str, int]  # category value -> minimum count
    discount_amount: float | None = None
    discount_percent: float | None = None


class Cart(BaseModel):
    session_id: str
    items: list[CartItem] = Field(default_factory=list)
    applied_deal_id: str | None = None
    deal_discount: float = 0.0
    delivery_address: DeliveryAddress | None = None
    address_candidates: dict[str, DeliveryAddress] = Field(default_factory=dict)

    @property
    def subtotal(self) -> float:
        return round(sum(i.line_total for i in self.items), 2)

    @property
    def total(self) -> float:
        return round(self.subtotal - self.deal_discount, 2)

    def item_count_by_category(self, category: Category) -> int:
        return sum(i.quantity for i in self.items if i.category == category)


class Order(BaseModel):
    order_id: UUID = Field(default_factory=uuid4)
    session_id: str
    cart: Cart
    status: OrderStatus = OrderStatus.CONFIRMED
    delivery_fee: float

    @property
    def grand_total(self) -> float:
        return round(self.cart.total + self.delivery_fee, 2)
