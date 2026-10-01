+++
doc_id = "policy-cancellations"
title = "Cancelling an order"
namespace = "policy"
audience = "customer"
version = 1
effective_date = 2026-01-01
+++

# Cancelling an order

You can cancel an order that has not started processing yet.

## When an order can be cancelled

An order can be cancelled only while its status is **pending**. Once an order is processed, delivered or already
cancelled, it cannot be cancelled. An order whose items were modified (status **pending (item modified)**) can no
longer be cancelled either.

## Reasons we accept

We ask for the reason, and it must be one of these two:

- **no longer needed**
- **ordered by mistake**

Other reasons are not accepted for a cancellation.

## What happens next

After you confirm the order number and the reason, the status changes to **cancelled** and the full amount is
refunded to the original payment method. A refund to a gift card is immediate. A refund to a credit card or PayPal
takes 5 to 7 business days.
