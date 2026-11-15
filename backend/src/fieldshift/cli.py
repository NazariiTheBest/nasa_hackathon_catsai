"""Command-line tools: bundle hand-off, climate cache and the server."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from fieldshift.settings import project_root

app = typer.Typer(add_completion=False, help="Field Shift command-line tools.", no_args_is_help=True)


@app.command("validate-bundle")
def validate_bundle_cmd(path: Path = typer.Argument(..., help="Bundle directory to validate.")) -> None:
    """Validate a bundle against the data contract. Exits non-zero when invalid."""
    from fieldshift.ingest.validator import validate_bundle

    report = validate_bundle(path)
    typer.echo(report.render())
    raise typer.Exit(code=0 if report.ok else 1)


@app.command("make-sample")
def make_sample_cmd(
    out: Path = typer.Option(None, help="Output directory. Defaults to data/sample."),
    seed: int = typer.Option(42, help="Random seed."),
) -> None:
    """Write the synthetic sample bundles."""
    from fieldshift.ingest.sample import generate_sample

    for bundle in generate_sample(out or project_root() / "data" / "sample", seed=seed):
        typer.echo(f"wrote {bundle}")


@app.command("convert-gee")
def convert_gee_cmd(
    input_table: Path = typer.Argument(..., help="Earth Engine export (CSV or Parquet), one row per unit and date."),
    mapping: Path = typer.Argument(..., help="YAML mapping from band columns to contract variables."),
    output: Path = typer.Argument(..., help="Output path, normally <bundle>/timeseries.parquet."),
) -> None:
    """Convert an Earth Engine export table to the contract's long format."""
    from fieldshift.ingest.convert import ConversionError, convert_file

    try:
        long = convert_file(input_table, mapping, output)
    except ConversionError as exc:
        typer.echo(f"conversion failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    counts = long.groupby("variable", observed=True).size().to_dict()
    typer.echo(f"wrote {output} with {len(long)} rows: {counts}")


@app.command("export-schemas")
def export_schemas_cmd(out: Path = typer.Option(None, help="Output directory. Defaults to contracts/.")) -> None:
    """Write the bundle JSON Schemas and the API schema for the team."""
    from fieldshift.contracts.export import write_all

    for path in write_all(out or project_root() / "contracts"):
        typer.echo(f"wrote {path}")


@app.command("climate")
def climate_cmd(lat: float, lon: float) -> None:
    """Fetch (or read from cache) the NASA POWER series for a point and print a summary."""
    from fieldshift.climate.power import ClimateUnavailable, PowerClient

    try:
        series = PowerClient().get_series(lat, lon)
    except ClimateUnavailable as exc:
        typer.echo(f"climate unavailable: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(series.provenance.model_dump(mode="json"), indent=2))
    typer.echo(f"rows: {len(series.data)}  columns: {', '.join(series.data.columns)}")


@app.command("prewarm")
def prewarm_cmd(
    bundle: Path = typer.Option(None, help="Bundle directory; every unit's centroid is fetched."),
    points: Path = typer.Option(None, help="CSV file with lat,lon columns."),
    pause: float = typer.Option(1.0, help="Seconds to wait between downloads."),
) -> None:
    """Pre-fetch NASA POWER series. Skips cached cells; safe to re-run after interruption."""
    from fieldshift.climate.power import PowerClient, points_from_bundle, points_from_csv

    if (bundle is None) == (points is None):
        typer.echo("give exactly one of --bundle or --points", err=True)
        raise typer.Exit(code=2)
    pts = points_from_bundle(bundle) if bundle else points_from_csv(points)
    summary = PowerClient().prewarm(pts, pause_s=pause, progress=typer.echo)
    typer.echo(
        f"cells: {summary.cells}  fetched: {len(summary.fetched)}  "
        f"skipped: {len(summary.skipped)}  failed: {len(summary.failed)}"
    )
    for cell, reason in summary.failed:
        typer.echo(f"  failed {cell}: {reason}")
    raise typer.Exit(code=1 if summary.failed else 0)


@app.command("serve")
def serve_cmd(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Run the HTTP API."""
    import uvicorn

    uvicorn.run("fieldshift.api.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
