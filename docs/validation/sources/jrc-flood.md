# JRC flood hazard maps (GloFAS, EFAS): assessment

Generated from the records of the run of 2026-11-23T20:49:23Z against crc-framework 0.6.0, crc-sdk 0.11.2. **Draft: not yet reviewed.**
Do not edit: change the source file or re-run the assessment and rebuild.

- **What the framework adds:** From JRC's maps of flood depth at fixed return periods crc-sdk makes one fitted curve per map pixel (a Gumbel distribution by least squares), so that a depth can be read at any return period, and places each pixel on the H3 cells it overlaps. The published depths themselves are not kept, and a pixel with fewer than four depths gets no curve.
- **How it is compared:** JRC's files are downloaded whole and read by an independent reader. In five areas (Texas, Houston, Austin, Fremont, the Rhine) every pixel of crc-sdk's local copies is compared with them bit for bit, every curve is refitted and compared, and samples of the curve values, cells and identifiers are recomputed.
- **Purpose (the framework's documentation):** River flood depth at published return periods, fitted to a curve per source pixel and placed on H3 cells.
- **Publisher:** European Commission JRC, Copernicus Emergency Management Service · https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard and CEMS-EFAS/flood_hazard
- **Entry points:** `HazardDataset.glofas`, `HazardDataset.efas`, `HazardDataset.jrc`
- **Status:** exploration assessed, verification assessed, validation not assessed
- **Options, dataset:** assessed efas, glofas; not assessed none

## Exploration

### What was read

Counted from the publisher's files by the reference reader. A pixel is wet at a return period when the file gives it a depth; dry pixels hold the nodata value, not zero.

| Area | Dataset | H3 | Tiles | Pixels in box | Wet at the shortest | Wet at the longest | Wet at any | With a curve | Deepest (m) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Texas box | glofas | 7 | 4 | 201,757,502 | 9,255,575 | 11,686,209 | 11,686,210 | 9,853,959 | 108.23 |
| Houston | glofas | 9 | 2 | 1,298,281 | 186,964 | 278,654 | 278,654 | 212,949 | 10.14 |
| Austin | glofas | 9 | 2 | 361,201 | 20,396 | 25,494 | 25,494 | 22,201 | 21.83 |
| Fremont, California | glofas | 10 | 1 | 87,001 | 7,972 | 10,603 | 10,603 | 7,869 | 20.55 |
| Rhine, Bonn to Mainz | efas | 7 | 1 | 2,595,241 | 123,586 | 161,898 | 161,898 | 143,074 | 22.86 |

### Wet pixels that get no curve

crc-sdk fits a pixel only when it has a depth at four or more return periods that are not all equal and never decrease. Share is of the pixels wet at any return period. The publisher patches permanent water bodies into the maps: in the GloFAS areas every pixel with equal depths lies in the publisher's permanent-water layer and none with fewer than four depths does (probe, finding CRC-014-JRC).

| Area | Wet at any | Fewer than four depths | All depths equal | Of those, all exactly 1 m | A depth decreases | No curve | Share |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Texas box | 11,686,210 | 941,251 | 698,317 | 698,317 | 192,683 | 1,832,251 | 15.7% |
| Houston | 278,654 | 44,732 | 16,983 | 16,983 | 3,990 | 65,705 | 23.6% |
| Austin | 25,494 | 1,910 | 1,243 | 1,243 | 140 | 3,293 | 12.9% |
| Fremont, California | 10,603 | 967 | 992 | 992 | 775 | 2,734 | 25.8% |
| Rhine, Bonn to Mainz | 161,898 | 15,166 | 2,928 | 2,928 | 730 | 18,824 | 11.6% |

### Published wet pixels without a curve, by return period

Of the pixels the publisher shows flooded at a return period, how many have no row in crc-sdk's output.

| Area | 10 y | 20 y | 30 y | 40 y | 50 y | 75 y | 100 y | 200 y | 500 y |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Texas box | 890,968 (9.6%) | 890,974 (9.0%) |  |  | 890,994 (8.5%) | 891,001 (8.3%) | 1,051,657 (9.6%) | 1,408,040 (12.5%) | 1,832,250 (15.7%) |
| Houston | 20,973 (11.2%) | 20,973 (10.3%) |  |  | 20,973 (9.3%) | 20,973 (9.0%) | 27,334 (11.4%) | 43,619 (17.0%) | 65,705 (23.6%) |
| Austin | 1,383 (6.8%) | 1,383 (6.4%) |  |  | 1,383 (6.0%) | 1,383 (5.9%) | 1,693 (7.1%) | 2,362 (9.6%) | 3,293 (12.9%) |
| Fremont, California | 1,767 (22.2%) | 1,767 (20.4%) |  |  | 1,767 (18.9%) | 1,767 (18.3%) | 1,947 (19.8%) | 2,275 (22.4%) | 2,734 (25.8%) |
| Rhine, Bonn to Mainz | 3,658 (3.0%) | 3,658 (2.8%) | 3,658 (2.7%) | 3,658 (2.6%) | 3,658 (2.6%) | 3,658 (2.5%) | 6,241 (4.2%) | 12,009 (7.7%) | 18,824 (11.6%) |

### How far the fitted curve lies from the published depths

Per fitted pixel, the largest gap in metres between the curve and the published depth over the return periods at which the pixel is wet.

| Area | Curves | Median | 90th percentile | 99th percentile | Largest | Over 0.5 m | Over 1 m |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Texas box | 9,853,959 | 0.039 | 0.138 | 0.600 | 26.429 | 127,116 | 31,771 |
| Houston | 212,949 | 0.040 | 0.085 | 0.256 | 3.109 | 940 | 221 |
| Austin | 22,201 | 0.095 | 0.165 | 0.265 | 1.163 | 40 | 1 |
| Fremont, California | 7,869 | 0.017 | 0.066 | 0.230 | 1.976 | 55 | 26 |
| Rhine, Bonn to Mainz | 143,074 | 0.092 | 0.242 | 0.655 | 8.685 | 3,410 | 654 |

### Curve where the publisher is dry, and curve below zero

Pixels with a curve that the publisher shows dry at the shortest return period: how many curves give a depth above 0 and of 0.1 m or more there (0.1 m is the smallest published depth). And fitted curves that are below zero at the shortest return period.

| Area | Dry at the shortest, with a curve | Curve above 0 | Curve 0.1 m or more | Largest such depth (m) | Curves below 0 |
| --- | --- | --- | --- | --- | --- |
| Texas box | 1,489,352 | 890,236 | 493,550 | 53.90 | 604,768 |
| Houston | 46,958 | 25,838 | 14,678 | 7.32 | 21,124 |
| Austin | 3,188 | 1,113 | 782 | 4.23 | 2,075 |
| Fremont, California | 1,664 | 1,304 | 593 | 3.65 | 362 |
| Rhine, Bonn to Mainz | 23,146 | 8,085 | 5,709 | 13.06 | 15,293 |

### Depths above 10 m and the publisher's spurious-depth mask

The publisher marks areas where depths above 10 m are predicted in small channels and asks for caution there; crc-sdk does not read the mask. Counted at the 100-year return period. The mask of EFAS was not read.

| Area | Pixels in the mask | Deeper than 10 m | Of those, in the mask |
| --- | --- | --- | --- |
| Texas box | 268,433 | 192,437 | 8,393 |
| Houston | 0 | 0 | 0 |
| Austin | 1,245 | 2,201 | 21 |
| Fremont, California | 5,137 | 126 | 126 |
| Rhine, Bonn to Mainz |  | 9,037 |  |

### crc-sdk's runs

One run per area, reading the publisher over the network into an empty cache. Memory is the peak of the whole process when the run ended, so it includes whatever that process did before the run; it is crc-sdk's own only for a run that began its process (the Texas box here).

| Area | Rows | Seconds | Process peak memory (MB) | Outcome |
| --- | --- | --- | --- | --- |
| glofas-tx | 10,703,386 | 1605.5 | 7,711 | completed |
| glofas-houston | 354,477 | 45.5 | 7,711 | completed |
| glofas-austin | 36,803 | 12.1 | 7,711 | completed |
| glofas-fremont | 23,702 | 9.1 | 7,711 | completed |
| efas-rhine | 154,825 | 42.3 | 7,711 | completed |
| efas-tx | 0 | 7.2 |  | LookupError: no JRC resources intersect area (-106.645646, 25.837377, -93.508292, 36.500704) |
| efas-fremont | 0 | 0.8 |  | LookupError: no JRC resources intersect area (-122.15, 37.42, -121.85, 37.62) |

### The publisher's releases

From each dataset's README.txt, copyright.txt and directory page.

| Dataset | Release | Return periods | Licence in README.txt | copyright.txt names CC BY 4.0 | Depth files last modified | README last modified | Coverage in README.txt |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cems-efas-river-flood | 3.1.1 | 10, 20, 30, 40, 50, 75, 100, 200, 500 | Open Data Commons Open Database License v1.0 | yes | 2026-03-03 to 2026-03-05 | 2026-10-21 10:39 | European extended domain (-24.54, 67.26; 27.81, 71.13) |
| cems-glofas-river-flood | 2.1.2 | 10, 20, 50, 75, 100, 200, 500 | Open Data Commons Open Database License v1.0 | yes | 2025-12-17 to 2025-12-18 | 2026-10-21 10:40 | Global |

### River flood depth at 25 years by county: Texas box

The summary of crc-docs' flood_risk_by_province notebook, from crc-sdk's output of this run: each row's curve read at 25 years, the largest value per H3 resolution-7 cell, cells at or above 0.5 m (38,418 of 40,358 cells with a curve), then mean and largest per county; a cell on a border counts in each county it overlaps. Boundaries: Texas counties: U.S. Census Bureau TIGERweb, vintage 1 January 2026, simplified to 0.002 degrees by the service.

| County | Mean depth of those cells (m) | Largest (m) | Cells at or above 0.5 m | Cells of the county |
| --- | --- | --- | --- | --- |
| Brewster | 14.54 | 67.20 | 371 | 2,779 |
| Johnson | 10.16 | 16.19 | 21 | 374 |
| San Saba | 10.11 | 21.97 | 153 | 568 |
| Lampasas | 9.74 | 21.97 | 56 | 360 |
| Somervell | 9.68 | 15.09 | 37 | 108 |
| Mills | 9.61 | 16.06 | 81 | 388 |
| Bastrop | 9.45 | 15.23 | 87 | 443 |
| Presidio | 9.26 | 43.55 | 205 | 1,753 |
| Mason | 9.03 | 13.68 | 60 | 456 |
| Parker | 8.49 | 14.72 | 53 | 457 |
| Palo Pinto | 8.23 | 16.46 | 141 | 488 |
| Kendall | 8.02 | 12.27 | 45 | 329 |
| Travis | 7.98 | 17.50 | 131 | 513 |
| Waller | 7.98 | 13.29 | 84 | 283 |
| Cherokee | 7.97 | 12.21 | 148 | 550 |
| Panola | 7.86 | 11.63 | 114 | 428 |
| Fayette | 7.85 | 14.54 | 85 | 471 |
| Washington | 7.78 | 13.29 | 89 | 331 |
| Hood | 7.68 | 16.19 | 54 | 228 |
| Smith | 7.64 | 13.43 | 63 | 489 |
| McCulloch | 7.59 | 14.03 | 114 | 529 |
| Gregg | 7.51 | 10.30 | 57 | 158 |
| Kimble | 7.51 | 13.50 | 83 | 603 |
| Brazos | 7.50 | 12.64 | 137 | 318 |
| Anderson | 7.48 | 11.41 | 147 | 559 |
| Austin | 7.44 | 13.29 | 101 | 351 |
| Wood | 7.14 | 13.43 | 88 | 367 |
| Webb | 7.08 | 14.65 | 172 | 1,572 |
| Rusk | 7.03 | 10.62 | 33 | 486 |
| Val Verde | 6.95 | 26.15 | 344 | 1,497 |
| Maverick | 6.93 | 14.55 | 110 | 623 |
| Blanco | 6.90 | 13.18 | 35 | 357 |
| Burnet | 6.84 | 17.69 | 96 | 510 |
| Swisher | 6.83 | 12.37 | 39 | 446 |
| Tyler | 6.79 | 11.29 | 116 | 482 |
| Colorado | 6.78 | 12.89 | 119 | 490 |
| Houston | 6.78 | 11.07 | 129 | 628 |
| Llano | 6.77 | 16.96 | 104 | 477 |
| Grimes | 6.75 | 11.43 | 72 | 410 |
| Newton | 6.74 | 13.98 | 214 | 506 |
| Terrell | 6.73 | 41.59 | 194 | 1,094 |
| Bexar | 6.70 | 13.07 | 90 | 606 |
| Cooke | 6.54 | 10.39 | 90 | 478 |
| Montague | 6.54 | 8.18 | 43 | 474 |
| Liberty | 6.51 | 9.84 | 206 | 589 |
| Leon | 6.34 | 10.18 | 137 | 548 |
| Hays | 6.30 | 12.36 | 45 | 344 |
| Bosque | 6.14 | 16.14 | 119 | 508 |
| Jasper | 6.14 | 11.29 | 181 | 525 |
| Freestone | 6.08 | 9.82 | 81 | 455 |
| Upshur | 6.07 | 10.31 | 59 | 318 |
| Harrison | 6.07 | 11.63 | 117 | 478 |
| Robertson | 6.05 | 12.19 | 132 | 443 |
| Burleson | 6.04 | 12.64 | 140 | 358 |
| DeWitt | 6.04 | 10.17 | 85 | 451 |
| Starr | 6.03 | 16.73 | 84 | 591 |
| Coleman | 5.99 | 14.03 | 116 | 628 |
| Young | 5.99 | 11.96 | 114 | 465 |
| Morris | 5.95 | 9.12 | 45 | 154 |
| Fannin | 5.95 | 9.37 | 74 | 462 |
| Hill | 5.84 | 16.14 | 78 | 505 |
| Carson | 5.84 | 8.68 | 17 | 462 |
| Nacogdoches | 5.83 | 12.22 | 141 | 513 |
| Comal | 5.78 | 12.27 | 75 | 300 |
| Gillespie | 5.71 | 7.83 | 28 | 518 |
| Dallas | 5.71 | 12.19 | 140 | 459 |
| McLennan | 5.70 | 13.83 | 101 | 527 |
| Lamar | 5.63 | 9.41 | 101 | 491 |
| Red River | 5.60 | 10.56 | 165 | 558 |
| Hudspeth | 5.57 | 22.20 | 155 | 2,072 |
| Bowie | 5.55 | 11.74 | 212 | 503 |
| Hardin | 5.55 | 10.81 | 222 | 463 |
| Karnes | 5.53 | 9.63 | 79 | 379 |
| Polk | 5.52 | 11.45 | 130 | 566 |
| Van Zandt | 5.48 | 9.19 | 41 | 446 |
| Zapata | 5.35 | 13.86 | 95 | 515 |
| Throckmorton | 5.35 | 10.18 | 73 | 452 |
| Milam | 5.31 | 12.19 | 162 | 508 |
| Montgomery | 5.29 | 9.21 | 102 | 545 |
| Brown | 5.29 | 13.65 | 97 | 472 |
| Angelina | 5.28 | 12.22 | 168 | 455 |
| Madison | 5.27 | 7.91 | 67 | 258 |
| Goliad | 5.27 | 9.74 | 95 | 428 |
| Wilson | 5.21 | 11.21 | 86 | 400 |
| Randall | 5.18 | 16.45 | 61 | 458 |
| Guadalupe | 5.17 | 9.12 | 107 | 365 |
| Trinity | 5.17 | 9.90 | 78 | 370 |
| Titus | 5.16 | 7.93 | 78 | 235 |
| Victoria | 5.03 | 8.15 | 140 | 448 |
| Gonzales | 4.96 | 8.48 | 119 | 523 |
| Fort Bend | 4.93 | 10.59 | 268 | 454 |
| Coryell | 4.93 | 7.36 | 97 | 520 |
| Tarrant | 4.85 | 11.39 | 99 | 454 |
| Lavaca | 4.81 | 8.32 | 69 | 478 |
| Henderson | 4.81 | 10.06 | 120 | 494 |
| Camp | 4.78 | 7.15 | 25 | 123 |
| Shackelford | 4.76 | 10.18 | 69 | 455 |
| Caldwell | 4.76 | 8.60 | 45 | 282 |
| Stonewall | 4.74 | 8.60 | 120 | 455 |
| Falls | 4.67 | 9.68 | 81 | 390 |
| Franklin | 4.67 | 6.70 | 37 | 169 |
| Menard | 4.66 | 7.62 | 42 | 443 |
| Kinney | 4.65 | 11.74 | 77 | 649 |
| Mitchell | 4.63 | 7.52 | 96 | 447 |
| Hamilton | 4.63 | 7.77 | 53 | 422 |
| Walker | 4.62 | 6.71 | 73 | 413 |
| Hardeman | 4.62 | 8.06 | 84 | 360 |
| Kerr | 4.59 | 7.89 | 27 | 547 |
| San Jacinto | 4.59 | 11.45 | 101 | 337 |
| Edwards | 4.56 | 8.79 | 56 | 994 |
| El Paso | 4.54 | 14.60 | 116 | 491 |
| Lubbock | 4.53 | 10.74 | 65 | 445 |
| Coke | 4.52 | 7.24 | 63 | 454 |
| Jack | 4.49 | 6.66 | 50 | 462 |
| Bandera | 4.47 | 10.99 | 38 | 399 |
| Hansford | 4.47 | 10.96 | 80 | 464 |
| Glasscock | 4.46 | 7.73 | 38 | 438 |
| Castro | 4.43 | 12.37 | 55 | 446 |
| Oldham | 4.40 | 12.84 | 102 | 731 |
| Comanche | 4.40 | 8.68 | 86 | 471 |
| Cass | 4.38 | 11.74 | 90 | 501 |
| Bell | 4.36 | 11.74 | 115 | 537 |
| Kent | 4.34 | 8.12 | 129 | 442 |
| Sherman | 4.34 | 9.53 | 97 | 464 |
| Collingsworth | 4.32 | 9.02 | 47 | 461 |
| Scurry | 4.15 | 8.05 | 43 | 445 |
| Runnels | 4.14 | 8.68 | 82 | 514 |
| Uvalde | 4.13 | 7.94 | 146 | 737 |
| King | 4.11 | 6.79 | 30 | 451 |
| Moore | 4.11 | 8.52 | 46 | 454 |
| Live Oak | 4.08 | 7.99 | 120 | 527 |
| Lamb | 4.06 | 11.36 | 63 | 498 |
| Stephens | 4.01 | 9.95 | 79 | 456 |
| Floyd | 4.01 | 10.87 | 55 | 489 |
| Wheeler | 4.01 | 8.38 | 51 | 461 |
| Lee | 4.01 | 5.74 | 39 | 335 |
| Deaf Smith | 3.97 | 7.89 | 110 | 723 |
| Gray | 3.94 | 8.89 | 58 | 465 |
| Concho | 3.93 | 10.73 | 75 | 485 |
| Williamson | 3.93 | 7.31 | 76 | 557 |
| Eastland | 3.92 | 9.21 | 27 | 459 |
| Wise | 3.92 | 14.73 | 92 | 463 |
| Briscoe | 3.87 | 14.63 | 71 | 449 |
| Marion | 3.86 | 10.59 | 108 | 238 |
| Wichita | 3.86 | 9.78 | 101 | 329 |
| Harris | 3.86 | 9.21 | 278 | 883 |
| Haskell | 3.83 | 9.46 | 60 | 449 |
| Sutton | 3.80 | 8.52 | 57 | 690 |
| Foard | 3.78 | 6.68 | 76 | 374 |
| Grayson | 3.77 | 11.57 | 81 | 504 |
| Medina | 3.75 | 8.19 | 89 | 642 |
| Crockett | 3.75 | 7.75 | 171 | 1,324 |
| Cottle | 3.75 | 7.45 | 101 | 450 |
| Rains | 3.74 | 9.19 | 49 | 148 |
| Ellis | 3.73 | 8.19 | 73 | 479 |
| Crosby | 3.70 | 8.28 | 60 | 444 |
| Jackson | 3.70 | 7.66 | 152 | 432 |
| Armstrong | 3.69 | 5.65 | 46 | 452 |
| Ochiltree | 3.69 | 6.74 | 37 | 465 |
| Kaufman | 3.69 | 7.88 | 105 | 415 |
| Clay | 3.67 | 7.33 | 147 | 559 |
| San Patricio | 3.65 | 8.12 | 128 | 373 |
| Howard | 3.63 | 6.42 | 43 | 443 |
| Wilbarger | 3.61 | 9.78 | 123 | 498 |
| Brazoria | 3.53 | 8.78 | 610 | 791 |
| Refugio | 3.51 | 8.15 | 153 | 419 |
| Shelby | 3.43 | 10.50 | 66 | 432 |
| Baylor | 3.42 | 7.40 | 122 | 450 |
| Navarro | 3.42 | 9.15 | 183 | 547 |
| Denton | 3.38 | 8.36 | 117 | 479 |
| Chambers | 3.35 | 8.14 | 220 | 454 |
| Bee | 3.35 | 5.97 | 64 | 432 |
| Dallam | 3.33 | 10.96 | 89 | 738 |
| Hopkins | 3.32 | 7.37 | 63 | 408 |
| Tom Green | 3.31 | 8.72 | 120 | 760 |
| Parmer | 3.28 | 7.89 | 71 | 437 |
| Knox | 3.28 | 6.63 | 120 | 428 |
| Potter | 3.23 | 5.73 | 49 | 460 |
| Hale | 3.22 | 7.04 | 107 | 493 |
| Gaines | 3.22 | 8.04 | 132 | 716 |
| Childress | 3.20 | 5.28 | 49 | 362 |
| Donley | 3.17 | 19.33 | 44 | 465 |
| Garza | 3.15 | 8.97 | 143 | 439 |
| Hall | 3.11 | 7.31 | 57 | 452 |
| Fisher | 3.10 | 7.70 | 81 | 443 |
| Orange | 3.10 | 6.28 | 155 | 210 |
| Atascosa | 3.09 | 5.11 | 80 | 593 |
| Callahan | 3.08 | 5.04 | 13 | 444 |
| McMullen | 3.08 | 6.71 | 151 | 557 |
| Hockley | 3.06 | 7.21 | 31 | 446 |
| Delta | 3.06 | 6.26 | 74 | 166 |
| Reagan | 3.05 | 7.95 | 50 | 559 |
| Dickens | 3.04 | 4.98 | 13 | 450 |
| Frio | 3.04 | 7.84 | 114 | 546 |
| La Salle | 3.03 | 7.02 | 175 | 709 |
| Hartley | 2.99 | 5.71 | 85 | 714 |
| Lipscomb | 2.99 | 5.17 | 57 | 473 |
| Terry | 2.99 | 8.16 | 96 | 438 |
| Schleicher | 2.93 | 6.39 | 17 | 628 |
| Wharton | 2.92 | 8.37 | 282 | 543 |
| Cameron | 2.91 | 7.79 | 502 | 631 |
| San Augustine | 2.90 | 10.50 | 76 | 320 |
| Dawson | 2.89 | 5.50 | 82 | 442 |
| Matagorda | 2.87 | 6.69 | 547 | 796 |
| Limestone | 2.84 | 5.81 | 28 | 469 |
| Loving | 2.84 | 7.41 | 66 | 338 |
| Midland | 2.78 | 7.73 | 84 | 438 |
| Hidalgo | 2.77 | 7.08 | 315 | 765 |
| Zavala | 2.75 | 7.84 | 139 | 618 |
| Roberts | 2.74 | 13.44 | 48 | 465 |
| Dimmit | 2.68 | 5.55 | 111 | 633 |
| Andrews | 2.65 | 5.12 | 55 | 710 |
| Jeff Davis | 2.64 | 22.19 | 43 | 1,049 |
| Real | 2.64 | 5.13 | 27 | 347 |
| Bailey | 2.53 | 10.47 | 35 | 410 |
| Calhoun | 2.53 | 5.49 | 209 | 517 |
| Yoakum | 2.53 | 7.45 | 61 | 395 |
| Motley | 2.53 | 5.68 | 68 | 488 |
| Crane | 2.50 | 4.54 | 50 | 393 |
| Archer | 2.45 | 4.90 | 48 | 462 |
| Jefferson | 2.44 | 9.50 | 278 | 570 |
| Irion | 2.43 | 3.82 | 66 | 506 |
| Nueces | 2.41 | 7.86 | 200 | 584 |
| Lynn | 2.40 | 13.52 | 37 | 439 |
| Jones | 2.36 | 6.84 | 98 | 460 |
| Martin | 2.34 | 6.33 | 99 | 445 |
| Borden | 2.28 | 4.04 | 52 | 442 |
| Hemphill | 2.26 | 13.44 | 69 | 462 |
| Jim Hogg | 2.24 | 4.03 | 6 | 550 |
| Ward | 2.23 | 9.13 | 146 | 418 |
| Sterling | 2.22 | 4.21 | 34 | 452 |
| Pecos | 2.22 | 7.00 | 344 | 2,171 |
| Hutchinson | 2.22 | 4.88 | 55 | 452 |
| Culberson | 2.21 | 6.44 | 136 | 1,733 |
| Reeves | 2.19 | 8.27 | 352 | 1,234 |
| Nolan | 2.13 | 2.93 | 5 | 449 |
| Cochran | 2.11 | 4.59 | 37 | 383 |
| Erath | 2.10 | 3.06 | 5 | 538 |
| Kleberg | 1.92 | 6.26 | 193 | 538 |
| Aransas | 1.87 | 4.01 | 116 | 286 |
| Willacy | 1.87 | 5.25 | 204 | 396 |
| Duval | 1.80 | 3.61 | 22 | 852 |
| Taylor | 1.74 | 2.83 | 5 | 455 |
| Kenedy | 1.65 | 5.22 | 330 | 918 |
| Collin | 1.61 | 4.62 | 42 | 449 |
| Jim Wells | 1.59 | 8.12 | 117 | 444 |
| Winkler | 1.54 | 5.19 | 33 | 409 |
| Brooks | 1.49 | 4.03 | 152 | 464 |
| Galveston | 1.49 | 4.23 | 108 | 457 |
| Sabine | 1.27 | 1.84 | 89 | 316 |
| Upton | 1.15 | 2.26 | 12 | 590 |
| Ector | 0.90 | 1.23 | 7 | 436 |
| Rockwall | 0.87 | 1.09 | 21 | 86 |
| Hunt | 0.63 | 1.07 | 18 | 452 |

### River flood depth at 25 years by city: Fremont, California

The summary of crc-docs' flood_risk_by_province notebook, from crc-sdk's output of this run: each row's curve read at 25 years, the largest value per H3 resolution-10 cell, cells at or above 0.5 m (4,201 of 6,465 cells with a curve), then mean and largest per city; a cell on a border counts in each city it overlaps. Boundaries: City of Fremont: U.S. Census Bureau TIGERweb incorporated places (BAS 2026).

| City | Mean depth of those cells (m) | Largest (m) | Cells at or above 0.5 m | Cells of the city |
| --- | --- | --- | --- | --- |
| Fremont | 1.72 | 20.11 | 1,922 | 15,040 |

### River flood depth at 25 years by state: Rhine, Bonn to Mainz

The summary of crc-docs' flood_risk_by_province notebook, from crc-sdk's output of this run: each row's curve read at 25 years, the largest value per H3 resolution-7 cell, cells at or above 0.5 m (743 of 751 cells with a curve), then mean and largest per state; a cell on a border counts in each state it overlaps. Boundaries: German states: geoBoundaries ADM1, simplified, commit 9469f09 (the notebook's file).

