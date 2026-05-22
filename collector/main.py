# RC Collector — MicroPython script for RP2040-PiZero
# Reads OBS lines from T114 RPTR via UART, buffers observations.
#
# Hardware: RP2040-PiZero
#   UART0 TX -> GP0  -> T114 RX (hardware UART pin)
#   UART0 RX <- GP1  <- T114 TX (hardware UART pin)
#
# Serial protocol (T114 → RP2040):
#   OBS|ADV|<pubkey_hex32>|<rssi>|<snr>|<uptime_s>|<name>|<lat>|<lon>  — advert
#   OBS|RX|<pkt_hash_hex4>|<rssi>|<snr>|<uptime_s>                      — coverage
#   OMCOLLECT                                                             — trigger relay
#   OMCOUNT                                                               — report buffer count
#   RC alive | uptime=<s>s                                               — heartbeat (ignored)
#
# Serial protocol (RP2040 → T114):
#   RELAY|OMCOLLECT_START|<id>|<count>\r              — start of relay burst
#   RELAY|OBS|<type>|<id>|<rssi>|<snr>|<ts>\r        — one buffered observation
#   RELAY|OMCOLLECT_END\r                             — end of relay burst (T114 clears ctx)

import time
from machine import UART, Pin

# ── Config ─────────────────────────────────────────────────────────────────────
UART_ID       = 0
UART_TX_PIN   = 0       # GP0
UART_RX_PIN   = 1       # GP1
UART_BAUD     = 115200
BUFFER_SIZE   = 200     # max observations in ring buffer
COLLECTOR_ID  = "RC1"   # identifies this unit in OM
RELAY_INTERVAL_MS = 3000 # pace mesh DMs from T114 back to OM

# ── Ring buffer ────────────────────────────────────────────────────────────────
# Each entry: raw OBS line as received from T114
_buf   = []
_stats = {'adv': 0, 'rx': 0, 'dropped': 0, 'parse_err': 0}

def _buf_add(line):
    if len(_buf) >= BUFFER_SIZE:
        _buf.pop(0)
        _stats['dropped'] += 1
    _buf.append(line)

# ── Parser ─────────────────────────────────────────────────────────────────────
def parse_obs(line):
    """Return True if line is a valid OBS entry worth buffering."""
    try:
        parts = line.split('|')
        if len(parts) < 6 or parts[0] != 'OBS':
            return False
        if parts[1] not in ('ADV', 'RX', 'ANON', 'PEER'):
            return False
        float(parts[3]); float(parts[4])  # rssi, snr must be numeric
        return True
    except Exception:
        return False

# ── Stats / dump ───────────────────────────────────────────────────────────────
def dump_stats():
    print("RC stats: buf={} adv={} rx={} dropped={} err={}".format(
        len(_buf), _stats['adv'], _stats['rx'], _stats['dropped'], _stats['parse_err']))

# ── DM delivery via RELAY| protocol ───────────────────────────────────────────
def deliver_relay(uart):
    entries = list(_buf)  # snapshot
    print("RELAY: {} entries".format(len(entries)))
    uart.write("RELAY|OMCOLLECT_START|{}|{}\r".format(COLLECTOR_ID, len(entries)).encode())
    time.sleep_ms(RELAY_INTERVAL_MS)
    for line in entries:
        uart.write(("RELAY|" + line + "\r").encode())
        time.sleep_ms(RELAY_INTERVAL_MS)
    uart.write("RELAY|OMCOLLECT_END\r".encode())

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
                        if parse_obs(line):
                            _buf_add(line)
                            obs_type = line.split('|')[1] if '|' in line else ''
                            if obs_type == 'ADV':
                                _stats['adv'] += 1
                            else:
                                _stats['rx'] += 1
                        else:
                            _stats['parse_err'] += 1

                    elif line == 'OMCOLLECT':
                        deliver_relay(uart)

                    elif line == 'OMCOUNT':
                        uart.write("RELAY|OMCOUNT_RESULT|{}|{}\r".format(COLLECTOR_ID, len(_buf)).encode())
                        time.sleep_ms(500)
                        uart.write("RELAY|OMCOLLECT_END\r".encode())

        # Print stats every 60s
        if time.ticks_diff(time.ticks_ms(), last_stats) > 60_000:
            dump_stats()
            last_stats = time.ticks_ms()

        time.sleep_ms(10)

main()
