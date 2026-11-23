---
name: POS System
description: Receipt Book, a light, ink-on-stock register world for a multi-store point of sale.
colors:
  paper: "#FAFAF7"
  paper-2: "#F3F3EF"
  panel: "#FFFFFF"
  ink: "#1E2430"
  ink-deep: "#0F141C"
  ink-2: "#4A5263"
  ink-3: "#626A7B"
  ink-disabled: "#8F96A3"
  rule: "#E3E3DD"
  rule-strong: "#C3C8D0"
  receipt-red: "#B3242B"
  receipt-red-hover: "#962027"
  red-tint: "#FBEAEA"
  red-rule: "#EBC4C6"
  red-ink: "#9E1F26"
  red-ink-deep: "#8E1C22"
  carbon: "#E8EEF6"
  carbon-rule: "#CFD9E6"
  carbon-ink: "#24467A"
  change-green: "#1F7A45"
  green-tint: "#E6F2EA"
  amber-ink: "#8A5300"
  amber-tint: "#FBF1DE"
  amber-rule: "#EED9AE"
  amber-mark: "#C98A1B"
  chip-rule: "#D6D8DC"
  rail: "#1E2430"
  rail-2: "#283040"
  rail-line: "#333B4A"
  rail-ink: "#E1E5EC"
  rail-muted: "#9AA3B4"
  rail-ink-muted: "#C9D0DC"
typography:
  figure-hero:
    fontFamily: "'JetBrains Mono', 'Source Sans 3', ui-monospace, Consolas, monospace"
    fontSize: "48px"
    fontWeight: 700
    lineHeight: 1.05
    letterSpacing: "-1.5px"
    fontFeature: "\"tnum\""
  figure-total:
    fontFamily: "'JetBrains Mono', 'Source Sans 3', ui-monospace, Consolas, monospace"
    fontSize: "44px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "-1.5px"
    fontFeature: "\"tnum\""
  headline:
    fontFamily: "'Source Sans 3', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "22px"
    fontWeight: 800
    lineHeight: 1.2
    letterSpacing: "-0.2px"
  title:
    fontFamily: "'Source Sans 3', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "20px"
    fontWeight: 800
    lineHeight: 1.2
  heading:
    fontFamily: "'Source Sans 3', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "16px"
    fontWeight: 700
    lineHeight: 1.3
  body:
    fontFamily: "'Source Sans 3', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.45
  body-sm:
    fontFamily: "'Source Sans 3', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.35
  label:
    fontFamily: "'Source Sans 3', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.45
  figure-summary:
    fontFamily: "'JetBrains Mono', 'Source Sans 3', ui-monospace, Consolas, monospace"
    fontSize: "22px"
    fontWeight: 700
    letterSpacing: "-0.5px"
    fontFeature: "\"tnum\""
  figure-row:
    fontFamily: "'JetBrains Mono', 'Source Sans 3', ui-monospace, Consolas, monospace"
    fontSize: "18px"
    fontWeight: 700
    fontFeature: "\"tnum\""
  figure:
    fontFamily: "'JetBrains Mono', 'Source Sans 3', ui-monospace, Consolas, monospace"
    fontSize: "15px"
    fontWeight: 700
    lineHeight: 1.25
    fontFeature: "\"tnum\""
  figure-meta:
    fontFamily: "'JetBrains Mono', 'Source Sans 3', ui-monospace, Consolas, monospace"
    fontSize: "11.5px"
    fontWeight: 400
    lineHeight: 1.4
  group-label:
    fontFamily: "'Source Sans 3', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "11.5px"
    fontWeight: 700
    letterSpacing: "1.2px"
rounded:
  sm: "4px"
  md: "6px"
  lg: "8px"
  xl: "10px"
