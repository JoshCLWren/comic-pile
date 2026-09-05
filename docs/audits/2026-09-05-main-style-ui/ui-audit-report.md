# Comic Pile UI visual and geometry audit

Generated: 2026-08-30T12:00:00.000Z
Fixture: fresh authenticatedWithThreadsPage user per viewport; three deterministic ten-issue threads; volatile username/session timestamps normalized
Scenarios: 32
Diagnostic warnings: 55

> Audit warnings are rendered evidence for investigation. They do not fail the harness by themselves. Navigation, fixture, browser-health, capture, or report-generation failures still fail the command.

## Coverage

| State | Route | Viewport | Screenshot | Warnings | Document |
| --- | --- | --- | --- | ---: | --- |
| roll | `/` | phone (390x844) | `screenshots/roll-phone-390x844.png` | 2 | 390x844 |
| roll-rating | `/` | phone (390x844) | `screenshots/roll-rating-phone-390x844.png` | 2 | 390x844 |
| queue | `/queue` | phone (390x844) | `screenshots/queue-phone-390x844.png` | 3 | 390x844 |
| history | `/history` | phone (390x844) | `screenshots/history-phone-390x844.png` | 0 | 390x844 |
| crossovers | `/crossovers` | phone (390x844) | `screenshots/crossovers-phone-390x844.png` | 0 | 390x844 |
| continuity-plans | `/continuity-plans` | phone (390x844) | `screenshots/continuity-plans-phone-390x844.png` | 0 | 390x844 |
| continuity-planner | `/continuity-plans/new` | phone (390x844) | `screenshots/continuity-planner-phone-390x844.png` | 1 | 390x844 |
| manual-picker-dialog | `/` | phone (390x844) | `screenshots/manual-picker-dialog-phone-390x844.png` | 5 | 390x844 |
| roll | `/` | tablet (820x1180) | `screenshots/roll-tablet-820x1180.png` | 8 | 820x1180 |
| roll-rating | `/` | tablet (820x1180) | `screenshots/roll-rating-tablet-820x1180.png` | 2 | 820x1180 |
| queue | `/queue` | tablet (820x1180) | `screenshots/queue-tablet-820x1180.png` | 1 | 820x1180 |
| history | `/history` | tablet (820x1180) | `screenshots/history-tablet-820x1180.png` | 1 | 820x1180 |
| crossovers | `/crossovers` | tablet (820x1180) | `screenshots/crossovers-tablet-820x1180.png` | 1 | 820x1180 |
| continuity-plans | `/continuity-plans` | tablet (820x1180) | `screenshots/continuity-plans-tablet-820x1180.png` | 1 | 820x1180 |
| continuity-planner | `/continuity-plans/new` | tablet (820x1180) | `screenshots/continuity-planner-tablet-820x1180.png` | 1 | 820x1180 |
| manual-picker-dialog | `/` | tablet (820x1180) | `screenshots/manual-picker-dialog-tablet-820x1180.png` | 6 | 820x1180 |
| roll | `/` | desktop (1280x900) | `screenshots/roll-desktop-1280x900.png` | 2 | 1280x900 |
| roll-rating | `/` | desktop (1280x900) | `screenshots/roll-rating-desktop-1280x900.png` | 2 | 1280x900 |
| queue | `/queue` | desktop (1280x900) | `screenshots/queue-desktop-1280x900.png` | 1 | 1280x900 |
| history | `/history` | desktop (1280x900) | `screenshots/history-desktop-1280x900.png` | 1 | 1280x900 |
| crossovers | `/crossovers` | desktop (1280x900) | `screenshots/crossovers-desktop-1280x900.png` | 1 | 1280x900 |
| continuity-plans | `/continuity-plans` | desktop (1280x900) | `screenshots/continuity-plans-desktop-1280x900.png` | 1 | 1280x900 |
| continuity-planner | `/continuity-plans/new` | desktop (1280x900) | `screenshots/continuity-planner-desktop-1280x900.png` | 1 | 1280x900 |
| manual-picker-dialog | `/` | desktop (1280x900) | `screenshots/manual-picker-dialog-desktop-1280x900.png` | 5 | 1280x900 |
| roll | `/` | wide-desktop (1920x1080) | `screenshots/roll-wide-desktop-1920x1080.png` | 1 | 1920x1080 |
| roll-rating | `/` | wide-desktop (1920x1080) | `screenshots/roll-rating-wide-desktop-1920x1080.png` | 1 | 1920x1080 |
| queue | `/queue` | wide-desktop (1920x1080) | `screenshots/queue-wide-desktop-1920x1080.png` | 0 | 1920x1080 |
| history | `/history` | wide-desktop (1920x1080) | `screenshots/history-wide-desktop-1920x1080.png` | 0 | 1920x1080 |
| crossovers | `/crossovers` | wide-desktop (1920x1080) | `screenshots/crossovers-wide-desktop-1920x1080.png` | 0 | 1920x1080 |
| continuity-plans | `/continuity-plans` | wide-desktop (1920x1080) | `screenshots/continuity-plans-wide-desktop-1920x1080.png` | 0 | 1920x1080 |
| continuity-planner | `/continuity-plans/new` | wide-desktop (1920x1080) | `screenshots/continuity-planner-wide-desktop-1920x1080.png` | 0 | 1920x1080 |
| manual-picker-dialog | `/` | wide-desktop (1920x1080) | `screenshots/manual-picker-dialog-wide-desktop-1920x1080.png` | 5 | 1920x1080 |

## Findings

### roll at phone

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"`, `main text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only"`
  - measurements: `{"overlapWidth":390,"overlapHeight":57,"overlapArea":22230,"chromePosition":"fixed"}`
- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `div`, `h1 text="PILE ROLLER"`
  - measurements: `{"overlapWidth":111,"overlapHeight":28,"overlapArea":3108,"chromePosition":"fixed"}`

### roll-rating at phone

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"`, `main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"`
  - measurements: `{"overlapWidth":390,"overlapHeight":57,"overlapArea":22230,"chromePosition":"fixed"}`
- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `div`, `h1 text="PILE ROLLER"`
  - measurements: `{"overlapWidth":111,"overlapHeight":28,"overlapArea":3108,"chromePosition":"fixed"}`

### queue at phone

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/queue`
  - elements: `nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"`, `main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3 + ⠿ #1 Test Thread 1 ISSUE"`
  - measurements: `{"overlapWidth":390,"overlapHeight":57,"overlapArea":22230,"chromePosition":"fixed"}`
- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/queue`
  - elements: `button aria-label=Add Thread text="+"`, `button aria-label=Open Test Thread 3 text="Test Thread 3"`
  - measurements: `{"overlapWidth":47,"overlapHeight":28,"overlapArea":1316,"chromePosition":"fixed"}`
- **element-collision** (medium confidence): Two independent interactive controls substantially overlap.
  - route: `/queue`
  - elements: `button aria-label=Add Thread text="+"`, `button aria-label=Open Test Thread 3 text="Test Thread 3"`
  - measurements: `{"overlapArea":1316,"smallerElementArea":3136,"overlapRatio":0.42}`

### continuity-planner at phone

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/continuity-plans/new`
  - elements: `nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"`, `main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"`
  - measurements: `{"overlapWidth":390,"overlapHeight":57,"overlapArea":22230,"chromePosition":"fixed"}`

### manual-picker-dialog at phone

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"`, `main text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only"`
  - measurements: `{"overlapWidth":390,"overlapHeight":57,"overlapArea":22230,"chromePosition":"fixed"}`
- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `div`, `h1 text="PILE ROLLER"`
  - measurements: `{"overlapWidth":111,"overlapHeight":28,"overlapArea":3108,"chromePosition":"fixed"}`
- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `div text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select "`, `main text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only"`
  - measurements: `{"overlapWidth":390,"overlapHeight":844,"overlapArea":329160,"chromePosition":"fixed"}`
- **element-collision** (medium confidence): Two independent interactive controls substantially overlap.
  - route: `/`
  - elements: `div role=button aria-label=Roll the dice data-testid=main-die-3d`, `select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is"`
  - measurements: `{"overlapArea":5800,"smallerElementArea":12960,"overlapRatio":0.448}`
- **element-collision** (medium confidence): Two independent interactive controls substantially overlap.
  - route: `/`
  - elements: `div role=button aria-label=Roll the dice data-testid=main-die-3d`, `button text="PICK THIS THREAD"`
  - measurements: `{"overlapArea":8000,"smallerElementArea":12960,"overlapRatio":0.617}`

### roll at tablet

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `div`, `h1 text="PILE ROLLER"`
  - measurements: `{"overlapWidth":133.8,"overlapHeight":32,"overlapArea":4282,"chromePosition":"fixed"}`
- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `button aria-label=Send feedback`, `main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"`
  - measurements: `{"overlapWidth":32,"overlapHeight":32,"overlapArea":1024,"chromePosition":"fixed"}`
- **unreachable-action** (high confidence): An interactive control is rendered outside its reachable viewport or document width.
  - route: `/`
  - elements: `a text="LADDER"`
  - measurements: `{"elementLeft":824,"elementTop":77.5,"elementRight":858.4,"elementBottom":101.5,"viewportWidth":820,"viewportHeight":1180,"documentScrollWidth":820,"position":"static"}`
- **container-escape** (medium confidence): An interactive element extends beyond its nearest semantic container.
  - route: `/`
  - elements: `a text="LADDER"`, `main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"`
  - measurements: `{"elementLeft":824,"elementRight":858.4,"containerLeft":288,"containerRight":820}`
- **clipped-action** (high confidence): An interactive control is clipped by an ancestor without a scrolling path on that axis.
  - route: `/`
  - elements: `a text="LADDER"`, `div text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"`
  - measurements: `{"clippedX":true,"clippedY":false,"ancestorOverflowX":"hidden","ancestorOverflowY":"auto"}`
- **unreachable-action** (high confidence): An interactive control is rendered outside its reachable viewport or document width.
  - route: `/`
  - elements: `button text="PICK MANUALLY"`
  - measurements: `{"elementLeft":962.4,"elementTop":75,"elementRight":1087.4,"elementBottom":119,"viewportWidth":820,"viewportHeight":1180,"documentScrollWidth":820,"position":"static"}`
- **container-escape** (medium confidence): An interactive element extends beyond its nearest semantic container.
  - route: `/`
  - elements: `button text="PICK MANUALLY"`, `main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"`
  - measurements: `{"elementLeft":962.4,"elementRight":1087.4,"containerLeft":288,"containerRight":820}`
- **clipped-action** (high confidence): An interactive control is clipped by an ancestor without a scrolling path on that axis.
  - route: `/`
  - elements: `button text="PICK MANUALLY"`, `div text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"`
  - measurements: `{"clippedX":true,"clippedY":false,"ancestorOverflowX":"hidden","ancestorOverflowY":"auto"}`

### roll-rating at tablet

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `div`, `h1 text="PILE ROLLER"`
  - measurements: `{"overlapWidth":133.8,"overlapHeight":32,"overlapArea":4282,"chromePosition":"fixed"}`
- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `button aria-label=Send feedback`, `main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"`
  - measurements: `{"overlapWidth":32,"overlapHeight":32,"overlapArea":1024,"chromePosition":"fixed"}`

### queue at tablet

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/queue`
  - elements: `button aria-label=Send feedback`, `main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"`
  - measurements: `{"overlapWidth":32,"overlapHeight":32,"overlapArea":1024,"chromePosition":"fixed"}`

### history at tablet

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/history`
  - elements: `button aria-label=Send feedback`, `main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "`
  - measurements: `{"overlapWidth":32,"overlapHeight":32,"overlapArea":1024,"chromePosition":"fixed"}`

### crossovers at tablet

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/crossovers`
  - elements: `button aria-label=Send feedback`, `main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"`
  - measurements: `{"overlapWidth":32,"overlapHeight":32,"overlapArea":1024,"chromePosition":"fixed"}`

### continuity-plans at tablet

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/continuity-plans`
  - elements: `button aria-label=Send feedback`, `main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"`
  - measurements: `{"overlapWidth":32,"overlapHeight":32,"overlapArea":1024,"chromePosition":"fixed"}`

### continuity-planner at tablet

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/continuity-plans/new`
  - elements: `button aria-label=Send feedback`, `main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"`
  - measurements: `{"overlapWidth":32,"overlapHeight":32,"overlapArea":1024,"chromePosition":"fixed"}`

### manual-picker-dialog at tablet

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `div`, `h1 text="PILE ROLLER"`
  - measurements: `{"overlapWidth":133.8,"overlapHeight":32,"overlapArea":4282,"chromePosition":"fixed"}`
- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `div text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select "`, `main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"`
  - measurements: `{"overlapWidth":532,"overlapHeight":1180,"overlapArea":627760,"chromePosition":"fixed"}`
- **container-escape** (medium confidence): An interactive element extends beyond its nearest semantic container.
  - route: `/`
  - elements: `a text="LADDER"`, `main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"`
  - measurements: `{"elementLeft":557,"elementRight":591.4,"containerLeft":21,"containerRight":553}`
- **container-escape** (medium confidence): An interactive element extends beyond its nearest semantic container.
  - route: `/`
  - elements: `button text="PICK MANUALLY"`, `main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"`
  - measurements: `{"elementLeft":695.4,"elementRight":820.4,"containerLeft":21,"containerRight":553}`
- **element-collision** (medium confidence): Two independent interactive controls substantially overlap.
  - route: `/`
  - elements: `div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"`, `select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is"`
  - measurements: `{"overlapArea":12996,"smallerElementArea":17556,"overlapRatio":0.74}`
- **element-collision** (medium confidence): Two independent interactive controls substantially overlap.
  - route: `/`
  - elements: `div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE"`, `button text="PICK THIS THREAD"`
  - measurements: `{"overlapArea":9234,"smallerElementArea":18480,"overlapRatio":0.5}`

### roll at desktop

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `div`, `h1 text="PILE ROLLER"`
  - measurements: `{"overlapWidth":133.8,"overlapHeight":32,"overlapArea":4282,"chromePosition":"fixed"}`
- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `button aria-label=Send feedback`, `main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"`
  - measurements: `{"overlapWidth":32,"overlapHeight":32,"overlapArea":1024,"chromePosition":"fixed"}`

### roll-rating at desktop

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `div`, `h1 text="PILE ROLLER"`
  - measurements: `{"overlapWidth":133.8,"overlapHeight":32,"overlapArea":4282,"chromePosition":"fixed"}`
- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `button aria-label=Send feedback`, `main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"`
  - measurements: `{"overlapWidth":32,"overlapHeight":32,"overlapArea":1024,"chromePosition":"fixed"}`

### queue at desktop

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/queue`
  - elements: `button aria-label=Send feedback`, `main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"`
  - measurements: `{"overlapWidth":32,"overlapHeight":32,"overlapArea":1024,"chromePosition":"fixed"}`

### history at desktop

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/history`
  - elements: `button aria-label=Send feedback`, `main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "`
  - measurements: `{"overlapWidth":32,"overlapHeight":32,"overlapArea":1024,"chromePosition":"fixed"}`

### crossovers at desktop

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/crossovers`
  - elements: `button aria-label=Send feedback`, `main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"`
  - measurements: `{"overlapWidth":32,"overlapHeight":32,"overlapArea":1024,"chromePosition":"fixed"}`

### continuity-plans at desktop

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/continuity-plans`
  - elements: `button aria-label=Send feedback`, `main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"`
  - measurements: `{"overlapWidth":32,"overlapHeight":32,"overlapArea":1024,"chromePosition":"fixed"}`

### continuity-planner at desktop

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/continuity-plans/new`
  - elements: `button aria-label=Send feedback`, `main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"`
  - measurements: `{"overlapWidth":32,"overlapHeight":32,"overlapArea":1024,"chromePosition":"fixed"}`

### manual-picker-dialog at desktop

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `div`, `h1 text="PILE ROLLER"`
  - measurements: `{"overlapWidth":133.8,"overlapHeight":32,"overlapArea":4282,"chromePosition":"fixed"}`
- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `button aria-label=Send feedback`, `main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"`
  - measurements: `{"overlapWidth":32,"overlapHeight":32,"overlapArea":1024,"chromePosition":"fixed"}`
- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `div text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select "`, `main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"`
  - measurements: `{"overlapWidth":992,"overlapHeight":900,"overlapArea":892800,"chromePosition":"fixed"}`
- **element-collision** (medium confidence): Two independent interactive controls substantially overlap.
  - route: `/`
  - elements: `div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"`, `select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is"`
  - measurements: `{"overlapArea":17556,"smallerElementArea":17556,"overlapRatio":1}`
- **element-collision** (medium confidence): Two independent interactive controls substantially overlap.
  - route: `/`
  - elements: `div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"`, `button text="PICK THIS THREAD"`
  - measurements: `{"overlapArea":13398,"smallerElementArea":18480,"overlapRatio":0.725}`

### roll at wide-desktop

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `div`, `h1 text="PILE ROLLER"`
  - measurements: `{"overlapWidth":133.8,"overlapHeight":32,"overlapArea":4282,"chromePosition":"fixed"}`

### roll-rating at wide-desktop

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `div`, `h1 text="PILE ROLLER"`
  - measurements: `{"overlapWidth":133.8,"overlapHeight":32,"overlapArea":4282,"chromePosition":"fixed"}`

### manual-picker-dialog at wide-desktop

- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `div`, `h1 text="PILE ROLLER"`
  - measurements: `{"overlapWidth":133.8,"overlapHeight":32,"overlapArea":4282,"chromePosition":"fixed"}`
- **chrome-overlap** (high confidence): Fixed or sticky chrome intersects meaningful page content.
  - route: `/`
  - elements: `div text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select "`, `main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"`
  - measurements: `{"overlapWidth":1536,"overlapHeight":1080,"overlapArea":1658880,"chromePosition":"fixed"}`
- **element-collision** (medium confidence): Two independent interactive controls substantially overlap.
  - route: `/`
  - elements: `div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"`, `button aria-label=Close modal text="×"`
  - measurements: `{"overlapArea":312,"smallerElementArea":312,"overlapRatio":1}`
- **element-collision** (medium confidence): Two independent interactive controls substantially overlap.
  - route: `/`
  - elements: `div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"`, `select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is"`
  - measurements: `{"overlapArea":17556,"smallerElementArea":17556,"overlapRatio":1}`
- **element-collision** (medium confidence): Two independent interactive controls substantially overlap.
  - route: `/`
  - elements: `div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE"`, `button text="PICK THIS THREAD"`
  - measurements: `{"overlapArea":14784,"smallerElementArea":18480,"overlapRatio":0.8}`

## Computed-style inventory

The inventory is descriptive, not a defect list. Repeated or unique values are evidence only.

