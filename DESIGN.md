---
name: Nimbus Index
description: Independent, signed outage data for parametric cloud cover, laid out like a cat-bond term sheet.
colors:
  navy: "#13294B"
  navy-deep: "#0C1C36"
  navy-line: "#2A426A"
  on-navy: "#FFFFFF"
  on-navy-soft: "#B9C8DE"
  ground: "#EDF0F4"
  paper: "#FFFFFF"
  sunk: "#F4F6F9"
  ink: "#0E1726"
  slate: "#4A5869"
  faint: "#6B7889"
  rule: "#D6DDE6"
  rule-strong: "#AEB9C7"
  link: "#1B4F9C"
  amber: "#E0A526"
  amber-ink: "#7D5200"
  amber-bg: "#FBF0D2"
  on-amber: "#1A1200"
  loss: "#C0392B"
  loss-ink: "#A42B1F"
  loss-bg: "#FBE6E3"
  loss-soft: "#E9A39A"
  inforce: "#2E7D5B"
  inforce-ink: "#23664A"
  inforce-bg: "#E1F1E8"
  inforce-soft: "#A8D4BD"
  undecided: "#5B6B7F"
  undecided-bg: "#E6EBF1"
  undecided-soft: "#D3DAE3"
  bar-ok: "#C5D1E0"
  bar-none: "#E3E8EE"
  dark-navy: "#102544"
  dark-navy-deep: "#08142A"
  dark-navy-line: "#24395C"
  dark-on-navy-soft: "#A9BAD3"
  dark-ground: "#0B1220"
  dark-paper: "#121B2C"
  dark-sunk: "#172235"
  dark-ink: "#E5EBF3"
  dark-slate: "#A3B0C2"
  dark-faint: "#8794A6"
  dark-rule: "#24314A"
  dark-rule-strong: "#3A4A66"
  dark-link: "#8DB6F0"
  dark-action: "#2F5FA8"
  dark-amber: "#F0B83C"
  dark-amber-ink: "#F3C761"
  dark-amber-bg: "#3A2C0C"
  dark-loss: "#F07A6C"
  dark-loss-ink: "#F59487"
  dark-loss-bg: "#3D1814"
  dark-loss-soft: "#8C3B33"
  dark-inforce: "#5CC495"
  dark-inforce-ink: "#7AD3AA"
  dark-inforce-bg: "#12301F"
  dark-inforce-soft: "#2F6B4D"
  dark-undecided: "#A3B0C2"
  dark-undecided-bg: "#1D2738"
  dark-undecided-soft: "#34425A"
  dark-bar-ok: "#2C3B55"
  dark-bar-none: "#1A2436"
typography:
  display:
    fontFamily: "'Source Serif 4', 'Source Serif Pro', Georgia, serif"
    fontSize: "clamp(34px, 5vw, 54px)"
    fontWeight: 600
    lineHeight: 1.08
    letterSpacing: "-0.015em"
  headline:
    fontFamily: "'Source Serif 4', 'Source Serif Pro', Georgia, serif"
    fontSize: "clamp(30px, 4.4vw, 46px)"
    fontWeight: 600
    lineHeight: 1.08
    letterSpacing: "-0.015em"
  title:
    fontFamily: "'Source Serif 4', 'Source Serif Pro', Georgia, serif"
    fontSize: "22px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.005em"
  figure:
    fontFamily: "'Source Serif 4', 'Source Serif Pro', Georgia, serif"
    fontSize: "19px"
    fontWeight: 600
    fontFeature: "tnum, lnum"
  defined-term:
    fontFamily: "'Source Serif 4', 'Source Serif Pro', Georgia, serif"
    fontSize: "15.5px"
    fontWeight: 600
  wordmark:
    fontFamily: "'Source Serif 4', 'Source Serif Pro', Georgia, serif"
    fontSize: "20px"
    fontWeight: 700
    letterSpacing: "-0.01em"
  lede:
    fontFamily: "'Public Sans', 'Helvetica Neue', Arial, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.5
  body:
    fontFamily: "'Public Sans', 'Helvetica Neue', Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
  subhead:
    fontFamily: "'Public Sans', 'Helvetica Neue', Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.3
  table:
    fontFamily: "'Public Sans', 'Helvetica Neue', Arial, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    fontFeature: "tnum, lnum"
  label:
    fontFamily: "'Public Sans', 'Helvetica Neue', Arial, sans-serif"
    fontSize: "12.5px"
    fontWeight: 600
    lineHeight: 1.4
  mono:
    fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.55
