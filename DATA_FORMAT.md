# NSU Timetable Data — JSON Schema Documentation

This document describes the structure of `nsu_data.json` produced by `analysis.py`.

The file is a single JSON object with four top-level keys:

```
{
  "bell_schedule": { ... },
  "teachers":      { ... },
  "rooms":         { ... },
  "groups":        { ... }
}
```

---

## `bell_schedule`

A lookup table that maps **time-slot numbers** (1–7) to their actual bell-ring times. Each slot is split into two 45-minute halves with a 5-minute break in between.

| Key | Type   | Description                        |
|-----|--------|------------------------------------|
| `"1"` – `"7"` | object | A slot object (see below) |

### Slot object

| Field   | Type   | Example         | Description                    |
|---------|--------|-----------------|--------------------------------|
| `half1` | string | `"9:00-9:45"`   | First 45-minute half of the slot  |
| `half2` | string | `"9:50-10:35"`  | Second 45-minute half of the slot |

### Full bell schedule

| Slot | Half 1        | Half 2        |
|------|---------------|---------------|
| 1    | 9:00 – 9:45   | 9:50 – 10:35  |
| 2    | 10:50 – 11:35 | 11:40 – 12:25 |
| 3    | 12:40 – 13:25 | 13:30 – 14:15 |
| 4    | 14:30 – 15:15 | 15:20 – 16:05 |
| 5    | 16:20 – 17:05 | 17:10 – 17:55 |
| 6    | 18:10 – 18:55 | 19:00 – 19:45 |
| 7    | 20:00 – 20:45 | 20:50 – 21:35 |

---

## `teachers`

A flat dictionary mapping **teacher IDs** to display names.

| Key (teacher ID) | Value (string) |
|-------------------|----------------|
| UUID string from the website (e.g. `"aae52064-015d-11e6-8152-000c29b4927a"`) | Full name (e.g. `"Бардаков В.Г."`) |

These IDs are extracted from the `href` attribute of `<a class="tutor" href="/teacher/{uuid}">` elements on group schedule pages. They are stable across the site and can be used to look up any teacher referenced in a group's schedule.

---

## `rooms`

A flat dictionary mapping **room IDs** to display names.

| Key (room ID) | Value (string) |
|----------------|----------------|
| Composite key from `room_view()` onclick params (e.g. `"nk_5_301_798"`) **or** plain display text for rooms without an onclick link (e.g. `"Ауд. 209 КПА"`) | Display name shown on the schedule (e.g. `"5207"` or `"Ауд. 209 КПА"`) |

Room IDs come in two flavors:
- **Linked rooms**: Extracted from the JavaScript `room_view('campus', building, room, id)` call. The four arguments are joined with underscores (e.g. `nk_5_301_798`).
- **Text-only rooms**: Some rooms (often in external buildings like КПА or the sports complex) have no interactive link. Their display text is used as the ID directly.

---

## `groups`

A dictionary mapping **group IDs** (e.g. `"25111"`, `"24154.2"`) to group objects.

### Group object

| Field          | Type            | Example                                 | Description |
|----------------|-----------------|-----------------------------------------|-------------|
| `faculty_id`   | string \| null  | `"mmf"`                                 | Short slug of the faculty from the URL path |
| `faculty_name` | string \| null  | `"Механико-математический факультет"`   | Full display name of the faculty |
| `degree`       | string \| null  | `"Бакалавриат"` or `"Магистратура"`     | Degree level (bachelor's or master's) |
| `year`         | integer \| null | `1`                                     | Year of study (1-based) |
| `specialty`    | string \| null  | `"Математика и компьютерные науки"`     | Programme / specialty name |
| `schedule`     | array           | *(see below)*                           | List of class entries for this group |

### Class entry (schedule item)

Each element in the `schedule` array is an object:

| Field          | Type            | Example                        | Description |
|----------------|-----------------|--------------------------------|-------------|
| `day`          | integer         | `1`                            | Day of the week: 1 = Monday, 2 = Tuesday, … 6 = Saturday |
| `slot`         | integer         | `2`                            | Time slot (1–7). Use `bell_schedule` to resolve actual times |
| `subject`      | string          | `"Мат.анализ"`                 | Short (abbreviated) subject name |
| `subject_full` | string \| null  | `"Математический анализ"`      | Full subject name from the tooltip. May equal `subject` if no tooltip exists |
| `type`         | string          | `"lecture"`                    | One of five values — see table below |
| `teacher_id`   | string \| null  | `"9bff0127-0099-11e6-8152-..."` | Foreign key into the `teachers` dictionary. `null` if no teacher is listed |
| `room_id`      | string \| null  | `"nk_5_301_798"`               | Foreign key into the `rooms` dictionary. `null` if no room is listed |
| `week`         | string \| null  | `"odd"`                        | Week parity: `"odd"`, `"even"`, or `null` (every week) |

### Class type values

| Value      | Meaning                                  |
|------------|------------------------------------------|
| `lecture`  | Лекция (lecture)                         |
| `seminar`  | Практическое занятие / семинар (seminar) |
| `labs`     | Лабораторная работа (laboratory work)    |
| `elective` | Факультатив (optional / elective class)  |
| `other`    | Unrecognized type, **or** a class that has neither a teacher nor a room explicitly listed |

### Week parity values

| Value  | Meaning                                          |
|--------|--------------------------------------------------|
| `null` | The class takes place every week                 |
| `"odd"`  | Only on odd-numbered (нечётная) weeks          |
| `"even"` | Only on even-numbered (чётная) weeks           |

---

## Relationships

The data is normalized in a relational style:

```
groups[gid].schedule[i].teacher_id  ──►  teachers[teacher_id]
groups[gid].schedule[i].room_id     ──►  rooms[room_id]
groups[gid].schedule[i].slot        ──►  bell_schedule[slot]
```

To reconstruct a human-readable timetable for any group, join the schedule entries with the `teachers`, `rooms`, and `bell_schedule` lookups.