### roll at phone

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 8 | a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY"; a aria-label=Crossovers page text="CROSSOVERS" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 4 | button text="SHUFFLE QUEUE"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE" |
| colors | background-color | `rgba(212, 137, 14, 0.12)` | 1 | a aria-label=Roll page text="ROLL" |
| colors | background-color | `rgba(255, 255, 255, 0.04)` | 1 | button aria-label=Current die d6, automatic mode text="d6 AUTO" |
| colors | background-color | `rgb(212, 137, 14)` | 1 | button text="PICK MANUALLY" |
| colors | border-color | `rgb(232, 213, 176)` | 5 | a aria-label=Roll page text="ROLL"; main text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only"; div text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only" |
| colors | border-color | `rgb(160, 147, 126)` | 4 | a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY"; a aria-label=Crossovers page text="CROSSOVERS" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| colors | border-color | `rgba(255, 255, 255, 0.08) rgb(232, 213, 176) rgb(232, 213, 176)` | 1 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 1 | button aria-label=Current die d6, automatic mode text="d6 AUTO" |
| colors | border-color | `oklch(0.216 0.006 56.043)` | 1 | button text="PICK MANUALLY" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 1 | button text="SHUFFLE QUEUE" |
| colors | color | `rgb(232, 213, 176)` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; main text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only" |
| colors | color | `rgb(160, 147, 126)` | 4 | a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY"; a aria-label=Crossovers page text="CROSSOVERS" |
| colors | color | `rgb(212, 137, 14)` | 1 | button aria-label=Current die d6, automatic mode text="d6 AUTO" |
| colors | color | `oklch(0.216 0.006 56.043)` | 1 | button text="PICK MANUALLY" |
| colors | color | `oklch(0.869 0.005 56.366)` | 1 | button text="SHUFFLE QUEUE" |
| controls | border-width | `0px` | 7 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | border-width | `1px` | 5 | button aria-label=Current die d6, automatic mode text="d6 AUTO"; button text="SHUFFLE QUEUE"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE" |
| controls | height | `56px` | 5 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | height | `79px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| controls | height | `44px` | 2 | button aria-label=Current die d6, automatic mode text="d6 AUTO"; button text="PICK MANUALLY" |
| controls | height | `200px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| controls | height | `32px` | 1 | button text="SHUFFLE QUEUE" |
| controls | min-height | `auto` | 7 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | min-height | `0px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| controls | min-height | `44px` | 2 | button aria-label=Current die d6, automatic mode text="d6 AUTO"; button text="PICK MANUALLY" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only"; div text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only"; div text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only" |
| panels | border-radius | `0px` | 2 | main text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only"; div text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only" |
| panels | box-shadow | `none` | 2 | main text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only"; div text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only" |
| radii | border-radius | `0px` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| radii | border-radius | `12px` | 4 | button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| radii | border-radius | `8px` | 2 | button aria-label=Current die d6, automatic mode text="d6 AUTO"; button text="SHUFFLE QUEUE" |
| radii | border-radius | `3.35544e+07px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| shadows | box-shadow | `none` | 15 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| shadows | box-shadow | `rgba(212, 137, 14, 0.243) 0px 0px 38.7484px 0px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| spacing | gap | `normal` | 12 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | gap | `12px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | gap | `8px 12px` | 1 | header text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY" |
| spacing | margin-bottom | `0px` | 14 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | margin-bottom | `8px` | 2 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| spacing | margin-top | `0px` | 15 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | margin-top | `16px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| spacing | padding-bottom | `0px` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-bottom | `12px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-bottom | `80px` | 1 | main text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only" |
| spacing | padding-bottom | `8px` | 1 | header text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY" |
| spacing | padding-bottom | `4px` | 1 | button aria-label=Current die d6, automatic mode text="d6 AUTO" |
| spacing | padding-bottom | `6px` | 1 | button text="PICK MANUALLY" |
| spacing | padding-left | `0px` | 8 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-left | `12px` | 4 | main text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only"; button aria-label=Current die d6, automatic mode text="d6 AUTO"; button text="PICK MANUALLY" |
| spacing | padding-left | `16px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-left | `8px` | 1 | header text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY" |
| spacing | padding-right | `0px` | 8 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-right | `12px` | 4 | main text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only"; button aria-label=Current die d6, automatic mode text="d6 AUTO"; button text="PICK MANUALLY" |
| spacing | padding-right | `16px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-right | `8px` | 1 | header text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY" |
| spacing | padding-top | `0px` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-top | `12px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-top | `16px` | 1 | main text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only" |
| spacing | padding-top | `8px` | 1 | header text="PILE ROLLER d6 AUTO BALANCED PICK MANUALLY" |
| spacing | padding-top | `4px` | 1 | button aria-label=Current die d6, automatic mode text="d6 AUTO" |
| spacing | padding-top | `6px` | 1 | button text="PICK MANUALLY" |
| typography | font-family | `Outfit, sans-serif` | 16 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-size | `16px` | 14 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-size | `10px` | 2 | button text="PICK MANUALLY"; button text="SHUFFLE QUEUE" |
| typography | font-weight | `400` | 14 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-weight | `900` | 2 | button text="PICK MANUALLY"; button text="SHUFFLE QUEUE" |
| typography | letter-spacing | `normal` | 14 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | letter-spacing | `1px` | 2 | button text="PICK MANUALLY"; button text="SHUFFLE QUEUE" |
| typography | line-height | `24px` | 14 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | line-height | `15px` | 2 | button text="PICK MANUALLY"; button text="SHUFFLE QUEUE" |

### roll-rating at phone

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 11 | a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY"; a aria-label=Crossovers page text="CROSSOVERS" |
| colors | background-color | `rgba(255, 255, 255, 0.05)` | 2 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #" |
| colors | background-color | `rgba(255, 255, 255, 0.04)` | 2 | section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 2 | button text="SNOOZE"; button aria-label=Skip current roll data-testid=skip-roll text="SKIP" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE" |
| colors | background-color | `rgba(212, 137, 14, 0.12)` | 1 | a aria-label=Roll page text="ROLL" |
| colors | background-color | `oklch(0.769 0.188 70.08)` | 1 | button text="FIND COMICVINE MATCH" |
| colors | background-color | `rgba(6, 182, 212, 0.09)` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| colors | background-color | `oklab(0.666 0.0940116 0.152325 / 0.25)` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| colors | background-color | `oklab(0.586 0.241177 0.0764364 / 0.1)` | 1 | button text="CANCEL ROLL" |
| colors | border-color | `rgb(232, 213, 176)` | 6 | a aria-label=Roll page text="ROLL"; main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss" |
| colors | border-color | `rgb(160, 147, 126)` | 4 | a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY"; a aria-label=Crossovers page text="CROSSOVERS" |
| colors | border-color | `rgba(255, 255, 255, 0.1)` | 2 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | button text="SNOOZE"; button aria-label=Skip current roll data-testid=skip-roll text="SKIP" |
| colors | border-color | `rgba(255, 255, 255, 0.08) rgb(232, 213, 176) rgb(232, 213, 176)` | 1 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE" |
| colors | border-color | `oklch(0.216 0.006 56.043)` | 1 | button text="FIND COMICVINE MATCH" |
| colors | border-color | `rgba(6, 182, 212, 0.3)` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 1 | section text="ROLL RESULT Rolled 0 on d6 SERIES PROGRESS" |
| colors | border-color | `rgba(168, 85, 247, 0.15)` | 1 | section text="SERIES HISTORY Canonical series history unavailable" |
| colors | border-color | `rgba(168, 85, 247, 0.2)` | 1 | section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 1 | a text="d6 → d4" |
| colors | border-color | `oklab(0.666 0.0940116 0.152325 / 0.5)` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| colors | border-color | `oklab(0.586 0.241177 0.0764364 / 0.3)` | 1 | button text="CANCEL ROLL" |
| colors | color | `rgb(232, 213, 176)` | 12 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss" |
| colors | color | `rgb(160, 147, 126)` | 4 | a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY"; a aria-label=Crossovers page text="CROSSOVERS" |
| colors | color | `oklch(0.869 0.005 56.366)` | 4 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="SNOOZE" |
| colors | color | `oklch(0.216 0.006 56.043)` | 1 | button text="FIND COMICVINE MATCH" |
| colors | color | `oklch(0.828 0.189 84.429)` | 1 | a text="d6 → d4" |
| colors | color | `oklch(0.712 0.194 13.428)` | 1 | button text="CANCEL ROLL" |
| controls | border-width | `0px` | 8 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | border-width | `1px` | 6 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button data-testid=save-and-continue text="MARK READ & SAVE" |
| controls | height | `56px` | 5 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | height | `44px` | 5 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="SNOOZE" |
| controls | height | `36px` | 1 | button text="FIND COMICVINE MATCH" |
| controls | height | `auto` | 1 | a text="d6 → d4" |
| controls | height | `16px` | 1 | input aria-label=Rating from 0.5 to 5.0 in steps of 0.5 |
| controls | height | `46px` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| controls | min-height | `auto` | 5 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | min-height | `44px` | 5 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="SNOOZE" |
| controls | min-height | `0px` | 3 | a text="d6 → d4"; input aria-label=Rating from 0.5 to 5.0 in steps of 0.5; button data-testid=save-and-continue text="MARK READ & SAVE" |
| controls | min-height | `36px` | 1 | button text="FIND COMICVINE MATCH" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 4 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| panels | background-color | `rgba(255, 255, 255, 0.04)` | 2 | section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| panels | background-color | `rgba(6, 182, 212, 0.09)` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| panels | border-color | `rgb(232, 213, 176)` | 3 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| panels | border-color | `rgba(6, 182, 212, 0.3)` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| panels | border-color | `rgba(255, 255, 255, 0.08)` | 1 | section text="ROLL RESULT Rolled 0 on d6 SERIES PROGRESS" |
| panels | border-color | `rgba(168, 85, 247, 0.15)` | 1 | section text="SERIES HISTORY Canonical series history unavailable" |
| panels | border-color | `rgba(168, 85, 247, 0.2)` | 1 | section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| panels | border-radius | `0px` | 4 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| panels | border-radius | `16px` | 3 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis"; section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| panels | box-shadow | `none` | 7 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| radii | border-radius | `0px` | 13 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| radii | border-radius | `12px` | 6 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button data-testid=save-and-continue text="MARK READ & SAVE" |
| radii | border-radius | `16px` | 3 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis"; section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| radii | border-radius | `8px` | 1 | button text="FIND COMICVINE MATCH" |
| shadows | box-shadow | `none` | 23 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | gap | `normal` | 21 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | gap | `8px 12px` | 1 | header text="PILE ROLLER" |
| spacing | gap | `12px 24px` | 1 | section text="ROLL RESULT Rolled 0 on d6 SERIES PROGRESS" |
| spacing | margin-bottom | `0px` | 18 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | margin-bottom | `16px` | 3 | section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl"; section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis"; section text="SERIES HISTORY Canonical series history unavailable" |
| spacing | margin-bottom | `12px` | 1 | input aria-label=Rating from 0.5 to 5.0 in steps of 0.5 |
| spacing | margin-bottom | `8px` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| spacing | margin-top | `0px` | 23 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-bottom | `0px` | 13 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-bottom | `12px` | 6 | section text="ROLL RESULT Rolled 0 on d6 SERIES PROGRESS"; section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| spacing | padding-bottom | `80px` | 1 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss" |
| spacing | padding-bottom | `8px` | 1 | header text="PILE ROLLER" |
| spacing | padding-bottom | `16px` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| spacing | padding-bottom | `14px` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| spacing | padding-left | `0px` | 15 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-left | `12px` | 6 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #" |
| spacing | padding-left | `8px` | 1 | header text="PILE ROLLER" |
| spacing | padding-left | `16px` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| spacing | padding-right | `0px` | 15 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-right | `12px` | 6 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #" |
| spacing | padding-right | `8px` | 1 | header text="PILE ROLLER" |
| spacing | padding-right | `16px` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| spacing | padding-top | `0px` | 14 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-top | `12px` | 5 | section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of"; button text="SNOOZE" |
| spacing | padding-top | `16px` | 2 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| spacing | padding-top | `8px` | 1 | header text="PILE ROLLER" |
| spacing | padding-top | `14px` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| typography | font-family | `Outfit, sans-serif` | 23 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-size | `16px` | 15 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-size | `12px` | 4 | button data-testid=save-and-continue text="MARK READ & SAVE"; button text="SNOOZE"; button aria-label=Skip current roll data-testid=skip-roll text="SKIP" |
| typography | font-size | `10px` | 3 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="FIND COMICVINE MATCH" |
| typography | font-size | `14px` | 1 | a text="d6 → d4" |
| typography | font-weight | `400` | 15 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-weight | `900` | 7 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="FIND COMICVINE MATCH" |
| typography | font-weight | `700` | 1 | a text="d6 → d4" |
| typography | letter-spacing | `normal` | 16 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | letter-spacing | `1.8px` | 4 | button data-testid=save-and-continue text="MARK READ & SAVE"; button text="SNOOZE"; button aria-label=Skip current roll data-testid=skip-roll text="SKIP" |
| typography | letter-spacing | `0.5px` | 3 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="FIND COMICVINE MATCH" |
| typography | line-height | `24px` | 15 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | line-height | `16px` | 4 | button data-testid=save-and-continue text="MARK READ & SAVE"; button text="SNOOZE"; button aria-label=Skip current roll data-testid=skip-roll text="SKIP" |
| typography | line-height | `15px` | 3 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="FIND COMICVINE MATCH" |
| typography | line-height | `20px` | 1 | a text="d6 → d4" |

### queue at phone

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 19 | a aria-label=Roll page text="ROLL"; a aria-label=History page text="HISTORY"; a aria-label=Crossovers page text="CROSSOVERS" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 10 | button text="SHUFFLE"; button text="A-Z"; button text="NEW" |
| colors | background-color | `rgb(212, 137, 14)` | 3 | button aria-label=Read text="Read" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE" |
| colors | background-color | `rgba(212, 137, 14, 0.12)` | 1 | a aria-label=Queue page text="QUEUE" |
| colors | background-color | `oklab(0.666 0.0940116 0.152325 / 0.2)` | 1 | button text="POS" |
| colors | background-color | `oklch(0.666 0.179 58.318)` | 1 | button aria-label=Add Thread text="+" |
| colors | border-color | `rgb(160, 147, 126)` | 10 | a aria-label=Roll page text="ROLL"; a aria-label=History page text="HISTORY"; a aria-label=Crossovers page text="CROSSOVERS" |
| colors | border-color | `rgb(232, 213, 176)` | 7 | a aria-label=Queue page text="QUEUE"; main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3 + ⠿ #1 Test Thread 1 ISSUE"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3 + ⠿ #1 Test Thread 1 ISSUE" |
| colors | border-color | `rgb(107, 95, 80)` | 6 | button aria-label=Drag to reorder text="⠿"; button aria-label=Delete text="Delete" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 4 | button text="SHUFFLE"; button text="A-Z"; button text="NEW" |
| colors | border-color | `rgb(255, 255, 255)` | 4 | button aria-label=Add Thread text="+"; button aria-label=Read text="Read" |
| colors | border-color | `oklch(0.553 0.013 58.071)` | 3 | button aria-label=Thread actions text="⋮" |
| colors | border-color | `rgba(255, 255, 255, 0.08) rgb(232, 213, 176) rgb(232, 213, 176)` | 1 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE" |
| colors | border-color | `oklab(0.769 0.0640531 0.176752 / 0.3)` | 1 | button text="POS" |
| colors | color | `rgb(160, 147, 126)` | 10 | a aria-label=Roll page text="ROLL"; a aria-label=History page text="HISTORY"; a aria-label=Crossovers page text="CROSSOVERS" |
| colors | color | `rgb(232, 213, 176)` | 8 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Queue page text="QUEUE"; main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3 + ⠿ #1 Test Thread 1 ISSUE" |
| colors | color | `rgb(107, 95, 80)` | 6 | button aria-label=Drag to reorder text="⠿"; button aria-label=Delete text="Delete" |
| colors | color | `rgb(255, 255, 255)` | 4 | button aria-label=Add Thread text="+"; button aria-label=Read text="Read" |
| colors | color | `oklch(0.553 0.013 58.071)` | 3 | button aria-label=Thread actions text="⋮" |
| colors | color | `oklch(0.869 0.005 56.366)` | 2 | button text="SHUFFLE"; input |
| colors | color | `oklch(0.709 0.01 56.259)` | 2 | button text="A-Z"; button text="NEW" |
| colors | color | `oklch(0.828 0.189 84.429)` | 1 | button text="POS" |
| controls | border-width | `0px` | 27 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | border-width | `1px` | 5 | button text="SHUFFLE"; button text="POS"; button text="A-Z" |
| controls | height | `44px` | 18 | button aria-label=Drag to reorder text="⠿"; button aria-label=Read text="Read"; button aria-label=Edit text="Edit" |
| controls | height | `56px` | 6 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | height | `29px` | 3 | button text="POS"; button text="A-Z"; button text="NEW" |
| controls | height | `28px` | 3 | button aria-label=Open Test Thread 1 text="Test Thread 1"; button aria-label=Open Test Thread 2 text="Test Thread 2"; button aria-label=Open Test Thread 3 text="Test Thread 3" |
| controls | height | `36px` | 2 | button text="SHUFFLE"; input |
| controls | min-height | `auto` | 28 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | min-height | `0px` | 4 | button aria-label=Add Thread text="+"; button aria-label=Thread actions text="⋮" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3 + ⠿ #1 Test Thread 1 ISSUE"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3 + ⠿ #1 Test Thread 1 ISSUE" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3 + ⠿ #1 Test Thread 1 ISSUE"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3 + ⠿ #1 Test Thread 1 ISSUE" |
| panels | border-radius | `0px` | 2 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3 + ⠿ #1 Test Thread 1 ISSUE"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3 + ⠿ #1 Test Thread 1 ISSUE" |
| panels | box-shadow | `none` | 2 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3 + ⠿ #1 Test Thread 1 ISSUE"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3 + ⠿ #1 Test Thread 1 ISSUE" |
| radii | border-radius | `8px` | 23 | button text="SHUFFLE"; button text="POS"; button text="A-Z" |
| radii | border-radius | `0px` | 12 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Add Thread text="+" |
| shadows | box-shadow | `none` | 35 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(212, 137, 14, 0.4) 0px 4px 20px 0px` | 1 | button aria-label=Add Thread text="+" |
| spacing | gap | `normal` | 33 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | gap | `6px` | 3 | button aria-label=Snooze text="😴 Snooze" |
| spacing | margin-bottom | `0px` | 34 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | margin-bottom | `24px` | 2 | header text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3"; button aria-label=Add Thread text="+" |
| spacing | margin-top | `0px` | 36 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-bottom | `0px` | 31 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-bottom | `6px` | 3 | button text="POS"; button text="A-Z"; button text="NEW" |
| spacing | padding-bottom | `80px` | 1 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3 + ⠿ #1 Test Thread 1 ISSUE" |
| spacing | padding-bottom | `40px` | 1 | div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3 + ⠿ #1 Test Thread 1 ISSUE" |
| spacing | padding-left | `0px` | 17 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-left | `12px` | 12 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3 + ⠿ #1 Test Thread 1 ISSUE"; button text="SHUFFLE"; input |
| spacing | padding-left | `10px` | 3 | button text="POS"; button text="A-Z"; button text="NEW" |
| spacing | padding-left | `16px` | 3 | button aria-label=Read text="Read" |
| spacing | padding-left | `8px` | 1 | header text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3" |
| spacing | padding-right | `0px` | 17 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-right | `12px` | 12 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3 + ⠿ #1 Test Thread 1 ISSUE"; button text="SHUFFLE"; input |
| spacing | padding-right | `10px` | 3 | button text="POS"; button text="A-Z"; button text="NEW" |
| spacing | padding-right | `16px` | 3 | button aria-label=Read text="Read" |
| spacing | padding-right | `8px` | 1 | header text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3" |
| spacing | padding-top | `0px` | 32 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-top | `6px` | 3 | button text="POS"; button text="A-Z"; button text="NEW" |
| spacing | padding-top | `16px` | 1 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE POS A-Z NEW 3 + ⠿ #1 Test Thread 1 ISSUE" |
| typography | font-family | `Outfit, sans-serif` | 36 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-size | `16px` | 13 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-size | `14px` | 12 | button aria-label=Read text="Read"; button aria-label=Edit text="Edit"; button aria-label=Snooze text="😴 Snooze" |
| typography | font-size | `18px` | 6 | button aria-label=Drag to reorder text="⠿"; button aria-label=Thread actions text="⋮" |
| typography | font-size | `10px` | 4 | button text="SHUFFLE"; button text="POS"; button text="A-Z" |
| typography | font-size | `30px` | 1 | button aria-label=Add Thread text="+" |
| typography | font-weight | `400` | 19 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-weight | `600` | 6 | button aria-label=Edit text="Edit"; button aria-label=Snooze text="😴 Snooze" |
| typography | font-weight | `900` | 5 | button text="SHUFFLE"; button text="POS"; button text="A-Z" |
| typography | font-weight | `700` | 3 | button aria-label=Read text="Read" |
| typography | font-weight | `500` | 3 | button aria-label=Delete text="Delete" |
| typography | letter-spacing | `normal` | 32 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | letter-spacing | `1px` | 4 | button text="SHUFFLE"; button text="POS"; button text="A-Z" |
| typography | line-height | `24px` | 12 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | line-height | `20px` | 12 | button aria-label=Read text="Read"; button aria-label=Edit text="Edit"; button aria-label=Snooze text="😴 Snooze" |
| typography | line-height | `28px` | 6 | button aria-label=Drag to reorder text="⠿"; button aria-label=Thread actions text="⋮" |
| typography | line-height | `15px` | 4 | button text="SHUFFLE"; button text="POS"; button text="A-Z" |
| typography | line-height | `21.3333px` | 1 | input |
| typography | line-height | `36px` | 1 | button aria-label=Add Thread text="+" |

### history at phone

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 9 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=Crossovers page text="CROSSOVERS" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE" |
| colors | background-color | `rgba(212, 137, 14, 0.12)` | 1 | a aria-label=History page text="HISTORY" |
| colors | border-color | `rgb(160, 147, 126)` | 4 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=Crossovers page text="CROSSOVERS" |
| colors | border-color | `rgb(232, 213, 176)` | 4 | a aria-label=History page text="HISTORY"; main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| colors | border-color | `rgba(255, 255, 255, 0.08) rgb(232, 213, 176) rgb(232, 213, 176)` | 1 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE" |
| colors | border-color | `oklch(0.553 0.013 58.071)` | 1 | a text="EXPORT SUMMARY" |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 1 | a text="VIEW FULL SESSION →" |
| colors | color | `rgb(232, 213, 176)` | 5 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=History page text="HISTORY"; main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| colors | color | `rgb(160, 147, 126)` | 4 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=Crossovers page text="CROSSOVERS" |
| colors | color | `oklch(0.553 0.013 58.071)` | 1 | a text="EXPORT SUMMARY" |
| colors | color | `oklch(0.709 0.01 56.259)` | 1 | a text="VIEW FULL SESSION →" |
| controls | border-width | `0px` | 7 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | height | `56px` | 5 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | height | `23px` | 1 | a text="EXPORT SUMMARY" |
| controls | height | `15px` | 1 | a text="VIEW FULL SESSION →" |
| controls | min-height | `auto` | 6 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | min-height | `0px` | 1 | a text="VIEW FULL SESSION →" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| panels | border-radius | `0px` | 2 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| panels | box-shadow | `none` | 2 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| radii | border-radius | `0px` | 11 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| shadows | box-shadow | `none` | 11 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | gap | `normal` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | gap | `12px` | 1 | header text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY" |
| spacing | gap | `4px` | 1 | a text="VIEW FULL SESSION →" |
| spacing | margin-bottom | `0px` | 10 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | margin-bottom | `24px` | 1 | header text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY" |
| spacing | margin-top | `0px` | 11 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-bottom | `0px` | 8 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-bottom | `80px` | 2 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| spacing | padding-bottom | `4px` | 1 | a text="EXPORT SUMMARY" |
| spacing | padding-left | `0px` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-left | `12px` | 1 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| spacing | padding-left | `8px` | 1 | header text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY" |
| spacing | padding-right | `0px` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-right | `12px` | 1 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| spacing | padding-right | `8px` | 1 | header text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY" |
| spacing | padding-top | `0px` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-top | `16px` | 1 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| spacing | padding-top | `4px` | 1 | a text="EXPORT SUMMARY" |
| typography | font-family | `Outfit, sans-serif` | 11 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-size | `16px` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-size | `10px` | 2 | a text="EXPORT SUMMARY"; a text="VIEW FULL SESSION →" |
| typography | font-weight | `400` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-weight | `700` | 1 | a text="EXPORT SUMMARY" |
| typography | font-weight | `900` | 1 | a text="VIEW FULL SESSION →" |
| typography | letter-spacing | `normal` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | letter-spacing | `1px` | 2 | a text="EXPORT SUMMARY"; a text="VIEW FULL SESSION →" |
| typography | line-height | `24px` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | line-height | `15px` | 2 | a text="EXPORT SUMMARY"; a text="VIEW FULL SESSION →" |