rounded:
  hair: "1px"
  bar: "2px"
  tag: "3px"
  r: "4px"
  pill: "99px"
spacing:
  cell: "11px 14px"
  cell-edge: "22px"
  panel: "18px 22px"
  gap: "20px"
  section: "28px"
  page: "28px 24px 64px"
  band: "34px 24px 38px"
components:
  shell:
    backgroundColor: "{colors.navy-deep}"
    textColor: "{colors.on-navy-soft}"
    height: "58px"
    padding: "0 24px"
  band:
    backgroundColor: "{colors.navy}"
    textColor: "{colors.on-navy}"
    typography: "{typography.headline}"
    padding: "{spacing.band}"
  panel:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.r}"
    padding: "{spacing.panel}"
  table-head:
    backgroundColor: "{colors.sunk}"
    textColor: "{colors.slate}"
    typography: "{typography.label}"
    padding: "{spacing.cell}"
  deftable-term:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.defined-term}"
    width: "32%"
  pill-up:
    backgroundColor: "{colors.inforce-bg}"
    textColor: "{colors.inforce-ink}"
    rounded: "{rounded.pill}"
    padding: "3px 11px 3px 9px"
  pill-down:
    backgroundColor: "{colors.loss-bg}"
    textColor: "{colors.loss-ink}"
    rounded: "{rounded.pill}"
    padding: "3px 11px 3px 9px"
  pill-undecided:
    backgroundColor: "{colors.undecided-bg}"
    textColor: "{colors.undecided}"
    rounded: "{rounded.pill}"
    padding: "3px 11px 3px 9px"
  seal-verified:
    backgroundColor: "{colors.amber}"
    textColor: "{colors.on-amber}"
    rounded: "{rounded.pill}"
    padding: "5px 11px 5px 9px"
  seal-failed:
    backgroundColor: "{colors.loss}"
    textColor: "{colors.on-navy}"
    rounded: "{rounded.pill}"
    padding: "5px 11px 5px 9px"
  ladder-bar:
    backgroundColor: "{colors.loss}"
    rounded: "{rounded.bar}"
    height: "18px"
  ladder-attachment:
    backgroundColor: "{colors.amber}"
    width: "2px"
  met-yes:
    backgroundColor: "{colors.amber}"
    textColor: "{colors.on-amber}"
    rounded: "{rounded.tag}"
    padding: "1px 8px"
  met-no:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.amber-ink}"
    rounded: "{rounded.tag}"
    padding: "1px 8px"
  day-square-up:
    backgroundColor: "{colors.inforce-soft}"
    rounded: "{rounded.hair}"
    height: "30px"
  day-square-minor:
    backgroundColor: "{colors.loss-soft}"
    rounded: "{rounded.hair}"
    height: "30px"
  day-square-major:
    backgroundColor: "{colors.loss}"
    rounded: "{rounded.hair}"
    height: "30px"
  day-square-none:
    backgroundColor: "{colors.bar-none}"
    rounded: "{rounded.hair}"
    height: "30px"
  button-primary:
    backgroundColor: "{colors.navy}"
    textColor: "{colors.on-navy}"
    rounded: "{rounded.r}"
    padding: "10px 18px"
  button-primary-hover:
    backgroundColor: "{colors.navy-deep}"
  button-primary-dark:
    backgroundColor: "{colors.dark-action}"
    textColor: "{colors.on-navy}"
  button-secondary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.navy}"
    rounded: "{rounded.r}"
    padding: "10px 18px"
  button-secondary-hover:
    backgroundColor: "{colors.sunk}"
  button-danger:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.loss-ink}"
    rounded: "{rounded.r}"
    padding: "10px 18px"
  button-danger-hover:
    backgroundColor: "{colors.loss-bg}"
  button-light:
    backgroundColor: "{colors.on-navy}"
    textColor: "{colors.navy}"
    rounded: "{rounded.r}"
    padding: "10px 18px"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.r}"
    padding: "10px 12px"
  tag:
    backgroundColor: "{colors.undecided-bg}"
    textColor: "{colors.undecided}"
    rounded: "{rounded.tag}"
    padding: "2px 8px"
  alert-error:
    backgroundColor: "{colors.loss-bg}"
    textColor: "{colors.loss-ink}"
    rounded: "{rounded.r}"
    padding: "12px 16px"
  alert-ok:
    backgroundColor: "{colors.inforce-bg}"
    textColor: "{colors.inforce-ink}"
    rounded: "{rounded.r}"
    padding: "12px 16px"
  example-data-banner:
    backgroundColor: "{colors.amber}"
    textColor: "{colors.on-amber}"
    padding: "8px 24px"