| State | Mean depth of those cells (m) | Largest (m) | Cells at or above 0.5 m | Cells of the state |
| --- | --- | --- | --- | --- |
| Rheinland-Pfalz | 7.68 | 21.86 | 508 | 4,507 |
| Nordrhein-Westfalen | 7.27 | 16.05 | 98 | 7,908 |
| Hessen | 5.34 | 15.39 | 206 | 4,835 |

### The crc-docs notebook's saved numbers against this run (Rhine box)

Notebook outputs as saved at crc-docs c6f78fb. Same box, dataset, policy, resolution, return period and threshold.

| Number | Notebook, saved output | This run |
| --- | --- | --- |
| Curve rows crc-sdk returned | 154,532 | 154,825 |
| Cells at or above 0.5 m | 742 | 743 |
| Rheinland-Pfalz: mean depth (m) | 7.68 | 7.68 |
| Rheinland-Pfalz: largest depth (m) | 21.86 | 21.86 |
| Rheinland-Pfalz: cells | 508 | 508 |
| Nordrhein-Westfalen: mean depth (m) | 7.27 | 7.27 |
| Nordrhein-Westfalen: largest depth (m) | 16.05 | 16.05 |
| Nordrhein-Westfalen: cells | 98 | 98 |
| Hessen: mean depth (m) | 5.36 | 5.34 |
| Hessen: largest depth (m) | 15.39 | 15.39 |
| Hessen: cells | 205 | 206 |
| Places in those cells | 62,717 Overture places (release 2026-08-19.0, no longer hosted): not reproduced | not computed |