spacing:
  "4": "4px"
  "8": "8px"
  "10": "10px"
  "12": "12px"
  "16": "16px"
  "20": "20px"
  "24": "24px"
  "28": "28px"
  "32": "32px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.panel}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.ink-deep}"
    textColor: "{colors.panel}"
  button-commit:
    backgroundColor: "{colors.receipt-red}"
    textColor: "{colors.panel}"
    rounded: "{rounded.md}"
    height: "58px"
  button-commit-hover:
    backgroundColor: "{colors.receipt-red-hover}"
    textColor: "{colors.panel}"
  button-ghost:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  button-ghost-hover:
    backgroundColor: "{colors.paper-2}"
  button-danger:
    backgroundColor: "{colors.red-tint}"
    textColor: "{colors.red-ink}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  button-icon:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    width: "36px"
    height: "32px"
  button-icon-danger-hover:
    backgroundColor: "{colors.red-tint}"
    textColor: "{colors.red-ink}"
  input:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "9px 12px"
    height: "42px"
  scan-field:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    height: "54px"
  chip:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "40px"
  chip-selected:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.panel}"
  pager-page:
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    height: "32px"
    width: "36px"
  pager-page-current:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.panel}"
  payment-option:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    height: "44px"
  payment-option-selected:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.panel}"
  product-tile:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "12px"
  receipt-column:
    backgroundColor: "{colors.carbon}"
    textColor: "{colors.ink}"
    width: "440px"
  receipt-sheet:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.md}"
    padding: "2px 14px"
  serial:
    textColor: "{colors.receipt-red}"
    typography: "{typography.figure}"
  card:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.lg}"
    padding: "20px 24px"
  attention-item:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "0 16px"
    height: "52px"
  attention-item-warn:
    backgroundColor: "{colors.amber-tint}"
    textColor: "{colors.ink}"
  column-bar:
    backgroundColor: "{colors.rule-strong}"
    width: "24px"
  column-bar-today:
    backgroundColor: "{colors.ink}"
  hbar:
    backgroundColor: "{colors.ink}"
    height: "14px"
  stock-track:
    backgroundColor: "{colors.paper-2}"
    rounded: "{rounded.sm}"
    height: "8px"
    width: "120px"
  stock-bar:
    backgroundColor: "{colors.ink-2}"
  stock-bar-low:
    backgroundColor: "{colors.amber-mark}"
  chart-tooltip:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.panel}"
    rounded: "{rounded.md}"
    padding: "8px 10px"
  toast:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.panel}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
  nav-rail:
    backgroundColor: "{colors.rail}"
    textColor: "{colors.rail-ink}"
    width: "232px"
  nav-item-active:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    height: "44px"
  badge-blue:
    backgroundColor: "{colors.carbon}"
    textColor: "{colors.carbon-ink}"
    rounded: "{rounded.sm}"
    padding: "2px 8px"
  badge-green:
    backgroundColor: "{colors.green-tint}"
    textColor: "#1F6B3D"
    rounded: "{rounded.sm}"
    padding: "2px 8px"
  badge-amber:
    backgroundColor: "{colors.amber-tint}"
    textColor: "{colors.amber-ink}"
    rounded: "{rounded.sm}"
    padding: "2px 8px"
  badge-red:
    backgroundColor: "{colors.red-tint}"
    textColor: "{colors.red-ink}"
    rounded: "{rounded.sm}"
    padding: "2px 8px"
---

# Design System: POS System

## Overview

**Creative North Star: "The Receipt Book"**

Every sale is a numbered receipt from the first scan. The register is set like the slip it will print: a white sheet of lines on a pale carbon-copy tint, figures aligned in a monospaced column, a red serial at the top and a heavy rule above the total. The rest of the app is the book's binding: a navy ink rail, a white topbar, soft stock-white ground and hairline rules. It is a working document, not a dashboard.

The world is light, dense and calm enough for a full shift under mixed store lighting. Colour is mostly ink on paper; accents are rationed and each one means something (red commits, green is money coming back, amber is low stock, carbon blue is the receipt and selection). Depth is paper-flat: panels are separated by hairlines and tint, and shadow appears only on things that float above the page.

The direction refused two looks by name: the dark navy dashboard with a neon accent, and the generic white SaaS POS with blue accents. Navy lives only in the rail and in ink; it is never a page ground, and blue never becomes a button colour.

