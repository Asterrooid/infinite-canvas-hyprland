#!/usr/bin/env bash

set -uo pipefail

echo "== Hyprland Version =="
hyprctl version | head -3
echo

echo "== Available methods in hl.dsp.window.* =="
hyprctl repl 'local t={} for k,v in pairs(hl.dsp.window) do table.insert(t,k) end table.sort(t) return table.concat(t, ", ")'
echo "   (if 'resize' does not appear in this list, moveactive/resizewindowpixel"
echo "    may reside in another sub-namespace, or 'move' may handle both)"
echo

ADDR=$(hyprctl activewindow -j 2>/dev/null | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin)["address"])
except Exception:
    print("")' )

if [ -z "$ADDR" ]; then
    echo "No active window detected. Open/focus a floating window and re-run."
    exit 1
fi

echo "== Active window: $ADDR =="
echo

echo "== Testing move to (100, 100) using hypr_ipc.py syntax =="
OUT=$(hyprctl dispatch "hl.dsp.window.move({ window = \"address:$ADDR\", coords = { 100, 100 }, mode = \"exact\" })" 2>&1)
echo "$OUT"
if echo "$OUT" | grep -qi "error"; then
    echo
    echo "-> Failed. Test these manual variants to identify accepted syntax:"
    echo "   hyprctl dispatch 'hl.dsp.window.move({ window = \"address:$ADDR\", x = 100, y = 100 })'"
    echo "   hyprctl dispatch 'hl.dsp.window.move({ window = \"address:$ADDR\", coords = {x=100, y=100} })'"
    echo "   hyprctl dispatch 'hl.dsp.window.move({ window = \"address:$ADDR\", position = {100, 100} })'"
else
    echo "-> OK. Verify visually that the window moved to (100, 100)."
    echo "   If the window did not move but returned no error, test the variants above."
fi
echo

echo "== Testing resize to 800x600 =="
OUT=$(hyprctl dispatch "hl.dsp.window.resize({ window = \"address:$ADDR\", size = { 800, 600 }, mode = \"exact\" })" 2>&1)
echo "$OUT"
if echo "$OUT" | grep -qi "error"; then
    echo
    echo "-> Failed. 'resize' might not exist as a separate dispatcher. Check"
    echo "   the list above (hl.dsp.window.*) and check if 'move' accepts 'size':"
    echo "   hyprctl dispatch 'hl.dsp.window.move({ window = \"address:$ADDR\", size = {800,600} })'"
else
    echo "-> OK. Verify visually that the window now measures 800x600."
fi

echo
echo "== When confirmed, update move_window_exact_lua() and resize_window_exact_lua() in hypr_ipc.py"
