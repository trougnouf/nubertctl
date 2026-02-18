# nubertctl - Nubert Speaker Control (CLI)

An unofficial cross-platform Python command-line utility to control Nubert speakers (including X, XS, and A-Series) via Bluetooth Low Energy (BLE). This tool enables integration of Nubert hardware with desktop environments where no official client is provided.

## Features
- **Power Control:** Toggle speakers between On and Standby.
- **Source Selection:** Switch between Bluetooth, Optical, XLR, AUX, USB, etc.
- **Volume Control:** Set absolute volume levels (0–100).
- **Relative Volume:** Increase/decrease volume using a local state cache (bypassing unreliable BLE read requests on some OSs).
- **Auto-Protocol Detection:** Automatically handles multiple hardware generations (A600, X-Series, XS-Series).

## Installation

### Arch Linux
```bash
sudo pacman -S python-bleak
```

### Windows / macOS / Other Linux
```bash
pip install bleak
```

## Usage

### 1. Scan for your Master speaker
Use this to find your speaker's address:
```bash
python nubert_control.py --scan
```
*Note: On macOS, this will return a UUID instead of a MAC address. Use that UUID in the next steps.*

### 2. Basic Commands
Replace `ADDRESS` with your speaker's MAC address or UUID.

**Set Volume (0-100):**
```bash
python nubert_control.py --address ADDRESS --volume 45
```

**Relative Volume:**
The script tracks volume in `~/.nubert_state` to allow instant increments.
```bash
python nubert_control.py --address ADDRESS --volume-up
python nubert_control.py --address ADDRESS --volume-down 10
```

**Switch Source:**
Supported: `aux`, `bluetooth`, `xlr`, `coax1`, `coax2`, `optical1`, `optical2`, `usb`, `port`.
```bash
python nubert_control.py --address ADDRESS --source optical1
```

**Power Control:**
```bash
python nubert_control.py --address ADDRESS --power off
```

## Desktop Integration
To automatically sync your Linux system volume with your Nubert speakers, run the provided sync script in the background:
```bash
./nubert_pulseaudio_sync.sh XX:XX:XX:XX:XX:XX &

## Platform Notes
- **Linux:** If the script hangs or returns a "Not Permitted" error, restart your Bluetooth service: `sudo systemctl restart bluetooth`.
- **macOS:** You must use the UUID provided by the `--scan` command. Hardware MAC addresses are hidden by the OS.
- **Windows:** You may need to pair the speaker in Windows Bluetooth Settings before the script can communicate with it.

## Disclaimer
This project is an independent, unofficial community development. It is not affiliated with, authorized, or endorsed by Nubert electronic GmbH. "Nubert" is a registered trademark of Nubert electronic GmbH. 

This tool is provided for **interoperability purposes** under the exceptions provided by **EU Directive 2009/24/EC**. It was developed by analyzing publicly available communication protocols to allow the hardware to function with unsupported operating systems.

## License
This project is released under the **GNU General Public License v3.0 (GPLv3)**. See the LICENSE file for details.