### crossovers at phone

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 8 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE" |
| colors | background-color | `rgba(212, 137, 14, 0.12)` | 1 | a aria-label=Crossovers page text="CROSSOVERS" |
| colors | background-color | `oklch(0.147 0.004 49.25)` | 1 | input |
| colors | background-color | `oklch(0.769 0.188 70.08)` | 1 | button text="Create crossover" |
| colors | border-color | `rgb(160, 147, 126)` | 4 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| colors | border-color | `rgb(232, 213, 176)` | 4 | a aria-label=Crossovers page text="CROSSOVERS"; main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| colors | border-color | `rgba(255, 255, 255, 0.08) rgb(232, 213, 176) rgb(232, 213, 176)` | 1 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 1 | a text="What is a crossover?" |
| colors | border-color | `oklch(0.444 0.011 73.639)` | 1 | input |
| colors | border-color | `oklch(0.147 0.004 49.25)` | 1 | button text="Create crossover" |
| colors | color | `rgb(232, 213, 176)` | 5 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Crossovers page text="CROSSOVERS"; main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| colors | color | `rgb(160, 147, 126)` | 4 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| colors | color | `oklch(0.828 0.189 84.429)` | 1 | a text="What is a crossover?" |
| colors | color | `oklch(0.97 0.001 106.424)` | 1 | input |
| colors | color | `oklch(0.147 0.004 49.25)` | 1 | button text="Create crossover" |
| controls | border-width | `0px` | 7 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | border-width | `1px` | 1 | input |
| controls | height | `56px` | 5 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | height | `auto` | 1 | a text="What is a crossover?" |
| controls | height | `46px` | 1 | input |
| controls | height | `44px` | 1 | button text="Create crossover" |
| controls | min-height | `auto` | 7 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | min-height | `0px` | 1 | a text="What is a crossover?" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| panels | border-radius | `0px` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| panels | box-shadow | `none` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| radii | border-radius | `0px` | 10 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| radii | border-radius | `12px` | 2 | input; button text="Create crossover" |
| shadows | box-shadow | `none` | 12 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | gap | `normal` | 12 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | margin-bottom | `0px` | 11 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | margin-bottom | `24px` | 1 | header text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | margin-top | `0px` | 12 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-bottom | `0px` | 8 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-bottom | `10px` | 2 | input; button text="Create crossover" |
| spacing | padding-bottom | `80px` | 1 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | padding-bottom | `112px` | 1 | section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | padding-left | `0px` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-left | `12px` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; input |
| spacing | padding-left | `16px` | 1 | button text="Create crossover" |
| spacing | padding-right | `0px` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-right | `12px` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; input |
| spacing | padding-right | `16px` | 1 | button text="Create crossover" |
| spacing | padding-top | `0px` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-top | `10px` | 2 | input; button text="Create crossover" |
| spacing | padding-top | `16px` | 1 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| typography | font-family | `Outfit, sans-serif` | 12 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-size | `16px` | 11 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-size | `14px` | 1 | a text="What is a crossover?" |
| typography | font-weight | `400` | 10 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-weight | `700` | 2 | a text="What is a crossover?"; button text="Create crossover" |
| typography | letter-spacing | `normal` | 12 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | line-height | `24px` | 11 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | line-height | `20px` | 1 | a text="What is a crossover?" |

### continuity-plans at phone

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 7 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE" |
| colors | background-color | `rgba(212, 137, 14, 0.12)` | 1 | button aria-label=More pages text="MORE" |
| colors | background-color | `oklch(0.769 0.188 70.08)` | 1 | button text="Create a plan" |
| colors | border-color | `rgb(160, 147, 126)` | 4 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| colors | border-color | `rgb(232, 213, 176)` | 4 | button aria-label=More pages text="MORE"; main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| colors | border-color | `rgba(255, 255, 255, 0.08) rgb(232, 213, 176) rgb(232, 213, 176)` | 1 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE" |
| colors | border-color | `oklch(0.147 0.004 49.25)` | 1 | button text="Create a plan" |
| colors | color | `rgb(232, 213, 176)` | 5 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; button aria-label=More pages text="MORE"; main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| colors | color | `rgb(160, 147, 126)` | 4 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| colors | color | `oklch(0.147 0.004 49.25)` | 1 | button text="Create a plan" |
| controls | border-width | `0px` | 6 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | height | `56px` | 5 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | height | `44px` | 1 | button text="Create a plan" |
| controls | min-height | `auto` | 5 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | min-height | `44px` | 1 | button text="Create a plan" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| panels | border-radius | `0px` | 2 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| panels | box-shadow | `none` | 2 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| radii | border-radius | `0px` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| radii | border-radius | `12px` | 1 | button text="Create a plan" |
| shadows | box-shadow | `none` | 10 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | gap | `normal` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | gap | `12px` | 1 | header text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | margin-bottom | `0px` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | margin-bottom | `20px` | 1 | header text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | margin-top | `0px` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | margin-top | `16px` | 1 | button text="Create a plan" |
| spacing | padding-bottom | `0px` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-bottom | `80px` | 1 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-left | `0px` | 8 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-left | `12px` | 1 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-left | `20px` | 1 | button text="Create a plan" |
| spacing | padding-right | `0px` | 8 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-right | `12px` | 1 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-right | `20px` | 1 | button text="Create a plan" |
| spacing | padding-top | `0px` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-top | `16px` | 1 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| typography | font-family | `Outfit, sans-serif` | 10 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-size | `16px` | 10 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-weight | `400` | 9 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-weight | `900` | 1 | button text="Create a plan" |
| typography | letter-spacing | `normal` | 10 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | line-height | `24px` | 10 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |

