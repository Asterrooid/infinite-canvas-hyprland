#!/usr/bin/env bash
sleep 3
SPEED=1.6

# Get directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detect keyboard - prioritizing real keyboards (without "mouse" in the name)
KBD_DEV=$(python3 -c "
import glob, os

# Keywords indicating not a primary keyboard
ignore_words = ['mouse', 'optical', 'system control', 'consumer control']
real_keyboard = None

for dev in sorted(glob.glob('/dev/input/event*')):
    try:
        with open('/sys/class/input/'+os.path.basename(dev)+'/device/name') as f:
            name = f.read().strip().lower()
        
        # Skip if matching ignored words
        if any(word in name for word in ignore_words):
            continue
            
        # Verify that it is a keyboard
        if 'keyboard' in name or 'kbd' in name or 'gaming keyboard' in name:
            with open('/sys/class/input/'+os.path.basename(dev)+'/device/capabilities/ev') as f:
                caps = int(f.read().strip(), 16)
            if caps & 0x1:  # Has EV_KEY
                real_keyboard = dev
                break
    except:
        continue

# Fallback: find any keyboard device not belonging to a mouse
if not real_keyboard:
    for dev in sorted(glob.glob('/dev/input/event*')):
        try:
            with open('/sys/class/input/'+os.path.basename(dev)+'/device/name') as f:
                name = f.read().strip().lower()
            
            # Explicitly exclude mouse keyboard interfaces
            if 'optical mouse keyboard' in name:
                continue
                
            if 'keyboard' in name or 'kbd' in name:
                with open('/sys/class/input/'+os.path.basename(dev)+'/device/capabilities/ev') as f:
                    caps = int(f.read().strip(), 16)
                if caps & 0x1:
                    real_keyboard = dev
                    break
        except:
            continue

print(real_keyboard if real_keyboard else '')
")

# Detect mouse - search for pointer device
MOUSE_DEV=$(python3 -c "
import glob, os
mouse_found = None
for dev in sorted(glob.glob('/dev/input/event*')):
    try:
        # Verify relative motion capabilities
        with open('/sys/class/input/'+os.path.basename(dev)+'/device/capabilities/rel') as f:
            caps = int(f.read().strip(), 16)
        if caps & 0b11:
            with open('/sys/class/input/'+os.path.basename(dev)+'/device/name') as f:
                name = f.read().strip().lower()
            
            # Prioritize device named 'mouse' without 'keyboard'
            if 'mouse' in name and 'keyboard' not in name:
                print(dev)
                break
            elif 'optical' in name and not mouse_found:
                mouse_found = dev
    except:
        continue

if not mouse_found:
    print('')
")

# Validate device detection
if [ -z "$KBD_DEV" ]; then
    echo "❌ Error: Could not detect keyboard" >&2
    echo "Detected keyboard devices:" >&2
    for dev in /dev/input/event*; do
        name=$(cat "/sys/class/input/$(basename $dev)/device/name" 2>/dev/null)
        if echo "$name" | grep -qi "keyboard\|kbd"; then
            echo "  $dev: $name" >&2
        fi
    done
    exit 1
fi

if [ -z "$MOUSE_DEV" ]; then
    echo "❌ Error: Could not detect mouse" >&2
    echo "Detected mouse devices:" >&2
    for dev in /dev/input/event*; do
        name=$(cat "/sys/class/input/$(basename $dev)/device/name" 2>/dev/null)
        if echo "$name" | grep -qi "mouse\|optical"; then
            echo "  $dev: $name" >&2
        fi
    done
    exit 1
fi

echo "[hypr-canvas] Detected: keyboard=$KBD_DEV mouse=$MOUSE_DEV"

# Sanity check
if [ "$KBD_DEV" = "$MOUSE_DEV" ]; then
    echo "❌ Error: Keyboard and mouse are the same device" >&2
    exit 1
fi

exec python3 "$SCRIPT_DIR/infinite_desktop_core.py" "$SPEED"
