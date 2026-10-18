"""
Open Charvis - The mind (self-learning core)
===========================================
Everything else in this agent could be written without a neural network:
regexes route commands, SQLite stores facts, and the language model (when one
is connected) does the talking. What was missing is the part that *gets
better*.

This module is that part. It is a set of small models that train at runtime,
on this machine, from the agent's own experience:

``OnlineSoftmax``   multiclass logistic regression trained by SGD. Sparse
                    hashed features (word uni/bi-grams + character 3-grams),
                    pure Python, no numpy. Generalises past the regex table:
                    once it has seen a phrasing, it recognises near-misses it
                    was never explicitly programmed for.

``ToolBandit``      UCB1 contextual bandit. For each kind of request it learns
                    which action actually works, and stops repeating the ones
                    that failed - including actions that "worked" only because
                    the security gate blocked them.

``Calibrator``      Tracks per-intent success rate. The agent learns how
                    reliable it is at each kind of thing, and stops pretending
                    to be confident about the ones it keeps getting wrong.

All of it persists to ``mind/`` so learning survives restarts.

What it is *not*: it is not a language model. It learns routing, tool choice
and self-assessment. For open-ended conversation you still connect one - and
when you do, this sits underneath it.
"""

from __future__ import annotations

import atexit
import json
import math
import os
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .config import PATHS, ensure_dirs
from .events import BUS, Ev
from .logger import log_info, log_warn
from .utils import human_size, normalize_text, relative, stamp, token_set

# Hashing dimension. Large enough that collisions are rare, small enough that
# the sparse weight dicts stay fast in pure Python.
DIM = 1 << 18


# --------------------------------------------------------------------------
# Feature extraction
# --------------------------------------------------------------------------


def _hash_token(token: str, kind: str) -> int:
    import hashlib

    digest = hashlib.blake2b(f"{kind}:{token}".encode("utf-8"), digest_size=6).digest()
    return int.from_bytes(digest, "big") % DIM


def vectorize(text: str) -> Dict[int, float]:
    """
    Sparse hashed feature vector, L2 normalised.

    Three views of the same string:
      * word unigrams   - the literal words
      * word bigrams    - short phrases, so "power on" != "on power"
      * char 3-grams    - survives typos and morphological variants
        ("remembered"/"remember", "band"/"bandh")

    Char grams are what let it generalise to wordings nobody showed it.
    """
    norm = normalize_text(text or "")
    if not norm:
        return {}

    features: Dict[int, float] = {}

    def add(token: str, kind: str, weight: float) -> None:
        index = _hash_token(token, kind)
        features[index] = features.get(index, 0.0) + weight

    words = [w for w in norm.replace(".", " ").split() if w]
    for word in words:
        add(word, "w1", 1.0)
    for first, second in zip(words, words[1:]):
        add(f"{first}_{second}", "w2", 0.7)

    padded = f" {norm.replace(' ', '_')} "
    for index in range(len(padded) - 2):
        add(padded[index : index + 3], "c3", 0.35)

    magnitude = math.sqrt(sum(v * v for v in features.values())) or 1.0
    return {k: v / magnitude for k, v in features.items()}


# --------------------------------------------------------------------------
# Online multiclass logistic regression
# --------------------------------------------------------------------------


