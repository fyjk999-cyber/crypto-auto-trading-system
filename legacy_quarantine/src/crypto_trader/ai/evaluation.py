"""Prediction evaluation and calibration."""

from __future__ import annotations

from dataclasses import dataclass

from crypto_trader.ai.memory import AIPredictionRecord


@dataclass
class CalibrationState:
    total: int = 0
    correct: int = 0
    calibration_error: float = 0.0


class PredictionEvaluator:
    def evaluate(self, record: AIPredictionRecord, actual_direction: str) -> str:
        if record.direction == "NEUTRAL":
            record.error_category = "MISSED_OPPORTUNITY"
            record.actual_result = 0.0
            return "MISSED_OPPORTUNITY"
        correct = record.direction == actual_direction
        record.actual_result = 1.0 if correct else 0.0
        if correct:
            record.error_category = "SUCCESS"
            return "SUCCESS"
        if record.direction == "LONG":
            record.error_category = "FALSE_LONG"
        else:
            record.error_category = "FALSE_SHORT"
        return record.error_category

    def calibrate(self, records: list[AIPredictionRecord]) -> CalibrationState:
        state = CalibrationState(total=len(records))
        for record in records:
            if record.actual_result == 1.0:
                state.correct += 1
            elif record.actual_result is not None:
                state.calibration_error += abs(record.confidence - 0.0)
        if state.total > 0:
            state.calibration_error = round(state.calibration_error / state.total, 3)
        return state
