# Infinite Canvas Hyprland (Works on NixOS)

Transform your Hyprland desktop into a boundless whiteboard workspace with Figma/Miro-style focal zoom, Socket2 auto-capture strip daemon, and smart tiling.

[![Hyprland 0.55+](https://img.shields.io/badge/Hyprland-0.55%2B%20(Lua)-00A3E0?style=for-the-badge&logo=hyprland&logoColor=white)](https://hyprland.org)
[![NixOS](https://img.shields.io/badge/NixOS-Supported-5277C3?style=for-the-badge&logo=nixos&logoColor=white)](https://nixos.org)
[![Arch Linux](https://img.shields.io/badge/Arch_Linux-Supported-1793D1?style=for-the-badge&logo=arch-linux&logoColor=white)](https://archlinux.org)
[![Fedora](https://img.shields.io/badge/Fedora-Supported-51A2DA?style=for-the-badge&logo=fedora&logoColor=white)](https://getfedora.org)
[![Ubuntu](https://img.shields.io/badge/Ubuntu-Supported-E95420?style=for-the-badge&logo=ubuntu&logoColor=white)](https://ubuntu.com)
[![Python 3](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)

<p align="center">
  <img width="100%" alt="Infinite Canvas Hyprland Preview" src="https://github.com/user-attachments/assets/464fa371-7cc4-4fd5-a06c-55d7b51ba59d" />
</p>

---

## 🚀 Features

- 🔍 **Figma/Miro Canvas Zoom**: Focal-point zoom in, zoom out, and reset centered directly on your mouse cursor.
- ⚡ **Socket2 Auto-Capture Daemon**: Listens to Hyprland's IPC event stream in real time; opening new windows while in Canvas Mode automatically sizes them as cards and appends them to the canvas strip.
- 📐 **Smart Strip Layout Engine**: Replaces messy overlapping window stacks with clean, non-overlapping horizontal card strips with 40px gaps.
- 🖥️ **Fractional HiDPI Display Scaling**: Fixed monitor bounds calculation (`width/scale`, `height/scale`) for smooth panning on scaled laptop and 4K displays.
- 🔄 **Instant Tiled <-> Canvas Toggle**: One key shortcut (`SUPER + D`) flips between traditional tiling and Infinite Canvas without losing your window layout.
- 🧭 **Center & Directional Navigation**: `SUPER + Arrow Keys` smoothly navigates focus and centers cards in your viewport.

---

## ⌨️ Keybinding Cheat Sheet

| Keybinding | Action | Description |
| :--- | :--- | :--- |
| `SUPER + D` | Toggle Tiled <-> Canvas | Flips between traditional tiled layout and Infinite Canvas strip |
| `SUPER + ALT + Mouse Drag` | Pan Entire Canvas | Pan across the infinite canvas smoothly |
| `SUPER + Left Click Drag` | Drag Window | Drag floating window (viewport auto-pans at screen edges) |
| `SUPER + CTRL + Scroll Up` | Canvas Zoom In | Focal zoom in centered directly on mouse cursor |
| `SUPER + CTRL + Scroll Down` | Canvas Zoom Out | Focal zoom out centered directly on mouse cursor |
| `SUPER + CTRL + 0` | Reset Canvas Zoom | Reset card sizes to 100% standard dimensions |
| `SUPER + Arrow Keys` | Focus & Center Window | Navigate focus and center window in viewport |
| `SUPER + SHIFT + Arrow Keys` | Move Floating Window | Fine-tune floating card position |
| `SUPER + CTRL + Arrow Keys` | Resize Window | Resize focused window |
| `SUPER + ALT + Arrow Keys` | Move Tiled Window | Swap or reorder window in standard tiled layout |
| `SUPER + Z / X` | Switch Workspaces | Cycle to previous or next workspace |

---

## 📦 Installation & Setup

**Automated Installer (All Distros)**:

Run the 1-click automated installer to install dependencies, copy scripts to `~/scripts`, configure user permissions, and update your configuration:

```bash
git clone https://github.com/Asterrooid/infinite-canvas-hyprland.git
cd infinite-canvas-hyprland
chmod +x install.sh
./install.sh
```

---

**NixOS Support**:

Infinite Canvas Hyprland runs seamlessly on NixOS. You can configure it declaratively or run it directly using Nix Flakes.

**Option 1: Declarative Configuration (`/etc/nixos/configuration.nix`)**

Add required system packages and ensure your user belongs to the `input` group (needed for mouse evdev tracking):

```nix
environment.systemPackages = with pkgs; [
  (python3.withPackages (ps: with ps; [ evdev ]))
  jq
];
users.users.<username>.extraGroups = [ "input" ];
```

Rebuild your system:
```bash
sudo nixos-rebuild switch
```

**Option 2: Native Nix Flake**

Run directly without manual dependency management:

```bash
nix run github:Asterrooid/infinite-canvas-hyprland
```

---

**Traditional Distros (Manual Setup)**:

Install the required packages (`python3`, `python-evdev`, `bash`, `jq`):

- **Arch Linux:**
  ```bash
  sudo pacman -S python python-evdev bash jq
  ```

- **Fedora:**
  ```bash
  sudo dnf install python3 python3-evdev bash jq
  ```

- **Ubuntu / Debian:**
  ```bash
  sudo apt install python3 python3-evdev bash jq
  ```

**Configure User Permissions**:
Add your user account to the `input` group so the core daemon can read mouse gestures:
```bash
sudo usermod -aG input $USER
```
*(Note: Log out and back in, or reboot your machine for group changes to take effect.)*

**Install Scripts**:
```bash
mkdir -p ~/scripts
cp scripts/* ~/scripts/
chmod +x ~/scripts/*.py ~/scripts/*.sh
```

---

## ⚙️ Hyprland Configuration

Add the daemon autostart and keybindings to your Hyprland configuration (`~/.config/hypr/hyprland.lua`):

**1. Daemon Autostart**

```lua
-- Autostart Infinite Canvas Daemon (Socket2 IPC & Pan Engine)
hl.on("hyprland.start", function()
    hl.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/infinite_desktop_core.py 1.6 > /tmp/infinite-desktop.log 2>&1")
end)
```

**2. Keybindings**

```lua
local mainMod = "SUPER"

-- Workspace Navigation
hl.bind(mainMod .. " + Z", hl.dsp.focus({ workspace = "-1" }))
hl.bind(mainMod .. " + X", hl.dsp.focus({ workspace = "+1" }))
hl.bind(mainMod .. " + SHIFT + Z", hl.dsp.window.move({ workspace = "-1" }))
hl.bind(mainMod .. " + SHIFT + X", hl.dsp.window.move({ workspace = "+1" }))

-- Toggle Tiled <-> Canvas Mode
hl.bind(mainMod .. " + D", hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/floating_tile_toggle.py"))

-- Figma/Miro Canvas Focal Zoom
hl.bind(mainMod .. " + CTRL + mouse_up", hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/canvas_zoom.py in"))
hl.bind(mainMod .. " + CTRL + mouse_down", hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/canvas_zoom.py out"))
hl.bind(mainMod .. " + CTRL + 0", hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/canvas_zoom.py reset"))

-- Navigation & Centering
hl.bind(mainMod .. " + left",  hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/navigate_windows.py left"))
hl.bind(mainMod .. " + right", hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/navigate_windows.py right"))
hl.bind(mainMod .. " + up",    hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/navigate_windows.py up"))
hl.bind(mainMod .. " + down",  hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/navigate_windows.py down"))

-- Window Adjustments (Floating & Tiled)
hl.bind(mainMod .. " + SHIFT + left",  hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/move_window.py left"),  { repeating = true })
hl.bind(mainMod .. " + SHIFT + right", hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/move_window.py right"), { repeating = true })
hl.bind(mainMod .. " + SHIFT + up",    hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/move_window.py up"),    { repeating = true })
hl.bind(mainMod .. " + SHIFT + down",  hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/move_window.py down"),  { repeating = true })

hl.bind(mainMod .. " + CTRL + left",  hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/resize_window.py left"),  { repeating = true })
hl.bind(mainMod .. " + CTRL + right", hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/resize_window.py right"), { repeating = true })
hl.bind(mainMod .. " + CTRL + up",    hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/resize_window.py up"),    { repeating = true })
hl.bind(mainMod .. " + CTRL + down",  hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/resize_window.py down"),  { repeating = true })

hl.bind(mainMod .. " + ALT + left",  hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/move_window_tiled.py left"))
hl.bind(mainMod .. " + ALT + right", hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/move_window_tiled.py right"))
hl.bind(mainMod .. " + ALT + up",    hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/move_window_tiled.py up"))
hl.bind(mainMod .. " + ALT + down",  hl.dsp.exec_cmd("python3 " .. os.getenv("HOME") .. "/scripts/move_window_tiled.py down"))
```

---

## 🤝 Attribution & Credits

Special thanks to **Sarods2D** for creating the foundational concept and initial implementation of the infinite desktop in [`sarodscommits/hyprland-infinitie-desktop-v2`](https://github.com/sarodscommits/hyprland-infinitie-desktop-v2).

This repository is an enhanced, independent evolution developed by **Asterrooid**, engineered to provide:
- Figma/Miro-style focal cursor zoom (`canvas_zoom.py`)
- Real-time Socket2 IPC event stream auto-capture daemon for dynamic card insertion
- Smart non-overlapping horizontal strip layout engine
- Fractional HiDPI display scaling support for laptop and 4K displays
- Native NixOS declarative and Flake architecture

---

## 📄 License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