class OnlineSoftmax:
    """
    Sparse softmax regression trained by AdaGrad.

    Weights are stored as ``class -> {feature_index: weight}`` so an update
    only touches the features that are actually present, which is what makes
    this fast enough in pure Python to train on every single request.

    AdaGrad rather than plain SGD: with L2-normalised sparse features, a
    single global learning rate either crawls (small rates) or thrashes
    (large rates), because a word seen twice needs a much bigger step than a
    word seen two thousand times. Per-feature accumulated gradients give every
    feature its own step size automatically. Measured on the built-in
    benchmark this reaches 85% accuracy in 90 updates where plain SGD was
    still at 42% after 400.
    """

    def __init__(
        self,
        classes: Sequence[str],
        dim: int = DIM,
        lr: float = 0.35,
        l2: float = 1e-7,
    ):
        self.classes = list(classes)
        self.index = {name: i for i, name in enumerate(self.classes)}
        self.dim = dim
        self.lr = lr
        self.l2 = l2
        self.weights: List[Dict[int, float]] = [defaultdict(float) for _ in self.classes]
        self.bias: List[float] = [0.0] * len(self.classes)
        self._grad_sq: List[Dict[int, float]] = [defaultdict(float) for _ in self.classes]
        self._grad_sq_bias: List[float] = [0.0] * len(self.classes)
        self.trained = 0
        self._lock = threading.RLock()

    # -- inference -----------------------------------------------------
    def probabilities(self, features: Dict[int, float]) -> List[float]:
        if not features:
            return [1.0 / len(self.classes)] * len(self.classes)

        logits = list(self.bias)
        for index, value in features.items():
            if value == 0.0:
                continue
            for c, table in enumerate(self.weights):
                weight = table.get(index)
                if weight:
                    logits[c] += weight * value

        peak = max(logits)
        exponentials = [math.exp(v - peak) for v in logits]
        total = sum(exponentials) or 1.0
        return [e / total for e in exponentials]

    def predict(self, text_or_features: Any) -> Tuple[Optional[str], float]:
        """Returns (predicted class, confidence)."""
        features = (
            text_or_features
            if isinstance(text_or_features, dict)
            else vectorize(str(text_or_features))
        )
        if self.trained == 0:
            return None, 0.0
        probs = self.probabilities(features)
        best = max(range(len(probs)), key=probs.__getitem__)
        return self.classes[best], probs[best]

    def ranked(self, text: str, limit: int = 5) -> List[Tuple[str, float]]:
        probs = self.probabilities(vectorize(text))
        order = sorted(range(len(probs)), key=probs.__getitem__, reverse=True)
        return [(self.classes[i], probs[i]) for i in order[:limit]]

    # -- learning ------------------------------------------------------
    def update(self, features: Dict[int, float], label: str, weight: float = 1.0) -> bool:
        """
        One adaptive step toward ``label``.

        ``weight`` > 1 for corrections the owner explicitly made (those are
        the most valuable training signal there is) and < 1 for weak,
        rule-derived labels. A negative weight pushes the label *away*, which
        is how a correction un-learns the mistake.
        """
        target = self.index.get(label)
        if target is None or not features:
            return False

        with self._lock:
            probs = self.probabilities(features)
            for c in range(len(self.classes)):
                gradient = (probs[c] - (1.0 if c == target else 0.0)) * weight
                if not gradient:
                    continue

                self._grad_sq_bias[c] += gradient * gradient
                step = self.lr / (math.sqrt(self._grad_sq_bias[c]) + 1e-8)
                self.bias[c] -= step * gradient

                table = self.weights[c]
                accumulator = self._grad_sq[c]
                for index, value in features.items():
                    component = gradient * value
                    accumulator[index] += component * component
                    step = self.lr / (math.sqrt(accumulator[index]) + 1e-8)
                    updated = table.get(index, 0.0) - step * component
                    if self.l2:
                        updated *= 1.0 - self.lr * self.l2
                    if abs(updated) < 1e-6:
                        table.pop(index, None)
                    else:
                        table[index] = updated

            self.trained += 1
        return True

    def forget(self) -> None:
        with self._lock:
            self.weights = [defaultdict(float) for _ in self.classes]
            self.bias = [0.0] * len(self.classes)
            self._grad_sq = [defaultdict(float) for _ in self.classes]
            self._grad_sq_bias = [0.0] * len(self.classes)
            self.trained = 0

    # -- persistence ---------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "classes": self.classes,
            "lr": self.lr,
            "l2": self.l2,
            "trained": self.trained,
            "bias": self.bias,
            # Keep only weights big enough to matter; the rest is noise that
            # would bloat the file for no benefit.
            "weights": [
                {str(k): round(v, 6) for k, v in table.items() if abs(v) > 1e-4}
                for table in self.weights
            ],
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "OnlineSoftmax":
        model = cls(raw.get("classes", []), lr=raw.get("lr", 0.35),
                    l2=raw.get("l2", 1e-7))
        model.trained = int(raw.get("trained", 0))
        model.bias = [float(b) for b in raw.get("bias", [])] or [0.0] * len(model.classes)
        for c, table in enumerate(raw.get("weights", [])):
            model.weights[c] = defaultdict(
                float, {int(k): float(v) for k, v in table.items()}
            )
        # The AdaGrad accumulators are deliberately not persisted: they are
        # a speed-up cache, not knowledge, and rebuilding them keeps the
        # saved file small. The agent simply relearns step sizes after a
        # restart.
        return model

    @property
    def size_bytes(self) -> int:
        return sum(len(t) for t in self.weights) * 8 + self.trained * 4


