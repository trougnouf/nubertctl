#!/bin/bash

# Nubert Volume Sync
# Works with PulseAudio and PipeWire
# Usage: ./nubert_pulseaudio_sync.sh <MAC_ADDRESS>

ADDR="$1"

if [[ -z "$ADDR" ]]; then
    echo "Usage: $0 <SPEAKER_ADDRESS>"
    exit 1
fi

echo "Syncing system volume to Nubert speaker [$ADDR]..."

LAST_VOL="-1"

# Listen to all audio server events
pactl subscribe | while read -r event; do
    # We only care about volume changes on the output (sink)
    if echo "$event" | grep -q "sink"; then
        
        # Get the current volume level of the default output
        CURRENT_VOL=$(pactl get-sink-volume @DEFAULT_SINK@ | awk -F '/' '{print $2}' | grep -oP '\d+(?=%)' | head -n 1)

        # Proceed only if volume changed and we aren't already mid-connection
        if [ "$CURRENT_VOL" != "$LAST_VOL" ]; then
            
            # Check if nubertctl is already running to avoid BLE congestion
            if pgrep -x "nubertctl" > /dev/null; then
                continue
            fi

            LAST_VOL="$CURRENT_VOL"
            # Send volume to speaker in background
            nubertctl --address "$ADDR" --volume "$CURRENT_VOL" > /dev/null 2>&1 &
        fi
    fi
done
