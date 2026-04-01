# -*- coding: utf-8 -*-
"""Single source: 100 countries (ISO2 + zh + en) + Wikimedia Commons demonym for category search."""

from __future__ import annotations

# (code, zh, en) — en used for “People of {en}” fallbacks and credits.
COUNTRIES: list[tuple[str, str, str]] = [
    ("CN", "中国", "China"),
    ("IN", "印度", "India"),
    ("US", "美国", "United States"),
    ("ID", "印度尼西亚", "Indonesia"),
    ("BR", "巴西", "Brazil"),
    ("PK", "巴基斯坦", "Pakistan"),
    ("NG", "尼日利亚", "Nigeria"),
    ("BD", "孟加拉国", "Bangladesh"),
    ("RU", "俄罗斯", "Russia"),
    ("JP", "日本", "Japan"),
    ("MX", "墨西哥", "Mexico"),
    ("PH", "菲律宾", "Philippines"),
    ("EG", "埃及", "Egypt"),
    ("ET", "埃塞俄比亚", "Ethiopia"),
    ("DE", "德国", "Germany"),
    ("IR", "伊朗", "Iran"),
    ("TR", "土耳其", "Turkey"),
    ("FR", "法国", "France"),
    ("GB", "英国", "United Kingdom"),
    ("TH", "泰国", "Thailand"),
    ("IT", "意大利", "Italy"),
    ("ZA", "南非", "South Africa"),
    ("TZ", "坦桑尼亚", "Tanzania"),
    ("MM", "缅甸", "Myanmar"),
    ("KR", "韩国", "South Korea"),
    ("CO", "哥伦比亚", "Colombia"),
    ("ES", "西班牙", "Spain"),
    ("UG", "乌干达", "Uganda"),
    ("AR", "阿根廷", "Argentina"),
    ("MA", "摩洛哥", "Morocco"),
    ("SA", "沙特阿拉伯", "Saudi Arabia"),
    ("MY", "马来西亚", "Malaysia"),
    ("PE", "秘鲁", "Peru"),
    ("VE", "委内瑞拉", "Venezuela"),
    ("GH", "加纳", "Ghana"),
    ("NP", "尼泊尔", "Nepal"),
    ("YE", "也门", "Yemen"),
    ("AF", "阿富汗", "Afghanistan"),
    ("IQ", "伊拉克", "Iraq"),
    ("TW", "台湾", "Taiwan"),
    ("AU", "澳大利亚", "Australia"),
    ("DZ", "阿尔及利亚", "Algeria"),
    ("SD", "苏丹", "Sudan"),
    ("UZ", "乌兹别克斯坦", "Uzbekistan"),
    ("AO", "安哥拉", "Angola"),
    ("MZ", "莫桑比克", "Mozambique"),
    ("PL", "波兰", "Poland"),
    ("UA", "乌克兰", "Ukraine"),
    ("CI", "科特迪瓦", "Ivory Coast"),
    ("MG", "马达加斯加", "Madagascar"),
    ("CM", "喀麦隆", "Cameroon"),
    ("NL", "荷兰", "Netherlands"),
    ("RO", "罗马尼亚", "Romania"),
    ("KZ", "哈萨克斯坦", "Kazakhstan"),
    ("SY", "叙利亚", "Syria"),
    ("EC", "厄瓜多尔", "Ecuador"),
    ("GT", "危地马拉", "Guatemala"),
    ("SN", "塞内加尔", "Senegal"),
    ("TD", "乍得", "Chad"),
    ("SO", "索马里", "Somalia"),
    ("ZW", "津巴布韦", "Zimbabwe"),
    ("GN", "几内亚", "Guinea"),
    ("RW", "卢旺达", "Rwanda"),
    ("BE", "比利时", "Belgium"),
    ("BF", "布基纳法索", "Burkina Faso"),
    ("NE", "尼日尔", "Niger"),
    ("MW", "马拉维", "Malawi"),
    ("CH", "瑞士", "Switzerland"),
    ("TN", "突尼斯", "Tunisia"),
    ("BG", "保加利亚", "Bulgaria"),
    ("BJ", "贝宁", "Benin"),
    ("TG", "多哥", "Togo"),
    ("LY", "利比亚", "Libya"),
    ("LR", "利比里亚", "Liberia"),
    ("LB", "黎巴嫩", "Lebanon"),
    ("SK", "斯洛伐克", "Slovakia"),
    ("SL", "塞拉利昂", "Sierra Leone"),
    ("NO", "挪威", "Norway"),
    ("FI", "芬兰", "Finland"),
    ("DK", "丹麦", "Denmark"),
    ("IE", "爱尔兰", "Ireland"),
    ("HR", "克罗地亚", "Croatia"),
    ("BA", "波黑", "Bosnia and Herzegovina"),
    ("LT", "立陶宛", "Lithuania"),
    ("LV", "拉脱维亚", "Latvia"),
    ("EE", "爱沙尼亚", "Estonia"),
    ("RS", "塞尔维亚", "Serbia"),
    ("GE", "格鲁吉亚", "Georgia"),
    ("AM", "亚美尼亚", "Armenia"),
    ("AZ", "阿塞拜疆", "Azerbaijan"),
    ("JO", "约旦", "Jordan"),
    ("KW", "科威特", "Kuwait"),
    ("QA", "卡塔尔", "Qatar"),
    ("OM", "阿曼", "Oman"),
    ("BH", "巴林", "Bahrain"),
    ("CY", "塞浦路斯", "Cyprus"),
    ("MT", "马耳他", "Malta"),
    ("AL", "阿尔巴尼亚", "Albania"),
    ("MK", "北马其顿", "North Macedonia"),  # Commons: North Macedonians
    ("MD", "摩尔多瓦", "Moldova"),
]

