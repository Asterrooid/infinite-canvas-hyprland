#!/usr/bin/env python3
import sys, struct, threading, time, subprocess, json, os, socket
import fcntl
import select
import math
from evdev import InputDevice, list_devices, ecodes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hypr_ipc import (move_window_exact_lua, batch_async,
                      resize_window_exact_lua, get_state_file_path,
                      set_floating_lua, get_cursor_pos)

# Device paths are auto-detected by capabilities.
# Usage: infinite_desktop_core.py [speed]
speed = 1.0
for arg in sys.argv[1:]:
    try:
        speed = float(arg)
        break
    except ValueError:
        continue

DEVICE_RESCAN_INTERVAL = 3.0  # seconds between rescans of newly connected/removed devices

EVENT_SIZE = struct.calcsize('llHHi')
EV_KEY=1; EV_REL=2; REL_X=0; REL_Y=1
KEY_LEFTMETA=125; KEY_RIGHTMETA=126
KEY_LEFTALT=56; KEY_RIGHTALT=100
KEY_LEFTCTRL=29; KEY_RIGHTCTRL=97
KEY_LEFT=105; KEY_RIGHT=106
KEY_UP=103; KEY_DOWN=108
BTN_LEFT=272

PROTECTED_APPS = ['brave-browser', 'chromium', 'chromium-browser', 'google-chrome', 
                  'firefox', 'firefoxdeveloperedition', 'librewolf', 'vivaldi', 
                  'opera', 'microsoft-edge']

lock = threading.Lock()
super_pressed=False; alt_pressed=False; ctrl_pressed=False; btn_left=False
acc_x=0.0; acc_y=0.0
frame_held_hidden=False  # Last notified quickshell state (avoids IPC spam)

# Window dragging state variables
window_drag_active = False
last_window_pos = None
last_window_bounds = None
mouse_rel_x = 0
mouse_rel_y = 0

# Keyboard step movement
KEY_MOVE_STEP = 20

def read_inverted():
    candidates = []
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg and os.path.isdir(xdg):
        candidates.append(os.path.join(xdg, "infinite-desktop-state"))
    try:
        candidates.append(f"/tmp/infinite-desktop-state_{os.getuid()}")
    except Exception:
        pass
    candidates.append("/tmp/infinite-desktop-state")

    for path in candidates:
        try:
            if os.path.exists(path):
                with open(path) as f:
                    return f.read().strip() == 'inverse'
        except Exception:
            pass
    return False

def notify_quickshell_hold(state):
    """Notifies quickshell (IpcHandler target='frame') to hide/show the frame.
    Non-blocking: executed in a dedicated thread to prevent latency in the event reader loop.
    Fails silently if quickshell is not running."""
    try:
        subprocess.run(
            ['qs', 'ipc', 'call', 'frame', 'setHeldHidden', 'true' if state else 'false'],
            capture_output=True, timeout=1.0
        )
    except Exception:
        pass

def get_monitor_bounds():
    try:
        r = subprocess.run(['hyprctl', 'monitors', '-j'], capture_output=True, text=True, timeout=0.1)
        monitors = json.loads(r.stdout)
        if monitors:
            for m in monitors:
                if m.get('focused', False):
                    scale = m.get('scale', 1.0)
                    w = int(m['width'] / scale)
                    h = int(m['height'] / scale)
                    return {
                        'left': m['x'],
                        'right': m['x'] + w,
                        'top': m['y'],
                        'bottom': m['y'] + h,
                        'width': w,
                        'height': h
                    }
            m = monitors[0]
            scale = m.get('scale', 1.0)
            w = int(m['width'] / scale)
            h = int(m['height'] / scale)
            return {
                'left': m['x'],
                'right': m['x'] + w,
                'top': m['y'],
                'bottom': m['y'] + h,
                'width': w,
                'height': h
            }
    except:
        pass
    return {'left': 0, 'right': 1280, 'top': 0, 'bottom': 720, 'width': 1280, 'height': 720}

