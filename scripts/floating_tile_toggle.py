#!/usr/bin/env python3
"""
floating_tile_toggle.py - Intelligent Infinite Canvas Toggle Engine
Converts all windows on the active workspace into a clean, zoomed-out, non-overlapping
infinite canvas grid, or returns them to standard tiling.
"""

import subprocess
import json
import sys
import os
import fcntl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hypr_ipc import (hyprctl_json, toggle_floating_lua, move_window_exact_lua,
                      resize_window_exact_lua, batch, get_state_file_path)


def get_lock_file_path():
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg and os.path.isdir(xdg):
        return os.path.join(xdg, "floating_tile_toggle.lock")
    try:
        return f"/tmp/floating_tile_toggle_{os.getuid()}.lock"
    except Exception:
        return "/tmp/floating_tile_toggle.lock"


LOCK_FILE = get_lock_file_path()
STATE_FILE = get_state_file_path()


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"⚠️ Error saving state: {e}")


def get_monitor_info():
    monitors = hyprctl_json(["monitors"]) or []
    for m in monitors:
        if m.get("focused"):
            scale = m.get("scale", 1.0)
            return {
                "x": m.get("x", 0),
                "y": m.get("y", 0),
                "w": int(m.get("width", 1920) / scale),
                "h": int(m.get("height", 1080) / scale),
                "scale": scale
            }
    if monitors:
        m = monitors[0]
        scale = m.get("scale", 1.0)
        return {
            "x": m.get("x", 0),
            "y": m.get("y", 0),
            "w": int(m.get("width", 1920) / scale),
            "h": int(m.get("height", 1080) / scale),
            "scale": scale
        }
    return {"x": 0, "y": 0, "w": 1280, "h": 720, "scale": 1.5}


def get_active_workspace():
    ws = hyprctl_json(["activeworkspace"])
    return ws["id"] if ws else None


def get_workspace_windows(workspace_id):
    clients = hyprctl_json(["clients"]) or []
    return [w for w in clients if w.get("workspace", {}).get("id") == workspace_id]


def switch_to_tiled(workspace_id, windows, state):
    ws_key = str(workspace_id)
    positions = {}
    for w in windows:
        positions[w["address"]] = {
            "x": w["at"][0],
            "y": w["at"][1],
            "w": w["size"][0],
            "h": w["size"][1],
            "class": w.get("class", ""),
            "title": w.get("title", ""),
        }

    state[ws_key] = {
        "mode": "tiled",
        "positions": positions
    }
    save_state(state)

    print(f"📦 Switching {len(windows)} windows to Tiled Mode...")
    exprs = [toggle_floating_lua(w["address"]) for w in windows if w.get("floating")]
    if exprs:
        batch(exprs, timeout=5)
    return True


def switch_to_canvas(workspace_id, windows, state):
    ws_key = str(workspace_id)
    mon = get_monitor_info()

    # 1. Float any window that is currently tiled
    tiled_windows = [w for w in windows if not w.get("floating")]
    if tiled_windows:
        float_exprs = [toggle_floating_lua(w["address"]) for w in tiled_windows]
        batch(float_exprs, timeout=5)

    n_windows = len(windows)
    if n_windows == 0:
        return True

    # 2. Compute "Zoom Out" non-overlapping Canvas Layout
    layout_exprs = []
    positions = {}

    if n_windows == 1:
        card_w = min(960, mon["w"] - 100)
        card_h = min(560, mon["h"] - 120)
        x = mon["x"] + (mon["w"] - card_w) // 2
        y = mon["y"] + (mon["h"] - card_h) // 2
        w = windows[0]
        layout_exprs.append(resize_window_exact_lua(card_w, card_h, w["address"]))
        layout_exprs.append(move_window_exact_lua(x, y, w["address"]))
        positions[w["address"]] = {"x": x, "y": y, "w": card_w, "h": card_h}

    elif n_windows == 2:
        gap = 40
        margin_x = 35
        card_w = (mon["w"] - 2 * margin_x - gap) // 2
        card_h = min(520, mon["h"] - 140)
        margin_y = mon["y"] + (mon["h"] - card_h) // 2

        for idx, w in enumerate(windows):
            x = mon["x"] + margin_x + idx * (card_w + gap)
            y = margin_y
            layout_exprs.append(resize_window_exact_lua(card_w, card_h, w["address"]))
            layout_exprs.append(move_window_exact_lua(x, y, w["address"]))
            positions[w["address"]] = {"x": x, "y": y, "w": card_w, "h": card_h}

    else:
        # 3 or more windows: Infinite strip layout with 2 apps visible on initial screen
        gap = 40
        margin_x = 35
        card_w = (mon["w"] - 2 * margin_x - gap) // 2
        card_h = min(520, mon["h"] - 140)
        margin_y = mon["y"] + (mon["h"] - card_h) // 2

        for idx, w in enumerate(windows):
            x = mon["x"] + margin_x + idx * (card_w + gap)
            y = margin_y
            layout_exprs.append(resize_window_exact_lua(card_w, card_h, w["address"]))
            layout_exprs.append(move_window_exact_lua(x, y, w["address"]))
            positions[w["address"]] = {"x": x, "y": y, "w": card_w, "h": card_h}

    if layout_exprs:
        batch(layout_exprs, timeout=5)

    state[ws_key] = {
        "mode": "canvas",
        "positions": positions
    }
    save_state(state)
    print(f"🚀 Canvas Mode activated for {n_windows} windows (Zoom-out layout applied).")
    return True


def main():
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("⚠️ Another instance is running, skipping.")
        sys.exit(0)

    try:
        workspace_id = get_active_workspace()
        if workspace_id is None:
            sys.exit(1)

        windows = get_workspace_windows(workspace_id)
        if not windows:
            print("ℹ️ No windows on active workspace.")
            return

        state = load_state()
        ws_info = state.get(str(workspace_id), {})
        current_mode = ws_info.get("mode", "tiled")
        all_floating = all(w.get("floating") for w in windows)

        # Toggle logic:
        # If currently recorded as canvas AND all windows are floating -> switch to tiled
        # Otherwise -> switch to canvas!
        if current_mode == "canvas" and all_floating:
            switch_to_tiled(workspace_id, windows, state)
        else:
            switch_to_canvas(workspace_id, windows, state)

    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
