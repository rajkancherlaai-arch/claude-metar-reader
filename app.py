"""
METAR Reader — Flask web application.

Fetches live METAR (Meteorological Aerodrome Report) data from the
Aviation Weather Center API and decodes each field into plain English,
so anyone can understand the current weather at any ICAO airport.

Data source: https://aviationweather.gov/api/data/metar/
"""

import re
from flask import Flask, render_template, request
import requests

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Lookup tables
#
# These map the two-letter METAR codes defined in ICAO Annex 3 / WMO No. 49
# to their plain-English equivalents.
# ---------------------------------------------------------------------------

# Descriptor codes that modify a precipitation or obscuration type.
# e.g. "SH" in "SHRA" means "showers of rain".
WEATHER_DESCRIPTORS = {
    'MI': 'shallow', 'PR': 'partial', 'BC': 'patches of',
    'DR': 'low drifting', 'BL': 'blowing', 'SH': 'showers',
    'TS': 'thunderstorm', 'FZ': 'freezing',
}

# Precipitation type codes.
WEATHER_PRECIP = {
    'DZ': 'drizzle', 'RA': 'rain', 'SN': 'snow', 'SG': 'snow grains',
    'IC': 'ice crystals', 'PL': 'ice pellets', 'GR': 'hail',
    'GS': 'small hail', 'UP': 'unknown precipitation',
}

# Obscuration codes (phenomena that reduce visibility).
WEATHER_OBSCURATION = {
    'BR': 'mist', 'FG': 'fog', 'FU': 'smoke', 'VA': 'volcanic ash',
    'DU': 'dust', 'SA': 'sand', 'HZ': 'haze', 'PY': 'spray',
}

# Other weather phenomena that don't fit the above categories.
WEATHER_OTHER = {
    'PO': 'dust whirls', 'SQ': 'squalls', 'FC': 'funnel cloud',
    'SS': 'sandstorm', 'DS': 'dust storm',
}

# Sky coverage codes mapped to plain-English descriptions.
# Coverage determines the overall condition label (e.g. "overcast").
SKY_COVERAGE = {
    'SKC': 'clear',  'CLR': 'clear',  'NSC': 'clear',  'NCD': 'clear',
    'FEW': 'a few clouds',  'SCT': 'scattered clouds',
    'BKN': 'mostly cloudy', 'OVC': 'overcast',
}

# 16-point compass rose used to convert wind direction degrees to a
# human-readable bearing (e.g. 270° → "W").
COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
           'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']

