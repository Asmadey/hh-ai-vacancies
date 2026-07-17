# Google Sheets color-based feedback loop for vacancy filtering

Session: 2026-06-28 — user highlighted rows in the HH_AI sheet: green = suitable, red = not suitable.

## Use case

The user wants to teach the scraper which vacancies are good/bad by coloring rows in Google Sheets. Over time the scraper can learn from these labels and adjust its filter heuristics.

## How to read row background colors

Use the Sheets API metadata endpoint with `includeGridData=true`:

```python
import json, urllib.request

url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}?includeGridData=true"
req = urllib.request.Request(url)
req.add_header("Authorization", f"Bearer {access_token}")
data = json.load(urllib.request.urlopen(req))

for sheet in data.get("sheets", []):
    if sheet["properties"]["title"] == "HH_AI":
        for i, row in enumerate(sheet["data"][0].get("rowData", [])):
            first_cell = row.get("values", [{}])[0]
            bg = first_cell.get("effectiveFormat", {}).get("backgroundColor", {})
            # bg = {"red": 0.85, "green": 0.92, "blue": 0.83} for light green
```

## Color classification heuristic

```python
import math

def classify_color(bg):
    if not bg:
        return "none"
    r, g, b = bg.get("red", 0), bg.get("green", 0), bg.get("blue", 0)
    green_ref = {"r": 0.851, "g": 0.918, "b": 0.827}
    red_ref   = {"r": 0.957, "g": 0.761, "b": 0.761}
    dg = math.sqrt((r-green_ref["r"])**2 + (g-green_ref["g"])**2 + (b-green_ref["b"])**2)
    dr = math.sqrt((r-red_ref["r"])**2 + (g-red_ref["g"])**2 + (b-red_ref["b"])**2)
    if dg < 0.15: return "green"
    if dr < 0.15: return "red"
    if g > 0.5 and r < 0.4 and b < 0.4: return "green"
    if r > 0.5 and g < 0.4 and b < 0.4: return "red"
    return "other"
```

## Hard rules from verbal feedback

When the user gives an explicit rule like "exclude Designer/Developer/Analyst/Engineer, keep Sales/Head/Product", update the deterministic `JUNK_RE` regex in the scraper immediately. Surface conflicts if a previously green row would now be excluded.

Example update:

```python
JUNK_RE = re.compile(
    r"\b(data entry|virtual assistant|customer support|chat support|moderator|"
    r"content writer|translator|telemarketing|cold calling|sales representative|"
    r"social media manager|курьер|водитель|охранник|уборщица|кассир|продавец|"
    r"sales manager|smm|designer|developer|analyst|engineer|дизайнер|разработчик|"
    r"аналитик|инженер)\b",
    re.I,
)
```

### When the user says "this was a one-time action"

Stop reading colors and do not build an automated learning loop. Keep only the hard rules they explicitly asked for. Do not persistently re-read the sheet for new labels.

Note: this may also exclude roles the user previously marked green, such as `Product Engineer (AI / Fullstack)`. Always surface this conflict and ask whether to add an exception (`Product` + `AI` + `Engineer` should be kept).

Color extraction from Google Sheets is reliable. Classification is heuristic and depends on the exact palette Google Sheets uses. Always show the first few green/red matches to the user for verification before changing filters automatically.
