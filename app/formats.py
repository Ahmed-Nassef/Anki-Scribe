"""Make the math in a page's text legible to the model.

A PDF text layer does not hand over a formula: it hands over the glyphs in
reading order (`𝐴`, `𝝁`, `²`) with the structure lost. Left alone, a model
sees a line of odd characters and writes a weak card. This module turns those
glyphs back into text a model reads correctly — superscripts and subscripts as
`^{…}`/`_{…}`, Unicode math alphanumerics back into letters, Greek and
operators into LaTeX commands — and decides which lines are formulas at all, so
a sentence that merely mentions σ is not mistaken for an equation.

No dependency: the tables below are plain dicts.
"""

from __future__ import annotations

import re
import unicodedata

# Fonts used to typeset mathematics. A page from LaTeX or Word puts formulas in
# one of these instead of the body font, which is the strongest signal there is.
MATH_FONT = re.compile(
    r"(?:stixmath|cmmi|cmsy|cmex|msam|msbm|latinmodern-math|texgyre(?:math|pagella)|"
    r"eulermath|asana-?math|mathjax|noto\s*sans\s*math|cambria\s*math|"
    r"\bsymbol\b|\bmath\b|\bmtmi\b|\bmtex\b|\beuclid\b|\bxits\b|\bmt-?extra\b)",
    re.IGNORECASE,
)

