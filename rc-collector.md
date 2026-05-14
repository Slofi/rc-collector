# RC — Remote Collector

## Overview

Fork of MeshCore RPTR firmware to add identity-bearing passive observations over serial, enabling an attached RP2040/PiZero collector board to build per-node RF intel from a remote vantage point and deliver it to OverMesh over the mesh.

**Linked project:** [OverMesh](/home/slofi/Projects/overmesh/notes.md) — RC observations feed into OM's `passive_obs` system. See "Passive Mesh Intelligence" and "Remote Collector" sections.

**Status:** Active — firmware complete + flashed; needs physical UART wiring + OM parser  
**Repo:** local only — `rc-collector/firmware/` (personal project, no GitHub fork)  
**Hardware target:** nRF52840 + HT-RA62 — primary: T114 v1 (spare, MC-compatible); fallback: Faketec board  
**Collector:** RP2040-PiZero (off-grid) / Pi Pico 2W (urban, WiFi POST to OM API)  
**Build system:** PlatformIO

---

## What it does

A remote RPTR node (elevated, solar-powered) hears MC mesh traffic from a different RF vantage point. One unit delivers two parallel data streams:

**1. Passive Intel (RC)** — identity-bearing observations where the sender is known:
- **Adverts** — full pubkey + SNR/RSSI at `onAdvertRecv()`, after signature validation
- **Anon requests** — sender pubkey available after decrypt
- **Known peer packets** — mapped via ACL client pubkey in `onPeerDataRecv()`/`onPeerPathRecv()`
- **Relayed encrypted traffic** — not possible (only short src/dest hashes at `logRx()` time)

**2. Coverage Mapping** — all heard traffic regardless of identity:
- Every received packet logged with signal quality (RSSI/SNR) and short hash
- Builds a picture of which nodes reach this vantage point and at what signal strength
- Complements RC intel: RC tells you WHO, coverage tells you WHERE the mesh reaches

The attached RP2040/PiZero reads both streams from serial, buffers them, and delivers via `OMCOLLECT` DMs. OM imports into `passive_obs` (intel) and `coverage_obs` (coverage) tagged with `collector_id` and collector position.

**Deployment variants:**
- **Off-grid** (hilltop solar): T114 v1 RPTR + RP2040-PiZero, mesh DM delivery
- **Urban**: T114 v1 RPTR + Pi Pico 2W, direct WiFi POST to OM API

---

## Technical Reference

### Firmware patch plan

**Primary patch point:** `onAdvertRecv(packet, id, ...)` in `examples/simple_repeater/MyMesh.cpp`
- `id.pub_key` — full sender pubkey (after signature validation)
- `packet->getSNR()` — signal quality
- Output format TBD (see Serial Protocol below)

**Secondary patch points:**
- `onAnonDataRecv()` — anon request sender pubkey available post-decrypt
- `onPeerDataRecv()` / `onPeerPathRecv()` — known peer packets via ACL client mapping

**Not patchable generically:** `logRx()` — called too early, before packet decode. Only has short payload hashes for relayed encrypted traffic.

### Serial protocol (proposed, TBD after testing)

```
OBS|<type>|<pubkey_or_hash>|<rssi>|<snr>|<ts_unix>
```

| Type | Source | Identity | Notes |
|------|--------|----------|-------|
| `ADV` | `onAdvertRecv()` | full pubkey | primary RC intel |
| `ANON` | `onAnonDataRecv()` | full pubkey post-decrypt | |
| `PEER` | `onPeerDataRecv/PathRecv()` | full pubkey via ACL | |
| `RX` | `logRx()` | short hash only | coverage mapping |

Examples:
```
OBS|ADV|ee1916ba6f75...|−72|8.25|1778157541
OBS|RX|3a7f|−85|4.50|1778157602
```

### RP2040 collector

- MicroPython script on RP2040-PiZero
- Reads serial lines, parses `OBS|...` entries
- Ring buffer in RAM (or flash if persistent storage needed)
- Responds to `OMCOLLECT` DM from OM: sends buffered observations as compact DMs
- OM imports into `passive_obs` with `collector_id` and collector lat/lon

### Stock RPTR `neighbors` (no firmware patch needed)

`neighbors` command returns up to 8 recent advert neighbors as `pubkey-prefix:secs_ago:snr`. OM can query this remotely over mesh — useful as a lightweight first step before full collector is built. Implement as "Remote Neighbors Pull" in OM.

### Build environment

- PlatformIO (VS Code extension)
- Firmware: cloned to `rc-collector/firmware/` — local fork of `meshcore-dev/MeshCore`
- RC patch commits (firmware sub-repo — local only, no GitHub fork):
  - `fd58e5f2` — OBS|ADV + OBS|RX serial output
  - `a1fde994` — OMCOLLECT DM delivery (OmcollectCtx + RELAY handler)
  - `8ed43a65` — Serial1 hardware UART output (GPIO 9/10)