## Comparisons with outside evidence (no verdict)

Numbers beside data from other publishers, with their limits. They are not checks and carry no outcome.

### FEMA flood zones against the 100-year map: Houston

Every GloFAS pixel of the box is set against the FEMA zone that holds its centre. FEMA's 1 percent annual chance zones are the A zones (called riverine here) and the V zones (coastal); the 0.2 percent zone is zone X so labelled. GloFAS 'flooded' is a published depth at that return period on a pixel outside JRC's permanent-water layer.

| Number | Value |
| --- | --- |
| Pixels in the box | 1,298,281 |
| In JRC's permanent water (left out below) | 38,335 |
| In a FEMA A zone | 300,066 |
| In a FEMA V zone (coastal) | 16,017 |
| In FEMA's 0.2 percent zone | 128,065 |
| Flooded in GloFAS at 100 years | 202,541 |
| Flooded at 100 years and in an A zone | 106,577 |
| ... as a share of the A-zone pixels | 35.5% |
| ... as a share of the GloFAS pixels | 52.6% |
| Flooded at 100 years, outside A and V zones | 94,983 |
| In an A zone, dry in GloFAS at 100 years | 193,489 |
| Flooded at 500 years | 240,912 |
| ... of those, in an A, V or 0.2 percent zone | 55.5% |
| Flooded pixels with a depth at fewer than four return periods (no curve in crc-sdk) | 44,732 |
| ... of those, in an A zone | 20.7% |
| ... of those, in an A, V or 0.2 percent zone | 30.4% |
| Flooded pixels with four or more depths | 196,180 |
| ... of those, in an A zone | 53.6% |
| ... of those, in an A, V or 0.2 percent zone | 61.2% |

