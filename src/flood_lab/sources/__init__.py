"""Loaders of the flood lab's own sources (requirements FS1 to FS3, D8).

Each module reads one publisher's file into the lab's form and, where CRC 1.0.0 can hold it,
into CRC. This is one of the two places in ``flood_lab`` that may import ``crc_sdk`` (FG1). The
independent readers that recompute these values live in ``flood_lab.reference`` and share no code
with this package (FS4).
"""
