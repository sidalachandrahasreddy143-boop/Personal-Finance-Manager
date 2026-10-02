"""Heuristic auto-categorisation.

Deterministic keyword rules beat a black box here: a wrong guess is easy to
explain and fix, and the whole thing runs in microseconds with no API key.
The rules are intentionally data-driven so they can be extended or replaced by
a learnable classifier later (see ``docs/DESIGN.md``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Rule:
    category: str
    keywords: tuple[str, ...]


# Order matters: the first matching rule wins.
DEFAULT_RULES: tuple[Rule, ...] = (
    Rule("Salary", ("salary", "payroll", "stipend", "wages")),
    Rule("Freelance", ("upwork", "fiverr", "freelance", "consult", "invoice")),
    Rule("Investments", ("dividend", "interest credit", "mutual fund", "sip", "zerodha")),
    Rule("Rent", ("rent", "landlord", "lease", "maintenance charges")),
    Rule(
        "Groceries",
        ("bigbasket", "blinkit", "zepto", "dmart", "grocery", "supermarket", "instamart"),
    ),
    Rule(
        "Transport",
        ("uber", "ola", "rapido", "metro", "fuel", "petrol", "diesel", "toll", "parking"),
    ),
    Rule(
        "Dining",
        ("swiggy", "zomato", "restaurant", "cafe", "coffee", "starbucks", "dominos", "dining"),
    ),
    Rule(
        "Utilities",
        (
            "electricity",
            "water bill",
            "gas bill",
            "broadband",
            "jio",
            "airtel",
            "vi recharge",
            "dth",
        ),
    ),
    Rule(
        "Health",
        (
            "pharmacy",
            "apollo",
            "medplus",
            "hospital",
            "clinic",
            "gym",
            "doctor",
            "insurance premium",
        ),
    ),
    Rule("Shopping", ("amazon", "flipkart", "myntra", "ajio", "meesho", "decathlon", "shopping")),
    Rule(
        "Entertainment",
        ("netflix", "spotify", "prime video", "hotstar", "bookmyshow", "pvr", "game"),
    ),
    Rule(
        "Education",
        ("udemy", "coursera", "tuition", "school fee", "college", "book store", "kindle"),
    ),
)


class Categorizer:
    """Map free-text merchant/description strings onto category names."""

    def __init__(self, rules: tuple[Rule, ...] = DEFAULT_RULES) -> None:
        self.rules = rules

    def suggest(self, *texts: str | None) -> str | None:
        """Return the first category whose keyword appears in the given text."""
        haystack = " ".join(t for t in texts if t).lower()
        if not haystack.strip():
            return None
        for rule in self.rules:
            for keyword in rule.keywords:
                if re.search(rf"\b{re.escape(keyword)}\b", haystack):
                    return rule.category
        return None

    def confidence(self, *texts: str | None) -> float:
        """Rough 0-1 confidence: keyword hit length relative to the input length."""
        hit = self.suggest(*texts)
        if hit is None:
            return 0.0
        haystack = " ".join(t for t in texts if t).lower()
        matched = max(
            (
                len(k)
                for rule in self.rules
                if rule.category == hit
                for k in rule.keywords
                if k in haystack
            ),
            default=1,
        )
        return round(min(0.95, 0.5 + matched / max(len(haystack), 1)), 2)


categorizer = Categorizer()
