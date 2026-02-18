#!/bin/bash

# Nubert Volume Sync - Ghost Worker Mode (Bit-Perfect)
# Usage: nubert-sync <MAC_ADDRESS>

ADDR="$1"
VIRTUAL_NAME="Nubert_Virtual_Control"
SAFE_START_VOL="20"
LOCK_FILE="/tmp/nubert_sync.lock"

if [[ -z "$ADDR" ]]; then
    echo "Usage: nubert-sync 51:FA:D1:39:F8:AB"
    exit 1
fi

cleanup() {
    echo -e "\nCleaning up..."
    rm -f "$LOCK_FILE"
    pactl unload-module module-null-sink 2>/dev/null
    exit
}
trap cleanup SIGINT SIGTERM
rm -f "$LOCK_FILE"

# --- 1. Identify Hardware and Set as Default (Temporarily) ---
BASE_SINK=$(pactl get-default-sink)
if [[ "$BASE_SINK" == "$VIRTUAL_NAME" ]]; then
    # If the script was killed uncleanly, find the real sink
    BASE_SINK=$(pactl list short sinks | grep -v "$VIRTUAL_NAME" | awk '{print $2}' | head -n 1)
fi
pactl set-default-sink "$BASE_SINK" # Ensure a real device is default before we start
echo "Hardware Output: $BASE_SINK (Will be locked at 100%)"

# --- 2. Create Ghost Device & Set as New Default ---
# This ensures keyboard shortcuts target our virtual slider
if ! pactl list short sinks | grep -q "$VIRTUAL_NAME"; then
    pactl load-module module-null-sink \
        sink_name="$VIRTUAL_NAME" \
        sink_properties=device.description="Nubert_Speaker_Remote"
    pactl set-sink-volume "$VIRTUAL_NAME" "${SAFE_START_VOL}%"
fi
pactl set-default-sink "$VIRTUAL_NAME"

# --- 3. The Worker Function ---
LAST_SENT_VOL="-1"
sync_worker() {
    if [[ -f "$LOCK_FILE" ]]; then return; fi
    touch "$LOCK_FILE"

    while true; do
        TARGET_VOL=$(pactl get-sink-volume "$VIRTUAL_NAME" | grep -oP '\d+(?=%)' | head -n 1)
        if [[ "$TARGET_VOL" == "$LAST_SENT_VOL" ]]; then break; fi

        echo "[$(date +%T)] Nubert Volume -> $TARGET_VOL%"
        nubertctl --address "$ADDR" --volume "$TARGET_VOL" > /dev/null 2>&1
        LAST_SENT_VOL="$TARGET_VOL"
        sleep 0.1
    done
    rm -f "$LOCK_FILE"
}

# --- 4. Initial Sync ---
START_VOL=$(pactl get-sink-volume "$VIRTUAL_NAME" | grep -oP '\d+(?=%)' | head -n 1)
LAST_SENT_VOL="$START_VOL"
sync_worker &

echo "--------------------------------------------------------"
echo "Nubert Ghost Bridge Active"
echo "-> Keyboard shortcuts now control the Nubert speakers."
echo "-> Audio streams are auto-routed to $BASE_SINK at 100%."
echo "--------------------------------------------------------"

# --- 5. Main Event Loop ---
pactl subscribe | stdbuf -oL grep -E "sink|sink-input" | while read -r event; do
    
    # A. Auto-route new audio streams
    if echo "$event" | grep -q "new" && echo "$event" | grep -q "sink-input"; then
        pactl list short sink-inputs | awk '{print $1}' | while read -r stream_id; do
            pactl move-sink-input "$stream_id" "$BASE_SINK" 2>/dev/null
        done
    fi

    # B. If volume changes, trigger worker
    if echo "$event" | grep -q "sink" && echo "$event" | grep -q "change"; then
        # Check if the change was on our virtual sink
        SINK_INDEX=$(echo "$event" | grep -oP '(?<=sink #)\d+')
        VIRTUAL_INDEX=$(pactl list short sinks | grep "$VIRTUAL_NAME" | awk '{print $1}')
        
        if [[ "$SINK_INDEX" == "$VIRTUAL_INDEX" ]]; then
            sync_worker &
        fi
        
        # C. Keep physical hardware locked at 100%
        pactl set-sink-volume "$BASE_SINK" 100%
    fi
done
