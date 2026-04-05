---
name: docker
description: Docker CLI – containers, images, compose
version: "1.0"
metadata:
  requires:
    bins: ["docker"]
---

# Docker

Use the `docker` CLI to manage containers and images.

## Common operations

- `docker ps`, `docker ps -a`
- `docker images`, `docker pull <image>`
- `docker run`, `docker stop`, `docker rm`
- `docker compose up`, `docker compose down`
- `docker logs <container>`

Always use `run_command` to execute docker commands.
