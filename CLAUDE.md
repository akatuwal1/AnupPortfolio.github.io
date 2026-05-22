# CLAUDE.md

## Operational Boundaries

### 1. Order Cancellation & Refund Policy
Never delete cancelled or refunded orders. Flag them instead using a status indicator (e.g., `status: "cancelled"` or `status: "refunded"`). All order records must be preserved for audit and historical reference.

### 2. Zero-Tolerance Policy on Calculations
Never guess or approximate calculation results. Always execute a Python script to compute and cross-verify any data results before reporting or using them. If a script cannot be run, explicitly state that verification is pending.