---

# Design System: Nimbus Index

## Overview

**Creative North Star: "The Term Sheet"**

Every page reads like a cat-bond offering circular: a navy cover band that states the one thing that matters, then white ruled schedules on a cool paper ground. Every outage is read the way a term sheet reads a trigger, against its attachment points. The signature is the trigger ladder: each outage a duration bar on one shared scale, crossed by amber 1 h and 2 h waiting-period lines and marked "met" where it passes them.

Density is that of a working document, not a marketing page: one column of ruled panels at most 1180px wide, tabular figures, defined terms set in serif like the definitions section of a prospectus. The system refuses the status-page default of white cards, green bars and a big-number tile row; numbers sit in ruled tables or defined-terms schedules, never in floating tiles.

One stylesheet set (the shared dashboard sheet plus the app sheet) serves both the public GitHub Pages dashboard and the signed-in app, in light and dark.

**Key Characteristics:**
- Navy shell and navy title band own the top of every page; everything below sits on paper.
- 1px rules, not shadows, separate everything. Corners are square-ish (4px).
- Amber is a reserved word: attachment point or verified, nothing else.
- Loss red for down, in-force green for up, slate hatching for undecided. Gaps are drawn, never smoothed into up.
- Serif for titles, defined terms and key figures; sans for UI and every table.

## Colors

A cool navy-and-paper document palette with three semantic inks (loss, in-force, undecided) and one reserved accent.

### Primary
- **Term Sheet Navy** (navy): the title band, primary buttons, focus border on inputs, checkbox accent. In dark mode the band darkens (dark-navy) and primary buttons switch to the lifted **Action Blue** (dark-action) so they still read against the dark ground.
- **Deep Navy** (navy-deep): the sticky shell bar and the primary button hover; also the home page's drawn ladder figure.
- **Navy Rule** (navy-line): rules and outlines on navy (judges divider, segmented control, ghost buttons in the band, code on navy).
- **On-Navy / On-Navy Soft** (on-navy, on-navy-soft): headings and secondary text on navy; inactive tabs.

### Secondary
- **Attachment Amber** (amber, amber-ink, amber-bg, on-amber): waiting-period lines and their tick labels, the "met" marks, attachment rows in the Summary of terms, the verified seal and Pass steps, and the Example data banner. Text on solid amber is always on-amber, never white. Amber-ink carries amber meaning as text on paper (attachment figures, "not met" outlines).

### Tertiary (semantic inks)
- **Loss Red** (loss, loss-ink, loss-bg, loss-soft): down. Ladder bars, failed-call bars, down pills, major and minor day squares, failed seal, Fail steps, error alerts, danger buttons.
- **In-Force Green** (inforce, inforce-ink, inforce-bg, inforce-soft): up. Up pills, up-all-day squares, counted-judge dots, success alerts.
- **Undecided Slate** (undecided, undecided-bg, undecided-soft): no call either way. Undecided pills, hatched undecided day squares, neutral tags.

