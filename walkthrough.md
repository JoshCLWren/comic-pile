# Mobile UX Audit — Complete Findings

Seeded **15 threads** and **124 issue-level dependencies** (Ultimate Universe reading order), then ran 3 browser sessions.

## Browser Recordings

````carousel
![Session 1: Login, empty queue, create thread](/home/josh/.gemini/antigravity/brain/f9a637fc-a6b6-4d22-8a36-7dc550d2502e/mobile_ux_login_1773713695274.webp)
<!-- slide -->
![Session 2: Queue with blocked threads, action sheet, dependency builder](/home/josh/.gemini/antigravity/brain/f9a637fc-a6b6-4d22-8a36-7dc550d2502e/dependency_ux_test_1773714106651.webp)
<!-- slide -->
![Session 3: Dependency visualizer / flowchart testing](/home/josh/.gemini/antigravity/brain/f9a637fc-a6b6-4d22-8a36-7dc550d2502e/dependency_visualizer_1773714498956.webp)
````

---

## 1. Queue with 15 Blocked Threads

![Queue with 🔒 blocked threads](/home/josh/.gemini/antigravity/brain/f9a637fc-a6b6-4d22-8a36-7dc550d2502e/queue_populated_mobile_1773714124941.png)

- 🔒 icons work — but don't say *what* is blocking
- No reading order progress anywhere
- No "what to read next" guidance

---

## 2. Dependency Builder = Flat Dump

![Dependency builder — endless scrolling list](/home/josh/.gemini/antigravity/brain/f9a637fc-a6b6-4d22-8a36-7dc550d2502e/dependency_builder_mobile_1773714143341.png)

Every dependency shown as "Title #N · ISSUE-LEVEL BLOCK · REMOVE". No grouping, no order, no progress. For Ultimate Spider-Man this list has **30+ items** you must scroll through.

---

## 3. Flowchart is HIDDEN on Mobile

> [!CAUTION]
> The dependency flowchart SVG uses `hidden md:block` CSS — it simply **does not exist** at mobile width.

The "View Flowchart" toggle button is buried at the bottom of the dependency list. Even when the browser was widened to trigger it, it rendered a **6590px-wide horizontal SVG** with 70 nodes — requiring extensive pan/zoom.

````carousel
![Full page height showing the flowchart toggle buried at bottom](/home/josh/.gemini/antigravity/brain/f9a637fc-a6b6-4d22-8a36-7dc550d2502e/dependency_flowchart_full_height_1773714768395.png)
<!-- slide -->
![Flowchart at desktop width — modal overlaying queue with massive node graph](/home/josh/.gemini/antigravity/brain/f9a637fc-a6b6-4d22-8a36-7dc550d2502e/dependency_flowchart_maximized_full_1773714625410.png)
````

---

## 4. Roll Page — 14 Threads Silently Hidden

![Only Batman shows in the roll pool — 14 blocked threads disappeared](/home/josh/.gemini/antigravity/brain/f9a637fc-a6b6-4d22-8a36-7dc550d2502e/roll_page_blocked_filtered_1773714217740.png)

Dependencies work correctly (blocked threads filtered out) but no explanation of why 14/15 threads disappeared.

---

## 5. Simple Counter Shouldn't Exist

![Create thread modal showing Simple Counter toggle](/home/josh/.gemini/antigravity/brain/f9a637fc-a6b6-4d22-8a36-7dc550d2502e/create_thread_modal.png)

User confirmed: remove this option entirely.

---

## Issues Ranked by Severity

| # | Problem | Impact |
|---|---------|--------|
| 1 | **Flowchart hidden on mobile** | The main visualization doesn't exist on the primary platform |
| 2 | **Dependency builder is a flat list** | 30+ items with no grouping — unusable for managing reading orders |
| 3 | **No inline blocking info on cards** | 🔒 without context forces deep navigation |
| 4 | **No reading order progress** | Can't answer "what's next?" or "how far am I?" |
| 5 | **Roll page hides threads silently** | 14 threads vanish without explanation |
| 6 | **Simple Counter** should be removed | Prevents dependency tracking |
| 7 | **3D die too large on mobile** | Pushes content below fold |
