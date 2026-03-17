#!/bin/bash
# set -x # Uncomment for verbose debugging

# Configuration
ADDR="$1"
VIRTUAL_NAME="Nubert_Virtual_Control"
SAFE_START_VOL="20"
SOCKET="/tmp/nubert.sock"

# 0. Basic argument check
if [[ -z "$ADDR" ]]; then
    echo "Usage: $0 "nubert X-2 2272""
    exit 1
fi

ESCAPED_ADDR=$(systemd-escape "$ADDR")

# 1. Ensure the daemon socket exists
if [[ ! -S "$SOCKET" ]]; then
    echo "Error: Daemon socket not found at $SOCKET."
    echo "Please ensure the nubert-daemon@${ESCAPED_ADDR}.service is running."
    echo "You can start it with: systemctl --user start nubert-daemon@${ESCAPED_ADDR}.service"
    exit 1
fi

# 2. Determine the actual physical hardware sink (MOST IMPORTANT ROBUSTNESS IMPROVEMENT)
# We need to find a sink that ISN'T our virtual sink, and isn't a monitor/null sink.
PHYSICAL_SINK_CANDIDATE=""
CURRENT_DEFAULT_ON_START=$(pactl get-default-sink 2>/dev/null || echo "")

if [[ -n "$CURRENT_DEFAULT_ON_START" && "$CURRENT_DEFAULT_ON_START" != "$VIRTUAL_NAME" ]]; then
    # If there's an existing default sink and it's not our virtual one, use it as a primary candidate.
    PHYSICAL_SINK_CANDIDATE="$CURRENT_DEFAULT_ON_START"
else
    # Otherwise, iterate through sinks and pick the first "real" one.
    # Exclude our virtual sink, any monitor outputs, and null sinks.
    PHYSICAL_SINK_CANDIDATE=$(pactl list short sinks \
        | grep -v "$VIRTUAL_NAME" \
        | grep -v ".monitor" \
        | grep -v "null" \
        | awk '{print $2}' \
        | head -n 1)
fi

if [[ -z "$PHYSICAL_SINK_CANDIDATE" ]]; then
    echo "Error: Could not identify a suitable physical audio output device."
    echo "Please ensure you have a sound card or Bluetooth audio device available and not named '$VIRTUAL_NAME'."
    exit 1
fi
BASE_SINK="$PHYSICAL_SINK_CANDIDATE"
echo "Identified physical audio output: $BASE_SINK"

# 3. Ensure the virtual sink exists and is configured
if ! pactl list short sinks | grep -q "$VIRTUAL_NAME"; then
    echo "Creating virtual sink '$VIRTUAL_NAME'..."
    pactl load-module module-null-sink \
        sink_name="$VIRTUAL_NAME" \
        sink_properties=device.description="Nubert_Speaker_Remote"
    pactl set-sink-volume "$VIRTUAL_NAME" "${SAFE_START_VOL}%"
else
    echo "Virtual sink '$VIRTUAL_NAME' already exists."
fi

# 4. Set the physical sink's volume to 100% (always)
# This ensures that actual audio output is always at max, and Nubert controls the gain.
echo "Setting physical sink '$BASE_SINK' volume to 100%."
pactl set-sink-volume "$BASE_SINK" 100%

# 5. Set the virtual sink as the system default
# This allows user volume keys/sliders to control the virtual sink.
echo "Setting system default sink to '$VIRTUAL_NAME'."
pactl set-default-sink "$VIRTUAL_NAME"

# 6. Monitor volume changes and send to daemon
LAST_SENT_VOL="-1"
pactl subscribe | stdbuf -oL grep -E "sink|sink-input" | while read -r event; do
    # echo "Event: $event" # Uncomment for verbose event logging

    # Handle New Streams: Redirect them to the physical hardware sink
    if echo "$event" | grep -q "new" && echo "$event" | grep -q "sink-input"; then
        echo "New stream detected, routing to $BASE_SINK"
        # Iterate over all sink inputs and move them if they are not already on BASE_SINK
        pactl list short sink-inputs | awk '{print $1, $2}' | while read -r stream_id_and_sink; do
            stream_id=$(echo "$stream_id_and_sink" | awk '{print $1}')
            current_sink=$(echo "$stream_id_and_sink" | awk '{print $2}')
            if [[ "$current_sink" != "$BASE_SINK" ]]; then
                # Only move if it's not already there to avoid unnecessary operations/errors
                pactl move-sink-input "$stream_id" "$BASE_SINK" 2>/dev/null
            fi
        done
    fi

    # Handle Volume Changes on the virtual sink
    # Check for "change" and "sink" keywords in any order
    if echo "$event" | grep -q "change" && echo "$event" | grep -q "sink"; then
        # Identify which sink changed
        CHANGED_INDEX=$(echo "$event" | grep -oP 'sink #\K\d+')
        VIRTUAL_INDEX=$(pactl list short sinks | grep "$VIRTUAL_NAME" | awk '{print $1}')

        if [[ "$CHANGED_INDEX" == "$VIRTUAL_INDEX" ]]; then
            # Extract volume percentage from the virtual sink
            TARGET_VOL=$(pactl get-sink-volume "$VIRTUAL_NAME" | grep -oP '\d+(?=%)' | head -n 1)

            if [[ "$TARGET_VOL" != "$LAST_SENT_VOL" ]]; then
                echo "Sending volume $TARGET_VOL to Nubert..."
                echo "$TARGET_VOL" | socat - UNIX-CONNECT:"$SOCKET"
                LAST_SENT_VOL="$TARGET_VOL"
            fi
        fi

        # Keep the hardware sink at 100% so only Nubert controls the gain
        # This line is crucial and must apply to the PHYSICAL sink.
        # It's here in the loop to counteract any application that might try to lower the BASE_SINK volume.
        pactl set-sink-volume "$BASE_SINK" 100%
    fi
done