- Build target: `Heltec_t114_without_display_repeater`
- Flash: `~/.platformio/penv/bin/pio run -e Heltec_t114_without_display_repeater --target upload --upload-port /dev/ttyACM2`
- T114 v1 confirmed working — OBS|ADV tested with real MC node advert (RSSI -58, SNR 11.0)
- T114 currently flashed with `8ed43a65` — all three patches active

### Hardware UART wiring (T114 → RP2040-PiZero)

T114 v1 and v2 are the same physical board. Hardware UART pads confirmed from RS232 bridge variant:

| T114 pad | Direction | RP2040-PiZero |
|----------|-----------|----------------|
| GPIO 10 (TX) | → | GP1 (UART0 RX) |
| GPIO 9 (RX) | ← | GP0 (UART0 TX) |
| GND | — | GND |

Both 3.3V — direct connection, no level shifter needed.

---

## Changelog

### 2026-05-14 — Serial1 hardware UART output added (Session 296)
- `main.cpp` setup: `Serial1.setPins(9, 10); Serial1.begin(115200);` — GPIO 9 (RX), GPIO 10 (TX)
- All RC-specific output (OBS|ADV, OBS|RX, OMCOLLECT trigger) now mirrored to Serial1
- USB Serial preserved for debugging; RP2040 reads from Serial1 hardware UART
- GPIO 9/10 confirmed from RS232 bridge variant in firmware repo; T114 v1 = v2 physically
- Firmware committed `8ed43a65`, built clean, flashed to T114 — confirmed heartbeat on USB serial
- **Next:** wire T114 GPIO 10 (TX) → RP2040 GP1, GPIO 9 (RX) → RP2040 GP0, GND → GND

### 2026-05-14 — OMCOLLECT DM delivery implemented (Session 296)
- T114 firmware patched: `OmcollectCtx` struct stores requester identity/secret/path when OMCOLLECT DM arrives
- `onPeerDataRecv` intercepts "OMCOLLECT" command, writes `OMCOLLECT\n` to serial instead of replying directly
- `handleCommand` handles `RELAY|<line>` from RP2040: creates encrypted TXT_MSG DM per line, floods or sends direct to original requester; clears context on `RELAY|OMCOLLECT_END`
- `collector/main.py` updated: `deliver_relay(uart)` sends `RELAY|OMCOLLECT_START|RC1|N\r` + one `RELAY|OBS|...\r` per entry + `RELAY|OMCOLLECT_END\r`, 250ms between sends for rate limiting
- Dual-direction serial protocol fully documented in file header
- Firmware committed `a1fde994`, collector committed `970d98f`
- **Next:** rebuild firmware (`pio run ... --target upload`) → reflash T114 → wire T114 hardware UART to RP2040-PiZero GP0/GP1

### 2026-05-14 — Collector script written (Session 296)
- `collector/main.py` written for RP2040-PiZero (MicroPython)
- UART0 on GP0/GP1 @ 115200 baud connected to T114 hardware UART
- Parses OBS|ADV (full pubkey) and OBS|RX (4-byte hash) lines
- Ring buffer: 200 entries, drops oldest when full, tracks stats (adv/rx/dropped/parse_err)
- 60s periodic stats print for diagnostics

### 2026-05-14 — Firmware patch complete, serial output confirmed (Session 296)
- PlatformIO + VS Code installed on TestBox
- MeshCore cloned to `firmware/`, built clean for `Heltec_t114_without_display_repeater`
- RC patch written and tested: OBS|ADV fires on advert reception (full pubkey + RSSI/SNR), OBS|RX fires on all non-advert packets (4-byte packet hash + RSSI/SNR)
- Startup message + 5s heartbeat added for serial diagnostics
- T114 v1 flashed, serial confirmed working, OBS|ADV output verified with live MC node
- Committed as `fd58e5f2` in local firmware repo
- **Next:** rebuild firmware and reflash T114 with full OMCOLLECT delivery patch

### 2026-05-14 — Scope expanded + hardware confirmed (Session 296)
- T114 v1 confirmed as primary hardware target (spare, MC-compatible, nRF52840 + HT-RA62)
- RP2040-PiZero confirmed as off-grid collector; Pi Pico 2W as urban WiFi variant
- Coverage mapping added as parallel data stream alongside RC intel — same hardware, same firmware, same serial protocol, additional OBS|RX entry type
- Serial protocol updated: ADV/ANON/PEER (identity-bearing) + RX (coverage, short hash only)
- OM to import into two tables: `passive_obs` (intel) + `coverage_obs` (coverage)
- Status changed to Active — SW development starting

### 2026-05-07 — Project created (Session 289)
- Spawned from OverMesh passive collection investigation
- Firmware limitation confirmed: USB companion firmware does not push 0x88 LOG_DATA events; RPTR firmware is the right target
- Patch scope defined: adverts + anon requests + known peers patchable; relayed encrypted traffic not generically possible (no pubkey at `logRx()`)
- Codex researched RPTR source, confirmed `onAdvertRecv()` as primary patch point
- Near-term path: implement `Remote Neighbors Pull` in OM first (no firmware needed), then build firmware patch, then RP2040 collector