**Key Characteristics:**
- Stock-white ground, white panels, navy ink; one red, one green, one amber, one carbon blue, each with a fixed job.
- Two faces: Source Sans 3 for words, JetBrains Mono for every figure (money, quantity, code, serial, TIN).
- Hairline rules everywhere, dashed rules between receipt lines, a 2px ink rule above the total.
- 6px corners as the default; 44px touch targets on the register.
- Motion is short exponential ease-out and fully disabled under reduced motion.
- Fully self-hosted: fonts and icons ship from `static/`, nothing from a CDN.

## Colors

Ink on soft stock, with four rationed accents that each carry one meaning.

### Primary
- **Receipt Red** (receipt-red): the commit colour. As a fill it appears on one control per screen: "Complete sale" (and its phone stand-in, the "Pay" jump on the sticky total bar). As ink it marks the sale serial, the half-second pulse on a newly rung line figure, and errors that block a sale (shortfall change, line errors, field errors), the "Out" stock figure, and the refunded segment of the sale-status bar. Hover deepens to Receipt Red Hover.
- **Red Ink family** (red-ink, red-ink-deep, red-rule, red-tint): the tinted danger register. Red Ink is the text of danger buttons and red badges, Red Ink Deep the text of error alerts and the refund warning, Red Rule their border, Red Tint the ground. Destructive actions (Delete product, Refund sale, the trash row action on hover) live here, never on a solid red fill.
- **Carbon Blue** (carbon): the carbon-copy tint of the receipt column, the selection highlight, the pressed state of a product tile, and the 3px focus halo around inputs. Its partners are Carbon Rule (carbon-rule) for borders on the tint and Carbon Ink (carbon-ink) for links, info alerts and blue badges.

### Secondary
- **Change Green** (change-green): money coming back and success: the change-due figure, success alerts and badges (on Green Tint), the scan "added" status, the receipt modal's check.

### Tertiary
- **Amber Ink** (amber-ink): low stock and warnings only, as text ("3 left") or on Amber Tint for warning badges, alerts, buttons and the attention strip's stock item (bordered in Amber Rule, amber-rule). Amber never fills a solid control.
- **Amber Mark** (amber-mark): the amber used for marks rather than words: the low-stock stock bar, the held segment of the sale-status bar, the amber stat-card dot. It is never text; amber words use Amber Ink.
- **Low stock is 1–5, out is 0.** The same threshold drives the register tiles, the dashboard's low-stock panel and attention strip, and the product list's stock filter and meter.

### Neutral
- **Stock White** (paper): the page ground, table header ground, and the active nav item, which reads as a tab cut out of the rail into the page.
- **Panel White** (panel): cards, topbar, inputs, product tiles, the receipt sheet, modals.
- **Stock Shade** (paper-2): hover ground for ghost buttons and chips, disabled/out-of-stock tiles, image wells.
- **Navy Ink** (ink): primary text, primary buttons, selected chips and payment options, the total rule, the toast. Ink Deep (ink-deep) is its hover.
- **Ink 2 / Ink 3** (ink-2, ink-3): secondary text and labels; tertiary text, captions, placeholders, table headers. Ink Disabled (ink-disabled) for a disabled commit button.
- **Hairline / Strong Rule** (rule, rule-strong): dividers and card borders; input, ghost button and table-header borders. Strong Rule is also the fill of past-day columns in the week chart and the chart baseline. Chip Rule (chip-rule) is the resting border of filter chips, between the two.
- **Rail family** (rail, rail-2, rail-line, rail-ink, rail-muted): the navigation rail only. Rail shares Navy Ink's value; Rail 2 is hover, Rail Line its dividers, Rail Ink its text, Rail Muted its icons, group labels and meta. Rail Ink Muted (rail-ink-muted) is the count figure inside a selected (ink-filled) chip.

### Named Rules
**The One Red Button Rule.** Receipt red fills exactly one control on a screen, the action that commits money. Sign-in, Print, Save and every other primary action use Navy Ink. Red is never decoration, never a link, never a secondary button.

**The Each Accent Means One Thing Rule.** Green is change and success, amber is low stock and warning, carbon blue is the receipt and selection. Don't borrow an accent for emphasis it doesn't mean.

