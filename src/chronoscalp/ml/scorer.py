"""Runtime setup-probability scorer — optional loaded ML model."""

from __future__ import annotations

from pathlib import Path

from chronoscalp.logging_setup import logger
from chronoscalp.ml.model import SetupClassifier

_classifier: SetupClassifier | None = None
_model_path: str | None = None


def configure_scorer(model_path: str | Path | None) -> None:
    """Load a trained classifier for live/backtest scoring, or disable."""
    global _classifier, _model_path
    if not model_path:
        _classifier = None
        _model_path = None
        return

    path = Path(model_path)
    if not path.exists():
        logger.warning("ML model not found at {} — using neutral confidence 0.5", path)
        _classifier = None
        _model_path = None
        return

    _classifier = SetupClassifier.load(path)
    _model_path = str(path)
    logger.info("Loaded setup classifier from {}", path)


def is_configured() -> bool:
    return _classifier is not None


def predict_setup_probability(features: dict[str, float]) -> float:
    """Return P(win) from the loaded model, or 0.5 if no model is configured."""
    if _classifier is None:
        return 0.5
    return _classifier.predict_proba(features)


def reset_scorer() -> None:
    """Clear loaded model (for tests)."""
    global _classifier, _model_path
    _classifier = None
    _model_path = None
