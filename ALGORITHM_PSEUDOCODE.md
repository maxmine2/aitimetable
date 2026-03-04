# Event Timeslot Recommendation — Full Pseudocode

## Constants

```
W_PROXIMITY  = 3.0
W_LOCATION   = 3.0
W_SANDWICH   = 2.0
W_DEPARTURE  = 2.0

BUCKET_THRESHOLD = 4.0      // score ≥ this → "more likely"

PROXIMITY_DECAY = {
    1: 1.0,
    2: 0.55,
    3: 0.25,
    4: 0.1
}
// gap ≥ 5 → 0.0

DIRECTION_MOD_EARLY  = 0.6   // event before all campus classes
DIRECTION_MOD_LATE   = 0.8   // event after  all campus classes
DIRECTION_MOD_BETWEEN = 1.0  // event between campus classes

CAMPUS_FACTOR = {
    anchors_ge2:    1.0,     // ≥2 campus-anchoring classes today
    anchors_eq1:    0.6,     // exactly 1
    online_only:    0.15,    // 0 anchors, has online
    offcampus_only: 0.1      // 0 anchors, no online, only off-campus
}

LATE_HOUR_FACTOR = {
    1: 1.0,  2: 1.0,  3: 1.0,  4: 1.0,
    5: 0.95, 6: 0.85, 7: 0.7
}
// Reduced transport availability in late evening

TIREDNESS_TABLE = {
    // effective_load → factor
    // effective_load = class_count − 0.5 × gap_count
    1:  1.0,
    2:  0.95,
    3:  0.9,
    4:  0.85
}
// effective_load ≤ 1 → 1.0;  effective_load ≥ 5 → 0.8

ELECTIVE_PROXIMITY_DISCOUNT = 0.7
SOFT_CONFLICT_PENALTY       = 1.0
```

---

## Inputs

```
INPUTS:
    groups          : dict  // group_id → group object (with .schedule)
    rooms           : dict  // room_id → display name
    classify_room   : function(room_id) → {1, 2, 3, 4, 5}
    week_parity     : "odd" | "even"        // which week's timetable to use
    morning_cutoff  : int [1..7]            // earliest allowed slot (inclusive)
    evening_cutoff  : int [1..7]            // latest  allowed slot (inclusive)
    event_location  : 1 | 2                 // event venue building group
    allowed_days    : set of int [1..6]     // days the event may be held
```

---

## Outputs

```
OUTPUTS:
    top_3_slots : list of {
        day            : int,
        slot           : int,
        total_score    : float,
        more_likely    : list of group_id,
        less_likely    : list of group_id,
        have_class     : list of group_id
    }
    // sorted best (index 0) → worst (index 2)
```

---

## Phase 1 — Generate Candidates

```
FUNCTION generate_candidates(allowed_days, morning_cutoff, evening_cutoff):
    candidates ← []
    FOR each day d IN allowed_days:
        FOR slot s FROM morning_cutoff TO evening_cutoff:
            APPEND (d, s) TO candidates
    RETURN candidates
```

---

## Phase 2 — Filter Schedule for One Group on One Day

```
FUNCTION get_classes_today(group, day, week_parity):
    classes ← []
    FOR each entry E IN group.schedule:
        IF E.day ≠ day:
            CONTINUE
        IF E.week IS NOT NULL AND E.week ≠ week_parity:
            CONTINUE
        APPEND E TO classes
    RETURN classes
```

---

## Phase 3 — Classify a Single Class Entry

```
FUNCTION classify_entry(entry, classify_room):
    IF entry.room_id IS NULL:
        loc_group ← 5
    ELSE:
        loc_group ← classify_room(entry.room_id)

    is_anchor ← loc_group IN {1, 2, 4}
    RETURN { loc_group, is_anchor }
```

---

## Phase 4 — Score One Group for One Candidate

