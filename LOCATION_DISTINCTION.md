# NSU Room Location Classification Rules

## ID Structure

Each room is identified by its **room ID (key)** in the `rooms` object. Two forms exist:

- **Structured IDs** — lowercase prefix followed by `_` (e.g. `nk_3_276_1698`, `gk_2_675_621`). The prefix alone determines the building.
- **Unstructured IDs** — begin with `Ауд. ` followed by a human-readable name.

---

## Classification Algorithm

Apply rules in order. The first matching rule determines the group.

| Priority | Condition | Group |
|----------|-----------|-------|
| 1 | `room_id` starts with `nk_` | **1 — НК/КПА** |
| 2 | `room_id` starts with `gk_`, `lk_`, or `au_` | **2 — ГК/ЛК** |
| 3 | `room_id` contains `КПА` | **1 — НК/КПА** |
| 4 | `room_id` contains `Google Meet`, `BigBlueButton`, or `Яндекс.Телемост` | **3 — Online** |
| 5 | `room_id` contains `МНОЦ` | **4 — On-campus** |
| 6 | `room_id` equals `Ауд. Спортивный комплекс` | **4 — On-campus** |
| 7 | `room_id` contains `Пирогова` | **4 — On-campus** |
| 8 | remainder after `Ауд. ` matches `^т?\d{4}(_\S+)?$` | **1 — НК/КПА** |
| 9 | `room_id` contains `ГК` or `ЛК` | **2 — ГК/ЛК** |
| 10 | `room_id` contains `Институт`, `ФГБУН`, `ФГБНУ`, `ГБУЗ`, `Клинические базы`, `ВКИ`, `КЮТ`, or `Базы практик` | **5 — Off-campus/Unclear** |
| 11 | *(no prior rule matched)* | **5 — Off-campus/Unclear** |

---

## Group Definitions

### Group 1 — New Building (НК/УК) and Theaters Building (КПА)

- **НК/УК:** structured IDs starting with `nk_`, plus unstructured IDs where the room number (after `Ауд. `, optionally preceded by `т`) is exactly 4 digits with an optional underscore suffix (rule 8). 4-digit room numbers appear exclusively in the New Building.
- **КПА:** any ID containing the substring `КПА`.

### Group 2 — Main Building (ГК) and Laboratories Building (ЛК)

Structured IDs starting with `gk_`, `lk_`, or `au_`. Unstructured IDs containing `ГК` or `ЛК` (rule 9; evaluated after rules 1–7 so НК/КПА entries are already dispatched).

### Group 3 — Online Classes

IDs containing `Google Meet`, `BigBlueButton`, or `Яндекс.Телемост`.

### Group 4 — Other On-Campus Locations

IDs containing `МНОЦ`, equal to `Ауд. Спортивный комплекс`, or containing `Пирогова 11`.

### Group 5 — Institutions and Off-Campus / Unclear Locations

All SB RAS institutes (`Институт`, `ФГБУН`, `ФГБНУ`), hospitals (`ГБУЗ`, `Клинические базы`), ВКИ, КЮТ СО РАН, practice bases (`Базы практик`), and any room not matched by rules 1–10.
