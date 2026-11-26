# Terminology: water flows, sources and sinks in the flood lab

The words the flood lab uses for water and where it goes, taken from the hydrology glossaries, and the
lab's earlier home-made phrases they replace. New documents use the standard term. Each term is defined at
its first use in a document, and the plain words stay beside it. Requirement wording changes only through
`docs/flood/changes.md` (CH-22).

**Sources** (read 2026-11-26). Short definitions are quoted, with the entry number:

- **W**: WMO/UNESCO *International Glossary of Hydrology*, WMO-No. 385, 3rd edition, 2012. Read from the
  copy at the Brazilian water agency (ANA), `gov.br/ana/.../385_igh_2012.pdf`, and the UNESCO archive copy.
- **U**: USGS Water Science glossary, https://water.usgs.gov/water-basics_glossary.html.
- **S**: SFINCS documentation, https://sfincs.readthedocs.io (pages "Input" and "Parameters").
- **N**: NOAA National Weather Service glossary, https://forecast.weather.gov/glossary.php.

Not read: the AMS Glossary of Meteorology (it refused automated access), FEMA's NFIP glossary (only part of
it loaded) and NOAA Atlas 14's own documentation. A term that none of these sources defines is marked
**convention**, and the lab says so where it uses it.

## 1. The lab's phrases and the standard terms

| The lab said | Standard term | Note |
| --- | --- | --- |
| drainage allowance, "the 30 mm/h" | **constant loss rate**, in the sense of the infiltration index (φ-index, W799); in SFINCS, the uniform infiltration rate `qinf` (S) | It stands in for sewer capacity and infiltration together, so it is a lumped loss, not infiltration capacity (W796) |
| water from outside the square | **run-on** from the **contributing area** outside the square (W291) | Run-on is a convention (no glossary entry). The model has none: a stated limit |
| land edges where water may leave | **outflow boundary** (SFINCS mask value 3) | S: "the water level is not forced, but water depth at that cell is artificially kept at zero" |
| river edges at 0 m | **water-level boundary** (SFINCS mask value 2) at a fixed **water level** (stage, W1621) of 0 m NAVD88 | |
| rain on the square | **precipitation**, a distributed **source term** | "Source term" and "sink term" for distributed quantities are conventions; W1385 and W1326 define point or line sources and sinks |
| water removed by the allowance | a distributed **sink term**, the **loss** | |
| water left on the ground | **ponding** (W1103, sense 2), **storage** | |
| water balance within 1% | **water balance** (W1608) or **continuity** (W286) closes within 1% | Rain = losses + boundary outflow + change in storage + residual |
| depth at a cell | **inundation depth** = **water level** − **ground level** | WMO uses water level and stage for the elevation of the free surface (W1621). "Ground level" is the lab's word for the model terrain. SFINCS says "bed level" |
| peak depth map | **maximum inundation depth** per cell | |
| storm, rain per hour | **hyetograph** (W761, sense 2) | |
| flow out across an edge over time | **outflow hydrograph** (W733) | |
| the city's map scenarios, Atlas 14 storms | **design storm** (W368) | A catalogue storm is a transposed observed storm, not a design storm |
| synthetic years, catalogue | **stochastic storm transposition** (SST), **transposition domain**, **storm catalogue** | Conventions from the SST literature (Wright et al.; the RainyDay tutorial). No glossary entry |
| rainfall flooding | **pluvial flooding**, also surface-water flooding | Convention. Nearest glossary wording: W552 flooding (2), and N "urban and small stream flooding" |
| return period, frequency | **return period** (W1234), **annual maximum series** (W65), **annual exceedance probability** (AEP; convention, no glossary entry in what was read) | |

## 2. Definitions