**The Navy Is Ink Rule.** Navy appears as text, as the rail, and as the fill of selected and primary controls. It is never a page or panel ground.

**The Marks Are Not Words Rule.** Chart and meter marks take mark tones (Navy Ink, Ink 2, Strong Rule, Amber Mark, and the green/red status segments); chart labels, values, legends and tooltips stay in Navy Ink and the Ink greys. A value label never wears its bar's colour.

## Typography

**Body Font:** Source Sans 3 (variable 200–900, with system-ui, Segoe UI fallback)
**Label/Mono Font:** JetBrains Mono (variable 100–800, with Source Sans 3, Consolas fallback)

**Character:** A plain, legible humanist sans for every word, and a monospaced figure face that makes columns of money line up like a printed slip. Weight does the hierarchy work; the ramp is compact.

### Hierarchy
- **Figure Hero** (JetBrains Mono 700, 48px, line-height 1.05, -1.5px): the dashboard's "Sales today" figure, the single largest number on that page; 40px on phones.
- **Figure Total** (JetBrains Mono 700, 44px, line-height 1, -1.5px): the sale total. Steps down to 38px under 1200px wide and 36px on short screens.
- **Headline** (800, 22px, -0.2px): the topbar page title; 19px on phones. The sign-in heading uses the same weight at 28px.
- **Title** (800, 20px, 1.2): the register's panel headings such as "Current sale"; modal headers at 700.
- **Heading** (700, 16px, 1.3): panel headings on the dashboard and the product table head; sub-headings inside a panel drop to 14px.
- **Body** (400, 15px, 1.45): default text, nav items, line names (600), product names (600).
- **Body Small** (400, 14px, 1.35): table rows, bar-panel names (600, wrapping to two lines), list rows, the delta line, modal meta and toast text. Secondary meta in tables and keys runs 13.5px in Ink 2.
- **Label** (600, 13px): form and cart labels in Ink 2, stat labels, grid captions.
- **Figure Summary** (JetBrains Mono 700, 22px, -0.5px): summary figures above a table (history's completed count, total, refunded) and the refund total.
- **Figure Row** (JetBrains Mono 700, 18px): the dashboard's three-figure row (Transactions, Average sale, Last 7 days); 16px on phones.
- **Figure** (JetBrains Mono 700, 15px, tabular): line subtotals, quantities, serial (14px, +0.5px). Table figures, bar values and stock numbers run 14px; chart value labels and chip counts 12–12.5px. Product prices run 19px, change due 26px in Change Green, stat values 24px.
- **Figure Meta** (JetBrains Mono 400, 11.5px): barcodes, stock counts, unit prices, the store TIN.
- **Group Label** (700, 11.5px, uppercase, 1.2px): rail section labels only. Table column headers use the same treatment at 12px and 0.6px.

### Named Rules
**The Figures Are Mono Rule.** Every amount, quantity, code, serial and count is set in JetBrains Mono with tabular numerals. Words are never set in mono.

**The Peso Falls Back Rule.** The self-hosted JetBrains Mono subset does not contain the peso sign (U+20B1); `₱` renders from Source Sans 3's latin-ext subset via the figure stack. Keep Source Sans 3 second in the figure stack; don't add a CDN face to "fix" it.

## Layout

A fixed navy rail (232px) on the left, a sticky white topbar (64px; 56px on phones) and a padded content area (24px by 28px). From 992px up the rail can be collapsed (remembered per device); below 992px it becomes an off-canvas drawer (up to 288px) over a dimmed overlay, closed by Escape, the overlay, or choosing an item.

The register fills the content area edge to edge as two columns: a product work area (scan field, category chips, an auto-fill grid of tiles at least 136px wide with 10px gaps) and a sticky receipt column 440px wide (400px under 1200px, 372px under 992px) that stays the height of the viewport. On phones (under 768px) the receipt column stacks below the products and a sticky ink total bar at the bottom jumps to it.

Short screens (under 820px tall, 768px wide or more) tighten the receipt column: the seven payment options go to one row, steppers and buttons shrink, the total drops to 36px. On coarse pointers the 44px targets are restored. Under 700px tall the whole column scrolls.

The dashboard is a single column of panels, 16px apart, capped at 1400px: a "today" panel (the hero figure column at 260–340px beside the week chart; stacked under 1100px), a two-up attention strip, then two-up panel pairs (single column under 860px). List pages (history, products) lead with a filter row (chips, a search field at least 280px wide, inputs), then summary figures where they exist, then a full-bleed table card with a pager in its foot. Under 760px tables become stacked record cards: name or serial with the figure top-right, meta lines beneath, badge and row actions at the foot; header row hidden. Date-preset chips keep to one horizontally scrolling row on phones.

Spacing runs on a 4px base with 8, 10, 12, 16, 20, 24, 28 and 32 as the working steps (32 separates the dashboard hero from its chart and summary figures from each other); register controls sit 6–10px apart, panels pad 16–24px.

## Elevation & Depth

Paper-flat. Surfaces sit on the page and are told apart by hairline rules and tint (stock white, panel white, carbon blue), never by shadow. Shadow is reserved for things that genuinely float over the page, all cast in Navy Ink at low alpha.

### Shadow Vocabulary
- **Modal** (`box-shadow: 0 16px 40px rgba(30, 36, 48, .2)`): dialogs and the receipt modal (.25), over a `rgba(30, 36, 48, .45)` scrim.
- **Floating bar** (`box-shadow: 0 8px 24px rgba(30, 36, 48, .25)`): the toast and the chart tooltip; the phone total bar at .3.
- **Drawer** (`box-shadow: 12px 0 32px rgba(30, 36, 48, .25)`): the off-canvas rail on small screens.
- **Focus halo** (`box-shadow: 0 0 0 3px #E8EEF6`): input and scan-field focus, paired with an ink border. On the carbon receipt column the halo is white.

### Named Rules
**The Paper-Flat Rule.** Cards, tiles, the receipt sheet and the topbar carry no shadow. If it doesn't float, it doesn't cast.

## Shapes

Gently squared corners: 6px is the default for buttons, inputs, chips, tiles, the receipt sheet, alerts and the user avatar. Cards and stat cards use 8px, modals 10px, badges and image wells 4px. Attention-strip items and dashboard panels follow cards at 8px. Borders are 1px hairlines; the two deliberate exceptions are the 2px ink rule that marks a total (above the sale total, between the "Completed total" label and its figure in history, above the refund total) and the 2px ink border of the Hold button. Receipt lines are separated by 1px dashed rules, the one dashed device in the system.

Data marks are squared with a 4px round only at the value end: column bars round their top corners, horizontal and stock bars their right end, the status bar its two outer ends. Stock tracks are 8px pills at 4px; legend swatches are 10px squares at 2px.

## Components

### Buttons
Firm, flat, and sized for counters.
- **Shape:** gently squared (6px), 40px tall by default, 32px small; register actions 58px (50px on short screens).
- **Primary:** Navy Ink fill with white text, 600 weight, 16px side padding. Hover goes to Ink Deep. This is the default primary action everywhere, including sign-in.
- **Commit:** Receipt Red fill, white text, 700 at 17px on the register; hover Receipt Red Hover. Disabled becomes solid Ink Disabled rather than faded.
- **Ghost:** white with a Strong Rule border; hover Stock Shade. Hold uses the ghost with a 2px ink border so it reads as a real alternative to commit.
- **Tinted:** Danger (Red Tint, Red Ink text, Red Rule border) and Warning (Amber Tint with Amber Ink, Amber Rule border) for destructive or cautionary actions. A destructive modal commits with Danger beside a ghost Cancel; a constructive modal commits with Primary beside a ghost Cancel. Cancel takes initial focus in a destructive dialog.
- **Icon-only row actions:** ghost, 36px wide by 32px (small), always with an `aria-label` and title. A destructive icon action (delete) is neutral at rest and takes the Danger tint on hover.
- **Row text actions:** small ghost (32px, 13px). History's Refund appears only to staff and superusers, on completed sales.
- **Hover / Focus:** colour transitions at 120ms; a 2px ink outline offset 2px for keyboard focus (white inside the rail).

### Chips
- **Style:** category filters are 40px, white, 6px, hairline border, 600 at 14px, in a horizontally scrolling row.
- **State:** selected chips fill with Navy Ink and white text; `aria-pressed` carries the state on buttons, `aria-current` on link chips. Payment methods use the same language as a segmented radio grid (44px, four across, one row of seven on short screens).
- **Filter chips:** link chips on list pages, resting border Chip Rule, hover Stock Shade with Strong Rule. Date presets (Today, Yesterday, This week, This month) on history. Stock chips on products carry a mono count (12.5px, Ink 3; Rail Ink Muted when selected); the combined "Low or out of stock" view selects both the Low and Out chips at once.

### Cards / Containers
- **Corner Style:** 8px for cards and stat cards, 6px for the receipt sheet and product tiles.
- **Background:** Panel White on Stock White; the receipt column is Carbon Blue with a Carbon Rule border.
- **Shadow Strategy:** none (Paper-Flat Rule).
- **Border:** 1px Hairline.
- **Internal Padding:** cards 20px by 24px (16px on phones), stat cards 16px by 18px, tiles 12px.

### Inputs / Fields
- **Style:** white, 1px Strong Rule border, 6px, 42px tall, 15px text, placeholder in a mid grey. Labels sit above in the Label style.
- **Focus:** border goes to Navy Ink with a 3px Carbon Blue halo.
- **Scan field:** the register's lead input, 54px tall with a scanner icon and 17px text, autofocused; a status line below reports ready, added (green), warning (amber) or not found (red).
- **Error:** field errors in Receipt Red, 13px 600, below the field.

### Navigation
- **Style:** the navy rail carries the store name (17px 700 white), the TIN in Figure Meta, grouped links under Group Labels, and the signed-in user with role at the foot.
- **Items:** 44px tall, 15px Rail Ink with a Rail Muted icon; hover Rail 2. The active item is filled with Stock White and Navy Ink at 700, a tab cut out of the rail into the page.
- **Mobile:** off-canvas drawer with its own close button; the topbar toggle opens it.

### Tables, Badges, Alerts
- **Tables:** 14px tabular; uppercase 12px column heads in Ink 3 on Stock White over a Strong Rule; hairline row rules; rows hover a hair darker than the ground. Table cards are full-bleed (no padding) with 20px row insets; figures right-aligned. Sale serials sit in the first column in Receipt Red mono 700 (+0.5px), as `#139`. Empty tables show a centred 24px Strong Rule icon and one line saying what to do next.
- **Pager:** in the table card's foot above a hairline: "Page N of M" (or a range, "1–20 of 84") in 13.5px Ink 2 with mono figures on the left; small ghost Prev/Next and 36 by 32px mono page numbers on the right, the current page filled with Navy Ink, a window of two either side with ellipses.
- **Stock meter:** a 40px-wide mono stock number (14px 700) beside a 120px, 8px Stock Shade track whose bar is Ink 2 scaled to the largest stock on the page. Low (1–5) turns the number Amber Ink and the bar Amber Mark; out (0) shows a red "Out" and an empty track.
- **Badges:** 4px, 12px 600, tint fill with matching ink (green, amber, red, carbon blue).
- **Alerts:** 6px, tinted ground with a matching border and ink, a leading icon and a 32px close button.

### Receipt Column (signature)
The register's right column is the receipt being written. Header: "Current sale" with the serial beneath in red mono ("New sale", or "Resuming Nº" with the held sale's id; a number is never invented). A customer select, then the white receipt sheet: each line is name and unit price on the left, a −/+ stepper (36px; 44px on touch), and a right-aligned mono subtotal, separated by dashed rules. The sheet scrolls and fades its last 28px while more lines are hidden. Beneath, a 2px ink rule and the total in Figure Total; then payment, quick-cash amounts (₱20 to ₱1000 plus Exact), cash received with change due in large green mono (red when short), and Hold beside a double-width red Complete sale.