```
FUNCTION score_group(group, day, event_slot, week_parity,
                     classify_room, event_location):

    // ── 4.1  Get today's classes and classify each ──

    classes_today ← get_classes_today(group, day, week_parity)

    FOR each c IN classes_today:
        info ← classify_entry(c, classify_room)
        c.loc_group ← info.loc_group
        c.is_anchor ← info.is_anchor

    // ── 4.2  Conflict check ──

    conflicts ← [c FOR c IN classes_today WHERE c.slot = event_slot]

    IF ANY c IN conflicts WHERE c.type ≠ "elective":
        RETURN { bucket: "have class", score: NULL }

    soft_conflict ← FALSE

    IF conflicts IS NOT EMPTY:
        // all conflicts are electives
        soft_conflict ← TRUE
        // remove elective conflicts so they don't affect proximity calc
        classes_today ← [c FOR c IN classes_today WHERE c.slot ≠ event_slot]

    // ── 4.3  Empty day check ──

    IF classes_today IS EMPTY:
        RETURN { bucket: "less likely", score: 0.0 }

    // ── 4.4  Campus presence factor ──

    anchor_classes ← [c FOR c IN classes_today WHERE c.is_anchor]
    online_classes ← [c FOR c IN classes_today WHERE c.loc_group = 3]

    IF |anchor_classes| ≥ 2:
        campus_factor ← 1.0
    ELIF |anchor_classes| = 1:
        campus_factor ← 0.6
    ELIF |online_classes| > 0:
        campus_factor ← 0.15
    ELSE:
        campus_factor ← 0.1

    // ── 4.5  Find nearest classes (any type + anchor-only) ──

    any_before ← entry with MAX slot among classes_today WHERE slot < event_slot
                 (NULL if none)
    any_after  ← entry with MIN slot among classes_today WHERE slot > event_slot
                 (NULL if none)

    anchor_before ← entry with MAX slot among anchor_classes WHERE slot < event_slot
                    (NULL if none)
    anchor_after  ← entry with MIN slot among anchor_classes WHERE slot > event_slot
                    (NULL if none)

    // If multiple entries share the same slot, keep ALL for now;
    // tie-breaking by location is done in Step 4.7.

    // ── 4.6  Proximity factor P ──

    // Compute gap to nearest campus-anchoring class
    gap_anchor_before ← event_slot − anchor_before.slot   IF anchor_before ≠ NULL ELSE ∞
    gap_anchor_after  ← anchor_after.slot − event_slot     IF anchor_after  ≠ NULL ELSE ∞
    min_anchor_gap    ← MIN(gap_anchor_before, gap_anchor_after)

    IF min_anchor_gap < ∞:
        base_gap ← min_anchor_gap
    ELSE:
        // No campus-anchoring class today — use any-class gap as fallback
        gap_any_before ← event_slot − any_before.slot IF any_before ≠ NULL ELSE ∞
        gap_any_after  ← any_after.slot − event_slot  IF any_after  ≠ NULL ELSE ∞
        base_gap ← MIN(gap_any_before, gap_any_after)

    // Look up decay
    IF base_gap IN PROXIMITY_DECAY:
        P ← PROXIMITY_DECAY[base_gap]
    ELSE:
        P ← 0.0

    // Direction modifier
    IF anchor_before IS NULL AND anchor_after IS NOT NULL:
        // Event is before all campus classes → student must arrive early
        direction_mod ← DIRECTION_MOD_EARLY
    ELIF anchor_after IS NULL AND anchor_before IS NOT NULL:
        // Event is after all campus classes → student must stay late
        direction_mod ← DIRECTION_MOD_LATE
    ELSE:
        direction_mod ← DIRECTION_MOD_BETWEEN

    P ← P × direction_mod

    // ── 4.7  Location factor L ──

    // Pick reference class: nearest campus-anchoring class
    // If sandwiched between two anchors, pick whichever yields higher L

    FUNCTION compute_L(ref_loc_group, event_location):
        IF ref_loc_group = event_location:
            RETURN 1.0
        IF ref_loc_group IN {1, 2} AND event_location IN {1, 2}:
            RETURN 0.75                     // НК ↔ ГК, short walk
        IF ref_loc_group = 4:
            RETURN 0.5                      // other on-campus
        IF ref_loc_group = 3:
            RETURN 0.2                      // online
        RETURN 0.0                          // off-campus / unclear

    ref_class ← NULL

    IF min_anchor_gap < ∞:
        // At least one anchor exists
        IF anchor_before ≠ NULL AND anchor_after ≠ NULL:
            // Sandwiched between anchors — pick better L
            // (handle multiple entries at same slot: pick max L among them)
            L_before ← MAX compute_L(c.loc_group, event_location)
                        FOR c IN anchor_classes WHERE c.slot = anchor_before.slot
            L_after  ← MAX compute_L(c.loc_group, event_location)
                        FOR c IN anchor_classes WHERE c.slot = anchor_after.slot
            L ← MAX(L_before, L_after)
            ref_class ← the entry that produced the MAX L
        ELIF anchor_before ≠ NULL:
            L ← MAX compute_L(c.loc_group, event_location)
                 FOR c IN anchor_classes WHERE c.slot = anchor_before.slot
            ref_class ← that entry
        ELSE:
            L ← MAX compute_L(c.loc_group, event_location)
                 FOR c IN anchor_classes WHERE c.slot = anchor_after.slot
            ref_class ← that entry
    ELSE:
        // No anchors — use best loc_group among all today's classes
        L ← MAX compute_L(c.loc_group, event_location) FOR c IN classes_today
        ref_class ← that entry

    // ── 4.8  Elective proximity discount ──

    IF ref_class IS NOT NULL AND ref_class.type = "elective":
        P ← P × ELECTIVE_PROXIMITY_DISCOUNT

    // ── 4.9  Sandwich factor S ──

    is_sandwiched ← (any_before IS NOT NULL) AND (any_after IS NOT NULL)

    IF NOT is_sandwiched:
        S ← 0.0
    ELSE:
        before_anchor ← any_before.is_anchor
        after_anchor  ← any_after.is_anchor
        after_loc     ← any_after.loc_group
        before_loc    ← any_before.loc_group

        IF before_anchor AND after_anchor:
            S ← 1.0                          // genuine physical sandwich
        ELIF before_anchor AND after_loc = 3:
            S ← 0.5                          // after is online
        ELIF before_loc = 3 AND after_anchor:
            S ← 0.5                          // before is online
        ELIF before_anchor AND after_loc = 5:
            S ← 0.0                          // must leave for off-campus
        ELIF before_loc = 5 AND after_anchor:
            S ← 0.0                          // arriving from off-campus
        ELSE:
            S ← 0.0                          // both non-anchoring

    // ── 4.10  Departure pressure penalty D ──

    D ← 0.0

    IF any_after IS NOT NULL AND any_after.loc_group = 5:
        gap_to_departure ← any_after.slot − event_slot
        IF gap_to_departure = 1:
            D ← −W_DEPARTURE               // −2.0, must leave immediately
        ELIF gap_to_departure = 2:
            D ← −W_DEPARTURE / 2           // −1.0, tight
        // gap ≥ 3: D stays 0.0

    // ── 4.11  Tiredness factor T ──

    slots_before ← DISTINCT {c.slot FOR c IN classes_today WHERE c.slot < event_slot}

    IF |slots_before| = 0:
        tiredness_factor ← 1.0
    ELSE:
        class_count ← |slots_before|
        first_slot  ← MIN(slots_before)
        total_span  ← event_slot − first_slot       // slots from first class to event
        gap_count   ← total_span − class_count       // empty slots = rest breaks
        effective_load ← class_count − 0.5 × gap_count

        IF effective_load ≤ 1:
            tiredness_factor ← 1.0
        ELIF effective_load ≤ 4:
            tiredness_factor ← TIREDNESS_TABLE[⌊effective_load⌋]
        ELSE:
            tiredness_factor ← 0.8

    // ── 4.12  Late-hour factor ──

    late_hour_factor ← LATE_HOUR_FACTOR[event_slot]

    // ── 4.13  Combine ──

    raw_score ← (W_PROXIMITY × P)
              + (W_LOCATION  × L)
              + (W_SANDWICH  × S)
              + D

    raw_score ← MAX(raw_score, 0.0)

    score ← raw_score × campus_factor × tiredness_factor × late_hour_factor

    IF soft_conflict:
        score ← MAX(score − SOFT_CONFLICT_PENALTY, 0.0)

    // ── 4.14  Bucket ──

    IF score ≥ BUCKET_THRESHOLD:
        bucket ← "more likely"
    ELSE:
        bucket ← "less likely"

    RETURN { bucket, score }
```

