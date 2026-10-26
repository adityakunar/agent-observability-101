"""The finite choices accepted by pizza tools."""

from enum import StrEnum


class Size(StrEnum):
    PERSONAL = "personal"
    MEDIUM = "medium"
    LARGE = "large"


class Crust(StrEnum):
    ORIGINAL = "original"
    THIN = "thin"
    STUFFED = "stuffed"


class Category(StrEnum):
    PIZZA = "pizza"
    SIDE = "side"
    DRINK = "drink"
    DESSERT = "dessert"
    EXTRA = "extra"
    DEAL = "deal"


class OrderStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
