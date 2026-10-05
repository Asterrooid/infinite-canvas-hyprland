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
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hypr_ipc import (hyprctl_json, set_floating_lua, toggle_floating_lua, move_window_exact_lua,
                      resize_window_exact_lua, batch, batch_async, get_state_file_path)


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
            "x": int(w["at"][0]),
            "y": int(w["at"][1]),
            "w": int(w["size"][0]),
            "h": int(w["size"][1]),
            "class": w.get("class", ""),
            "title": w.get("title", ""),
        }

    state[ws_key] = {
        "mode": "tiled",
        "positions": positions
    }
    save_state(state)

    print(f"📦 Switching {len(windows)} windows to Tiled Mode...")
    exprs = [set_floating_lua(w["address"], enabled=False) for w in windows if w.get("floating")]
    if exprs:
        batch(exprs, timeout=5)
    return True


def switch_to_canvas(workspace_id, windows, state):
    ws_key = str(workspace_id)
    mon = get_monitor_info()

    # 1. Float any window that is currently tiled
    tiled_windows = [w for w in windows if not w.get("floating")]
    if tiled_windows:
        float_exprs = [set_floating_lua(w["address"], enabled=True) for w in tiled_windows]
        batch(float_exprs, timeout=5)
        time.sleep(0.04)

    n_windows = len(windows)
    if n_windows == 0:
        state[ws_key] = {
            "mode": "canvas",
            "positions": {}
        }
        save_state(state)
        return True

    ws_state = state.get(ws_key, {})
    saved_positions = ws_state.get("positions", {})

    restored = []
    unplaced = []
    for w in windows:
        addr = w["address"]
        if addr in saved_positions and isinstance(saved_positions[addr], dict):
            restored.append((w, saved_positions[addr]))
        else:
            unplaced.append(w)

    default_w = min(585, mon["w"] - 70)
    default_h = min(520, mon["h"] - 140)
    layout_exprs = []
    positions = {}

    if restored:
        for w, pos in restored:
            addr = w["address"]
            card_w = int(pos.get("w", default_w))
            card_h = int(pos.get("h", default_h))
            x = int(pos.get("x", mon["x"] + 35))
            y = int(pos.get("y", mon["y"] + (mon["h"] - card_h) // 2))

            layout_exprs.append(resize_window_exact_lua(card_w, card_h, addr))
            layout_exprs.append(move_window_exact_lua(x, y, addr))
            positions[addr] = {
                "x": x,
                "y": y,
                "w": card_w,
                "h": card_h,
                "class": w.get("class", ""),
                "title": w.get("title", "")
            }

        if unplaced:
            gap = 40
            max_right = max(p["x"] + p["w"] for p in positions.values())
            align_y = mon["y"] + (mon["h"] - default_h) // 2

            for idx, w in enumerate(unplaced):
                addr = w["address"]
                x = max_right + gap + idx * (default_w + gap)
                y = align_y
                layout_exprs.append(resize_window_exact_lua(default_w, default_h, addr))
                layout_exprs.append(move_window_exact_lua(x, y, addr))
                positions[addr] = {
                    "x": x,
                    "y": y,
                    "w": default_w,
                    "h": default_h,
                    "class": w.get("class", ""),
                    "title": w.get("title", "")
                }

        msg = f"🚀 Canvas Mode restored for {n_windows} windows ({len(restored)} restored, {len(unplaced)} new)."
    else:
        # Fallback to initial layout if no saved canvas arrangement exists
        if n_windows == 1:
            card_w = min(960, mon["w"] - 100)
            card_h = min(560, mon["h"] - 120)
            x = mon["x"] + (mon["w"] - card_w) // 2
            y = mon["y"] + (mon["h"] - card_h) // 2
            w = windows[0]
            layout_exprs.append(resize_window_exact_lua(card_w, card_h, w["address"]))
            layout_exprs.append(move_window_exact_lua(x, y, w["address"]))
            positions[w["address"]] = {
                "x": x, "y": y, "w": card_w, "h": card_h,
                "class": w.get("class", ""), "title": w.get("title", "")
            }
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
                positions[w["address"]] = {
                    "x": x, "y": y, "w": card_w, "h": card_h,
                    "class": w.get("class", ""), "title": w.get("title", "")
                }
        else:
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
                positions[w["address"]] = {
                    "x": x, "y": y, "w": card_w, "h": card_h,
                    "class": w.get("class", ""), "title": w.get("title", "")
                }
        msg = f"🚀 Canvas Mode activated for {n_windows} windows (Initial layout applied)."

    if layout_exprs:
        batch(layout_exprs, timeout=5)
        time.sleep(0.04)
        reinforce_exprs = [move_window_exact_lua(pos["x"], pos["y"], addr) for addr, pos in positions.items()]
        batch_async(reinforce_exprs)

    state[ws_key] = {
        "mode": "canvas",
        "positions": positions
    }
    save_state(state)
    print(msg)
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
