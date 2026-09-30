"""Export adapters: presentation sinks for compiled QS results.

Adapters never calculate and never feed values back into qs_engine.
Each adapter subpackage owns its third-party dependency (e.g. openpyxl
for Excel); the calculation core stays dependency-free.
"""
