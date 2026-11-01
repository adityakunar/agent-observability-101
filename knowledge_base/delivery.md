# Delivery

## Delivery area

Lantern Pizza's demo delivery area is Amsterdam postcode area **1012**.

Ask the customer for the street, the house number and the city. The order keeps
the address in the customer's own words. This demo does not check that the address
exists. Do not invent an address, and do not complete an address that the customer
gave in part.

## Address required before confirmation

An order requires both items and a saved delivery address. Save the address with
`set_delivery_address`. A new address replaces the previous one.

## Fee and estimated time

Delivery costs **€1.99 per order**, with an estimated time of **30–40 minutes**.
The meal deal's €2 discount applies to the food total; delivery is added after it.

This is a proof of concept. No courier, payment or fulfillment system is contacted.
A production service would need to validate addresses and to handle service failures.
