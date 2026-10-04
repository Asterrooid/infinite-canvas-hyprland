#!/usr/bin/env bash
#
# Infinite Canvas Hyprland Installer
# Seamless installer for infinite canvas panning, navigation, and zoom tools.
#
set -euo pipefail

REPO_URL="https://github.com/Asterrooid/infinite-canvas-hyprland"
REPO_TARBALL="https://codeload.github.com/Asterrooid/infinite-canvas-hyprland/tar.gz/refs/heads/main"
SCRIPTS_DEST="${HOME}/scripts"
HYPR_LUA="${HOME}/.config/hypr/hyprland.lua"
TMP_DIR="$(mktemp -d)"

C_RESET="\033[0m"; C_BOLD="\033[1m"; C_GREEN="\033[32m"; C_YELLOW="\033[33m"; C_RED="\033[31m"; C_CYAN="\033[36m"

log()  { echo -e "${C_CYAN}==>${C_RESET} $*"; }
ok()   { echo -e "${C_GREEN}[OK]${C_RESET} $*"; }
warn() { echo -e "${C_YELLOW}[WARNING]${C_RESET} $*"; }
err()  { echo -e "${C_RED}[ERROR]${C_RESET} $*" >&2; }

cleanup() { rm -rf "${TMP_DIR}"; }
trap cleanup EXIT

require_cmd() {
    command -v "$1" >/dev/null 2>&1
}

# 1. Package Installation & Verification
IS_NIXOS=0

