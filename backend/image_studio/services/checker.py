"""Check a generated image against the request, and say what to fix.

The request is broken into small checks (an object, its color, a count, a position),
because a vision model answers "Is the cube red?" far more reliably than "How well does
this image match?". Each check is asked separately about the image; yes/no checks are
scored by how sure the model is, counts by the number it reads."""

import json
import re
from image_studio.services import assistant

CHECKS_SYSTEM = """You turn a picture request into a checklist for inspecting the finished picture. Write short, concrete questions that can each be answered by looking at the picture: each requested object and its color or material, each count, each position (left, center, right, in front, behind), the setting, the lighting and the style, and any written text. One fact per question. For a number of things, ask "How many ...?" and give the expected number as "count". Ask only about what the request says. Answer only with JSON."""

CHECKS_EXAMPLES = [
    (
        'Two green apples on the left and a white mug on the right, on a wooden table, soft morning light.',
        '{"checks": ['
        '{"question": "How many apples are there?", "count": 2}, '
        '{"question": "Are the apples green?"}, '
        '{"question": "How many mugs are there?", "count": 1}, '
        '{"question": "Is the mug white?"}, '
        '{"question": "Are the apples on the left side of the picture?"}, '
        '{"question": "Is the mug on the right side of the picture?"}, '
        '{"question": "Are the objects on a wooden table?"}, '
        '{"question": "Is the light soft?"}]}',
    ),
    (
        'Close-up photo of an elderly Indian fisherman in a faded blue shirt beside the sea at sunrise, a sign saying "FRESH FISH".',
        '{"checks": ['
        '{"question": "Is the main subject an elderly man?"}, '
        '{"question": "Is the photo a close-up of the person?"}, '
        '{"question": "Is he wearing a faded blue shirt?"}, '
        '{"question": "Is the sea visible?"}, '
        '{"question": "Does the light look like sunrise?"}, '
        '{"question": "Is there a sign that says FRESH FISH?"}, '
        '{"question": "Does it look like a real photograph?"}]}',
    ),
]

REVISE_SYSTEM = """An image generator was given a prompt, and an inspection found what the picture got wrong. Rewrite the prompt so the next picture gets those points right. State each missed point early, plainly and unambiguously, keep everything else the prompt asks for, and do not add anything the request does not ask for. Answer with only the new prompt, at most 90 words."""