**Signature motion.** When a line is rung up it slides in from 6px above over 220ms, its subtotal flashes red and settles to ink over 500ms, and the total recounts with a 260ms rise. All on the exponential ease-out `cubic-bezier(.16, 1, .3, 1)`; all collapse to near-zero under reduced motion.

### Dashboard and Charts
Charts are server-rendered HTML and CSS: no chart library, no canvas, nothing from a CDN.
- **Hero figure:** "Sales today" (Heading) over the Figure Hero amount, then a delta line in Body Small: a green up-arrow and percentage when today is ahead, an ink down-arrow when behind (never red), and yesterday's amount in mono; "No sales yesterday to compare" when there is no base. Below a hairline, the three-figure row in Label over Figure Row.
- **Week column chart:** seven columns sharing one baseline (Strong Rule), at least 200px tall (160px on phones). Bars are at most 24px wide (60% of the column), 2px minimum, rounded 4px on top; today in Navy Ink, earlier days in Strong Rule; hover and focus deepen each a step. Value labels (12px mono) only on today and yesterday. Under each day name sits its transaction count in mono, explained by a right-aligned 12px key, in place of a second axis. Each column is focusable with a full `aria-label`; hover or focus shows the ink tooltip (date, amount, count) rising 4px. With no sales in the week, a centred empty line replaces the labels.
- **Attention strip:** two 52px items (held sales; products low or out of stock) as 8px hairline cards with a leading 18px icon, a mono count and a chevron; hover borders in ink. The stock item turns Amber Tint with Amber Rule and an Amber Ink icon and count when anything is low.
- **Horizontal bar panels:** a name column (at least 110px, up to 42%) wrapping to two lines, a 14px Navy Ink bar rounded at its right end, and a right-aligned 14px mono value; hover steps the bar to Ink 2. A cashier row adds a mono sale count beneath the name.
- **Status segmented bar:** a 12px bar of completed (Change Green), refunded (Receipt Red) and held (Amber Mark) segments with 2px gaps, outer ends rounded 4px, followed by a text legend of swatch, word and mono count (refund rate in Ink 3).
- **Panels:** Heading plus a 13px Ink 3 sub-line naming scope ("All time, completed sales", "5 or fewer left"); a Carbon Ink "Manage" link where the panel leads somewhere. Each has an explicit empty state.