# Pre-compiled regex that matches any valid present-weather token, e.g.
# "-RA", "+TSRA", "BR", "VCFG".  Used to identify weather tokens while
# walking the METAR token list.
WX_PATTERN = re.compile(
    r'^(VC|[-+])?(MI|PR|BC|DR|BL|SH|TS|FZ)?'
    r'(DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)+$'
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def deg_to_compass(deg):
    """Convert a wind direction in degrees (0–360) to a compass bearing string.

    Args:
        deg: Wind direction in degrees true north.

    Returns:
        A string such as 'N', 'NNE', 'SW', etc.
    """
    return COMPASS[round(deg / 22.5) % 16]


def parse_temp_str(s):
    """Parse a METAR temperature token into a signed integer (Celsius).

    METAR uses 'M' as a minus prefix instead of '-', e.g. 'M05' means -5°C.

    Args:
        s: Raw temperature string like '07' or 'M05'.

    Returns:
        Temperature as a Python int.
    """
    if s.startswith('M'):
        return -int(s[1:])
    return int(s)


def c_to_f(c):
    """Convert Celsius to Fahrenheit, rounded to the nearest whole degree.

    Args:
        c: Temperature in Celsius.

    Returns:
        Temperature in Fahrenheit as an int.
    """
    return round(c * 9 / 5 + 32)


def decode_wx_token(token):
    """Decode a single present-weather token into a plain-English phrase.

    METAR weather codes are built from up to three parts:
      - Intensity prefix: '-' (light), '+' (heavy), 'VC' (vicinity)
      - Descriptor:       two-letter modifier, e.g. 'TS' (thunderstorm)
      - Phenomenon:       one or more two-letter codes, e.g. 'RA' (rain)

    Examples:
        '-RA'   → 'light rain'
        '+TSRA' → 'heavy thunderstorm rain'
        'BR'    → 'mist'

    Args:
        token: A raw METAR weather token string.

    Returns:
        A plain-English description string.
    """
    i = 0
    intensity = ''
    if token.startswith('VC'):
        intensity = 'nearby'
        i = 2
    elif token.startswith('-'):
        intensity = 'light'
        i = 1
    elif token.startswith('+'):
        intensity = 'heavy'
        i = 1

    remaining = token[i:]

    # Extract optional descriptor (e.g. 'TS', 'SH', 'FZ')
    descriptor = ''
    for code, text in WEATHER_DESCRIPTORS.items():
        if remaining.startswith(code):
            descriptor = text
            remaining = remaining[len(code):]
            break

    # Extract one or more phenomenon codes (each 2 characters)
    phenomena = []
    while remaining:
        found = False
        for lookup in (WEATHER_PRECIP, WEATHER_OBSCURATION, WEATHER_OTHER):
            key = remaining[:2]
            if key in lookup:
                phenomena.append(lookup[key])
                remaining = remaining[2:]
                found = True
                break
        if not found:
            # Skip unrecognised 2-character code rather than looping forever
            remaining = remaining[2:] if len(remaining) >= 2 else ''

    parts = [p for p in [intensity, descriptor] + phenomena if p]
    return ' '.join(parts) if parts else token


def sky_description(layers_raw):
    """Convert a list of raw sky-condition tokens into plain-English descriptions.

    Iterates over each layer token (e.g. 'BKN038', 'OVC075'), derives a
    human-readable string for each, and tracks the most significant coverage
    level to produce a single overall condition label.

    The priority order for overall condition is:
        FEW (1) < SCT (2) < BKN (3) < OVC (4)

    Args:
        layers_raw: List of raw sky tokens, e.g. ['FEW015', 'BKN038', 'OVC075'].

    Returns:
        A tuple of:
            - descriptions (list[str]): Plain-English layer descriptions.
            - overall (str): The most significant sky coverage label.
    """
    descriptions = []
    overall = 'clear'
    priority = 0  # Tracks worst (highest) coverage seen so far

    for token in layers_raw:
        m = re.match(r'^(SKC|CLR|NSC|NCD|CAVOK|FEW|SCT|BKN|OVC)(\d{3})?(CB|TCU)?$', token)
        if not m:
            continue
        cov, alt, cloud_type = m.group(1), m.group(2), m.group(3)

        if cov in ('SKC', 'CLR', 'NSC', 'NCD', 'CAVOK'):
            descriptions.append('clear skies')
            continue

        alt_ft = int(alt) * 100 if alt else 0
        text = SKY_COVERAGE.get(cov, cov)
        layer = f'{text} at {alt_ft:,} ft'

        # CB (cumulonimbus) and TCU (towering cumulus) indicate convective
        # activity and are called out explicitly.
        if cloud_type == 'CB':
            layer += ' (cumulonimbus)'
        elif cloud_type == 'TCU':
            layer += ' (towering cumulus)'
        descriptions.append(layer)

        rank = {'FEW': 1, 'SCT': 2, 'BKN': 3, 'OVC': 4}.get(cov, 0)
        if rank > priority:
            priority = rank
            overall = SKY_COVERAGE.get(cov, cov)

    return descriptions, overall


# ---------------------------------------------------------------------------
# Main METAR parser
# ---------------------------------------------------------------------------

def parse_metar(raw):
    """Parse a raw METAR string into a dictionary of decoded weather fields.

    Walks through each whitespace-separated token in the METAR string in
    the order defined by the METAR specification (ICAO Annex 3):

        [TYPE] STATION DDHHMZ [AUTO|COR] WIND [WIND_VAR] VIS [RVR]
        [WEATHER ...] [SKY ...] TEMP/DEWPT ALTIMETER [RMK ...]

    The RMK (remarks) section is not decoded — parsing stops after the
    altimeter setting.

    Args:
        raw: The complete raw METAR string, e.g.
             'KJFK 020451Z 08009G17KT 7SM -RA OVC018 11/09 A3027 RMK AO2'

    Returns:
        A dict containing decoded fields.  Keys present depend on which
        fields were found in the METAR.  Always includes:
            raw (str):    The original unmodified string.
            summary (str): A plain-English one-line weather summary.
            condition_label (str): Short headline, e.g. 'Overcast · Light rain'.
    """
    result = {'raw': raw}
    tokens = raw.split()
    idx = 0

    # Optional report type prefix: METAR (routine) or SPECI (special)
    if idx < len(tokens) and tokens[idx] in ('METAR', 'SPECI'):
        idx += 1

    # ICAO station identifier (4 letters, e.g. KJFK)
    if idx < len(tokens):
        result['station'] = tokens[idx]
        idx += 1

    # Observation date/time in DDHHmmZ format (UTC)
    if idx < len(tokens) and re.match(r'^\d{6}Z$', tokens[idx]):
        t = tokens[idx]
        result['day']     = int(t[0:2])
        result['hour']    = int(t[2:4])
        result['minute']  = int(t[4:6])
        result['time_utc'] = f"{t[2:4]}:{t[4:6]} UTC"
        idx += 1

    # AUTO = fully automated station (no human observer)
    # COR  = corrected report (replaces a previous erroneous one)
    result['auto'] = False
    if idx < len(tokens) and tokens[idx] in ('AUTO', 'COR'):
        result['auto'] = tokens[idx] == 'AUTO'
        idx += 1

    # Wind: dddssKT, dddssGggKT, or VRBssKT
    #   ddd = direction in degrees true, ss = speed, gg = gust speed (knots)
    if idx < len(tokens):
        wm = re.match(r'^(VRB|\d{3})(\d{2,3})(?:G(\d{2,3}))?KT$', tokens[idx])
        if wm:
            dir_str, spd, gst = wm.group(1), int(wm.group(2)), wm.group(3)
            if spd == 0 and dir_str in ('000', 'VRB'):
                result['wind_text'] = 'calm'
                result['wind_speed_kt'] = 0
            elif dir_str == 'VRB':
                # Variable direction, defined speed
                result['wind_text'] = f'variable at {spd} knots'
                result['wind_speed_kt'] = spd
            else:
                deg = int(dir_str)
                compass = deg_to_compass(deg)
                result['wind_dir_deg'] = deg
                result['wind_dir_compass'] = compass
                result['wind_speed_kt'] = spd
                result['wind_text'] = f'from the {compass} at {spd} knots'
                if gst:
                    result['wind_gust_kt'] = int(gst)
                    result['wind_text'] += f', gusting to {int(gst)} knots'
            idx += 1

    # Optional variable wind direction range, e.g. '180V240'
    # Reported when direction varies by 60° or more and speed > 3 kt.
    if idx < len(tokens) and re.match(r'^\d{3}V\d{3}$', tokens[idx]):
        result['wind_variable_range'] = tokens[idx]
        idx += 1

    # Visibility in statute miles (SM).  Can be a whole number ('10SM'),
    # a fraction ('1/2SM'), or split across two tokens ('1 1/2SM').
    if idx < len(tokens):
        vis_tok = tokens[idx]
        if re.match(r'^\d+$', vis_tok) and idx + 1 < len(tokens) and re.match(r'^\d+/\d+SM$', tokens[idx + 1]):
            # e.g. "1 1/2SM" — whole number and fraction are separate tokens
            whole = int(vis_tok)
            fm = re.match(r'^(\d+)/(\d+)SM$', tokens[idx + 1])
            frac = int(fm.group(1)) / int(fm.group(2))
            result['visibility_sm'] = whole + frac
            result['visibility_text'] = f'{whole} {fm.group(1)}/{fm.group(2)} miles'
            idx += 2
        else:
            vm = re.match(r'^(\d+(?:/\d+)?)SM$', vis_tok)
            if vm:
                vis_str = vm.group(1)
                if '/' in vis_str:
                    n, d = vis_str.split('/')
                    sm = int(n) / int(d)
                else:
                    sm = int(vis_str)
                result['visibility_sm'] = sm
                result['visibility_text'] = ('more than 10 miles' if sm >= 10
                                             else f'{vis_str} {"mile" if sm <= 1 else "miles"}')
                idx += 1

    # Runway Visual Range (RVR) — skip; not decoded in this app.
    # Format: R<runway>/<distance>FT  e.g. R28L/2400FT
    while idx < len(tokens) and re.match(r'^R\d+[LCR]?/', tokens[idx]):
        idx += 1

    # Present weather phenomena — zero or more tokens, e.g. '-RA', '+TSRA', 'BR'
    wx_list = []
    while idx < len(tokens) and WX_PATTERN.match(tokens[idx]):
        wx_list.append(decode_wx_token(tokens[idx]))
        idx += 1
    result['weather_phenomena'] = wx_list

    # Sky condition layers — zero or more tokens in order of increasing altitude.
    # e.g. 'FEW015 BKN038 OVC075'
    sky_raw = []
    sky_pattern = re.compile(r'^(SKC|CLR|NSC|NCD|CAVOK|FEW|SCT|BKN|OVC)(\d{3})?(CB|TCU)?$')
    while idx < len(tokens) and sky_pattern.match(tokens[idx]):
        sky_raw.append(tokens[idx])
        idx += 1
    sky_descriptions, sky_overall = sky_description(sky_raw)
    result['sky_layers'] = sky_descriptions
    result['sky_overall'] = sky_overall

    # Temperature and dew point in Celsius.
    # Format: TT/DD, where 'M' prefix means negative, e.g. 'M05/M08'
    if idx < len(tokens):
        tm = re.match(r'^(M?\d+)/(M?\d+)$', tokens[idx])
        if tm:
            tc = parse_temp_str(tm.group(1))
            dc = parse_temp_str(tm.group(2))
            result['temp_c'] = tc
            result['temp_f'] = c_to_f(tc)
            result['dew_c']  = dc
            result['dew_f']  = c_to_f(dc)
            idx += 1

    # Altimeter setting (barometric pressure).
    # Format: AXXXX in hundredths of inches of mercury, e.g. A2959 = 29.59 inHg
    if idx < len(tokens):
        am = re.match(r'^A(\d{4})$', tokens[idx])
        if am:
            result['altimeter_inhg'] = int(am.group(1)) / 100
            idx += 1

    # Build the human-readable outputs from the decoded fields
    result['summary'] = build_summary(result)
    result['condition_label'] = build_condition_label(result)

    return result


# ---------------------------------------------------------------------------
# Summary builders
# ---------------------------------------------------------------------------

def build_condition_label(r):
    """Build a short headline label from sky coverage and weather phenomena.

    Example output: 'Overcast · Light rain'

    Args:
        r: Decoded METAR dict as returned by parse_metar().

    Returns:
        A string suitable for display as a card headline.
    """
    parts = [r.get('sky_overall', 'clear').capitalize()]
    for wx in r.get('weather_phenomena', []):
        parts.append(wx.capitalize())
    return ' · '.join(parts)


def build_summary(r):
    """Build a one-line plain-English weather summary sentence.

    Combines sky condition, temperature, wind, and visibility into a
    single readable string suitable for display below the headline.

    Example output:
        'Overcast, Light rain. Temperature 52°F (11°C).
         Winds from the E at 9 knots, gusting to 17 knots. Visibility 7 miles.'

    Args:
        r: Decoded METAR dict as returned by parse_metar().

    Returns:
        A plain-English summary string ending with a period.
    """
    sentences = []

    # Lead with sky condition and any active weather phenomena
    sky = r.get('sky_overall', 'clear')
    phenomena = r.get('weather_phenomena', [])
    cond_parts = [sky.capitalize()] + [p.capitalize() for p in phenomena]
    sentences.append(', '.join(cond_parts))

    if 'temp_f' in r:
        sentences.append(f"Temperature {r['temp_f']}°F ({r['temp_c']}°C)")

    if 'wind_text' in r:
        sentences.append(f"Winds {r['wind_text']}")

    if 'visibility_text' in r:
        sentences.append(f"Visibility {r['visibility_text']}")

    return '. '.join(sentences) + '.'


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------

@app.route('/', methods=['GET'])
def index():
    """Render the main page.

    Accepts an optional 'icao' query parameter.  When provided, fetches the
    latest METAR from the Aviation Weather Center API, parses it, and passes
    the decoded data to the template.

    Query parameters:
        icao (str): ICAO airport identifier, e.g. 'KJFK'.

    Returns:
        Rendered HTML response.
    """
    icao    = request.args.get('icao', '').upper().strip()
    weather = None
    error   = None

    if icao:
        try:
            resp = requests.get(
                f'https://aviationweather.gov/api/data/metar/?ids={icao}',
                timeout=10,
                headers={'User-Agent': 'METAR-Reader/1.0'}
            )
            raw = resp.text.strip()
            if not raw:
                error = f'No METAR data found for "{icao}". Is that a valid ICAO airport code?'
            else:
                weather = parse_metar(raw)
        except requests.Timeout:
            error = 'Request timed out. Please try again.'
        except requests.RequestException as exc:
            error = f'Could not reach the weather service: {exc}'

    return render_template('index.html', icao=icao, weather=weather, error=error)


if __name__ == '__main__':
    app.run(debug=True)
