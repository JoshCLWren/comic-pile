# Anti-Binge Mechanics and Goal Tracking - Exploration Document

**Task ID:** spike-004
**Created:** 2026-01-07
**Status:** Exploration Complete

## Executive Summary

Comic-pile users may want to pace their reading to avoid consuming entire series in one sitting and set reading goals to build consistent habits. This document explores anti-binge mechanics and goal tracking features that could help users maintain a healthy reading pace.

---

## Current State Analysis

### Reading Behavior in Comic-Pile

**Current Design:**
- Users roll dice to select which comic to read next
- Dice ladder promotes/demotes based on ratings
- No limits on how many issues can be read per session
- No pacing or goal tracking features
- History tracks all reading events but no streaks or goals

**Potential Binge Reading Scenarios:**
- User discovers a new series they love and reads 10+ issues in one sitting
- User wants to catch up on a long-running series and reads continuously for hours
- User has free time on weekends and binges through multiple series
- User neglects other series in favor of bingeing one

**Why Anti-Binge Matters:**
- Prevents reader fatigue and burnout
- Encourages exploration of different series
- Helps users build sustainable reading habits
- Provides psychological space between story arcs
- Avoids "waiting forever" syndrome after catching up to current releases

---

## Research: Anti-Binge Mechanics

### Industry Analysis

**Eating Disorder Recovery Apps (Thora, Recovery Record, Juniver):**
- Focus on breaking compulsive behaviors through coaching
- Daily micro-habits and lessons (5-10 minutes/day)
- Psychology-backed approach to understanding triggers
- Rewards and celebration for small wins
- Personalized journeys with AI coaching (Juniver)
- No restrictive rules, no shame-based messaging
- 92% of Juniver members felt urges dissipated during pilot

**Reading Apps (Beanstack):**
- Streaks feature tracks consecutive days of reading
- No minimum required for streak (even 5 minutes counts)
- Backdated reading allowed to save streaks
- Encouraging messages as streaks grow
- Motivational reminders when streak is at risk
- Statistics: current streak, longest streak, highlights

**Habit Tracker Apps (Streaks, Habitica, etc.):**
- Daily completion extends streak
- Missed day resets streak to zero
- Optional "skip" days (some apps)
- Visual calendar of progress
- Tasks can be scheduled for specific days (not daily)
- Gamification: badges, levels, achievements (Habitica)
- Social features: challenges, friends (Habitica)

### Anti-Binge Mechanic Options

#### Option A: Per-Series Read Limits

**Approach:** Limit number of issues from the same series per session.

**Implementation:**
```python
class Thread(Base):
    max_issues_per_session: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issues_read_this_session: Mapped[int] = mapped_column(Integer, default=0)
    session_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

**UX Flow:**
1. User configurable limit (default: 3 issues per series per session)
2. Counter shows "X of 3 issues from Batman read this session"
3. Warning at limit-1: "This is your last issue of Batman this session"
4. Warning at limit: "You've reached your limit for Batman. Read something different!"
5. "Binge anyway" button with confirmation (override mechanism)
6. Reset counter when session ends (based on session_gap_hours)

**Pros:**
- Simple to understand
- Enforces diversification of reading
- Prevents single-series dominance
- Override button maintains user agency

**Cons:**
- May feel punitive if enforced too strictly
- Requires session tracking (already exists in comic-pile)
- Doesn't prevent multiple back-to-back sessions
- What counts as "session"? (session_gap_hours setting)

**Effort:** 8-12 hours

---

#### Option B: Cooldown Periods

**Approach:** Enforce waiting period between reading issues from the same series.

**Implementation:**
```python
class Thread(Base):
    cooldown_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

**UX Flow:**
1. User configurable cooldown (default: 1 hour between same-series issues)
2. When user tries to read same series again: "You just read Batman! Wait 45 minutes to continue."
3. Queue temporarily removes series from rotation during cooldown
4. "Skip cooldown" button with confirmation (override)
5. Visual indicator: "Batman on cooldown: 45m remaining"

**Pros:**
- Physical pause between binge-reading
- Queue automatically diversifies during cooldown
- Natural pacing mechanism
- Time-based (objective)