Limits:

- GloFAS models large rivers without flood defences; FEMA zones also cover small streams, ponding and, in A zones near the coast, storm surge. Much of the disagreement is a difference of scope.
- FEMA zones are regulatory maps of different dates per panel; the 1 percent zone is not a depth.
- The zone polygons were generalised by the service to about 1 m and 431 of 21289 are not valid polygons after that; they were rasterised as they came.
- A pixel is about 90 m; a zone narrower than that can be missed.

Evidence: FEMA National Flood Hazard Layer, flood hazard zones (layer 28); retrieved 2026-11-23; none stated by the service; a U.S. federal government work.

### USGS gauge peaks against the map's depth at the gauge: Houston

For each stream gauge in the box: its annual peak stages, the NWS minor flood stage where NWS has the gauge, and the largest GloFAS depth within three pixels (about 270 m) of the gauge at 10, 100 and 500 years, on pixels outside JRC's permanent-water layer (where the map holds a patch value). 'Above flood stage' is a peak stage minus the minor flood stage, in metres.

| Number | Value |
| --- | --- |
| Stream gauges with annual peaks | 107 |
| With GloFAS water within 270 m at 100 years | 38 |
| With an NWS minor flood stage and a peak stage | 31 |
| With both | 17 |
| Those with both: median of the record's highest stage above flood stage (m) | 4.23 |
| Those with both: median GloFAS depth at 100 years (m) | 5.21 |
| Those with both: median GloFAS depth at 500 years (m) | 5.67 |
| With an NWS flood stage and no GloFAS water within 270 m at 100 years | 14 |
| Gauges with a Harvey peak stage and an NWS major flood stage | 27 |
| ... where the Harvey peak was above the major flood stage | 24 |
| Gauges listed in USGS SIR 2018-5070, table 3 | 41 |
| ... with a Harvey peak rarer than 1 percent a year | 19 |
| ... with a Harvey peak rarer than 0.2 percent a year | 1 |

