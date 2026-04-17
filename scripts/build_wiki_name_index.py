"""Helper: build a Wikipedia-name → IATA index.

Strategy:
  1. Seed from airportsdata (~7,900 airports).
  2. Index by normalized name tokens.
  3. Add hand-curated synonyms where Wikipedia titles differ materially
     (short-form names like "Heathrow Airport" vs airportsdata's
     "London Heathrow Airport").

Exposes `lookup(wiki_title) -> iata_code or None`.
"""

import re
import unicodedata
from functools import lru_cache

import airportsdata

_DATA = airportsdata.load('IATA')


def normalize(s: str) -> str:
    """Lowercase, strip diacritics, normalize separators, drop fluff words."""
    s = s.lower()
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.replace('–', ' ').replace('—', ' ').replace('/', ' ').replace('-', ' ')
    s = re.sub(r'[^a-z0-9 ]+', ' ', s)
    # Drop generic tokens
    drops = {
        'international', 'airport', 'intcntl', 'intl',
        'municipal', 'regional', 'county', 'metro', 'metropolitan',
        'wayne', 'afb',
    }
    tokens = [t for t in s.split() if t and t not in drops]
    return ' '.join(tokens)


# Hand-curated synonyms (Wikipedia-title → IATA).
# Use when normalize() collision doesn't give a unique match, or when the
# Wikipedia title contains a personal name we want to elide.
SYNONYMS: dict[str, str] = {
    # US
    "daniel k inouye airport": "HNL",
    "honolulu airport": "HNL",
    "hartsfield jackson atlanta airport": "ATL",
    "logan airport": "BOS",
    "general edward lawrence logan airport": "BOS",
    "charlotte douglas airport": "CLT",
    "dallas fort worth airport": "DFW",
    "cleveland hopkins airport": "CLE",
    "detroit airport": "DTW",
    "detroit wayne airport": "DTW",
    "austin bergstrom airport": "AUS",
    "george bush intercontinental airport": "IAH",
    "george bush intcntl houston airport": "IAH",
    "dulles airport": "IAD",
    "washington dulles airport": "IAD",
    "ronald reagan washington national airport": "DCA",
    "john wayne airport": "SNA",
    "john wayne orange county airport": "SNA",
    "charleston airport": "CHS",
    "fort lauderdale hollywood airport": "FLL",
    "cyril e king airport": "STT",
    "henry e rohlsen airport": "STX",
    "rafael hernandez airport": "BQN",  # Puerto Rico (US)
    "luis munoz marin airport": "SJU",
    "ted stevens anchorage airport": "ANC",
    "kansas city airport": "MCI",
    "sacramento airport": "SMF",
    "palm beach airport": "PBI",
    "san diego airport": "SAN",
    "southwest florida airport": "RSW",
    "harry reid airport": "LAS",
    "orlando airport": "MCO",
    "phoenix sky harbor airport": "PHX",
    "san antonio airport": "SAT",
    "savannah hilton head airport": "SAV",
    "portland airport": "PDX",
    "salt lake city airport": "SLC",
    "tampa airport": "TPA",
    "louis armstrong new orleans airport": "MSY",
    "bozeman yellowstone airport": "BZN",
    "eagle county airport": "EGE",
    "glacier park airport": "FCA",
    "jackson hole airport": "JAC",
    "montrose airport": "MTJ",
    "myrtle beach airport": "MYR",
    "palm springs airport": "PSP",
    "yampa valley airport": "HDN",
    "key west airport": "EYW",
    "jacksonville airport": "JAX",
    "miami airport": "MIA",
    "nashville airport": "BNA",
    "o hare airport": "ORD",
    "chicago o hare airport": "ORD",
    "chicago midway airport": "MDW",
    "midway airport": "MDW",
    "minneapolis saint paul airport": "MSP",
    "minneapolis st paul airport": "MSP",
    "baltimore washington airport": "BWI",
    "baltimore washington thurgood marshall airport": "BWI",
    "kona airport": "KOA",
    "ellison onizuka kona airport": "KOA",
    "boise airport": "BOI",
    "eugene airport": "EUG",
    "hollywood burbank airport": "BUR",
    "bob hope airport": "BUR",
    "memphis airport": "MEM",
    "wichita dwight d eisenhower airport": "ICT",
    "wichita airport": "ICT",
    "northwest arkansas airport": "XNA",
    "mcallen miller airport": "MFE",
    "dane county airport": "MSN",
    "madison airport": "MSN",
    # Europe
    "heathrow airport": "LHR",
    "london heathrow airport": "LHR",
    "amsterdam airport schiphol": "AMS",
    "amsterdam schiphol": "AMS",
    "frankfurt airport": "FRA",
    "frankfurt am main airport": "FRA",
    "munich airport": "MUC",
    "zurich airport": "ZRH",
    "geneva airport": "GVA",
    "geneva cointrin airport": "GVA",
    "vienna airport": "VIE",
    "vienna schwechat airport": "VIE",
    "lisbon airport": "LIS",
    "lisbon portela airport": "LIS",
    "humberto delgado airport": "LIS",
    "madrid barajas airport": "MAD",
    "adolfo suarez madrid barajas airport": "MAD",
    "barcelona airport": "BCN",
    "barcelona el prat airport": "BCN",
    "josep tarradellas barcelona el prat airport": "BCN",
    "bilbao airport": "BIO",
    "palma de mallorca airport": "PMI",
    "son sant joan airport": "PMI",
    "rome fiumicino airport": "FCO",
    "leonardo da vinci fiumicino airport": "FCO",
    "milan malpensa airport": "MXP",
    "venice marco polo airport": "VCE",
    "naples airport": "NAP",
    "bari karol wojtyla airport": "BRI",
    "bari karol wojty a airport": "BRI",
    "bari palese airport": "BRI",
    "northwest arkansas national airport": "XNA",
    "wichita dwight d eisenhower national airport": "ICT",
    "athens airport": "ATH",
    "eleftherios venizelos athens airport": "ATH",
    "istanbul airport": "IST",
    "dublin airport": "DUB",
    "shannon airport": "SNN",
    "edinburgh airport": "EDI",
    "glasgow airport": "GLA",
    "manchester airport": "MAN",
    "brussels airport": "BRU",
    "berlin brandenburg airport": "BER",
    "copenhagen airport": "CPH",
    "kastrup airport": "CPH",
    "stockholm arlanda airport": "ARN",
    "oslo airport": "OSL",
    "helsinki airport": "HEL",
    "helsinki vantaa airport": "HEL",
    "reykjavik keflavik airport": "KEF",
    "keflavik airport": "KEF",
    "vaclav havel airport prague": "PRG",
    "prague airport": "PRG",
    "charles de gaulle airport": "CDG",
    "paris charles de gaulle airport": "CDG",
    "paris orly airport": "ORY",
    "nice cote d azur airport": "NCE",
    "dubrovnik airport": "DBV",
    "split airport": "SPU",
    "madeira airport": "FNC",
    "faro airport": "FAO",
    "porto airport": "OPO",
    "francisco sa carneiro airport": "OPO",
    "nice cote d azur airport": "NCE",
    "palermo airport": "PMO",
    "falcone borsellino airport": "PMO",
    "bari karol wojtyla airport": "BRI",
    "santiago rosalia de castro airport": "SCQ",
    "santiago de compostela airport": "SCQ",
    # Middle East / Africa
    "ben gurion airport": "TLV",
    "ben gurion international airport": "TLV",
    "dubai airport": "DXB",
    "hamad airport": "DOH",
    "king khalid airport": "RUH",
    "king abdulaziz airport": "JED",
    "kotoka airport": "ACC",
    "accra airport": "ACC",
    "murtala muhammed airport": "LOS",
    "o r tambo airport": "JNB",
    "johannesburg airport": "JNB",
    "cape town airport": "CPT",
    "menara airport": "RAK",
    "marrakesh menara airport": "RAK",
    # Asia / Pacific
    "narita airport": "NRT",
    "tokyo narita airport": "NRT",
    "haneda airport": "HND",
    "tokyo airport": "HND",
    "kansai airport": "KIX",
    "kansai osaka airport": "KIX",
    "beijing capital airport": "PEK",
    "shanghai pudong airport": "PVG",
    "guangzhou baiyun airport": "CAN",
    "hong kong airport": "HKG",
    "chek lap kok airport": "HKG",
    "taipei taoyuan airport": "TPE",
    "taiwan taoyuan airport": "TPE",
    "singapore changi airport": "SIN",
    "changi airport": "SIN",
    "incheon airport": "ICN",
    "seoul incheon airport": "ICN",
    "ninoy aquino airport": "MNL",
    "suvarnabhumi airport": "BKK",
    "kuala lumpur airport": "KUL",
    "indira gandhi airport": "DEL",
    "delhi indira gandhi airport": "DEL",
    "chhatrapati shivaji maharaj airport": "BOM",
    "mumbai airport": "BOM",
    "sydney airport": "SYD",
    "kingsford smith airport": "SYD",
    "melbourne airport": "MEL",
    "auckland airport": "AKL",
    # Latin America / Caribbean
    "benito juarez airport": "MEX",
    "mexico city airport": "MEX",
    "licenciado benito juarez airport": "MEX",
    "licenciado gustavo diaz ordaz airport": "PVR",
    "puerto vallarta airport": "PVR",
    "los cabos airport": "SJD",
    "cancun airport": "CUN",
    "juan santamaria airport": "SJO",
    "tocumen airport": "PTY",
    "panama city tocumen airport": "PTY",
    "el dorado airport": "BOG",
    "jorge chavez airport": "LIM",
    "guarulhos airport": "GRU",
    "sao paulo guarulhos airport": "GRU",
    "galeao airport": "GIG",
    "rio de janeiro galeao airport": "GIG",
    "ministro pistarini airport": "EZE",
    "buenos aires ezeiza airport": "EZE",
    "arturo merino benitez airport": "SCL",
    "santiago airport": "SCL",
    "silvio pettirossi airport": "ASU",
    "rafael nunez airport": "CTG",
    "cartagena airport": "CTG",
    "la aurora airport": "GUA",
    "guatemala city airport": "GUA",
    "el salvador airport": "SAL",
    "comalapa airport": "SAL",
    "philip s w goldson airport": "BZE",
    "belize city airport": "BZE",
    "v c bird airport": "ANU",
    "queen beatrix airport": "AUA",
    "aruba airport": "AUA",
    "grantley adams airport": "BGI",
    "barbados airport": "BGI",
    "cibao airport": "STI",
    "las americas airport": "SDQ",
    "santo domingo airport": "SDQ",
    "punta cana airport": "PUJ",
    "princess juliana airport": "SXM",
    "st maarten airport": "SXM",
    "sangster airport": "MBJ",
    "montego bay airport": "MBJ",
    "norman manley airport": "KIN",
    "kingston airport": "KIN",
    "owen roberts airport": "GCM",
    "grand cayman airport": "GCM",
    "gregorio luperon airport": "POP",
    "puerto plata airport": "POP",
    "piarco airport": "POS",
    "port of spain airport": "POS",
    "flamingo airport": "BON",
    "bonaire airport": "BON",
    "hato airport": "CUR",
    "curacao airport": "CUR",
    "robert l bradshaw airport": "SKB",
    "st kitts airport": "SKB",
    "hewanorra airport": "UVF",
    "st lucia hewanorra airport": "UVF",
    "douglas charles airport": "DOM",
    "melville hall airport": "DOM",
    "lynden pindling airport": "NAS",
    "nassau airport": "NAS",
    "l f wade airport": "BDA",
    "bermuda airport": "BDA",
    "nuuk airport": "GOH",
    "guanacaste airport": "NCT",   # alt LIR
    "tulum airport": "TQO",
    "felipe carrillo puerto tulum airport": "TQO",
    "cozumel airport": "CZM",
    "cozumel international airport": "CZM",
    "guadalajara airport": "GDL",
    "miguel hidalgo airport": "GDL",
    "monterrey airport": "MTY",
    "general mariano escobedo airport": "MTY",
    "merida airport": "MID",
    "manuel crescencio rejon airport": "MID",
    "bajio airport": "BJX",
    "guanajuato airport": "BJX",
    "tampico airport": "TAM",
    "francisco javier mina airport": "TAM",
    "veracruz airport": "VER",
    "general heriberto jara airport": "VER",
    "san luis potosi airport": "SLP",
    "ponciano arriaga airport": "SLP",
    "queretaro airport": "QRO",
    "ingeniero fernando espinoza gutierrez airport": "QRO",
    "augusto c sandino airport": "MGA",
    "managua airport": "MGA",
    "comayagua airport": "XPL",
    "palmerola airport": "XPL",
    "ramon villeda morales airport": "SAP",
    "san pedro sula airport": "SAP",
    "golosón airport": "LCE",
    "goloson airport": "LCE",
    "la ceiba airport": "LCE",
    "juan manuel galvez airport": "RTB",
    "juan manuel galvez roatan airport": "RTB",
    "roatán airport": "RTB",
    "roatan airport": "RTB",
    "mariscal sucre airport": "UIO",
    "mariscal sucre quito airport": "UIO",
    "quito airport": "UIO",
    "cheddi jagan airport": "GEO",
    "georgetown airport": "GEO",
    "jose joaquin de olmedo airport": "GYE",
    "guayaquil airport": "GYE",
    "mohammed v airport": "CMN",
    "casablanca airport": "CMN",
    "grantley adams international airport": "BGI",
    "providenciales airport": "PLS",
    "howard hughes airport": "TZA",
    "belmopan airport": "TZA",
    "taoyuan international airport": "TPE",
    "taoyuan airport": "TPE",
    "daniel oduber airport": "LIR",
    "liberia costa rica airport": "LIR",
    # Canada
    "vancouver airport": "YVR",
    "toronto pearson airport": "YYZ",
    "pearson airport": "YYZ",
    "montreal trudeau airport": "YUL",
    "pierre elliott trudeau airport": "YUL",
    "calgary airport": "YYC",
}

# Build name-to-IATA index
_INDEX: dict[str, str] = {}

def _seed():
    if _INDEX:
        return
    # 1. Seed from airportsdata
    for code, info in _DATA.items():
        key = normalize(info['name'])
        if key and key not in _INDEX:
            _INDEX[key] = code
    # 2. Overlay synonyms (normalized)
    for wiki_name, code in SYNONYMS.items():
        _INDEX[normalize(wiki_name)] = code


@lru_cache(maxsize=4096)
def lookup(wiki_title: str) -> str | None:
    """Return IATA code for a Wikipedia airport page title, or None if unknown."""
    _seed()
    key = normalize(wiki_title)
    if not key:
        return None
    return _INDEX.get(key)


def country_of(iata: str) -> str | None:
    info = _DATA.get(iata)
    return info['country'] if info else None


def city_of(iata: str) -> str | None:
    info = _DATA.get(iata)
    return info['city'] if info else None
