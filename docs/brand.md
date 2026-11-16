# Brand: palette and type for the Ledger UI

**Colors and type only.** The app's own name is "Roseton Ledger"; no other name, wordmark or logo appears anywhere in it.

This file replaces the "Design direction" paragraph in CLAUDE.md §7. Everything else in §7 (screens, scrubber, arrows carrying values, accessibility) stands.

---

## 1. Tokens (copy verbatim into `ui/styles/tokens.css`)

Light is the default; dark applies under `prefers-color-scheme: dark` unless `data-theme="light"`, and under `data-theme="dark"`. Dark is the primary working theme for the control-room screens; light must be equally finished.

```css
:root {
  /* surfaces */
  --surface-app:     #f6faff;  --surface-panel:   #ffffff;  --surface-raised: #eff5fc;
  --line:            #dce4ef;  --line-soft:       #e9eff7;  --line-strong:    #7a8ca6;
  /* text */
  --text-primary:    #0f1b2d;  --text-muted:      #515864;  --text-faint:     #5f6c7e;  --text-on-brand: #ffffff;
  /* brand & action */
  --brand-primary:   #174a93;  --brand-green:     #69df8e;  --navy-700: #0f3a7e;  --navy-900: #062a64;
  --action-primary:  #174a93;  --action-primary-hover: #69df8e;
  --accent:          #174a93;  --accent-soft:     #174a9314;
  /* semantic (status), never used for branding */
  --success: #1f7a45; --success-soft: #1f7a4514;
  --warning: #9a6200; --warning-soft: #d9900014;
  --danger:  #b03428; --danger-soft:  #c0392b14;
  --info:    #1a6b8a; --info-soft:    #1a6b8a14;
  --neutral: #6b7788;
  /* charts */
  --viz-1: #174a93; --viz-2: #69df8e; --viz-3: #fe9200; --viz-4: #521b92; --viz-5: #f37053; --viz-6: #0f3a7e;
  --viz-grid: #e9eff7;  --gold: #9c7a2d;
  /* ledger roles (see §2) */
  --money:      #9a6200;   /* amber family, text-safe on light */
  --money-soft: #fe920022;
  --physical:   #174a93;   /* MW, MMBtu, bbl */
  --physical-soft: #174a9314;
  /* type */
  --font-display: "brandon-grotesque", "Josefin Sans", "Poppins", sans-serif;
  --font-ui:      "Inter", system-ui, -apple-system, sans-serif;
  --font-mono:    "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace;
  /* spacing 4px scale, radii, shadow */
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px; --space-5: 24px; --space-6: 32px;
  --radius-control: 6px; --radius-md: 8px; --radius-lg: 12px; --radius-pill: 360px;
  --shadow-popover: 0 8px 24px 0 #06183a40;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { color-scheme: dark;
  --surface-app: #0a1730; --surface-panel: #10203f; --surface-raised: #16294d;
  --line: #24365a; --line-soft: #1b2b4b; --line-strong: #5b76a3;
  --text-primary: #eaf1fb; --text-muted: #9fb3d1; --text-faint: #7a92b8; --text-on-brand: #062a64;
  --action-primary: #69df8e; --action-primary-hover: #98c3eb; --accent: #69df8e; --accent-soft: #69df8e1f;
  --success: #5fd48a; --success-soft: #5fd48a1f; --warning: #f2b441; --warning-soft: #f2b4411f;
  --danger: #ff8a7a; --danger-soft: #c0392b24; --info: #5fb8dd; --info-soft: #5fb8dd1f; --neutral: #8a9bb5;
  --viz-1: #98c3eb; --viz-4: #b48ce8; --viz-6: #5fb8dd; --viz-grid: #1b2b4b; --gold: #e3b457;
  --money: #f2b441; --money-soft: #fe920029; --physical: #98c3eb; --physical-soft: #98c3eb1f;
} }
:root[data-theme="dark"] { color-scheme: dark;
  --surface-app: #0a1730; --surface-panel: #10203f; --surface-raised: #16294d;
  --line: #24365a; --line-soft: #1b2b4b; --line-strong: #5b76a3;
  --text-primary: #eaf1fb; --text-muted: #9fb3d1; --text-faint: #7a92b8; --text-on-brand: #062a64;
  --action-primary: #69df8e; --action-primary-hover: #98c3eb; --accent: #69df8e; --accent-soft: #69df8e1f;
  --success: #5fd48a; --success-soft: #5fd48a1f; --warning: #f2b441; --warning-soft: #f2b4411f;
  --danger: #ff8a7a; --danger-soft: #c0392b24; --info: #5fb8dd; --info-soft: #5fb8dd1f; --neutral: #8a9bb5;
  --viz-1: #98c3eb; --viz-4: #b48ce8; --viz-6: #5fb8dd; --viz-grid: #1b2b4b; --gold: #e3b457;
  --money: #f2b441; --money-soft: #fe920029; --physical: #98c3eb; --physical-soft: #98c3eb1f;
}
body { background: var(--surface-app); color: var(--text-primary); font-family: var(--font-ui); }
```