# Characters that only appear in mathematics.
MATH_CHARS = set("±×÷∓≤≥≠≈≡≢∞∑∏∫∬∂∇√∝∈∉∋⊂⊃⊆⊇∪∩∅∀∃∄∧∨¬⊕⊗⊥∠∥⋅∗∘⇒⇔→←↔↦⇌⇄≪≫≅∼⌈⌉⌊⌋")
GREEK = {
    "α": "\\alpha", "β": "\\beta", "γ": "\\gamma", "δ": "\\delta",
    "ε": "\\epsilon", "ζ": "\\zeta", "η": "\\eta", "θ": "\\theta",
    "ι": "\\iota", "κ": "\\kappa", "λ": "\\lambda", "μ": "\\mu",
    "ν": "\\nu", "ξ": "\\xi", "ο": "o", "π": "\\pi", "ρ": "\\rho",
    "σ": "\\sigma", "ς": "\\varsigma", "τ": "\\tau", "υ": "\\upsilon",
    "φ": "\\phi", "χ": "\\chi", "ψ": "\\psi", "ω": "\\omega",
    "Γ": "\\Gamma", "Δ": "\\Delta", "Θ": "\\Theta", "Λ": "\\Lambda",
    "Ξ": "\\Xi", "Π": "\\Pi", "Σ": "\\Sigma", "Υ": "\\Upsilon",
    "Φ": "\\Phi", "Ψ": "\\Psi", "Ω": "\\Omega", "ϑ": "\\vartheta",
    "ϕ": "\\varphi", "ϵ": "\\epsilon", "ϱ": "\\varrho",
}
OPERATORS = {
    "±": "\\pm", "∓": "\\mp", "×": "\\times", "÷": "\\div", "⋅": "\\cdot",
    "∗": "\\ast", "∘": "\\circ", "≤": "\\leq", "≥": "\\geq", "≠": "\\neq",
    "≈": "\\approx", "≡": "\\equiv", "≢": "\\not\\equiv", "∞": "\\infty",
    "∑": "\\sum", "∏": "\\prod", "∫": "\\int", "∬": "\\iint", "∂": "\\partial",
    "∇": "\\nabla", "√": "\\sqrt", "∝": "\\propto", "∈": "\\in", "∉": "\\notin",
    "∋": "\\ni", "⊂": "\\subset", "⊃": "\\supset", "⊆": "\\subseteq",
    "⊇": "\\supseteq", "∪": "\\cup", "∩": "\\cap", "∅": "\\emptyset",
    "∀": "\\forall", "∃": "\\exists", "∄": "\\nexists", "∧": "\\wedge",
    "∨": "\\vee", "¬": "\\neg", "⊕": "\\oplus", "⊗": "\\otimes",
    "⊥": "\\perp", "∠": "\\angle", "∥": "\\parallel", "≪": "\\ll", "≫": "\\gg",
    "≅": "\\cong", "∼": "\\sim", "→": "\\to", "←": "\\leftarrow",
    "↔": "\\leftrightarrow", "⇒": "\\Rightarrow", "⇔": "\\Leftrightarrow",
    "↦": "\\mapsto", "⇌": "\\rightleftharpoons", "°": "^{\\circ}",
    "′": "'", "″": "''", "⌈": "\\lceil", "⌉": "\\rceil", "⌊": "\\lfloor",
    "⌋": "\\rfloor",
}
SUPERSCRIPT = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6",
    "⁷": "7", "⁸": "8", "⁹": "9", "⁺": "+", "⁻": "-", "⁼": "=", "⁽": "(",
    "⁾": ")", "ⁿ": "n", "ⁱ": "i",
}
SUBSCRIPT = {
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5", "₆": "6",
    "₇": "7", "₈": "8", "₉": "9", "₊": "+", "₋": "-", "₌": "=", "₍": "(",
    "₎": ")", "ₐ": "a", "ₑ": "e", "ₒ": "o", "ₓ": "x", "ₕ": "h", "ₖ": "k",
    "ₗ": "l", "ₘ": "m", "ₙ": "n", "ₚ": "p", "ₛ": "s", "ₜ": "t",
}
FRACTIONS = {"½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4",
             "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5", "⅙": "1/6",
             "⅚": "5/6", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8"}

def _fold_superscripts(text: str) -> str:
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        nonlocal run
        if run:
            out.append("^{" + "".join(run) + "}")
            run = []

    for char in text:
        if char in SUPERSCRIPT:
            run.append(SUPERSCRIPT[char])
            continue
        flush()
        out.append(char)
    flush()
    return "".join(out)


def _fold_subscripts(text: str) -> str:
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        nonlocal run
        if run:
            out.append("_{" + "".join(run) + "}")
            run = []

    for char in text:
        if char in SUBSCRIPT:
            run.append(SUBSCRIPT[char])
            continue
        flush()
        out.append(char)
    flush()
    return "".join(out)


def normalise_math(text: str, *, latex_symbols: bool = False) -> str:
    """Make a text layer's math readable.

    Always: superscripts and subscripts become ``^{…}`` / ``_{…}``, fraction
    glyphs become ``a/b``, and Unicode compatibility (NFKC) turns mathematical
    alphanumerics back into letters — ``𝐴``/``𝝁`` are what a LaTeX PDF's text
    layer gives instead of ``A``/``\\mu``. With ``latex_symbols``: Greek letters
    and operators become LaTeX commands, which is right for a line the page set
    in a math font.
    """
    if not text:
        return text
    text = "".join(FRACTIONS.get(char, char) for char in text)
    text = _fold_superscripts(text)
    text = _fold_subscripts(text)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u2044", "/")
    if latex_symbols or _is_operator_heavy(text):
        text = "".join(GREEK.get(char, OPERATORS.get(char, char)) for char in text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text


def _is_operator_heavy(text: str) -> bool:
    """A short line that is mostly symbols is math wherever it was set."""
    if len(text) > 80:
        return False
    symbols = sum(1 for char in text if char in OPERATORS or char in MATH_CHARS)
    return symbols >= 3 and symbols >= len(text) * 0.08


def math_density(text: str) -> float:
    if not text:
        return 0.0
    hits = sum(
        1
        for char in text
        if char in MATH_CHARS or char in GREEK or char in SUPERSCRIPT or char in SUBSCRIPT
        or 0x1D400 <= ord(char) <= 0x1D7FF
    )
    return hits / len(text)


def looks_like_math(text: str, math_font_ratio: float = 0.0) -> bool:
    """Is this line a formula rather than a sentence quoting a symbol?

    Deliberately strict. Wrapping prose in ``$…$`` makes the model treat a
    sentence as an equation, which is worse than leaving the symbols alone, so
    a line must either be set almost entirely in a math font or contain no
    prose word of four letters or more.
    """
    text = str(text or "").strip()
    if len(text) < 2 or len(text) > 120 or "$" in text:
        return False
    if math_font_ratio >= 0.9:
        return True
    bare = re.sub(r"\\[a-zA-Z]+", " ", text)
    if re.search(r"[a-z]{4,}", bare):
        return False
    density = math_density(text)
    symbols = len(re.findall(r"[=+\u2212\u00d7\u00f7\u00b7<>\u2264\u2265\u2248^]", text))
    if symbols == 0 and density < 0.2:
        return False
    # A formula states a value or a relation; "Make-A-Wish" has hyphens but
    # neither, which is exactly the line this test must not wrap.
    return bool(re.search(r"[0-9]", text)) or "=" in text


def mark_math(text: str, is_math: bool) -> str:
    """Wrap a formula so the model treats it as one."""
    if not is_math:
        return text
    stripped = text.strip()
    if not stripped or "$" in stripped:
        return text
    return f"${stripped}$"