### continuity-planner at phone

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 17 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| colors | background-color | `rgba(255, 255, 255, 0.04)` | 5 | input; button text="Add issue"; select text="Select a crossover" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 2 | input; select text="No issues available" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE" |
| colors | background-color | `rgba(212, 137, 14, 0.12)` | 1 | button aria-label=More pages text="MORE" |
| colors | background-color | `rgb(212, 137, 14)` | 1 | button text="Save plan" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 11 | input; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc"; button text="Add issue" |
| colors | border-color | `rgb(160, 147, 126)` | 5 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| colors | border-color | `rgb(232, 213, 176)` | 4 | button aria-label=More pages text="MORE"; main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 3 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.2)` | 2 | input; select text="No issues available" |
| colors | border-color | `rgba(255, 255, 255, 0.08) rgb(232, 213, 176) rgb(232, 213, 176)` | 1 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE" |
| colors | border-color | `oklch(0.147 0.004 49.25)` | 1 | button text="Save plan" |
| colors | color | `rgb(232, 213, 176)` | 12 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; button aria-label=More pages text="MORE"; main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| colors | color | `rgb(160, 147, 126)` | 9 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| colors | color | `oklch(0.828 0.189 84.429)` | 3 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| colors | color | `oklch(0.869 0.005 56.366)` | 2 | input; select text="No issues available" |
| colors | color | `oklch(0.147 0.004 49.25)` | 1 | button text="Save plan" |
| controls | border-width | `1px` | 11 | input; select text="No issues available"; button text="Add issue" |
| controls | border-width | `0px` | 10 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | height | `44px` | 6 | button text="Add issue"; select text="Select a crossover"; button text="Add crossover" |
| controls | height | `56px` | 5 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | height | `auto` | 3 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| controls | height | `36px` | 3 | button aria-label=Move lane Reading order earlier text="↑"; button aria-label=Move lane Reading order later text="↓"; button aria-label=Remove lane Reading order text="Remove" |
| controls | height | `40.8438px` | 2 | input; input aria-label=Lane Reading order name |
| controls | height | `47.3281px` | 1 | input |
| controls | height | `40px` | 1 | select text="No issues available" |
| controls | min-height | `auto` | 6 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | min-height | `0px` | 6 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| controls | min-height | `44px` | 6 | button text="Add issue"; select text="Select a crossover"; button text="Add crossover" |
| controls | min-height | `36px` | 3 | button aria-label=Move lane Reading order earlier text="↑"; button aria-label=Move lane Reading order later text="↓"; button aria-label=Remove lane Reading order text="Remove" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 4 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| panels | border-color | `rgba(255, 255, 255, 0.08)` | 2 | section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc"; section text="READING LANES 1 lane · 0 steps Add lane ↑ ↓ Remove No steps in this lane yet." |
| panels | border-radius | `0px` | 4 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc" |
| panels | box-shadow | `none` | 4 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc" |
| radii | border-radius | `0px` | 14 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| radii | border-radius | `12px` | 10 | input; select text="No issues available"; button text="Add issue" |
| radii | border-radius | `8px` | 3 | button aria-label=Move lane Reading order earlier text="↑"; button aria-label=Move lane Reading order later text="↓"; button aria-label=Remove lane Reading order text="Remove" |
| shadows | box-shadow | `none` | 27 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | gap | `normal` | 27 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | margin-bottom | `0px` | 24 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | margin-bottom | `24px` | 3 | header text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc"; section text="READING LANES 1 lane · 0 steps Add lane ↑ ↓ Remove No steps in this lane yet." |
| spacing | margin-top | `0px` | 23 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | margin-top | `4px` | 4 | input; select text="No issues available"; select text="Select a crossover" |
| spacing | padding-bottom | `0px` | 21 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-bottom | `8px` | 3 | input; select text="No issues available"; input aria-label=Lane Reading order name |
| spacing | padding-bottom | `80px` | 1 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-bottom | `32px` | 1 | section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-bottom | `12px` | 1 | input |
| spacing | padding-left | `0px` | 15 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-left | `12px` | 8 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; input; select text="No issues available" |
| spacing | padding-left | `16px` | 2 | button text="Add issue"; button text="Add crossover" |
| spacing | padding-left | `20px` | 1 | button text="Cancel changes" |
| spacing | padding-left | `32px` | 1 | button text="Save plan" |
| spacing | padding-right | `0px` | 15 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-right | `12px` | 8 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; input; select text="No issues available" |
| spacing | padding-right | `16px` | 2 | button text="Add issue"; button text="Add crossover" |
| spacing | padding-right | `20px` | 1 | button text="Cancel changes" |
| spacing | padding-right | `32px` | 1 | button text="Save plan" |
| spacing | padding-top | `0px` | 20 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-top | `8px` | 3 | input; select text="No issues available"; input aria-label=Lane Reading order name |
| spacing | padding-top | `20px` | 2 | section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc"; section text="READING LANES 1 lane · 0 steps Add lane ↑ ↓ Remove No steps in this lane yet." |
| spacing | padding-top | `16px` | 1 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-top | `12px` | 1 | input |
| typography | font-family | `Outfit, sans-serif` | 27 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-size | `16px` | 21 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-size | `14px` | 5 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| typography | font-size | `12px` | 1 | button aria-label=Remove lane Reading order text="Remove" |
| typography | font-weight | `400` | 13 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-weight | `700` | 13 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| typography | font-weight | `900` | 1 | button text="Save plan" |
| typography | letter-spacing | `normal` | 23 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | letter-spacing | `1.2px` | 2 | input; select text="Select a crossover" |
| typography | letter-spacing | `1px` | 2 | input; select text="No issues available" |
| typography | line-height | `24px` | 16 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | line-height | `20px` | 5 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| typography | line-height | `22.8571px` | 2 | input; input aria-label=Lane Reading order name |
| typography | line-height | `normal` | 2 | select text="No issues available"; select text="Select a crossover" |
| typography | line-height | `21.3333px` | 1 | input |
| typography | line-height | `16px` | 1 | button aria-label=Remove lane Reading order text="Remove" |

### manual-picker-dialog at phone

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 10 | a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY"; a aria-label=Crossovers page text="CROSSOVERS" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 5 | button text="SHUFFLE QUEUE"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE" |
| colors | background-color | `rgba(212, 137, 14, 0.12)` | 1 | a aria-label=Roll page text="ROLL" |
| colors | background-color | `rgba(255, 255, 255, 0.04)` | 1 | button aria-label=Current die d4, automatic mode text="d4 AUTO" |
| colors | background-color | `rgb(212, 137, 14)` | 1 | button text="PICK MANUALLY" |
| colors | background-color | `rgba(17, 14, 10, 0.95)` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| colors | border-color | `rgb(232, 213, 176)` | 6 | a aria-label=Roll page text="ROLL"; main text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only"; div text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only" |
| colors | border-color | `rgb(160, 147, 126)` | 4 | a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY"; a aria-label=Crossovers page text="CROSSOVERS" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 2 | button aria-label=Current die d4, automatic mode text="d4 AUTO"; div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| colors | border-color | `rgba(255, 255, 255, 0.08) rgb(232, 213, 176) rgb(232, 213, 176)` | 1 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE" |
| colors | border-color | `oklch(0.216 0.006 56.043)` | 1 | button text="PICK MANUALLY" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 1 | button text="SHUFFLE QUEUE" |
| colors | border-color | `oklch(0.553 0.013 58.071)` | 1 | button aria-label=Close modal text="×" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 1 | select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| colors | color | `rgb(232, 213, 176)` | 11 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; main text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only" |
| colors | color | `rgb(160, 147, 126)` | 4 | a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY"; a aria-label=Crossovers page text="CROSSOVERS" |
| colors | color | `oklch(0.869 0.005 56.366)` | 2 | button text="SHUFFLE QUEUE"; select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| colors | color | `rgb(212, 137, 14)` | 1 | button aria-label=Current die d4, automatic mode text="d4 AUTO" |
| colors | color | `oklch(0.216 0.006 56.043)` | 1 | button text="PICK MANUALLY" |
| colors | color | `oklch(0.553 0.013 58.071)` | 1 | button aria-label=Close modal text="×" |
| controls | border-width | `0px` | 9 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | border-width | `1px` | 6 | button aria-label=Current die d4, automatic mode text="d4 AUTO"; button text="SHUFFLE QUEUE"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE" |
| controls | height | `56px` | 5 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | height | `79px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| controls | height | `44px` | 2 | button aria-label=Current die d4, automatic mode text="d4 AUTO"; button text="PICK MANUALLY" |
| controls | height | `40px` | 2 | select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is"; button text="PICK THIS THREAD" |
| controls | height | `200px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| controls | height | `32px` | 1 | button text="SHUFFLE QUEUE" |
| controls | height | `24px` | 1 | button aria-label=Close modal text="×" |
| controls | min-height | `auto` | 8 | a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE"; a aria-label=History page text="HISTORY" |
| controls | min-height | `0px` | 5 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| controls | min-height | `44px` | 2 | button aria-label=Current die d4, automatic mode text="d4 AUTO"; button text="PICK MANUALLY" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only"; div text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only" |
| panels | background-color | `rgba(17, 14, 10, 0.95)` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only"; div text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only" |
| panels | border-color | `rgba(255, 255, 255, 0.08)` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| panels | border-radius | `0px` | 2 | main text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only"; div text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only" |
| panels | border-radius | `8px` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| panels | box-shadow | `none` | 2 | main text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only"; div text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only" |
| panels | box-shadow | `rgba(0, 0, 0, 0.3) 0px 20px 25px -5px, rgba(0, 0, 0, 0.2) 0px 10px 10px -5px` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| radii | border-radius | `0px` | 10 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| radii | border-radius | `12px` | 5 | button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| radii | border-radius | `8px` | 3 | button aria-label=Current die d4, automatic mode text="d4 AUTO"; button text="SHUFFLE QUEUE"; div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| radii | border-radius | `3.35544e+07px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| radii | border-radius | `24px` | 1 | button text="PICK THIS THREAD" |
| shadows | box-shadow | `none` | 18 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| shadows | box-shadow | `rgba(0, 0, 0, 0.3) 0px 20px 25px -5px, rgba(0, 0, 0, 0.2) 0px 10px 10px -5px` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, oklab(0.769 0.0640531 0.176752 / 0.3) 0px 0px 0px 2px, rgba(0, 0, 0, 0) 0px 0px 0px 0px` | 1 | select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| spacing | gap | `normal` | 16 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | gap | `12px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | gap | `8px 12px` | 1 | header text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY" |
| spacing | margin-bottom | `0px` | 18 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | margin-bottom | `8px` | 2 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| spacing | margin-top | `0px` | 19 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | margin-top | `16px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| spacing | padding-bottom | `0px` | 11 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-bottom | `12px` | 4 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-bottom | `8px` | 2 | header text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY"; select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| spacing | padding-bottom | `80px` | 1 | main text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only" |
| spacing | padding-bottom | `4px` | 1 | button aria-label=Current die d4, automatic mode text="d4 AUTO" |
| spacing | padding-bottom | `6px` | 1 | button text="PICK MANUALLY" |
| spacing | padding-left | `0px` | 11 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-left | `12px` | 5 | main text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only"; button aria-label=Current die d4, automatic mode text="d4 AUTO"; button text="PICK MANUALLY" |
| spacing | padding-left | `16px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-left | `8px` | 1 | header text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY" |
| spacing | padding-right | `0px` | 11 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-right | `12px` | 5 | main text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only"; button aria-label=Current die d4, automatic mode text="d4 AUTO"; button text="PICK MANUALLY" |
| spacing | padding-right | `16px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-right | `8px` | 1 | header text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY" |
| spacing | padding-top | `0px` | 11 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| spacing | padding-top | `12px` | 4 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-top | `8px` | 2 | header text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY"; select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| spacing | padding-top | `16px` | 1 | main text="PILE ROLLER d4 AUTO BALANCED PICK MANUALLY TAP DIE TO ROLL ELIGIBLE NOW · 3 Only" |
| spacing | padding-top | `4px` | 1 | button aria-label=Current die d4, automatic mode text="d4 AUTO" |
| spacing | padding-top | `6px` | 1 | button text="PICK MANUALLY" |
| typography | font-family | `Outfit, sans-serif` | 20 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-size | `16px` | 16 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-size | `10px` | 2 | button text="PICK MANUALLY"; button text="SHUFFLE QUEUE" |
| typography | font-size | `24px` | 1 | button aria-label=Close modal text="×" |
| typography | font-size | `12px` | 1 | button text="PICK THIS THREAD" |
| typography | font-weight | `400` | 17 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | font-weight | `900` | 3 | button text="PICK MANUALLY"; button text="SHUFFLE QUEUE"; button text="PICK THIS THREAD" |
| typography | letter-spacing | `normal` | 17 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | letter-spacing | `1px` | 2 | button text="PICK MANUALLY"; button text="SHUFFLE QUEUE" |
| typography | letter-spacing | `1.8px` | 1 | button text="PICK THIS THREAD" |
| typography | line-height | `24px` | 16 | nav role=navigation aria-label=Mobile navigation text="ROLL QUEUE HISTORY CROSSOVERS MORE"; a aria-label=Roll page text="ROLL"; a aria-label=Queue page text="QUEUE" |
| typography | line-height | `15px` | 2 | button text="PICK MANUALLY"; button text="SHUFFLE QUEUE" |
| typography | line-height | `normal` | 1 | select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| typography | line-height | `16px` | 1 | button text="PICK THIS THREAD" |

### roll at tablet

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 22 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 4 | button text="SHUFFLE QUEUE"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=Roll page text="Roll"; button text="Classic" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklab(0.691008 0.049379 0.13801 / 0.15)` | 1 | button text="d6" |
| colors | background-color | `rgb(212, 137, 14)` | 1 | button text="PICK MANUALLY" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 16 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | border-color | `rgb(232, 213, 176)` | 5 | button text="Classic"; main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Roll page text="Roll"; a text="LADDER" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `rgb(212, 137, 14)` | 1 | button text="d6" |
| colors | border-color | `oklch(0.216 0.006 56.043)` | 1 | button text="PICK MANUALLY" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 1 | button text="SHUFFLE QUEUE" |
| colors | color | `oklch(0.709 0.01 56.259)` | 16 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | color | `rgb(232, 213, 176)` | 9 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| colors | color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Roll page text="Roll"; a text="LADDER" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `rgb(212, 137, 14)` | 1 | button text="d6" |
| colors | color | `oklch(0.216 0.006 56.043)` | 1 | button text="PICK MANUALLY" |
| colors | color | `oklch(0.869 0.005 56.366)` | 1 | button text="SHUFFLE QUEUE" |
| controls | border-width | `0px` | 25 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | border-width | `1px` | 4 | button text="SHUFFLE QUEUE"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| controls | height | `44px` | 11 | button text="d4"; button text="d6"; button text="d8" |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `24px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `79px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| controls | height | `32px` | 2 | button text="SHUFFLE QUEUE"; button aria-label=Send feedback |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `200px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| controls | min-height | `auto` | 13 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `44px` | 11 | button text="d4"; button text="d6"; button text="d8" |
| controls | min-height | `0px` | 5 | button aria-label=Log out text="LOG OUT"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| panels | border-radius | `0px` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| panels | box-shadow | `none` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| radii | border-radius | `8px` | 19 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| radii | border-radius | `12px` | 4 | button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `3.35544e+07px` | 2 | div role=button aria-label=Roll the dice data-testid=main-die-3d; button aria-label=Send feedback |
| shadows | box-shadow | `none` | 31 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(212, 137, 14, 0.243) 0px 0px 38.7531px 0px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 22 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | gap | `8px 12px` | 1 | header text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| spacing | margin-bottom | `0px` | 31 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `8px` | 2 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| spacing | margin-top | `0px` | 31 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | margin-top | `32px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| spacing | padding-bottom | `0px` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; button text="d4" |
| spacing | padding-bottom | `8px` | 9 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `12px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| spacing | padding-left | `8px` | 13 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `12px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; a text="LADDER" |
| spacing | padding-left | `16px` | 5 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE" |
| spacing | padding-right | `8px` | 13 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `12px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; a text="LADDER" |
| spacing | padding-right | `16px` | 5 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE" |
| spacing | padding-top | `0px` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; button text="d4" |
| spacing | padding-top | `8px` | 9 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `12px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| typography | font-family | `Outfit, sans-serif` | 33 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `10px` | 12 | button text="d4"; button text="d6"; button text="d8" |
| typography | font-size | `12px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `400` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `900` | 12 | button text="d4"; button text="d6"; button text="d8" |
| typography | font-weight | `700` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | letter-spacing | `normal` | 29 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1px` | 2 | button text="PICK MANUALLY"; button text="SHUFFLE QUEUE" |
| typography | letter-spacing | `1.2px` | 1 | button aria-label=Log out text="LOG OUT" |
| typography | letter-spacing | `0.25px` | 1 | button text="AUTO" |
| typography | line-height | `24px` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `15px` | 12 | button text="d4"; button text="d6"; button text="d8" |
| typography | line-height | `16px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |

### roll-rating at tablet

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 15 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=Roll page text="Roll"; button text="Classic" |
| colors | background-color | `rgba(255, 255, 255, 0.05)` | 2 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #" |
| colors | background-color | `rgba(255, 255, 255, 0.04)` | 2 | section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 2 | button text="SNOOZE"; button aria-label=Skip current roll data-testid=skip-roll text="SKIP" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklch(0.769 0.188 70.08)` | 1 | button text="FIND COMICVINE MATCH" |
| colors | background-color | `rgba(6, 182, 212, 0.09)` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| colors | background-color | `oklab(0.666 0.0940116 0.152325 / 0.25)` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| colors | background-color | `oklab(0.586 0.241177 0.0764364 / 0.1)` | 1 | button text="CANCEL ROLL" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | border-color | `rgb(232, 213, 176)` | 6 | button text="Classic"; main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 2 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="ROLL RESULT Rolled 0 on d6 SERIES PROGRESS" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Roll page text="Roll"; a text="d6 → d4" |
| colors | border-color | `rgba(255, 255, 255, 0.1)` | 2 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | button text="SNOOZE"; button aria-label=Skip current roll data-testid=skip-roll text="SKIP" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `oklch(0.216 0.006 56.043)` | 1 | button text="FIND COMICVINE MATCH" |
| colors | border-color | `rgba(6, 182, 212, 0.3)` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| colors | border-color | `rgba(168, 85, 247, 0.15)` | 1 | section text="SERIES HISTORY Canonical series history unavailable" |
| colors | border-color | `rgba(168, 85, 247, 0.2)` | 1 | section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| colors | border-color | `oklab(0.666 0.0940116 0.152325 / 0.5)` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| colors | border-color | `oklab(0.586 0.241177 0.0764364 / 0.3)` | 1 | button text="CANCEL ROLL" |
| colors | color | `rgb(232, 213, 176)` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss" |
| colors | color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | color | `oklch(0.869 0.005 56.366)` | 4 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="SNOOZE" |
| colors | color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Roll page text="Roll"; a text="d6 → d4" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `oklch(0.216 0.006 56.043)` | 1 | button text="FIND COMICVINE MATCH" |
| colors | color | `oklch(0.712 0.194 13.428)` | 1 | button text="CANCEL ROLL" |
| controls | border-width | `0px` | 15 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | border-width | `1px` | 6 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button data-testid=save-and-continue text="MARK READ & SAVE" |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `24px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `58px` | 3 | button text="SNOOZE"; button aria-label=Skip current roll data-testid=skip-roll text="SKIP"; button text="CANCEL ROLL" |
| controls | height | `44px` | 2 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #" |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `36px` | 1 | button text="FIND COMICVINE MATCH" |
| controls | height | `auto` | 1 | a text="d6 → d4" |
| controls | height | `16px` | 1 | input aria-label=Rating from 0.5 to 5.0 in steps of 0.5 |
| controls | height | `46px` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| controls | height | `32px` | 1 | button aria-label=Send feedback |
| controls | min-height | `auto` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `0px` | 5 | button aria-label=Log out text="LOG OUT"; a text="d6 → d4"; input aria-label=Rating from 0.5 to 5.0 in steps of 0.5 |
| controls | min-height | `44px` | 5 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="SNOOZE" |
| controls | min-height | `36px` | 1 | button text="FIND COMICVINE MATCH" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 4 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| panels | background-color | `rgba(255, 255, 255, 0.04)` | 2 | section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| panels | background-color | `rgba(6, 182, 212, 0.09)` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| panels | border-color | `rgb(232, 213, 176)` | 3 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| panels | border-color | `rgba(6, 182, 212, 0.3)` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| panels | border-color | `rgba(255, 255, 255, 0.08)` | 1 | section text="ROLL RESULT Rolled 0 on d6 SERIES PROGRESS" |
| panels | border-color | `rgba(168, 85, 247, 0.15)` | 1 | section text="SERIES HISTORY Canonical series history unavailable" |
| panels | border-color | `rgba(168, 85, 247, 0.2)` | 1 | section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| panels | border-radius | `0px` | 4 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| panels | border-radius | `16px` | 3 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis"; section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| panels | box-shadow | `none` | 7 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| radii | border-radius | `8px` | 9 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 8 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss" |
| radii | border-radius | `12px` | 6 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button data-testid=save-and-continue text="MARK READ & SAVE" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `16px` | 3 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis"; section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `none` | 29 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 21 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | gap | `8px 12px` | 1 | header text="PILE ROLLER" |
| spacing | gap | `12px 24px` | 1 | section text="ROLL RESULT Rolled 0 on d6 SERIES PROGRESS" |
| spacing | margin-bottom | `0px` | 25 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `16px` | 3 | section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl"; section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis"; section text="SERIES HISTORY Canonical series history unavailable" |
| spacing | margin-bottom | `12px` | 1 | input aria-label=Rating from 0.5 to 5.0 in steps of 0.5 |
| spacing | margin-bottom | `8px` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| spacing | margin-top | `0px` | 29 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `0px` | 9 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| spacing | padding-bottom | `8px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `12px` | 6 | section text="ROLL RESULT Rolled 0 on d6 SERIES PROGRESS"; section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss" |
| spacing | padding-bottom | `16px` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| spacing | padding-bottom | `14px` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| spacing | padding-left | `12px` | 14 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 11 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| spacing | padding-left | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `16px` | 2 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| spacing | padding-right | `12px` | 14 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 11 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| spacing | padding-right | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `16px` | 2 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| spacing | padding-top | `0px` | 10 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| spacing | padding-top | `8px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `12px` | 5 | section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of"; button text="SNOOZE" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss" |
| spacing | padding-top | `16px` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| spacing | padding-top | `14px` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| typography | font-family | `Outfit, sans-serif` | 30 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `12px` | 8 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-size | `10px` | 3 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="FIND COMICVINE MATCH" |
| typography | font-size | `14px` | 1 | a text="d6 → d4" |
| typography | font-weight | `400` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `900` | 7 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="FIND COMICVINE MATCH" |
| typography | font-weight | `700` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | letter-spacing | `normal` | 22 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1.8px` | 4 | button data-testid=save-and-continue text="MARK READ & SAVE"; button text="SNOOZE"; button aria-label=Skip current roll data-testid=skip-roll text="SKIP" |
| typography | letter-spacing | `0.5px` | 3 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="FIND COMICVINE MATCH" |
| typography | letter-spacing | `1.2px` | 1 | button aria-label=Log out text="LOG OUT" |
| typography | line-height | `24px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `16px` | 8 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | line-height | `15px` | 3 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="FIND COMICVINE MATCH" |
| typography | line-height | `20px` | 1 | a text="d6 → d4" |

### queue at tablet

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 24 | a aria-label=Roll page text="Roll"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 10 | button text="SHUFFLE"; button text="A-Z"; button text="NEW" |
| colors | background-color | `rgb(212, 137, 14)` | 3 | button aria-label=Read text="Read" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=Queue page text="Queue"; button text="Classic" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklab(0.666 0.0940116 0.152325 / 0.2)` | 1 | button text="POS" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `rgb(232, 213, 176)` | 8 | button text="Classic"; main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Roll page text="Roll"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | border-color | `rgb(107, 95, 80)` | 6 | button aria-label=Drag to reorder text="⠿"; button aria-label=Delete text="Delete" |
| colors | border-color | `rgb(160, 147, 126)` | 6 | button aria-label=Edit text="Edit"; button aria-label=Snooze text="😴 Snooze" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 4 | button text="SHUFFLE"; button text="A-Z"; button text="NEW" |
| colors | border-color | `rgb(255, 255, 255)` | 3 | button aria-label=Read text="Read" |
| colors | border-color | `oklch(0.553 0.013 58.071)` | 3 | button aria-label=Thread actions text="⋮" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 1 | a aria-label=Queue page text="Queue" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `oklab(0.769 0.0640531 0.176752 / 0.3)` | 1 | button text="POS" |
| colors | color | `rgb(232, 213, 176)` | 9 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| colors | color | `oklch(0.709 0.01 56.259)` | 9 | a aria-label=Roll page text="Roll"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | color | `rgb(107, 95, 80)` | 6 | button aria-label=Drag to reorder text="⠿"; button aria-label=Delete text="Delete" |
| colors | color | `rgb(160, 147, 126)` | 6 | button aria-label=Edit text="Edit"; button aria-label=Snooze text="😴 Snooze" |
| colors | color | `rgb(255, 255, 255)` | 3 | button aria-label=Read text="Read" |
| colors | color | `oklch(0.553 0.013 58.071)` | 3 | button aria-label=Thread actions text="⋮" |
| colors | color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Queue page text="Queue"; button text="POS" |
| colors | color | `oklch(0.869 0.005 56.366)` | 2 | button text="SHUFFLE"; input |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | border-width | `0px` | 34 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | border-width | `1px` | 5 | button text="SHUFFLE"; button text="POS"; button text="A-Z" |
| controls | height | `36px` | 13 | input; button aria-label=Read text="Read"; button aria-label=Edit text="Edit" |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `32px` | 4 | button aria-label=Drag to reorder text="⠿"; button aria-label=Send feedback |
| controls | height | `24px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `29px` | 3 | button text="POS"; button text="A-Z"; button text="NEW" |
| controls | height | `140px` | 3 | button aria-label=Open Test Thread 1 text="Test Thread 1"; button aria-label=Open Test Thread 2 text="Test Thread 2"; button aria-label=Open Test Thread 3 text="Test Thread 3" |
| controls | height | `44px` | 3 | button aria-label=Thread actions text="⋮" |
| controls | height | `48px` | 2 | button text="SHUFFLE"; button data-testid=queue-add-thread-desktop text="ADD THREAD" |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | min-height | `auto` | 34 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `0px` | 5 | button aria-label=Log out text="LOG OUT"; button aria-label=Thread actions text="⋮"; button aria-label=Send feedback |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| panels | border-radius | `0px` | 2 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| panels | box-shadow | `none` | 2 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| radii | border-radius | `8px` | 31 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 7 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `24px` | 1 | button data-testid=queue-add-thread-desktop text="ADD THREAD" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `none` | 41 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 20px 25px -5px, rgba(0, 0, 0, 0.1) 0px 8px 10px -6px` | 1 | button data-testid=queue-add-thread-desktop text="ADD THREAD" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 33 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | gap | `6px` | 3 | button aria-label=Snooze text="😴 Snooze" |
| spacing | margin-bottom | `0px` | 42 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `40px` | 1 | header text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3" |
| spacing | margin-top | `0px` | 42 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `0px` | 27 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; header text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3"; button text="SHUFFLE" |
| spacing | padding-bottom | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `6px` | 4 | button aria-label=Log out text="LOG OUT"; button text="POS"; button text="A-Z" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `24px` | 1 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| spacing | padding-bottom | `40px` | 1 | div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| spacing | padding-left | `12px` | 21 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; button aria-label=Drag to reorder text="⠿" |
| spacing | padding-left | `8px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `16px` | 4 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; button aria-label=Read text="Read" |
| spacing | padding-left | `20px` | 2 | button text="SHUFFLE"; button data-testid=queue-add-thread-desktop text="ADD THREAD" |
| spacing | padding-right | `12px` | 21 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; button aria-label=Drag to reorder text="⠿" |
| spacing | padding-right | `8px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `16px` | 4 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; button aria-label=Read text="Read" |
| spacing | padding-right | `20px` | 2 | button text="SHUFFLE"; button data-testid=queue-add-thread-desktop text="ADD THREAD" |
| spacing | padding-top | `0px` | 28 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; header text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3" |
| spacing | padding-top | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `6px` | 4 | button aria-label=Log out text="LOG OUT"; button text="POS"; button text="A-Z" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `24px` | 1 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| typography | font-family | `Outfit, sans-serif` | 43 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 15 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `14px` | 12 | button aria-label=Read text="Read"; button aria-label=Edit text="Edit"; button aria-label=Snooze text="😴 Snooze" |
| typography | font-size | `12px` | 7 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-size | `18px` | 6 | button aria-label=Drag to reorder text="⠿"; button aria-label=Thread actions text="⋮" |
| typography | font-size | `10px` | 3 | button text="POS"; button text="A-Z"; button text="NEW" |
| typography | font-weight | `400` | 22 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `700` | 7 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `600` | 6 | button aria-label=Edit text="Edit"; button aria-label=Snooze text="😴 Snooze" |
| typography | font-weight | `900` | 5 | button text="SHUFFLE"; button data-testid=queue-add-thread-desktop text="ADD THREAD"; button text="POS" |
| typography | font-weight | `500` | 3 | button aria-label=Delete text="Delete" |
| typography | letter-spacing | `normal` | 37 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1px` | 3 | button text="POS"; button text="A-Z"; button text="NEW" |
| typography | letter-spacing | `1.2px` | 2 | button aria-label=Log out text="LOG OUT"; button text="SHUFFLE" |
| typography | letter-spacing | `1.8px` | 1 | button data-testid=queue-add-thread-desktop text="ADD THREAD" |
| typography | line-height | `24px` | 15 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `20px` | 12 | button aria-label=Read text="Read"; button aria-label=Edit text="Edit"; button aria-label=Snooze text="😴 Snooze" |
| typography | line-height | `16px` | 7 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | line-height | `28px` | 6 | button aria-label=Drag to reorder text="⠿"; button aria-label=Thread actions text="⋮" |
| typography | line-height | `15px` | 3 | button text="POS"; button text="A-Z"; button text="NEW" |

### history at tablet

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 13 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=Crossovers page text="Crossovers" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=History page text="History"; button text="Classic" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=Crossovers page text="Crossovers" |
| colors | border-color | `rgb(232, 213, 176)` | 4 | button text="Classic"; main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 1 | a aria-label=History page text="History" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `oklch(0.553 0.013 58.071)` | 1 | a text="EXPORT SUMMARY" |
| colors | color | `oklch(0.709 0.01 56.259)` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=Crossovers page text="Crossovers" |
| colors | color | `rgb(232, 213, 176)` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| colors | color | `oklch(0.828 0.189 84.429)` | 1 | a aria-label=History page text="History" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `oklch(0.553 0.013 58.071)` | 1 | a text="EXPORT SUMMARY" |
| controls | border-width | `0px` | 14 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `24px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `23px` | 1 | a text="EXPORT SUMMARY" |
| controls | height | `15px` | 1 | a text="VIEW FULL SESSION →" |
| controls | height | `32px` | 1 | button aria-label=Send feedback |
| controls | min-height | `auto` | 11 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `0px` | 3 | button aria-label=Log out text="LOG OUT"; a text="VIEW FULL SESSION →"; button aria-label=Send feedback |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| panels | border-radius | `0px` | 2 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| panels | box-shadow | `none` | 2 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| radii | border-radius | `8px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 6 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `none` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 9 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | gap | `4px` | 1 | a text="VIEW FULL SESSION →" |
| spacing | margin-bottom | `0px` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `32px` | 1 | header text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY" |
| spacing | margin-top | `0px` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `0px` | 4 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; header text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY"; a text="VIEW FULL SESSION →" |
| spacing | padding-bottom | `4px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| spacing | padding-bottom | `80px` | 1 | div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| spacing | padding-left | `12px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; a text="EXPORT SUMMARY" |
| spacing | padding-left | `8px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `16px` | 1 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| spacing | padding-right | `12px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; a text="EXPORT SUMMARY" |
| spacing | padding-right | `8px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `16px` | 1 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| spacing | padding-top | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; header text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY" |
| spacing | padding-top | `4px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| typography | font-family | `Outfit, sans-serif` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `12px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-size | `10px` | 2 | a text="EXPORT SUMMARY"; a text="VIEW FULL SESSION →" |
| typography | font-weight | `400` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `700` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `900` | 1 | a text="VIEW FULL SESSION →" |
| typography | letter-spacing | `normal` | 15 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1px` | 2 | a text="EXPORT SUMMARY"; a text="VIEW FULL SESSION →" |
| typography | letter-spacing | `1.2px` | 1 | button aria-label=Log out text="LOG OUT" |
| typography | line-height | `24px` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `16px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | line-height | `15px` | 2 | a text="EXPORT SUMMARY"; a text="VIEW FULL SESSION →" |

### crossovers at tablet

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 12 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=Crossovers page text="Crossovers"; button text="Classic" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklch(0.147 0.004 49.25)` | 1 | input |
| colors | background-color | `oklch(0.769 0.188 70.08)` | 1 | button text="Create crossover" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | border-color | `rgb(232, 213, 176)` | 4 | button text="Classic"; main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Crossovers page text="Crossovers"; a text="What is a crossover?" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `oklch(0.444 0.011 73.639)` | 1 | input |
| colors | border-color | `oklch(0.147 0.004 49.25)` | 1 | button text="Create crossover" |
| colors | color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | color | `rgb(232, 213, 176)` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| colors | color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Crossovers page text="Crossovers"; a text="What is a crossover?" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `oklch(0.97 0.001 106.424)` | 1 | input |
| colors | color | `oklch(0.147 0.004 49.25)` | 1 | button text="Create crossover" |
| controls | border-width | `0px` | 14 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | border-width | `1px` | 1 | input |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `24px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `46px` | 2 | input; button text="Create crossover" |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `auto` | 1 | a text="What is a crossover?" |
| controls | height | `32px` | 1 | button aria-label=Send feedback |
| controls | min-height | `auto` | 12 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `0px` | 3 | button aria-label=Log out text="LOG OUT"; a text="What is a crossover?"; button aria-label=Send feedback |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| panels | border-radius | `0px` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| panels | box-shadow | `none` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| radii | border-radius | `8px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `12px` | 2 | input; button text="Create crossover" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `none` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | margin-bottom | `0px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `24px` | 1 | header text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | margin-top | `0px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `0px` | 4 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; header text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; a text="What is a crossover?" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `10px` | 2 | input; button text="Create crossover" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | padding-bottom | `112px` | 1 | section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | padding-left | `12px` | 9 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; header text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | padding-left | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `16px` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; button text="Create crossover" |
| spacing | padding-right | `12px` | 9 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; header text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | padding-right | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `16px` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; button text="Create crossover" |
| spacing | padding-top | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; header text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `10px` | 2 | input; button text="Create crossover" |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| typography | font-family | `Outfit, sans-serif` | 19 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 14 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `12px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-size | `14px` | 1 | a text="What is a crossover?" |
| typography | font-weight | `400` | 13 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `700` | 6 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | letter-spacing | `normal` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1.2px` | 1 | button aria-label=Log out text="LOG OUT" |
| typography | line-height | `24px` | 14 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `16px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | line-height | `20px` | 1 | a text="What is a crossover?" |

