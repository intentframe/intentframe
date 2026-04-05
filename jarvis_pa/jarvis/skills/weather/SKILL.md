---
name: weather
description: Weather information via wttr.in
version: "1.0"
metadata:
  requires:
    bins: ["curl"]
  always: true
---

# Weather

Use `curl wttr.in` to get weather information.

## Usage

- Current weather: `curl -s "wttr.in/?format=3"`
- Detailed forecast: `curl -s "wttr.in/<city>"`
- Compact: `curl -s "wttr.in/<city>?format=%C+%t+%w"`

Always use `run_command` to execute curl commands.