def get_monitor_for_cursor(cx, cy):
    """Returns monitor bounds dict for the monitor containing cursor coordinates (cx, cy)."""
    try:
        r = subprocess.run(['hyprctl', 'monitors', '-j'], capture_output=True, text=True, timeout=0.1)
        monitors = json.loads(r.stdout)
        for m in monitors:
            scale = m.get('scale', 1.0)
            mx = m.get('x', 0)
            my = m.get('y', 0)
            mw = int(m['width'] / scale)
            mh = int(m['height'] / scale)
            if mx <= cx <= mx + mw and my <= cy <= my + mh:
                return {
                    'left': mx,
                    'right': mx + mw,
                    'top': my,
                    'bottom': my + mh,
                    'width': mw,
                    'height': mh
                }
    except Exception:
        pass
    return get_monitor_bounds()

def get_floating_windows(workspace_id):
    try:
        r = subprocess.run(['hyprctl', 'clients', '-j'], capture_output=True, text=True, timeout=0.1)
        clients = json.loads(r.stdout)
        floating = []
        for w in clients:
            if w.get('floating') and w.get('workspace', {}).get('id') == workspace_id:
                floating.append(w)
        return floating
    except:
        return []

def get_focused_window():
    try:
        r = subprocess.run(['hyprctl', 'activewindow', '-j'], capture_output=True, text=True, timeout=0.1)
        return json.loads(r.stdout)
    except:
        return None

def is_protected_app(window):
    if not window:
        return False
    window_class = window.get('class', '').lower()
    return any(app in window_class for app in PROTECTED_APPS)

