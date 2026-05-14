# RC Collector — MicroPython script for RP2040-PiZero
# Reads OBS lines from T114 RPTR via UART, buffers observations.
#
# Hardware: RP2040-PiZero
#   UART0 TX -> GP0  -> T114 RX (hardware UART pin)
#   UART0 RX <- GP1  <- T114 TX (hardware UART pin)
#
# Serial protocol from T114:
#   OBS|ADV|<pubkey_hex32>|<rssi>|<snr>|<uptime_s>   — advert (full identity)
#   OBS|RX|<pkt_hash_hex4>|<rssi>|<snr>|<uptime_s>   — any other packet (coverage)
#   RC alive | uptime=<s>s                             — heartbeat (ignored)

import time
from machine import UART, Pin

# ── Config ─────────────────────────────────────────────────────────────────────
UART_ID       = 0
UART_TX_PIN   = 0       # GP0
UART_RX_PIN   = 1       # GP1
UART_BAUD     = 115200
BUFFER_SIZE   = 200     # max observations in ring buffer
COLLECTOR_ID  = "RC1"   # identifies this unit in OM

# ── Ring buffer ────────────────────────────────────────────────────────────────
# Each entry: [type, id, rssi, snr, ts]
# type: 'ADV' or 'RX'
# id:   full pubkey hex (ADV) or 4-byte packet hash hex (RX)
_buf   = []
_stats = {'adv': 0, 'rx': 0, 'dropped': 0, 'parse_err': 0}

def _buf_add(entry):
    if len(_buf) >= BUFFER_SIZE:
        _buf.pop(0)
        _stats['dropped'] += 1
    _buf.append(entry)

# ── Parser ─────────────────────────────────────────────────────────────────────
def parse_obs(line):
    """Return [type, id, rssi, snr, ts] or None."""
    try:
        parts = line.split('|')
        if len(parts) != 6 or parts[0] != 'OBS':
            return None
        obs_type = parts[1]
        if obs_type not in ('ADV', 'RX'):
            return None
        return [obs_type, parts[2], float(parts[3]), float(parts[4]), int(parts[5])]
    except Exception:
        return None

# ── Stats / dump ───────────────────────────────────────────────────────────────
def dump_stats():
    print("RC stats: buf={} adv={} rx={} dropped={} err={}".format(
        len(_buf), _stats['adv'], _stats['rx'], _stats['dropped'], _stats['parse_err']))

def dump_buffer(max_entries=None):
    entries = _buf if max_entries is None else _buf[-max_entries:]
    print("OMCOLLECT_START|{}|{}".format(COLLECTOR_ID, len(entries)))
    for e in entries:
        print("OBS|{}|{}|{:.1f}|{:.1f}|{}".format(*e))
    print("OMCOLLECT_END")

# ── TODO: DM delivery ──────────────────────────────────────────────────────────
# When T114 firmware gains a serial 'msg' command:
#   send "msg <om_pubkey_prefix> OMCOLLECT_START|...\n" lines via uart
#   triggered by incoming "OMCOLLECT" line forwarded from T114 DM handler
#
# def deliver_via_dm(uart, om_pubkey_prefix):
#     for e in _buf:
#         obs_str = "OBS|{}|{}|{:.1f}|{:.1f}|{}".format(*e)
#         uart.write("msg {} {}\n".format(om_pubkey_prefix, obs_str).encode())
#         time.sleep_ms(200)   # rate limit

# ── Main loop ──────────────────────────────────────────────────────────────────
def main():
    uart = UART(UART_ID, baudrate=UART_BAUD,
                tx=Pin(UART_TX_PIN), rx=Pin(UART_RX_PIN))

    print("RC collector ready | buf_size={} id={}".format(BUFFER_SIZE, COLLECTOR_ID))

    line_buf = b''
    last_stats = time.ticks_ms()

    while True:
        # Read available bytes
        if uart.any():
            chunk = uart.read(256)
            if chunk:
                line_buf += chunk
                while b'\n' in line_buf:
                    raw, line_buf = line_buf.split(b'\n', 1)
                    line = raw.decode('utf-8', 'ignore').strip()

                    if line.startswith('OBS|'):
                        obs = parse_obs(line)
                        if obs:
                            _buf_add(obs)
                            if obs[0] == 'ADV':
                                _stats['adv'] += 1
                            else:
                                _stats['rx'] += 1
                        else:
                            _stats['parse_err'] += 1

                    elif line == 'OMCOLLECT':
                        # TODO: replace with DM delivery once firmware supports 'msg' command
                        dump_buffer()

        # Print stats every 60s
        if time.ticks_diff(time.ticks_ms(), last_stats) > 60_000:
            dump_stats()
            last_stats = time.ticks_ms()

        time.sleep_ms(10)

main()
