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

Bundles are usually produced by a brand or design team rather than assembled by hand. Whoever builds yours needs to know five things, because entries outside these rules are skipped silently:

- Brand images and logos go in **`assets/`**. Anything in a differently-named folder — `brand/`, `images/`, `logo/` — **is not imported**, and you get no error.
- Webfonts go in **`fonts/`**.
- Each template folder should include a preview image — either **`.thumbnail`** (no file extension) or **`preview.png`** / `.jpg` / `.gif` / `.webp`. Without one, the app falls back to rendering a live preview from the template itself, so you lose the stored image rather than the feature.
- The bundle needs a **`_ds_manifest.json`** at its root. It declares the tokens and templates; without it the importer cannot find the bundle root.
- Every text size you want used should be declared as a **token**, not only inside template CSS.

The full contract is in [Design System Bundle Format](../technical/design-system-bundle-format.md) if you need to hand it to whoever builds the bundle.

After upload, the library shows the token, asset and template counts. Check them: if the asset count is much lower than you expect, the bundle almost certainly used a folder name other than `assets/`. The upload response also lists entries the importer ignored and why — that list is the fastest way to spot a mis-shaped bundle.

## Choosing which design system a deck uses

This is not a single ranking of settings. What a deck gets depends on **how the deck was started**, so find your case below.

### The deck in front of you

Pick a design system in the agent config bar. That choice is saved on the deck, and no default is applied over it afterwards — not the organisation default, and not an admin changing the org default later. Picking **None** is a choice too, and it is preserved the same way.

The **Set as default** and **Clear default** buttons in the library are the exception, because they are you making another choice: each one moves the slot on the surface you are on as well as recording the preference.

### A brand-new deck, started in this browser

The app fills the empty slot once, in this order, and **stops at the first one that applies**:

1. **Your personal design-system default** — **Set as default** in the library. Remembered **in this browser only**.
2. **Your personal slide-style default** — if you have one, you have no personal design-system default, *and* the deck's starting point already carries some slide style. That last condition is easy to miss: the preference replaces a style, it does not introduce one, so a starting point holding no style at all skips this step. When it does apply, this is the case that surprises people: a personal *style* default takes the slot and **the organisation's design system is then not applied at all**.
3. **The organisation default design system**, if an admin has set one.
4. **The workspace's default slide style**, if there is no org design system.

**If this browser already holds a configuration you have used before, the choices you made yourself are kept.** A design system or slide style you picked — including **None** — is not replaced by any default. What can still change is a slot the app filled in for you and you never touched: if that is how the current style got there and you have not chosen a design system yourself, an organisation design system set later takes the slot the next time the app loads. So a new org default does reach a browser whose style was only ever filled in automatically, and leaves alone a browser where you made the choice.

### Clearing a personal default

Click **Clear default** to stop using it. That does two things: it forgets the preference, and it hands the slot back on the surface you are on — the design system **and any pinned template** are cleared, and your personal slide-style default takes the slot if you have one.

**It does not immediately put the organisation default in place.** That surface now counts as configured by you. The org default applies to decks started later on a surface where the app is still filling in defaults.

### A deck started from a profile

A **profile** you built yourself is treated as an explicit choice: whatever it contains is used, and no default is layered over it. The default profile that ships with tellr is treated as a starting point instead, so defaults may still fill its empty slots.

> A profile is also the only personal default that **follows you between browsers and machines** — the two "Set as default" preferences live in this browser only. Choose the design system, save the configuration as a profile, then set that profile as your default.

### A deck created through the MCP API

MCP cannot see anything stored in your browser. It resolves, stopping at the first that applies:

1. A **design system passed explicitly** in the call.
2. A **slide style passed explicitly** — which also stops the organisation's design system being applied.
3. The **organisation default design system**.
4. The **workspace's default slide style**.

### The organisation default

One design system can be marked as the org default. **Only a tellr admin can set this**, from the `/admin` page under the "Design System" tab.

## Pinning a template

A design system's templates appear in the detail panel with preview images. Selecting a template for your deck is done from the **agent config bar**, not from the library.

**Pinning a template matters more than it sounds.** With a template pinned, the deck receives that template's own layout HTML and CSS. Without a pin, the model receives only a short list of template names and descriptions — **no layout CSS at all** — so which template it works from, and how closely the result resembles it, are down to the model rather than to anything the app supplies. Stronger prompt wording cannot recover styling that was never sent.

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
| The org default doesn't seem to apply to you | You have a personal design-system or slide-style default set in this browser, or this browser already holds a configuration you have used before. Use **Clear default** on the design system library page, and see "A brand-new deck, started in this browser". |
| Upload rejected with a message about the file paths | The zip contains an entry whose path is ambiguous or unsafe. Re-export the bundle from its source tool rather than repacking it by hand. |
| A deck made via MCP ignored your personal default | Personal defaults live in your browser and cannot be seen by the API. MCP uses a design system or slide style passed explicitly in the call; failing that the org default design system, then the workspace's default slide style. |

## Related guides

- [Advanced Configuration](./03-advanced-configuration.md) — deck prompts and slide styles
- [Creating Custom Styles](./05-creating-custom-styles.md) — slide styles, and how defaults resolve
- [Design System Bundle Format](../technical/design-system-bundle-format.md) — the bundle contract, for whoever builds yours
