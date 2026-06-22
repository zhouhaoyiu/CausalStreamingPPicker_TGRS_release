# FDSN Continuous Strong-Motion Station-Day Campaign

## Protocol

- Waveform provider: `SCEDC`
- Event provider: `USGS`
- Network/stations: `CI` / `PASC,SVD,USC,WTT2,CAC,FON,CFS,CJV2,LAF,LDR`
- Starts: `2024-06-18T00:00:00`, `2024-07-23T00:00:00`, `2024-08-28T00:00:00`, `2024-09-17T00:00:00`, `2024-10-22T00:00:00`, `2024-11-19T00:00:00`, `2024-12-10T00:00:00`
- Duration per station per start: 1.00 h
- Event screen: M >= 3.0
- Reset chunks: 320

This campaign uses public FDSN chronological strong-motion acceleration
streams. It is stronger than clip-based station-time replay, but still a
bounded public-data check rather than full operational certification.

Catalog events found during screened intervals: 0

## Working Operating Point

| Gate | Valid h | Station-time days | Episodes | False triggers/h | False triggers per station day |
|---|---:|---:|---:|---:|---:|
| none | 69.55 | 2.90 | 28 | 0.403 | 9.66 |
| peak12_width2 | 69.55 | 2.90 | 28 | 0.403 | 9.66 |
| peak12_width8 | 69.55 | 2.90 | 25 | 0.359 | 8.63 |

## Multi-Station Time Coincidence

| Gate | N stations | Window | Coincidences | Coincidences per station day |
|---|---:|---:|---:|---:|
| none | 2 | 3.0 s | 1 | 0.35 |
| none | 2 | 5.0 s | 1 | 0.35 |
| none | 3 | 3.0 s | 0 | 0.00 |
| none | 3 | 5.0 s | 0 | 0.00 |
| peak12_width2 | 2 | 3.0 s | 1 | 0.35 |
| peak12_width2 | 2 | 5.0 s | 1 | 0.35 |
| peak12_width2 | 3 | 3.0 s | 0 | 0.00 |
| peak12_width2 | 3 | 5.0 s | 0 | 0.00 |
| peak12_width8 | 2 | 3.0 s | 1 | 0.35 |
| peak12_width8 | 2 | 5.0 s | 1 | 0.35 |
| peak12_width8 | 3 | 3.0 s | 0 | 0.00 |
| peak12_width8 | 3 | 5.0 s | 0 | 0.00 |