def get_window_center(window):
    return (window['at'][0] + window['size'][0] // 2,
            window['at'][1] + window['size'][1] // 2)

def get_window_bounds(window):
    x, y = window['at'][0], window['at'][1]
    w, h = window['size'][0], window['size'][1]
    return {
        'left': x,
        'right': x + w,
        'top': y,
        'bottom': y + h,
        'center_x': x + w // 2,
        'center_y': y + h // 2
    }

def windows_overlap_horizontally(bounds1, bounds2):
    return not (bounds1['right'] <= bounds2['left'] or bounds1['left'] >= bounds2['right'])

def windows_overlap_vertically(bounds1, bounds2):
    return not (bounds1['bottom'] <= bounds2['top'] or bounds1['top'] >= bounds2['bottom'])



def pan_other_windows(excluded_addr, dx, dy, workspace_id):
    """Moves all canvas windows EXCEPT the specified window address in a single batch."""
    if dx == 0 and dy == 0:
        return
    try:
        floating_windows = get_floating_windows(workspace_id)
        exprs = []
        for w in floating_windows:
            if w['address'] != excluded_addr:
                nx = int(w['at'][0] + dx)
                ny = int(w['at'][1] + dy)
                exprs.append(move_window_exact_lua(nx, ny, w['address']))
        batch_async(exprs)
    except Exception:
        pass

def get_monitor_center():
    """Returns the logical center coordinates of the focused monitor."""
    try:
        r = subprocess.run(['hyprctl', 'monitors', '-j'], capture_output=True, text=True, timeout=0.1)
        monitors = json.loads(r.stdout)
        for m in monitors:
            if m.get('focused', False):
                scale = m.get('scale', 1.0)
                lw = int(m['width'] / scale)
                lh = int(m['height'] / scale)
                return m['x'] + lw // 2, m['y'] + lh // 2
        if monitors:
            m = monitors[0]
            scale = m.get('scale', 1.0)
            lw = int(m['width'] / scale)
            lh = int(m['height'] / scale)
            return m['x'] + lw // 2, m['y'] + lh // 2
    except Exception:
        pass
    return 640, 360


def monitor_window_drag():
    """Monitors active window dragging and pushes neighboring canvas windows when touching screen bounds."""
    global window_drag_active, last_window_bounds, mouse_rel_x, mouse_rel_y
    
    dragged_window_addr = None
    
    while True:
        try:
            with lock:
                is_dragging = super_pressed and btn_left and not alt_pressed and not ctrl_pressed
                mouse_dx = mouse_rel_x
                mouse_dy = mouse_rel_y
                mouse_rel_x = 0
                mouse_rel_y = 0
            
            if is_dragging and not window_drag_active:
                focused = get_focused_window()
                if focused and focused.get('address'):
                    dragged_window_addr = focused['address']
                    window_drag_active = True
                    last_window_bounds = get_window_bounds(focused)
            
            elif not is_dragging and window_drag_active:
                window_drag_active = False
                dragged_window_addr = None
                last_window_bounds = None
            
            if window_drag_active and dragged_window_addr:
                window = get_focused_window()
                if window and window.get('address') == dragged_window_addr:
                    current_bounds = get_window_bounds(window)
                    monitor = get_monitor_bounds()
                    MARGIN = 10
                    
                    touch_left   = current_bounds['left']   <= monitor['left']   + MARGIN
                    touch_right  = current_bounds['right']  >= monitor['right']  - MARGIN
                    touch_top    = current_bounds['top']    <= monitor['top']    + MARGIN
                    touch_bottom = current_bounds['bottom'] >= monitor['bottom'] - MARGIN
                    
                    if (touch_left or touch_right or touch_top or touch_bottom) and (mouse_dx != 0 or mouse_dy != 0):
                        pan_dx = 0
                        pan_dy = 0
                        
                        if touch_right and mouse_dx > 0:
                            pan_dx = -mouse_dx
                        elif touch_left and mouse_dx < 0:
                            pan_dx = -mouse_dx
                        
                        if touch_bottom and mouse_dy > 0:
                            pan_dy = -mouse_dy
                        elif touch_top and mouse_dy < 0:
                            pan_dy = -mouse_dy
                        
                        if pan_dx != 0 or pan_dy != 0:
                            r = subprocess.run(['hyprctl', 'activeworkspace', '-j'], 
                                             capture_output=True, text=True, timeout=0.1)
                            ws = json.loads(r.stdout)
                            workspace_id = ws['id']
                            pan_other_windows(dragged_window_addr, int(pan_dx), int(pan_dy), workspace_id)
                    
                    last_window_bounds = current_bounds
                else:
                    window_drag_active = False
                    dragged_window_addr = None
            
            time.sleep(0.016)
        except Exception:
            time.sleep(0.1)


def move_active_window(direction):
    """Moves the active window KEY_MOVE_STEP px in the indicated direction.
    If it reaches the monitor edge, pushes neighboring windows in the opposite direction."""
    try:
        r = subprocess.run(['hyprctl', 'activeworkspace', '-j'], capture_output=True, text=True, timeout=0.1)
        ws = json.loads(r.stdout)
        workspace_id = ws['id']

        window = get_focused_window()
        if not window or not window.get('floating'):
            return

        monitor = get_monitor_bounds()
        bounds = get_window_bounds(window)
        addr = window['address']

        dx, dy = 0, 0
        if direction == 'left':
            dx = -KEY_MOVE_STEP
        elif direction == 'right':
            dx = KEY_MOVE_STEP
        elif direction == 'up':
            dy = -KEY_MOVE_STEP
        elif direction == 'down':
            dy = KEY_MOVE_STEP

        new_x = window['at'][0] + dx
        new_y = window['at'][1] + dy

        # Detect edge collision AFTER movement
        new_bounds_left   = new_x
        new_bounds_right  = new_x + window['size'][0]
        new_bounds_top    = new_y
        new_bounds_bottom = new_y + window['size'][1]

        hits_left   = new_bounds_left   <= monitor['left']
        hits_right  = new_bounds_right  >= monitor['right']
        hits_top    = new_bounds_top    <= monitor['top']
        hits_bottom = new_bounds_bottom >= monitor['bottom']

        hitting_edge = (dx < 0 and hits_left) or (dx > 0 and hits_right) or \
                       (dy < 0 and hits_top)  or (dy > 0 and hits_bottom)

        # Move active window
        subprocess.run(['hyprctl', 'dispatch', move_window_exact_lua(new_x, new_y, addr)],
                       capture_output=True, timeout=0.2)

        # If reaching screen edge, pan all other windows in opposite direction
        if hitting_edge:
            pan_other_windows(addr, -dx, -dy, workspace_id)

    except Exception as e:
        print(f"[hypr-canvas] Error in move_active_window: {e}", flush=True)


def classify_device(path):
    """Returns 'mouse', 'touchpad', 'keyboard', or None based on actual device capabilities,
    regardless of brand or device name."""
    try:
        dev = InputDevice(path)
        caps = dev.capabilities()
        dev.close()
    except Exception:
        return None

    keys = set(caps.get(ecodes.EV_KEY, []))
    rels = set(caps.get(ecodes.EV_REL, []))
    abss = set(x[0] if isinstance(x, tuple) else x for x in caps.get(ecodes.EV_ABS, []))

    # A real keyboard features full alphanumeric keys and Meta keys.
    # This filters out consumer/system control interfaces.
    is_keyboard = (
        ecodes.KEY_A in keys and ecodes.KEY_Z in keys and ecodes.KEY_LEFTSHIFT in keys
        and (ecodes.KEY_LEFTMETA in keys or ecodes.KEY_RIGHTMETA in keys)
    )
    if is_keyboard:
        return 'keyboard'

    # Touchpad features absolute X/Y (or MT position) and touch/finger buttons
    is_touchpad = (
        (ecodes.ABS_X in abss or ecodes.ABS_MT_POSITION_X in abss)
        and (ecodes.ABS_Y in abss or ecodes.ABS_MT_POSITION_Y in abss)
        and (ecodes.BTN_TOUCH in keys or ecodes.BTN_TOOL_FINGER in keys)
    )
    if is_touchpad:
        return 'touchpad'

    is_mouse = (ecodes.REL_X in rels and ecodes.REL_Y in rels and ecodes.BTN_LEFT in keys)
    if is_mouse:
        return 'mouse'

    return None


def scan_devices():
    keyboards, mice, touchpads = [], [], []
    for path in list_devices():
        kind = classify_device(path)
        if kind == 'mouse':
            mice.append(path)
        elif kind == 'touchpad':
            touchpads.append(path)
        elif kind == 'keyboard':
            keyboards.append(path)
    return keyboards, mice, touchpads


def kbd_reader_device(path):
    """Reads input events from a single keyboard device."""
    global super_pressed, alt_pressed, ctrl_pressed, frame_held_hidden
    try:
        fd = open(path, 'rb')
    except Exception:
        return

    try:
        while True:
            try:
                data = fd.read(EVENT_SIZE)
            except Exception:
                break
            if not data or len(data) < EVENT_SIZE:
                break
            _, _, etype, code, value = struct.unpack('llHHi', data)
            if etype != EV_KEY:
                continue
            if value == 2:
                continue

            notify_state = None
            with lock:
                if code in (KEY_LEFTMETA, KEY_RIGHTMETA):
                    super_pressed = (value == 1)
                elif code in (KEY_LEFTALT, KEY_RIGHTALT):
                    alt_pressed = (value == 1)
                elif code in (KEY_LEFTCTRL, KEY_RIGHTCTRL):
                    ctrl_pressed = (value == 1)

                combo = super_pressed and alt_pressed
                if combo != frame_held_hidden:
                    frame_held_hidden = combo
                    notify_state = combo

            # Dispatch IPC asynchronously outside lock to keep event reading real-time
            if notify_state is not None:
                threading.Thread(target=notify_quickshell_hold, args=(notify_state,), daemon=True).start()
    finally:
        print(f"[hypr-canvas] Device disconnected: {path}", flush=True)
        try:
            fd.close()
        except Exception:
            pass


def mouse_reader_device(path):
    """Reads input events from a single mouse device."""
    global acc_x, acc_y, btn_left, mouse_rel_x, mouse_rel_y
    try:
        fd = open(path, 'rb')
    except Exception:
        return

    try:
        while True:
            try:
                data = fd.read(EVENT_SIZE)
            except Exception:
                break
            if not data or len(data) < EVENT_SIZE:
                break
            _, _, etype, code, value = struct.unpack('llHHi', data)

            with lock:
                if etype == EV_KEY and code == BTN_LEFT:
                    btn_left = (value == 1)
                elif etype == EV_REL:
                    if code == REL_X:
                        mouse_rel_x += value
                    elif code == REL_Y:
                        mouse_rel_y += value

                    if super_pressed and alt_pressed:
                        sign = -1 if read_inverted() else 1
                        if code == REL_X:
                            acc_x += value * speed * sign
                        elif code == REL_Y:
                            acc_y += value * speed * sign
                    else:
                        acc_x = 0.0
                        acc_y = 0.0
    finally:
        print(f"[hypr-canvas] Device disconnected: {path}", flush=True)
        try:
            fd.close()
        except Exception:
            pass


def touchpad_reader_device(path):
    """Reads input events from a single touchpad device (EV_ABS)."""
    global acc_x, acc_y, btn_left, mouse_rel_x, mouse_rel_y
    try:
        fd = open(path, 'rb')
    except Exception:
        return

    current_slot = 0
    slot0_active = False
    touch_down = False
    cur_x = None
    cur_y = None
    last_x = None
    last_y = None

    try:
        while True:
            try:
                data = fd.read(EVENT_SIZE)
            except Exception:
                break
            if not data or len(data) < EVENT_SIZE:
                break
            _, _, etype, code, value = struct.unpack('llHHi', data)

            if etype == EV_KEY:
                if code == BTN_LEFT:
                    with lock:
                        btn_left = (value == 1)
                elif code == ecodes.BTN_TOUCH:
                    touch_down = (value == 1)
                    if not touch_down:
                        last_x = None
                        last_y = None

            elif etype == ecodes.EV_ABS:
                if code == ecodes.ABS_MT_SLOT:
                    current_slot = value
                elif code == ecodes.ABS_MT_TRACKING_ID and current_slot == 0:
                    if value == -1:
                        slot0_active = False
                        last_x = None
                        last_y = None
                    else:
                        slot0_active = True
                elif current_slot == 0:
                    if code in (ecodes.ABS_MT_POSITION_X, ecodes.ABS_X):
                        cur_x = value
                    elif code in (ecodes.ABS_MT_POSITION_Y, ecodes.ABS_Y):
                        cur_y = value

            elif etype == ecodes.EV_SYN and code == ecodes.SYN_REPORT:
                is_active = touch_down or slot0_active
                if is_active and cur_x is not None and cur_y is not None:
                    if last_x is not None and last_y is not None:
                        dx = cur_x - last_x
                        dy = cur_y - last_y

                        # Filter out multi-finger switches or sudden coordinate jumps (>250 units)
                        if abs(dx) < 250 and abs(dy) < 250 and (dx != 0 or dy != 0):
                            with lock:
                                mouse_rel_x += dx
                                mouse_rel_y += dy
                                if super_pressed and alt_pressed:
                                    sign = -1 if read_inverted() else 1
                                    acc_x += dx * speed * sign
                                    acc_y += dy * speed * sign
                                else:
                                    acc_x = 0.0
                                    acc_y = 0.0
                    last_x = cur_x
                    last_y = cur_y
                elif not is_active:
                    last_x = None
                    last_y = None
    finally:
        print(f"[hypr-canvas] Device disconnected: {path}", flush=True)
        try:
            fd.close()
        except Exception:
            pass


_active_kbd_threads = {}
_active_mouse_threads = {}
_active_touchpad_threads = {}

def device_manager():
    """Periodically scans /dev/input for new or reconnected keyboards, mice, and touchpads,
    spawning a reader thread for each."""
    WARMUP_DURATION = 20.0
    WARMUP_INTERVAL = 0.5
    start_time = time.time()

    while True:
        try:
            keyboards, mice, touchpads = scan_devices()

            for path in keyboards:
                t = _active_kbd_threads.get(path)
                if t is None or not t.is_alive():
                    nt = threading.Thread(target=kbd_reader_device, args=(path,), daemon=True)
                    nt.start()
                    _active_kbd_threads[path] = nt
                    print(f"[hypr-canvas] Device detected: {path}", flush=True)

            for path in mice:
                t = _active_mouse_threads.get(path)
                if t is None or not t.is_alive():
                    nt = threading.Thread(target=mouse_reader_device, args=(path,), daemon=True)
                    nt.start()
                    _active_mouse_threads[path] = nt
                    print(f"[hypr-canvas] Device detected: {path}", flush=True)

            for path in touchpads:
                t = _active_touchpad_threads.get(path)
                if t is None or not t.is_alive():
                    nt = threading.Thread(target=touchpad_reader_device, args=(path,), daemon=True)
                    nt.start()
                    _active_touchpad_threads[path] = nt
                    print(f"[hypr-canvas] Device detected: {path}", flush=True)
        except Exception as e:
            print(f"[hypr-canvas] Error in device_manager: {e}", flush=True)

        elapsed = time.time() - start_time
        interval = WARMUP_INTERVAL if elapsed < WARMUP_DURATION else DEVICE_RESCAN_INTERVAL
        time.sleep(interval)

def on_window_opened(new_addr, initial_cursor=None, win_ws=None):
    cursor_pos = initial_cursor or get_cursor_pos()
    time.sleep(0.08)
    if cursor_pos is None:
        cursor_pos = get_cursor_pos()

    try:
        state_file = get_state_file_path()
        if not os.path.exists(state_file):
            return
        with open(state_file, "r") as f:
            state = json.load(f)

        r = subprocess.run(['hyprctl', 'clients', '-j'], capture_output=True, text=True, timeout=0.2)
        clients = json.loads(r.stdout)

        new_win = next((c for c in clients if c["address"] == new_addr), None)
        if not new_win:
            time.sleep(0.06)
            r = subprocess.run(['hyprctl', 'clients', '-j'], capture_output=True, text=True, timeout=0.2)
            clients = json.loads(r.stdout)
            new_win = next((c for c in clients if c["address"] == new_addr), None)
            if not new_win:
                return

        if win_ws is None:
            raw_ws = new_win.get("workspace", {}).get("id")
            win_ws = str(raw_ws) if raw_ws is not None else None

        if win_ws is None:
            r = subprocess.run(['hyprctl', 'activeworkspace', '-j'], capture_output=True, text=True, timeout=0.1)
            active_ws = json.loads(r.stdout)
            win_ws = str(active_ws.get("id"))

        ws_key = str(win_ws)
        ws_state = state.get(ws_key, {})
        if ws_state.get("mode") != "canvas":
            return

        # Ensure window is floating
        if not new_win.get("floating"):
            subprocess.run(['hyprctl', 'dispatch', set_floating_lua(new_addr, enabled=True)],
                           capture_output=True, timeout=0.2)
            time.sleep(0.02)

        mon = get_monitor_for_cursor(cursor_pos[0], cursor_pos[1]) if cursor_pos else get_monitor_bounds()
        default_w = min(585, mon["width"] - 70)
        default_h = min(520, mon["height"] - 140)

        other_canvas = [c for c in clients if str(c.get("workspace", {}).get("id")) == ws_key and c["address"] != new_addr]
        if other_canvas:
            sample_w = other_canvas[-1].get("size", [default_w, default_h])[0]
            sample_h = other_canvas[-1].get("size", [default_w, default_h])[1]
            if 200 <= sample_w <= mon["width"] and 150 <= sample_h <= mon["height"]:
                card_w = sample_w
                card_h = sample_h
            else:
                card_w = default_w
                card_h = default_h
        else:
            card_w = default_w
            card_h = default_h

        if cursor_pos:
            cx, cy = cursor_pos
            target_x = int(cx - card_w // 2)
            target_y = int(cy - card_h // 2)

            margin = 15
            if mon["width"] > card_w + 2 * margin:
                next_x = max(mon["left"] + margin, min(target_x, mon["right"] - card_w - margin))
            else:
                next_x = mon["left"]

            if mon["height"] > card_h + 2 * margin:
                next_y = max(mon["top"] + margin, min(target_y, mon["bottom"] - card_h - margin))
            else:
                next_y = mon["top"]
        else:
            gap = 40
            margin_x = 35
            margin_y = mon["top"] + (mon["height"] - card_h) // 2
            if other_canvas:
                max_right = max(c["at"][0] + c["size"][0] for c in other_canvas)
                next_x = max_right + gap
                next_y = margin_y
            else:
                next_x = mon["left"] + margin_x
                next_y = margin_y

        resize_expr = resize_window_exact_lua(int(card_w), int(card_h), new_addr)
        move_expr = move_window_exact_lua(int(next_x), int(next_y), new_addr)
        cmd = f"dispatch {resize_expr} ; dispatch {move_expr}"
        subprocess.run(["hyprctl", "--batch", cmd], capture_output=True, timeout=1.0)
        time.sleep(0.04)
        subprocess.run(["hyprctl", "dispatch", move_expr], capture_output=True, timeout=0.5)

        if "positions" not in ws_state:
            ws_state["positions"] = {}
        ws_state["positions"][new_addr] = {
            "x": next_x,
            "y": next_y,
            "w": card_w,
            "h": card_h,
            "class": new_win.get("class", ""),
            "title": new_win.get("title", "")
        }
        with open(state_file, "w") as f:
            json.dump(state, f, indent=2)
        print(f"[hypr-canvas] Auto-captured new window {new_addr} into Infinite Canvas at cursor ({next_x}, {next_y})", flush=True)
    except Exception as e:
        print(f"[hypr-canvas] Error in on_window_opened: {e}", flush=True)


def on_window_closed(closed_addr):
    try:
        state_file = get_state_file_path()
        if not os.path.exists(state_file):
            return
        with open(state_file, "r") as f:
            state = json.load(f)

        modified = False
        for ws_id, ws_state in state.items():
            if isinstance(ws_state, dict) and "positions" in ws_state:
                if closed_addr in ws_state["positions"]:
                    del ws_state["positions"][closed_addr]
                    modified = True

        if modified:
            with open(state_file, "w") as f:
                json.dump(state, f, indent=2)
    except Exception:
        pass


def socket2_listener():
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not xdg_runtime:
        try:
            xdg_runtime = f"/run/user/{os.getuid()}"
        except Exception:
            xdg_runtime = "/tmp"
    if not signature:
        return

    sock_path = f"{xdg_runtime}/hypr/{signature}/.socket2.sock"

    while True:
        try:
            if not os.path.exists(sock_path):
                time.sleep(1)
                continue

            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(sock_path)
            buf = ""

            while True:
                data = s.recv(4096)
                if not data:
                    break
                buf += data.decode("utf-8", errors="ignore")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if line.startswith("openwindow>>"):
                        parts = line[len("openwindow>>"):].split(",", 3)
                        if parts:
                            raw_addr = parts[0].strip()
                            addr = raw_addr if raw_addr.startswith("0x") else f"0x{raw_addr}"
                            win_ws = parts[1].strip() if len(parts) > 1 else None
                            cur = get_cursor_pos()
                            threading.Thread(target=on_window_opened, args=(addr, cur, win_ws), daemon=True).start()
                    elif line.startswith("closewindow>>"):
                        raw_addr = line[len("closewindow>>"):].strip()
                        addr = raw_addr if raw_addr.startswith("0x") else f"0x{raw_addr}"
                        threading.Thread(target=on_window_closed, args=(addr,), daemon=True).start()
        except Exception:
            time.sleep(1)


# Preload Hyprland IPC
print("[hypr-canvas] Preloading components...", flush=True)
try:
    subprocess.run(['hyprctl', 'activeworkspace', '-j'], capture_output=True, text=True, timeout=0.5)
    subprocess.run(['hyprctl', 'clients', '-j'], capture_output=True, text=True, timeout=0.5)
except Exception:
    pass

threading.Thread(target=device_manager, daemon=True).start()
threading.Thread(target=monitor_window_drag, daemon=True).start()
threading.Thread(target=socket2_listener, daemon=True).start()
print("[hypr-canvas] Infinite Desktop active (automatic device detection enabled)", flush=True)
print("[hypr-canvas] Super + Left Click: Drag window (at edge, screen follows)", flush=True)
print("[hypr-canvas] Super + Alt + Mouse: Pan entire canvas", flush=True)
print("[hypr-canvas] Super + Arrows: Navigation via Hyprland bind", flush=True)
print("[hypr-canvas] Super + Shift + Arrows: Move active window via Hyprland bind", flush=True)

# Active workspace cache (refreshed every 2s to minimize hyprctl calls)
_cached_workspace_id = None
_last_workspace_check = 0
WORKSPACE_CACHE_TTL = 2.0

def get_cached_workspace_id():
    global _cached_workspace_id, _last_workspace_check
    now = time.time()
    if _cached_workspace_id is None or (now - _last_workspace_check) > WORKSPACE_CACHE_TTL:
        try:
            r = subprocess.run(['hyprctl', 'activeworkspace', '-j'],
                               capture_output=True, text=True, timeout=0.1)
            ws = json.loads(r.stdout)
            _cached_workspace_id = ws['id']
            _last_workspace_check = now
        except Exception:
            pass
    return _cached_workspace_id

# Main event loop for canvas panning
while True:
    time.sleep(0.016)

    with lock:
        active_drag = super_pressed and alt_pressed
        dx = acc_x
        dy = acc_y
        acc_x = 0.0
        acc_y = 0.0

    if not active_drag:
        continue

    idx = int(round(dx))
    idy = int(round(dy))

    if idx == 0 and idy == 0:
        continue

    try:
        workspace_id = get_cached_workspace_id()
        if workspace_id is None:
            continue

        r = subprocess.run(['hyprctl', 'clients', '-j'], capture_output=True, text=True, timeout=0.1)
        clients = json.loads(r.stdout)

        exprs = []
        for w in clients:
            if w.get('floating') and w.get('workspace', {}).get('id') == workspace_id:
                nx = w['at'][0] + idx
                ny = w['at'][1] + idy
                exprs.append(move_window_exact_lua(nx, ny, w['address']))

        batch_async(exprs)
    except Exception:
        pass