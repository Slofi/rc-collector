# RC — Remote Collector

## Overview

Fork of MeshCore RPTR firmware to add identity-bearing passive observations over serial, enabling an attached RP2040/PiZero collector board to build per-node RF intel from a remote vantage point and deliver it to OverMesh over the mesh.

**Linked project:** [OverMesh](/home/slofi/Projects/overmesh/notes.md) — RC observations feed into OM's `passive_obs` system. See "Passive Mesh Intelligence" and "Remote Collector" sections.

- **Status:** Active, flashed, and live-tested end to end on TestBox; ready for balcony test deployment.
- **Firmware repo:** https://github.com/Slofi/overmesh-RC (public, forked from meshcore-dev/MeshCore)
- **Hardware target:** nRF52840 + HT-RA62, primary: T114 v1 (spare, MC-compatible); fallback: Faketec board
- **Collector:** RP2040-PiZero (off-grid) / Pi Pico 2W (urban, WiFi POST to OM API)
- **Build system:** PlatformIO

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

The attached RP2040/PiZero reads both streams from serial, buffers them, and delivers via `OMCOLLECT` DMs. OM imports identity-bearing rows into `passive_obs` tagged with `collector_id` and collector position. Anonymous `OBS|RX` short-hash rows are currently ignored by OM passive intel; they belong in a future separate coverage table if we decide to visualize coverage-only activity.

**Deployment variants:**
- **Off-grid** (hilltop solar): T114 v1 RPTR + RP2040-PiZero, mesh DM delivery
- **Urban**: T114 v1 RPTR + Pi Pico 2W, direct WiFi POST to OM API

---

## Technical Reference

### Firmware patch points

**Primary patch point:** `onAdvertRecv(packet, id, ...)` in `examples/simple_repeater/MyMesh.cpp`
- `id.pub_key` — full sender pubkey (after signature validation)
- `packet->getSNR()` — signal quality
- Emits `OBS|ADV|<pubkey>|<rssi>|<snr>|<ts>` to USB Serial and the collector UART.

**Secondary patch points:**
- `onAnonDataRecv()` — anon request sender pubkey available post-decrypt
- `onPeerDataRecv()` / `onPeerPathRecv()` — known peer packets via ACL client mapping

**Coverage-only patch point:** `logRx()` — called too early for generic identity, but useful for coverage. Emits `OBS|RX|<hash4>|<rssi>|<snr>|<ts>`, which OM currently ignores for passive intel.

### Serial protocol

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

RP2040 to T114 relay protocol:

```
RELAY|OMCOLLECT_START|RC1|<count>\r
RELAY|OBS|ADV|<pubkey>|<rssi>|<snr>|<ts>\r
RELAY|OMCOLLECT_END\r
```

The T114 strips `RELAY|`, encrypts the remaining line as a DM to the OM requester, and clears the collection context on `OMCOLLECT_END`.

### RP2040 collector

- MicroPython script on RP2040-PiZero
- Reads serial lines, parses `OBS|...` entries
- Ring buffer in RAM (or flash if persistent storage needed)
- Responds to `OMCOLLECT` DM from OM: sends buffered observations as `RELAY|...` lines to the T114
- Uses 3-second pacing between relay lines so the T114 forwards one mesh DM at a time
- OM imports identity-bearing rows into `passive_obs` with `collector_id` and collector lat/lon

### Stock RPTR `neighbors` (no firmware patch needed)

`neighbors` command returns up to 8 recent advert neighbors as `pubkey-prefix:secs_ago:snr`. OM can query this remotely over mesh — useful as a lightweight first step before full collector is built. Implement as "Remote Neighbors Pull" in OM.

### Build environment

- PlatformIO (VS Code extension)
- Firmware: cloned to `rc-collector/firmware/` — fork of `meshcore-dev/MeshCore`
- **GitHub:** https://github.com/Slofi/overmesh-RC (public) — pushed 2026-05-15
- Earlier RC patch commits:
  - `fd58e5f2` — OBS|ADV + OBS|RX serial output
  - `a1fde994` — OMCOLLECT DM delivery (OmcollectCtx + RELAY handler)
  - `8ed43a65` — Serial1 hardware UART output (GPIO 9/10), superseded locally on 2026-05-15 by explicit `RC_SERIAL`/`Serial2` handling for Heltec T114
