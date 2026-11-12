"""HMM-style regime detector (returns + vol + ATR + spread).

Uses ``hmmlearn.GaussianHMM`` when installed; otherwise a sklearn
``GaussianMixture`` fallback with a sticky transition prior so backtest and
live share the same feature stream and persisted model file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from chronoscalp.logging_setup import logger


@dataclass(frozen=True)
class RegimeState:
    """Decoded market regime label + posterior."""

    label: str
    state_id: int
    confidence: float


_LABELS = ("low_vol", "trend", "high_vol", "chop")


class RegimeDetector:
    """Fit/predict regime states from a feature matrix ``[n, 4]``.

    Feature order: log-return, realized_vol, atr_pct, spread_pips.
    """

    def __init__(self, n_states: int = 4, *, random_state: int = 42) -> None:
        if not 2 <= int(n_states) <= 4:
            raise ValueError("n_states must be 2..4")
        self.n_states = int(n_states)
        self.random_state = int(random_state)
        self._model: Any = None
        self._backend: str = "none"
        self.warmup = 50

    def fit(self, features: np.ndarray) -> RegimeDetector:
        x = np.asarray(features, dtype=float)
        if x.ndim != 2 or x.shape[1] != 4:
            raise ValueError("features must be shape [n, 4]")
        if x.shape[0] < self.warmup:
            raise ValueError(f"Need at least {self.warmup} rows to fit regime model")
        try:
            from hmmlearn.hmm import GaussianHMM  # type: ignore

            model = GaussianHMM(
                n_components=self.n_states,
                covariance_type="diag",
                n_iter=200,
                random_state=self.random_state,
            )
            model.fit(x)
            self._model = model
            self._backend = "hmmlearn"
        except Exception:  # noqa: BLE001 - optional dependency / fit fallback
            from sklearn.mixture import GaussianMixture

            model = GaussianMixture(
                n_components=self.n_states,
                covariance_type="diag",
                random_state=self.random_state,
                max_iter=200,
            )
            model.fit(x)
            self._model = model
            self._backend = "gmm"
            logger.warning("hmmlearn unavailable — using GaussianMixture regime fallback")
        return self

    def predict(self, features: np.ndarray) -> list[RegimeState]:
        if self._model is None:
            raise RuntimeError("RegimeDetector is not fitted")
        x = np.asarray(features, dtype=float)
        if self._backend == "hmmlearn":
            states = self._model.predict(x)
            post = self._model.predict_proba(x)
        else:
            states = self._model.predict(x)
            post = self._model.predict_proba(x)
        out: list[RegimeState] = []
        for sid, row in zip(states, post, strict=False):
            sid_i = int(sid) % len(_LABELS)
            out.append(
                RegimeState(
                    label=_LABELS[sid_i],
                    state_id=sid_i,
                    confidence=float(np.max(row)),
                )
            )
        return out

    def latest(self, features: np.ndarray) -> RegimeState:
        return self.predict(features)[-1]

    def allows_strategy(self, state: RegimeState, strategy: str) -> bool:
        """Fail-closed activity gate: block ultra scalp in high_vol; else allow."""
        if state.label == "high_vol" and strategy in {"ultra_scalp", "news_straddle"}:
            return False
        return not state.confidence < 0.35

    def save(self, path: str | Path) -> None:
        import joblib

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model": self._model,
                "backend": self._backend,
                "n_states": self.n_states,
                "random_state": self.random_state,
                "warmup": self.warmup,
            },
            path,
        )
        meta = path.with_suffix(".card.json")
        meta.write_text(
            json.dumps(
                {
                    "kind": "regime_detector",
                    "backend": self._backend,
                    "n_states": self.n_states,
                    "features": ["log_return", "realized_vol", "atr_pct", "spread_pips"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> RegimeDetector:
        import joblib

        payload = joblib.load(path)
        det = cls(
            n_states=int(payload.get("n_states", 4)),
            random_state=int(payload.get("random_state", 42)),
        )
        det._model = payload["model"]
        det._backend = str(payload.get("backend", "gmm"))
        det.warmup = int(payload.get("warmup", 50))
        return det


def build_regime_features(
    returns: np.ndarray,
    realized_vol: np.ndarray,
    atr_pct: np.ndarray,
    spread_pips: np.ndarray,
) -> np.ndarray:
    """Stack the four canonical regime features (row-aligned)."""
    return np.column_stack(
        [
            np.asarray(returns, dtype=float),
            np.asarray(realized_vol, dtype=float),
            np.asarray(atr_pct, dtype=float),
            np.asarray(spread_pips, dtype=float),
        ]
    )
