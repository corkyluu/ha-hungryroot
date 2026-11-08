# Hungryroot for Home Assistant

Unofficial, **read-only** Home Assistant integration for [Hungryroot](https://www.hungryroot.com).
It shows your next delivery, the edit cut-off, what's in the box, this week's recipes and recent spend.
It never changes, skips or places an order.

> Hungryroot has no public API. This uses the same private API their website uses, so it can break
> whenever they change their site. Not affiliated with or endorsed by Hungryroot.

## Install (Home Assistant Marketplace)

1. Settings → **Marketplace** → **Add from link** → `corkyluu/ha-hungryroot`, type **Integration**.
   (Adding a link needs the Marketplace connected to a GitHub account.)
2. Open **Hungryroot** → **Install**. The setup screen opens.

## Logging in

- **Email and password**: tried first. Your password is not stored, only the session Hungryroot returns.
- **Paste a session**: Hungryroot's login uses a captcha. If it blocks Home Assistant, the setup
  screen switches to pasting the session cookie from your browser, with step-by-step instructions.

When the session expires, Home Assistant shows **Re-authenticate** on the integration card. Click it
and log in again from the same screens.

## What you get

| Entity | What it shows |
|---|---|
| Next delivery | Date of the next box (status and order id in attributes) |
| Edit cut-off | Deadline to change the next box |
| Box editable | On until the cut-off passes |
| Box items | Number of items; the list is in the `items` attribute |
| Recipes this week | Number of recipes; names in the `recipes` attribute |
| Next box total | Price of the next box |
| Spend (last 10 orders) | Sum of recent orders; each order in the `orders` attribute |
| Last delivery | Date of the most recent box |

Settings (⋮ → **Configure**): how often to check, 1–24 hours (default 6).

## When it breaks

If Hungryroot changes their site, a **Repairs** card appears in Settings explaining it. Install the
update from Settings → Updates (or the Hungryroot page in Settings → Marketplace). If no update
exists yet, use **Download diagnostics** on the integration (personal details are removed) and use
it to fix the parser in `coordinator.py`.