Rule: no literal hex in components. Every color is one of these variables.

## 2. Role mapping for the Ledger (the part that is specific to this app)

| Role in the UI | Token | Why |
|---|---|---|
| Dollar amounts, cash arrows, ledger totals, P&L | `--money` (+ `--money-soft` fills) | Amber is the brand's tertiary; reads on both grounds; never collides with status green/red |
| Physical quantities: MW, MWh, MMBtu, bbl, heat rate; the plant node; fuel arrows | `--physical` (+ `--physical-soft`) | Brand blue (light) / blue-300 (dark) |
| Prices ($/MWh, $/MMBtu) on arrows | `--text-primary` in `--font-mono`, with the arrow stroke in the role color of what flows (MW → physical, $ → money) | A price is a label, not a flow |
| Interactive: selected hour, active tab, focus ring, links, the scrubber handle | `--accent` / `--accent-soft` | The brand pair's role swap by theme comes free |
| Primary buttons | `--action-primary` → hover `--action-primary-hover`, text `--text-on-brand` | The brand's blue→green flip on light |
| Plant commitment state badges | off `--neutral`; hot `--warning`; warm `--info`; cold `--line-strong` text on `--surface-raised` | Shape + label too, never color alone |
| Outage / derate markers, invariant failures | `--danger` / `--danger-soft` | |
| Invariant checks passing, hedge in-the-money | `--success` / `--success-soft` | |
| Parameter provenance badges | public `--success-soft`; assumed `--warning-soft`; confirmed `--info-soft`; text in matching strong token | Always with the word, not just the fill |
| Chart series (energy, fuel, capacity, hedge, …) | `--viz-1` … `--viz-6` in order; grid `--viz-grid` | `--gold` reserved for a highlight marker |
| DA market node, RT market node, LSE node | `--surface-raised` fill, `--line-strong` stroke, label in `--font-display` `app-section` style | Markets are places, not quantities |

Negative money is shown in parentheses in `--money`, never in red; red is for failures and outages only.

## 3. Type

| Use | Family | Style |
|---|---|---|
| Page titles, node titles in the flow diagram | `--font-display` | 22px / 600 / −0.3px (`app-page-title`); section eyebrows 12px / 700 / 1.5px tracking uppercase (`app-section`) |
| Everything else | `--font-ui` | 13px / 1.45 default; 14px / 1.5 for notes and forms; 12px / 500 labels; 11px captions |
| Every number | `--font-mono` with `font-variant-numeric: tabular-nums`, right-aligned, units always shown | 13px in tables (`data-num`); 28px / 500 for KPI tiles (`app-kpi`) |

Load Inter and IBM Plex Mono from Google Fonts. brandon-grotesque is an Adobe Fonts face: use the Josefin Sans fallback unless the Adobe kit is supplied; never embed a copy.

## 4. Layout and elevation

- 4px spacing scale (`--space-1` … `--space-6`); panels are flat with a `--line` border; only menus, popovers and dialogs take `--shadow-popover`. No card shadows on tables or the flow diagram.
- Controls `--radius-control` (6px), cards and panels `--radius-md` (8px).
- Light theme: app ground `--surface-app` (blue-025), panels white. Dark: navy-cast near-black, panels `#10203f`. Do not use full `--navy-900` as a ground; it fights chart fills.
- Section pattern inherited from the brand: eyebrow → title → content. Use it for each screen's header.

## 5. Not allowed

- Any other wordmark, logo, favicon or name in a UI string, title tag or metadata.
- Brand green as small text on white (fails contrast). On light it is a fill or a hover; on dark it is the accent.
- Red/green as the only encoding of anything.
- Literal hex values in component code.
- Gradients from the marketing site; the app is flat.
