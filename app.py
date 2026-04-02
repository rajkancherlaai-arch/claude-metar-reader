import re
from flask import Flask, render_template, request
import requests

app = Flask(__name__)

# ── Lookup tables ──────────────────────────────────────────────────────────────

WEATHER_DESCRIPTORS = {
    'MI': 'shallow', 'PR': 'partial', 'BC': 'patches of',
    'DR': 'low drifting', 'BL': 'blowing', 'SH': 'showers',
    'TS': 'thunderstorm', 'FZ': 'freezing',
}

WEATHER_PRECIP = {
    'DZ': 'drizzle', 'RA': 'rain', 'SN': 'snow', 'SG': 'snow grains',
    'IC': 'ice crystals', 'PL': 'ice pellets', 'GR': 'hail',
    'GS': 'small hail', 'UP': 'unknown precipitation',
}

WEATHER_OBSCURATION = {
    'BR': 'mist', 'FG': 'fog', 'FU': 'smoke', 'VA': 'volcanic ash',
    'DU': 'dust', 'SA': 'sand', 'HZ': 'haze', 'PY': 'spray',
}

WEATHER_OTHER = {
    'PO': 'dust whirls', 'SQ': 'squalls', 'FC': 'funnel cloud',
    'SS': 'sandstorm', 'DS': 'dust storm',
}

SKY_COVERAGE = {
    'SKC': 'clear',  'CLR': 'clear',  'NSC': 'clear',  'NCD': 'clear',
    'FEW': 'a few clouds',  'SCT': 'scattered clouds',
    'BKN': 'mostly cloudy', 'OVC': 'overcast',
}

COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
           'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']