---

## Phase 5 — Rank All Candidates

```
FUNCTION rank_candidates(groups, candidates, week_parity,
                         classify_room, event_location):

    results ← []

    FOR each (day, slot) IN candidates:

        total_score     ← 0.0
        more_likely     ← []
        less_likely     ← []
        have_class      ← []

        FOR each group_id, group IN groups:
            result ← score_group(group, day, slot, week_parity,
                                 classify_room, event_location)

            IF result.bucket = "have class":
                APPEND group_id TO have_class
            ELIF result.bucket = "more likely":
                APPEND group_id TO more_likely
                total_score ← total_score + result.score
            ELSE:
                APPEND group_id TO less_likely
                total_score ← total_score + result.score

        APPEND {
            day, slot, total_score,
            more_count:       |more_likely|,
            have_class_count: |have_class|,
            more_likely,
            less_likely,
            have_class
        } TO results

    // Sort: best first
    SORT results BY:
        total_score        DESC,     // primary
        more_count         DESC,     // secondary: prefer more "more likely"
        have_class_count   ASC       // tertiary: prefer fewer conflicts

    RETURN results[0..2]             // top 3
```

---

## Phase 6 — Entry Point

```
FUNCTION find_best_event_slots(groups, rooms, classify_room,
                               week_parity, morning_cutoff, evening_cutoff,
                               event_location, allowed_days):

    candidates ← generate_candidates(allowed_days,
                                     morning_cutoff, evening_cutoff)

    top_3 ← rank_candidates(groups, candidates, week_parity,
                            classify_room, event_location)

    RETURN top_3
```
