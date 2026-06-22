# K-NET Delaunay Association Gate

This post-processing check uses existing single-station K-NET trigger details and K-NET station coordinates. It does not rerun model inference.

## Protocol

- Dataset: K-NET test split, M < 4, source distance <= 200 km.
- Station trigger time: confirmation-completion packet time on the event-window replay axis.
- Plain association: at least `min_stations` distinct stations trigger within a rolling `window_sec` time window.
- Delaunay support: within the same rolling window, a Delaunay-connected station component reaches `min_stations` stations.
- Scope: event-window geometry consistency check. This is not blind hypocenter estimation or chronological station-day alert validation.

## Summary

| threshold | confirm_chunks | min_stations | window_sec | n_events | associated_events | delaunay_supported_events | delaunay_support_among_associated_percent | median_delaunay_delay_from_first_p_sec | p95_delaunay_delay_from_first_p_sec | median_extra_delay_after_plain_assoc_sec |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.550 | 2.000 | 2.000 | 3.000 | 40.000 | 38.000 | 38.000 | 100.000 | 2.250 | 6.650 | 0.000 |
| 0.550 | 2.000 | 2.000 | 5.000 | 40.000 | 38.000 | 38.000 | 100.000 | 2.250 | 6.650 | 0.000 |
| 0.550 | 2.000 | 3.000 | 3.000 | 40.000 | 34.000 | 29.000 | 85.294 | 3.000 | 9.800 | 0.500 |
| 0.550 | 2.000 | 3.000 | 5.000 | 40.000 | 36.000 | 32.000 | 88.889 | 3.500 | 9.450 | 0.500 |

## Output Files

- `knet_lt4_dle200_delaunay_association_events.csv`
- `knet_lt4_dle200_delaunay_association_summary.csv`
- `knet_lt4_dle200_delaunay_association_summary.json`
