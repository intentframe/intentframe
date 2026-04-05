---
name: system-control
description: macOS system controls – brightness, volume, dark mode, system info
version: "1.0"
metadata:
  os: ["darwin"]
---

# System Control

Control macOS display, audio, and appearance settings.

## Available Tools

- `get_system_info` — Get OS version, hostname, architecture, and Python version. Safe read, no side effects.
- `set_volume` — Set system audio output volume. Level is an integer **0–100** (e.g. 50 for 50%).
- `get_volume` — Get the current system volume level (0–100). Safe read, no side effects.
- `toggle_mute` — Toggle system audio mute on/off.
- `get_mute` — Check whether system audio is currently muted. Safe read, no side effects.
- `set_brightness` — Set display brightness. Level is a float **0.0–1.0** (e.g. 0.75 for 75%).
- `get_brightness` — Get the current display brightness level (0.0–1.0). Safe read, no side effects.
- `toggle_dark_mode` — Toggle between macOS dark and light appearance. No parameters needed.
- `get_dark_mode` — Check whether dark mode is currently enabled. Safe read, no side effects.

## Important

- Always use the dedicated tools above for system controls.
- When the user asks "what is my brightness/volume?", use `get_brightness`/`get_volume` — do not guess or say you can't.
- For "increase/decrease brightness" without a specific value, call `get_brightness` first, then adjust by ±0.2.
- For "increase/decrease volume" without a specific value, call `get_volume` first, then adjust by ±20.
- Brightness 0.0 does not turn off the display — it sets minimum backlight. Use 0.1 as a practical minimum.
- **Before toggling dark mode or mute**, always check the current state first (`get_dark_mode`/`get_mute`). If the state already matches what the user wants, do nothing. Only toggle when the current state differs from the request.
