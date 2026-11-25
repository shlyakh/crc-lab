# Reading list for Yuri: passages only a person can read

Written 2026-11-25, after F2. These are the facts the flood lab still needs from pages that refuse
automated access or that state nothing a program could find. Each entry says where to look, what to bring
back, why it matters and by when. Until a passage is read its value stays a labelled placeholder
(**[P]**) and nothing is stated as the publisher's.

**For each passage bring back four things:** the value; the document's title and date; the page, table
or figure number; and the sentence or table row as written. Paste them in a session and they are entered
in the source's facts file (`src/flood_lab/facts/`) with your name and the date.

## A. Needed for the demo of 1 December

| # | What to read | Link | What to bring back | Why it matters | By |
| --- | --- | --- | --- | --- | --- |
| 1 | Williams et al. 2025, substation flood damage | <https://doi.org/10.1111/jfr3.70045> (Journal of Flood Risk Management; the PDF is at <https://onlinelibrary.wiley.com/doi/pdf/10.1111/jfr3.70045>) | The damage ratios at 3 m depth for "substation", "distribution substation" and "grid exit point". The requirements hold 0.52–0.76, 0.51–0.77 and 0.49–0.70 as reported by another paper, never read at the source. Also the lowest depth at which damage starts | This is the **high** end of the substation damage-curve envelope (FR2). The low end (Hazus-type) gives 16% at 3 m; this one gives about 50 to 77%. The spread between them is the headline uncertainty of the loss figure | Sat 28 Nov (F6) |
| 2 | FEMA project useful life | <https://www.fema.gov/grants/tools/benefit-cost-analysis> ; look for the "BCA Reference Guide" and its Supplement, or the current toolkit's guidance, and in it the table of **project useful life** by mitigation type | The years for **elevation** and for **floodproofing or flood barriers** (and, if listed, for utility or electrical equipment protection) | The benefit-cost ratio (FM4) is the present value of avoided loss over the project's life. Life is one of three placeholders under the ratio; this removes one. The only FEMA figure found so far is 100 years for acquisition, which does not apply | Sun 29 Nov (F7) |
| 3 | FEMA BCA Toolkit, current version | The same page, <https://www.fema.gov/grants/tools/benefit-cost-analysis> | The version number and release date as the page states them. A 2025 snapshot said "Version 6.0, released in 2019"; the 2026 page announces an update on 1 October 2026 with no number we could read | The report names the method it follows; a wrong version number is the kind of slip a reviewer checks first | Sun 29 Nov |
| 4 | Hazus functional depth for substations | <https://www.fema.gov/sites/default/files/documents/fema_hazus-inventory-technical-manual-4.2.3.pdf> (Hazus Inventory Technical Manual 4.2 SP3); find the table of flood **functionality thresholds** for electric power facilities. The requirements call it Table 10-12 | The depth at which a low-voltage and a high-voltage substation stop functioning (we hold 4 ft, unverified), the table's number, and the row as written | It is the outage threshold of FM5: below it the substation is damaged but serving, above it customers lose power | Sun 29 Nov |

If time is short, read 1 and 2. Items 3 and 4 can stay placeholders on Tuesday without changing the
conclusion.

## B. Before anything is shown publicly as "public domain"

No licence statement was found on the pages a program could read, so the lab shows "licence not stated on
the pages read" for these. None blocks the demo. Each needs one sentence from the publisher's terms.

| # | Source | Link | What to look for |
| --- | --- | --- | --- |
| 5 | USGS Ida high-water marks | <https://www.sciencebase.gov/catalog/item/618975c8d34ec04fc9c5a049> | A statement that the data is public domain or how to credit it. The metadata says use constraints "none" |
| 6 | USGS Ida depth rasters | <https://www.sciencebase.gov/catalog/item/63badf22d34e92aad3cd279e> | The same. Its metadata asks for acknowledgement of the USGS |
| 7 | USACE National Structure Inventory | <https://www.hec.usace.army.mil/confluence/nsi/technicalreferences/latest/> | Terms of use or licence for the 2026 Base release (building values come from it) |
| 8 | NOAA Storm Events Database | <https://www.ncei.noaa.gov/access/storm-events-database/> and its FAQ | Terms of use and the attribution NOAA asks for |
| 9 | OpenFEMA NFIP claims | <https://www.fema.gov/about/openfema/terms-conditions> | The terms for reuse and the citation FEMA asks for |
| 10 | NOAA Atlas 14 | <https://hdsc.nws.noaa.gov/pfds/> (the Disclaimer link) | Any copyright or reuse statement |
| 11 | NYC 2017 lidar terrain | <https://data.cityofnewyork.us/d/7sc8-jtbz> | Not used in a committed product; only if it comes to be used |

## C. Not a reading, but yours

| # | What | Where | Why |
| --- | --- | --- | --- |
| 12 | Look at the substation contact sheet | `docs/flood/figures/f1/substation_contact_sheet.png`; then put the date in `src/flood_lab/assets/substation_review.toml` (`person_reviewed_on`) | The F1 record still shows "a person has looked" as not judged. Two calls rest on it: Building 390 removed, the unnamed Williamsburg yard kept |
| 13 | Email the city for a re-export of the Limited Flood map | StormwaterResiliency@cityhall.nyc.gov, dataset NYC Open Data `9i7c-xyvv` | We read the map through ESRI's library, so nothing waits on this. A plain re-export would repair the file for everyone and give a second reading |
| 14 | Storm duration behind the map intensities (1.77, 2.13, 3.66 in/hr) | The same address is the one to ask; it is not published | F3 assumes one hour **[P]** and tests the sensitivity. An answer from the city would replace the assumption |

## What was already tried

For 1 to 4 and 7 to 10 the publishers' sites answered a program with "access denied" or served a page
with no terms in its text. No way round a block was used. Details are on each source's data card under
`docs/flood/data-cards/`.
