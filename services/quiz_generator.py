"""
services/quiz_generator.py — NLP-based MCQ generator.

Unchanged from the original desktop app's QuizGenerator.py: this is
100% rule-based (spaCy NER + POS tagging), needs no AI API call, and
runs cheaply on a Render web dyno. The only change from the original
is dropping the PyInstaller `sys.frozen` / _MEIPASS loading branch,
since we're no longer packaging a .exe — spaCy just loads the model
by name like any normal server-side Python package.
"""

import re
import random
import spacy

try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    # Model not downloaded yet — see requirements.txt / build step, which
    # runs: python -m spacy download en_core_web_sm
    print("[quiz_generator] en_core_web_sm not found — falling back to a blank "
          "pipeline. Run: python -m spacy download en_core_web_sm")
    nlp = spacy.blank("en")

# --- Filler / stop words — never used as an answer ---
_SKIP_WORDS = {
    "thing", "part", "type", "kind", "form", "way", "case", "time",
    "example", "fact", "result", "number", "term", "group", "area",
    "level", "point", "process", "system", "value", "state", "place",
    "people", "person", "man", "woman", "year", "day", "week", "month",
    "use", "used", "include", "including", "make", "made", "know",
    "information", "data", "note", "answer", "question", "quiz",
    "certainly", "loading", "wait", "please", "model", "here", "sure",
    "hello", "goodbye", "yes", "okay", "actually", "basically",
}

# --- UI / AI artifact patterns — sentences matching these are skipped ---
_JUNK_PATTERNS = [
    r"^\[.*\]",
    r"loading.*please wait",
    r"^certainly!?$",
    r"^(yes|no|okay|sure|hello|hi|hey|thanks|thank you)\.?$",
    r"apex\.?$",
    r"generating.*please wait",
    r"extracting text",
    r"summarizing",
    r"^\s*$",
    r"\bai model\b",
    r"please wait",
    r"^error",
    r"welcome to",
]
_JUNK_RE = re.compile("|".join(_JUNK_PATTERNS), re.IGNORECASE)


def _is_quality_sentence(sent):
    text = sent.text.strip()
    if len(text) < 30 or len(list(sent)) < 6:
        return False
    if _JUNK_RE.search(text):
        return False
    if text.endswith("?"):
        return False
    has_content = any(
        tok.pos_ in ("NOUN", "PROPN") and len(tok.text) > 3
        and tok.text.lower() not in _SKIP_WORDS
        for tok in sent
    )
    if not has_content:
        return False
    has_verb = any(tok.pos_ in ("VERB", "AUX") for tok in sent)
    if not has_verb:
        return False
    words = text.split()
    if len(words) <= 3:
        return False
    caps_words = sum(1 for w in words if w.isupper() and len(w) > 1)
    if caps_words > len(words) * 0.5:
        return False
    return True


def _score_keyword(token_or_span):
    text = token_or_span.text
    score = 0
    if hasattr(token_or_span, "label_"):
        label = token_or_span.label_
        if label in ("PERSON", "ORG", "GPE", "PRODUCT", "EVENT", "LAW", "WORK_OF_ART"):
            score += 30
        elif label in ("DATE", "TIME", "PERCENT", "MONEY", "QUANTITY"):
            score += 15
        else:
            score += 20
    else:
        if token_or_span.pos_ == "PROPN":
            score += 20
        elif token_or_span.pos_ == "NOUN":
            score += 10
    score += min(len(text), 20)
    if text.lower() in _SKIP_WORDS:
        score -= 50
    return score


def _collect_all_keywords(doc):
    seen, keywords = set(), []
    for ent in doc.ents:
        key = ent.text.strip().lower()
        if (len(ent.text) > 3 and key not in _SKIP_WORDS
                and not _JUNK_RE.search(key) and key not in seen):
            seen.add(key)
            keywords.append(ent.text.strip())
    for token in doc:
        key = token.text.lower()
        if (token.pos_ in ("NOUN", "PROPN") and len(token.text) > 3
                and key not in _SKIP_WORDS and not _JUNK_RE.search(key)
                and key not in seen):
            seen.add(key)
            keywords.append(token.text)
    return keywords


def _clean_source_text(text):
    lines = text.splitlines()
    clean = [ln for ln in lines if ln.strip() and not _JUNK_RE.search(ln.strip())]
    return "\n".join(clean)


def generate_quiz(text, max_questions=10):
    """
    Generate Multiple Choice Questions from academic text.
    Returns: [{"question": str, "answer": str, "options": [str, str, str, str]}]
    """
    text = _clean_source_text(text)
    if not text.strip():
        return []

    doc = nlp(text)
    all_keywords = _collect_all_keywords(doc)
    quiz_data, used_answers = [], set()

    for sent in doc.sents:
        if len(quiz_data) >= max_questions:
            break
        if not _is_quality_sentence(sent):
            continue

        keyword, best_score = None, -1

        # Strategy 1: best-scoring Named Entity
        for ent in sent.ents:
            if (len(ent.text) > 3 and ent.text.lower().strip() not in _SKIP_WORDS
                    and ent.text.lower().strip() not in used_answers
                    and not _JUNK_RE.search(ent.text)):
                score = _score_keyword(ent)
                if score > best_score:
                    best_score, keyword = score, ent.text.strip()

        # Strategy 2: best-scoring noun token
        if not keyword:
            candidates = []
            for token in sent:
                if (token.pos_ in ("NOUN", "PROPN") and len(token.text) > 3
                        and token.text.lower() not in _SKIP_WORDS
                        and token.text.lower() not in used_answers
                        and not _JUNK_RE.search(token.text)):
                    candidates.append((_score_keyword(token), token.text))
            if candidates:
                candidates.sort(reverse=True)
                keyword = candidates[0][1]

        if not keyword:
            continue
        used_answers.add(keyword.lower().strip())

        distractors_pool = [
            k for k in all_keywords
            if k.lower().strip() != keyword.lower().strip() and k.lower().strip() not in _SKIP_WORDS
        ]
        random.shuffle(distractors_pool)
        distractors = distractors_pool[:3]

        placeholders = ["None of the above", "All of the above", "Cannot be determined"]
        while len(distractors) < 3:
            distractors.append(placeholders[len(distractors)])

        options = [keyword] + distractors
        random.shuffle(options)

        question = re.sub(rf'\b{re.escape(keyword)}\b', "__________", sent.text.strip(), count=1)
        if question == sent.text.strip():
            question = sent.text.strip().replace(keyword, "__________", 1)

        quiz_data.append({"question": question, "answer": keyword, "options": options})

    return quiz_data