| Term | Definition (quoted) | In this study |
| --- | --- | --- |
| Basin, catchment, drainage basin, watershed | W133: "Area having a common outlet for its surface runoff." U: drainage basin, "The land area drained by a river or stream." | The 4 km square is not a catchment. It is a window cut from several, without the land upslope of its edges |
| Contributing area | W291: "That part of a drainage basin which contributes to the direct runoff." | Inside the square, all of it. Outside, about 1.6 km² drains towards the square (a D8 estimate on bare ground, 2026-11-26); the model gives it no rain. The ring sensitivity runs test this |
| Run-on | Convention: surface water flowing onto an area from upslope | Zero in the square model by design |
| Runoff; surface runoff; overland flow | W1261: "That part of the precipitation which flows towards a river on the ground surface (surface runoff) or within the soil (subsurface runoff or interflow)." W1044 overland flow: "Flow of water over the ground surface before it enters a defined channel." | SFINCS computes overland flow on the 5 m cells. Water taken by the loss rate is not runoff |
| Rainfall excess, effective rainfall | W1156: "Part of rainfall which contributes directly to surface runoff." | Rain above the 30 mm/h loss rate |
| Infiltration | W795: "Flow of water through the soil surface into a porous medium." | SFINCS names its loss term "infiltration"; here it also stands for the sewers |
| Infiltration capacity | W796: "Maximum rate at which water can penetrate the soil matrix per unit area under certain conditions." | Not what the 30 mm/h is |
| Infiltration index (φ-index) | W799: "Average rate of infiltration derived from a time intensity graph of rainfall in such a manner that the volume of rainfall in excess of this rate will equal the volume of storm runoff." | The 30 mm/h is a constant loss rate in this sense, calibrated on the city's maps (F3) |
| Initial loss | W807 (initial rainfall, syn. initial loss): "Rainfall at the beginning of a storm, before the surface detention and interception capacities are reached." | None in the model |
| Depression storage | W356: "Volume of water required to fill small depressions in a drainage basin to their overflow levels." | Resolved by the terrain and the sub-grid tables, not a separate parameter |
| Ponding | W1103 (2): "Creation of free standing water on the soil surface." | What the depth maps show |
| Source, sink | W1385 (2): "In fluid dynamics, point or line where streamlines diverge." W1326: "...the point or line where streamlines converge." | Precipitation is a distributed source, the loss rate a distributed sink, and the boundaries take outflow. SFINCS also offers point discharge sources (`srcfile`, `disfile`), unused here |
| Inflow, outflow | W804: "Flow of water into a receiving water body." W1039: "Flow of water out of a hydrosystem." | Measured across the square's edges by cross-sections in every run |
| Water balance, continuity | W1608 (2): "Numerical calculation based on the principle that the outflow for a given drainage basin or water body must equal the inflow plus or minus the change in storage." W286 continuity equation (syn. mass conservation law). | Every run: rain − losses − boundary outflow − change in storage = residual, within 1% |
| Boundary condition | W174: "Set of conditions to be satisfied by the solution of a differential equation at the boundaries of the region in which the solution is sought." | Outflow boundary on land, water-level boundary on the river |
| Water level, stage | W1621: "Elevation of the free water surface of a water body relative to a datum level." | Datum NAVD88 |
| Hyetograph | W761 (2): "Graph displaying the intensity of precipitation in relation to time." | Each catalogue storm's hourly rain over the box |
| Hydrograph | W733: "Graph showing the variation in time of some hydrological data, such as stage, discharge, velocity and sediment load." | Outflow at the edges, if plotted |
| Time of concentration | W1516: "Period of time required for storm runoff to flow to the outlet from the point of a drainage basin having the longest travel time." | Short for streets in a 4 km window; one reason for 3-hour storms |
| Design storm | W368 (1): "Rainstorm, either observed or synthetic, which is chosen as the basis for the design of a hydraulic structure." | The six Atlas 14 storms (FH6) and the city's map scenarios |
| Areal reduction factor | W85: "Ratio of the mean areal rainfall, for a given duration and given return period, to the mean point rainfall, for the same duration and same return period in the same area." | Not applied. Catalogue rain is areal, over the study box; Atlas 14 is a point value |
| Return period | W1234: "Long-term average time interval between a hydrological event of a specific magnitude and an event with equal or greater magnitude." | Catalogue: rank r of M years has return period M/r |
| Annual maximum series | W65: "Series of the largest values from each year." | One storm per synthetic year, its largest |
| Partial duration series | W1053 (syn. peaks-over-threshold series): "Time series of the values of independent events ... above a selected base level, irrespective of the number of events occurring during the time period under consideration." | Atlas 14 publishes both; the lab compares with the annual maximum series |
| Intensity-duration-frequency curve | W820: "Curve showing the probability that various short-period rainfall rates for various durations of precipitation at a given location will be exceeded." | Atlas 14's tables |
| Annual exceedance probability | Convention: the probability that a value is equalled or exceeded in any one year, 1 / return period | CRC 1.0.0 works with its complement, the non-exceedance probability |
| Stochastic storm transposition; transposition domain | Convention (Wright et al.; RainyDay tutorial) | Domain B (`docs/flood/simulated-events.md`) |
| D8 flow direction, flow accumulation | Convention (terrain analysis) | Used only for the screening estimate of the outside contributing area. SFINCS solves the shallow-water equations and does not use D8 |

## 3. Rules for writing

1. Use the standard term and keep the plain explanation beside it at first use. For example: "a constant
   loss rate of 30 mm/h (the water the sewers and the ground take away)".
2. Never call the 30 mm/h "infiltration capacity" or "sewer capacity". It is a calibrated lumped loss.
3. Say "water level" for the elevation of the water surface and "depth" for water level less ground level.
4. Say "run-on" only for water from outside an area, and "runoff" for water flowing over the surface.
5. Mark conventions as such where a reader might take them for defined terms (SST, AEP, run-on, pluvial).