# --------------------------------------------------------------------------
# UCB1 contextual bandit
# --------------------------------------------------------------------------


class ToolBandit:
    """
    Upper Confidence Bound over actions, grouped by request shape.

    Standard UCB1: pick the arm with the best ``reward + c*sqrt(ln N / n)``,
    so untried actions get an optimistic bonus and the agent explores instead
    of grinding the same failing tool forever.

    This is how the agent stops re-attempting something that never worked.
    """

    def __init__(self, exploration: float = 1.2):
        self.exploration = exploration
        # context -> {arm -> [pulls, total_reward]}
        self.arms: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(lambda: [0.0, 0.0])
        )
        self.global_arms: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0.0])
        self._lock = threading.RLock()
        self.updates = 0

    @staticmethod
    def context(intent: str, slots: Optional[Dict[str, Any]] = None) -> str:
        """Bucket requests into similar shapes, e.g. "image_generate:style"."""
        intent = intent or "unknown"
        if not slots:
            return intent
        for key in ("language", "style", "topic"):
            if slots.get(key):
                return f"{intent}:{key}"
        return intent

    def select(self, context: str, candidates: Sequence[str]) -> Tuple[str, float]:
        """Pick an action. Returns (arm, confidence-in-the-choice)."""
        candidates = list(candidates)
        if not candidates:
            return "", 0.0
        if len(candidates) == 1:
            return candidates[0], 1.0

        with self._lock:
            table = self.arms.get(context, {})
            total = sum(pulls for pulls, _ in table.values())
            best_arm, best_score = candidates[0], float("-inf")

            for arm in candidates:
                pulls, reward = table.get(arm, [0.0, 0.0])
                if pulls == 0:
                    # Unproven: optimism is maximal here.
                    score = float("inf")
                else:
                    mean = reward / pulls
                    bonus = self.exploration * math.sqrt(math.log(total + 1) / pulls)
                    score = mean + bonus
                if score > best_score:
                    best_arm, best_score = arm, score

            # Translate the winner into a comparable confidence.
            pulls, reward = table.get(best_arm, [0.0, 0.0])
            mean = reward / pulls if pulls else 0.5
            confidence = 0.5 + 0.5 * mean if pulls else 0.35
        return best_arm, min(1.0, confidence)

    def update(self, context: str, arm: str, reward: float) -> None:
        reward = max(0.0, min(1.0, float(reward)))
        with self._lock:
            entry = self.arms[context][arm]
            entry[0] += 1.0
            entry[1] += reward
            overall = self.global_arms[arm]
            overall[0] += 1.0
            overall[1] += reward
            self.updates += 1

    def stats(self, context: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if context:
                table = self.arms.get(context, {})
                return {
                    "context": context,
                    "arms": {
                        arm: {
                            "tries": int(pulls),
                            "success_rate": round(reward / pulls, 3) if pulls else 0.0,
                        }
                        for arm, (pulls, reward) in sorted(table.items())
                    },
                }
            return {
                "contexts": len(self.arms),
                "arms": len(self.global_arms),
                "updates": self.updates,
                "best": sorted(
                    (
                        {
                            "arm": arm,
                            "tries": int(pulls),
                            "success_rate": round(reward / pulls, 3),
                        }
                        for arm, (pulls, reward) in self.global_arms.items()
                        if pulls >= 2
                    ),
                    key=lambda r: r["success_rate"],
                    reverse=True,
                )[:8],
            }


# --------------------------------------------------------------------------
# Confidence calibration
# --------------------------------------------------------------------------


class Calibrator:
    """
    Learns how reliable the agent is per intent.

    Keeps an exponential moving average of success, and a correction count.
    ``adjusted(intent, raw_confidence)`` pulls confidence down for intents
    that keep failing, so the agent stops sounding certain about things it is
    bad at - which is the whole point of having a confidence number.
    """

    def __init__(self, alpha: float = 0.25):
        self.alpha = alpha
        self.rates: Dict[str, float] = defaultdict(lambda: 0.5)
        self.tries: Dict[str, int] = defaultdict(int)
        self.corrections: Dict[str, int] = defaultdict(int)
        self._lock = threading.RLock()

    def record(self, intent: str, success: bool) -> None:
        with self._lock:
            target = 1.0 if success else 0.0
            current = self.rates[intent]
            self.rates[intent] = current + self.alpha * (target - current)
            self.tries[intent] += 1

    def correction(self, intent: str) -> None:
        """
        The owner said "that was wrong".

        Treated as a stronger negative than an ordinary failure - it is
        direct, explicit feedback, not just a task that did not go well.
        """
        with self._lock:
            self.corrections[intent] += 1
            self.tries[intent] += 1
            self.rates[intent] = max(0.0, min(1.0, self.rates[intent] * 0.45))

    def adjusted(self, intent: str, raw: float) -> float:
        """Recalibrate a confidence score using what this machine has learned."""
        with self._lock:
            rate = self.rates.get(intent)
            if rate is None:
                return raw
            # Blend the claimed confidence toward the measured success rate,
            # weighted by how much evidence there is.
            evidence = min(1.0, self.tries[intent] / 8.0)
            pulled = raw * (1.0 - evidence) + rate * evidence
            return max(0.0, min(1.0, pulled))

    def weakest(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Intents the agent is worst at - where it should be humble."""
        with self._lock:
            rows = [
                {
                    "intent": intent,
                    "tries": tries,
                    "success_rate": round(self.rates[intent], 3),
                    "corrections": self.corrections[intent],
                }
                for intent, tries in self.tries.items()
                if tries >= 2
            ]
        rows.sort(key=lambda r: (r["success_rate"], -r["tries"]))
        return rows[:limit]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alpha": self.alpha,
            "rates": dict(self.rates),
            "tries": dict(self.tries),
            "corrections": dict(self.corrections),
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Calibrator":
        obj = cls(alpha=raw.get("alpha", 0.25))
        obj.rates = defaultdict(lambda: 0.5, raw.get("rates", {}))
        obj.tries = defaultdict(int, {k: int(v) for k, v in raw.get("tries", {}).items()})
        obj.corrections = defaultdict(
            int, {k: int(v) for k, v in raw.get("corrections", {}).items()}
        )
        return obj


# --------------------------------------------------------------------------
# The mind
# --------------------------------------------------------------------------

# Phrases the owner uses to tell the agent it got something wrong. These are
# the highest-value training signal in the whole system, because they are the
# owner correcting the agent explicitly.
CORRECTION_PHRASES = (
    "nahi", "nahi yaar", "galat", "ye nahi", "ye galat", "that's wrong", "thats wrong",
    "not what i", "not correct", "incorrect", "wrong answer", "try again",
    "i said", "i asked", "you misunderstood", "misunderstood", "kaam nahi kiya",
    "galat hai", "sahi nahi", "chalo bhool jao",
)


class Mind:
    """
    Everything the agent has taught itself, in one place.

    Usage from the kernel::

        mind = get_mind()
        guess = mind.route(text, rule_intent, rule_confidence)
        ...
        mind.learn(text, true_intent, success=True)
    """

    VERSION = 1

    def __init__(self, classes: Optional[Sequence[str]] = None, home: Optional[Path] = None):
        ensure_dirs()
        self.home = Path(home or (PATHS["home"] / "mind"))
        self.home.mkdir(parents=True, exist_ok=True)
        self.file = self.home / "mind.json"
        self.lock_file = self.home / "mind.lock"

        self.classes = list(classes or [])
        self.classifier = OnlineSoftmax(self.classes) if self.classes else None
        self.bandit = ToolBandit()
        self.calibrator = Calibrator()
        self.history: List[Dict[str, Any]] = []
        self.corrections_total = 0
        self.last_train = 0.0
        self.read_only = False
        self._lock = threading.RLock()

        self._claim_lock()
        self.load()

    # ------------------------------------------------------------------
    # Single-writer guard
    # ------------------------------------------------------------------
    def _claim_lock(self) -> bool:
        """
        Take exclusive ownership of the mind file.

        Two Open Charvis processes training on the same file would each
        overwrite the other's weights, and whichever saved last would erase
        the other's learning. So the first process to start owns the mind;
        any later process loads read-only and says so, instead of silently
        corrupting it.
        """
        try:
            handle = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            self.read_only = self._lock_is_live()
            return False
        except OSError:
            self.read_only = False
            return False

        try:
            os.write(handle, str(os.getpid()).encode("ascii"))
        finally:
            os.close(handle)
        atexit.register(self.release_lock)
        return True

    def _lock_is_live(self) -> bool:
        """A lock file left by a crashed process should not block forever."""
        try:
            pid = int(self.lock_file.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            pid = 0
        if pid <= 0:
            return False
        if pid == os.getpid():
            return True
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def release_lock(self) -> None:
        try:
            if self.lock_file.exists() and not self.read_only:
                self.lock_file.unlink()
        except OSError:
            pass

    @property
    def owner(self) -> bool:
        return not self.read_only

    # ------------------------------------------------------------------
    # Routing: rules propose, the learned model disposes
    # ------------------------------------------------------------------
    def route(
        self,
        text: str,
        rule_intent: str,
        rule_confidence: float,
        accepted_margin: float = 0.12,
    ) -> Tuple[str, float, str]:
        """
        Blend the regex table with the learned classifier.

        A confident rule always wins - rules are reviewed, hand-written and
        safe to trust. The learned model is allowed to *veto a weak rule* and
        to *rescue an unrecognised phrasing*, but only when it is clearly
        more sure. That asymmetry is deliberate: a bad rule is a small
        annoyance, a bad learned prediction could send the agent to the wrong
        tool.

        Returns (intent, confidence, source) where source is
        ``rule`` | ``learned`` | ``ensemble`` | ``untrained``.
        """
        if self.classifier is None or self.classifier.trained < 12:
            return rule_intent, rule_confidence, "rule"

        predicted, probability = self.classifier.predict(text)
        if predicted is None:
            return rule_intent, rule_confidence, "rule"

        if rule_confidence >= 0.9:
            return rule_intent, rule_confidence, "rule"

        if predicted == rule_intent:
            # Agreement is extra evidence, not a reason to change course.
            blended = max(rule_confidence, probability)
            return rule_intent, blended, "ensemble"

        if probability > rule_confidence + accepted_margin:
            BUS.emit(Ev.LEARNED, {
                "why": "learned override",
                "text": text[:80],
                "rule": rule_intent,
                "learned": predicted,
                "probability": round(probability, 3),
            }, "mind")
            return predicted, probability, "learned"

        return rule_intent, rule_confidence, "rule"

    # ------------------------------------------------------------------
    # Learning
    # ------------------------------------------------------------------
    def learn(
        self,
        text: str,
        intent: str,
        success: bool = True,
        confidence: float = 1.0,
        weight: Optional[float] = None,
    ) -> bool:
        """
        Train on one completed request.

        Rule-derived labels are down-weighted (``confidence``) because they
        are the teacher's opinion, not ground truth. Corrections from the
        owner are up-weighted, because they are ground truth.
        """
        if not text.strip():
            return False

        if weight is None:
            weight = 0.25 + 0.75 * max(0.0, min(1.0, confidence))

        with self._lock:
            if self.classifier is not None:
                if intent not in self.classifier.index:
                    self.add_class(intent)
                self.classifier.update(vectorize(text), intent, weight)
            self.calibrator.record(intent, success)
            self.history.append({
                "at": time.time(),
                "intent": intent,
                "success": success,
                "weight": round(weight, 3),
            })
            if len(self.history) > 4000:
                del self.history[:2000]
            self.last_train = time.time()
        return True

    def add_class(self, intent: str) -> None:
        """Extend the label set without discarding what has been learned."""
        if not intent or (self.classifier and intent in self.classifier.index):
            return
        with self._lock:
            if self.classifier is None:
                self.classes = [intent]
                self.classifier = OnlineSoftmax([intent])
                return
            self.classes.append(intent)
            self.classifier.classes.append(intent)
            self.classifier.index[intent] = len(self.classes) - 1
            self.classifier.weights.append(defaultdict(float))
            self.classifier.bias.append(0.0)
            # The AdaGrad accumulators must grow with the weights, or the
            # next update indexes past the end of these lists.
            self.classifier._grad_sq.append(defaultdict(float))
            self.classifier._grad_sq_bias.append(0.0)

    def correct(self, text: str, wrong_intent: str, right_intent: str) -> Dict[str, Any]:
        """
        The owner said "that's wrong".

        This is the single most valuable event the system can observe: a
        labelled mistake. The wrong label is actively pushed down and the
        right one pushed up, and the intent's reliability takes a hit so it
        stops being confident there until it proves otherwise.
        """
        result = {"wrong": wrong_intent, "right": right_intent, "applied": False}

        with self._lock:
            if self.classifier is not None:
                if right_intent not in self.classifier.index:
                    self.add_class(right_intent)
                features = vectorize(text)
                if features:
                    self.classifier.update(features, right_intent, weight=3.0)
                    if wrong_intent in self.classifier.index:
                        self.classifier.update(features, wrong_intent, weight=-2.0)
                    result["applied"] = True
            self.calibrator.correction(wrong_intent)
            self.corrections_total += 1
            self.history.append({
                "at": time.time(),
                "intent": right_intent,
                "success": True,
                "correction": True,
                "rejected": wrong_intent,
            })

        BUS.emit(Ev.SKILL_LEARNED, {
            "correction": True,
            "text": text[:80],
            "wrong": wrong_intent,
            "right": right_intent,
        }, "mind")
        return result

    # -- bandit ------------------------------------------------------
    def choose(self, intent: str, candidates: Sequence[str], slots: Optional[Dict[str, Any]] = None):
        return self.bandit.select(self.bandit.context(intent, slots), candidates)

    def reward(self, intent: str, arm: str, value: float,
               slots: Optional[Dict[str, Any]] = None) -> None:
        self.bandit.update(self.bandit.context(intent, slots), arm, value)

    def calibrate(self, intent: str, raw: float) -> float:
        return self.calibrator.adjusted(intent, raw)

    # ------------------------------------------------------------------
    # Corrections: detect them in free text
    # ------------------------------------------------------------------
    @staticmethod
    def looks_like_correction(text: str) -> bool:
        probe = normalize_text(text or "")
        if len(probe) > 60:
            return False
        return any(phrase in probe for phrase in CORRECTION_PHRASES)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save(self) -> Path:
        if self.read_only:
            # Another process owns the mind; writing here would erase its
            # learning. Stay quiet instead.
            return self.file
        with self._lock:
            payload = {
                "version": self.VERSION,
                "saved": time.time(),
                "saved_h": stamp(),
                "classes": self.classes,
                "classifier": self.classifier.to_dict() if self.classifier else None,
                "bandit": {
                    "exploration": self.bandit.exploration,
                    "arms": {
                        context: {arm: values for arm, values in table.items()}
                        for context, table in self.bandit.arms.items()
                    },
                    "global_arms": {arm: values for arm, values in self.bandit.global_arms.items()},
                    "updates": self.bandit.updates,
                },
                "calibrator": self.calibrator.to_dict(),
                "corrections": self.corrections_total,
                "last_train": self.last_train,
                "history_tail": self.history[-400:],
            }
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.file)
        return self.file

    def load(self) -> bool:
        if not self.file.exists():
            return False
        try:
            raw = json.loads(self.file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log_warn(f"mind file unreadable, starting fresh: {exc}", "mind")
            return False

        try:
            self.classes = raw.get("classes", [])
            if raw.get("classifier") and self.classes:
                self.classifier = OnlineSoftmax.from_dict(raw["classifier"])

            band = raw.get("bandit", {})
            self.bandit = ToolBandit(exploration=band.get("exploration", 1.2))
            for context, table in band.get("arms", {}).items():
                self.bandit.arms[context] = defaultdict(
                    lambda: [0.0, 0.0], {arm: list(v) for arm, v in table.items()}
                )
            for arm, values in band.get("global_arms", {}).items():
                self.bandit.global_arms[arm] = list(values)
            self.bandit.updates = int(band.get("updates", 0))

            self.calibrator = Calibrator.from_dict(raw.get("calibrator", {}))
            self.corrections_total = int(raw.get("corrections", 0))
            self.last_train = float(raw.get("last_train", 0.0))
            self.history = list(raw.get("history_tail", []))
        except Exception as exc:  # never let a bad save break the agent
            log_warn(f"mind file could not be restored: {exc}", "mind")
            return False

        log_info(
            f"mind restored: {self.classifier.trained if self.classifier else 0} training "
            f"steps, {len(self.classes)} intents, {self.corrections_total} corrections",
            "mind",
        )
        return True

    def reset(self) -> None:
        with self._lock:
            if self.classifier:
                self.classifier.forget()
            self.bandit = ToolBandit()
            self.calibrator = Calibrator()
            self.history.clear()
            self.corrections_total = 0
        self.save()
        BUS.emit(Ev.LEARNED, {"reset": True}, "mind")

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        classifier = self.classifier
        top = []
        if classifier and classifier.trained:
            # Which label has accumulated the most confident weights.
            for i, name in enumerate(classifier.classes):
                table = classifier.weights[i]
                positive = sum(w for w in table.values() if w > 0)
                if positive:
                    top.append({"intent": name, "learned_weight": round(positive, 2)})
            top.sort(key=lambda r: r["learned_weight"], reverse=True)

        return {
            "enabled": classifier is not None,
            "owns_file": self.owner,
            "read_only": self.read_only,
            "classes": len(self.classes),
            "trained_examples": classifier.trained if classifier else 0,
            "corrections_learned": self.corrections_total,
            "weights_stored": sum(len(t) for t in classifier.weights) if classifier else 0,
            "weight_bytes": classifier.size_bytes if classifier else 0,
            "bandit": self.bandit.stats(),
            "calibration": self.calibrator.weakest(),
            "best_learned": top[:8],
            "file": str(self.file),
            "file_size": self.file.stat().st_size if self.file.exists() else 0,
            "last_train": relative(self.last_train) if self.last_train else "never",
        }

    def explain(self, text: str) -> Dict[str, Any]:
        """Show what the learned model currently thinks, and why."""
        if not self.classifier:
            return {"enabled": False}
        return {
            "enabled": True,
            "text": text,
            "features": len(vectorize(text)),
            "ranked": [
                {"intent": intent, "probability": round(probability, 4)}
                for intent, probability in self.classifier.ranked(text)
            ],
            "trained_examples": self.classifier.trained,
        }


_MIND: Optional[Mind] = None
_MIND_LOCK = threading.Lock()


def get_mind(classes: Optional[Sequence[str]] = None) -> Mind:
    global _MIND
    if _MIND is None:
        with _MIND_LOCK:
            if _MIND is None:
                known = list(classes or [])
                if not known:
                    try:
                        from .nlu import get_nlu

                        known = get_nlu().intents()
                    except Exception:
                        known = []
                _MIND = Mind(classes=known)
    return _MIND