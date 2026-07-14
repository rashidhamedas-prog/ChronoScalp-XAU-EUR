"""Train, persist, and load setup-probability classifiers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split

from chronoscalp.logging_setup import logger
from chronoscalp.ml.features import FEATURE_COLUMNS


@dataclass
class TrainReport:
    train_samples: int
    test_samples: int
    accuracy: float
    roc_auc: float | None
    positive_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "train_samples": self.train_samples,
            "test_samples": self.test_samples,
            "accuracy": round(self.accuracy, 4),
            "roc_auc": round(self.roc_auc, 4) if self.roc_auc is not None else None,
            "positive_rate": round(self.positive_rate, 4),
        }


class SetupClassifier:
    """Gradient-boosting binary classifier for setup win probability."""

    def __init__(self, model: GradientBoostingClassifier | None = None) -> None:
        self._model = model or GradientBoostingClassifier(
            random_state=42,
            max_depth=3,
            n_estimators=100,
        )
        self.feature_columns = list(FEATURE_COLUMNS)

    @classmethod
    def load(cls, path: str | Path) -> SetupClassifier:
        import joblib

        payload = joblib.load(path)
        instance = cls(model=payload["model"])
        instance.feature_columns = list(payload.get("feature_columns", FEATURE_COLUMNS))
        return instance

    def save(self, path: str | Path) -> None:
        import joblib

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": self._model, "feature_columns": self.feature_columns}, path)
        logger.info("Saved setup classifier to {}", path)

    def train(self, dataset: pd.DataFrame, test_size: float = 0.25) -> TrainReport:
        if dataset.empty or "label" not in dataset.columns:
            raise ValueError("Dataset is empty or missing 'label' column")

        x = dataset[self.feature_columns].astype(float)
        y = dataset["label"].astype(int)

        if y.nunique() < 2:
            raise ValueError("Need both win and loss labels to train a classifier")

        x_train, x_test, y_train, y_test = train_test_split(
            x, y, test_size=test_size, random_state=42, stratify=y
        )
        self._model.fit(x_train, y_train)
        preds = self._model.predict(x_test)
        accuracy = float(accuracy_score(y_test, preds))

        roc: float | None = None
        try:
            proba = self._model.predict_proba(x_test)[:, 1]
            roc = float(roc_auc_score(y_test, proba))
        except ValueError:
            pass

        return TrainReport(
            train_samples=len(x_train),
            test_samples=len(x_test),
            accuracy=accuracy,
            roc_auc=roc,
            positive_rate=float(y.mean()),
        )

    def predict_proba(self, features: dict[str, float]) -> float:
        row = pd.DataFrame(
            [[features.get(col, 0.0) for col in self.feature_columns]], columns=self.feature_columns
        )
        proba = self._model.predict_proba(row)[0]
        return float(proba[1])
