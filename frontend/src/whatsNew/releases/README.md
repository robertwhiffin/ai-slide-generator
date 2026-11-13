# Release notes

One file per final release, named `<version>.json` (for example `0.5.7.json`). Dev builds
(`0.5.7.dev1`) have no notes.

```json
{
  "version": "0.5.7",
  "date": "2026-11-14",
  "items": [
    { "title": "Images in chat", "body": "Ask for an image of a monkey at a keyboard." }
  ]
}
```

- `version` must equal the file name. `date` is a real `YYYY-MM-DD` date.
- Titles have no trailing period. The popup renders each bullet as `**{title}.** {body}`.
- `"items": []` is valid and means the release has nothing user-facing.
- Files are written only by the `release-tellr` skill, after the owner approves the wording.
  Do not add or edit them by hand.
