# claude-usage-docker

A small container that reports your Claude subscription plan usage over HTTP, so
Home Assistant, a dashboard, or anything else can read it:

```json
{"current": 47, "current_resets_at": "2026-09-12T13:30:00+02:00",
 "weekly": 56, "weekly_resets_at": "2026-09-15T00:00:00+02:00",
 "fetched_at": "2026-09-12T10:21:35+02:00"}
```

`current` is the current session (the five hour window), `weekly` is the week.
Both are percent used, the same numbers you see on claude.ai/settings/usage.

Handing this repository to a coding agent to set up? Point it at
[For a coding agent](#for-a-coding-agent) below.

## How it works

The container runs Claude Code and asks it `claude -p /usage`. That is a local
command: it costs no tokens and does not count against your limits.
`claude_usage.py` pulls the two percentages and the reset times out of the text.

Nothing runs in the background. A measurement happens only when a request comes
in and the previous one is older than `CACHE_SECONDS` (60 by default). A
dashboard polling every five minutes produces 288 measurements a day, all free.

A measurement takes about two seconds, so the first request after the cache
expires is the slow one.

## Requirements

- Docker with Compose
- A Claude subscription (Pro, Max, Team or Enterprise). An API key will not do:
  this reads subscription usage, and the code explicitly drops
  `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` from the environment so a key
  lying around cannot quietly start spending credits.

## For a coding agent

You have been given this repository to set up. Work in this order, on the machine
that will host the service.

1. `docker compose build`.
2. Ask the user for their timezone and put it in `compose.yml` as `TZ`. Do not
   leave it on `Europe/Amsterdam`; the reset times are rendered in it.
3. Ask where the service must be reachable from. `compose.yml` publishes on
   `127.0.0.1:8130`, which is right when the consumer runs on the same machine.
   For another machine on the LAN, put that host's own LAN address in front:
   `"192.168.1.10:8130:8130"`. Never publish it to the internet: the port
   answers without authentication.
4. **Stop here and hand back to the user.** Signing in is interactive and you
   cannot finish it alone: Claude Code prints an Anthropic URL, a person signs in
   with their subscription in a browser, and only they can read back the code.
   Either let them run `docker compose run --rm claude-usage claude` themselves,
   or drive it with the tmux recipe below and ask them for just the code. Without
   a terminal, `docker compose run` fails with "the input device is not a TTY".
5. Verify the login took, before starting anything:

   ```bash
   docker compose run --rm claude-usage python3 -c \
     "import claude_usage, json; print(json.dumps(claude_usage.fetch(), indent=2))"
   ```

6. `docker compose up -d`, then `curl -s http://127.0.0.1:8130/` (or the address
   you bound in step 3). Report the JSON back to the user so they can see it
   works.
7. If they want it in Home Assistant, add the REST sensor below, with the
   address from step 3.

What will otherwise cost you a cycle or two:

- A `503` whose body says "no subscription data in the output of /usage" means
  step 4 never completed. It is not a bug; nobody has signed in yet.
- Claude Code wraps the sign-in URL at the terminal width, and
  `tmux capture-pane -J` does not join it back. Join the lines between
  `https://` and "Paste code here" yourself, with nothing in between.
- On the trust question, **No, exit** is preselected. Send a Down before Enter,
  or the session closes and you start over.
- The first request after the cache expires takes about two seconds. That is the
  measurement running, not a hang.
- Do not run the tests as proof that the service works: they only exercise the
  parser against stored samples and pass fine without a login.

## Setup

```bash
git clone https://github.com/bglnelissen/claude-usage-docker.git
cd claude-usage-docker
docker compose build
```

Set `TZ` in `compose.yml` to your own timezone first, or the reset times come
back on Amsterdam clock time. Then sign in once (see below), and start it:

```bash
docker compose up -d
curl -s http://127.0.0.1:8130/
```

## Signing in

**This step needs a person at a browser.** It is the one part that cannot be
automated away: Claude Code opens an Anthropic sign-in page and you paste back
the code it gives you. Everything after this is unattended, and the login lives
in the `data` volume, so it survives restarts and rebuilds and you do it once.

If you are running these commands through something without a terminal, plain
`docker compose run` fails with "the input device is not a TTY". Use the tmux
recipe further down, and have a human ready to supply the code.

```bash
docker compose run --rm claude-usage claude
```

Press Enter for the theme, choose **Claude account with subscription**, open the
URL it prints, approve, and paste the code back. Then confirm the welcome
screens, and at "Is this a project you created or one you trust?" choose
**Yes, I trust this folder**. Leave with `/exit`.

Check that it took:

```bash
docker compose run --rm claude-usage python3 -c \
  "import claude_usage, json; print(json.dumps(claude_usage.fetch(), indent=2))"
```

### Two things that will cost you time

**The URL is wrapped.** Claude Code breaks the sign-in URL at the terminal
width. If you are copying it out of a script rather than clicking it, join the
lines between `https://` and "Paste code here" with nothing in between. Note
that `tmux capture-pane -J` does not join them for you.

**"No, exit" is preselected** on the trust question. Pressing Enter straight
away closes the session and you start over. Move down first.

### Signing in from a script

If you drive this from automation rather than a terminal, a detached tmux
session works:

```bash
tmux new-session -d -s claude-login -x 250 -y 60 \
  "docker compose run --rm claude-usage claude"
tmux send-keys -t claude-login Enter          # theme
tmux send-keys -t claude-login Enter          # subscription account
tmux capture-pane -p -J -t claude-login       # read the URL (see above)
tmux send-keys -t claude-login -l "<code>"
tmux send-keys -t claude-login Enter
tmux send-keys -t claude-login Enter          # login confirmation
tmux send-keys -t claude-login Enter          # security notes
tmux send-keys -t claude-login Down           # move off "No, exit"
tmux send-keys -t claude-login Enter          # trust /app
tmux send-keys -t claude-login -l "/exit"
tmux send-keys -t claude-login Enter
```

Afterwards check that no `run` container is left behind:
`docker ps -a --filter name=claude-usage`.

## Endpoints

| Path | Answer |
| --- | --- |
| `GET /` (or `/usage`) | the JSON above, `200` |
| `GET /health` | `{"ok": true, "last_fetched_at": ..., "last_error": ...}` |
| anything else | `404` |

When a measurement fails, the previous one keeps being served for up to
`STALE_MAX_SECONDS` with `"stale": true` and an `error` field alongside it.
After that it becomes a `503`. Serving a known-old number beats serving a wrong
one, and beats going dark the moment a single call hiccups.

## Configuration

Environment variables, set in `compose.yml`:

| Variable | Default | What it does |
| --- | --- | --- |
| `PORT` | `8130` | port inside the container |
| `CACHE_SECONDS` | `60` | how long a measurement is reused |
| `STALE_MAX_SECONDS` | `3600` | how long a failed measurement falls back to the previous one |
| `TZ` | `Europe/Amsterdam` | the timezone the reset times are rendered in; change it to yours |
| `CLAUDE_BIN` | unset | path to `claude`, if it is not on `PATH` |

Build argument:

| Argument | Default | What it does |
| --- | --- | --- |
| `CLAUDE_VERSION` | `2.1.268` | which Claude Code version gets installed |

## Home Assistant

```yaml
sensor:
  - platform: rest
    resource: http://127.0.0.1:8130/
    name: Claude usage
    value_template: "{{ value_json.current }}"
    json_attributes: [weekly, current_resets_at, weekly_resets_at, fetched_at]
    scan_interval: 300
```

Use the address the container is actually published on. Out of the box that is
loopback only, so Home Assistant on another machine needs `compose.yml` changed
to your LAN address first.

## Why the Claude Code version is pinned

`/usage` is plain text meant for humans, not an API, so an update can reword it.
2.1.267 writes `resets Sep 15, 12am` where 2.1.268 writes `resets Sep 15 at
12am`, and the parser handles both. To move to a newer version: raise
`CLAUDE_VERSION`, rebuild, and run the tests. If they fail, add the new output
as a sample in `test_claude_usage.py` and widen the pattern.

## Tests

```bash
docker compose run --rm claude-usage python3 -m unittest -v
```

Six tests, all against real `/usage` output: both reset formats, the year
rollover around new year, a line with only a time, a weekly line for a single
model that must be ignored, and the not-signed-in case.

## A note on exposure

The published port answers without any authentication, and the `data` volume
holds your Claude login. Keep both on your own network. `compose.yml` binds to
loopback for that reason, and it is on you to widen it no further than you need.

## License

MIT. See [LICENSE](LICENSE).

## Related

[claude-usage](https://github.com/bglnelissen/claude-usage) is the same
measurement as a single bash script, without the container and without the reset
times. Use that one if all you want is two numbers on the machine you are
already on.
