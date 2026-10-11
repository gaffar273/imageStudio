"""Different faces for different seeds, and for different people in one picture.

Image models drift to one "default" face for a given kind of person, so a new seed
alone often gives the same woman again, and a group comes out as copies of one face.
Small facial details barely move it; a heritage, a first name, age and hairstyle do.
One person gets these after the word that names them; a counted group ("five
friends") gets a separate description for every member. Everything is picked from the
seed, so the same seed reproduces the same people, and anything the request already
says (a heritage, the face) is left as written. Relatives share one heritage."""

import random
import re

FEMALE = r'woman|girl|lady|bride|mother|grandmother|wife|businesswoman|actress|queen|princess|sister|daughter'
MALE = r'man|boy|gentleman|guy|groom|father|grandfather|husband|businessman|fisherman|king|prince|brother|son'
NEUTRAL = r'person|chef|doctor|nurse|teacher|student|farmer|worker|athlete|soldier|scientist|artist|musician'
PERSON = re.compile(rf'\b(?:({FEMALE})|({MALE})|({NEUTRAL}))\b', re.I)
# Requests that already describe the face keep it.
DESCRIBED_FACE = re.compile(
    r'\b(face|faces|jaw|jawline|cheekbones|nose|lips|eyes|eyebrows|freckles|named)\b', re.I
)

# Groups: plural words for people, and how many.
GROUP_FEMALE = r'women|girls|ladies|sisters|daughters|granddaughters|mothers|brides'
GROUP_MALE = r'men|boys|guys|brothers|sons|grandsons|fathers'
GROUP_NEUTRAL = (
    r'friends|people|persons|kids|children|students|colleagues|coworkers|teammates|players|dancers|'
    r'workers|tourists|siblings|teenagers|adults|musicians|doctors|nurses|soldiers|athletes|customers|'
    r'shoppers|passengers|grandchildren|cousins'
)
YOUNG = re.compile(
    r'^(girls|boys|sons|daughters|grandsons|granddaughters|kids|children|teenagers|grandchildren)$', re.I
)
NUMBERS = {
    'two': 2,
    'three': 3,
    'four': 4,
    'five': 5,
    'six': 6,
    'seven': 7,
    'eight': 8,
    'nine': 9,
    'ten': 10,
    'eleven': 11,
    'twelve': 12,
}
NUMBER = r'\d{1,2}|' + '|'.join(NUMBERS)
GROUP = re.compile(
    rf'\b({NUMBER})\s+(?:[a-z-]+\s+){{0,2}}?(?:({GROUP_FEMALE})|({GROUP_MALE})|({GROUP_NEUTRAL}))\b', re.I
)
GROUP_OF = re.compile(
    rf'\b(family|group|team|band|crew|circle) of ({NUMBER})(?:\s+(?:{GROUP_NEUTRAL}))?\b', re.I
)
PEOPLE = re.compile(rf'\b(?:{GROUP_FEMALE}|{GROUP_MALE}|{GROUP_NEUTRAL})\b', re.I)
# "a family restaurant" or "a family car" is not a family of people.
FAMILY = (
    r'famil(?:y|ies)(?!\s+(?:restaurant|business|shop|store|car|van|home|house|room|style|friendly|'
    r'farm|run|owned|name|tree|recipe|kitchen|hotel|cafe|diner|bakery|market))'
)
CROWD = re.compile(rf'\b(?:crowd|group|team|{FAMILY})\b', re.I)
# Friends, classmates and teammates are usually close in age.
PEERS = re.compile(
    r'^(friends|students|teammates|colleagues|coworkers|players|dancers|athletes|cousins)$', re.I
)
KIN = re.compile(
    rf'\b({FAMILY}|grandmother|grandfather|grandparents|grandsons?|granddaughters?|'
    r'grandchildren|mother|father|parents|sons?|daughters?|siblings|brothers?|sisters?|cousins|'
    r'twins)\b',
    re.I,
)
MOST_DESCRIBED = 8  # beyond this, one instruction for the whole group

