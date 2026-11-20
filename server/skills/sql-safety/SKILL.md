---
name: sql-safety
description: Rules for writing safe, correct read-only SQL against the analytics database. Use before writing or running any SQL query.
---
# SQL safety

1. Look before you query: list_tables, then describe_table for every table you will use.
2. Write one SELECT statement. No INSERT, UPDATE, DELETE or DDL. The tool refuses them.
3. Always add a LIMIT. Default 50.
4. Never select personal data columns (name, phone, email). Aggregate instead.
5. Dates are stored as text YYYY-MM-DD. Compare with date('YYYY-MM-DD').
6. "Last week" means the last full Monday-to-Sunday week. State the dates you used.
7. After running, sanity-check: does the total look plausible against a simple COUNT or SUM?
8. Show the SQL you ran in your answer.
