#!/usr/bin/env python3
import asyncio
import argparse
import os
import json
from bleak import BleakScanner, BleakClient
from bleak.exc import BleakError

# --- Settings ---
STATE_FILE = os.path.expanduser("~/.nubert_state")
DEFAULT_VOL = 50  # Starting volume if no state is found

# --- Protocol Definitions from Decompiled Code ---
PROTOCOLS = {
    "A600": { # X-2 / A-Series
        "service": "8e2ceaaa-0e27-11e7-93ae-92361f002671",
        "write":   "8e2cece4-0e27-11e7-93ae-92361f002671",
        "use_response": True
    },
    "X1": { # X-Series (Standard)
        "service": "3c92551f-8448-4636-93e1-12da5274a9a2",
        "write":   "dc968ed5-ed46-43d9-8562-ae5984e55e40",
        "use_response": False
    },
    "XS": { # XS-Series / NuConnect
        "service": "0000fff0-0000-1000-8000-00805f9b34fb",
        "write":   "0000fff1-0000-1000-8000-00805f9b34fb",
        "use_response": False
    }
}

CMD_VOLUME_SET = 0x0B
CMD_SOURCE_SET = 0x0F
CMD_POWER_SET  = 0x1F

SOURCE_MAP = {
    "aux": 0x00, "bluetooth": 0x01, "xlr": 0x03, "coax1": 0x04,
    "coax2": 0x05, "optical1": 0x06, "optical2": 0x07, "usb": 0x08, "port": 0x09
}

def load_state(address):
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                return data.get(address, {})
        except: pass
    return {}

def save_state(address, key, value):
    data = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
        except: pass
    
    if address not in data: data[address] = {}
    data[address][key] = value
    
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(data, f)
    except: pass

async def main():
    parser = argparse.ArgumentParser(description="Nubert Speaker Control")
    parser.add_argument("--scan", action="store_true", help="Scan for devices")
    parser.add_argument("--address", help="Speaker MAC address")
    parser.add_argument("--volume", type=int, help="Set volume (0-100)")
    parser.add_argument("--volume-up", type=int, nargs='?', const=5, help="Increase volume")
    parser.add_argument("--volume-down", type=int, nargs='?', const=5, help="Decrease volume")
    parser.add_argument("--source", choices=SOURCE_MAP.keys(), help="Switch input")
    parser.add_argument("--power", choices=["on", "off"], help="Power on/off")
    args = parser.parse_args()

    if args.scan:
        print("Scanning for Nubert devices...")
        for d in await BleakScanner.discover(timeout=4.0):
            if d.name and any(x in d.name.lower() for x in ["nubert", "x-", "xs-"]):
                print(f"FOUND: {d.name} [{d.address}]")
        return

    if not args.address:
        print("Error: --address required.")
        return

    # Logical handling of volume increment before connecting
    target_vol = args.volume
    if args.volume_up or args.volume_down:
        state = load_state(args.address)
        current = state.get("volume", DEFAULT_VOL)
        step = args.volume_up if args.volume_up else -args.volume_down
        target_vol = max(0, min(100, current + step))
        print(f"Calculated relative volume: {current} -> {target_vol}")

    print(f"Connecting to {args.address}...")
    try:
        async with BleakClient(args.address) as client:
            cfg = None
            for name, p_cfg in PROTOCOLS.items():
                if client.services.get_service(p_cfg["service"]):
                    print(f"Detected Protocol: {name}")
                    cfg = p_cfg
                    break
            
            if not cfg:
                print("Error: Unsupported device.")
                return

            if args.power:
                val = 0x01 if args.power == "on" else 0x00
                await client.write_gatt_char(cfg["write"], bytearray([CMD_POWER_SET, val]), response=cfg["use_response"])
                print(f"Power set to {args.power}")

            if args.source:
                await client.write_gatt_char(cfg["write"], bytearray([CMD_SOURCE_SET, SOURCE_MAP[args.source]]), response=cfg["use_response"])
                print(f"Source set to {args.source}")

            if target_vol is not None:
                await client.write_gatt_char(cfg["write"], bytearray([CMD_VOLUME_SET, 0x01, target_vol]), response=cfg["use_response"])
                save_state(args.address, "volume", target_vol)
                print(f"Volume set to {target_vol}")

    except BleakError as e:
        print(f"Bluetooth Error: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt: pass
