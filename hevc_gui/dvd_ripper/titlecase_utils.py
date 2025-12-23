#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Title-case per IT/EN, con gestione di parole “piccole”, apostrofi e trattini.
"""

from __future__ import annotations
import re

SMALLS_IT = {
    "a","ad","al","allo","ai","agli","alla","alle",
    "da","dal","dallo","dai","dagli","dalla","dalle",
    "di","del","dello","dei","degli","della","delle",
    "in","nel","nello","nei","negli","nella","nelle",
    "su","sul","sullo","sui","sugli","sulla","sulle",
    "con","per","tra","fra","e","ed","o","od","ma","né","che","se",
    "il","lo","la","i","gli","le","un","uno","una",
}
APOS_ROOTS_IT = {"l", "dell", "all", "dall", "nell", "sull", "coll"}

SMALLS_EN = {
    "a","an","the",
    "and","but","or","nor","so","yet",
    "as","at","by","for","in","of","on","per","to","via","vs","vs.",
    "from","over","into","onto","upon","off",
}
APOS_ROOTS_EN = {"o"}  # O'Connor

def sanitize_label(s: str) -> str:
    return re.sub(r"[_\s]+", " ", (s or "").strip())

def _is_acronym(tok: str) -> bool:
    return len(tok) >= 2 and tok.upper() == tok and any(c.isalpha() for c in tok)

def _cap_word(w: str) -> str:
    if not w:
        return w
    if _is_acronym(w):
        return w
    return w[0].upper() + w[1:].lower()

def _cap_with_apostrophe(tok: str, is_first: bool, is_last: bool, lang: str) -> str:
    m = re.match(r"^([A-Za-zÀ-ÖØ-öø-ÿ]+)([’'])(.+)$", tok)
    if not m:
        return _cap_word(tok)
    head, apo, tail = m.groups()
    head_low = head.lower()
    if lang == "it":
        if head_low in APOS_ROOTS_IT:
            head_fmt = _cap_word(head_low) if (is_first or is_last) else head_low
            return f"{head_fmt}{apo}{_cap_word(tail)}"
        return f"{_cap_word(head)}{apo}{_cap_word(tail)}"
    if head_low in APOS_ROOTS_EN or len(head) == 1:
        return f"{_cap_word(head)}{apo}{_cap_word(tail)}"
    return f"{_cap_word(head)}{apo}{_cap_word(tail)}"

def _title_case_tokens(tokens: list[str], lang: str) -> str:
    smalls = SMALLS_IT if lang == "it" else SMALLS_EN
    n = len(tokens)
    out: list[str] = []
    for i, tok in enumerate(tokens):
        if not tok:
            out.append(tok); continue
        is_first = (i == 0)
        is_last = (i == n - 1)

        pre = ""; post = ""
        m_pre = re.match(r"^([\"“‘\(\[\{]+)(.+)$", tok)
        if m_pre:
            pre, tok = m_pre.group(1), m_pre.group(2)
        m_post = re.match(r"^(.+?)([\"”’\)\]\}\.\,\!\?\:;]+)$", tok)
        if m_post:
            tok, post = m_post.group(1), m_post.group(2)

        if "-" in tok:
            parts = tok.split("-")
            cap_parts = []
            for p in parts:
                if not p: cap_parts.append(p); continue
                if re.search(r"[’']", p):
                    cap_parts.append(_cap_with_apostrophe(p, True, True, lang))
                else:
                    cap_parts.append(_cap_word(p))
            out_tok = "-".join(cap_parts)
            out.append(f"{pre}{out_tok}{post}")
            continue

        if re.search(r"[’']", tok):
            out_tok = _cap_with_apostrophe(tok, is_first, is_last, lang)
            out.append(f"{pre}{out_tok}{post}")
            continue

        tok_low = tok.lower()
        if tok_low in smalls and not (is_first or is_last):
            out.append(f"{pre}{tok_low}{post}")
        else:
            out.append(f"{pre}{_cap_word(tok)}{post}")
    return " ".join(out)

def title_case(text: str, lang: str = "it") -> str:
    s = sanitize_label(text)
    if not s:
        return s
    tokens = s.split(" ")
    return _title_case_tokens(tokens, lang=lang)