Limits:

- A gauge stage is a height above the gauge's own datum, not a depth of water over land. Stage above the NWS flood stage is used as a rough stand-in for depth over the banks; it is not the same quantity as a GloFAS depth, which at a channel pixel includes the channel.
- Whether the NWS stage scale and the USGS gage height share a datum at each gauge was not checked.
- Both rivers are regulated (reservoirs upstream of Houston and Austin); the record is not stationary. A record of a few decades says little about 100 and 500 years.
- The largest depth within 270 m may belong to a neighbouring channel.

Evidence: USGS NWIS annual peaks (stage and streamflow); NOAA NWPS flood stages; USGS SIR 2018-5070, table 3; retrieved 2026-11-17; U.S. public domain (USGS); attribution requested; peaks may be provisional.

### High-water marks of Hurricane Harvey (2017) against the map: Houston

For each surveyed high-water mark with a height above ground: the GloFAS depth of the pixel that holds the mark, at 100 and 500 years. Quartiles are the 25th, 50th and 75th percentiles.

| Number | Value |
| --- | --- |
| High-water marks of Harvey in the box | 829 |
| Riverine / coastal | 715 / 114 |
| With a height above ground | 694 |
| ... height above ground: quartiles (m) | 0.00, 0.25, 0.85 |
| ... on a pixel GloFAS floods at 100 years | 195 |
| ... on a pixel GloFAS floods at 500 years | 215 |
| ... on a pixel dry in GloFAS at 500 years | 479 |
| Marks on a dry pixel: height above ground, quartiles (m) | 0.00, 0.20, 0.81 |
| Marks on a 100-year pixel: mark height, quartiles (m) | 0.00, 0.34, 1.06 |
| Marks on a 100-year pixel: GloFAS depth, quartiles (m) | 0.55, 1.16, 2.74 |
| Marks on a 100-year pixel: mark minus GloFAS, quartiles (m) | -2.13, -1.00, -0.19 |
| Marks on a 100-year pixel: mark higher than GloFAS | 42 of 195 |
| Marks on a 500-year pixel: mark height, quartiles (m) | 0.00, 0.30, 1.02 |
| Marks on a 500-year pixel: GloFAS depth, quartiles (m) | 0.69, 1.33, 3.04 |
| Marks on a 500-year pixel: mark minus GloFAS, quartiles (m) | -2.56, -1.20, -0.29 |
| Marks on a 500-year pixel: mark higher than GloFAS | 45 of 215 |
| Marks with a height that lie in JRC's permanent water | 16 |

Limits:

- Harvey was a rainfall flood: bayous, streets and reservoir pools flooded far from the large rivers GloFAS models, so a mark on a pixel that GloFAS leaves dry is expected and is not an error of the map.
- How rare Harvey was differs by place: USGS SIR 2018-5070 gives annual exceedance probabilities from below 0.2 to 14 percent at 74 gauges (docs/validation/references/usgs-sir-2018-5070). It is not one return period.
- A mark's height above ground is at one point; a pixel is about 90 m and its depth is over a 90 m terrain model, which in a channel includes the channel.
- Marks are where surveyors went, mostly where water was; they do not sample dry places.

Evidence: USGS Short-Term Network, event '2017 Harvey', high-water marks in Texas; retrieved 2026-11-17; U.S. public domain (USGS); attribution requested.

### FEMA flood zones against the 100-year map: Austin

Every GloFAS pixel of the box is set against the FEMA zone that holds its centre. FEMA's 1 percent annual chance zones are the A zones (called riverine here) and the V zones (coastal); the 0.2 percent zone is zone X so labelled. GloFAS 'flooded' is a published depth at that return period on a pixel outside JRC's permanent-water layer.

| Number | Value |
| --- | --- |
| Pixels in the box | 361,201 |
| In JRC's permanent water (left out below) | 7,667 |
| In a FEMA A zone | 42,016 |
| In a FEMA V zone (coastal) | 0 |
| In FEMA's 0.2 percent zone | 10,607 |
| Flooded in GloFAS at 100 years | 16,227 |
| Flooded at 100 years and in an A zone | 8,715 |
| ... as a share of the A-zone pixels | 20.7% |
| ... as a share of the GloFAS pixels | 53.7% |
| Flooded at 100 years, outside A and V zones | 7,512 |
| In an A zone, dry in GloFAS at 100 years | 33,301 |
| Flooded at 500 years | 17,827 |
| ... of those, in an A, V or 0.2 percent zone | 86.6% |
| Flooded pixels with a depth at fewer than four return periods (no curve in crc-sdk) | 1,910 |
| ... of those, in an A zone | 37.2% |
| ... of those, in an A, V or 0.2 percent zone | 63.8% |
| Flooded pixels with four or more depths | 15,917 |
| ... of those, in an A zone | 54.1% |
| ... of those, in an A, V or 0.2 percent zone | 89.3% |

Limits:

- GloFAS models large rivers without flood defences; FEMA zones also cover small streams, ponding and, in A zones near the coast, storm surge. Much of the disagreement is a difference of scope.
- FEMA zones are regulatory maps of different dates per panel; the 1 percent zone is not a depth.
- The zone polygons were generalised by the service to about 1 m and 606 of 7071 are not valid polygons after that; they were rasterised as they came.
- A pixel is about 90 m; a zone narrower than that can be missed.

Evidence: FEMA National Flood Hazard Layer, flood hazard zones (layer 28); retrieved 2026-11-17; none stated by the service; a U.S. federal government work.

