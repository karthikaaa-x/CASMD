"""
Lexicon-based sentiment (pure Python — no model, no compiled deps).

Deliberately simple and transparent: a positive/negative word list with a few
negation and intensifier rules. It is NOT a research-grade classifier — it gives
each narrative a readable "mood" (alarmed / negative / neutral / positive) so a
non-technical reader can see the tone at a glance. Swap for a transformer
classifier in production if you need accuracy.
"""

from __future__ import annotations

import re

_POS = set("""good great safe secure legit genuine trust trusted reliable happy
support confirmed verified official calm resolved fixed recovered profit gain
win winner congratulations thanks helpful love best amazing excellent""".split())

_NEG = set("""scam fraud fake hoax lie lies stolen steal theft hack hacked breach
collapse insolvent bankrupt crash panic fear afraid scared urgent warning danger
risk lose loss gone cheat cheated ponzi rug fraudulent suspicious bot bots
withdraw emergency crisis angry hate worried worry terrible awful bad fail failed
failing exposed victim scammed phishing malware""".split())

_NEG_WORDS = {"not", "no", "never", "n't", "cannot", "cant", "without"}
_WORD = re.compile(r"[a-z']+")


def score(text: str) -> float:
    """Return a sentiment score in roughly [-1, 1]."""
    toks = _WORD.findall((text or "").lower())
    if not toks:
        return 0.0
    s = 0
    for i, w in enumerate(toks):
        val = 1 if w in _POS else (-1 if w in _NEG else 0)
        if val and i > 0 and toks[i - 1] in _NEG_WORDS:
            val = -val
        s += val
    return max(-1.0, min(1.0, s / (len(toks) ** 0.5)))


def label(avg: float) -> str:
    if avg <= -0.5:
        return "alarmed / hostile"
    if avg < -0.1:
        return "negative"
    if avg < 0.1:
        return "neutral / mixed"
    if avg < 0.5:
        return "positive"
    return "very positive"
