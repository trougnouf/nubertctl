#!/bin/bash

# Configuration
ADDR="$1"
VIRTUAL_NAME="Nubert_Virtual_Control"
SAFE_START_VOL="20"
SOCKET="/tmp/nubert.sock"

if [[ -z "$ADDR" ]]; then
    echo "Usage: $0 51:FA:D1:39:F8:AB"
    exit 1
fi

# Ensure the virtual sink exists
if ! pactl list short sinks | grep -q "$VIRTUAL_NAME"; then
    echo "Creating virtual sink..."
    pactl load-module module-null-sink \
        sink_name="$VIRTUAL_NAME" \
        sink_properties=device.description="Nubert_Speaker_Remote"
    pactl set-sink-volume "$VIRTUAL_NAME" "${SAFE_START_VOL}%"
fi

# Determine the physical hardware sink to actually play audio
BASE_SINK=$(pactl get-default-sink)
if [[ "$BASE_SINK" == "$VIRTUAL_NAME" ]]; then
    BASE_SINK=$(pactl list short sinks | grep -v "$VIRTUAL_NAME" | awk '{print $2}' | head -n 1)
fi

echo "Routing audio to: $BASE_SINK"
echo "Control via: $VIRTUAL_NAME"

# Set default to virtual so user volume keys control it
pactl set-default-sink "$VIRTUAL_NAME"

LAST_SENT_VOL="-1"

# Monitor events
# We use a more robust regex to catch "change" and "sink" in any order
pactl subscribe | stdbuf -oL grep -E "sink|sink-input" | while read -r event; do

    # 1. Handle New Streams: Redirect them to the physical hardware
    if echo "$event" | grep -q "new" && echo "$event" | grep -q "sink-input"; then
        pactl list short sink-inputs | awk '{print $1}' | while read -r stream_id; do
            pactl move-sink-input "$stream_id" "$BASE_SINK" 2>/dev/null
        done
    fi

    # 2. Handle Volume Changes
    if echo "$event" | grep -q "change" && echo "$event" | grep -q "sink"; then
        # Identify which sink changed
        CHANGED_INDEX=$(echo "$event" | grep -oP 'sink #\K\d+')
        VIRTUAL_INDEX=$(pactl list short sinks | grep "$VIRTUAL_NAME" | awk '{print $1}')

        if [[ "$CHANGED_INDEX" == "$VIRTUAL_INDEX" ]]; then
            # Extract volume percentage
            TARGET_VOL=$(pactl get-sink-volume "$VIRTUAL_NAME" | grep -oP '\d+(?=%)' | head -n 1)

            if [[ "$TARGET_VOL" != "$LAST_SENT_VOL" ]]; then
                echo "Sending volume $TARGET_VOL to Nubert..."
                echo "$TARGET_VOL" | socat - UNIX-CONNECT:"$SOCKET"
                LAST_SENT_VOL="$TARGET_VOL"
            fi
        fi

        # Keep the hardware sink at 100% so only Nubert controls the gain
        pactl set-sink-volume "$BASE_SINK" 100%
    fi
done
