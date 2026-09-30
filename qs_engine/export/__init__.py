"""Document export package (Phase 19): formal PDF generation.

Presentation sinks only: compiled BOQs and IPC valuations in,
print-ready PDF bytes out. Amounts arrive as exact strings and are
formatted for display at this boundary only (quantize_money);
nothing is calculated here beyond presentation roll-ups.
"""