### USGS gauge peaks against the map's depth at the gauge: Austin

For each stream gauge in the box: its annual peak stages, the NWS minor flood stage where NWS has the gauge, and the largest GloFAS depth within three pixels (about 270 m) of the gauge at 10, 100 and 500 years, on pixels outside JRC's permanent-water layer (where the map holds a patch value). 'Above flood stage' is a peak stage minus the minor flood stage, in metres.

| Number | Value |
| --- | --- |
| Stream gauges with annual peaks | 58 |
| With GloFAS water within 270 m at 100 years | 10 |
| With an NWS minor flood stage and a peak stage | 9 |
| With both | 2 |
| Those with both: median of the record's highest stage above flood stage (m) | 5.5 |
| Those with both: median GloFAS depth at 100 years (m) | 7.8 |
| Those with both: median GloFAS depth at 500 years (m) | 8.4 |
| With an NWS flood stage and no GloFAS water within 270 m at 100 years | 7 |
| Gauges with a Harvey peak stage and an NWS major flood stage | 4 |
| ... where the Harvey peak was above the major flood stage | 0 |
| Gauges listed in USGS SIR 2018-5070, table 3 | 0 |
| ... with a Harvey peak rarer than 1 percent a year | 0 |
| ... with a Harvey peak rarer than 0.2 percent a year | 0 |

Limits:

- A gauge stage is a height above the gauge's own datum, not a depth of water over land. Stage above the NWS flood stage is used as a rough stand-in for depth over the banks; it is not the same quantity as a GloFAS depth, which at a channel pixel includes the channel.
- Whether the NWS stage scale and the USGS gage height share a datum at each gauge was not checked.
- Both rivers are regulated (reservoirs upstream of Houston and Austin); the record is not stationary. A record of a few decades says little about 100 and 500 years.
- The largest depth within 270 m may belong to a neighbouring channel.

Evidence: USGS NWIS annual peaks (stage and streamflow); NOAA NWPS flood stages; USGS SIR 2018-5070, table 3; retrieved 2026-11-17; U.S. public domain (USGS); attribution requested; peaks may be provisional.

### FEMA flood zones against the 100-year map: Fremont, California

Every GloFAS pixel of the box is set against the FEMA zone that holds its centre. FEMA's 1 percent annual chance zones are the A zones (called riverine here) and the V zones (coastal); the 0.2 percent zone is zone X so labelled. GloFAS 'flooded' is a published depth at that return period on a pixel outside JRC's permanent-water layer.

| Number | Value |
| --- | --- |
| Pixels in the box | 87,001 |
| In JRC's permanent water (left out below) | 3,983 |
| In a FEMA A zone | 23,585 |
| In a FEMA V zone (coastal) | 5,832 |
| In FEMA's 0.2 percent zone | 5,120 |
| Flooded in GloFAS at 100 years | 6,140 |
| Flooded at 100 years and in an A zone | 2,747 |
| ... as a share of the A-zone pixels | 11.6% |
| ... as a share of the GloFAS pixels | 44.7% |
| Flooded at 100 years, outside A and V zones | 3,071 |
| In an A zone, dry in GloFAS at 100 years | 20,838 |
| Flooded at 500 years | 6,927 |
| ... of those, in an A, V or 0.2 percent zone | 54.3% |
| Flooded pixels with a depth at fewer than four return periods (no curve in crc-sdk) | 967 |
| ... of those, in an A zone | 44.8% |
| ... of those, in an A, V or 0.2 percent zone | 59.4% |
| Flooded pixels with four or more depths | 5,960 |
| ... of those, in an A zone | 44.7% |
| ... of those, in an A, V or 0.2 percent zone | 53.5% |

Limits:

- GloFAS models large rivers without flood defences; FEMA zones also cover small streams, ponding and, in A zones near the coast, storm surge. Much of the disagreement is a difference of scope.
- FEMA zones are regulatory maps of different dates per panel; the 1 percent zone is not a depth.
- The zone polygons were generalised by the service to about 1 m and 1 of 718 are not valid polygons after that; they were rasterised as they came.
- A pixel is about 90 m; a zone narrower than that can be missed.

Evidence: FEMA National Flood Hazard Layer, flood hazard zones (layer 28); retrieved 2026-11-17; none stated by the service; a U.S. federal government work.

GloFAS is assessed in the Texas box, in close-ups of Houston and Austin and in a box around Fremont, California; EFAS in the Rhine box of crc-docs' flood_risk_by_province notebook. Every run uses all published return periods, the curated policy and a cache. A stream run (no cache), a subset of return periods, other policies and `for_assets` were not run.

## What the framework does (transformation statement)

| Step | What crc-sdk does | Code | Outcome |
| --- | --- | --- | --- |
| release | Reads the release from the publisher's README.txt (the text after 'Dataset version') and refuses to run when it is not the one written in the code (GloFAS 2.1.2, EFAS 3.1.1). The file addresses hold no version. | crc_sdk/providers/jrc.py:83-110, 155-176 | **confirmed** |
| periods | Offers the return periods written in the code: 10, 20, 50, 75, 100, 200 and 500 years for GloFAS, and also 30 and 40 for EFAS. The publisher's directory is not read. | crc_sdk/providers/jrc.py:93, 102; crc_sdk/workflows/jrc.py:92-106 | **confirmed** |
| tiles | For GloFAS, takes every tile of the publisher's tile index whose extent meets the box, tiles that only touch it included; one depth file per tile and return period. For EFAS, takes the one raster of Europe per return period, whatever the box. | crc_sdk/providers/jrc.py:186-246 | **confirmed** |
| crop | With a cache, copies from each file the window of every pixel the box touches into a local GeoTIFF, values unchanged, and fits from those copies. A tile the box does not reach is left out. | crc_sdk/workflows/jrc.py:151-161, 396-447; crc_sdk/connectors/duckdb/geotiff.py:283-312, 434-462 | **confirmed** |
| manifest | Writes a manifest in the cache with the release, the time it was resolved, the box, the return periods, each file's address and the SHA-256 of each local copy. No checksum of the publisher's file is taken, and a later run that finds the manifest does not ask the publisher again. | crc_sdk/workflows/jrc.py:109-132, 362-365, 449-465 | **confirmed**. The contents of the manifest and its checksums are confirmed. That a later run does not ask the publisher again is read in the code; it was not run with the network off. |
| coverage | A box outside the raster gives no crop; when no file reaches the box the run ends with LookupError 'no JRC resources intersect area' (with a cache). The message does not name the dataset's extent. | crc_sdk/workflows/jrc.py:156-159, 439-441, 516-517; crc_sdk/connectors/duckdb/geotiff.py:289-292 | **confirmed**. Run with a cache. Without one (stream mode) the code raises a different error, ValueError 'bounds do not intersect the raster'; that mode was not run. |
| nodata | A pixel equal to the file's nodata value (-9999), or not finite, has no depth at that return period. A pixel with no depth at any return period is skipped. | crc_sdk/connectors/duckdb/geotiff.py:676-687 | **differs** |
| knots | Fits a curve only to a pixel that has a depth at four or more return periods. Other pixels get no row and no message (the curated policy writes no diagnostics file). | crc_sdk/connectors/adapters.py:658-663; crc_sdk/workflows/jrc.py:57-81 | **differs** |
| fit | Fits a Gumbel distribution by least squares to the pixel's depths at their return periods (probability 1 - 1/T). The curated policy sets no limit on the misfit. | crc_sdk/connectors/adapters.py:392-459, 696-701; crc_sdk/workflows/jrc.py:50-56 | **differs** |
| fit-failure | A pixel whose depths are all equal, or decrease from one return period to the next, cannot be fitted and is skipped without a message (`on_fit_failure = "skip"`). | crc_sdk/connectors/adapters.py:702-726; crc_sdk/workflows/jrc.py:53 | **differs** |
| cells | Gives each fitted pixel one row for every H3 cell its square overlaps, at the resolution asked for (`native` means 10). Rows of one cell are not combined: reducing them to one value per cell is left to the caller. | crc_sdk/connectors/adapters.py:743-803; crc_sdk/geometry/h3.py:236-260; crc_sdk/workflows/jrc.py:70 | **confirmed**. Compared for a seeded sample of pixels in each area, not for every pixel. |
| source-id | Identifies a pixel by the SHA-256 of the dataset name, the tile and the pixel's row and column. With a cache the row and column are those of the local crop, not of the publisher's file. | crc_sdk/connectors/adapters.py:299-301, 741-743; crc_sdk/providers/jrc.py:248-262; crc_sdk/workflows/jrc.py:502-511 | **confirmed**. Compared for a seeded sample of pixels in each area. |
| labels | Labels every row hazard `RiverineInundation`, pathway `historical`, horizon 0, curve type `gumbel_r`, and the file with the unit m, the release and the return-period range of the inputs. | crc_sdk/providers/jrc.py:43-48, 248-262; crc_sdk/connectors/adapters.py:306-345 | **confirmed** |
| provenance | Writes in the output file a uri naming the dataset, the box (to twelve significant digits), the tiles that gave a curve and the return periods. Licence, attribution, retrieval time and checksum are left empty. | crc_sdk/workflows/jrc.py:135-148, 518-534; crc_sdk/connectors/adapters.py:306-345 | **confirmed** |
| evaluation | Depths at any return period, the published ones included, are read from the fitted curve; the published depths are not kept. | docs/sources/jrc.md:36-40; crc_sdk/connectors/adapters.py:1-40 | **confirmed**. Confirmed in so far as crc-framework's values of the fitted curves equal the reference's at the published return periods and at 25 and 250 years, for a seeded sample of pixels. How far the curve lies from the published depths is reported as exploration, not as a check. |

