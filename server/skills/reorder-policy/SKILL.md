---
name: reorder-policy
description: The store's rules for deciding which items to reorder and how many units. Use when checking stock risk, calculating an order quantity or choosing a supplier.
---
# Reorder policy

Definitions
- Days of cover = stock on hand / average daily sales.
- An item is at risk when days of cover <= supplier lead time + 2 safety days.

Order quantity
- Target cover after delivery: 14 days.
- Quantity = forecast demand for (lead time + 14 days) - stock on hand, rounded up to the next 10.
- Show the calculation with the numbers.

Choosing a supplier
1. Remove suppliers whose lead time is longer than the days of cover left, unless none remain.
2. From the rest choose the lowest unit price.
3. If two prices are within 2 percent, choose the better on-time record.

Limits
- One purchase order per item per day.
- Every purchase order is a draft until a human approves it.