- Radio config: 869.618 MHz, BW 62.5 kHz, SF8, **CR8** (matches rest of SLO MC mesh — changed from default CR5 via RPTR Manage)
- Node name, live position, advert intervals, and admin password are configured via OM RPTR Manage / Remote Collectors UI.
- Build target: `Heltec_t114_without_display_repeater`
- Flash: `~/.platformio/penv/bin/pio run -e Heltec_t114_without_display_repeater --target upload --upload-port /dev/ttyACM2`
- T114 v1 confirmed working — OBS|ADV tested with real MC node advert (RSSI -58, SNR 11.0)
- T114 currently flashed locally from `/home/slofi/Projects/rc-collector/firmware` after the 2026-05-15 RC UART bridge fix.
- Live test on TestBox: OM login succeeded with admin password, `OMCOLLECT` returned `OMCOLLECT_START|RC1|118`, paced `OBS|ADV|...` lines arrived, and OM imported `rc_adv` rows into `passive_obs`.
- Latest pushed firmware fix: `c6561981 Fix T114 remote collector UART bridge` on `git@github.com:Slofi/overmesh-RC.git` `main`.

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

### 2026-05-15 — RC end-to-end live test passed; firmware bridge bug fixed (Session 297 follow-up)

**Live result:**
- T114 connected as `/dev/ttyACM2` (`Heltec_HT-n5262_697705043C5A613A`) and flashed successfully with `Heltec_t114_without_display_repeater`.
- USB serial after flash showed `RC alive`, confirming the patched firmware was running.
- OM login to `Heltec_T114 Repeater` (`ce2192c987bc...`) with test password succeeded as admin.
- `OMCOLLECT` returned `OMCOLLECT_START|RC1|118`; this was the first confirmed proof that the T114 received the RP2040 relay response and forwarded it back to OM.
- OM imported real collector observations as `rc_adv` rows with `collector_id='RC1'`, RSSI/SNR, and full pubkeys.
- User then sent position commands from OM and received `OK`, confirming remote admin replies remained functional after the RC fix.

**Firmware bug found:**
- The original RC firmware wrote `OMCOLLECT` to the RP2040 over hardware UART, and it already had a `RELAY|...` handler in `MyMesh::handleCommand()`.
- However, `examples/simple_repeater/main.cpp` only read command lines from USB `Serial`.
- The RP2040 replied on the T114 hardware UART, but the T114 never read those bytes, so the existing `RELAY|...` handler was unreachable during real operation.
- On Heltec T114 specifically, pins 9/10 are defined as `Serial2` in the variant, while the old RC patch used `Serial1.setPins(9, 10)`. This was fragile and could also conflict with GPS/Serial1 handling.
- Symptom before fix: OM could login and send `OMCOLLECT` (`MSG_SENT`) but saw no `OMCOLLECT_START`, no `OBS`, and no `rc_adv` imports.

**Firmware fix:**
- Added explicit RC UART selection:
  - Heltec T114: `RC_SERIAL = Serial2`, `RX=9`, `TX=10`
  - Other targets: fallback `RC_SERIAL = Serial1`, `RX=9`, `TX=10`
- Replaced collector protocol writes (`OBS|ADV`, `OBS|RX`, `OMCOLLECT`) to use `RC_SERIAL` consistently.
- Added a second line buffer in `main.cpp` that reads from `RC_SERIAL` and passes completed `RELAY|...` lines to `the_mesh.handleCommand(0, ...)`.
- Kept USB `Serial` CLI behavior unchanged for debugging.
- Left the existing `RELAY|...` forwarding logic in `MyMesh.cpp` as the relay-to-DM path.

**RP2040 pacing fix:**
- `collector/main.py` now uses `RELAY_INTERVAL_MS = 3000`.
- `deliver_relay()` waits 3 seconds between each `RELAY|...` line, so the T114 receives and forwards one mesh DM at a time instead of being fed the whole buffer burst immediately.
- This protects the T114 packet queue and keeps RC collection from flooding the mesh.

**OM-side fixes made during the sweep:**
- Collector button sends uppercase `OMCOLLECT` to match firmware's case-sensitive command check.
- `_collectorLogin()` now uses a lightweight `login_only` read path, so Collect no longer waits for a full remote repeater read before sending the command.
- Remote admin allowlist includes `OMCOLLECT` and `password `.
- RC import now stores only identity-bearing `ADV`/`ANON`/`PEER` observations into `passive_obs`; anonymous `RX` short-hash coverage rows are ignored by passive intel.
- Collector timestamps are preserved when plausible Unix timestamps are provided.
- Valid `0.0` coordinates are no longer converted to `None` accidentally.

**Git/GitHub state after closeout:**
- Firmware fix pushed to `Slofi/overmesh-RC` as `c6561981 Fix T114 remote collector UART bridge`.
- OM-side Remote Collector fix pushed to `Slofi/overmesh` as `cf7f141 Fix remote collector import and command flow`.
- Parent RC notes/script repo is separate from the nested firmware fork:
  - Local repo: `/home/slofi/Projects/rc-collector`
  - Branch: `main`
  - Remote: `git@github.com:Slofi/rc-collector.git`
  - Pushed to GitHub on 2026-05-15; branch tracks `origin/main`.
  - Local safety bundle: `/home/slofi/Projects/rc-collector-parent-2026-05-15.bundle`
