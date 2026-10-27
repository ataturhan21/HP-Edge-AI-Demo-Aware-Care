# Requirements and permissions

What a machine and the person running the demo need, in one place; the README's "You need" line links here. `./demo.sh setup` (and `./demo.sh doctor`) checks each item and prints the fix.

## Who does what

| Admin, once, with sudo | The user, no sudo |
|---|---|
| Install Docker Engine and buildx (the `docker-buildx-plugin` package, or the standalone `docker-buildx` program) | Clone the repository (read access, below), then `./demo.sh setup` |
| Add the user to the `docker` group: `sudo usermod -aG docker <user>` (the user logs out and back in) | The model: download and serve it through ZRT, with a systemd **user** unit (`setup`, or `model`) |
| Behind a proxy (ask your IT for the proxy): the Docker daemon's proxy (`/etc/systemd/system/docker.service.d/http-proxy.conf`; `demo.sh` prints it) | The app: build the images, run the two containers, keep the data in `~/.local/share/aware-care-demo` (`setup`, or `local`) |
| Install ZRT (preinstalled on ZGX) and a CUDA toolkit with `nvcc` (CUDA 13 on ZGX; for serving the model); in ZRT's system mode, add the user to the `zrt` group | The shell's proxy (`HTTPS_PROXY` in `~/.bashrc`); uv and Node 24 for `./demo.sh setup --mock` |
| Optional: `sudo loginctl enable-linger <user>`, so the model keeps running after the user logs out | `status`, `stop`, `update`, `uninstall [--all]` (README: "Remove it") |

**Does the user need root or sudo?** No. `demo.sh` never uses sudo and refuses to run as root.
A conda or virtualenv shell may put its own `docker` first on PATH; `doctor` names the Docker CLI it finds and says
when one hides the system's (fix: `conda deactivate`). buildx is found as the plugin, the standalone program or the
plugin binary in `~/.docker/cli-plugins` or `/usr/{local/lib,libexec,lib}/docker/cli-plugins`.

**Does the user need "sudo docker"?** No, and it is not enough: Docker must work **without** sudo, through the `docker`
group. `demo.sh` runs `docker` as the user and stops when that is denied, because the containers, images, data, model
unit and checkout belong to that user (run as root, they would land in root's home and the user could not manage them).

> [!WARNING]
> The `docker` group is root-equivalent on that machine: its members can start a container that mounts the host's
> files as root. Add only people you would give sudo to.

## Credentials

- **None to clone:** the repository is public, so `git clone` and `./demo.sh update` need no GitHub sign-in, only a
  network (or proxy) that reaches GitHub.
- No registry login (the images are built on the machine; GHCR is not needed), no cloud keys, no Hugging Face token
  (the Qwen models are public). The presenter key is generated on the machine (`~/.local/share/aware-care-demo/secrets/`).

## ZRT: system or user mode

`zrt` has `-m/--mode user|system`; the default is `system` (a shared service, files in `/opt/hp/zrt`, owned by the
`zrt` group: if `zrt services` says permission denied, an admin adds the user to that group); `user` keeps its files
in the user's home and needs no sudo (`zrt -m user setup`). The app needs only two things: the `zrt` command on the
user's PATH, and a ZRT proxy or service that answers on loopback. `demo.sh` passes `-m <mode>` to every `zrt` call:
`--zrt-mode user|system`, else `AWARECARE_ZRT_MODE`, else what `zrt config get mode` says, else `system`. ZRT's
address: `--zrt-url`, else `--zrt-port <n>`, else `AWARECARE_ZRT_URL`, else the proxy port `zrt config get proxy.port`
names (any loopback port), else 8080; the deploy, the API and the model unit's serve script follow the same port.
These are the two ways ZRT runs, not two kinds of app user: the app always runs as one ordinary user.

## Ports and network

All on loopback (`127.0.0.1`); reach them through the SSH tunnel `demo.sh` prints.

| Port | What |
|---|---|
| 8180 | the app (web); `--web-port` moves it |
| 8100 | the API; `--api-port` moves it |
| 8080 | ZRT's proxy: the port `zrt config get proxy.port` names, 8080 by default (`--zrt-port` or `--zrt-url` for another) |
| 5173, 8000 | `mock` mode's development servers (`--port` moves 5173) |

The build and the model download need the internet: directly, or through a proxy (ask your IT for the proxy), set for the shell
**and** the Docker daemon. Nothing else leaves the machine: the model runs on it.
