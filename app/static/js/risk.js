"use strict";

/* Likely-wrong ranking.

   Cheap, local heuristics — no model call, no embeddings. The score orders
   triage and drives the "N to check" chip, so the cards most likely to be
   wrong are the first ones a student sees. Nothing here is a verdict; it is a
   queue order. */

const RISK_STOPWORDS = new Set([
  "the", "and", "for", "with", "that", "this", "these", "those", "from",
  "which", "what", "when", "where", "does", "did", "are", "was", "were",
  "has", "have", "had", "into", "than", "then", "there", "their", "they",
  "you", "your", "its", "his", "her", "not", "but", "can", "may", "most",
  "more", "less", "one", "two", "how", "why", "who", "via", "per",
]);

const RISK_WEIGHTS = {
  evidence: 5,
  cloze: 3,
  vague: 3,
  duplicate: 2,
  negation: 1,
  notags: 1,
};

let riskCache = { key: "", map: new Map() };

function unwrapCloze(value) {
  return String(value || "").replace(/\{\{c\d+::(.*?)(?:::.*?)?\}\}/g, "$1");
}

function riskTokens(card) {
  const base = card.mode === "cloze" ? unwrapCloze(card.text) : card.question;
  return String(base || "")
    .toLowerCase()
    .replace(/[^a-z0-9\s'-]+/g, " ")
    .split(/\s+/)
    .filter((token) => token.length > 2 && !RISK_STOPWORDS.has(token));
}

function jaccard(left, right) {
  if (!left.size || !right.size) return 0;
  let shared = 0;
  left.forEach((token) => {
    if (right.has(token)) shared += 1;
  });
  return shared / (left.size + right.size - shared);
}

function clozeRiskReason(card) {
  if (card.mode !== "cloze") return null;
  const raw = String(card.text || "");
  const matches = raw.match(/\{\{c\d+::(.*?)(?:::.*?)?\}\}/g) || [];
  if (!matches.length) return null;
  if (matches.length > 3) {
    return { label: "more than three deletions in one card", weight: RISK_WEIGHTS.cloze };
  }
  const longest = matches.reduce((max, entry) => {
    const body = entry.slice(entry.indexOf("::") + 2, entry.lastIndexOf("}}"));
    const words = body.trim().split(/\s+/).length;
    return Math.max(max, words);
  }, 0);
  if (longest > 6) {
    return { label: "a deletion longer than six words", weight: RISK_WEIGHTS.cloze };
  }
  return null;
}

function vagueRiskReason(card) {
  const question = String(card.question || "").trim();
  if (card.mode === "cloze") return null;
  if (/\b(this|the text|the excerpt|the document)\b\s*\?*$/i.test(question)) {
    return { label: "the question points at the text instead of naming the fact", weight: RISK_WEIGHTS.vague };
  }
  if (question.split(/\s+/).filter(Boolean).length < 5) {
    return { label: "a question this short rarely stands alone", weight: RISK_WEIGHTS.vague };
  }
  return null;
}

function negationRiskReason(card) {
  const question = String(card.question || card.text || "").toLowerCase();
  const answer = String(card.answer || card.text || "").toLowerCase();
  const hasNegation = /\b(not|no|never|cannot|without|except)\b|n't\b/.test(answer);
  const questionHasIt = /\b(not|no|never|cannot|without|except)\b|n't\b/.test(question);
  if (hasNegation && !questionHasIt) {
    return { label: "the answer negates something the question doesn't", weight: RISK_WEIGHTS.negation };
  }
  return null;
}

/* Cards with near-identical fronts are the ones that interfere with each
   other. Comparing every pair is O(n²), so each card is indexed under its two
   rarest tokens: a near-duplicate differs in one word, so at least one shared
   token almost always survives. Buckets that are too generic to be evidence,
   and a hard comparison budget, keep a 2,000-card batch cheap. */
const MAX_DUPLICATE_BUCKET = 40;
const MAX_DUPLICATE_COMPARISONS = 20000;

function duplicateIndex(cards, tokens) {
  const frequency = new Map();
  tokens.forEach((set) => {
    set.forEach((token) => frequency.set(token, (frequency.get(token) || 0) + 1));
  });

  const buckets = new Map();
  const addToBucket = (token, uid) => {
    if (!buckets.has(token)) buckets.set(token, []);
    buckets.get(token).push(uid);
  };
  cards.forEach((card) => {
    const set = tokens.get(card.uid);
    const ranked = [];
    set.forEach((token) => ranked.push({ token, count: frequency.get(token) || 0 }));
    ranked.sort((a, b) => a.count - b.count || (a.token < b.token ? -1 : 1));
    ranked.slice(0, 2).forEach((entry) => addToBucket(entry.token, card.uid));
  });

  const duplicateOf = new Map();
  const seen = new Set();
  let comparisons = 0;
  buckets.forEach((uids) => {
    if (uids.length < 2 || uids.length > MAX_DUPLICATE_BUCKET) return;
    for (let index = 0; index < uids.length; index += 1) {
      for (let other = index + 1; other < uids.length; other += 1) {
        if (comparisons >= MAX_DUPLICATE_COMPARISONS) return;
        const left = uids[index];
        const right = uids[other];
        if (left === right) continue;
        const pair = left < right ? `${left}|${right}` : `${right}|${left}`;
        if (seen.has(pair)) continue;
        seen.add(pair);
        comparisons += 1;
        if (jaccard(tokens.get(left), tokens.get(right)) < 0.8) continue;
        if (!duplicateOf.has(left)) duplicateOf.set(left, right);
        if (!duplicateOf.has(right)) duplicateOf.set(right, left);
      }
    }
  });
  return duplicateOf;
}

function riskKeyFor(cards) {
  return cards
    .map((card) => `${card.uid}:${card.verified === false ? 0 : 1}:${(card.question || card.text || "").length}`)
    .join("|");
}

function computeRisk() {
  const cards = state.cards.filter((card) => card && card.uid);
  const key = riskKeyFor(cards);
  if (riskCache.key === key) return riskCache.map;

  const tokens = new Map();
  cards.forEach((card) => tokens.set(card.uid, new Set(riskTokens(card))));
  const duplicateOf = duplicateIndex(cards, tokens);

  const result = new Map();
  cards.forEach((card) => {
    const reasons = [];
    if (card.verified === false) {
      reasons.push({ label: "the quote is not in the source", weight: RISK_WEIGHTS.evidence });
    }
    [clozeRiskReason(card), vagueRiskReason(card), negationRiskReason(card)].forEach((reason) => {
      if (reason) reasons.push(reason);
    });
    if (duplicateOf.has(card.uid)) {
      reasons.push({ label: "overlaps another card in this batch", weight: RISK_WEIGHTS.duplicate });
    }
    if (!Array.isArray(card.tags) || !card.tags.length) {
      reasons.push({ label: "no tags", weight: RISK_WEIGHTS.notags });
    }
    const score = reasons.reduce((total, reason) => total + reason.weight, 0);
    result.set(card.uid, { score, reasons, duplicateOf: duplicateOf.get(card.uid) || null });
  });

  riskCache = { key, map: result };
  return result;
}

function riskFor(uid) {
  const entry = computeRisk().get(uid);
  return entry || { score: 0, reasons: [], duplicateOf: null };
}

function riskyCards() {
  const risk = computeRisk();
  return state.cards
    .filter((card) => card && card.uid && (risk.get(card.uid) || {}).score > 0)
    .sort((a, b) => (risk.get(b.uid) || {}).score - (risk.get(a.uid) || {}).score);
}

function riskSummary(card) {
  const entry = riskFor(card.uid);
  if (!entry.score) return "";
  return entry.reasons.map((reason) => reason.label).join(" \u00b7 ");
}