## Checks

### files

The release, the return periods, the address and the layout crc-sdk states for the dataset, against the release in the publisher's README.txt and the return periods its directory holds depth files for. Steps: release, periods. Tolerance: values: identical.

| Check | Outcome | Result |
| --- | --- | --- |
| files[efas] | confirmed | release 3.1.1, return periods 10, 20, 30, 40, 50, 75, 100, 200, 500; 5 items compared, 0 differ |
| files[glofas] | confirmed | release 2.1.2, return periods 10, 20, 50, 75, 100, 200, 500; 5 items compared, 0 differ |

### manifest

crc-sdk's cache manifest against the reference: the tiles (those of the publisher's tile index that meet the box and hold a pixel of it), each file's address, the release, the box, the return periods, and each recorded checksum against the SHA-256 of the cropped file, recomputed. Steps: tiles, manifest. Tolerance: values: identical.

| Check | Outcome | Result |
| --- | --- | --- |
| manifest[glofas-tx] | confirmed | 4 of 4 tiles meeting the box hold a pixel of it; 28 crops, 0 items differ; checksum of the publisher's file recorded: no |
| manifest[glofas-houston] | confirmed | 2 of 2 tiles meeting the box hold a pixel of it; 14 crops, 0 items differ; checksum of the publisher's file recorded: no |
| manifest[glofas-austin] | confirmed | 2 of 2 tiles meeting the box hold a pixel of it; 14 crops, 0 items differ; checksum of the publisher's file recorded: no |
| manifest[glofas-fremont] | confirmed | 1 of 1 tiles meeting the box hold a pixel of it; 7 crops, 0 items differ; checksum of the publisher's file recorded: no |
| manifest[efas-rhine] | confirmed | 1 of 1 tiles meeting the box hold a pixel of it; 9 crops, 0 items differ; checksum of the publisher's file recorded: no |

### crop

Every pixel of the local GeoTIFFs crc-sdk cropped for the box, read with the reference's own TIFF reader, against the same window of the publisher's file downloaded whole (the window of every pixel the box touches), bit for bit; and the crop's origin, shape, pixel size, type and nodata value against the window's. Steps: crop, nodata. Tolerance: values: identical bits.

| Check | Outcome | Result |
| --- | --- | --- |
| crop[glofas-tx] | confirmed | 1,412,302,514 pixel values compared (4 tiles, 7 return periods), 0 differ; 4 of 4 crops on the expected window |
| crop[glofas-houston] | confirmed | 9,087,967 pixel values compared (2 tiles, 7 return periods), 0 differ; 2 of 2 crops on the expected window |
| crop[glofas-austin] | confirmed | 2,528,407 pixel values compared (2 tiles, 7 return periods), 0 differ; 2 of 2 crops on the expected window |
| crop[glofas-fremont] | confirmed | 609,007 pixel values compared (1 tiles, 7 return periods), 0 differ; 1 of 1 crops on the expected window |
| crop[efas-rhine] | confirmed | 23,357,169 pixel values compared (1 tiles, 9 return periods), 0 differ; 1 of 1 crops on the expected window |

### curves

Every pixel of the box. Which pixels get a curve (four or more depths, not all equal, none lower than at a shorter return period), and the location and scale of each Gumbel curve, fitted by the reference in closed form (least squares on -ln(-ln(1 - 1/T))) from the publisher's files, against the rows of crc-sdk's output placed on the publisher's pixel grid by their geometry. Steps: nodata, knots, fit, fit-failure. Tolerance: location, scale: 1e-06 m; set of pixels: identical.

| Check | Outcome | Result |
| --- | --- | --- |
| curves[glofas-tx] | differs | 9,853,959 curves against 9,851,138; only in the reference 2,821, only in crc-sdk 0; 19,702,276 parameters compared, 2 differ by more than 1e-06 m (largest 1.1e-06); of 11,686,210 pixels with a depth, no curve for 1,832,251 |
| curves[glofas-houston] | differs | 212,949 curves against 212,867; only in the reference 82, only in crc-sdk 0; 425,734 parameters compared, 0 differ by more than 1e-06 m (largest 1.2e-07); of 278,654 pixels with a depth, no curve for 65,705 |
| curves[glofas-austin] | confirmed | 22,201 curves against 22,201; only in the reference 0, only in crc-sdk 0; 44,402 parameters compared, 0 differ by more than 1e-06 m (largest 6.0e-08); of 25,494 pixels with a depth, no curve for 3,293 |
| curves[glofas-fremont] | differs | 7,869 curves against 7,864; only in the reference 5, only in crc-sdk 0; 15,728 parameters compared, 0 differ by more than 1e-06 m (largest 3.7e-08); of 10,603 pixels with a depth, no curve for 2,734 |
| curves[efas-rhine] | differs | 143,074 curves against 143,025; only in the reference 49, only in crc-sdk 0; 286,050 parameters compared, 0 differ by more than 1e-06 m (largest 1.4e-07); of 161,898 pixels with a depth, no curve for 18,824 |

### values

For a seeded sample of fitted pixels: the depth of crc-sdk's curve at each published return period and at 25 and 250 years, evaluated by crc-framework from crc-sdk's parameters, against the reference's own evaluation of its own fit. Steps: evaluation, fit. Tolerance: depth: 1e-06 m.

| Check | Outcome | Result |
| --- | --- | --- |
| values[glofas-tx] | confirmed | 20,000 pixels, 180,000 depths compared, 0 differ; largest difference 9.0e-08 m |
| values[glofas-houston] | confirmed | 20,000 pixels, 180,000 depths compared, 0 differ; largest difference 6.6e-08 m |
| values[glofas-austin] | confirmed | 20,000 pixels, 180,000 depths compared, 0 differ; largest difference 3.0e-08 m |
| values[glofas-fremont] | confirmed | 7,864 pixels, 70,776 depths compared, 0 differ; largest difference 1.8e-08 m |
| values[efas-rhine] | confirmed | 20,000 pixels, 220,000 depths compared, 0 differ; largest difference 6.1e-08 m |