**The Plain Chart Rule.** One axis at most; a single-series chart carries no legend box; direct labels are selective (today and yesterday, not every bar); a second measure is written as text under the axis, not plotted on another scale.

### Report, list and admin pages
Every page below the register is built from shared parts defined once in `templates/base.html`; page templates add only page-specific CSS.
- **Filter row** (`.filter-row`, `.field`): labelled fields 168px wide (full width on phones) with a Navy Ink "Show"/"Calculate" and a ghost reset ("Today", "This month"). Period switches are link chips (`.chips` / `.chip.is-on`).
- **Summary figures** (`.summary`): Label over Figure Summary. The headline total takes `.s-total` (2px ink rule between label and figure); a deduction takes `.s-neg` (Red Ink figure, written "− ₱"). A right-aligned `.s-scope` line says what the numbers cover.
- **Section head** (`.sec-head`): Heading plus a 13px Ink 3 `.panel-sub`, action button on the right.
- **Table card** (`.card.table-card`): full-bleed, serials in `.serial-cell`, figures `.num.fig`, a 2px ink rule over `tfoot` totals, the shared pager.
- **Phone records** (`.rec-table` with `rec-title`, `rec-total`, `rec-meta`, `rec-foot` on the cells): under 760px a row becomes the serial with its figure top-right, one meta line joined by "·", then any badge.
- **Topbar actions** wrap their label in `.btn-text`; under 600px the button shrinks to its icon and the label stays as its accessible name.
- **Report column chart** (`.vchart`, `.vc-col`, `.vc-bar`, `.vc-tip`): the dashboard chart's language, server-rendered. A previous-period comparison draws the earlier period as a narrow Strong Rule bar beside the Navy Ink current bar, explained by a text key (`.vc-key`); no axis, no legend box. Thin out labels on long ranges (every third hour, every fifth day).
- **Drawer slip** (cash closing): the drawer reconciliation is set as a receipt on the carbon tint: dashed lines, then the 2px ink rule and "Expected in drawer" in Figure Total.
- **Confirmation pages** (refund, delete held sale, delete store): a single 460–520px card, receipt-style item lines, a Red Tint danger note, ghost Cancel beside the tinted Danger commit. Deleting a store also requires typing its name.