WX_PATTERN = re.compile(
    r'^(VC|[-+])?(MI|PR|BC|DR|BL|SH|TS|FZ)?'
    r'(DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)+$'
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def deg_to_compass(deg):
    return COMPASS[round(deg / 22.5) % 16]


def parse_temp_str(s):
    """Parse METAR temp string like '07' or 'M05' into an int."""
    if s.startswith('M'):
        return -int(s[1:])
    return int(s)


def c_to_f(c):
    return round(c * 9 / 5 + 32)


def decode_wx_token(token):
    """Return plain-English description of a weather code like -TSRA, +SN, BR."""
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

    descriptor = ''
    for code, text in WEATHER_DESCRIPTORS.items():
        if remaining.startswith(code):
            descriptor = text
            remaining = remaining[len(code):]
            break

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
            remaining = remaining[2:] if len(remaining) >= 2 else ''

    parts = [p for p in [intensity, descriptor] + phenomena if p]
    return ' '.join(parts) if parts else token


def sky_description(layers_raw):
    """
    Given a list of raw sky tokens (e.g. ['BKN038', 'OVC075']),
    return a list of plain-English strings and an overall condition label.
    """
    descriptions = []
    overall = 'clear'
    priority = 0  # higher = worse

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

# ── Main parser ────────────────────────────────────────────────────────────────

def parse_metar(raw):
    """Parse a raw METAR string and return a dict of decoded fields."""
    result = {'raw': raw, 'errors': []}
    tokens = raw.split()
    idx = 0

    # Optional type prefix
    if idx < len(tokens) and tokens[idx] in ('METAR', 'SPECI'):
        idx += 1

    # Station identifier
    if idx < len(tokens):
        result['station'] = tokens[idx]
        idx += 1

    # Date/time  DDHHmmZ
    if idx < len(tokens) and re.match(r'^\d{6}Z$', tokens[idx]):
        t = tokens[idx]
        result['day']  = int(t[0:2])
        result['hour'] = int(t[2:4])
        result['minute'] = int(t[4:6])
        result['time_utc'] = f"{t[2:4]}:{t[4:6]} UTC"
        idx += 1

    # AUTO / COR
    result['auto'] = False
    if idx < len(tokens) and tokens[idx] in ('AUTO', 'COR'):
        result['auto'] = tokens[idx] == 'AUTO'
        idx += 1

    # Wind  dddssKT or dddssGggKT or VRBssKT
    if idx < len(tokens):
        wm = re.match(r'^(VRB|\d{3})(\d{2,3})(?:G(\d{2,3}))?KT$', tokens[idx])
        if wm:
            dir_str, spd, gst = wm.group(1), int(wm.group(2)), wm.group(3)
            if spd == 0 and dir_str in ('000', 'VRB'):
                result['wind_text'] = 'calm'
                result['wind_speed_kt'] = 0
            elif dir_str == 'VRB':
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

    # Variable wind direction  180V240
    if idx < len(tokens) and re.match(r'^\d{3}V\d{3}$', tokens[idx]):
        result['wind_variable_range'] = tokens[idx]
        idx += 1

    # Visibility
    if idx < len(tokens):
        vis_tok = tokens[idx]
        # Whole + fraction e.g. "1 1/2SM" — handled across two tokens
        if re.match(r'^\d+$', vis_tok) and idx + 1 < len(tokens) and re.match(r'^\d+/\d+SM$', tokens[idx + 1]):
            whole = int(vis_tok)
            fm = re.match(r'^(\d+)/(\d+)SM$', tokens[idx + 1])
            frac = int(fm.group(1)) / int(fm.group(2))
            total = whole + frac
            result['visibility_sm'] = total
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

    # RVR  R28L/2400FT  (skip)
    while idx < len(tokens) and re.match(r'^R\d+[LCR]?/', tokens[idx]):
        idx += 1

    # Present weather phenomena
    wx_list = []
    while idx < len(tokens) and WX_PATTERN.match(tokens[idx]):
        wx_list.append(decode_wx_token(tokens[idx]))
        idx += 1
    result['weather_phenomena'] = wx_list

    # Sky conditions
    sky_raw = []
    sky_pattern = re.compile(r'^(SKC|CLR|NSC|NCD|CAVOK|FEW|SCT|BKN|OVC)(\d{3})?(CB|TCU)?$')
    while idx < len(tokens) and sky_pattern.match(tokens[idx]):
        sky_raw.append(tokens[idx])
        idx += 1
    sky_descriptions, sky_overall = sky_description(sky_raw)
    result['sky_layers'] = sky_descriptions
    result['sky_overall'] = sky_overall

    # Temperature / Dewpoint  07/03 or M05/M08
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

    # Altimeter  A2959
    if idx < len(tokens):
        am = re.match(r'^A(\d{4})$', tokens[idx])
        if am:
            result['altimeter_inhg'] = int(am.group(1)) / 100
            idx += 1

    # Build human-readable summary
    result['summary'] = build_summary(result)
    result['condition_label'] = build_condition_label(result)

    return result


def build_condition_label(r):
    """Short label like 'Overcast · Light Rain' for the headline."""
    parts = []
    sky = r.get('sky_overall', 'clear').capitalize()
    parts.append(sky)
    for wx in r.get('weather_phenomena', []):
        parts.append(wx.capitalize())
    return ' · '.join(parts)


def build_summary(r):
    """One or two sentence plain-English summary."""
    sentences = []

    # Condition + phenomena
    sky = r.get('sky_overall', 'clear')
    phenomena = r.get('weather_phenomena', [])
    cond_parts = [sky.capitalize()]
    cond_parts.extend(p.capitalize() for p in phenomena)
    sentences.append(', '.join(cond_parts))

    # Temperature
    if 'temp_f' in r:
        sentences.append(f"Temperature {r['temp_f']}°F ({r['temp_c']}°C)")

    # Wind
    if 'wind_text' in r:
        sentences.append(f"Winds {r['wind_text']}")

    # Visibility
    if 'visibility_text' in r:
        vis = r['visibility_text']
        label = 'Visibility ' + vis
        sentences.append(label)

    return '. '.join(sentences) + '.'


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route('/', methods=['GET'])
def index():
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
