"""Train, persist, and load setup-probability classifiers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import accuracy_score, roc_auc_score

from chronoscalp.logging_setup import logger
from chronoscalp.ml.features import FEATURE_COLUMNS


def chronological_train_test_split(
    dataset: pd.DataFrame,
    *,
    test_size: float = 0.25,
    embargo: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a chronologically ordered dataset without shuffling.

    ``embargo`` drops the last ``embargo`` training rows immediately before the
    test window so overlapping label horizons cannot leak (AFML purge/embargo).
    """
    if not 0.0 < float(test_size) < 1.0:
        raise ValueError("test_size must be in (0, 1)")
    n = len(dataset)
    if n < 4:
        raise ValueError("Need at least 4 samples for a chronological split")
    test_n = max(1, int(round(n * float(test_size))))
    train_end = n - test_n
    if train_end <= 0:
        raise ValueError("test_size leaves no training samples")
    embargo_n = max(0, int(embargo))
    usable_train_end = max(1, train_end - embargo_n)
    train = dataset.iloc[:usable_train_end]
    test = dataset.iloc[train_end:]
    if train.empty or test.empty:
        raise ValueError("Chronological split produced an empty fold")
    return train, test


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

    def train(
        self,
        dataset: pd.DataFrame,
        test_size: float = 0.25,
        *,
        embargo: int = 0,
    ) -> TrainReport:
        if dataset.empty or "label" not in dataset.columns:
            raise ValueError("Dataset is empty or missing 'label' column")

        if dataset["label"].nunique() < 2:
            raise ValueError("Need both win and loss labels to train a classifier")

        # Rows from build_labeled_dataset are chronological; never shuffle.
        train_df, test_df = chronological_train_test_split(
            dataset, test_size=test_size, embargo=embargo
        )
        x_train = train_df[self.feature_columns].astype(float)
        y_train = train_df["label"].astype(int)
        x_test = test_df[self.feature_columns].astype(float)
        y_test = test_df["label"].astype(int)

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
            positive_rate=float(dataset["label"].astype(int).mean()),
        )

    def predict_proba(self, features: dict[str, float]) -> float:
        row = pd.DataFrame(
            [[features.get(col, 0.0) for col in self.feature_columns]], columns=self.feature_columns
        )
        proba = self._model.predict_proba(row)[0]
        return float(proba[1])