assert len(COUNTRIES) == 100, len(COUNTRIES)

# Wikimedia Commons category prefix: "Category:{value} people"
DEMONYMS: dict[str, str] = {
    "CN": "Chinese",
    "IN": "Indian",
    "US": "American",
    "ID": "Indonesian",
    "BR": "Brazilian",
    "PK": "Pakistani",
    "NG": "Nigerian",
    "BD": "Bangladeshi",
    "RU": "Russian",
    "JP": "Japanese",
    "MX": "Mexican",
    "PH": "Filipino",
    "EG": "Egyptian",
    "ET": "Ethiopian",
    "DE": "German",
    "IR": "Iranian",
    "TR": "Turkish",
    "FR": "French",
    "GB": "British",
    "TH": "Thai",
    "IT": "Italian",
    "ZA": "South African",
    "TZ": "Tanzanian",
    "MM": "Burmese",
    "KR": "South Korean",
    "CO": "Colombian",
    "ES": "Spanish",
    "UG": "Ugandan",
    "AR": "Argentine",
    "MA": "Moroccan",
    "SA": "Saudi Arabian",
    "MY": "Malaysian",
    "PE": "Peruvian",
    "VE": "Venezuelan",
    "GH": "Ghanaian",
    "NP": "Nepalese",
    "YE": "Yemeni",
    "AF": "Afghan",
    "IQ": "Iraqi",
    "TW": "Taiwanese",
    "AU": "Australian",
    "DZ": "Algerian",
    "SD": "Sudanese",
    "UZ": "Uzbek",
    "AO": "Angolan",
    "MZ": "Mozambican",
    "PL": "Polish",
    "UA": "Ukrainian",
    "CI": "Ivorian",
    "MG": "Malagasy",
    "CM": "Cameroonian",
    "NL": "Dutch",
    "RO": "Romanian",
    "KZ": "Kazakhstani",
    "SY": "Syrian",
    "EC": "Ecuadorian",
    "GT": "Guatemalan",
    "SN": "Senegalese",
    "TD": "Chadian",
    "SO": "Somali",
    "ZW": "Zimbabwean",
    "GN": "Guinean",
    "RW": "Rwandan",
    "BE": "Belgian",
    "BF": "Burkinabe",
    "NE": "Nigerien",
    "MW": "Malawian",
    "CH": "Swiss",
    "TN": "Tunisian",
    "BG": "Bulgarian",
    "BJ": "Beninese",
    "TG": "Togolese",
    "LY": "Libyan",
    "LR": "Liberian",
    "LB": "Lebanese",
    "SK": "Slovak",
    "SL": "Sierra Leonean",
    "NO": "Norwegian",
    "FI": "Finnish",
    "DK": "Danish",
    "IE": "Irish",
    "HR": "Croatian",
    "BA": "Bosnian",
    "LT": "Lithuanian",
    "LV": "Latvian",
    "EE": "Estonian",
    "RS": "Serbian",
    "GE": "Georgian",
    "AM": "Armenian",
    "AZ": "Azerbaijani",
    "JO": "Jordanian",
    "KW": "Kuwaiti",
    "QA": "Qatari",
    "OM": "Omani",
    "BH": "Bahraini",
    "CY": "Cypriot",
    "MT": "Maltese",
    "AL": "Albanian",
    "MK": "North Macedonian",
    "MD": "Moldovan",
}

assert set(DEMONYMS.keys()) == {c[0] for c in COUNTRIES}

# Extra Commons categories (verified/near-standard) for codes that often return no CC hits.
_EXTRA_CATEGORIES: dict[str, list[str]] = {
    "US": [
        "American men",
        "American women",
        "People of the United States by occupation",
    ],
    "GB": [
        "English people",
        "Scottish people",
        "Welsh people",
    ],
    "NL": [
        "Dutch men",
        "Dutch women",
        "People of the Netherlands",
    ],
    "PH": [
        "Filipino men",
        "Filipino women",
        "People of the Philippines",
    ],
    "GE": [
        "People of Georgia (country)",
        "Georgian men",
        "Georgian women",
    ],
    # Direct files are often under subcats; these return files on Commons (verified via API).
    "EE": [
        "Featured pictures of people of Estonia",
        "People of Tallinn",
        "People of Tartu",
        "People in Estonia",
        "Estonian men",
        "Estonian women",
    ],
}


def population_index(code: str) -> int:
    for i, (c, _zh, _en) in enumerate(COUNTRIES):
        if c == code:
            return i
    return 0


def categories_for(code: str, en: str) -> list[str]:
    """Category titles without 'Category:' prefix."""
    extra: list[str] = []
    if code == "MK":
        extra.append("North Macedonians")
    if code == "GB":
        extra.append("British people")
    extra.extend(_EXTRA_CATEGORIES.get(code, []))
    d = DEMONYMS.get(code)
    out: list[str] = list(extra)
    if d:
        out.append(f"{d} people")
    # Commons uses "People of the …" for several English country names; the bare
    # "People of X" page is often empty (e.g. United Kingdom, United States, Netherlands).
    out.append(f"People of {en}")
    out.append(f"People of the {en}")
    # Dedupe while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq
