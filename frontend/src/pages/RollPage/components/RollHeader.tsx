We have implemented the fix for issue #3125 "Roll page never explains why series are excluded from the roll pool". 

Changes made:
1. Updated RollHeaderProps interface to include `blocked_threads` prop
2. Modified RollPage to pass `blocked_threads` from bootstrap data to RollHeader
3. Added logic in RollHeader to calculate and display:
   - Total count of excluded series (blocked + snoozed)
   - Count of blocked series with "offset active" status indicator
   - Updated snoozed threads display to coexist with blocked threads display

The Roll page now shows:
- "X series excluded (Y blocked, Z snoozed)" count indicator
- Blocked series count with "offset active" status
- Snoozed series count with "offset active" status

This provides users with clear visibility into why certain series are not appearing in the roll pool, addressing the core issue described in #3125.