### Neutral
- **Cool Paper** (ground): page background. **Paper** (paper): panels, inputs, secondary buttons. **Sunk** (sunk): table heads, ladder scale, empty tracks, code.
- **Ink / Slate / Faint** (ink, slate, faint): body text, secondary text and table heads, axis labels.
- **Rule / Rule Strong** (rule, rule-strong): every hairline; strong under table heads, around inputs and secondary buttons.
- **Bar OK / Bar None** (bar-ok, bar-none): healthy and empty steps in the 24 h failure strip; no-data day squares.
- **Link Blue** (link): inline links, 1px underline that thickens to 2px on hover.

### Named Rules
**The Reserved Amber Rule.** Amber means only an attachment point (a waiting period and whether it was met) or a verification result (signed, chains valid, Pass). The Example data banner is the one exception, so simulated data can never be mistaken for live. Navigation, branding, selection, tags and emphasis do not use amber.

**The Three Inks Rule.** State is carried by exactly three inks: loss red for down, in-force green for up, undecided slate (hatched where drawn) for no call. Undecided is never shown in green.

**The Dark Twin Rule.** Every colour token has a dark twin (dark-*), applied by system preference unless the page is pinned light, or when pinned dark. Shadows drop to none in dark mode.

## Typography

**Display Font:** Source Serif 4 (with Source Serif Pro, Georgia)
**Body Font:** Public Sans (with Helvetica Neue, Arial)
**Label/Mono Font:** system monospace (ui-monospace, SF Mono, Menlo, Consolas) for keys, records, endpoints and rule versions

**Character:** The serif plays the offering circular: titles, defined terms, service names and key figures. The sans is the operating instrument: navigation, controls, tables and every run of figures, always with tabular lining numerals.

### Hierarchy
- **Display** (600, clamp(34px, 5vw, 54px), 1.08): the landing page band headline only.
- **Headline** (600, clamp(30px, 4.4vw, 46px), 1.08, -0.015em): the one h1 per page, in the navy band. On the dashboard it states the official state and carries a 72px x 4px state bar beneath it (in-force soft, loss, or undecided soft).
- **Title** (600, 22px, 1.2): panel headings.
- **Figure** (600 serif, 19px in defined-terms tables, 17px elsewhere, tabular lining): key numbers inside schedules (official uptime, outages called, waiting periods met).
- **Defined term** (600 serif, 15.5px, upright): the term column of defined-terms tables. Service names use the same serif at 16px; day-strip labels at 15px.
- **Lede** (400, 17px, 1.5, max 64ch): band introductions, on-navy-soft.
- **Body** (400, 15px, 1.55): running text; panel-head descriptions at 14px, max 80ch.
- **Subhead** (600 sans, 15px): h3 inside panels.
- **Table** (400, 14px, tabular): every table cell; sub-lines at 12.5px slate.
- **Label** (600, 12.5px, slate, sentence case): table heads, form legends, stacked-cell labels (12px).
- **Wordmark** (700 serif, 20px, -0.01em): "Nimbus Index" in the shell.

### Named Rules
**The Defined Terms Rule.** A term the reader must rely on is set in serif as a defined term with its meaning beside it, never as a floating stat tile.

**The Tabular Figures Rule.** Every number that can be compared down a column uses tabular lining numerals and right-aligns in tables.

## Layout

The page is a stack: shell bar (58px min, sticky on desktop), optional Example data banner, navy title band, then one working column (max 1180px, padding 28px 24px 64px) of ruled panels separated by 28px. The band is a two-column grid (statement left, "Judged by" or a period switcher right, 40px gutter); the landing band splits 1.25 : 1 with the drawn ladder figure on the right. Inside panels: head 18px 22px 14px over a rule, body 18px 22px, foot 12px 22px over a rule; table cells 11px 14px with 22px at the outer edges so columns align with panel heads. Two-up grids (5 : 7 columns, verification grid) use a 20-22px gap. Forms sit in a narrow 520px column.

**Responsive behaviour:**
- At 980px the reports filter bar folds to two columns, fieldsets full width.
- At 900px the band, two-up grids and verification grid collapse to one column; the judges block moves under the statement with a top rule instead of a left rule.
- At 760px the shell stops being sticky and the tabs drop to their own full-width row that scrolls horizontally (faded at the right edge on phones).
- At 720px tables stack: the services table and every stack-table hide their header row and render each row as a ruled two-column grid card (first cell full width; each value labelled from its data-label in 12px slate). The ladder reflows to date and length on one line, the track full width beneath, meta below; attachment lines shorten to the track and the "wait" tick suffix hides.
- At 640px the day strip goes full width: label above the strip, cells lose their gap and corners and fill the row exactly with no horizontal scroll; the period switcher may scroll.

