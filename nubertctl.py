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
DEFAULT_VOL = 50

# --- Global state variables for Daemon ---
_bt_client = None
_bt_cfg = None

# --- Protocol Definitions ---
PROTOCOLS = {
    "A600": {
        "service": "8e2ceaaa-0e27-11e7-93ae-92361f002671",
        "write": "8e2cece4-0e27-11e7-93ae-92361f002671",
        "use_response": True,
    },
    "X1": {
        "service": "3c92551f-8448-4636-93e1-12da5274a9a2",
        "write": "dc968ed5-ed46-43d9-8562-ae5984e55e40",
        "use_response": False,
    },
    "XS": {
        "service": "0000fff0-0000-1000-8000-00805f9b34fb",
        "write": "0000fff1-0000-1000-8000-00805f9b34fb",
        "use_response": False,
    },
}

CMD_VOLUME_SET = 0x0B
CMD_SOURCE_SET = 0x0F
CMD_POWER_SET = 0x1F

SOURCE_MAP = {
    "aux": 0x00, "bluetooth": 0x01, "xlr": 0x03, "coax1": 0x04,
    "coax2": 0x05, "optical1": 0x06, "optical2": 0x07, "usb": 0x08, "port": 0x09,
}

def is_mac_or_uuid(s):
    if not s:
        return False
    mac_regex = r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$"
    uuid_regex = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
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

def get_default_address():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                if data:
                    return list(data.keys())[0]
        except:
            pass
    return None

# ---------- Daemon mode ----------
async def handle_client(reader, writer, target):
    global _bt_client, _bt_cfg
    data = await reader.read(1024)
    if not data:
        writer.close()
        return

    try:
        text = data.decode().strip()
        
        # 1. Parse JSON payload (or fallback to plain int for the bash script)
        try:
            payload = json.loads(text)
            # Prevent json.loads from parsing a raw string/int into a non-dict type
            if not isinstance(payload, dict):
                payload = {"volume": int(text)}
        except ValueError:
            payload = {"volume": int(text)}
            
        if _bt_client and _bt_client.is_connected and _bt_cfg:
            
            # Volume Relative Step
            if "volume_step" in payload:
                state = load_state(target)
                current = state.get("volume", DEFAULT_VOL)
                payload["volume"] = current + payload["volume_step"]
            
            # Volume Absolute
            if "volume" in payload:
                vol = max(0, min(100, int(payload["volume"])))
                await _bt_client.write_gatt_char(
                    _bt_cfg["write"], bytearray([CMD_VOLUME_SET, 0x01, vol]), response=_bt_cfg["use_response"]
                )
                save_state(target, "volume", vol)
                print(f"Daemon set volume to {vol}")
                
            # Power
            if "power" in payload:
                val = 0x01 if payload["power"] == "on" else 0x00
                await _bt_client.write_gatt_char(
                    _bt_cfg["write"], bytearray([CMD_POWER_SET, val]), response=_bt_cfg["use_response"]
                )
                print(f"Daemon set power to {payload['power']}")
                
            # Source
            if "source" in payload and payload["source"] in SOURCE_MAP:
                await _bt_client.write_gatt_char(
                    _bt_cfg["write"], bytearray([CMD_SOURCE_SET, SOURCE_MAP[payload["source"]]]), response=_bt_cfg["use_response"]
                )
                print(f"Daemon set source to {payload['source']}")

        else:
            print("Ignored command, speaker not connected. Waiting for reconnect...")

    except Exception as e:
        print(f"Error processing client command: {e}")
        # Force reconnect on error
        if _bt_client:
            try:
                await _bt_client.disconnect()
            except:
                pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except:
            pass

async def maintain_ble_connection(target):
    global _bt_client, _bt_cfg
    while True:
        try:
            address = await resolve_target(target)
            if not address:
                print("Speaker not found, retrying in 10s...")
                await asyncio.sleep(10)
                continue

            print(f"Connecting to {address}...")
            disconnect_event = asyncio.Event()

            def on_disconnect(client):
                print("Bluetooth disconnected callback triggered!")
                disconnect_event.set()

            async with BleakClient(address, timeout=20.0, disconnected_callback=on_disconnect) as client:
                cfg = None
                try:
                    if client.services is None:
                        await client.get_services()
                except:
                    pass

                for name, p_cfg in PROTOCOLS.items():
                    if client.services and client.services.get_service(p_cfg["service"]):
                        print(f"Detected Protocol: {name}")
                        cfg = p_cfg
                        break

                if not cfg:
                    print("Unsupported device, retrying...")
                    await asyncio.sleep(10)
                    continue

                _bt_client = client
                _bt_cfg = cfg
                print("Bluetooth connected and ready.")

                # Wait for disconnect
                await disconnect_event.wait()
                
        except Exception as e:
            pass
        finally:
            _bt_client = None
            _bt_cfg = None

        print("Waiting 5s before reconnecting...")
        await asyncio.sleep(5)

