"""
Unit tests for the METAR Reader Flask application.

Test organisation
-----------------
TestHelpers      — individual helper functions (pure, no I/O)
TestMETARParser  — parse_metar() with mock METAR strings covering edge cases
TestFlaskRoutes  — Flask HTTP layer with requests.get mocked out
"""

import pytest
from unittest.mock import patch, MagicMock

from app import (
    app,
    deg_to_compass,
    parse_temp_str,
    c_to_f,
    decode_wx_token,
    sky_description,
    parse_metar,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Flask test client with testing mode enabled."""
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# TestHelpers — pure helper functions
# ---------------------------------------------------------------------------

class TestDegToCompass:
    def test_north(self):
        assert deg_to_compass(0) == 'N'

    def test_north_360(self):
        assert deg_to_compass(360) == 'N'

    def test_east(self):
        assert deg_to_compass(90) == 'E'

    def test_south(self):
        assert deg_to_compass(180) == 'S'

    def test_west(self):
        assert deg_to_compass(270) == 'W'

    def test_northeast(self):
        assert deg_to_compass(45) == 'NE'

    def test_southwest(self):
        assert deg_to_compass(225) == 'SW'

    def test_rounding_nnw(self):
        # 337.5° rounds to NNW (index 15)
        assert deg_to_compass(338) == 'NNW'


class TestParseTempStr:
    def test_positive(self):
        assert parse_temp_str('07') == 7

    def test_zero(self):
        assert parse_temp_str('00') == 0

    def test_negative_prefix(self):
        assert parse_temp_str('M05') == -5

    def test_negative_double_digit(self):
        assert parse_temp_str('M18') == -18


class TestCToF:
    def test_freezing(self):
        assert c_to_f(0) == 32

    def test_boiling(self):
        assert c_to_f(100) == 212

    def test_body_temp(self):
        assert c_to_f(37) == 99

    def test_negative(self):
        assert c_to_f(-40) == -40  # -40 is the same in both scales


class TestDecodeWxToken:
    def test_light_rain(self):
        assert decode_wx_token('-RA') == 'light rain'

    def test_heavy_rain(self):
        assert decode_wx_token('+RA') == 'heavy rain'

    def test_moderate_rain(self):
        # No intensity prefix = moderate; descriptor only says 'rain'
        assert decode_wx_token('RA') == 'rain'

    def test_light_snow(self):
        assert decode_wx_token('-SN') == 'light snow'

    def test_heavy_thunderstorm_rain(self):
        assert decode_wx_token('+TSRA') == 'heavy thunderstorm rain'

    def test_fog(self):
        assert decode_wx_token('FG') == 'fog'

    def test_mist(self):
        assert decode_wx_token('BR') == 'mist'

    def test_freezing_rain(self):
        assert decode_wx_token('FZRA') == 'freezing rain'

    def test_vicinity_fog(self):
        assert decode_wx_token('VCFG') == 'nearby fog'

    def test_shower_rain(self):
        assert decode_wx_token('SHRA') == 'showers rain'

    def test_haze(self):
        assert decode_wx_token('HZ') == 'haze'


class TestSkyDescription:
    def test_clear(self):
        desc, overall = sky_description(['CLR'])
        assert overall == 'clear'
        assert 'clear' in desc[0]

    def test_overcast(self):
        desc, overall = sky_description(['OVC018'])
        assert overall == 'overcast'
        assert '1,800 ft' in desc[0]

    def test_broken(self):
        desc, overall = sky_description(['BKN038'])
        assert overall == 'mostly cloudy'

    def test_scattered(self):
        desc, overall = sky_description(['SCT020'])
        assert overall == 'scattered clouds'

    def test_few(self):
        desc, overall = sky_description(['FEW015'])
        assert overall == 'a few clouds'

    def test_worst_layer_wins(self):
        # BKN and OVC present — OVC should win
        desc, overall = sky_description(['BKN038', 'OVC075'])
        assert overall == 'overcast'
        assert len(desc) == 2

    def test_cumulonimbus_flagged(self):
        desc, overall = sky_description(['BKN025CB'])
        assert 'cumulonimbus' in desc[0]

    def test_towering_cumulus_flagged(self):
        desc, overall = sky_description(['SCT030TCU'])
        assert 'towering cumulus' in desc[0]

    def test_empty(self):
        desc, overall = sky_description([])
        assert overall == 'clear'
        assert desc == []


# ---------------------------------------------------------------------------
# TestMETARParser — parse_metar() with realistic mock strings
# ---------------------------------------------------------------------------

class TestMETARParser:

    # ── Basic fields ──────────────────────────────────────────────────────

    def test_station_parsed(self):
        r = parse_metar('KJFK 020451Z 00000KT 10SM CLR 11/09 A3027')
        assert r['station'] == 'KJFK'

    def test_metar_prefix_stripped(self):
        r = parse_metar('METAR KJFK 020451Z 00000KT 10SM CLR 11/09 A3027')
        assert r['station'] == 'KJFK'

    def test_time_parsed(self):
        r = parse_metar('KJFK 020451Z 00000KT 10SM CLR 11/09 A3027')
        assert r['time_utc'] == '04:51 UTC'
        assert r['day'] == 2

    def test_auto_flag_true(self):
        r = parse_metar('KHIO 020453Z AUTO 20006KT 10SM CLR 07/03 A2959')
        assert r['auto'] is True

    def test_auto_flag_false(self):
        r = parse_metar('KJFK 020451Z 08009KT 10SM CLR 11/09 A3027')
        assert r['auto'] is False

    def test_raw_preserved(self):
        raw = 'KJFK 020451Z 00000KT 10SM CLR 11/09 A3027'
        r = parse_metar(raw)
        assert r['raw'] == raw

    # ── Wind ─────────────────────────────────────────────────────────────

    def test_wind_directional(self):
        r = parse_metar('KJFK 020451Z 08009KT 10SM CLR 11/09 A3027')
        assert r['wind_speed_kt'] == 9
        assert r['wind_dir_compass'] == 'E'
        assert 'from the E at 9 knots' in r['wind_text']

    def test_wind_with_gust(self):
        r = parse_metar('KJFK 020451Z 08009G17KT 7SM OVC018 11/09 A3027')
        assert r['wind_gust_kt'] == 17
        assert 'gusting to 17 knots' in r['wind_text']

    def test_wind_calm(self):
        r = parse_metar('KLAX 010000Z 00000KT 10SM CLR 22/10 A2998')
        assert r['wind_text'] == 'calm'
        assert r['wind_speed_kt'] == 0

    def test_wind_variable(self):
        r = parse_metar('KORD 010100Z VRB04KT 9SM FEW015 15/08 A3010')
        assert 'variable at 4 knots' in r['wind_text']

    # ── Visibility ───────────────────────────────────────────────────────

    def test_visibility_10sm(self):
        r = parse_metar('KJFK 020451Z 08009KT 10SM CLR 11/09 A3027')
        assert r['visibility_text'] == 'more than 10 miles'

    def test_visibility_whole_miles(self):
        r = parse_metar('KJFK 020451Z 08009KT 7SM OVC018 11/09 A3027')
        assert r['visibility_text'] == '7 miles'

    def test_visibility_fraction(self):
        r = parse_metar('KSFO 010600Z 00000KT 1/4SM FG OVC002 12/12 A3005')
        assert '1/4' in r['visibility_text']

    def test_visibility_mixed_fraction(self):
        r = parse_metar('KBOS 010300Z 18008KT 1 1/2SM -SN OVC010 M02/M05 A2990')
        assert '1 1/2' in r['visibility_text']

    # ── Weather phenomena ─────────────────────────────────────────────────

    def test_light_rain_detected(self):
        r = parse_metar('KJFK 020451Z 08009KT 7SM -RA OVC018 11/09 A3027')
        assert 'light rain' in r['weather_phenomena']

    def test_heavy_thunderstorm(self):
        r = parse_metar('KIAH 011200Z 25012KT 3SM +TSRA BKN020 OVC040 28/24 A2985')
        assert 'heavy thunderstorm rain' in r['weather_phenomena']

    def test_fog(self):
        r = parse_metar('KSFO 010600Z 00000KT 1/4SM FG OVC002 12/12 A3005')
        assert 'fog' in r['weather_phenomena']

    def test_multiple_phenomena(self):
        r = parse_metar('KORD 010000Z 18010KT 2SM -RA BR OVC010 10/09 A2995')
        assert len(r['weather_phenomena']) == 2

    def test_no_phenomena(self):
        r = parse_metar('KLAX 010000Z 00000KT 10SM CLR 22/10 A2998')
        assert r['weather_phenomena'] == []

    # ── Sky conditions ────────────────────────────────────────────────────

    def test_clear_sky(self):
        r = parse_metar('KLAX 010000Z 00000KT 10SM CLR 22/10 A2998')
        assert r['sky_overall'] == 'clear'

    def test_overcast(self):
        r = parse_metar('KJFK 020451Z 08009KT 7SM -RA OVC018 11/09 A3027')
        assert r['sky_overall'] == 'overcast'

    def test_multiple_sky_layers(self):
        r = parse_metar('KHIO 020453Z 20006KT 10SM BKN038 OVC075 07/03 A2959')
        assert len(r['sky_layers']) == 2
        assert r['sky_overall'] == 'overcast'  # OVC beats BKN

    # ── Temperature ───────────────────────────────────────────────────────

    def test_positive_temperature(self):
        r = parse_metar('KJFK 020451Z 08009KT 7SM OVC018 11/09 A3027')
        assert r['temp_c'] == 11
        assert r['temp_f'] == 52

    def test_negative_temperature(self):
        r = parse_metar('PANC 010900Z 36015KT 10SM SKC M18/M22 A2965')
        assert r['temp_c'] == -18
        assert r['temp_f'] == 0

    def test_dewpoint_parsed(self):
        r = parse_metar('KJFK 020451Z 08009KT 7SM OVC018 11/09 A3027')
        assert r['dew_c'] == 9
        assert r['dew_f'] == 48

    # ── Altimeter ────────────────────────────────────────────────────────

    def test_altimeter(self):
        r = parse_metar('KJFK 020451Z 08009KT 7SM OVC018 11/09 A3027')
        assert r['altimeter_inhg'] == pytest.approx(30.27)

    # ── Summary and condition label ───────────────────────────────────────

    def test_condition_label_clear(self):
        r = parse_metar('KLAX 010000Z 00000KT 10SM CLR 22/10 A2998')
        assert r['condition_label'] == 'Clear'

    def test_condition_label_overcast_rain(self):
        r = parse_metar('KJFK 020451Z 08009G17KT 7SM -RA OVC018 11/09 A3027')
        assert r['condition_label'] == 'Overcast · Light rain'

    def test_summary_contains_temperature(self):
        r = parse_metar('KJFK 020451Z 08009KT 7SM OVC018 11/09 A3027')
        assert '52°F' in r['summary']
        assert '11°C' in r['summary']

    def test_summary_contains_wind(self):
        r = parse_metar('KJFK 020451Z 08009KT 7SM OVC018 11/09 A3027')
        assert 'Winds' in r['summary']

    def test_summary_contains_visibility(self):
        r = parse_metar('KJFK 020451Z 08009KT 7SM OVC018 11/09 A3027')
        assert 'Visibility' in r['summary']

    def test_summary_ends_with_period(self):
        r = parse_metar('KJFK 020451Z 08009KT 7SM OVC018 11/09 A3027')
        assert r['summary'].endswith('.')


# ---------------------------------------------------------------------------
# TestFlaskRoutes — HTTP layer with requests.get mocked
# ---------------------------------------------------------------------------

class TestFlaskRoutes:

    def test_landing_page_loads(self, client):
        """GET / with no ICAO should show the landing page."""
        resp = client.get('/')
        assert resp.status_code == 200
        assert b'METAR Reader' in resp.data
        assert b'What is a METAR' in resp.data

    def test_landing_page_shows_examples(self, client):
        resp = client.get('/')
        assert b'KJFK' in resp.data

    def test_valid_icao_returns_weather(self, client):
        """A valid ICAO with a successful API response should show decoded weather."""
        mock_resp = MagicMock()
        mock_resp.text = 'KJFK 020451Z 08009G17KT 7SM -RA OVC018 11/09 A3027 RMK AO2'

        with patch('app.requests.get', return_value=mock_resp):
            resp = client.get('/?icao=KJFK')

        assert resp.status_code == 200
        assert b'Overcast' in resp.data
        assert b'Light rain' in resp.data
        assert b'KJFK' in resp.data

    def test_invalid_icao_shows_error(self, client):
        """An ICAO that returns empty data should show an error message."""
        mock_resp = MagicMock()
        mock_resp.text = ''

        with patch('app.requests.get', return_value=mock_resp):
            resp = client.get('/?icao=XXXX')

        assert resp.status_code == 200
        assert b'No METAR data found' in resp.data

    def test_icao_lowercased_normalised(self, client):
        """Lowercase input should be normalised to uppercase before fetching."""
        mock_resp = MagicMock()
        mock_resp.text = 'KJFK 020451Z 08009KT 7SM CLR 11/09 A3027'

        with patch('app.requests.get', return_value=mock_resp) as mock_get:
            client.get('/?icao=kjfk')
            called_url = mock_get.call_args[0][0]

        assert 'KJFK' in called_url

    def test_timeout_shows_error(self, client):
        """A network timeout should display a user-friendly error."""
        import requests as req_lib
        with patch('app.requests.get', side_effect=req_lib.Timeout):
            resp = client.get('/?icao=KJFK')

        assert resp.status_code == 200
        assert b'timed out' in resp.data

    def test_network_error_shows_error(self, client):
        """A general network error should display a user-friendly error."""
        import requests as req_lib
        with patch('app.requests.get', side_effect=req_lib.RequestException('connection refused')):
            resp = client.get('/?icao=KJFK')

        assert resp.status_code == 200
        assert b'Could not reach' in resp.data

    def test_raw_metar_shown_in_results(self, client):
        """The raw METAR string should appear on the results page."""
        raw = 'KJFK 020451Z 08009G17KT 7SM -RA OVC018 11/09 A3027 RMK AO2'
        mock_resp = MagicMock()
        mock_resp.text = raw

        with patch('app.requests.get', return_value=mock_resp):
            resp = client.get('/?icao=KJFK')

        assert b'Raw METAR' in resp.data
        assert b'OVC018' in resp.data