**The One Column Rule.** There is one reading column. Panels never float side by side except the explicit two-up grids, and those collapse at 900px.

## Elevation & Depth

Flat. Depth comes from tone (navy over paper over cool ground, sunk table heads) and from 1px rules. Panels carry only a hairline drop (`0 1px 0 rgba(14, 23, 38, .05)`), removed in dark mode. The one ring in the system is the input focus ring (3px, see Components).

### Shadow Vocabulary
- **Hairline drop** (`box-shadow: 0 1px 0 rgba(14, 23, 38, .05)`): panels in light mode only.

### Named Rules
**The Ruled Not Lifted Rule.** Separation is a 1px rule. Nothing hovers, nothing lifts on hover, no blurred shadows.

## Shapes

Square-ish and documentary. Panels, buttons, inputs, fieldsets, alerts and code blocks use 4px; tags, "met" marks, inline code and Pass/Fail chips 3px; ladder bars, tracks and legend swatches 2px; day squares 1px (0 on phones). Only state pills and the verified seal are fully rounded (99px), each led by a 7px dot in currentColor. Lines that mean something are 2px solid (attachment lines, attachment markers before defined terms); state bars under the h1 are 4px with 2px ends. Ongoing outages and undecided days use diagonal hatching rather than a new colour.

## Components

### Shell and Navigation
Deep navy bar, serif wordmark left, text tabs, account cluster right with an outlined "Pilot" tag (white text, navy-line border, 11.5px uppercase 700). Tabs are 14.5px 500 on-navy-soft with a 3px bottom border; hover turns them white; the current tab is white 600 with a 3px underline. On phones the tabs become a scrolling row under the wordmark. The public dashboard uses a simpler bar with the wordmark and a one-line description.

### Title Band
Navy, white serif h1, lede in on-navy-soft. Dashboard variant: h1 states the official state with the 4px state bar, a large state pill and the update line, and a "Judged by" list on the right (white 600 names, in-force-soft dot for counted companies, hollow dot for the reference network) closed by the verified seal. Slim variant (30px / 32px padding) for forms and admin. History adds a segmented period switcher (navy-line outline; current segment white with navy text). Ghost buttons in the band are transparent with a navy-line border; the landing CTA is the light button.

### Panels
White, 1px rule border, 4px corners, hairline drop. Head (serif title, optional slate description, optional right-aligned action or date) over a rule; body; optional slate foot over a rule.

### Ruled Tables
Full-width, collapsed, 14px. Header row on sunk with 12.5px 600 slate labels and a strong rule beneath; 1px rules between rows, none after the last. Numbers right-aligned and tabular; secondary lines as 12.5px slate sub-lines; down durations in loss-ink 600. Wide tables scroll inside their panel on desktop and stack on phones (see Layout).

### Defined-Terms Tables
Two columns: a serif defined term (32% wide, 42% on phones) on paper, and its meaning in ink. Key figures inside use the Figure style. Attachment rows (waiting periods met) put a 2px x 12px amber marker before the term and set the figure in amber-ink. A sub-heading row ("Definitions") sits on sunk with a 2px strong top rule. Used for the Summary of terms on History and the key terms on the landing page.

### Pills and Seal
Pills: 13px 600, 3px 11px 3px 9px, fully rounded, led by a 7px dot; up / down / undecided map to the three inks. The band variant is 14px. The verified seal (signed, chains valid) is amber with on-amber text and a 15px inline SVG mark; a failed chain turns it loss red with white text.

