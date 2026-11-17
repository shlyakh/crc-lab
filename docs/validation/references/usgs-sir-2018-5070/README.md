# USGS Scientific Investigations Report 2018-5070: flood peaks of Hurricane Harvey

Kept so that the comparison of JRC's flood maps with Harvey's high-water marks and gauge peaks
(`docs/validation/reports/V8.3-jrc-flood-outside-evidence.md`) can be checked against the text it
cites for how rare that flood was.

| File | What it is | SHA-256 |
| --- | --- | --- |
| `sir20185070.txt` | Text extracted with `pdftotext -layout` from the report's PDF, for searching and for reading table 3. The PDF is the reference; it is 13.6 MB and is not kept here. | PDF: `633dfa3957db1258007d90deed5ed679ed9d23caf1577c02eeb062fff8eb569b` |

- Watson, K.M., Harwell, G.R., Wallace, D.S., Welborn, T.L., Stengel, V.G., and McDowell, J.S., 2018,
  *Characterization of peak streamflows and flood inundation of selected areas in southeastern Texas
  and southwestern Louisiana from the August and September 2017 flood resulting from Hurricane
  Harvey*: U.S. Geological Survey Scientific Investigations Report 2018-5070. Prepared in
  cooperation with the Federal Emergency Management Agency.
- Source: <https://pubs.usgs.gov/sir/2018/5070/sir20185070.pdf>, downloaded 2026-11-17.
- A publication of a U.S. federal agency. The cover photographs are credited to others and are not
  reproduced here (text only).
- Only the abstract and table 3 were read. The inundation maps were not examined.

## Passages the comparison relies on

| Topic | Where | In short |
| --- | --- | --- |
| Stations analysed | Abstract | "Seventy-four USGS streamflow-gaging stations in Texas with at least 15 years of record ... had a 2017 annual peak streamflow related to Harvey ranking in the top five of all annual peaks" |
| Peaks of record | Abstract | "New peaks of record streamflow were recorded at 40 of the 74 USGS streamflow-gaging stations." |
| How rare | Abstract | "The annual exceedance probability estimates for the analyzed streamflow-gaging stations ranged from less than 0.2 to 14.0 percent." |
| Per station | Table 3 | Peak gage height, peak streamflow, rank, years of record and the estimated annual exceedance probability with its 66.7 percent confidence interval |

So the report does not say that Harvey exceeded a 100-year flood everywhere: it gives a probability
per station, from below 0.2 percent (rarer than 1 in 500 years) to 14 percent (about 1 in 7).

Table 3 is read from the text extract by `data_source_check.assessments.jrc_flood_evidence.sir_table`:
71 of the 74 rows have the layout it accepts; the rows of stations 08040600, 08074000 and one other
are broken across lines in the extract and are left out.