# (heritage, female name, male name)
HERITAGES = [
    ('Indian', 'Priya', 'Arjun'),
    ('Korean', 'Min-ji', 'Ji-ho'),
    ('Brazilian', 'Camila', 'Rafael'),
    ('Nigerian', 'Adaeze', 'Chinedu'),
    ('Irish', 'Siobhan', 'Cian'),
    ('Italian', 'Giulia', 'Matteo'),
    ('Mexican', 'Lucia', 'Diego'),
    ('Japanese', 'Yuki', 'Haruto'),
    ('Ethiopian', 'Selam', 'Dawit'),
    ('Swedish', 'Astrid', 'Erik'),
    ('Lebanese', 'Nour', 'Karim'),
    ('Filipino', 'Maria', 'Paolo'),
    ('Polish', 'Zofia', 'Jakub'),
    ('Moroccan', 'Salma', 'Youssef'),
    ('Greek', 'Eleni', 'Nikos'),
    ('Vietnamese', 'Linh', 'Minh'),
    ('Pakistani', 'Ayesha', 'Bilal'),
    ('Chinese', 'Mei', 'Wei'),
    ('Ghanaian', 'Akosua', 'Kwame'),
    ('Turkish', 'Elif', 'Emre'),
    ('Peruvian', 'Valeria', 'Mateo'),
    ('Russian', 'Anya', 'Dmitri'),
    ('Iranian', 'Shirin', 'Dariush'),
    ('Thai', 'Ploy', 'Niran'),
]
# A heritage already in the request is kept; no second one is added.
HERITAGE_WORDS = re.compile(
    r'\b(' + '|'.join(h for h, _, _ in HERITAGES) + r'|american|british|english|scottish|'
    r'welsh|french|german|spanish|portuguese|dutch|arab|arabic|bangladeshi|sri lankan|'
    r'nepali|indonesian|malaysian|african|asian|european|latina|latino|hispanic|caucasian|'
    r'scandinavian|middle eastern|south asian|east asian|desi|punjabi|tamil|bengali|'
    r'kenyan|egyptian|australian|canadian|ukrainian)\b',
    re.I,
)

FACE_SHAPES = [
    'oval face',
    'round face',
    'heart-shaped face',
    'square jaw',
    'long narrow face',
    'high cheekbones',
    'soft full cheeks',
    'angular face',
]
DETAILS = [
    'light freckles',
    'a small mole on the cheek',
    'dimples',
    'thick eyebrows',
    'arched eyebrows',
    'full lips',
    'thin lips',
    'a broad nose',
    'an aquiline nose',
    'a button nose',
    'laugh lines',
    'a gap between the front teeth',
]
HAIR = {
    'female': [
        'long straight black hair',
        'short curly brown hair',
        'a blonde bob',
        'auburn hair in a ponytail',
        'long wavy dark hair',
        'a pixie cut',
        'braided hair',
        'shoulder-length red hair',
        'a high bun',
        'curly black hair',
    ],
    'male': [
        'a shaved head',
        'short curly black hair',
        'neatly parted brown hair',
        'long hair tied back',
        'a buzz cut',
        'wavy blond hair',
        'grey hair',
        'thick black hair',
        'a short fade',
        'messy red hair',
    ],
}
EXTRAS = {
    'female': ['glasses', 'freckles', 'dimples', 'bangs', 'thick eyebrows', 'a wide smile'],
    'male': ['a full beard', 'a moustache', 'stubble', 'glasses', 'no beard', 'freckles'],
    'young': ['freckles', 'dimples', 'glasses', 'a missing front tooth', 'rosy cheeks', 'a wide grin'],
}
BUILDS = ['slim', 'tall', 'short', 'stocky', 'athletic', 'broad-shouldered']


def article(word):
    return 'an' if word[:1].lower() in 'aeiou' else 'a'


def with_article(phrase):
    """'an oval face', but 'high cheekbones' (plural) as it is."""
    return phrase if phrase.split()[-1].endswith('s') else f'{article(phrase)} {phrase}'


def describe(rng, gender, heritage_choice):
    """Features for one named person: (heritage or None, words after the person)."""
    heritage, female, male = heritage_choice or rng.choice(HERITAGES)
    face = f'{with_article(rng.choice(FACE_SHAPES))} and {rng.choice(DETAILS)}'
    if heritage_choice is False:
        return None, f'with {face}'
    name = female if gender == 'female' else male if gender == 'male' else None
    return heritage, (f'named {name}, ' if name else '') + f'with {face}'


def vary_person(prompt, rng, heritage_choice):
    """Heritage, name and features after the first single person the prompt names.
    Returns the prompt and that person's description (None if nobody is named)."""
    match = PERSON.search(prompt)
    if not match:
        return prompt, None
    gender = 'female' if match.group(1) else 'male' if match.group(2) else None
    heritage, features = describe(rng, gender, heritage_choice)
    before = prompt[: match.start()]
    if heritage:
        before = re.sub(
            r'\b([Aa])n? $', lambda a: a.group(1) + ('n ' if heritage[0] in 'AEIOU' else ' '), before
        )
    person = f'{heritage} {match.group(0)}' if heritage else match.group(0)
    # Early words count most for SDXL, so everything goes where the person is first named.
    after = prompt[match.end() :]
    return f'{before}{person} {features}{"" if after.startswith(",") else ","}{after}', f'{person} {features}'


