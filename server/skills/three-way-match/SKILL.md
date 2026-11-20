---
name: three-way-match
description: How to match a supplier invoice to the purchase order and goods receipt. Use for every new supplier invoice.
---
# Three-way match playbook

1. Every invoice line must be on the purchase order, at the order price within the client's tolerance.
2. Invoiced quantity must not exceed received quantity.
3. The same supplier and invoice number twice is a probable duplicate.
4. Any exception: propose a payment block (a buyer approves) and say exactly what differs.
Never approve or make a payment.
