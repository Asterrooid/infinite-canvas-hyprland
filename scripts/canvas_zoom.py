#!/usr/bin/env python3
"""
canvas_zoom.py - Infinite Canvas Zoom In / Out Engine
Scales floating windows relative to mouse cursor position (or monitor center)
for a true Figma/Miro-style infinite whiteboard zoom experience.
"""

import sys
import os
import json
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hypr_ipc import (hyprctl_json, move_window_exact_lua, resize_window_exact_lua,
                      batch_async, get_state_file_path, get_cursor_pos)

STATE_FILE = get_state_file_path()
ZOOM_FACTOR_IN = 1.15
ZOOM_FACTOR_OUT = 0.85

MIN_WIDTH = 280
MIN_HEIGHT = 200
MAX_WIDTH = 1240
MAX_HEIGHT = 680


def get_focal_point():
    # Try mouse cursor position first
    cur = get_cursor_pos()
    if cur and (cur[0] > 0 or cur[1] > 0):
        return cur[0], cur[1]

    # Fallback to monitor center
    monitors = hyprctl_json(["monitors"]) or []
    for m in monitors:
        if m.get("focused"):
            scale = m.get("scale", 1.0)
            lw = int(m["width"] / scale)
            lh = int(m["height"] / scale)
            return m.get("x", 0) + lw // 2, m.get("y", 0) + lh // 2
    return 640, 360


def zoom_canvas(direction):
    ws = hyprctl_json(["activeworkspace"])
    if not ws:
        return
    workspace_id = ws["id"]

    clients = hyprctl_json(["clients"]) or []
    floating = [
        w for w in clients
        if w.get("floating") and w.get("workspace", {}).get("id") == workspace_id
    ]

    if not floating:
        return

    if direction == "reset":
        scale = 1.0
        # Reset cards to standard 585x520
        exprs = []
        for w in floating:
            exprs.append(resize_window_exact_lua(585, 520, w["address"]))
        if exprs:
            batch_async(exprs)
        return

    scale = ZOOM_FACTOR_IN if direction == "in" else ZOOM_FACTOR_OUT
    fx, fy = get_focal_point()

    exprs = []
    updated_positions = {}

    for w in floating:
        curr_x, curr_y = w["at"][0], w["at"][1]
        curr_w, curr_h = w["size"][0], w["size"][1]

        # Calculate new dimensions clamped to limits
        new_w = int(curr_w * scale)
        new_h = int(curr_h * scale)

        if direction == "out":
            if new_w < MIN_WIDTH or new_h < MIN_HEIGHT:
                new_w = max(new_w, MIN_WIDTH)
                new_h = max(new_h, MIN_HEIGHT)
        else:
            if new_w > MAX_WIDTH or new_h > MAX_HEIGHT:
                new_w = min(new_w, MAX_WIDTH)
                new_h = min(new_h, MAX_HEIGHT)

        # Scale center position relative to focal point
        center_x = curr_x + curr_w / 2
        center_y = curr_y + curr_h / 2

        new_center_x = fx + (center_x - fx) * scale
        new_center_y = fy + (center_y - fy) * scale

        new_x = int(new_center_x - new_w / 2)
        new_y = int(new_center_y - new_h / 2)

        exprs.append(resize_window_exact_lua(new_w, new_h, w["address"]))
        exprs.append(move_window_exact_lua(new_x, new_y, w["address"]))

        updated_positions[w["address"]] = {
            "x": new_x,
            "y": new_y,
            "w": new_w,
            "h": new_h
        }

    if exprs:
        batch_async(exprs)

    # Save to state if canvas state exists
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
            ws_key = str(workspace_id)
            if ws_key in state and state[ws_key].get("mode") == "canvas":
                if "positions" not in state[ws_key]:
                    state[ws_key]["positions"] = {}
                state[ws_key]["positions"].update(updated_positions)
                with open(STATE_FILE, "w") as f:
                    json.dump(state, f, indent=2)
    except Exception:
        pass


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("in", "out", "reset"):
        print("Usage: canvas_zoom.py <in|out|reset>")
        sys.exit(1)

    zoom_canvas(sys.argv[1])


if __name__ == "__main__":
    main()