def members(rng, count, kind, noun, heritage_choice, short):
    """One distinct description per group member."""
    young = bool(YOUNG.match(noun))
    family = noun.lower() == 'family'
    heritages = (
        [heritage_choice] * count
        if heritage_choice is not None
        else rng.sample(HERITAGES, count)
        if count <= len(HERITAGES)
        else [rng.choice(HERITAGES) for _ in range(count)]
    )
    genders = [kind if kind in ('female', 'male') else rng.choice(['female', 'male']) for _ in range(count)]
    hair = {gender: rng.sample(HAIR[gender], len(HAIR[gender])) for gender in HAIR}
    people = []
    for index, gender in enumerate(genders):
        child = young or (family and index >= 2)
        words = ('girl' if child else 'woman') if gender == 'female' else ('boy' if child else 'man')
        age = (
            rng.randint(6, 15)
            if child
            else rng.randint(30, 45)
            if family
            else rng.randint(19, 34)
            if PEERS.match(noun)
            else rng.randint(20, 60)
        )
        heritage = heritages[index][0] if heritages[index] else ''
        this_hair = hair[gender][index % len(hair[gender])]
        if short:
            text = f'{heritage} {words} with {this_hair}'.strip()
        else:
            extra = rng.choice(EXTRAS['young' if child else gender])
            build = '' if child else rng.choice(BUILDS) + ' '
            text = (
                (
                    f'{build}{heritage} {words} about {age} with {this_hair}, '
                    f'{with_article(rng.choice(FACE_SHAPES))} and {extra}'
                )
                .replace('  ', ' ')
                .strip()
            )
        people.append(f'{article(text)} {text}')
    return people


def vary_group(prompt, rng, heritage_choice, short):
    """A description for every member of a counted group; otherwise ask for different faces.
    Returns the prompt and the members' descriptions from left to right ([] when their
    order is not in the prompt, None when there is no group)."""
    match, count, kind, noun = GROUP.search(prompt), None, 'any', ''
    if match:
        word = match.group(1).lower()
        count = int(word) if word.isdigit() else NUMBERS[word]
        kind = 'female' if match.group(2) else 'male' if match.group(3) else 'any'
        noun = match.group(2) or match.group(3) or match.group(4)
    else:
        match = GROUP_OF.search(prompt)
        if match:
            word = match.group(2).lower()
            count = int(word) if word.isdigit() else NUMBERS[word]
            noun = match.group(1)
    if match and 2 <= count <= MOST_DESCRIBED:
        people = members(rng, count, kind, noun, heritage_choice, short)
        listing = f' ({"from left to right: " if not short else ""}{"; ".join(people)})'
        return prompt[: match.end()] + listing + prompt[match.end() :], [] if short else people
    # The note goes after the word for the people ("a crowd of people (...)"), else after "crowd".
    crowd = match or PEOPLE.search(prompt) or CROWD.search(prompt)
    # "a street with no people" asks for nobody.
    if not crowd or re.search(r'\b(no|without|zero)\s+$', prompt[: crowd.start()], re.I):
        return prompt, None
    note = (
        ' (each with a clearly different face and hairstyle)'
        if heritage_choice is not None
        else ' (each with a clearly different face, age, hairstyle and heritage)'
    )
    return prompt[: crowd.end()] + note + prompt[crowd.end() :], []


def vary(prompt, seed, short=False):
    """The prompt with seed-chosen, distinct people, and those people's descriptions from
    left to right for face repair ([] when unknown). `short` keeps it brief for SDXL's
    75-word limit."""
    if DESCRIBED_FACE.search(prompt):
        return prompt, []
    rng = random.Random(seed)
    # False: keep the request's heritage; a tuple: one shared heritage for relatives; None: each their own.
    heritage_choice = (
        False if HERITAGE_WORDS.search(prompt) else rng.choice(HERITAGES) if KIN.search(prompt) else None
    )
    varied, person = vary_person(prompt, random.Random(seed), heritage_choice)
    # Group members get no heritage word when the request names one ('' leaves it out).
    varied, group = vary_group(
        varied, rng, ('', '', '') if heritage_choice is False else heritage_choice, short
    )
    # A group's members replace the single person; an unordered crowd leaves them unknown.
    return varied, group if group is not None else [person] if person else []


def vary_faces(prompt, seed, short=False):
    return vary(prompt, seed, short)[0]


def heritage_of(person):
    """The heritage a person's description names, as in HERITAGES, or None."""
    names = {heritage.lower(): heritage for heritage, _, _ in HERITAGES}
    match = HERITAGE_WORDS.search(person)
    return names.get(match.group(1).lower()) if match else None


def for_repair(person):
    """A person's description without heritage or name. Face repair should keep the face
    that was drawn; when the model did not follow the heritage it was given, naming it in
    the repair would recast the face to match the words."""
    person = re.sub(r'\bnamed [A-Z][\w-]*,?\s*', '', person)
    person = HERITAGE_WORDS.sub('', person)
    person = re.sub(r'^\s*an?\s+(?=[aeiou])', 'an ', re.sub(r'^\s*an?\s+', 'a ', person))
    return re.sub(r'\s{2,}', ' ', person).strip()


def face_details(seed, index):
    """Distinct features for a face whose person is not described. No heritage, gender or
    age, so they cannot contradict the face being repaired."""
    rng = random.Random(seed * 31 + index)
    return f'{with_article(rng.choice(FACE_SHAPES))} and {rng.choice(DETAILS)}'
