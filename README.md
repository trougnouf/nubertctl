# nubertctl - Nubert Speaker Control (CLI)

An unofficial cross-platform Python utility to control Nubert speakers (X, XS, and A-Series) via Bluetooth Low Energy (BLE).

## Features
- **Daemon Mode:** Persistent BLE connection via Unix socket for instant response times.
- **PulseAudio/PipeWire Sync:** Maps a virtual system volume slider to physical speaker gain.
- **Auto-Protocol Detection:** Supports A600, X-Series, and XS-Series hardware.
- **Source & Power Control:** Full control over inputs and standby states.
- **Name Resolution:** Identifies your speaker dynamically by its Bluetooth name, circumventing rotating MAC address problems.

## Installation

### Arch Linux (AUR)
Install `nubertctl-git`. The package includes the CLI tool, the sync script, and systemd units.
```bash
# Example using yay
yay -S nubertctl-git
```

### Manual Installation
1. **Dependencies:**
   ```bash

   pip install bleak 
   # For PulseAudio/PipeWire sync:
   sudo pacman -S socat  # Or your distro equivalent (e.g., apt install socat)
   ```

## Usage

### 1. Find your Speaker
```bash
nubertctl --scan
```
Take note of the resulting Bluetooth name (e.g., `nubert X-2 2272`). While a MAC address is still perfectly acceptable, using the Bluetooth Name is highly recommended. 

### 2. Desktop Integration (Linux)
The most robust way to use this on Linux is via the provided systemd services. This creates a persistent background connection so volume changes are instant. 

*(If your speaker name has spaces, wrap it in a `systemd-escape` subshell as shown below to ensure systemctl mounts the instances perfectly!)*

1. **Enable the Daemon**:
   ```bash
   systemctl --user enable --now nubert-daemon@$(systemd-escape "nubert X-2 2272").service
   ```
2. **Enable the Volume Sync**:
   ```bash
   systemctl --user enable --now nubert-sync@$(systemd-escape "nubert X-2 2272").service
   ```

You will now see a **"Nubert_Speaker_Remote"** output in your system sound settings. Setting this as default allows your media keys to control the hardware speakers directly.

### 3. Manual CLI Commands
**Set Volume (0-100):**
```bash
nubertctl --address "nubert X-2 2272" --volume 45
```

**Switch Source:**
`aux`, `bluetooth`, `xlr`, `coax1`, `coax2`, `optical1`, `optical2`, `usb`, `port`.
```bash
nubertctl --address "nubert X-2 2272" --source usb
```

## Platform Notes
- **Linux:** Uses `socat` and `pactl` for volume synchronization.
- **macOS:** Use the UUID from `--scan` instead of a MAC address.
- **Windows:** Pair the device in System Settings first.

## Disclaimer
This is an unofficial community project. "Nubert" is a trademark of Nubert electronic GmbH. This tool is provided for interoperability purposes under EU Directive 2009/24/EC.
