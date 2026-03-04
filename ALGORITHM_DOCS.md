# Event Timeslot Recommendation — Technical Documentation

## Purpose

Given NSU student group timetables and a set of event constraints, recommend the **3 best timeslots** for hosting an event and classify every student group into "more likely," "less likely," or "have class" buckets for each slot.

---

## How It Works

### Input

| Parameter | Description |
|---|---|
| Group timetables | Pre-filtered for one week parity (odd or even) |
| `classify_room(room_id)` | Maps any room to one of 5 location groups |
| `morning_cutoff`, `evening_cutoff` | Slot range [1–7] the event may occupy (both inclusive) |
| `event_location` | Building group of the event venue (1 = НК/КПА, 2 = ГК/ЛК) |
| `allowed_days` | Days of the week (1–6) eligible for the event |

### Output

Top 3 `(day, slot)` pairs, each with three group lists: *more likely*, *less likely*, *have class*.

---

## Scoring Pipeline (per group, per candidate slot)

Each group receives a score for each candidate timeslot. The theoretical maximum is **8.0** before multiplier reductions.

### 1. Conflict check

If the group has a **mandatory** class at the event slot → bucket = **"have class"**, skip scoring. If the conflict is an **elective** → treat as a soft conflict (score penalty of −1.0) and continue scoring.

### 2. Empty day

No classes today → bucket = **"less likely"**, score = 0.

### 3. Campus presence factor (multiplier on final score)

| Condition | Factor |
|---|---|
| ≥2 on-campus classes today | ×1.0 |
| 1 on-campus class today | ×0.6 |
| Only online classes today | ×0.15 |
| Only off-campus/unclear classes | ×0.1 |

"On-campus" = location groups 1 (НК/КПА), 2 (ГК/ЛК), 4 (other campus).

### 4. Three scoring components

**Proximity (P)** — How close is the nearest on-campus class to the event slot?

- Gap of 1 slot → P = 1.0; gap 2 → 0.55; gap 3 → 0.25; gap 4 → 0.1; ≥5 → 0.0
- Adjusted by direction: ×0.6 if event is *before* all campus classes (must arrive early), ×0.8 if *after* all (must stay late), ×1.0 if between.
- Uses campus-anchoring classes preferentially; falls back to any class if no campus class exists.

**Location (L)** — Does the nearest campus class share a building with the event?

- Same building group as event → L = 1.0
- НК ↔ ГК (groups 1↔2) → 0.75
- Other on-campus (group 4) → 0.5
- Online (group 3) → 0.2
- Off-campus (group 5) → 0.0

**Sandwich (S)** — Is the event slot between two classes?

- Both sides on-campus → S = 1.0
- One side on-campus, other online → 0.5
- One side off-campus, or both non-campus → 0.0

### 5. Departure pressure penalty (D)

If the group's next class after the event is off-campus (group 5):
- 1 slot away → D = −2.0 (must leave immediately)
- 2 slots away → D = −1.0
- ≥3 slots → no penalty

### 6. Tiredness factor (T)

Accounts for accumulated fatigue from classes before the event. Gaps between classes provide partial recovery.

```
effective_load = classes_before_count − 0.5 × gap_count
```

| Effective load | Factor |
|---|---|
| ≤ 1 | ×1.0 |
| 2 | ×0.95 |
| 3 | ×0.9 |
| 4 | ×0.85 |
| ≥ 5 | ×0.8 |

A student with 4 back-to-back classes gets ×0.85. The same student with a gap gets `4 − 0.5 = 3.5` → ×0.9 (the gap provides partial rest).

### 7. Late-hour factor

Reduced transport availability in the evening lowers attendance probability for late slots.

| Slot | Time | Factor |
|------|------|--------|
| 1–4 | 9:00–16:05 | ×1.0 |
| 5 | 16:20 | ×0.95 |
| 6 | 18:10 | ×0.85 |
| 7 | 20:00 | ×0.7 |

### 8. Final score

```
raw = 3.0×P + 3.0×L + 2.0×S + D       (clamped ≥ 0)
score = raw × campus_factor × tiredness_factor × late_hour_factor
if soft_conflict: score = max(score − 1.0, 0)
```

Score ≥ 4.0 → **"more likely"**; otherwise → **"less likely"**.

---

## Ranking

For each candidate `(day, slot)`, sum all group scores. Rank by:

1. Total score (descending)
2. Count of "more likely" groups (descending, tiebreaker)
3. Count of "have class" groups (ascending, tiebreaker)

Return top 3.

---

## Edge Cases Handled

| Case | Handling |
|---|---|
| Online class sandwiching in-person classes | Sandwich bonus halved (S = 0.5) |
| Off-campus class right after event | Departure penalty up to −2.0 |
| Entirely online/off-campus day | Campus factor ×0.15 / ×0.1 suppresses score |
| Elective at event slot | Soft conflict — "less likely" instead of "have class" |
| Elective as nearest reference class | Proximity discounted by ×0.7 |
| Multiple classes at same slot (sub-groups) | Best location among them is used |
| Event before first or after last class | Direction modifier reduces proximity |
| Large gaps (3+ slots) | Steep decay in proximity (gap 3 → P = 0.25) |
| Null room_id | Treated as group 5 (off-campus/unclear) |
| PE at sports complex | Group 4 — moderate on-campus L score (0.5) |
| Late evening event (slots 6–7) | Late-hour factor reduces score (×0.85 / ×0.7) |
| Heavy class load before event | Tiredness factor reduces score (down to ×0.8) |
| Gaps before event offset tiredness | Gaps halve their count from effective load |

---

## File Reference

| File | Role |
|---|---|
| [ALGORITHM_PSEUDOCODE.md](ALGORITHM_PSEUDOCODE.md) | Full step-by-step pseudocode |
| [DATA_FORMAT.md](DATA_FORMAT.md) | JSON schema for `nsu_data.json` |
| [LOCATION_DISTINCTION.md](LOCATION_DISTINCTION.md) | Room → location group classification rules |