async def daemon_main(target):
    if os.path.exists(SOCKET_PATH):
        try:
            os.unlink(SOCKET_PATH)
        except:
            pass
    server = await asyncio.start_unix_server(
        lambda r, w: handle_client(r, w, target), path=SOCKET_PATH
    )
    print(f"Daemon listening on {SOCKET_PATH}")
    asyncio.create_task(maintain_ble_connection(target))
    async with server:
        await server.serve_forever()

# ---------- One shot / CLI mode ----------
async def oneshot(args):
    if args.scan:
        for d in await BleakScanner.discover(timeout=10.0):
            if d.name and any(x in d.name.lower() for x in ["nubert", "x-", "xs-"]):
                print(f"FOUND: {d.name} [{d.address}]")
        return

    address = args.address or get_default_address()

    # 1. Forward command to daemon if it's running
    if os.path.exists(SOCKET_PATH):
        payload = {}
        if args.power: payload["power"] = args.power
        if args.source: payload["source"] = args.source
        if args.volume is not None: payload["volume"] = args.volume
        if args.volume_up: payload["volume_step"] = args.volume_up
        if args.volume_down: payload["volume_step"] = -args.volume_down
        
        if not payload:
            print("No action specified.")
            return

        try:
            reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)
            writer.write(json.dumps(payload).encode() + b"\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return
        except Exception as e:
            print("Failed to contact daemon, falling back to direct connection...")

    # 2. Fallback: Connect directly if daemon is offline
    if not address:
        print("Error: --address required (or run daemon to cache the address).")
        sys.exit(1)

    address_resolved = await resolve_target(address)
    if not address_resolved:
        sys.exit(1)

    target_vol = args.volume
    if args.volume_up or args.volume_down:
        state = load_state(address)
        current = state.get("volume", DEFAULT_VOL)
        step = args.volume_up if args.volume_up else -args.volume_down
        target_vol = max(0, min(100, current + step))

    print(f"Connecting to {address_resolved}...")
    try:
        async with BleakClient(address_resolved, timeout=20.0) as client:
            cfg = None
            try:
                if client.services is None:
                    await client.get_services()
            except:
                pass
            for name, p_cfg in PROTOCOLS.items():
                if client.services and client.services.get_service(p_cfg["service"]):
                    cfg = p_cfg
                    break
            if not cfg:
                print("Error: Unsupported device.")
                sys.exit(1)

            if args.power:
                val = 0x01 if args.power == "on" else 0x00
                await client.write_gatt_char(cfg["write"], bytearray([CMD_POWER_SET, val]), response=cfg["use_response"])
            if args.source:
                await client.write_gatt_char(cfg["write"], bytearray([CMD_SOURCE_SET, SOURCE_MAP[args.source]]), response=cfg["use_response"])
            if target_vol is not None:
                await client.write_gatt_char(cfg["write"], bytearray([CMD_VOLUME_SET, 0x01, target_vol]), response=cfg["use_response"])
                save_state(address, "volume", target_vol)

    except BleakError as e:
        print(f"Bluetooth Error: {e}")
        sys.exit(1)

async def main():
    parser = argparse.ArgumentParser(description="Nubert Speaker Control")
    parser.add_argument("--daemon", action="store_true", help="Run as persistent daemon")
    parser.add_argument("--scan", action="store_true", help="Scan for devices")
    parser.add_argument("--address", help="Speaker MAC address OR Bluetooth Name")
    parser.add_argument("--volume", type=int, help="Set volume (0-100)")
    parser.add_argument("--volume-up", type=int, nargs="?", const=5, help="Increase volume")
    parser.add_argument("--volume-down", type=int, nargs="?", const=5, help="Decrease volume")
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
