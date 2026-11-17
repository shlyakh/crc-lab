"""Outside evidence of flooding, fetched from its publishers to compare with flood depth maps.

Each module fetches one publisher's records into a folder (``live=True``) or reads the copy
kept there (``live=False``), and has pure parsers that turn the stored text into plain rows.

- ``fema_nfhl``: FEMA National Flood Hazard Layer, flood hazard zone polygons.
- ``usgs_peaks``: USGS stream gauges, their annual peaks, and NWS flood stages.
- ``usgs_stn``: USGS Short-Term Network high-water marks (Hurricane Harvey 2017).

Rule (enforced by tests/validation): nothing here imports the framework under test or any
other project of this repository.
"""