install_packages() {
    log "Detecting distro and verifying required packages (python, python-evdev, bash, jq)..."

    if [ -f /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        DISTRO_ID="${ID:-unknown}"
        DISTRO_LIKE="${ID_LIKE:-}"
    else
        DISTRO_ID="unknown"
        DISTRO_LIKE=""
    fi

    if [ "$DISTRO_ID" = "nixos" ] || [ -f /etc/NIXOS ] || [[ "$DISTRO_LIKE" == *nixos* ]]; then
        IS_NIXOS=1
        local nixos_missing=0

        if ! python3 -c "import evdev" >/dev/null 2>&1; then
            nixos_missing=1
        fi
        if ! command -v jq >/dev/null 2>&1; then
            nixos_missing=1
        fi
        if ! (groups "$USER" 2>/dev/null || groups) | grep -qw input; then
            nixos_missing=1
        fi

        if [ "$nixos_missing" -eq 1 ]; then
            warn "NixOS detected with missing dependencies or permissions!"
            echo ""
            echo -e "${C_CYAN}==>${C_RESET} NixOS detected! To enable required system packages and permissions, ensure your /etc/nixos/configuration.nix includes:
     environment.systemPackages = with pkgs; [
       (python3.withPackages (ps: with ps; [ evdev ]))
       jq
     ];
     users.users.${USER}.extraGroups = [ \"input\" ];
Then run: sudo nixos-rebuild switch"
            echo ""
        else
            ok "NixOS dependencies verified (python-evdev, jq, input group)."
        fi
    elif [[ "$DISTRO_ID" == "arch" || "$DISTRO_LIKE" == *arch* ]]; then
        sudo pacman -S --needed --noconfirm python python-evdev bash jq
        ok "Packages installed (or already present)."
    elif [[ "$DISTRO_ID" == "fedora" || "$DISTRO_LIKE" == *fedora* ]]; then
        sudo dnf install -y python python-evdev bash jq
        ok "Packages installed (or already present)."
    elif [[ "$DISTRO_ID" == "ubuntu" || "$DISTRO_ID" == "debian" || "$DISTRO_LIKE" == *debian* ]]; then
        sudo apt update && sudo apt install -y python3 python3-evdev bash jq
        ok "Packages installed (or already present)."
    else
        warn "Could not automatically recognize your distro (ID=$DISTRO_ID)."
        warn "Please install manually: python3, python-evdev, bash, jq"
    fi
}

# 2. "input" group membership (required by evdev for mouse/keyboard capture)
setup_input_group() {
    log "Checking user (${USER}) membership in the 'input' group..."
    if (groups "$USER" 2>/dev/null || groups) | grep -qw input; then
        ok "User '${USER}' already belongs to the 'input' group."
    else
        if [ "${IS_NIXOS:-0}" -eq 1 ]; then
            warn "User '${USER}' does not belong to the 'input' group."
            warn "On NixOS, group membership is declarative. Ensure /etc/nixos/configuration.nix includes:"
            warn "  users.users.${USER}.extraGroups = [ \"input\" ];"
            warn "Then run: sudo nixos-rebuild switch"
        else
            log "Adding user (${USER}) to the 'input' group..."
            sudo usermod -aG input "$USER"
            warn "User added to the 'input' group. You must LOG OUT (or reboot) for this to take effect."
            NEED_RELOGIN=1
        fi
    fi
}

# 3. Download the repository and copy scripts
fetch_and_install_scripts() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    if [ -d "${SCRIPT_DIR}/scripts" ]; then
        log "Found local scripts directory at ${SCRIPT_DIR}/scripts. Installing scripts..."
        mkdir -p "${SCRIPTS_DEST}"
        find "${SCRIPT_DIR}/scripts" -maxdepth 1 -type f \( -name "*.py" -o -name "*.sh" \) -print0 |
            while IFS= read -r -d '' f; do
                cp -f "$f" "${SCRIPTS_DEST}/"
                ok "Copied: $(basename "$f")"
            done
    else
        log "Downloading the repository from ${REPO_TARBALL}..."
        if ! curl -fsSL -o "${TMP_DIR}/repo.tar.gz" "${REPO_TARBALL}"; then
            err "Could not download the repo from ${REPO_TARBALL}"
            err "Check your connection or download it manually: ${REPO_URL}"
            exit 1
        fi

        mkdir -p "${TMP_DIR}/repo"
        tar -xzf "${TMP_DIR}/repo.tar.gz" -C "${TMP_DIR}/repo" --strip-components=1

        if [ ! -d "${TMP_DIR}/repo/scripts" ]; then
            err "Could not find the 'scripts' folder inside the downloaded repo."
            exit 1
        fi

        log "Creating ${SCRIPTS_DEST} and copying files..."
        mkdir -p "${SCRIPTS_DEST}"

        find "${TMP_DIR}/repo/scripts" -maxdepth 1 -type f \( -name "*.py" -o -name "*.sh" \) -print0 |
            while IFS= read -r -d '' f; do
                cp -f "$f" "${SCRIPTS_DEST}/"
                ok "Copied: $(basename "$f")"
            done
    fi

    log "Applying execute permissions..."
    chmod +x \
        "${SCRIPTS_DEST}/canvas_zoom.py" \
        "${SCRIPTS_DEST}/infinite-desktop.sh" \
        "${SCRIPTS_DEST}/floating_tile_toggle.py" \
        "${SCRIPTS_DEST}/move_window_tiled.py" \
        "${SCRIPTS_DEST}/navigate_windows.py" \
        "${SCRIPTS_DEST}/resize_window.py" \
        "${SCRIPTS_DEST}/move_window.py" \
        "${SCRIPTS_DEST}/infinite_desktop_core.py" \
        "${SCRIPTS_DEST}/hypr_ipc.py" \
        2>/dev/null || true

    [ -f "${SCRIPTS_DEST}/discover_hyprland_api.sh" ] && chmod +x "${SCRIPTS_DEST}/discover_hyprland_api.sh"

    ok "Scripts installed in ${SCRIPTS_DEST}"
}

# 4. Patch hyprland.lua (autostart + keybinds, with conflict resolution)
patch_hyprland_config() {
    log "Updating ${HYPR_LUA} (autostart + keybinds)..."
    mkdir -p "$(dirname "${HYPR_LUA}")"

    STATUS=0
    python3 "${TMP_DIR}/patch_hyprland.py" "${HYPR_LUA}" "${SCRIPTS_DEST}" || STATUS=$?

    if [ "$STATUS" -eq 3 ]; then
        warn "hyprland.lua was not modified (already installed before)."
    elif [ "$STATUS" -ne 0 ]; then
        err "Failed to patch hyprland.lua"
        exit 1
    fi
}

write_patch_script() {
cat > "${TMP_DIR}/patch_hyprland.py" << 'PYEOF'
#!/usr/bin/env python3
import re, sys, os, datetime

HYPR_LUA = os.path.expanduser(sys.argv[1]) if len(sys.argv) > 1 else os.path.expanduser("~/.config/hypr/hyprland.lua")

MARK_START = "-- >>> hyprland-infinite-desktop-v2 (auto-installed) START"
MARK_END   = "-- <<< hyprland-infinite-desktop-v2 (auto-installed) END"

# Alternative key ladders to try on collision (in order of preference).
FALLBACK = {
    "Z": ["Z", "COMMA", "MINUS", "F13"],
    "X": ["X", "PERIOD", "EQUAL", "F14"],
    "D": ["D", "F", "G", "B"],
    "left": ["left", "H"],
    "right": ["right", "L"],
    "up": ["up", "K"],
    "down": ["down", "J"],
    "0": ["0", "KP_0", "grave"],
    "mouse_down": ["mouse_down"],
    "mouse_up": ["mouse_up"],
}

def norm_key(k):
    return k.strip().upper()

BINDS = []

def add(id_, mods, basekey, action_tpl, desc):
    BINDS.append({"id": id_, "mods": mods, "basekey": basekey, "action_tpl": action_tpl, "desc": desc})

add("ws_prev", ["MOD"], "Z", '{mod} .. " + {key}", hl.dsp.focus({{ workspace = "-1" }})', "Previous workspace")
add("ws_next", ["MOD"], "X", '{mod} .. " + {key}", hl.dsp.focus({{ workspace = "+1" }})', "Next workspace")
add("ws_prev_move", ["MOD", "SHIFT"], "Z", '{mod} .. " + SHIFT + {key}", hl.dsp.window.move({{ workspace = "-1" }})', "Move window to previous workspace")
add("ws_next_move", ["MOD", "SHIFT"], "X", '{mod} .. " + SHIFT + {key}", hl.dsp.window.move({{ workspace = "+1" }})', "Move window to next workspace")
add("toggle_floating_all", ["MOD"], "D", '{mod} .. " + {key}", hl.dsp.exec_cmd("python3 ~/scripts/floating_tile_toggle.py")', "Toggle floating/tiled (all windows)")

for d in ["left", "right", "up", "down"]:
    add(f"nav_{d}", ["MOD"], d, '{mod} .. " + {key}", hl.dsp.exec_cmd("python3 ~/scripts/navigate_windows.py ' + d + '")', f"Navigate window ({d})")
    add(f"movetiled_{d}", ["MOD", "ALT"], d, '{mod} .. " + ALT + {key}", hl.dsp.exec_cmd("python3 ~/scripts/move_window_tiled.py ' + d + '")', f"Move tiled window ({d})")
    add(f"movefloat_{d}", ["MOD", "SHIFT"], d, '{mod} .. " + SHIFT + {key}", hl.dsp.exec_cmd("python3 ~/scripts/move_window.py ' + d + '"), {{ repeating = true }}', f"Move floating window ({d})")
    add(f"resize_{d}", ["MOD", "CTRL"], d, '{mod} .. " + CTRL + {key}", hl.dsp.exec_cmd("python3 ~/scripts/resize_window.py ' + d + '"), {{ repeating = true }}', f"Resize window ({d})")

# Canvas Zoom In / Out / Reset
add("canvas_zoom_out", ["MOD", "CTRL"], "mouse_down", '{mod} .. " + CTRL + {key}", hl.dsp.exec_cmd("python3 ~/scripts/canvas_zoom.py out")', "Zoom out canvas")
add("canvas_zoom_in", ["MOD", "CTRL"], "mouse_up", '{mod} .. " + CTRL + {key}", hl.dsp.exec_cmd("python3 ~/scripts/canvas_zoom.py in")', "Zoom in canvas")
add("canvas_zoom_reset", ["MOD", "CTRL"], "0", '{mod} .. " + CTRL + {key}", hl.dsp.exec_cmd("python3 ~/scripts/canvas_zoom.py reset")', "Reset canvas zoom")

def read_file(path):
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def detect_mainmod(content):
    m = re.search(r'local\s+mainMod\s*=\s*"([A-Za-z0-9_ +]+)"', content)
    if m:
        return m.group(1).strip().upper()
    return "SUPER"

def first_call_arg(line, call_idx_end):
    depth = 0
    buf = []
    i = call_idx_end
    while i < len(line):
        c = line[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif c == "," and depth == 0:
            break
        buf.append(c)
        i += 1
    return "".join(buf)

def extract_existing_signatures(content):
    """
    Normalized signature (frozenset of mods+key) for every active
    hl.bind()/bind() call, ignoring comments.
    """
    mainmod = detect_mainmod(content)
    sigs = {}
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        m = re.search(r'\bbind\(', line)
        if not m:
            continue
        arg = first_call_arg(line, m.end())
        if "mainMod" not in arg and '"' not in arg:
            continue
        literals = re.findall(r'"([^"]*)"', arg)
        if not literals:
            continue
        joined = " ".join(literals)
        tokens = re.split(r'\+', joined)
        tokens = [norm_key(t) for t in tokens if t.strip() != ""]
        if "mainMod" in arg:
            tokens = [mainmod] + tokens
        if not tokens:
            continue
        sigs[frozenset(tokens)] = line.strip()
    return sigs, mainmod

def build_signature(mods, key, mainmod):
    resolved = [mainmod if m == "MOD" else m for m in mods]
    return frozenset([norm_key(x) for x in resolved] + [norm_key(key)])

def resolve_binds(content):
    existing_sigs, mainmod = extract_existing_signatures(content)
    chosen = {}
    used_sigs = set(existing_sigs.keys())
    remapped_report = []

    for b in BINDS:
        candidates = FALLBACK.get(b["basekey"], [b["basekey"]])
        picked = None
        picked_mods = list(b["mods"])
        for cand in candidates:
            sig = build_signature(b["mods"], cand, mainmod)
            if sig not in used_sigs:
                picked = cand
                used_sigs.add(sig)
                break
        if picked is None:
            # Special keys like mouse wheel should not have arbitrary modifier shifts
            if b["basekey"] not in ["mouse_down", "mouse_up"]:
                for extra in ["ALT", "SHIFT", "CTRL"]:
                    if extra in b["mods"]:
                        continue
                    cand = candidates[0]
                    sig = build_signature(b["mods"] + [extra], cand, mainmod)
                    if sig not in used_sigs:
                        picked = cand
                        picked_mods = b["mods"] + [extra]
                        used_sigs.add(sig)
                        break
        if picked is None:
            picked = candidates[0]
        if norm_key(picked) != norm_key(b["basekey"]) or picked_mods != b["mods"]:
            remapped_report.append((b["id"], b["basekey"], picked))
        chosen[b["id"]] = (picked_mods, picked)

    return chosen, mainmod, remapped_report

def render_lines(chosen, mainmod, use_mainmod_var=True):
    lines = []
    final_desc = []
    mod_literal = "mainMod" if use_mainmod_var else f'"{mainmod}"'
    for b in BINDS:
        mods, key = chosen[b["id"]]
        line = "hl.bind(" + b["action_tpl"].format(mod=mod_literal, key=key) + ")"
        lines.append(line)
        combo_parts = [mainmod if m == "MOD" else m for m in mods]
        combo_parts.append(norm_key(key))
        final_desc.append((" + ".join(combo_parts), b["desc"]))
    return lines, final_desc

def main():
    content = read_file(HYPR_LUA)
    os.makedirs(os.path.dirname(HYPR_LUA), exist_ok=True)

    if MARK_START in content or "-- >>> hyprland-infinite-desktop-v2 START" in content:
        print("WARNING: a block installed previously by this script already exists in hyprland.lua.")
        print("The file was not modified. Remove the block manually if you want to reinstall.")
        sys.exit(3)

    backup = HYPR_LUA + ".bak." + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    if content:
        with open(backup, "w", encoding="utf-8") as f:
            f.write(content)

    has_mainmod_var = bool(re.search(r'\blocal\s+mainMod\s*=', content))
    chosen, mainmod, remapped = resolve_binds(content)
    bind_lines, final_desc = render_lines(chosen, mainmod, use_mainmod_var=has_mainmod_var)

    autostart_block = (
        '    hl.on("hyprland.start", function()\n'
        '        hl.exec_cmd("python3 ~/scripts/infinite_desktop_core.py 1.6 > /tmp/infinite-desktop.log 2>&1")\n'
        '    end)'
    )

    block = []
    block.append("")
    block.append(MARK_START)
    block.append(f'-- mainMod detected/used: "{mainmod}"')
    block.append(autostart_block)
    block.append("")
    block.append("-- Infinite desktop keybinds")
    block.extend(bind_lines)
    block.append(MARK_END)
    block.append("")

    new_content = content.rstrip("\n") + "\n" + "\n".join(block) + "\n"
    with open(HYPR_LUA, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"OK: hyprland.lua updated (backup at {backup})")
    print(f"mainMod detected: {mainmod}")
    print("")
    if remapped:
        print("The following keys were remapped due to conflicts with existing binds:")
        for id_, orig, new in remapped:
            print(f"  - {id_}: {orig} -> {new}")
        print("")
    print("=== New binds added by hyprland-infinite-desktop-v2 ===")
    for combo, desc in final_desc:
        print(f"  {combo:<28} -> {desc}")

if __name__ == "__main__":
    main()
PYEOF
}

# Main Execution Flow

NEED_RELOGIN=0

echo -e "${C_BOLD}Infinite Canvas Hyprland Installer${C_RESET}"
echo "Repo: ${REPO_URL}"
echo ""

install_packages
setup_input_group
fetch_and_install_scripts
write_patch_script
patch_hyprland_config

echo ""
ok "Installation complete."
echo ""
echo "Remember:"
echo "  - Reload Hyprland (hyprctl reload) or restart your session to apply the binds."
if [ "${NEED_RELOGIN:-0}" -eq 1 ]; then
    warn "  - You must log out / reboot for the 'input' group membership to take effect (required by python-evdev)."
fi