### Platform console
The operator console uses the same shell: `platform_admin/base.html` extends `base.html` and replaces only the rail (`{% block rail %}`: "Platform console", the store list, the store being managed). The sign-in page matches the store sign-in. The console is never dark.

### Printed receipt and kiosk
- **Receipt** (`sales/receipt.html`, 80mm thermal): black only, Source Sans 3 for words and JetBrains Mono for figures (self-hosted), dashed rules between sections and a 2px rule over TOTAL. Refunded and held sales print a boxed stamp ("Refunded … by …", "Held · not paid — This is not a receipt"). It prints once its fonts have loaded.
- **Price-check kiosk** (`price_checker/kiosk.html`): full screen, no rail even on a signed-in browser (`{% block body %}` and `{% block shell_script %}` overridden). Store name in a white bar; one state at a time (idle, result, not found); the price in mono at up to 120px under a 2px ink rule; stock in the 1–5 low / 0 out language; a "type the barcode" fallback for screens without a scanner.

### Toast and Receipt Modal
The toast is an ink pill rising 16px from the bottom centre over 220ms, with a green, amber, or (on a red ground) error state. After a sale, the receipt modal shows the printable receipt in a frame with Print (primary) and New sale (ghost).

## Do's and Don'ts

### Do:
- **Do** reserve a Receipt Red fill for the single commit action on a screen; use Navy Ink for every other primary button.
- **Do** set every figure (money, quantity, code, serial, TIN, count) in JetBrains Mono with tabular numerals, keeping Source Sans 3 second in the stack so `₱` renders.
- **Do** separate surfaces with 1px hairlines and tint; use dashed rules only between receipt lines.
- **Do** keep register targets at 44px or larger, and restore them on coarse pointers whenever a layout tightens.
- **Do** use 6px corners for controls, 8px for cards, 10px for modals, 4px for badges.
- **Do** animate with the exponential ease-out at 120ms for state colour and 220–260ms for movement, and honour `prefers-reduced-motion`.
- **Do** self-host every font, icon and asset under `static/`.
- **Do** treat stock 1–5 as low and 0 as out on every surface.
- **Do** draw charts in server-rendered HTML and CSS with one axis, selective direct labels and an explicit empty state.
- **Do** commit a destructive modal with the tinted Danger button beside a ghost Cancel.
- **Do** read new tokens from the Receipt Book names on `:root` (`--paper`, `--ink`, `--red`, `--red-ink`, `--carbon`, `--green`, `--amber-ink`, `--amber-mark`, `--rule`, `--chip-rule`, `--font-ui`, `--font-fig`, `--radius`).

### Don't:
- **Don't** make navy a page or panel ground, or add a neon accent; the dark navy dashboard is a refused direction.
- **Don't** use blue as a button fill or as a generic accent; the generic white SaaS POS with blue accents is a refused direction. Carbon blue is the receipt tint and selection only.
- **Don't** use red, green or amber for emphasis they don't mean.
- **Don't** put shadows on cards, tiles, the topbar or the receipt sheet.
- **Don't** set words in mono or figures in the sans.
- **Don't** add a chart library, a second axis, or a legend box on a single-series chart; don't colour a chart label in its series colour.
- **Don't** use Amber Mark for text, or show a falling figure in red; red is not "down".
- **Don't** invent a sale serial; show "New sale" until a real number exists.
- **Don't** load fonts or icons from a CDN.
- **Don't** build new pages on the legacy aliases (`--navy`, `--navy2`, `--navy3`, `--card`, `--accent`, `--accent2`, `--amber`, `--danger`, `--text*`, `--border`, `--color-*`). They exist only so unredesigned pages keep rendering, and several names now lie (`--navy` resolves to Stock White). Migrate a page off them when it is redesigned.
