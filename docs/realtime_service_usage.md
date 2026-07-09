# Real-Time P Picker Service Usage

This service exposes the causal streaming P-picker as a small local HTTP API.
The default decision rule matches the manuscript: `p >= 0.55` for two
consecutive packets, with model state reset every 320 packets and the first two
packets after each reset excluded from confirmation.

## Requirements

- Python environment with the project dependencies installed.
- Model checkpoint:
  `models/checkpoints/multidomain_best.pt`

Activate the project environment, then verify the interpreter:

```bash
python --version
```

## Start The Service

From the project root:

```bash
python scripts/demo/realtime_service.py \
  --checkpoint models/checkpoints/multidomain_best.pt \
  --device cpu \
  --host 127.0.0.1 \
  --port 8765
```

Health check:

```bash
curl http://127.0.0.1:8765/health
```

## Web Stream Demo

After starting the service, open:

```text
docs/realtime_stream_demo.html
```

The page sends a 221 s synthetic ZNE stream, one 0.5 s packet at a time, to
`http://127.0.0.1:8765/predict`. It plots the waveform and returned P
probability. Real network data should still use the SeedLink client below.

## Device Acceleration Demo

After starting the service, open:

```text
http://127.0.0.1:8765/device-accel-demo
```

This page reads browser `devicemotion` acceleration, packs it into 0.5 s
streaming requests, and plots the live acceleration and P probability. Desktop
Mac browsers usually do not expose an accelerometer; use a phone or tablet
browser for this demo. The device axes are mapped to model input as `z/y/x ->
Z/N/E`, so this page is for interface testing, not seismological validation.

## Input Contract

The service accepts three-component acceleration waveforms and converts them to
the model format:

- target sampling rate: `100 Hz`
- model packet length: `50 samples`, i.e. `0.5 s`
- component order after conversion: `Z, N, E`
- accepted array shapes: `(3, n_samples)` or `(n_samples, 3)`
- session length: `320 packets` (`160 s`); packet position restarts from zero
- confirmation: `2` consecutive non-boundary packets above `0.55`

If fewer than 50 samples arrive, they are buffered. Once enough samples are
available, the service returns one result per 0.5 s packet.

## JSON Example

```bash
curl -X POST http://127.0.0.1:8765/predict \
  -H 'content-type: application/json' \
  -d '{
    "station_id": "STA001",
    "sampling_rate_hz": 100,
    "component_order": "ZNE",
    "scale_factor": 1.0,
    "data": [[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
             [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
             [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]]
  }'
```

## CSV Example

CSV may be one row per sample:

```text
Z,N,E
0.01,0.02,0.03
0.01,0.02,0.03
...
```

Send it with:

```bash
curl -X POST \
  'http://127.0.0.1:8765/predict?station_id=STA001&sampling_rate_hz=100&component_order=ZNE&format=csv' \
  -H 'content-type: text/csv' \
  --data-binary @packet.csv
```

## NumPy Example

```python
import requests

with open("packet.npy", "rb") as f:
    r = requests.post(
        "http://127.0.0.1:8765/predict"
        "?station_id=STA001&sampling_rate_hz=100&component_order=ZNE&format=npy",
        data=f.read(),
        headers={"content-type": "application/x-npy"},
        timeout=10,
    )
print(r.json())
```

## miniSEED Example

The service supports standard `Z/N/E` channels and K-NET-style `UD/NS/EW`.

```bash
curl -X POST \
  'http://127.0.0.1:8765/predict?format=mseed' \
  -H 'content-type: application/octet-stream' \
  --data-binary @trace.mseed
```

## Continuous Stream From A File

For a continuous test, start the service first:

```bash
python scripts/demo/realtime_service.py \
  --checkpoint models/checkpoints/multidomain_best.pt \
  --device cpu \
  --host 127.0.0.1 \
  --port 8765
```

Then stream a waveform file packet by packet:

```bash
python scripts/demo/realtime_stream_client.py \
  --source data/samples/AOM0122512082315_3comp.mseed \
  --format mseed \
  --url http://127.0.0.1:8765/predict \
  --station-id AOM01 \
  --speed 1
```

`--speed 1` sends packets in real time, one 0.5 s packet every 0.5 s.
Use `--speed 20` for a 20x faster replay, or `--speed 0` for no sleep.

Limit packets during a smoke test:

```bash
python scripts/demo/realtime_stream_client.py \
  --source data/samples/AOM0122512082315_3comp.mseed \
  --format mseed \
  --url http://127.0.0.1:8765/predict \
  --station-id AOM01 \
  --speed 0 \
  --max-packets 20
```

The client prints one JSON line per processed packet.

`--source` means the local waveform file used for replay. It can be a miniSEED,
CSV, `.npy`, or `.npz` file. It is not a real-time network address.

## Real-Time Network Stream Via SeedLink

For a seismic network real-time stream, use the SeedLink client. Start the
picker service first:

```bash
python scripts/demo/realtime_service.py \
  --checkpoint models/checkpoints/multidomain_best.pt \
  --device cpu \
  --host 127.0.0.1 \
  --port 8765
```

Then connect to a SeedLink server:

```bash
python scripts/demo/realtime_seedlink_client.py \
  --server seedlink.example.org:18000 \
  --stream NET.STA.HN? \
  --url http://127.0.0.1:8765/predict
```

`--stream` has the form:

```text
NET.STA.SELECTOR
```

Examples:

```bash
--stream CI.PASC.HN?
--stream BO.AOM01.?
```

Repeat `--stream` for multiple stations:

```bash
python scripts/demo/realtime_seedlink_client.py \
  --server seedlink.example.org:18000 \
  --stream NET1.STA1.HN? \
  --stream NET1.STA2.HN? \
  --url http://127.0.0.1:8765/predict
```

The client maps standard channel suffixes `Z/N/E` and K-NET-style `UD/NS/EW`
to the model input order `ZNE`. It keeps one buffer per `NET.STA`, posts every
complete 0.5 s packet to the service, and resets station state if a channel gap
is detected.

## Response

```json
{
  "station_id": "STA001",
  "threshold": 0.55,
  "confirm_chunks": 2,
  "reset_chunks": 320,
  "boundary_exclude_chunks": 2,
  "packets_processed": 1,
  "buffered_samples": 0,
  "results": [
    {
      "packet_idx": 0,
      "session_packet_idx": 0,
      "time_sec": 0.0,
      "p_probability": 0.0028,
      "candidate": false,
      "confirmed": false,
      "confirmation_streak": 0,
      "boundary_excluded": true,
      "trigger": false
    }
  ]
}
```

`candidate` is the raw single-packet threshold result. `confirmed` remains true
while a run has at least two consecutive positive packets. `trigger` is true
only once, on the packet that first completes the two-packet confirmation.
Boundary packets may still report `candidate=true`, but they cannot confirm or
trigger.

## Reset State

Reset one station:

```bash
curl -X POST 'http://127.0.0.1:8765/reset?station_id=STA001'
```

Reset all stations:

```bash
curl -X POST http://127.0.0.1:8765/reset
```

## Notes

- Use one stable `station_id` per station so the service can keep streaming
  state correctly.
- Keep the default reset and boundary settings when comparing live output with
  the manuscript's CI/FDSN continuous-stream protocol.
- Set `scale_factor` if raw values need conversion to acceleration units.
- If the source sampling rate is not 100 Hz, set `sampling_rate_hz`; the service
  resamples internally.
- This is a local HTTP service, not a public deployment. Use a reverse proxy or
  VPN if it must be exposed outside the machine.
