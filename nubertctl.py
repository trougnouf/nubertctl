#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import re
import socket
import sys

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

# --- Settings ---
STATE_FILE = os.path.expanduser("~/.nubert_state")
SOCKET_PATH = "/tmp/nubert.sock"
DEFAULT_VOL = 50  # Starting volume if no state is found

# --- Protocol Definitions from Decompiled Code ---
PROTOCOLS = {
    "A600": {  # X-2 / A-Series
        "service": "8e2ceaaa-0e27-11e7-93ae-92361f002671",
        "write": "8e2cece4-0e27-11e7-93ae-92361f002671",
        "use_response": True,
    },
    "X1": {  # X-Series (Standard)
        "service": "3c92551f-8448-4636-93e1-12da5274a9a2",
        "write": "dc968ed5-ed46-43d9-8562-ae5984e55e40",
        "use_response": False,
    },
    "XS": {  # XS-Series / NuConnect
        "service": "0000fff0-0000-1000-8000-00805f9b34fb",
        "write": "0000fff1-0000-1000-8000-00805f9b34fb",
        "use_response": False,
    },
}

CMD_VOLUME_SET = 0x0B
CMD_SOURCE_SET = 0x0F
CMD_POWER_SET = 0x1F

SOURCE_MAP = {
    "aux": 0x00,
    "bluetooth": 0x01,
    "xlr": 0x03,
    "coax1": 0x04,
    "coax2": 0x05,
    "optical1": 0x06,
    "optical2": 0x07,
    "usb": 0x08,
    "port": 0x09,
}


def is_mac_or_uuid(s):
    if not s:
        return False
    mac_regex = r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$"
    uuid_regex = (
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )
    return re.match(mac_regex, s) or re.match(uuid_regex, s)


async def resolve_target(target):
    if is_mac_or_uuid(target):
        return target

    print(f"Scanning to resolve name '{target}'...")
    devices = await BleakScanner.discover(timeout=30.0)
    for d in devices:
        if d.name and d.name == target:
            print(f"Found '{target}' at {d.address}")
            return d.address

    print(f"Error: Could not find a device named '{target}'.")
    return None


def load_state(address):
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                return data.get(address, {})
        except:
            pass
    return {}


def save_state(address, key, value):
    data = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
        except:
            pass

    if address not in data:
        data[address] = {}
    data[address][key] = value

    try:
        with open(STATE_FILE, "w") as f:
            json.dump(data, f)
    except:
        pass


# ---------- Daemon mode ----------
async def handle_client(reader, writer, client, write_char, use_response, target):
    data = await reader.read(100)
    if not data:
        try:
            writer.close()
            await writer.wait_closed()
        except:
            pass
        return
    try:
        vol = int(data.decode().strip())
        vol = max(0, min(100, vol))
        await client.write_gatt_char(
            write_char, bytearray([CMD_VOLUME_SET, 0x01, vol]), response=use_response
        )
        try:
            save_state(target, "volume", vol)
        except:
            pass

        print(f"Volume set to {vol}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except:
            pass


async def daemon_main(target):
    address = await resolve_target(target)
    if not address:
        sys.exit(1)  # Exit so systemd can trigger a restart and rescan later

    print(f"Connecting to {address}...")
    try:
        async with BleakClient(address, timeout=20.0) as client:
            cfg = None
            for name, p_cfg in PROTOCOLS.items():
                try:
                    if client.services is None:
                        await client.get_services()
                except:
                    pass

                if client.services.get_service(p_cfg["service"]):
                    print(f"Detected Protocol: {name}")
                    cfg = p_cfg
                    break

            if not cfg:
                print("Unsupported device")
                sys.exit(1)

            write_char = cfg["write"]
            use_response = cfg["use_response"]

            if os.path.exists(SOCKET_PATH):
                try:
                    os.unlink(SOCKET_PATH)
                except:
                    pass

            server = await asyncio.start_unix_server(
                lambda r, w: handle_client(
                    r, w, client, write_char, use_response, target
                ),
                path=SOCKET_PATH,
            )
            print(f"Daemon listening on {SOCKET_PATH}")
            async with server:
                await server.serve_forever()

    except BleakError as e:
        print(f"Bluetooth Error (daemon): {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Daemon error: {e}")
        sys.exit(1)


# ---------- One‑shot mode (original) ----------
async def oneshot(args):
    if args.scan:
        print("Scanning for Nubert devices...")
        for d in await BleakScanner.discover(timeout=10.0):
            if d.name and any(x in d.name.lower() for x in ["nubert", "x-", "xs-"]):
                print(f"FOUND: {d.name} [{d.address}]")
        return

    if not args.address:
        print("Error: --address required.")
        return

    address = await resolve_target(args.address)
    if not address:
        sys.exit(1)

    target_vol = args.volume
    if args.volume_up or args.volume_down:
        state = load_state(
            args.address
        )  # Load state keyed by name/mac (avoids state resets if MAC shifts)
        current = state.get("volume", DEFAULT_VOL)
        step = args.volume_up if args.volume_up else -args.volume_down
        target_vol = max(0, min(100, current + step))
        print(f"Calculated relative volume: {current} -> {target_vol}")

    print(f"Connecting to {address}...")
    try:
        async with BleakClient(address, timeout=20.0) as client:
            cfg = None
            try:
                if client.services is None:
                    await client.get_services()
            except:
                pass

            for name, p_cfg in PROTOCOLS.items():
                if client.services.get_service(p_cfg["service"]):
                    print(f"Detected Protocol: {name}")
                    cfg = p_cfg
                    break

            if not cfg:
                print("Error: Unsupported device.")
                sys.exit(1)

            if args.power:
                val = 0x01 if args.power == "on" else 0x00
                await client.write_gatt_char(
                    cfg["write"],
                    bytearray([CMD_POWER_SET, val]),
                    response=cfg["use_response"],
                )
                print(f"Power set to {args.power}")

            if args.source:
                await client.write_gatt_char(
                    cfg["write"],
                    bytearray([CMD_SOURCE_SET, SOURCE_MAP[args.source]]),
                    response=cfg["use_response"],
                )
                print(f"Source set to {args.source}")

            if target_vol is not None:
                await client.write_gatt_char(
                    cfg["write"],
                    bytearray([CMD_VOLUME_SET, 0x01, target_vol]),
                    response=cfg["use_response"],
                )
                save_state(args.address, "volume", target_vol)
                print(f"Volume set to {target_vol}")

    except BleakError as e:
        print(f"Bluetooth Error: {e}")
        sys.exit(1)


async def main():
    parser = argparse.ArgumentParser(description="Nubert Speaker Control")
    parser.add_argument(
        "--daemon", action="store_true", help="Run as persistent daemon"
    )
    parser.add_argument("--scan", action="store_true", help="Scan for devices")
    parser.add_argument("--address", help="Speaker MAC address OR Bluetooth Name")
    parser.add_argument("--volume", type=int, help="Set volume (0-100)")
    parser.add_argument(
        "--volume-up", type=int, nargs="?", const=5, help="Increase volume"
    )
    parser.add_argument(
        "--volume-down", type=int, nargs="?", const=5, help="Decrease volume"
    )
    parser.add_argument("--source", choices=SOURCE_MAP.keys(), help="Switch input")
    parser.add_argument("--power", choices=["on", "off"], help="Power on/off")
    args = parser.parse_args()

    if args.daemon:
        if not args.address:
            print("--address required for daemon mode")
            return
        await daemon_main(args.address)
    else:
        await oneshot(args)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
