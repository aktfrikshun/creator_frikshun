# Repository Guidance

## Runtime reload

Creator OS runs as a persistent Flask launchd service without the development reloader. After changing application Python, templates, or other runtime-loaded UI code, restart it with:

```bash
launchctl kickstart -k gui/$(id -u)/com.frikshun.creator
```

Verify the updated behavior against the restarted service before treating the change as complete.

## Fan engagement

Ordinary daily posts must not receive a compulsory promotional footer. Follow `docs/fan-engagement-cadence.md` for conversational engagement and dedicated participation messages.