### continuity-plans at tablet

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 11 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=Continuity Planner page text="Planner"; button text="Classic" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklch(0.769 0.188 70.08)` | 1 | button text="Create a plan" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | border-color | `rgb(232, 213, 176)` | 4 | button text="Classic"; main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 1 | a aria-label=Continuity Planner page text="Planner" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `oklch(0.147 0.004 49.25)` | 1 | button text="Create a plan" |
| colors | color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | color | `rgb(232, 213, 176)` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| colors | color | `oklch(0.828 0.189 84.429)` | 1 | a aria-label=Continuity Planner page text="Planner" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `oklch(0.147 0.004 49.25)` | 1 | button text="Create a plan" |
| controls | border-width | `0px` | 13 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `24px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `44px` | 1 | button text="Create a plan" |
| controls | height | `32px` | 1 | button aria-label=Send feedback |
| controls | min-height | `auto` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `0px` | 2 | button aria-label=Log out text="LOG OUT"; button aria-label=Send feedback |
| controls | min-height | `44px` | 1 | button text="Create a plan" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| panels | border-radius | `0px` | 2 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| panels | box-shadow | `none` | 2 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| radii | border-radius | `8px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 4 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `12px` | 1 | button text="Create a plan" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `none` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 9 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | margin-bottom | `0px` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `20px` | 1 | header text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | margin-top | `0px` | 15 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | margin-top | `16px` | 1 | button text="Create a plan" |
| spacing | padding-bottom | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; header text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-left | `12px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 4 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; header text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-left | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `16px` | 1 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-left | `20px` | 1 | button text="Create a plan" |
| spacing | padding-right | `12px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 4 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; header text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-right | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `16px` | 1 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-right | `20px` | 1 | button text="Create a plan" |
| spacing | padding-top | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; header text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| typography | font-family | `Outfit, sans-serif` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 13 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `12px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `400` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `700` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `900` | 1 | button text="Create a plan" |
| typography | letter-spacing | `normal` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1.2px` | 1 | button aria-label=Log out text="LOG OUT" |
| typography | line-height | `24px` | 13 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `16px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |

### continuity-planner at tablet

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 22 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | background-color | `rgba(255, 255, 255, 0.04)` | 5 | input; button text="Add issue"; select text="Select a crossover" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 2 | input; select text="No issues available" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 1 | button text="Classic" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `rgb(212, 137, 14)` | 1 | button text="Save plan" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; input; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc" |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | border-color | `rgb(232, 213, 176)` | 4 | button text="Classic"; main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 3 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.2)` | 2 | input; select text="No issues available" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `rgb(160, 147, 126)` | 1 | button aria-label=Remove lane Reading order text="Remove" |
| colors | border-color | `oklch(0.147 0.004 49.25)` | 1 | button text="Save plan" |
| colors | color | `rgb(232, 213, 176)` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| colors | color | `oklch(0.709 0.01 56.259)` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | color | `rgb(160, 147, 126)` | 5 | button text="Add lane"; button aria-label=Move lane Reading order earlier text="↑"; button aria-label=Move lane Reading order later text="↓" |
| colors | color | `oklch(0.828 0.189 84.429)` | 3 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| colors | color | `oklch(0.869 0.005 56.366)` | 2 | input; select text="No issues available" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `oklch(0.147 0.004 49.25)` | 1 | button text="Save plan" |
| controls | border-width | `0px` | 17 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | border-width | `1px` | 11 | input; select text="No issues available"; button text="Add issue" |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `44px` | 6 | button text="Add issue"; select text="Select a crossover"; button text="Add crossover" |
| controls | height | `24px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `auto` | 3 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| controls | height | `38px` | 3 | input; select text="No issues available"; input aria-label=Lane Reading order name |
| controls | height | `36px` | 3 | button aria-label=Move lane Reading order earlier text="↑"; button aria-label=Move lane Reading order later text="↓"; button aria-label=Remove lane Reading order text="Remove" |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `42px` | 1 | input |
| controls | height | `32px` | 1 | button aria-label=Send feedback |
| controls | min-height | `auto` | 11 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `0px` | 8 | button aria-label=Log out text="LOG OUT"; a text="Continuity Plan"; a text="Lane" |
| controls | min-height | `44px` | 6 | button text="Add issue"; select text="Select a crossover"; button text="Add crossover" |
| controls | min-height | `36px` | 3 | button aria-label=Move lane Reading order earlier text="↑"; button aria-label=Move lane Reading order later text="↓"; button aria-label=Remove lane Reading order text="Remove" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 4 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| panels | border-color | `rgba(255, 255, 255, 0.08)` | 2 | section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc"; section text="READING LANES 1 lane · 0 steps Add lane ↑ ↓ Remove No steps in this lane yet." |
| panels | border-radius | `0px` | 4 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc" |
| panels | box-shadow | `none` | 4 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc" |
| radii | border-radius | `8px` | 11 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `12px` | 10 | input; select text="No issues available"; button text="Add issue" |
| radii | border-radius | `0px` | 9 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `none` | 33 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 27 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | margin-bottom | `0px` | 31 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `24px` | 3 | header text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc"; section text="READING LANES 1 lane · 0 steps Add lane ↑ ↓ Remove No steps in this lane yet." |
| spacing | margin-top | `0px` | 29 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `4px` | 4 | input; select text="No issues available"; select text="Select a crossover" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `0px` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; header text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; a text="Continuity Plan" |
| spacing | padding-bottom | `8px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-bottom | `32px` | 1 | section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-bottom | `12px` | 1 | input |
| spacing | padding-left | `12px` | 15 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 11 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; header text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-left | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `16px` | 3 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; button text="Add issue"; button text="Add crossover" |
| spacing | padding-left | `20px` | 1 | button text="Cancel changes" |
| spacing | padding-left | `32px` | 1 | button text="Save plan" |
| spacing | padding-right | `12px` | 15 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 11 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; header text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-right | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `16px` | 3 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; button text="Add issue"; button text="Add crossover" |
| spacing | padding-right | `20px` | 1 | button text="Cancel changes" |
| spacing | padding-right | `32px` | 1 | button text="Save plan" |
| spacing | padding-top | `0px` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; header text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-top | `8px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `20px` | 2 | section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc"; section text="READING LANES 1 lane · 0 steps Add lane ↑ ↓ Remove No steps in this lane yet." |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-top | `12px` | 1 | input |
| typography | font-family | `Outfit, sans-serif` | 34 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 19 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `14px` | 8 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| typography | font-size | `12px` | 7 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `700` | 17 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `400` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `900` | 1 | button text="Save plan" |
| typography | letter-spacing | `normal` | 29 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1.2px` | 3 | button aria-label=Log out text="LOG OUT"; input; select text="Select a crossover" |
| typography | letter-spacing | `1px` | 2 | input; select text="No issues available" |
| typography | line-height | `24px` | 19 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `20px` | 7 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| typography | line-height | `16px` | 6 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | line-height | `normal` | 2 | select text="No issues available"; select text="Select a crossover" |

### manual-picker-dialog at tablet

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 24 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 5 | button text="SHUFFLE QUEUE"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=Roll page text="Roll"; button text="Classic" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklab(0.691008 0.049379 0.13801 / 0.15)` | 1 | button text="d4" |
| colors | background-color | `rgb(212, 137, 14)` | 1 | button text="PICK MANUALLY" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | background-color | `rgba(17, 14, 10, 0.95)` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 16 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | border-color | `rgb(232, 213, 176)` | 6 | button text="Classic"; main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 3 | a aria-label=Roll page text="Roll"; a text="LADDER"; select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 2 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `rgb(212, 137, 14)` | 1 | button text="d4" |
| colors | border-color | `oklch(0.216 0.006 56.043)` | 1 | button text="PICK MANUALLY" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 1 | button text="SHUFFLE QUEUE" |
| colors | border-color | `oklch(0.553 0.013 58.071)` | 1 | button aria-label=Close modal text="×" |
| colors | color | `oklch(0.709 0.01 56.259)` | 16 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | color | `rgb(232, 213, 176)` | 11 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| colors | color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Roll page text="Roll"; a text="LADDER" |
| colors | color | `oklch(0.869 0.005 56.366)` | 2 | button text="SHUFFLE QUEUE"; select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `rgb(212, 137, 14)` | 1 | button text="d4" |
| colors | color | `oklch(0.216 0.006 56.043)` | 1 | button text="PICK MANUALLY" |
| colors | color | `oklch(0.553 0.013 58.071)` | 1 | button aria-label=Close modal text="×" |
| controls | border-width | `0px` | 27 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | border-width | `1px` | 5 | button text="SHUFFLE QUEUE"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| controls | height | `44px` | 11 | button text="d4"; button text="d6"; button text="d8" |
| controls | height | `40px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `24px` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `79px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| controls | height | `32px` | 2 | button text="SHUFFLE QUEUE"; button aria-label=Send feedback |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `200px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| controls | height | `38px` | 1 | select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| controls | min-height | `auto` | 14 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `44px` | 11 | button text="d4"; button text="d6"; button text="d8" |
| controls | min-height | `0px` | 7 | button aria-label=Log out text="LOG OUT"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| panels | background-color | `rgba(17, 14, 10, 0.95)` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| panels | border-color | `rgba(255, 255, 255, 0.08)` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| panels | border-radius | `0px` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| panels | border-radius | `8px` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| panels | box-shadow | `none` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| panels | box-shadow | `rgba(0, 0, 0, 0.3) 0px 20px 25px -5px, rgba(0, 0, 0, 0.2) 0px 10px 10px -5px` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| radii | border-radius | `8px` | 20 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 6 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| radii | border-radius | `12px` | 5 | button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `3.35544e+07px` | 2 | div role=button aria-label=Roll the dice data-testid=main-die-3d; button aria-label=Send feedback |
| radii | border-radius | `24px` | 1 | button text="PICK THIS THREAD" |
| shadows | box-shadow | `none` | 34 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `rgba(0, 0, 0, 0.3) 0px 20px 25px -5px, rgba(0, 0, 0, 0.2) 0px 10px 10px -5px` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, oklab(0.769 0.0640531 0.176752 / 0.3) 0px 0px 0px 2px, rgba(0, 0, 0, 0) 0px 0px 0px 0px` | 1 | select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| spacing | gap | `normal` | 26 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | gap | `8px 12px` | 1 | header text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| spacing | margin-bottom | `0px` | 35 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `8px` | 2 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| spacing | margin-top | `0px` | 35 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | margin-top | `32px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| spacing | padding-bottom | `0px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; button text="d4" |
| spacing | padding-bottom | `8px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `12px` | 4 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| spacing | padding-left | `8px` | 13 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `12px` | 11 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 8 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; a text="LADDER" |
| spacing | padding-left | `16px` | 5 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE" |
| spacing | padding-right | `8px` | 13 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `12px` | 11 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 8 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; a text="LADDER" |
| spacing | padding-right | `16px` | 5 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE" |
| spacing | padding-top | `0px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; button text="d4" |
| spacing | padding-top | `8px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `12px` | 4 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| typography | font-family | `Outfit, sans-serif` | 37 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `10px` | 12 | button text="d4"; button text="d6"; button text="d8" |
| typography | font-size | `12px` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-size | `24px` | 1 | button aria-label=Close modal text="×" |
| typography | font-size | `14px` | 1 | select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| typography | font-weight | `400` | 19 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `900` | 13 | button text="d4"; button text="d6"; button text="d8" |
| typography | font-weight | `700` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | letter-spacing | `normal` | 32 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1px` | 2 | button text="PICK MANUALLY"; button text="SHUFFLE QUEUE" |
| typography | letter-spacing | `1.2px` | 1 | button aria-label=Log out text="LOG OUT" |
| typography | letter-spacing | `0.25px` | 1 | button text="AUTO" |
| typography | letter-spacing | `1.8px` | 1 | button text="PICK THIS THREAD" |
| typography | line-height | `24px` | 19 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `15px` | 12 | button text="d4"; button text="d6"; button text="d8" |
| typography | line-height | `16px` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | line-height | `normal` | 1 | select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |

### roll at desktop

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 22 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 4 | button text="SHUFFLE QUEUE"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=Roll page text="Roll"; button text="Classic" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklab(0.691008 0.049379 0.13801 / 0.15)` | 1 | button text="d6" |
| colors | background-color | `rgb(212, 137, 14)` | 1 | button text="PICK MANUALLY" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 16 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | border-color | `rgb(232, 213, 176)` | 5 | button text="Classic"; main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Roll page text="Roll"; a text="LADDER" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `rgb(212, 137, 14)` | 1 | button text="d6" |
| colors | border-color | `oklch(0.216 0.006 56.043)` | 1 | button text="PICK MANUALLY" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 1 | button text="SHUFFLE QUEUE" |
| colors | color | `oklch(0.709 0.01 56.259)` | 16 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | color | `rgb(232, 213, 176)` | 9 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| colors | color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Roll page text="Roll"; a text="LADDER" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `rgb(212, 137, 14)` | 1 | button text="d6" |
| colors | color | `oklch(0.216 0.006 56.043)` | 1 | button text="PICK MANUALLY" |
| colors | color | `oklch(0.869 0.005 56.366)` | 1 | button text="SHUFFLE QUEUE" |
| controls | border-width | `0px` | 25 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | border-width | `1px` | 4 | button text="SHUFFLE QUEUE"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| controls | height | `44px` | 11 | button text="d4"; button text="d6"; button text="d8" |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `24px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `79px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| controls | height | `32px` | 2 | button text="SHUFFLE QUEUE"; button aria-label=Send feedback |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `200px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| controls | min-height | `auto` | 13 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `44px` | 11 | button text="d4"; button text="d6"; button text="d8" |
| controls | min-height | `0px` | 5 | button aria-label=Log out text="LOG OUT"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| panels | border-radius | `0px` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| panels | box-shadow | `none` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| radii | border-radius | `8px` | 19 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| radii | border-radius | `12px` | 4 | button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `3.35544e+07px` | 2 | div role=button aria-label=Roll the dice data-testid=main-die-3d; button aria-label=Send feedback |
| shadows | box-shadow | `none` | 31 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(212, 137, 14, 0.243) 0px 0px 38.7558px 0px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 22 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | gap | `8px 12px` | 1 | header text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| spacing | margin-bottom | `0px` | 31 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `8px` | 2 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| spacing | margin-top | `0px` | 31 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | margin-top | `32px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| spacing | padding-bottom | `0px` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; button text="d4" |
| spacing | padding-bottom | `8px` | 9 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `12px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| spacing | padding-left | `8px` | 13 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `12px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; a text="LADDER" |
| spacing | padding-left | `16px` | 5 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE" |
| spacing | padding-right | `8px` | 13 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `12px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; a text="LADDER" |
| spacing | padding-right | `16px` | 5 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE" |
| spacing | padding-top | `0px` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; button text="d4" |
| spacing | padding-top | `8px` | 9 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `12px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| typography | font-family | `Outfit, sans-serif` | 33 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `10px` | 12 | button text="d4"; button text="d6"; button text="d8" |
| typography | font-size | `12px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `400` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `900` | 12 | button text="d4"; button text="d6"; button text="d8" |
| typography | font-weight | `700` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | letter-spacing | `normal` | 29 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1px` | 2 | button text="PICK MANUALLY"; button text="SHUFFLE QUEUE" |
| typography | letter-spacing | `1.2px` | 1 | button aria-label=Log out text="LOG OUT" |
| typography | letter-spacing | `0.25px` | 1 | button text="AUTO" |
| typography | line-height | `24px` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `15px` | 12 | button text="d4"; button text="d6"; button text="d8" |
| typography | line-height | `16px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |

### roll-rating at desktop

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 15 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=Roll page text="Roll"; button text="Classic" |
| colors | background-color | `rgba(255, 255, 255, 0.05)` | 2 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #" |
| colors | background-color | `rgba(255, 255, 255, 0.04)` | 2 | section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 2 | button text="SNOOZE"; button aria-label=Skip current roll data-testid=skip-roll text="SKIP" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklch(0.769 0.188 70.08)` | 1 | button text="FIND COMICVINE MATCH" |
| colors | background-color | `rgba(6, 182, 212, 0.09)` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| colors | background-color | `oklab(0.666 0.0940116 0.152325 / 0.25)` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| colors | background-color | `oklab(0.586 0.241177 0.0764364 / 0.1)` | 1 | button text="CANCEL ROLL" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | border-color | `rgb(232, 213, 176)` | 6 | button text="Classic"; main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 2 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="ROLL RESULT Rolled 0 on d6 SERIES PROGRESS" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Roll page text="Roll"; a text="d6 → d4" |
| colors | border-color | `rgba(255, 255, 255, 0.1)` | 2 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | button text="SNOOZE"; button aria-label=Skip current roll data-testid=skip-roll text="SKIP" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `oklch(0.216 0.006 56.043)` | 1 | button text="FIND COMICVINE MATCH" |
| colors | border-color | `rgba(6, 182, 212, 0.3)` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| colors | border-color | `rgba(168, 85, 247, 0.15)` | 1 | section text="SERIES HISTORY Canonical series history unavailable" |
| colors | border-color | `rgba(168, 85, 247, 0.2)` | 1 | section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| colors | border-color | `oklab(0.666 0.0940116 0.152325 / 0.5)` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| colors | border-color | `oklab(0.586 0.241177 0.0764364 / 0.3)` | 1 | button text="CANCEL ROLL" |
| colors | color | `rgb(232, 213, 176)` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss" |
| colors | color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | color | `oklch(0.869 0.005 56.366)` | 4 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="SNOOZE" |
| colors | color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Roll page text="Roll"; a text="d6 → d4" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `oklch(0.216 0.006 56.043)` | 1 | button text="FIND COMICVINE MATCH" |
| colors | color | `oklch(0.712 0.194 13.428)` | 1 | button text="CANCEL ROLL" |
| controls | border-width | `0px` | 15 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | border-width | `1px` | 6 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button data-testid=save-and-continue text="MARK READ & SAVE" |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `44px` | 5 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="SNOOZE" |
| controls | height | `24px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `36px` | 1 | button text="FIND COMICVINE MATCH" |
| controls | height | `auto` | 1 | a text="d6 → d4" |
| controls | height | `16px` | 1 | input aria-label=Rating from 0.5 to 5.0 in steps of 0.5 |
| controls | height | `46px` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| controls | height | `32px` | 1 | button aria-label=Send feedback |
| controls | min-height | `auto` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `0px` | 5 | button aria-label=Log out text="LOG OUT"; a text="d6 → d4"; input aria-label=Rating from 0.5 to 5.0 in steps of 0.5 |
| controls | min-height | `44px` | 5 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="SNOOZE" |
| controls | min-height | `36px` | 1 | button text="FIND COMICVINE MATCH" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 4 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| panels | background-color | `rgba(255, 255, 255, 0.04)` | 2 | section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| panels | background-color | `rgba(6, 182, 212, 0.09)` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| panels | border-color | `rgb(232, 213, 176)` | 3 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| panels | border-color | `rgba(6, 182, 212, 0.3)` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| panels | border-color | `rgba(255, 255, 255, 0.08)` | 1 | section text="ROLL RESULT Rolled 0 on d6 SERIES PROGRESS" |
| panels | border-color | `rgba(168, 85, 247, 0.15)` | 1 | section text="SERIES HISTORY Canonical series history unavailable" |
| panels | border-color | `rgba(168, 85, 247, 0.2)` | 1 | section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| panels | border-radius | `0px` | 4 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| panels | border-radius | `16px` | 3 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis"; section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| panels | box-shadow | `none` | 7 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| radii | border-radius | `8px` | 9 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 8 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss" |
| radii | border-radius | `12px` | 6 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button data-testid=save-and-continue text="MARK READ & SAVE" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `16px` | 3 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis"; section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `none` | 29 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 21 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | gap | `8px 12px` | 1 | header text="PILE ROLLER" |
| spacing | gap | `12px 24px` | 1 | section text="ROLL RESULT Rolled 0 on d6 SERIES PROGRESS" |
| spacing | margin-bottom | `0px` | 25 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `16px` | 3 | section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl"; section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis"; section text="SERIES HISTORY Canonical series history unavailable" |
| spacing | margin-bottom | `12px` | 1 | input aria-label=Rating from 0.5 to 5.0 in steps of 0.5 |
| spacing | margin-bottom | `8px` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| spacing | margin-top | `0px` | 29 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `0px` | 9 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| spacing | padding-bottom | `8px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `12px` | 6 | section text="ROLL RESULT Rolled 0 on d6 SERIES PROGRESS"; section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss" |
| spacing | padding-bottom | `16px` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| spacing | padding-bottom | `14px` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| spacing | padding-left | `12px` | 14 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 11 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| spacing | padding-left | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `16px` | 2 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| spacing | padding-right | `12px` | 14 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 11 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| spacing | padding-right | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `16px` | 2 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| spacing | padding-top | `0px` | 10 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| spacing | padding-top | `8px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `12px` | 5 | section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of"; button text="SNOOZE" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss" |
| spacing | padding-top | `16px` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| spacing | padding-top | `14px` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| typography | font-family | `Outfit, sans-serif` | 30 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `12px` | 8 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-size | `10px` | 3 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="FIND COMICVINE MATCH" |
| typography | font-size | `14px` | 1 | a text="d6 → d4" |
| typography | font-weight | `400` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `900` | 7 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="FIND COMICVINE MATCH" |
| typography | font-weight | `700` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | letter-spacing | `normal` | 22 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1.8px` | 4 | button data-testid=save-and-continue text="MARK READ & SAVE"; button text="SNOOZE"; button aria-label=Skip current roll data-testid=skip-roll text="SKIP" |
| typography | letter-spacing | `0.5px` | 3 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="FIND COMICVINE MATCH" |
| typography | letter-spacing | `1.2px` | 1 | button aria-label=Log out text="LOG OUT" |
| typography | line-height | `24px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `16px` | 8 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | line-height | `15px` | 3 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="FIND COMICVINE MATCH" |
| typography | line-height | `20px` | 1 | a text="d6 → d4" |

### queue at desktop

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 24 | a aria-label=Roll page text="Roll"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 10 | button text="SHUFFLE"; button text="A-Z"; button text="NEW" |
| colors | background-color | `rgb(212, 137, 14)` | 3 | button aria-label=Read text="Read" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=Queue page text="Queue"; button text="Classic" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklab(0.666 0.0940116 0.152325 / 0.2)` | 1 | button text="POS" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `rgb(232, 213, 176)` | 8 | button text="Classic"; main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Roll page text="Roll"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | border-color | `rgb(107, 95, 80)` | 6 | button aria-label=Drag to reorder text="⠿"; button aria-label=Delete text="Delete" |
| colors | border-color | `rgb(160, 147, 126)` | 6 | button aria-label=Edit text="Edit"; button aria-label=Snooze text="😴 Snooze" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 4 | button text="SHUFFLE"; button text="A-Z"; button text="NEW" |
| colors | border-color | `rgb(255, 255, 255)` | 3 | button aria-label=Read text="Read" |
| colors | border-color | `oklch(0.553 0.013 58.071)` | 3 | button aria-label=Thread actions text="⋮" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 1 | a aria-label=Queue page text="Queue" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `oklab(0.769 0.0640531 0.176752 / 0.3)` | 1 | button text="POS" |
| colors | color | `rgb(232, 213, 176)` | 9 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| colors | color | `oklch(0.709 0.01 56.259)` | 9 | a aria-label=Roll page text="Roll"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | color | `rgb(107, 95, 80)` | 6 | button aria-label=Drag to reorder text="⠿"; button aria-label=Delete text="Delete" |
| colors | color | `rgb(160, 147, 126)` | 6 | button aria-label=Edit text="Edit"; button aria-label=Snooze text="😴 Snooze" |
| colors | color | `rgb(255, 255, 255)` | 3 | button aria-label=Read text="Read" |
| colors | color | `oklch(0.553 0.013 58.071)` | 3 | button aria-label=Thread actions text="⋮" |
| colors | color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Queue page text="Queue"; button text="POS" |
| colors | color | `oklch(0.869 0.005 56.366)` | 2 | button text="SHUFFLE"; input |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | border-width | `0px` | 34 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | border-width | `1px` | 5 | button text="SHUFFLE"; button text="POS"; button text="A-Z" |
| controls | height | `36px` | 13 | input; button aria-label=Read text="Read"; button aria-label=Edit text="Edit" |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `28px` | 4 | button aria-label=Log out text="LOG OUT"; button aria-label=Open Test Thread 1 text="Test Thread 1"; button aria-label=Open Test Thread 2 text="Test Thread 2" |
| controls | height | `32px` | 4 | button aria-label=Drag to reorder text="⠿"; button aria-label=Send feedback |
| controls | height | `24px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `29px` | 3 | button text="POS"; button text="A-Z"; button text="NEW" |
| controls | height | `44px` | 3 | button aria-label=Thread actions text="⋮" |
| controls | height | `48px` | 2 | button text="SHUFFLE"; button data-testid=queue-add-thread-desktop text="ADD THREAD" |
| controls | min-height | `auto` | 34 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `0px` | 5 | button aria-label=Log out text="LOG OUT"; button aria-label=Thread actions text="⋮"; button aria-label=Send feedback |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| panels | border-radius | `0px` | 2 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| panels | box-shadow | `none` | 2 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| radii | border-radius | `8px` | 31 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 7 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `24px` | 1 | button data-testid=queue-add-thread-desktop text="ADD THREAD" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `none` | 41 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 20px 25px -5px, rgba(0, 0, 0, 0.1) 0px 8px 10px -6px` | 1 | button data-testid=queue-add-thread-desktop text="ADD THREAD" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 33 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | gap | `6px` | 3 | button aria-label=Snooze text="😴 Snooze" |
| spacing | margin-bottom | `0px` | 42 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `40px` | 1 | header text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3" |
| spacing | margin-top | `0px` | 42 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `0px` | 27 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; header text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3"; button text="SHUFFLE" |
| spacing | padding-bottom | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `6px` | 4 | button aria-label=Log out text="LOG OUT"; button text="POS"; button text="A-Z" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `24px` | 1 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| spacing | padding-bottom | `40px` | 1 | div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| spacing | padding-left | `12px` | 21 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; button aria-label=Drag to reorder text="⠿" |
| spacing | padding-left | `8px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `16px` | 4 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; button aria-label=Read text="Read" |
| spacing | padding-left | `20px` | 2 | button text="SHUFFLE"; button data-testid=queue-add-thread-desktop text="ADD THREAD" |
| spacing | padding-right | `12px` | 21 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; button aria-label=Drag to reorder text="⠿" |
| spacing | padding-right | `8px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `16px` | 4 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; button aria-label=Read text="Read" |
| spacing | padding-right | `20px` | 2 | button text="SHUFFLE"; button data-testid=queue-add-thread-desktop text="ADD THREAD" |
| spacing | padding-top | `0px` | 28 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; header text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3" |
| spacing | padding-top | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `6px` | 4 | button aria-label=Log out text="LOG OUT"; button text="POS"; button text="A-Z" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `24px` | 1 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| typography | font-family | `Outfit, sans-serif` | 43 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 15 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `14px` | 12 | button aria-label=Read text="Read"; button aria-label=Edit text="Edit"; button aria-label=Snooze text="😴 Snooze" |
| typography | font-size | `12px` | 7 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-size | `18px` | 6 | button aria-label=Drag to reorder text="⠿"; button aria-label=Thread actions text="⋮" |
| typography | font-size | `10px` | 3 | button text="POS"; button text="A-Z"; button text="NEW" |
| typography | font-weight | `400` | 22 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `700` | 7 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `600` | 6 | button aria-label=Edit text="Edit"; button aria-label=Snooze text="😴 Snooze" |
| typography | font-weight | `900` | 5 | button text="SHUFFLE"; button data-testid=queue-add-thread-desktop text="ADD THREAD"; button text="POS" |
| typography | font-weight | `500` | 3 | button aria-label=Delete text="Delete" |
| typography | letter-spacing | `normal` | 37 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1px` | 3 | button text="POS"; button text="A-Z"; button text="NEW" |
| typography | letter-spacing | `1.2px` | 2 | button aria-label=Log out text="LOG OUT"; button text="SHUFFLE" |
| typography | letter-spacing | `1.8px` | 1 | button data-testid=queue-add-thread-desktop text="ADD THREAD" |
| typography | line-height | `24px` | 15 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `20px` | 12 | button aria-label=Read text="Read"; button aria-label=Edit text="Edit"; button aria-label=Snooze text="😴 Snooze" |
| typography | line-height | `16px` | 7 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | line-height | `28px` | 6 | button aria-label=Drag to reorder text="⠿"; button aria-label=Thread actions text="⋮" |
| typography | line-height | `15px` | 3 | button text="POS"; button text="A-Z"; button text="NEW" |

### history at desktop

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 13 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=Crossovers page text="Crossovers" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=History page text="History"; button text="Classic" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=Crossovers page text="Crossovers" |
| colors | border-color | `rgb(232, 213, 176)` | 4 | button text="Classic"; main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 1 | a aria-label=History page text="History" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `oklch(0.553 0.013 58.071)` | 1 | a text="EXPORT SUMMARY" |
| colors | color | `oklch(0.709 0.01 56.259)` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=Crossovers page text="Crossovers" |
| colors | color | `rgb(232, 213, 176)` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| colors | color | `oklch(0.828 0.189 84.429)` | 1 | a aria-label=History page text="History" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `oklch(0.553 0.013 58.071)` | 1 | a text="EXPORT SUMMARY" |
| controls | border-width | `0px` | 14 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `24px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `23px` | 1 | a text="EXPORT SUMMARY" |
| controls | height | `15px` | 1 | a text="VIEW FULL SESSION →" |
| controls | height | `32px` | 1 | button aria-label=Send feedback |
| controls | min-height | `auto` | 11 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `0px` | 3 | button aria-label=Log out text="LOG OUT"; a text="VIEW FULL SESSION →"; button aria-label=Send feedback |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| panels | border-radius | `0px` | 2 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| panels | box-shadow | `none` | 2 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| radii | border-radius | `8px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 6 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `none` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 9 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | gap | `4px` | 1 | a text="VIEW FULL SESSION →" |
| spacing | margin-bottom | `0px` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `32px` | 1 | header text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY" |
| spacing | margin-top | `0px` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `0px` | 4 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; header text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY"; a text="VIEW FULL SESSION →" |
| spacing | padding-bottom | `4px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| spacing | padding-bottom | `80px` | 1 | div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| spacing | padding-left | `12px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; a text="EXPORT SUMMARY" |
| spacing | padding-left | `8px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `16px` | 1 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| spacing | padding-right | `12px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; a text="EXPORT SUMMARY" |
| spacing | padding-right | `8px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `16px` | 1 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| spacing | padding-top | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; header text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY" |
| spacing | padding-top | `4px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| typography | font-family | `Outfit, sans-serif` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `12px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-size | `10px` | 2 | a text="EXPORT SUMMARY"; a text="VIEW FULL SESSION →" |
| typography | font-weight | `400` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `700` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `900` | 1 | a text="VIEW FULL SESSION →" |
| typography | letter-spacing | `normal` | 15 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1px` | 2 | a text="EXPORT SUMMARY"; a text="VIEW FULL SESSION →" |
| typography | letter-spacing | `1.2px` | 1 | button aria-label=Log out text="LOG OUT" |
| typography | line-height | `24px` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `16px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | line-height | `15px` | 2 | a text="EXPORT SUMMARY"; a text="VIEW FULL SESSION →" |