- OM `secret.key` remains local/untracked and must never be pushed.

### 2026-05-15 — Hardware assembled, OM UI complete, firmware pushed to GitHub (Session 297)

**Hardware unit assembled:**
- T114 v1 + RP2040-PiZero in 100×68×50mm plastic enclosure
- SMA bulkhead through enclosure bottom — antenna points up, box lies flat on lid
- Magnetic solar connector on long side of enclosure
- T114 powered by LiPo via VBAT + solar panel via Solar connector
- RP2040-PiZero powered from T114 3.3V rail (pin 1 on 40-pin header)
- UART wired: T114 GPIO 10 (TX) → RP2040 GP1 (RX); GPIO 9 (RX) → RP2040 GP0 (TX); GND shared
- `main.py` copied to RP2040 flash — runs autonomously on power-up, no USB needed
- T114 display physically removable (unused by `without_display` firmware target)

**OM Remote Collector UI (Session 297):**
- `omcollect` and `password ` added to `_validate_remote_admin_command` allowlist/prefixes in `mesh_mc.py`
- `collectFromNode` replaced with `sendCollectorCommand(pubkeyPre, command, btn)` — uses correct `/api/mc/<rid>/remote/<node>/command` endpoint (RPTR nodes can't be DM'd directly); logs in with stored password before every command if one is saved
- Each collector row now has: Collect + Neighbors buttons, custom command input + Send button
- Collector position row: lat/lon inputs + **Pick on map** (map picker, `'rc-collector'` pick mode) + **Set pos** (sends `set lat`/`set lon` to T114 and saves locally)
- Password row: password input + **Save password** (stores to localStorage per node, used for auto-login before commands) + **Change password** (logs in with old password, sends `password <new>` to T114, updates stored password)
- Node search in Add Collector: type name or pubkey prefix, live dropdown from known MC contacts, click to auto-fill fields
- Signal heatmap: Leaflet.heat layer in Map → Overlays → Data layers; weather-radar style RSSI coverage overlay; toggle persists across refreshes; ↻ refresh button

**Firmware pushed to GitHub:**
- https://github.com/Slofi/overmesh-RC — public repo, 3 RC commits on top of MeshCore main
- Referenced in OM in-app manual under "Remote Collector (RC)" section

### 2026-05-14 — OM collector DM parser implemented (Session 296)
- `db.py`: added `collector_id TEXT`, `collector_lat REAL`, `collector_lon REAL` to `passive_obs` table
- Migration via try/except ALTER TABLE — works on existing DBs without data loss
- `save_passive_obs` updated to accept and store the three new collector params
- `mesh_mc.py`: `_rc_collector_state` dict tracks in-flight sessions per (config_id, sender_prefix)
- `_get_collector_latlon()` resolves collector position from live contacts (adv_lat/adv_lon)
- `_handle_rc_collector_line()` parses incoming relay lines:
  - `OMCOLLECT_START|RC1|N` → log session start, store collector_id
  - `OBS|ADV|<pubkey>|<rssi>|<snr>|<ts>` → save to `passive_obs` with `obs_type='rc_adv'`
  - `OBS|RX|<hash4>|<rssi>|<snr>|<ts>` → save with `obs_type='rc_rx'`
  - `OMCOLLECT_END` → clear session state, log completion
- `on_dm` hook: fires handler in background thread when DM text starts with `OMCOLLECT_START|` or `OBS|` or equals `OMCOLLECT_END`
- All passive_obs tests pass (5/5); 2 pre-existing unrelated MT failures unchanged
- OM committed `8ff4913`
- **Next:** wire T114 GPIO 10/9 → RP2040 GP1/GP0 + GND, then end-to-end test

### 2026-05-14 — Serial1 hardware UART output added (Session 296)
- `main.cpp` setup: `Serial1.setPins(9, 10); Serial1.begin(115200);` — GPIO 9 (RX), GPIO 10 (TX)
- All RC-specific output (OBS|ADV, OBS|RX, OMCOLLECT trigger) now mirrored to Serial1
- USB Serial preserved for debugging; RP2040 reads from Serial1 hardware UART
- GPIO 9/10 confirmed from RS232 bridge variant in firmware repo; T114 v1 = v2 physically
- Firmware committed `8ed43a65`, built clean, flashed to T114 — confirmed heartbeat on USB serial
- Superseded on 2026-05-15: Heltec T114 now uses explicit `RC_SERIAL = Serial2` on GPIO 9/10 and reads RP2040 `RELAY|...` replies from that UART.
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
