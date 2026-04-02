# ✈️ METAR Reader

A Flask web application that fetches live aviation weather reports (METARs) for any airport in the world and translates the cryptic codes into plain English.

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![Flask](https://img.shields.io/badge/flask-3.x-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

---

## What is a METAR?

A **METAR** (Meteorological Aerodrome Report) is a standardized weather observation issued by airports around the world, typically every hour. Pilots use METARs to assess weather before and during a flight — but the format was designed for efficiency, not readability.

A raw METAR looks like this:

```
METAR KJFK 020451Z 08009G17KT 7SM -RA OVC018 11/09 A3027 RMK AO2
```

This app decodes that into:

> **Overcast · Light rain**
> Temperature 52°F (11°C). Winds from the E at 9 knots, gusting to 17 knots. Visibility 7 miles.

---

## Features

- Look up live weather for any ICAO airport code worldwide
- Decodes all major METAR fields:
  - Sky conditions (clear, scattered, broken, overcast)
  - Temperature and dew point (°F and °C)
  - Wind direction, speed, and gusts
  - Visibility
  - Present weather (rain, snow, fog, thunderstorms, etc.)
  - Barometric pressure
- Plain-English explainer on the landing page for first-time users
- Raw METAR string always shown alongside the decoded report
- Clean, dark-themed responsive UI

---

## Installation

### Prerequisites

- Python 3.8 or higher
- pip

### Steps

1. **Clone the repository**

   ```bash
   git clone https://github.com/rajkancherlaai-arch/claude-metar-reader.git
   cd claude-metar-reader
   ```

2. **Create and activate a virtual environment**

   ```bash
   python3 -m venv venv
   source venv/bin/activate        # macOS / Linux
   venv\Scripts\activate           # Windows
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Run the app**

   ```bash
   python app.py
   ```

5. **Open your browser** and go to `http://127.0.0.1:5000`

---

## Usage

1. Enter a 4-letter **ICAO airport code** in the search box (e.g. `KJFK`, `KLAX`, `EGLL`)
2. Click **Get Weather**
3. Read the plain-English weather report

> **Tip:** Not sure of the ICAO code? It is usually the airport's IATA code prefixed with a region letter — e.g. `K` for the US, `EG` for the UK, `YY` for Canada. You can look up ICAO codes at [ourairports.com](https://ourairports.com).

---

## Running the Tests

The project has 76 unit tests covering the METAR parser and Flask routes.

Install pytest, then run:

```bash
pip install pytest
pytest tests/test_app.py -v
```

Test coverage includes:

| Layer | What is tested |
|---|---|
| **Helpers** | Wind direction conversion, temperature parsing, °C→°F, weather code decoding, sky condition logic |
| **Parser** | All major METAR fields with mock strings — wind, visibility, phenomena, sky layers, temperature, altimeter, summaries |
| **Flask routes** | Landing page, valid/invalid airport codes, lowercase normalisation, network timeout, connection errors |

Tests use `unittest.mock.patch` to intercept `requests.get` — no real network calls are made.

---

## Project Structure

```
claude-metar-reader/
├── app.py               # Flask app and METAR parser
├── requirements.txt     # Python dependencies
├── templates/
│   └── index.html       # Jinja2 HTML template
├── tests/
│   ├── conftest.py      # pytest path setup
│   └── test_app.py      # 76 unit tests
└── .gitignore
```

---

## Data Source

Live METAR data is fetched from the **Aviation Weather Center** API, operated by NOAA:

```
https://aviationweather.gov/api/data/metar/?ids={ICAO}
```

No API key is required.

---

## License

MIT License — free to use, modify, and distribute.