### crossovers at desktop

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 12 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=Crossovers page text="Crossovers"; button text="Classic" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklch(0.147 0.004 49.25)` | 1 | input |
| colors | background-color | `oklch(0.769 0.188 70.08)` | 1 | button text="Create crossover" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | border-color | `rgb(232, 213, 176)` | 4 | button text="Classic"; main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Crossovers page text="Crossovers"; a text="What is a crossover?" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `oklch(0.444 0.011 73.639)` | 1 | input |
| colors | border-color | `oklch(0.147 0.004 49.25)` | 1 | button text="Create crossover" |
| colors | color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | color | `rgb(232, 213, 176)` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| colors | color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Crossovers page text="Crossovers"; a text="What is a crossover?" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `oklch(0.97 0.001 106.424)` | 1 | input |
| colors | color | `oklch(0.147 0.004 49.25)` | 1 | button text="Create crossover" |
| controls | border-width | `0px` | 14 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | border-width | `1px` | 1 | input |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `24px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `46px` | 2 | input; button text="Create crossover" |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `auto` | 1 | a text="What is a crossover?" |
| controls | height | `32px` | 1 | button aria-label=Send feedback |
| controls | min-height | `auto` | 12 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `0px` | 3 | button aria-label=Log out text="LOG OUT"; a text="What is a crossover?"; button aria-label=Send feedback |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| panels | border-radius | `0px` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| panels | box-shadow | `none` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| radii | border-radius | `8px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `12px` | 2 | input; button text="Create crossover" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `none` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | margin-bottom | `0px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `24px` | 1 | header text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | margin-top | `0px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `0px` | 4 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; header text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; a text="What is a crossover?" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `10px` | 2 | input; button text="Create crossover" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | padding-bottom | `112px` | 1 | section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | padding-left | `12px` | 9 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; header text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | padding-left | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `16px` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; button text="Create crossover" |
| spacing | padding-right | `12px` | 9 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; header text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | padding-right | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `16px` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; button text="Create crossover" |
| spacing | padding-top | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; header text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `10px` | 2 | input; button text="Create crossover" |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| typography | font-family | `Outfit, sans-serif` | 19 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 14 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `12px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-size | `14px` | 1 | a text="What is a crossover?" |
| typography | font-weight | `400` | 13 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `700` | 6 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | letter-spacing | `normal` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1.2px` | 1 | button aria-label=Log out text="LOG OUT" |
| typography | line-height | `24px` | 14 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `16px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | line-height | `20px` | 1 | a text="What is a crossover?" |

### continuity-plans at desktop

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 11 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=Continuity Planner page text="Planner"; button text="Classic" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklch(0.769 0.188 70.08)` | 1 | button text="Create a plan" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | border-color | `rgb(232, 213, 176)` | 4 | button text="Classic"; main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 1 | a aria-label=Continuity Planner page text="Planner" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `oklch(0.147 0.004 49.25)` | 1 | button text="Create a plan" |
| colors | color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | color | `rgb(232, 213, 176)` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| colors | color | `oklch(0.828 0.189 84.429)` | 1 | a aria-label=Continuity Planner page text="Planner" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `oklch(0.147 0.004 49.25)` | 1 | button text="Create a plan" |
| controls | border-width | `0px` | 13 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `24px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `44px` | 1 | button text="Create a plan" |
| controls | height | `32px` | 1 | button aria-label=Send feedback |
| controls | min-height | `auto` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `0px` | 2 | button aria-label=Log out text="LOG OUT"; button aria-label=Send feedback |
| controls | min-height | `44px` | 1 | button text="Create a plan" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| panels | border-radius | `0px` | 2 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| panels | box-shadow | `none` | 2 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| radii | border-radius | `8px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 4 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `12px` | 1 | button text="Create a plan" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `none` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 9 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | margin-bottom | `0px` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `20px` | 1 | header text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | margin-top | `0px` | 15 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | margin-top | `16px` | 1 | button text="Create a plan" |
| spacing | padding-bottom | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; header text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-left | `12px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 4 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; header text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-left | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `16px` | 1 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-left | `20px` | 1 | button text="Create a plan" |
| spacing | padding-right | `12px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 4 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; header text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-right | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `16px` | 1 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-right | `20px` | 1 | button text="Create a plan" |
| spacing | padding-top | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; header text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| typography | font-family | `Outfit, sans-serif` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 13 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `12px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `400` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `700` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `900` | 1 | button text="Create a plan" |
| typography | letter-spacing | `normal` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1.2px` | 1 | button aria-label=Log out text="LOG OUT" |
| typography | line-height | `24px` | 13 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `16px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |

### continuity-planner at desktop

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 22 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | background-color | `rgba(255, 255, 255, 0.04)` | 5 | input; button text="Add issue"; select text="Select a crossover" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 2 | input; select text="No issues available" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 1 | button text="Classic" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `rgb(212, 137, 14)` | 1 | button text="Save plan" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; input; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc" |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | border-color | `rgb(232, 213, 176)` | 4 | button text="Classic"; main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 3 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.2)` | 2 | input; select text="No issues available" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `rgb(160, 147, 126)` | 1 | button aria-label=Remove lane Reading order text="Remove" |
| colors | border-color | `oklch(0.147 0.004 49.25)` | 1 | button text="Save plan" |
| colors | color | `rgb(232, 213, 176)` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| colors | color | `oklch(0.709 0.01 56.259)` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | color | `rgb(160, 147, 126)` | 5 | button text="Add lane"; button aria-label=Move lane Reading order earlier text="↑"; button aria-label=Move lane Reading order later text="↓" |
| colors | color | `oklch(0.828 0.189 84.429)` | 3 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| colors | color | `oklch(0.869 0.005 56.366)` | 2 | input; select text="No issues available" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `oklch(0.147 0.004 49.25)` | 1 | button text="Save plan" |
| controls | border-width | `0px` | 17 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | border-width | `1px` | 11 | input; select text="No issues available"; button text="Add issue" |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `44px` | 6 | button text="Add issue"; select text="Select a crossover"; button text="Add crossover" |
| controls | height | `24px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `auto` | 3 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| controls | height | `38px` | 3 | input; select text="No issues available"; input aria-label=Lane Reading order name |
| controls | height | `36px` | 3 | button aria-label=Move lane Reading order earlier text="↑"; button aria-label=Move lane Reading order later text="↓"; button aria-label=Remove lane Reading order text="Remove" |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `42px` | 1 | input |
| controls | height | `32px` | 1 | button aria-label=Send feedback |
| controls | min-height | `auto` | 11 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `0px` | 8 | button aria-label=Log out text="LOG OUT"; a text="Continuity Plan"; a text="Lane" |
| controls | min-height | `44px` | 6 | button text="Add issue"; select text="Select a crossover"; button text="Add crossover" |
| controls | min-height | `36px` | 3 | button aria-label=Move lane Reading order earlier text="↑"; button aria-label=Move lane Reading order later text="↓"; button aria-label=Remove lane Reading order text="Remove" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 4 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| panels | border-color | `rgba(255, 255, 255, 0.08)` | 2 | section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc"; section text="READING LANES 1 lane · 0 steps Add lane ↑ ↓ Remove No steps in this lane yet." |
| panels | border-radius | `0px` | 4 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc" |
| panels | box-shadow | `none` | 4 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc" |
| radii | border-radius | `8px` | 11 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `12px` | 10 | input; select text="No issues available"; button text="Add issue" |
| radii | border-radius | `0px` | 9 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `none` | 33 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 27 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | margin-bottom | `0px` | 31 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `24px` | 3 | header text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc"; section text="READING LANES 1 lane · 0 steps Add lane ↑ ↓ Remove No steps in this lane yet." |
| spacing | margin-top | `0px` | 29 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `4px` | 4 | input; select text="No issues available"; select text="Select a crossover" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `0px` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; header text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; a text="Continuity Plan" |
| spacing | padding-bottom | `8px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-bottom | `32px` | 1 | section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-bottom | `12px` | 1 | input |
| spacing | padding-left | `12px` | 15 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 11 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; header text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-left | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `16px` | 3 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; button text="Add issue"; button text="Add crossover" |
| spacing | padding-left | `20px` | 1 | button text="Cancel changes" |
| spacing | padding-left | `32px` | 1 | button text="Save plan" |
| spacing | padding-right | `12px` | 15 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 11 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; header text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-right | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `16px` | 3 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; button text="Add issue"; button text="Add crossover" |
| spacing | padding-right | `20px` | 1 | button text="Cancel changes" |
| spacing | padding-right | `32px` | 1 | button text="Save plan" |
| spacing | padding-top | `0px` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; header text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-top | `8px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `20px` | 2 | section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc"; section text="READING LANES 1 lane · 0 steps Add lane ↑ ↓ Remove No steps in this lane yet." |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-top | `12px` | 1 | input |
| typography | font-family | `Outfit, sans-serif` | 34 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 19 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `14px` | 8 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| typography | font-size | `12px` | 7 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `700` | 17 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `400` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `900` | 1 | button text="Save plan" |
| typography | letter-spacing | `normal` | 29 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1.2px` | 3 | button aria-label=Log out text="LOG OUT"; input; select text="Select a crossover" |
| typography | letter-spacing | `1px` | 2 | input; select text="No issues available" |
| typography | line-height | `24px` | 19 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `20px` | 7 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| typography | line-height | `16px` | 6 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | line-height | `normal` | 2 | select text="No issues available"; select text="Select a crossover" |

