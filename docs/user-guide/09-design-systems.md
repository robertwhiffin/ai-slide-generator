# Design Systems

This guide covers what a design system is, how to upload one, how defaults work, and how to pin a template so your deck follows it closely.

## Overview

A **design system** is a brand bundle you upload once: colour and type tokens, webfonts, brand imagery, and named slide templates. Decks generated with it pick up your brand without you describing it in the prompt.

A design system is a superset of a slide style:

| | Slide style | Design system |
|---|---|---|
| Typography and colour | Yes | Yes |
| Uploaded webfont files | No | Yes |
| Brand images and logos | No | Yes |
| Named slide templates | No | Yes |
| How you create it | Written in the app | Uploaded as a bundle |

**You cannot use both at once.** If a deck has a design system, that wins and the slide style is ignored.

Design systems are **shared across your workspace**. Anyone can upload one, and anyone can use any of them. You can edit or delete the ones you uploaded; an admin can edit or delete any of them. One exception: while a design system is set as the organisation default, only an admin can change it — even its author cannot.

## Uploading a bundle

Go to **Design Systems** in the navigation, then **Upload design system**.

Bundles are usually produced by a brand or design team rather than assembled by hand. Whoever builds yours needs to know four things, because entries outside these rules are skipped silently:

- Brand images and logos go in **`assets/`**. Anything in a differently-named folder — `brand/`, `images/`, `logo/` — **is not imported**, and you get no error.
- Webfonts go in **`fonts/`**.
- Each template folder should include a preview image — either **`.thumbnail`** (no file extension) or **`preview.png`** / `.jpg` / `.gif` / `.webp`. Without one, the app falls back to rendering a live preview from the template itself, so you lose the stored image rather than the feature.
- The bundle needs a **`_ds_manifest.json`** at its root. It declares the tokens and templates; without it the importer cannot find the bundle root.
- Every text size you want used should be declared as a **token**, not only inside template CSS.

The full contract is in [Design System Bundle Format](../technical/design-system-bundle-format.md) if you need to hand it to whoever builds the bundle.

After upload, the library shows the token, asset and template counts. Check them: if the asset count is much lower than you expect, the bundle almost certainly used a folder name other than `assets/`. The upload response also lists entries the importer ignored and why — that list is the fastest way to spot a mis-shaped bundle.

## Choosing which design system a deck uses

There are three levels, and they apply in this order.

**1. This deck only.** Pick a design system in the agent config bar. This overrides everything below and affects only the current deck.

**2. Your personal default.** Click **Set as default** on a design system in the library. Every new deck of yours uses it. This is remembered **in your current browser only** — it does not follow you to another laptop, and it does not apply to decks created through the MCP API.

Click **Clear default** to stop using it. Your slide-style default, or the organisation default, then applies again.

**3. The organisation default.** One design system can be marked as the org default, and it applies to everyone who hasn't set a personal one — including decks created through the MCP API. **Only a tellr admin can set this**, from the `/admin` page under the "Design System" tab.

> If you want a personal default that follows you between browsers and machines, use a **profile** instead: choose the design system, save the configuration as a profile, then set that profile as your default. Profiles are stored server-side.

## Pinning a template

A design system's templates appear in the detail panel with preview images. Selecting a template for your deck is done from the **agent config bar**, not from the library.

**Pinning a template matters more than it sounds.** With a template pinned, the deck reuses that template's actual styling. Without one, the model is only given a short list of template names and descriptions — no styling — so it picks a sensible template and then invents its own layout. The result is still on-brand in colour and typeface, but it will not match the template.

If brand fidelity matters, pin a template.

**One limitation:** pinning only sticks on a deck that already exists. If you pick a template before sending your first message, the choice is dropped. Send your first message, then pin the template and continue.

## Deleting a design system

Deleting hides a design system from the library and stops it being used for new decks.

**The underlying files are retained, but existing decks may still lose their brand.** Reopening a deck whose design system was deleted clears that deck's link to it, after which its brand fonts fall back and its brand images stop appearing — text, layout and colours remain. Exports made before that point are unaffected. If you need a deck to keep its brand, avoid deleting the design system it uses. The name is freed, so you can upload a replacement under the same name.

## Troubleshooting

| What you see | Likely cause |
|---|---|
| Upload succeeded but the asset count is near zero | Brand files are in a folder other than `assets/` or `fonts/`. Those entries are skipped without an error. |
| Templates show no stored preview | The template folder has neither a `.thumbnail` (extension-less) nor a `preview.<ext>` file, or the file was not a recognised image format. The app can still render a live preview from the template. |
| Headings come out smaller than the template's | A text size is set in template CSS but not declared as a token. Derived sizes read the tokens. |
| Deck ignores the design system entirely | A slide style is set on that deck. Setting a slide style stops the organisation's design system being applied automatically — clear the style in the agent config bar. (If a design system **is** explicitly chosen, it wins and the style is dropped.) |
| The org default doesn't seem to apply to you | You have a personal default set in this browser. Use **Clear default** on the design system library page. |
| Upload rejected with a message about the file paths | The zip contains an entry whose path is ambiguous or unsafe. Re-export the bundle from its source tool rather than repacking it by hand. |
| A deck made via MCP ignored your personal default | Personal defaults live in your browser and cannot be seen by the API. MCP decks use the org default, or an explicit design system passed in the call. |

## Related guides

- [Advanced Configuration](./03-advanced-configuration.md) — deck prompts and slide styles
- [Creating Custom Styles](./05-creating-custom-styles.md) — slide styles, and how defaults resolve
- [Design System Bundle Format](../technical/design-system-bundle-format.md) — the bundle contract, for whoever builds yours