### cells

For a seeded sample of fitted pixels: the H3 cells of crc-sdk's rows for the pixel, against the cells whose boundary overlaps the pixel's square, found by the reference by testing the cells around the square one by one. Steps: cells. Tolerance: cells: identical set.

| Check | Outcome | Result |
| --- | --- | --- |
| cells[glofas-tx] | confirmed | 2,000 pixels at resolution 7, 2,172 cells; pixels whose cells differ: 0; 1.087 rows per pixel |
| cells[glofas-houston] | confirmed | 2,000 pixels at resolution 9, 3,336 cells; pixels whose cells differ: 0; 1.665 rows per pixel |
| cells[glofas-austin] | confirmed | 2,000 pixels at resolution 9, 3,321 cells; pixels whose cells differ: 0; 1.658 rows per pixel |
| cells[glofas-fremont] | confirmed | 2,000 pixels at resolution 10, 5,991 cells; pixels whose cells differ: 0; 3.014 rows per pixel |
| cells[efas-rhine] | confirmed | 2,000 pixels at resolution 7, 2,142 cells; pixels whose cells differ: 0; 1.083 rows per pixel |

### source-id

For the same sample: crc-sdk's identifier of the pixel against the SHA-256 the reference computes from the dataset name, the tile and the pixel's row and column in the local crop. Also counted: how many identifiers equal the one computed from the row and column in the publisher's file. Steps: source-id. Tolerance: identifier: identical text.

| Check | Outcome | Result |
| --- | --- | --- |
| source-id[glofas-tx] | confirmed | 2,000 identifiers, 0 differ from the crop position; equal to the position in the publisher's file: 621 |
| source-id[glofas-houston] | confirmed | 2,000 identifiers, 0 differ from the crop position; equal to the position in the publisher's file: 0 |
| source-id[glofas-austin] | confirmed | 2,000 identifiers, 0 differ from the crop position; equal to the position in the publisher's file: 0 |
| source-id[glofas-fremont] | confirmed | 2,000 identifiers, 0 differ from the crop position; equal to the position in the publisher's file: 0 |
| source-id[efas-rhine] | confirmed | 2,000 identifiers, 0 differ from the crop position; equal to the position in the publisher's file: 0 |

### labels

The labels of every row (hazard, pathway, horizon, curve type) and of the file (unit, release, return-period range of the inputs, H3 resolution) against the statement and the publisher's README.txt. Steps: labels. Tolerance: labels: identical.

| Check | Outcome | Result |
| --- | --- | --- |
| labels[glofas-tx] | confirmed | 10,703,386 rows; labels wrong: none |
| labels[glofas-houston] | confirmed | 354,477 rows; labels wrong: none |
| labels[glofas-austin] | confirmed | 36,803 rows; labels wrong: none |
| labels[glofas-fremont] | confirmed | 23,702 rows; labels wrong: none |
| labels[efas-rhine] | confirmed | 154,825 rows; labels wrong: none |

### provenance

The source block of the output file's metadata: its uri against the dataset, the box, the tiles that gave a curve and the return periods; and whether licence, attribution, retrieval time and checksum are empty, as the statement says. Steps: provenance. Tolerance: values: identical.

| Check | Outcome | Result |
| --- | --- | --- |
| provenance[glofas-tx] | confirmed | uri wrong: nothing; empty: licence, attribution, retrieved_at, checksum; the publisher's README names the licence 'Open Data Commons Open Database License v1.0' |
| provenance[glofas-houston] | confirmed | uri wrong: nothing; empty: licence, attribution, retrieved_at, checksum; the publisher's README names the licence 'Open Data Commons Open Database License v1.0' |
| provenance[glofas-austin] | confirmed | uri wrong: nothing; empty: licence, attribution, retrieved_at, checksum; the publisher's README names the licence 'Open Data Commons Open Database License v1.0' |
| provenance[glofas-fremont] | confirmed | uri wrong: nothing; empty: licence, attribution, retrieved_at, checksum; the publisher's README names the licence 'Open Data Commons Open Database License v1.0' |
| provenance[efas-rhine] | confirmed | uri wrong: nothing; empty: licence, attribution, retrieved_at, checksum; the publisher's README names the licence 'Open Data Commons Open Database License v1.0' |

### coverage

A box outside the dataset's raster: whether the reference finds a pixel of the publisher's file in the box, against what crc-sdk does when asked for it with a cache (the statement: LookupError 'no JRC resources intersect area'). Steps: coverage. Tolerance: outcome: as stated.

| Check | Outcome | Result |
| --- | --- | --- |
| coverage[efas-tx] | confirmed | pixels of the raster in the box: 0; crc-sdk: LookupError: no JRC resources intersect area (-106.645646, 25.837377, -93.508292, 36.500704); the message names the extent: no |
| coverage[efas-fremont] | confirmed | pixels of the raster in the box: 0; crc-sdk: LookupError: no JRC resources intersect area (-122.15, 37.42, -121.85, 37.62); the message names the extent: no |

## Inputs

| Role | File | SHA-256 | Retrieved |
| --- | --- | --- | --- |
| reference download | flood_hazard | c94df55469b009667f326e5e1cefc76b1a18b3c0bb9c29a552f2fa0306e91266 | 2026-11-23T18:26:26Z |
| crc-sdk (its configuration and README.txt) | README.txt |  |  |
| reference download | flood_hazard | 028537820008f548f974cc61c8bccece14d8cfa79d2eada566a924e050cd0c71 | 2026-11-23T18:26:28Z |
| crc-sdk (its configuration and README.txt) | README.txt |  |  |
| crc-sdk (GDAL over the network, cropped into its cache) | flood_hazard |  |  |
| crc-sdk (GDAL over the network, cropped into its cache) | flood_hazard |  |  |
| crc-sdk (GDAL over the network) | flood_hazard |  |  |

## Findings

| Id | Kind | Finding | Basis | Status |
| --- | --- | --- | --- | --- |
| CRC-003-JRC | doc-code difference | JRC flood and EDO output files do not carry licence, attribution, retrieval time or checksum | reproduced | open |
| CRC-014-JRC | observation | A pixel the publisher shows flooded gets no curve, and no message, when it has fewer than four depths, equal depths or a decreasing depth | reproduced | open |
| CRC-015-JRC | observation | The fitted curve can be positive where the publisher's map is dry, below zero where it is wet, and metres away from the published depth | reproduced | open |
| CRC-016-JRC | observation | A request outside a dataset's coverage ends with an error that does not name the coverage, and the error differs with the cache mode | reproduced | open |
| CRC-017-JRC | observation | The release is identified by one line of the publisher's README; the file addresses hold no version and no publisher checksum is taken | reproduced | open |
| CRC-018-JRC | doc-code difference | crc-sdk states CC BY 4.0 for the JRC flood maps; the publisher's README names the Open Database License | reproduced | open |
| CRC-019-JRC | observation | The publisher's masks of spurious depths and permanent water are not read | reproduced | open |
| CRC-020-JRC | observation | With a cache, a pixel's source_id depends on the box asked for | reproduced | open |
| CRC-021-JRC | defect | A cache made under a relative path cannot be read offline from another working folder | reproduced | open |
| CRC-022-JRC | observation | A state-sized box is fitted pixel by pixel in one process: 27 minutes and 5.8 GB of memory for the Texas box | reproduced | open |

Details are in [the inventory](../inventory.md#findings).

## What this does not cover

- A `confirmed` outcome holds for these files, these options and crc-framework 0.6.0, crc-sdk 0.11.2.
- Verification says nothing about whether the publisher's values are right.
- Validation (fitness for a stated use) is not assessed.