### manual-picker-dialog at desktop

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 24 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 5 | button text="SHUFFLE QUEUE"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=Roll page text="Roll"; button text="Classic" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklab(0.691008 0.049379 0.13801 / 0.15)` | 1 | button text="d4" |
| colors | background-color | `rgb(212, 137, 14)` | 1 | button text="PICK MANUALLY" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | background-color | `rgba(17, 14, 10, 0.95)` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 16 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | border-color | `rgb(232, 213, 176)` | 6 | button text="Classic"; main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 3 | a aria-label=Roll page text="Roll"; a text="LADDER"; select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 2 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `rgb(212, 137, 14)` | 1 | button text="d4" |
| colors | border-color | `oklch(0.216 0.006 56.043)` | 1 | button text="PICK MANUALLY" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 1 | button text="SHUFFLE QUEUE" |
| colors | border-color | `oklch(0.553 0.013 58.071)` | 1 | button aria-label=Close modal text="×" |
| colors | color | `oklch(0.709 0.01 56.259)` | 16 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | color | `rgb(232, 213, 176)` | 11 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| colors | color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Roll page text="Roll"; a text="LADDER" |
| colors | color | `oklch(0.869 0.005 56.366)` | 2 | button text="SHUFFLE QUEUE"; select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `rgb(212, 137, 14)` | 1 | button text="d4" |
| colors | color | `oklch(0.216 0.006 56.043)` | 1 | button text="PICK MANUALLY" |
| colors | color | `oklch(0.553 0.013 58.071)` | 1 | button aria-label=Close modal text="×" |
| controls | border-width | `0px` | 27 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | border-width | `1px` | 5 | button text="SHUFFLE QUEUE"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| controls | height | `44px` | 11 | button text="d4"; button text="d6"; button text="d8" |
| controls | height | `40px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `24px` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `79px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| controls | height | `32px` | 2 | button text="SHUFFLE QUEUE"; button aria-label=Send feedback |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `200px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| controls | height | `38px` | 1 | select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| controls | min-height | `auto` | 14 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `44px` | 11 | button text="d4"; button text="d6"; button text="d8" |
| controls | min-height | `0px` | 7 | button aria-label=Log out text="LOG OUT"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| panels | background-color | `rgba(17, 14, 10, 0.95)` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| panels | border-color | `rgba(255, 255, 255, 0.08)` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| panels | border-radius | `0px` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| panels | border-radius | `8px` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| panels | box-shadow | `none` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| panels | box-shadow | `rgba(0, 0, 0, 0.3) 0px 20px 25px -5px, rgba(0, 0, 0, 0.2) 0px 10px 10px -5px` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| radii | border-radius | `8px` | 20 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 6 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| radii | border-radius | `12px` | 5 | button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `3.35544e+07px` | 2 | div role=button aria-label=Roll the dice data-testid=main-die-3d; button aria-label=Send feedback |
| radii | border-radius | `24px` | 1 | button text="PICK THIS THREAD" |
| shadows | box-shadow | `none` | 34 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `rgba(0, 0, 0, 0.3) 0px 20px 25px -5px, rgba(0, 0, 0, 0.2) 0px 10px 10px -5px` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, oklab(0.769 0.0640531 0.176752 / 0.3) 0px 0px 0px 2px, rgba(0, 0, 0, 0) 0px 0px 0px 0px` | 1 | select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| spacing | gap | `normal` | 26 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | gap | `8px 12px` | 1 | header text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| spacing | margin-bottom | `0px` | 35 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `8px` | 2 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| spacing | margin-top | `0px` | 35 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | margin-top | `32px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| spacing | padding-bottom | `0px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; button text="d4" |
| spacing | padding-bottom | `8px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `12px` | 4 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| spacing | padding-left | `8px` | 13 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `12px` | 11 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 8 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; a text="LADDER" |
| spacing | padding-left | `16px` | 5 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE" |
| spacing | padding-right | `8px` | 13 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `12px` | 11 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 8 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; a text="LADDER" |
| spacing | padding-right | `16px` | 5 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE" |
| spacing | padding-top | `0px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; button text="d4" |
| spacing | padding-top | `8px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `12px` | 4 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| typography | font-family | `Outfit, sans-serif` | 37 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `10px` | 12 | button text="d4"; button text="d6"; button text="d8" |
| typography | font-size | `12px` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-size | `24px` | 1 | button aria-label=Close modal text="×" |
| typography | font-size | `14px` | 1 | select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| typography | font-weight | `400` | 19 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `900` | 13 | button text="d4"; button text="d6"; button text="d8" |
| typography | font-weight | `700` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | letter-spacing | `normal` | 32 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1px` | 2 | button text="PICK MANUALLY"; button text="SHUFFLE QUEUE" |
| typography | letter-spacing | `1.2px` | 1 | button aria-label=Log out text="LOG OUT" |
| typography | letter-spacing | `0.25px` | 1 | button text="AUTO" |
| typography | letter-spacing | `1.8px` | 1 | button text="PICK THIS THREAD" |
| typography | line-height | `24px` | 19 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `15px` | 12 | button text="d4"; button text="d6"; button text="d8" |
| typography | line-height | `16px` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | line-height | `normal` | 1 | select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |

### roll at wide-desktop

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 22 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 4 | button text="SHUFFLE QUEUE"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=Roll page text="Roll"; button text="Classic" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklab(0.691008 0.049379 0.13801 / 0.15)` | 1 | button text="d6" |
| colors | background-color | `rgb(212, 137, 14)` | 1 | button text="PICK MANUALLY" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 16 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | border-color | `rgb(232, 213, 176)` | 5 | button text="Classic"; main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Roll page text="Roll"; a text="LADDER" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `rgb(212, 137, 14)` | 1 | button text="d6" |
| colors | border-color | `oklch(0.216 0.006 56.043)` | 1 | button text="PICK MANUALLY" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 1 | button text="SHUFFLE QUEUE" |
| colors | color | `oklch(0.709 0.01 56.259)` | 16 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | color | `rgb(232, 213, 176)` | 9 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| colors | color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Roll page text="Roll"; a text="LADDER" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `rgb(212, 137, 14)` | 1 | button text="d6" |
| colors | color | `oklch(0.216 0.006 56.043)` | 1 | button text="PICK MANUALLY" |
| colors | color | `oklch(0.869 0.005 56.366)` | 1 | button text="SHUFFLE QUEUE" |
| controls | border-width | `0px` | 25 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | border-width | `1px` | 4 | button text="SHUFFLE QUEUE"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| controls | height | `44px` | 11 | button text="d4"; button text="d6"; button text="d8" |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `24px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `79px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| controls | height | `32px` | 2 | button text="SHUFFLE QUEUE"; button aria-label=Send feedback |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `200px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| controls | min-height | `auto` | 13 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `44px` | 11 | button text="d4"; button text="d6"; button text="d8" |
| controls | min-height | `0px` | 5 | button aria-label=Log out text="LOG OUT"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| panels | border-radius | `0px` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| panels | box-shadow | `none` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| radii | border-radius | `8px` | 19 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| radii | border-radius | `12px` | 4 | button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `3.35544e+07px` | 2 | div role=button aria-label=Roll the dice data-testid=main-die-3d; button aria-label=Send feedback |
| shadows | box-shadow | `none` | 32 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 22 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | gap | `8px 12px` | 1 | header text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| spacing | margin-bottom | `0px` | 31 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `8px` | 2 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| spacing | margin-top | `0px` | 31 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | margin-top | `32px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| spacing | padding-bottom | `0px` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; button text="d4" |
| spacing | padding-bottom | `8px` | 9 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `12px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| spacing | padding-left | `8px` | 13 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `12px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; a text="LADDER" |
| spacing | padding-left | `16px` | 5 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE" |
| spacing | padding-right | `8px` | 13 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `12px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; a text="LADDER" |
| spacing | padding-right | `16px` | 5 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE" |
| spacing | padding-top | `0px` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA"; button text="d4" |
| spacing | padding-top | `8px` | 9 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `12px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 1. Open thread actions. text="1 Test Thread 1 #1 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d6 BALANCED PICK MANUA" |
| typography | font-family | `Outfit, sans-serif` | 33 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `10px` | 12 | button text="d4"; button text="d6"; button text="d8" |
| typography | font-size | `12px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `400` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `900` | 12 | button text="d4"; button text="d6"; button text="d8" |
| typography | font-weight | `700` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | letter-spacing | `normal` | 29 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1px` | 2 | button text="PICK MANUALLY"; button text="SHUFFLE QUEUE" |
| typography | letter-spacing | `1.2px` | 1 | button aria-label=Log out text="LOG OUT" |
| typography | letter-spacing | `0.25px` | 1 | button text="AUTO" |
| typography | line-height | `24px` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `15px` | 12 | button text="d4"; button text="d6"; button text="d8" |
| typography | line-height | `16px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |

### roll-rating at wide-desktop

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 15 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=Roll page text="Roll"; button text="Classic" |
| colors | background-color | `rgba(255, 255, 255, 0.05)` | 2 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #" |
| colors | background-color | `rgba(255, 255, 255, 0.04)` | 2 | section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 2 | button text="SNOOZE"; button aria-label=Skip current roll data-testid=skip-roll text="SKIP" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklch(0.769 0.188 70.08)` | 1 | button text="FIND COMICVINE MATCH" |
| colors | background-color | `rgba(6, 182, 212, 0.09)` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| colors | background-color | `oklab(0.666 0.0940116 0.152325 / 0.25)` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| colors | background-color | `oklab(0.586 0.241177 0.0764364 / 0.1)` | 1 | button text="CANCEL ROLL" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | border-color | `rgb(232, 213, 176)` | 6 | button text="Classic"; main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 2 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="ROLL RESULT Rolled 0 on d6 SERIES PROGRESS" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Roll page text="Roll"; a text="d6 → d4" |
| colors | border-color | `rgba(255, 255, 255, 0.1)` | 2 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | button text="SNOOZE"; button aria-label=Skip current roll data-testid=skip-roll text="SKIP" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `oklch(0.216 0.006 56.043)` | 1 | button text="FIND COMICVINE MATCH" |
| colors | border-color | `rgba(6, 182, 212, 0.3)` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| colors | border-color | `rgba(168, 85, 247, 0.15)` | 1 | section text="SERIES HISTORY Canonical series history unavailable" |
| colors | border-color | `rgba(168, 85, 247, 0.2)` | 1 | section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| colors | border-color | `oklab(0.666 0.0940116 0.152325 / 0.5)` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| colors | border-color | `oklab(0.586 0.241177 0.0764364 / 0.3)` | 1 | button text="CANCEL ROLL" |
| colors | color | `rgb(232, 213, 176)` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss" |
| colors | color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | color | `oklch(0.869 0.005 56.366)` | 4 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="SNOOZE" |
| colors | color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Roll page text="Roll"; a text="d6 → d4" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `oklch(0.216 0.006 56.043)` | 1 | button text="FIND COMICVINE MATCH" |
| colors | color | `oklch(0.712 0.194 13.428)` | 1 | button text="CANCEL ROLL" |
| controls | border-width | `0px` | 15 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | border-width | `1px` | 6 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button data-testid=save-and-continue text="MARK READ & SAVE" |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `44px` | 5 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="SNOOZE" |
| controls | height | `24px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `36px` | 1 | button text="FIND COMICVINE MATCH" |
| controls | height | `auto` | 1 | a text="d6 → d4" |
| controls | height | `16px` | 1 | input aria-label=Rating from 0.5 to 5.0 in steps of 0.5 |
| controls | height | `46px` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| controls | height | `32px` | 1 | button aria-label=Send feedback |
| controls | min-height | `auto` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `0px` | 5 | button aria-label=Log out text="LOG OUT"; a text="d6 → d4"; input aria-label=Rating from 0.5 to 5.0 in steps of 0.5 |
| controls | min-height | `44px` | 5 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="SNOOZE" |
| controls | min-height | `36px` | 1 | button text="FIND COMICVINE MATCH" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 4 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| panels | background-color | `rgba(255, 255, 255, 0.04)` | 2 | section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| panels | background-color | `rgba(6, 182, 212, 0.09)` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| panels | border-color | `rgb(232, 213, 176)` | 3 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| panels | border-color | `rgba(6, 182, 212, 0.3)` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| panels | border-color | `rgba(255, 255, 255, 0.08)` | 1 | section text="ROLL RESULT Rolled 0 on d6 SERIES PROGRESS" |
| panels | border-color | `rgba(168, 85, 247, 0.15)` | 1 | section text="SERIES HISTORY Canonical series history unavailable" |
| panels | border-color | `rgba(168, 85, 247, 0.2)` | 1 | section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| panels | border-radius | `0px` | 4 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| panels | border-radius | `16px` | 3 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis"; section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| panels | box-shadow | `none` | 7 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| radii | border-radius | `8px` | 9 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 8 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss" |
| radii | border-radius | `12px` | 6 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button data-testid=save-and-continue text="MARK READ & SAVE" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `16px` | 3 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis"; section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `none` | 29 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 21 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | gap | `8px 12px` | 1 | header text="PILE ROLLER" |
| spacing | gap | `12px 24px` | 1 | section text="ROLL RESULT Rolled 0 on d6 SERIES PROGRESS" |
| spacing | margin-bottom | `0px` | 25 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `16px` | 3 | section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl"; section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis"; section text="SERIES HISTORY Canonical series history unavailable" |
| spacing | margin-bottom | `12px` | 1 | input aria-label=Rating from 0.5 to 5.0 in steps of 0.5 |
| spacing | margin-bottom | `8px` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| spacing | margin-top | `0px` | 29 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `0px` | 9 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| spacing | padding-bottom | `8px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `12px` | 6 | section text="ROLL RESULT Rolled 0 on d6 SERIES PROGRESS"; section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss" |
| spacing | padding-bottom | `16px` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| spacing | padding-bottom | `14px` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| spacing | padding-left | `12px` | 14 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 11 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| spacing | padding-left | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `16px` | 2 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| spacing | padding-right | `12px` | 14 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 11 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| spacing | padding-right | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `16px` | 2 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| spacing | padding-top | `0px` | 10 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss"; section text="SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Issue 1 of 20 · 50% compl" |
| spacing | padding-top | `8px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `12px` | 5 | section text="SERIES HISTORY Canonical series history unavailable"; section text="YOUR RATING 4.0 d6 → d4 More focused next roll Moves this thread to the front of"; button text="SNOOZE" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="PILE ROLLER THE COMIC SELECTED ISSUE Test Thread 1 #1 COPY TITLE FIX ISSUE # Iss" |
| spacing | padding-top | `16px` | 1 | section text="Your Place in the Story 📍 Test Thread 1 #1 YOU ARE HERE No continuity prerequis" |
| spacing | padding-top | `14px` | 1 | button data-testid=save-and-continue text="MARK READ & SAVE" |
| typography | font-family | `Outfit, sans-serif` | 30 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `12px` | 8 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-size | `10px` | 3 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="FIND COMICVINE MATCH" |
| typography | font-size | `14px` | 1 | a text="d6 → d4" |
| typography | font-weight | `400` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `900` | 7 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="FIND COMICVINE MATCH" |
| typography | font-weight | `700` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | letter-spacing | `normal` | 22 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1.8px` | 4 | button data-testid=save-and-continue text="MARK READ & SAVE"; button text="SNOOZE"; button aria-label=Skip current roll data-testid=skip-roll text="SKIP" |
| typography | letter-spacing | `0.5px` | 3 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="FIND COMICVINE MATCH" |
| typography | letter-spacing | `1.2px` | 1 | button aria-label=Log out text="LOG OUT" |
| typography | line-height | `24px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `16px` | 8 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | line-height | `15px` | 3 | button aria-label=Copy Test Thread 1 1 text="COPY TITLE"; button aria-label=Fix issue number text="FIX ISSUE #"; button text="FIND COMICVINE MATCH" |
| typography | line-height | `20px` | 1 | a text="d6 → d4" |

### queue at wide-desktop

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 24 | a aria-label=Roll page text="Roll"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 10 | button text="SHUFFLE"; button text="A-Z"; button text="NEW" |
| colors | background-color | `rgb(212, 137, 14)` | 3 | button aria-label=Read text="Read" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=Queue page text="Queue"; button text="Classic" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklab(0.666 0.0940116 0.152325 / 0.2)` | 1 | button text="POS" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `rgb(232, 213, 176)` | 8 | button text="Classic"; main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Roll page text="Roll"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | border-color | `rgb(107, 95, 80)` | 6 | button aria-label=Drag to reorder text="⠿"; button aria-label=Delete text="Delete" |
| colors | border-color | `rgb(160, 147, 126)` | 6 | button aria-label=Edit text="Edit"; button aria-label=Snooze text="😴 Snooze" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 4 | button text="SHUFFLE"; button text="A-Z"; button text="NEW" |
| colors | border-color | `rgb(255, 255, 255)` | 3 | button aria-label=Read text="Read" |
| colors | border-color | `oklch(0.553 0.013 58.071)` | 3 | button aria-label=Thread actions text="⋮" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 1 | a aria-label=Queue page text="Queue" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `oklab(0.769 0.0640531 0.176752 / 0.3)` | 1 | button text="POS" |
| colors | color | `rgb(232, 213, 176)` | 9 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| colors | color | `oklch(0.709 0.01 56.259)` | 9 | a aria-label=Roll page text="Roll"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | color | `rgb(107, 95, 80)` | 6 | button aria-label=Drag to reorder text="⠿"; button aria-label=Delete text="Delete" |
| colors | color | `rgb(160, 147, 126)` | 6 | button aria-label=Edit text="Edit"; button aria-label=Snooze text="😴 Snooze" |
| colors | color | `rgb(255, 255, 255)` | 3 | button aria-label=Read text="Read" |
| colors | color | `oklch(0.553 0.013 58.071)` | 3 | button aria-label=Thread actions text="⋮" |
| colors | color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Queue page text="Queue"; button text="POS" |
| colors | color | `oklch(0.869 0.005 56.366)` | 2 | button text="SHUFFLE"; input |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | border-width | `0px` | 34 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | border-width | `1px` | 5 | button text="SHUFFLE"; button text="POS"; button text="A-Z" |
| controls | height | `36px` | 13 | input; button aria-label=Read text="Read"; button aria-label=Edit text="Edit" |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `28px` | 4 | button aria-label=Log out text="LOG OUT"; button aria-label=Open Test Thread 1 text="Test Thread 1"; button aria-label=Open Test Thread 2 text="Test Thread 2" |
| controls | height | `32px` | 4 | button aria-label=Drag to reorder text="⠿"; button aria-label=Send feedback |
| controls | height | `24px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `29px` | 3 | button text="POS"; button text="A-Z"; button text="NEW" |
| controls | height | `44px` | 3 | button aria-label=Thread actions text="⋮" |
| controls | height | `48px` | 2 | button text="SHUFFLE"; button data-testid=queue-add-thread-desktop text="ADD THREAD" |
| controls | min-height | `auto` | 34 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `0px` | 5 | button aria-label=Log out text="LOG OUT"; button aria-label=Thread actions text="⋮"; button aria-label=Send feedback |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| panels | border-radius | `0px` | 2 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| panels | box-shadow | `none` | 2 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| radii | border-radius | `8px` | 31 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 7 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `24px` | 1 | button data-testid=queue-add-thread-desktop text="ADD THREAD" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `none` | 41 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 20px 25px -5px, rgba(0, 0, 0, 0.1) 0px 8px 10px -6px` | 1 | button data-testid=queue-add-thread-desktop text="ADD THREAD" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 33 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | gap | `6px` | 3 | button aria-label=Snooze text="😴 Snooze" |
| spacing | margin-bottom | `0px` | 42 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `40px` | 1 | header text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3" |
| spacing | margin-top | `0px` | 42 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `0px` | 27 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; header text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3"; button text="SHUFFLE" |
| spacing | padding-bottom | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `6px` | 4 | button aria-label=Log out text="LOG OUT"; button text="POS"; button text="A-Z" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `24px` | 1 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| spacing | padding-bottom | `40px` | 1 | div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| spacing | padding-left | `12px` | 21 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; button aria-label=Drag to reorder text="⠿" |
| spacing | padding-left | `8px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `16px` | 4 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; button aria-label=Read text="Read" |
| spacing | padding-left | `20px` | 2 | button text="SHUFFLE"; button data-testid=queue-add-thread-desktop text="ADD THREAD" |
| spacing | padding-right | `12px` | 21 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; button aria-label=Drag to reorder text="⠿" |
| spacing | padding-right | `8px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `16px` | 4 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; button aria-label=Read text="Read" |
| spacing | padding-right | `20px` | 2 | button text="SHUFFLE"; button data-testid=queue-add-thread-desktop text="ADD THREAD" |
| spacing | padding-top | `0px` | 28 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa"; header text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3" |
| spacing | padding-top | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `6px` | 4 | button aria-label=Log out text="LOG OUT"; button text="POS"; button text="A-Z" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `24px` | 1 | main text="READ QUEUE YOUR UPCOMING COMICS SHUFFLE ADD THREAD POS A-Z NEW 3 ⠿ #1 Test Threa" |
| typography | font-family | `Outfit, sans-serif` | 43 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 15 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `14px` | 12 | button aria-label=Read text="Read"; button aria-label=Edit text="Edit"; button aria-label=Snooze text="😴 Snooze" |
| typography | font-size | `12px` | 7 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-size | `18px` | 6 | button aria-label=Drag to reorder text="⠿"; button aria-label=Thread actions text="⋮" |
| typography | font-size | `10px` | 3 | button text="POS"; button text="A-Z"; button text="NEW" |
| typography | font-weight | `400` | 22 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `700` | 7 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `600` | 6 | button aria-label=Edit text="Edit"; button aria-label=Snooze text="😴 Snooze" |
| typography | font-weight | `900` | 5 | button text="SHUFFLE"; button data-testid=queue-add-thread-desktop text="ADD THREAD"; button text="POS" |
| typography | font-weight | `500` | 3 | button aria-label=Delete text="Delete" |
| typography | letter-spacing | `normal` | 37 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1px` | 3 | button text="POS"; button text="A-Z"; button text="NEW" |
| typography | letter-spacing | `1.2px` | 2 | button aria-label=Log out text="LOG OUT"; button text="SHUFFLE" |
| typography | letter-spacing | `1.8px` | 1 | button data-testid=queue-add-thread-desktop text="ADD THREAD" |
| typography | line-height | `24px` | 15 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `20px` | 12 | button aria-label=Read text="Read"; button aria-label=Edit text="Edit"; button aria-label=Snooze text="😴 Snooze" |
| typography | line-height | `16px` | 7 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | line-height | `28px` | 6 | button aria-label=Drag to reorder text="⠿"; button aria-label=Thread actions text="⋮" |
| typography | line-height | `15px` | 3 | button text="POS"; button text="A-Z"; button text="NEW" |

### history at wide-desktop

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 13 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=Crossovers page text="Crossovers" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=History page text="History"; button text="Classic" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=Crossovers page text="Crossovers" |
| colors | border-color | `rgb(232, 213, 176)` | 4 | button text="Classic"; main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 1 | a aria-label=History page text="History" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `oklch(0.553 0.013 58.071)` | 1 | a text="EXPORT SUMMARY" |
| colors | color | `oklch(0.709 0.01 56.259)` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=Crossovers page text="Crossovers" |
| colors | color | `rgb(232, 213, 176)` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| colors | color | `oklch(0.828 0.189 84.429)` | 1 | a aria-label=History page text="History" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `oklch(0.553 0.013 58.071)` | 1 | a text="EXPORT SUMMARY" |
| controls | border-width | `0px` | 14 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `24px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `23px` | 1 | a text="EXPORT SUMMARY" |
| controls | height | `15px` | 1 | a text="VIEW FULL SESSION →" |
| controls | height | `32px` | 1 | button aria-label=Send feedback |
| controls | min-height | `auto` | 11 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `0px` | 3 | button aria-label=Log out text="LOG OUT"; a text="VIEW FULL SESSION →"; button aria-label=Send feedback |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| panels | border-radius | `0px` | 2 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| panels | box-shadow | `none` | 2 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| radii | border-radius | `8px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 6 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `none` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 9 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | gap | `4px` | 1 | a text="VIEW FULL SESSION →" |
| spacing | margin-bottom | `0px` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `32px` | 1 | header text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY" |
| spacing | margin-top | `0px` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `0px` | 4 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; header text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY"; a text="VIEW FULL SESSION →" |
| spacing | padding-bottom | `4px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| spacing | padding-bottom | `80px` | 1 | div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| spacing | padding-left | `12px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; a text="EXPORT SUMMARY" |
| spacing | padding-left | `8px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `16px` | 1 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| spacing | padding-right | `12px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; a text="EXPORT SUMMARY" |
| spacing | padding-right | `8px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `16px` | 1 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| spacing | padding-top | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread "; header text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY" |
| spacing | padding-top | `4px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="HISTORY YOUR READING SESSION HISTORY EXPORT SUMMARY Aug 30 12:00 PM Test Thread " |
| typography | font-family | `Outfit, sans-serif` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `12px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-size | `10px` | 2 | a text="EXPORT SUMMARY"; a text="VIEW FULL SESSION →" |
| typography | font-weight | `400` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `700` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `900` | 1 | a text="VIEW FULL SESSION →" |
| typography | letter-spacing | `normal` | 15 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1px` | 2 | a text="EXPORT SUMMARY"; a text="VIEW FULL SESSION →" |
| typography | letter-spacing | `1.2px` | 1 | button aria-label=Log out text="LOG OUT" |
| typography | line-height | `24px` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `16px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | line-height | `15px` | 2 | a text="EXPORT SUMMARY"; a text="VIEW FULL SESSION →" |