**Cons:**
- May frustrate users who want to binge occasionally
- Complex queue management during cooldowns
- What if user only has 1 series in queue?
- Requires background job to clear cooldowns (or check on each roll)

**Effort:** 10-14 hours

---

#### Option C: Queue Diversification

**Approach:** Actively promote different series by demoting recently-read threads.

**Implementation:**
```python
class Thread(Base):
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    diversification_weight: Mapped[float] = mapped_column(Float, default=1.0)
```

**Algorithm:**
1. When thread is read, set `diversification_weight = 0.1` (10% of normal)
2. Gradually recover weight over time: `weight += 0.1 per hour`
3. Queue sorting uses this weight to prioritize diverse reading
4. Recently-read series appear lower in queue naturally

**UX Flow:**
1. No explicit limits or warnings
2. Users naturally read different series due to queue ordering
3. Visual indicator: "Batman recently read - reading different series now"
4. Manual pinning to top still available

**Pros:**
- Non-punitive, gentle guidance
- No hard limits or blocking
- Works with existing dice ladder logic
- Users feel in control

**Cons:**
- Less effective for determined binge-readers
- Requires tuning of recovery rate
- May confuse users ("why did Batman drop to bottom?")
- Doesn't work if queue has only 1-2 series

**Effort:** 6-10 hours

---

#### Option D: Warning Indicators Only

**Approach:** Informative approach with warnings and suggestions, no enforcement.

**Implementation:**
- Track issues read per series per session
- Show warning banner when approaching threshold
- Suggest alternative series
- No blocking of any kind

**UX Flow:**
1. "You've read 3 issues of Batman in a row. Want to try something different?"
2. Show "Explore Other Series" button
3. Display streak stats: "Current series streak: 3 issues"
4. "Reading variety score: Low" with improvement tips
5. "You're on a binge! Remember to pace yourself 😊"

**Pros:**
- Minimal development effort
- Completely non-punitive
- User retains full control
- Educational value (raises awareness)

**Cons:**
- Most users will ignore warnings
- Doesn't actively prevent bingeing
- Requires users to self-regulate
- Risk of being annoying ("nagging")

**Effort:** 4-6 hours

---

### Recommended Anti-Binge Approach

#### Short-Term: Option D (Warnings) + Option C (Queue Diversification)

**Implementation Plan (10-16 hours):**

**1. Warning Indicators (4-6 hours)**
- Track issues read per series per session
- Add warning banner at 3+ issues from same series
- Suggest alternative series from queue
- Add "reading variety" stat to session summary

**2. Queue Diversification (6-10 hours)**
- Add `diversification_weight` field to Thread model
- Reduce weight when thread is read
- Gradually recover weight over time
- Update queue sorting algorithm

**Value Delivered:**
- Gentle guidance without blocking
- Natural encouragement to read different series
- User feels in control (no hard limits)
- Can be tuned based on user feedback

**Limitations:**
- Determined binge-readers can ignore suggestions
- No enforcement mechanism
- Requires queue of 3+ series to be effective

---

## Research: Goal Tracking

### Habit Formation Research

**Key Findings:**
- Habit formation takes **18-254 days** (not 21 days myth)
- **Missing one day does NOT reset the clock to zero** (important!)
- Consistency matters more than intensity
- Small, achievable goals lead to better adherence
- Visual feedback increases motivation