### Trigger Ladder (signature)
A ruled list on one shared time scale. Scale row (34px, sunk, strong rule beneath) shows hour ticks; ticks at waiting periods are amber-ink 700 and labelled "wait". Each row is a three-column grid (230px date and UTC time, track, 92px tabular duration in 700). The track is a 4px sunk line; the outage bar is loss red, 2px corners, width proportional to duration (min 3px), growing from the left over 1.1s on cubic-bezier(.16, 1, .3, 1) with a 60ms stagger, disabled under reduced motion. Ongoing outages hatch loss over loss-soft. Amber 2px attachment lines cross the whole row at each waiting period. Below: affected services, a "met" mark per waiting period (solid amber with a check when met, amber outline with amber-ink text when not met), and a minute-detail link. The landing page draws the same idea once in navy-deep inside the band.

### 24-Hour Failure Strip
Inside the services table: 10-minute steps as 1px-gapped bars, 30px tall; healthy steps in bar-ok, empty steps in bar-none at 35% height, failing steps in loss red with height proportional to the failed share (min 18%). A faint 11.5px axis ("24 h ago", "now") sits beneath.

### Day Squares
One cell per day per service on a shared grid (`repeat(n, minmax(3px, 1fr))`, 1px gap), 30px tall, 42px for the all-services row, which is separated by a rule. Classes map to in-force-soft (up all day), loss-soft (down under 1 h), loss (down 1 h or more), hatched undecided, and bar-none (no data). Every cell links to that day's report; hover and focus draw a 2px ink outline. A legend of 11px swatches sits in the panel head; a month axis sits beneath. On phones the strip fills the full width with no gap (see Layout).

### Buttons
- **Shape:** 4px corners, 600 14.5px Public Sans, 10px 18px (small: 6px 12px, 13.5px), 8px icon gap.
- **Primary:** navy fill, white text; hover navy-deep. Dark mode: Action Blue fill.
- **Secondary:** paper fill, navy text, rule-strong border; hover navy border on sunk.
- **Danger:** paper fill, loss-ink text, rule-strong border; hover loss border on loss-bg.
- **Light:** white fill, navy text, for the landing band; hover ground.
- **On navy:** ghost buttons go transparent with a navy-line border, white text.
- **Disabled:** 50% opacity, not-allowed cursor. Transitions 0.15s on background and border only.

### Forms
Labels stack above fields (14px 600; optional hints in 400 slate small). Inputs, selects and textareas: paper, 1px rule-strong border, 4px, 10px 12px, 15px; hover slate border; focus navy border plus a 3px ring. Fieldsets: 1px rule border, 4px, slate 13px legends, checkboxes in a wrapping row with navy accent. Stacked forms use a 16px gap in a 520px column. Alerts: 4px, 12px 16px, loss or in-force background with matching ink and soft border.

### Tags and Code
Tags: 12px 600, 2px 8px, 3px corners; neutral undecided, "on" in-force, "off" loss. Inline code: 13px mono on sunk with a rule border and 3px corners; on navy, mono on navy-line. Record blocks: 12px mono on sunk, rule border, 4px, 14px padding, max 420px tall.

### Example Data Banner
Full-width amber strip under the shell, on-amber 14px text, "Example data." in bold, shown on every page of the simulated copy. The only non-attachment, non-verification use of amber.

## Do's and Don'ts

### Do:
- **Do** draw every outage on the trigger ladder against the configured waiting periods, with amber lines and a met / not met mark for each.
- **Do** put the page's one statement in the navy band and the evidence in ruled panels below it.
- **Do** set terms a reader relies on as serif defined terms in a defined-terms table.
- **Do** show undecided minutes and missing days explicitly (undecided slate, hatched; bar-none for no data).
- **Do** use tabular lining numerals and right alignment for every comparable number.
- **Do** stack wide tables into labelled two-column rows below 720px and let the day strip fill the width below 640px.
- **Do** keep every colour change paired with its dark-* twin.

### Don't:
- **Don't** use amber for anything other than an attachment point or a verification result; the Example data banner is the sole exception.
- **Don't** build a row of big-number stat tiles or white floating cards; use ruled tables and defined-terms schedules.
- **Don't** show undecided or no-data time in green, or merge it into up.
- **Don't** lift elements with blurred shadows or hover translation; separate with 1px rules.
- **Don't** round panels, buttons or inputs beyond 4px; full rounding is reserved for state pills and the seal.
- **Don't** put white text on amber; use on-amber.
