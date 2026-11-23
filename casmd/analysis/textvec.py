"""
Dependency-light text vectorization + clustering (numpy only).

This replaces the scikit-learn pieces the project used (TfidfVectorizer,
cosine_similarity, AgglomerativeClustering) with small numpy implementations.
Reason: scikit-learn ships compiled C/Cython extensions (.pyd/.so). On managed
/ locked-down analyst machines, Windows Application Control (WDAC/AppLocker)
blocks loading those unsigned DLLs, which crashes `import sklearn`. numpy is
pure enough to be allowed, so we depend only on it here.

Everything is deterministic. For a production upgrade you can still swap the
clustering for HDBSCAN/BERTopic and the vectors for sentence-transformers
(see narratives.semantic_embed) without touching the callers.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

import numpy as np

from ..utils import normalize_text

# Compact English stopword set (enough for labeling; non-English tokens pass
# through untouched, which is what we want for multilingual topics).
_STOP = set("""a an and are as at be but by for from has have i in is it its of on
or that the this to was were will with you your we they he she them his her our
not no do does did can could would should how what when where who why this these
those there here just like get got rt via amp""".split())

_WORD = re.compile(r"[^\W_]+(?:#\w+)?|#\w+|@\w+", re.UNICODE)


def _word_tokens(text, ngram_range=(1, 2)):
    toks = [t for t in _WORD.findall(normalize_text(text)) if t not in _STOP]
    out = list(toks) if ngram_range[0] <= 1 else []
    for n in range(max(2, ngram_range[0]), ngram_range[1] + 1):
        out.extend("_".join(toks[i:i + n]) for i in range(len(toks) - n + 1))
    return out


def _char_tokens(text, ngram_range=(3, 5)):
    """char_wb-style: n-grams within space-padded words (robust to emoji/casing
    edits used to lightly obfuscate near-duplicate posts)."""
    out = []
    for word in normalize_text(text).split():
        w = " " + word + " "
        for n in range(ngram_range[0], ngram_range[1] + 1):
            out.extend(w[i:i + n] for i in range(len(w) - n + 1))
    return out


def tfidf(texts, analyzer="word", ngram_range=None, min_df=2, sublinear=True):
    """Return (X, features): L2-normalized dense TF-IDF matrix + feature list."""
    tok = _word_tokens if analyzer == "word" else _char_tokens
    if ngram_range is None:
        ngram_range = (1, 2) if analyzer == "word" else (3, 5)

    docs = [tok(t, ngram_range) for t in texts]
    df = defaultdict(int)
    for d in docs:
        for term in set(d):
            df[term] += 1
    kept = [t for t, c in sorted(df.items()) if c >= min_df]
    if not kept:  # fall back to df>=1 if min_df wiped everything (tiny corpora)
        kept = sorted(df)
    vocab = {t: i for i, t in enumerate(kept)}
    features = kept

    n = len(texts)
    X = np.zeros((n, len(vocab)), dtype=np.float32)
    for r, d in enumerate(docs):
        counts = defaultdict(int)
        for term in d:
            if term in vocab:
                counts[term] += 1
        for term, c in counts.items():
            tf = (1.0 + math.log(c)) if (sublinear and c > 0) else c
            X[r, vocab[term]] = tf
    idf = np.array([math.log((1.0 + n) / (1.0 + df[f])) + 1.0 for f in features],
                   dtype=np.float32)
    X *= idf
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    X /= norms
    return X, features


def cosine_matrix(X):
    """Rows are L2-normalized, so cosine = dot product."""
    return X @ X.T


def cluster_threshold(X, sim_threshold):
    """Single-linkage clustering via a similarity-threshold graph + union-find.

    Fast (O(n^2) to build similarities, near-linear union-find) and
    dependency-free. Two items join a cluster when their cosine similarity is
    >= sim_threshold. Good enough to group near-duplicate / strongly-related
    posts into narratives; raise the threshold to reduce chaining.
    """
    n = X.shape[0]
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    sim = cosine_matrix(X)
    for i in range(n):
        # only upper triangle
        js = np.where(sim[i, i + 1:] >= sim_threshold)[0]
        for j in js:
            union(i, i + 1 + int(j))

    roots = {}
    labels = np.empty(n, dtype=int)
    for i in range(n):
        r = find(i)
        if r not in roots:
            roots[r] = len(roots)
        labels[i] = roots[r]
    return labels