YES_NO = re.compile(r'^(is|are|does|do|did|can|has|have|was|were|will|could|should)\b', re.I)
QUOTED = re.compile(r'["“]([^"”]{1,80})["”]')
NUMBER_WORDS = {
    'zero': 0,
    'no': 0,
    'none': 0,
    'one': 1,
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
PASS = 0.5


# "Are there three people?" asked as yes/no is answered unreliably; counted, it is not.
YES_NO_COUNT = re.compile(r'^(?:is|are) there (?:exactly |only )?(\w+) (.+?)\??$', re.I)


def as_count(question):
    """A yes/no count question turned into a "How many" question and its number, or None."""
    match = YES_NO_COUNT.match(question.strip())
    if not match:
        return None
    word = match.group(1).lower()
    number = int(word) if word.isdigit() else NUMBER_WORDS.get(word)
    if number is None or number < 1:
        return None
    thing = re.split(r'\b(?:in|on|at|inside|visible)\b', match.group(2), maxsplit=1)[0].strip()
    if number == 1 or not thing:
        return None
    return {'question': f'How many {thing} are there?', 'count': number}


def plan(request, session):
    """The checklist for a request: [{'question': ..., 'count': n?}, ...]."""
    answer = assistant.clean(
        session.ask(CHECKS_SYSTEM, CHECKS_EXAMPLES, request, max_new_tokens=500, repetition_penalty=1.0)
    )
    match = re.search(r'\{.*\}', answer, flags=re.S)
    try:
        checks = json.loads(match.group(0))['checks'] if match else []
    except (ValueError, KeyError, TypeError):
        checks = []
    clean_checks, seen = [], set()
    for check in checks if isinstance(checks, list) else []:
        question = str(check.get('question', '')).strip() if isinstance(check, dict) else ''
        if not question or question.lower() in seen:
            continue
        seen.add(question.lower())
        entry = as_count(question) or {'question': question}
        question = entry['question']
        if isinstance(check.get('count'), (int, float)) and question.lower().startswith('how many'):
            entry['count'] = int(check['count'])
        elif 'count' not in entry and (
            not YES_NO.match(question) or re.search(r'\b(say|says|read|reads|written|text)\b', question, re.I)
        ):
            # Not answerable with yes or no, or about lettering (checked by reading it below).
            continue
        clean_checks.append(entry)
    # Written text is read back and compared letter by letter, not asked as yes/no.
    texts = [
        {'question': f'Does the picture show the text "{text}"?', 'text': text}
        for text in dict.fromkeys(QUOTED.findall(request))
    ]
    # An explicit order is checked place by place; the planner's own order questions are too
    # vague ("Are the mugs arranged from left to right?" passes any row).
    order = order_checks(request)
    if order:
        clean_checks = [check for check in clean_checks if not ORDER_WORDS.search(check['question'])]
    fixed = texts + order
    return fixed + clean_checks[: max(12 - len(fixed), 4)]


ORDER = re.compile(r'from (left|right) to (?:right|left)\s*[:,]?\s*(.+?)(?:\.(?:\s|$)|$)', re.I)
ORDER_WORDS = re.compile(r'\b(left to right|right to left|first|second|third|order|arranged)\b', re.I)
ORDINALS = ['1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th']


def order_checks(request):
    """'From left to right: a red mug, a green mug and a blue mug' as one check per place."""
    match = ORDER.search(request)
    if not match:
        return []
    items = [item.strip(' ,;') for item in re.split(r',|;|\band\b|\bthen\b', match.group(2))]
    items = [re.sub(r'^(?:and|then)\s+', '', item) for item in items if item.strip(' ,;')]
    if not 2 <= len(items) <= len(ORDINALS):
        return []
    side = match.group(1).lower()
    items = [
        item
        if re.match(r'(a|an|the|one)\b', item, re.I)
        else f'{"an" if item[:1].lower() in "aeiou" else "a"} {item}'
        for item in items
    ]
    return [
        {'question': f'Counting from the {side}, is the {ORDINALS[index]} item {item}?'}
        for index, item in enumerate(items)
    ]


def same_text(expected, read):
    """True when the read text contains the expected words spelled exactly; only case,
    spacing and punctuation may differ, since misspelled lettering is what this catches."""

    def letters(value):
        return ' '.join(re.sub(r'[^a-z0-9]+', ' ', value.lower()).split())

    expected, read = letters(expected), letters(read)
    return bool(expected) and f' {expected} ' in f' {read} '


def read_number(text):
    text = text.lower()
    digits = re.search(r'\d+', text)
    if digits:
        return int(digits.group(0))
    word = re.search(r'\b(' + '|'.join(NUMBER_WORDS) + r')\b', text)
    return NUMBER_WORDS[word.group(1)] if word else None


def inspect(image, checks, session):
    """Answer every check about the image. Returns (score 0..1, results)."""
    results = []
    for check in checks:
        if 'text' in check:
            reply = session.ask(
                None,
                [],
                'Read all the text written in the picture. Answer with the text only.',
                image,
                max_new_tokens=60,
                repetition_penalty=1.0,
                image_size=1024,
                prefix='',
            )
            ok = same_text(check['text'], reply)
            results.append(dict(check, answer=assistant.clean(reply), score=1.0 if ok else 0.0, ok=ok))
        elif 'count' in check:
            reply = session.ask(
                None,
                [],
                f'{check["question"]} Answer with a number only.',
                image,
                max_new_tokens=8,
                repetition_penalty=1.0,
                image_size=1024,
                prefix='',
            )
            seen = read_number(reply)
            ok = seen == check['count']
            results.append(dict(check, answer=seen, score=1.0 if ok else 0.0, ok=ok))
        else:
            probability = session.yes_probability(check['question'], image)
            results.append(
                dict(check, answer=round(probability, 3), score=probability, ok=probability >= PASS)
            )
    score = sum(result['score'] for result in results) / len(results) if results else 1.0
    return score, results


def describe_failures(results):
    """What the next picture must get right, stated as requirements. (Telling a small model
    what the last picture showed, such as "saw 5", leads it to write those numbers in.)"""
    lines = []
    for result in results:
        if result['ok']:
            continue
        if 'text' in result:
            lines.append(f'The text must read exactly "{result["text"]}", spelled letter by letter.')
        elif 'count' in result:
            thing = re.sub(r'^how many (.+?) (?:are|is) there\??$', r'\1', result['question'], flags=re.I)
            lines.append(f'There must be exactly {result["count"]} {thing}, no more and no fewer.')
        else:
            lines.append(f'The answer to "{result["question"]}" must clearly be yes.')
    return lines


def revise(prompt, request, results, session):
    """A new prompt that stresses what the last picture missed."""
    failures = describe_failures(results)
    if not failures:
        return prompt
    text = (
        f'Original request: {request}\nPrompt used: {prompt}\nWhat the picture got wrong:\n- '
        + '\n- '.join(failures)
    )
    revised = assistant.clean(session.ask(REVISE_SYSTEM, [], text, max_new_tokens=200, prefix=''))
    # A rewrite that loses the request's counts or positions would make things worse.
    if not revised or assistant.lost_specifics(request, revised):
        return prompt
    return revised


POSITION = re.compile(
    r'\b(left|right|center|centre|middle|front|behind|above|below|between|next to|row)\b', re.I
)


def needs_layout(results):
    """True when a missed check is a count or a position, which a layout sketch fixes."""
    return any(
        not result['ok'] and ('count' in result or POSITION.search(result['question'])) for result in results
    )


def report(results, score):
    """A short readable summary of the checks."""
    lines = [f'Match score {score:.0%}']
    for result in results:
        mark = '✓' if result['ok'] else '✗'
        detail = (
            f' (read "{result["answer"]}")'
            if 'text' in result
            else f' (expected {result["count"]}, saw {result["answer"]})'
            if 'count' in result
            else f' ({result["answer"]:.0%} sure)'
        )
        lines.append(f'{mark} {result["question"]}{detail}')
    return '\n'.join(lines)
