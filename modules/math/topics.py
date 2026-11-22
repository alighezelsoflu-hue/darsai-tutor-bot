"""Which practice generator belongs to each (level, topic).

Pure Python with no Telegram imports, so the button interface and the old commands can both use it.
"""

from types import ModuleType
from typing import Dict, List

from .high_school import algebra as high_algebra
from .high_school import quadratics as high_quadratics
from .middle_school import equations as middle_equations
from .pre_college import precalculus as pre_calculus
from .shared import normalize_topic
from .university import calculus as uni_calculus

LEVEL_ORDER = ("middle_school", "high_school", "pre_college", "university")

# The order here is the order of the topic buttons.
TOPIC_MODULES: Dict[tuple, ModuleType] = {
    ("middle_school", "linear_equations"): middle_equations,
    ("high_school", "algebra"): high_algebra,
    ("high_school", "quadratics"): high_quadratics,
    ("pre_college", "precalculus"): pre_calculus,
    ("university", "calculus"): uni_calculus,
}

TOPIC_ALIASES = {
    "equations": "linear_equations",
}

DEFAULT_TOPIC = {
    "middle_school": "linear_equations",
    "high_school": "algebra",
    "pre_college": "precalculus",
    "university": "calculus",
}

# Topic names are unique across levels, because AI memory and button callback data use the topic alone.
TOPIC_LEVEL: Dict[str, str] = {topic: level for level, topic in TOPIC_MODULES}
if len(TOPIC_LEVEL) != len(TOPIC_MODULES):
    raise RuntimeError("Two levels use the same topic name. Topic names must be unique.")

# Every AI memory topic the math tutor writes to ("math" is used by /solve tutor).
MATH_MEMORY_TOPICS = ("math",) + tuple(sorted(TOPIC_LEVEL))


def canonical_topic(text: str) -> str:
    topic = normalize_topic(text)
    return TOPIC_ALIASES.get(topic, topic)


def topics_for_level(level: str) -> List[str]:
    return [topic for topic_level, topic in TOPIC_MODULES if topic_level == level]


def get_topic_module(level: str, topic: str) -> ModuleType:
    """The generator for (level, topic), or the level's default topic when there is none."""
    return TOPIC_MODULES.get((level, canonical_topic(topic))) or TOPIC_MODULES[(level, DEFAULT_TOPIC[level])]
