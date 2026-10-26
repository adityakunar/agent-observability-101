# Delivery

## Delivery area

Lantern Pizza's demo delivery area is Amsterdam postcode area **1012**.
The address lookup searches a local snapshot of real Netherlands BAG address
records obtained through OpenAddresses.

Provide a street name and house number. The chat shows matching addresses and
asks the customer to select one. A similar street name may be suggested when a
name is misspelled. If no address is found, ask the customer to check their details.
Do not invent an address or interpret a missing record as proof that it does not exist.

## Address required before confirmation

An order requires both items and a customer-selected address from the lookup.
A typed address alone is not a selection. The model cannot select an address;
the host saves the customer's choice. A new lookup clears the previous choice.

## Fee and estimated time

Delivery costs **€1.99 per order**, with an estimated time of **30–40 minutes**.
The meal deal's €2 discount applies to the food total; delivery is added after it.
Use `get_delivery_estimate` to show the current quote.

This is a proof of concept. No courier, payment or fulfillment system is contacted.
The local snapshot is dated 3 June 2026. A production service would need maintained
coverage and a way to handle unknown addresses and service failures.
