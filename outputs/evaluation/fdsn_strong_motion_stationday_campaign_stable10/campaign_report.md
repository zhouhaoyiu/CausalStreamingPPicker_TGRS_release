# FDSN Continuous Strong-Motion Station-Day Campaign

## Protocol

- Waveform provider: `SCEDC`
- Event provider: `USGS`
- Network/stations: `CI` / `PASC,SVD,USC,WTT2,CAC,FON,CFS,CJV2,LAF,LDR`
- Starts: `2024-01-03T00:00:00`, `2024-02-07T00:00:00`, `2024-03-12T00:00:00`, `2024-05-21T00:00:00`
- Duration per station per start: 6.00 h
- Event screen: M >= 3.0
- Reset chunks: 320

This campaign uses public FDSN chronological strong-motion acceleration
streams. It is stronger than clip-based station-time replay, but still a
bounded public-data audit rather than full operational certification.

Catalog events found during screened intervals: 0

## Working Operating Point

| Gate | Valid h | Station-day equiv. | Episodes | FA/h | FA/station-day |
|---|---:|---:|---:|---:|---:|
| none | 238.50 | 9.94 | 79 | 0.331 | 7.95 |
| peak12_width2 | 238.50 | 9.94 | 79 | 0.331 | 7.95 |
| peak12_width8 | 238.50 | 9.94 | 78 | 0.327 | 7.85 |

## Multi-Station Time Coincidence

| Gate | N stations | Window | Clusters | Clusters/station-day equiv. |
|---|---:|---:|---:|---:|
| none | 2 | 3.0 s | 2 | 0.20 |
| none | 2 | 5.0 s | 3 | 0.30 |
| none | 3 | 3.0 s | 0 | 0.00 |
| none | 3 | 5.0 s | 0 | 0.00 |
| peak12_width2 | 2 | 3.0 s | 2 | 0.20 |
| peak12_width2 | 2 | 5.0 s | 3 | 0.30 |
| peak12_width2 | 3 | 3.0 s | 0 | 0.00 |
| peak12_width2 | 3 | 5.0 s | 0 | 0.00 |
| peak12_width8 | 2 | 3.0 s | 2 | 0.20 |
| peak12_width8 | 2 | 5.0 s | 3 | 0.30 |
| peak12_width8 | 3 | 3.0 s | 0 | 0.00 |
| peak12_width8 | 3 | 5.0 s | 0 | 0.00 |