### crossovers at wide-desktop

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 12 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=Crossovers page text="Crossovers"; button text="Classic" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklch(0.147 0.004 49.25)` | 1 | input |
| colors | background-color | `oklch(0.769 0.188 70.08)` | 1 | button text="Create crossover" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | border-color | `rgb(232, 213, 176)` | 4 | button text="Classic"; main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Crossovers page text="Crossovers"; a text="What is a crossover?" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `oklch(0.444 0.011 73.639)` | 1 | input |
| colors | border-color | `oklch(0.147 0.004 49.25)` | 1 | button text="Create crossover" |
| colors | color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | color | `rgb(232, 213, 176)` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| colors | color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Crossovers page text="Crossovers"; a text="What is a crossover?" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `oklch(0.97 0.001 106.424)` | 1 | input |
| colors | color | `oklch(0.147 0.004 49.25)` | 1 | button text="Create crossover" |
| controls | border-width | `0px` | 14 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | border-width | `1px` | 1 | input |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `24px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `46px` | 2 | input; button text="Create crossover" |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `auto` | 1 | a text="What is a crossover?" |
| controls | height | `32px` | 1 | button aria-label=Send feedback |
| controls | min-height | `auto` | 12 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `0px` | 3 | button aria-label=Log out text="LOG OUT"; a text="What is a crossover?"; button aria-label=Send feedback |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| panels | border-radius | `0px` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| panels | box-shadow | `none` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| radii | border-radius | `8px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `12px` | 2 | input; button text="Create crossover" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `none` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | margin-bottom | `0px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `24px` | 1 | header text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | margin-top | `0px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `0px` | 4 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; header text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; a text="What is a crossover?" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `10px` | 2 | input; button text="Create crossover" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | padding-bottom | `112px` | 1 | section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | padding-left | `12px` | 9 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; header text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | padding-left | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `16px` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; button text="Create crossover" |
| spacing | padding-right | `12px` | 9 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; header text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | padding-right | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `16px` | 2 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; button text="Create crossover" |
| spacing | padding-top | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog"; header text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `10px` | 2 | input; button text="Create crossover" |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="CONTINUITY Crossovers Name connected comics so their continuity is easy to recog" |
| typography | font-family | `Outfit, sans-serif` | 19 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 14 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `12px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-size | `14px` | 1 | a text="What is a crossover?" |
| typography | font-weight | `400` | 13 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `700` | 6 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | letter-spacing | `normal` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1.2px` | 1 | button aria-label=Log out text="LOG OUT" |
| typography | line-height | `24px` | 14 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `16px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | line-height | `20px` | 1 | a text="What is a crossover?" |

### continuity-plans at wide-desktop

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 11 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=Continuity Planner page text="Planner"; button text="Classic" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklch(0.769 0.188 70.08)` | 1 | button text="Create a plan" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | border-color | `rgb(232, 213, 176)` | 4 | button text="Classic"; main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 1 | a aria-label=Continuity Planner page text="Planner" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `oklch(0.147 0.004 49.25)` | 1 | button text="Create a plan" |
| colors | color | `oklch(0.709 0.01 56.259)` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | color | `rgb(232, 213, 176)` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| colors | color | `oklch(0.828 0.189 84.429)` | 1 | a aria-label=Continuity Planner page text="Planner" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `oklch(0.147 0.004 49.25)` | 1 | button text="Create a plan" |
| controls | border-width | `0px` | 13 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `24px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `44px` | 1 | button text="Create a plan" |
| controls | height | `32px` | 1 | button aria-label=Send feedback |
| controls | min-height | `auto` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `0px` | 2 | button aria-label=Log out text="LOG OUT"; button aria-label=Send feedback |
| controls | min-height | `44px` | 1 | button text="Create a plan" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| panels | border-radius | `0px` | 2 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| panels | box-shadow | `none` | 2 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| radii | border-radius | `8px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 4 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `12px` | 1 | button text="Create a plan" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `none` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 9 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | margin-bottom | `0px` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `20px` | 1 | header text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | margin-top | `0px` | 15 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | margin-top | `16px` | 1 | button text="Create a plan" |
| spacing | padding-bottom | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; header text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-left | `12px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 4 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; header text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-left | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `16px` | 1 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-left | `20px` | 1 | button text="Create a plan" |
| spacing | padding-right | `12px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 4 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; header text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-right | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `16px` | 1 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-right | `20px` | 1 | button text="Create a plan" |
| spacing | padding-top | `8px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `0px` | 5 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs"; header text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="CONTINUITY Reading plans Saved sequential reading plans, ordered last-saved firs" |
| typography | font-family | `Outfit, sans-serif` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 13 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `12px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `400` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `700` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `900` | 1 | button text="Create a plan" |
| typography | letter-spacing | `normal` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1.2px` | 1 | button aria-label=Log out text="LOG OUT" |
| typography | line-height | `24px` | 13 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `16px` | 4 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |

### continuity-planner at wide-desktop

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 22 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | background-color | `rgba(255, 255, 255, 0.04)` | 5 | input; button text="Add issue"; select text="Select a crossover" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 2 | input; select text="No issues available" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 1 | button text="Classic" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `rgb(212, 137, 14)` | 1 | button text="Save plan" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; input; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc" |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | border-color | `rgb(232, 213, 176)` | 4 | button text="Classic"; main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 3 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.2)` | 2 | input; select text="No issues available" |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `rgb(160, 147, 126)` | 1 | button aria-label=Remove lane Reading order text="Remove" |
| colors | border-color | `oklch(0.147 0.004 49.25)` | 1 | button text="Save plan" |
| colors | color | `rgb(232, 213, 176)` | 12 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| colors | color | `oklch(0.709 0.01 56.259)` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| colors | color | `rgb(160, 147, 126)` | 5 | button text="Add lane"; button aria-label=Move lane Reading order earlier text="↑"; button aria-label=Move lane Reading order later text="↓" |
| colors | color | `oklch(0.828 0.189 84.429)` | 3 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| colors | color | `oklch(0.869 0.005 56.366)` | 2 | input; select text="No issues available" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `oklch(0.147 0.004 49.25)` | 1 | button text="Save plan" |
| controls | border-width | `0px` | 17 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | border-width | `1px` | 11 | input; select text="No issues available"; button text="Add issue" |
| controls | height | `40px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `44px` | 6 | button text="Add issue"; select text="Select a crossover"; button text="Add crossover" |
| controls | height | `24px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `auto` | 3 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| controls | height | `38px` | 3 | input; select text="No issues available"; input aria-label=Lane Reading order name |
| controls | height | `36px` | 3 | button aria-label=Move lane Reading order earlier text="↑"; button aria-label=Move lane Reading order later text="↓"; button aria-label=Remove lane Reading order text="Remove" |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `42px` | 1 | input |
| controls | height | `32px` | 1 | button aria-label=Send feedback |
| controls | min-height | `auto` | 11 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `0px` | 8 | button aria-label=Log out text="LOG OUT"; a text="Continuity Plan"; a text="Lane" |
| controls | min-height | `44px` | 6 | button text="Add issue"; select text="Select a crossover"; button text="Add crossover" |
| controls | min-height | `36px` | 3 | button aria-label=Move lane Reading order earlier text="↑"; button aria-label=Move lane Reading order later text="↓"; button aria-label=Remove lane Reading order text="Remove" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 4 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc" |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| panels | border-color | `rgba(255, 255, 255, 0.08)` | 2 | section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc"; section text="READING LANES 1 lane · 0 steps Add lane ↑ ↓ Remove No steps in this lane yet." |
| panels | border-radius | `0px` | 4 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc" |
| panels | box-shadow | `none` | 4 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc" |
| radii | border-radius | `8px` | 11 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `12px` | 10 | input; select text="No issues available"; button text="Add issue" |
| radii | border-radius | `0px` | 9 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `3.35544e+07px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `none` | 33 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| spacing | gap | `normal` | 27 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 7 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | margin-bottom | `0px` | 31 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `24px` | 3 | header text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc"; section text="READING LANES 1 lane · 0 steps Add lane ↑ ↓ Remove No steps in this lane yet." |
| spacing | margin-top | `0px` | 29 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `4px` | 4 | input; select text="No issues available"; select text="Select a crossover" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `0px` | 17 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; header text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; a text="Continuity Plan" |
| spacing | padding-bottom | `8px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-bottom | `32px` | 1 | section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-bottom | `12px` | 1 | input |
| spacing | padding-left | `12px` | 15 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 11 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; header text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-left | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `16px` | 3 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; button text="Add issue"; button text="Add crossover" |
| spacing | padding-left | `20px` | 1 | button text="Cancel changes" |
| spacing | padding-left | `32px` | 1 | button text="Save plan" |
| spacing | padding-right | `12px` | 15 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 11 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; header text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-right | `8px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `16px` | 3 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; button text="Add issue"; button text="Add crossover" |
| spacing | padding-right | `20px` | 1 | button text="Cancel changes" |
| spacing | padding-right | `32px` | 1 | button text="Save plan" |
| spacing | padding-top | `0px` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; section text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral"; header text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-top | `8px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `20px` | 2 | section text="ADD STEPS To Reading order · issue or crossover Issue COMIC SERIES Type to searc"; section text="READING LANES 1 lane · 0 steps Add lane ↑ ↓ Remove No steps in this lane yet." |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="CONTINUITY Sequential planner Arrange issues and crossovers in one or more paral" |
| spacing | padding-top | `12px` | 1 | input |
| typography | font-family | `Outfit, sans-serif` | 34 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 19 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `14px` | 8 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| typography | font-size | `12px` | 7 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `700` | 17 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-weight | `400` | 16 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `900` | 1 | button text="Save plan" |
| typography | letter-spacing | `normal` | 29 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1.2px` | 3 | button aria-label=Log out text="LOG OUT"; input; select text="Select a crossover" |
| typography | letter-spacing | `1px` | 2 | input; select text="No issues available" |
| typography | line-height | `24px` | 19 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `20px` | 7 | a text="Continuity Plan"; a text="Lane"; a text="Crossover" |
| typography | line-height | `16px` | 6 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | line-height | `normal` | 2 | select text="No issues available"; select text="Select a crossover" |

### manual-picker-dialog at wide-desktop

| Category | Property | Value | Count | Examples |
| --- | --- | --- | ---: | --- |
| colors | background-color | `rgba(0, 0, 0, 0)` | 24 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 5 | button text="SHUFFLE QUEUE"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| colors | background-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 2 | a aria-label=Roll page text="Roll"; button text="Classic" |
| colors | background-color | `rgb(17, 14, 10)` | 1 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl" |
| colors | background-color | `rgba(17, 14, 10, 0.6)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | background-color | `oklab(0.691008 0.049379 0.13801 / 0.15)` | 1 | button text="d4" |
| colors | background-color | `rgb(212, 137, 14)` | 1 | button text="PICK MANUALLY" |
| colors | background-color | `oklab(0.268 0.00578283 0.00394448 / 0.6)` | 1 | button aria-label=Send feedback |
| colors | background-color | `rgba(17, 14, 10, 0.95)` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| colors | border-color | `oklch(0.709 0.01 56.259)` | 16 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | border-color | `rgb(232, 213, 176)` | 6 | button text="Classic"; main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| colors | border-color | `oklch(0.828 0.189 84.429)` | 3 | a aria-label=Roll page text="Roll"; a text="LADDER"; select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.05)` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| colors | border-color | `rgba(255, 255, 255, 0.08)` | 2 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| colors | border-color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | border-color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | border-color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | border-color | `rgb(212, 137, 14)` | 1 | button text="d4" |
| colors | border-color | `oklch(0.216 0.006 56.043)` | 1 | button text="PICK MANUALLY" |
| colors | border-color | `oklab(0.999994 0.0000455678 0.0000200868 / 0.1)` | 1 | button text="SHUFFLE QUEUE" |
| colors | border-color | `oklch(0.553 0.013 58.071)` | 1 | button aria-label=Close modal text="×" |
| colors | color | `oklch(0.709 0.01 56.259)` | 16 | a aria-label=Queue page text="Queue"; a aria-label=History page text="History"; a aria-label=Crossovers page text="Crossovers" |
| colors | color | `rgb(232, 213, 176)` | 11 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| colors | color | `oklch(0.828 0.189 84.429)` | 2 | a aria-label=Roll page text="Roll"; a text="LADDER" |
| colors | color | `oklch(0.869 0.005 56.366)` | 2 | button text="SHUFFLE QUEUE"; select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| colors | color | `rgb(160, 125, 63)` | 1 | button text="Ink Gold" |
| colors | color | `rgb(160, 216, 242)` | 1 | button text="Command Center" |
| colors | color | `oklch(0.704 0.191 22.216)` | 1 | button aria-label=Log out text="LOG OUT" |
| colors | color | `rgb(212, 137, 14)` | 1 | button text="d4" |
| colors | color | `oklch(0.216 0.006 56.043)` | 1 | button text="PICK MANUALLY" |
| colors | color | `oklch(0.553 0.013 58.071)` | 1 | button aria-label=Close modal text="×" |
| controls | border-width | `0px` | 27 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | border-width | `1px` | 5 | button text="SHUFFLE QUEUE"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| controls | height | `44px` | 11 | button text="d4"; button text="d6"; button text="d8" |
| controls | height | `40px` | 8 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | height | `24px` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| controls | height | `79px` | 3 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| controls | height | `32px` | 2 | button text="SHUFFLE QUEUE"; button aria-label=Send feedback |
| controls | height | `28px` | 1 | button aria-label=Log out text="LOG OUT" |
| controls | height | `200px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| controls | height | `38px` | 1 | select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| controls | min-height | `auto` | 14 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| controls | min-height | `44px` | 11 | button text="d4"; button text="d6"; button text="d8" |
| controls | min-height | `0px` | 7 | button aria-label=Log out text="LOG OUT"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| panels | background-color | `rgba(0, 0, 0, 0)` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| panels | background-color | `rgba(17, 14, 10, 0.95)` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| panels | border-color | `rgb(232, 213, 176)` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| panels | border-color | `rgba(255, 255, 255, 0.08)` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| panels | border-radius | `0px` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| panels | border-radius | `8px` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| panels | box-shadow | `none` | 2 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| panels | box-shadow | `rgba(0, 0, 0, 0.3) 0px 20px 25px -5px, rgba(0, 0, 0, 0.2) 0px 10px 10px -5px` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| radii | border-radius | `8px` | 20 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| radii | border-radius | `0px` | 6 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| radii | border-radius | `12px` | 5 | button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| radii | border-radius | `6px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| radii | border-radius | `3.35544e+07px` | 2 | div role=button aria-label=Roll the dice data-testid=main-die-3d; button aria-label=Send feedback |
| radii | border-radius | `24px` | 1 | button text="PICK THIS THREAD" |
| shadows | box-shadow | `none` | 34 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0.1) 0px 1px 3px 0px, rgba(0, 0, 0, 0.1) 0px 1px 2px -1px` | 1 | button aria-label=Send feedback |
| shadows | box-shadow | `rgba(0, 0, 0, 0.3) 0px 20px 25px -5px, rgba(0, 0, 0, 0.2) 0px 10px 10px -5px` | 1 | div role=dialog text="PICK MANUALLY × Choose the eligible thread you want to read next. THREAD Select " |
| shadows | box-shadow | `rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, rgba(0, 0, 0, 0) 0px 0px 0px 0px, oklab(0.769 0.0640531 0.176752 / 0.3) 0px 0px 0px 2px, rgba(0, 0, 0, 0) 0px 0px 0px 0px` | 1 | select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| spacing | gap | `normal` | 26 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; button text="Classic"; button text="Ink Gold" |
| spacing | gap | `12px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | gap | `8px 12px` | 1 | header text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| spacing | margin-bottom | `0px` | 35 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-bottom | `8px` | 2 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE" |
| spacing | margin-top | `0px` | 35 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| spacing | margin-top | `8px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | margin-top | `32px` | 1 | div role=button aria-label=Roll the dice data-testid=main-die-3d |
| spacing | padding-bottom | `0px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; button text="d4" |
| spacing | padding-bottom | `8px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-bottom | `12px` | 4 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-bottom | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-bottom | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-bottom | `24px` | 1 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| spacing | padding-left | `8px` | 13 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-left | `12px` | 11 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-left | `0px` | 8 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; a text="LADDER" |
| spacing | padding-left | `16px` | 5 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE" |
| spacing | padding-right | `8px` | 13 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-right | `12px` | 11 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-right | `0px` | 8 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; a text="LADDER" |
| spacing | padding-right | `16px` | 5 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; button text="PICK MANUALLY"; div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE" |
| spacing | padding-top | `0px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; div text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA"; button text="d4" |
| spacing | padding-top | `8px` | 10 | a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue"; a aria-label=History page text="History" |
| spacing | padding-top | `12px` | 4 | div role=button aria-label=Die face 1: Test Thread 1, issue 2. Open thread actions. text="1 Test Thread 1 #2 ISSUE"; div role=button aria-label=Die face 2: Test Thread 2, issue 1. Open thread actions. text="2 Test Thread 2 #1 ISSUE"; div role=button aria-label=Die face 3: Test Thread 3, issue 1. Open thread actions. text="3 Test Thread 3 #1 ISSUE" |
| spacing | padding-top | `4px` | 3 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| spacing | padding-top | `6px` | 1 | button aria-label=Log out text="LOG OUT" |
| spacing | padding-top | `24px` | 1 | main text="PILE ROLLER d4 d6 d8 d10 d12 d20 d30 d50 d100 AUTO LADDER d4 BALANCED PICK MANUA" |
| typography | font-family | `Outfit, sans-serif` | 37 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `16px` | 18 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-size | `10px` | 12 | button text="d4"; button text="d6"; button text="d8" |
| typography | font-size | `12px` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | font-size | `24px` | 1 | button aria-label=Close modal text="×" |
| typography | font-size | `14px` | 1 | select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |
| typography | font-weight | `400` | 19 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | font-weight | `900` | 13 | button text="d4"; button text="d6"; button text="d8" |
| typography | font-weight | `700` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | letter-spacing | `normal` | 32 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | letter-spacing | `1px` | 2 | button text="PICK MANUALLY"; button text="SHUFFLE QUEUE" |
| typography | letter-spacing | `1.2px` | 1 | button aria-label=Log out text="LOG OUT" |
| typography | letter-spacing | `0.25px` | 1 | button text="AUTO" |
| typography | letter-spacing | `1.8px` | 1 | button text="PICK THIS THREAD" |
| typography | line-height | `24px` | 19 | nav role=navigation aria-label=Desktop navigation text="Roll Queue History Crossovers Planner New Glossary ui_audit_reader_2043 THEME Cl"; a aria-label=Roll page text="Roll"; a aria-label=Queue page text="Queue" |
| typography | line-height | `15px` | 12 | button text="d4"; button text="d6"; button text="d8" |
| typography | line-height | `16px` | 5 | button text="Classic"; button text="Ink Gold"; button text="Command Center" |
| typography | line-height | `normal` | 1 | select text="Select a thread... Test Thread 1 (issue) Test Thread 2 (issue) Test Thread 3 (is" |