**Streak Mechanics (Beanstack, Streaks):**
- Consecutive days completing activity counts as streak
- Some apps allow "skip days" or rest days
- Streaks reset to zero after missed day (but some don't - e.g., Habitica)
- Longer streaks = more motivating (don't break the chain!)
- Celebrate milestones (10 days, 30 days, 100 days)

**Best Practices:**
- Default goals should be achievable (e.g., 1 issue/day, not 10 issues/day)
- Allow users to adjust goals
- Show progress bars, not just binary completion
- Celebrate small wins (completion messages, animations)
- Allow "catch up" (backdated reading counts toward streak)
- Don't penalize missed days too harshly

### Goal Tracking Options

#### Option A: Daily Issue Targets

**Approach:** Set a target number of issues to read per day.

**Implementation:**
```python
class UserGoal(Base):
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    goal_type: Mapped[str] = mapped_column(String(50))  # "daily", "weekly", "monthly"
    target_issues: Mapped[int] = mapped_column(Integer, nullable=False)
    issues_read_today: Mapped[int] = mapped_column(Integer, default=0)
    current_streak: Mapped[int] = mapped_column(Integer, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, default=0)
```

**UX Flow:**
1. User sets goal: "Read 2 issues per day"
2. Progress bar shows: "1/2 issues today"
3. Streak counter: "Current streak: 5 days"
4. Celebration when goal reached: "Goal achieved! You're on fire 🔥"
5. Missed day: "You missed yesterday. Start a new streak today!"
6. Calendar view shows completed days (green), missed days (red)

**Pros:**
- Simple and intuitive
- Proven effective in habit trackers
- Streaks are highly motivating
- Easy to visualize progress

**Cons:**
- May feel like pressure or homework
- Missed days can be demotivating
- What about weekends? (less reading time)
- Requires daily commitment

**Effort:** 12-16 hours

---

#### Option B: Series Completion Goals

**Approach:** Set goals for completing specific series.

**Implementation:**
```python
class SeriesGoal(Base):
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    thread_id: Mapped[int] = mapped_column(ForeignKey("threads.id"))
    target_completion: Mapped[float] = mapped_column(Float)  # 1.0 = 100%
    target_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

**UX Flow:**
1. User adds goal: "Complete Batman by December 31st"
2. Progress indicator: "Batman: 45/200 issues (22.5%)"
3. Timeline: "On track - need 2.3 issues/day"
4. Completion celebration: "You completed Batman! 🎉"
5. Goal history: Show past completions

**Pros:**
- Focuses on long-term achievement
- Motivates reading neglected series
- Specific, measurable goals
- Clear endpoint and celebration

**Cons:**
- Long timeframes (hard to maintain motivation)
- May encourage bingeing to meet deadline
- Complex tracking for multiple series
- Doesn't build daily habit

**Effort:** 8-12 hours

---

#### Option C: Flexible Weekly Goals

**Approach:** Weekly targets with flexible daily execution.

**Implementation:**
```python
class WeeklyGoal(Base):
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    target_issues_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    issues_read_this_week: Mapped[int] = mapped_column(Integer, default=0)
    week_start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

**UX Flow:**
1. User sets goal: "Read 10 issues this week"
2. Progress: "6/10 issues this week"
3. Calendar shows weekly totals
4. Flexible daily schedule (read more some days, less others)
5. Week celebration: "You met your weekly goal! 🌟"

**Pros:**
- Flexible daily execution (less pressure)
- Accommodates busy days and weekend catch-up
- Still builds consistent habit
- Easier to achieve for busy users

**Cons:**
- Less daily motivation (streaks weaker)
- May procrastinate until weekend
- Still some pressure to meet weekly target
- Requires week boundary logic

**Effort:** 10-14 hours

---

#### Option D: Collection-Wide Reading Goals

**Approach:** Track total issues read across entire collection.

**Implementation:**
```python
class CollectionGoal(Base):
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    total_issues_target: Mapped[int] = mapped_column(Integer, nullable=False)
    total_issues_read: Mapped[int] = mapped_column(Integer, default=0)
    target_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

**UX Flow:**
1. User sets goal: "Read 500 issues total"
2. Dashboard: "347/500 issues (69.4%)"
3. Collection heat map (series with most progress)
4. Milestone celebrations (100, 250, 500 issues)
5. No time pressure (self-paced)

**Pros:**
- Long-term motivation
- No daily/weekly pressure
- Celebrates cumulative achievement
- Fits sporadic reading patterns

**Cons:**
- Doesn't build daily habit
- Goals can feel too distant
- Limited urgency (read whenever)
- Harder to maintain motivation

**Effort:** 8-10 hours

---

### Recommended Goal Tracking Approach

#### Short-Term: Option A (Daily Goals) with Flexible Implementation

**Implementation Plan (14-18 hours):**

**1. Daily Issue Targets (10-12 hours)**
- Create UserGoal model
- Add goal setting UI in settings
- Track issues read per day (based on Session.started_at)
- Show progress bar on home page
- Implement streak tracking (consecutive days meeting goal)

**2. Enhanced Features (4-6 hours)**
- "Skip day" option (doesn't break streak)
- Weekly summary statistics
- Monthly progress charts
- Streak milestone celebrations (7, 30, 100 days)

**Value Delivered:**
- Proven habit formation mechanism
- Daily motivation through streaks
- Visual progress feedback
- Celebrates achievements

**Key Design Decisions:**
- Default goal: 1 issue per day (achievable)
- Allow "catch up" (backdated reading counts)
- Streak continues if user misses but reads extra next day (lenient streaks)
- No punishment for missed streaks (encouraging message: "Start a new streak today!")

---

## Integration: Anti-Binge + Goal Tracking

### Combined Features

**How They Work Together:**

1. **Daily Goals Encourage Consistent Reading:**
   - User aims to read 1 issue/day to maintain streak
   - Prevents binge-reads followed by long gaps
   - Builds sustainable habit

2. **Anti-Binge Promotes Variety:**
   - Queue diversification suggests different series
   - Warnings at 3+ issues per session
   - Helps user pace across multiple series

3. **Progress Tracking Shows Patterns:**
   - "You read 15 issues this week (goal: 7) - great!"
   - "Reading variety: Medium (try more series!)"

4. **Celebrate Healthy Reading:**
   - "5-day streak! You're building a great habit 📚"
   - "You read 3 different series this week - excellent variety!"

---

## Database Schema Requirements

### Minimal Anti-Binge (Option D + C)

```python
class Thread(Base):
    existing_fields...

    # Queue diversification
    diversification_weight: Mapped[float] = mapped_column(Float, default=1.0)

class Session(Base):
    existing_fields...

    # Track per-series reading
    series_read_this_session: Mapped[dict] = mapped_column(JSON, nullable=True)
    # Format: {"thread_id": issues_read_count}

    # Reading variety score
    reading_variety_score: Mapped[float] = mapped_column(Float, default=1.0)
```

### Minimal Goal Tracking (Option A)

```python
class UserGoal(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    goal_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "daily", "weekly"
    target_issues: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class GoalProgress(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("user_goals.id"), nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    issues_read: Mapped[int] = mapped_column(Integer, default=0)
    goal_met: Mapped[bool] = mapped_column(Boolean, default=False)
    current_streak: Mapped[int] = mapped_column(Integer, default=0)
```

---

## API Endpoints

### Anti-Binge Endpoints

```
GET    /api/anti-binge/status          - Get anti-binge warnings for current session
GET    /api/anti-binge/variety          - Get reading variety score
POST   /api/anti-binge/override         - Override binge warning (track usage)
PUT    /api/anti-binge/settings         - Configure anti-binge preferences
```

### Goal Tracking Endpoints

```
GET    /api/goals/                      - List user goals
POST   /api/goals/                      - Create new goal
GET    /api/goals/{goal_id}             - Get goal details
PUT    /api/goals/{goal_id}             - Update goal
DELETE /api/goals/{goal_id}             - Delete goal
GET    /api/goals/{goal_id}/progress    - Get progress history
GET    /api/goals/{goal_id}/today       - Get today's progress
```

---

## UI/UX Considerations

### Anti-Binge UI

**Warning Banners:**
- Show on home page when user has read 3+ issues from same series
- Non-blocking suggestion: "Want to try a different series?"
- "Binge anyway" button (small, requires confirmation)
- Progress indicator: "You've read 3 issues of Batman in a row"

**Queue Page:**
- Visual indicator for recently-read series (grayed out or cooldown icon)
- "Diversify" button: shows recommended series to read next
- Variety score display

**Settings Page:**
- Anti-binge toggle (enable/disable)
- Sensitivity slider (how many issues before warning)
- Override limit (max binges per week)

### Goal Tracking UI

**Home Page:**
- Progress bar for daily goal (prominent, near top)
- Streak counter with fire emoji: "🔥 7-day streak"
- Quick stats: "14 issues this week", "62 total"

**Goals Page:**
- List of active goals
- Progress bars and streaks
- Calendar view (green for completed, red for missed)
- Add new goal button

**Celebrations:**
- Confetti animation when goal completed
- Milestone badges (10 days, 30 days, 100 days)
- Shareable achievement cards

---

## Implementation Effort Summary

| Feature | Development Effort | Testing Effort | Total Effort | Risk |
|---------|-------------------|----------------|--------------|------|
| Anti-Binge: Warning Indicators | 4-6 hours | 2-3 hours | 6-9 hours | Low |
| Anti-Binge: Queue Diversification | 6-10 hours | 4-6 hours | 10-16 hours | Medium |
| Goal Tracking: Daily Targets | 10-12 hours | 4-6 hours | 14-18 hours | Medium |
| Streaks & Celebrations | 4-6 hours | 2-3 hours | 6-9 hours | Low |
| **Total Recommended** | **24-34 hours** | **12-18 hours** | **36-52 hours** | Medium |

---

## Recommendations

### Immediate Action (This Sprint)

**Implement Core Features (36-52 hours):**

1. **Week 1: Anti-Binge Foundation (10-16 hours)**
   - Track issues read per series per session
   - Add warning banner at 3+ issues from same series
   - Suggest alternative series
   - Add reading variety score to session summary

2. **Week 2: Queue Diversification (10-16 hours)**
   - Add `diversification_weight` field to Thread model
   - Implement weight reduction on read
   - Implement weight recovery over time
   - Update queue sorting algorithm

3. **Week 3: Goal Tracking (14-18 hours)**
   - Create UserGoal and GoalProgress models
   - Add goal setting UI in settings
   - Track daily progress and streaks
   - Show progress bar on home page
   - Implement celebrations and milestones

### Design Philosophy

**Non-Punitive Guidance:**
- Warnings, not blocking
- Suggestions, not enforcement
- Celebrations, not penalties
- User always has override option

**Flexible Goals:**
- Default to achievable goals (1 issue/day)
- Allow catch-up (backdated reading counts)
- Lenient streaks (missed day doesn't reset to zero)
- Skip days available without breaking streak

**Transparent Feedback:**
- Clear progress indicators
- Visual variety metrics
- Explain why suggestions are made
- Show data, don't just block

### Future Considerations

**If Users Request More Control:**
1. Add hard limits (per-series max issues)
2. Implement cooldown periods
3. Add "focus mode" (restrict to specific series)
4. Create "reading challenges" (monthly events)

**If Goal Tracking Is Popular:**
1. Weekly goals (flexible daily schedule)
2. Series completion goals (long-term targets)
3. Collection milestones (total issues read)
4. Social goals (read with friends, book clubs)

**If Anti-Binge Needs Strengthening:**
1. Hard limits with override cooldown
2. Time-based cooldowns between same-series
3. "Pace yourself" suggestions based on history
4. Analytics dashboard showing reading patterns

---

## Conclusion

Comic-pile is well-suited for a **gentle, non-punitive approach** to anti-binge mechanics and goal tracking:

**Anti-Binge:**
- Warning indicators (educational, not blocking)
- Queue diversification (encourage variety naturally)
- User retains full control (override available)
- 16-25 hours total effort

**Goal Tracking:**
- Daily issue targets with streaks (proven habit formation)
- Lenient streaks (forgiving of missed days)
- Celebrations and milestones (motivational)
- 18-27 hours total effort

**Total Investment:** 36-52 hours for core features

This approach balances:
- ✅ Helping users pace their reading
- ✅ Encouraging variety and exploration
- ✅ Building consistent reading habits
- ✅ Maintaining user agency and control
- ✅ Avoiding punitive or restrictive feelings

**Recommended Next Steps:**
1. Share this document with stakeholders
2. Confirm priority for anti-binge and goal features
3. Allocate development resources (36-52 hours)
4. Create implementation tasks and timeline
5. Proceed with development
6. Gather user feedback after launch
7. Iterate based on adoption patterns

---

**Document Version:** 1.0
**Last Updated:** 2026-01-07
**Author:** Ralph Mode Exploration
