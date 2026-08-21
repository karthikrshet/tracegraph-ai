"""Evaluate a real generated report against a separately reviewed truth set."""

from __future__ import annotations

import json
from pathlib import Path

import typer

app = typer.Typer(add_completion=False)


def _require_id_set(value: object, source: str) -> set[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise typer.BadParameter(f"{source} must be a JSON list of requirement IDs")
    return set(value)


@app.command()
def main(
    report: Path = typer.Option(..., exists=True, readable=True, help="Generated blast-radius JSON report"),
    ground_truth: Path = typer.Option(..., exists=True, readable=True, help="Human-reviewed JSON truth set"),
) -> None:
    """Calculate requirement-impact precision, recall, and F1 without mock predictions."""
    report_data = json.loads(report.read_text(encoding="utf-8"))
    truth_data = json.loads(ground_truth.read_text(encoding="utf-8"))
    if report_data.get("metrics", {}).get("evidence_mode") != "neo4j_graph_traversal":
        raise typer.BadParameter("Report is not provenance-verified and cannot be evaluated.")

    predicted = {str(item["item_id"]) for item in report_data.get("impacted_requirements", [])}
    expected = _require_id_set(truth_data.get("impacted_requirement_ids"), str(ground_truth))
    tp, fp, fn = len(predicted & expected), len(predicted - expected), len(expected - predicted)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    typer.echo(json.dumps({"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}, indent=2))


if __name__ == "__main__":
    app()
