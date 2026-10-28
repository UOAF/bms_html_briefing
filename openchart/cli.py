"""Command-line entry point for airport chart generation."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from .bms_layout import chart_path, resolve_chart_folder
from .geometry import build_parking_charts
from .ownership import find_start_campaign, load_objective_teams
from .resvg_render import (
    DEFAULT_RASTER_DPI,
    PdfRenderOptions,
    render_png_pages_pdf,
    render_svg_page_png,
    render_svg_pages_pdf,
)
from .render import (
    build_airport_render_context,
    output_filename,
    parking_pdf_output_filename,
    parking_output_filename,
    render_airport_chart_svg,
    render_airport_parking_chart_svg,
)
from .source import DEFAULT_CAMPAIGN_IDS, AirportRepository, load_airports
from .topo_render import render_topographic_chart_svg, topographic_output_filename


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate Falcon BMS airport ground and runway-end parking charts, "
            "with optional topographic charts, as SVG, PNG, and/or PDF files."
        )
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("/data/Data"),
        help="matching BMS theater Data directory (default: /data/Data)",
    )
    parser.add_argument(
        "--campaign",
        type=Path,
        default=None,
        help=(
            "optional campaign container supplying snapshot-specific .obj "
            "airfields (default: use current theater support data)"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("test_charts"),
        help="output directory (default: test_charts)",
    )
    parser.add_argument(
        "--airport",
        type=int,
        action="append",
        dest="campaign_ids",
        help=(
            "airfield campaign ID; repeat for multiple airports "
            f"(default: {', '.join(map(str, DEFAULT_CAMPAIGN_IDS))})"
        ),
    )
    parser.add_argument(
        "--topo",
        action="store_true",
        help="also generate a 50 × 50 NM chart with 500 ft elevation bands",
    )
    parser.add_argument(
        "--format",
        choices=("svg", "png", "pdf", "both", "all"),
        default="svg",
        dest="output_format",
        help=(
            "output format; 'both' writes SVG and PDF, 'all' also writes PNG "
            "(default: svg)"
        ),
    )
    parser.add_argument(
        "--bms-layout",
        action="store_true",
        help=(
            "write <team>/<airfield>/<airfield>_AGC|APC_RWYxx|LOC images and "
            "_AGC|APC|LOC PDFs (APC PDF holds all runway ends); team = first "
            "owner in Campaign/Te_New_Nt.tac (or --campaign); use with "
            "--format png, pdf, or all (= png + pdf); adds local charts"
        ),
    )
    parser.add_argument(
        "--all-airports",
        action="store_true",
        help="generate every airfield in the theater",
    )
    parser.add_argument(
        "--dpi",
        type=_positive_dpi,
        default=DEFAULT_RASTER_DPI,
        help=(
            "raster resolution for PNG and PDF output "
            f"(default: {DEFAULT_RASTER_DPI:g})"
        ),
    )
    return parser


def _positive_dpi(value: str) -> float:
    try:
        dpi = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("DPI must be a number") from exc
    if not math.isfinite(dpi) or dpi <= 0:
        raise argparse.ArgumentTypeError("DPI must be a positive finite number")
    return dpi


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    repository = AirportRepository(arguments.data_root, arguments.campaign)
    if arguments.all_airports:
        campaign_ids = tuple(entry.campaign_id for entry in repository.entries)
    else:
        campaign_ids = tuple(arguments.campaign_ids or DEFAULT_CAMPAIGN_IDS)
    airports = load_airports(
        arguments.data_root,
        arguments.campaign,
        campaign_ids,
        repository,
    )
    if arguments.bms_layout:
        if arguments.output_format not in {"png", "pdf", "all"}:
            build_parser().error("--bms-layout requires --format png, pdf, or all")
        return _write_bms_layout(arguments, airports, repository)
    write_svg = arguments.output_format in {"svg", "both", "all"}
    write_png = arguments.output_format in {"png", "all"}
    write_pdf = arguments.output_format in {"pdf", "both", "all"}
    pdf_options = PdfRenderOptions(dpi=arguments.dpi)
    for airport in airports:
        render_context = build_airport_render_context(airport)
        ground_svg = render_airport_chart_svg(airport, context=render_context)
        if write_svg:
            output = _write_bytes(
                arguments.output / output_filename(airport),
                ground_svg,
            )
            print(output)
        ground_png = render_svg_page_png(ground_svg, pdf_options) if write_png else None
        if ground_png is not None:
            output = _write_bytes(
                arguments.output / _png_filename(output_filename(airport)),
                ground_png,
            )
            print(output)
        if write_pdf:
            output = _write_pdf(
                arguments.output / _pdf_filename(output_filename(airport)),
                (ground_svg,),
                pdf_options,
                png_pages=None if ground_png is None else (ground_png,),
            )
            print(output)

        parking_pages: list[bytes] = []
        parking_png_pages: list[bytes] = []
        for parking_chart in build_parking_charts(
            airport.layout,
            runways=render_context.runways,
            atc=airport.atc,
            magnetic_variation_degrees=airport.magnetic_variation_degrees,
            objective_heading_degrees=airport.placement.heading,
        ):
            parking_svg = render_airport_parking_chart_svg(
                airport,
                parking_chart,
                context=render_context,
            )
            parking_pages.append(parking_svg)
            if write_svg:
                output = _write_bytes(
                    arguments.output
                    / parking_output_filename(airport, parking_chart.designator),
                    parking_svg,
                )
                print(output)
            if write_png:
                parking_png = render_svg_page_png(parking_svg, pdf_options)
                parking_png_pages.append(parking_png)
                output = _write_bytes(
                    arguments.output
                    / _png_filename(
                        parking_output_filename(airport, parking_chart.designator)
                    ),
                    parking_png,
                )
                print(output)
        if write_pdf and parking_pages:
            output = _write_pdf(
                arguments.output / parking_pdf_output_filename(airport),
                parking_pages,
                pdf_options,
                png_pages=parking_png_pages or None,
            )
            print(output)

        if arguments.topo:
            topographic_svg = render_topographic_chart_svg(
                airport,
                context=render_context,
            )
            if write_svg:
                output = _write_bytes(
                    arguments.output / topographic_output_filename(airport),
                    topographic_svg,
                )
                print(output)
            topographic_png = (
                render_svg_page_png(topographic_svg, pdf_options)
                if write_png
                else None
            )
            if topographic_png is not None:
                output = _write_bytes(
                    arguments.output
                    / _png_filename(topographic_output_filename(airport)),
                    topographic_png,
                )
                print(output)
            if write_pdf:
                output = _write_pdf(
                    arguments.output
                    / _pdf_filename(topographic_output_filename(airport)),
                    (topographic_svg,),
                    pdf_options,
                    png_pages=(
                        None
                        if topographic_png is None
                        else (topographic_png,)
                    ),
                )
                print(output)
    return 0


def _write_bms_layout(
    arguments: argparse.Namespace, airports, repository: AirportRepository
) -> int:
    formats = (
        {"png", "pdf"} if arguments.output_format == "all" else {arguments.output_format}
    )
    options = PdfRenderOptions(dpi=arguments.dpi)
    teams: dict[int, str] = {}
    start_file = arguments.campaign or find_start_campaign(arguments.data_root)
    if start_file is None:
        print("No Te_New_Nt.tac found; airfields go to the Unassigned folder")
    else:
        teams = load_objective_teams(start_file, repository.support)
    taken: dict[tuple[str, str], int] = {}
    for airport in airports:
        target = resolve_chart_folder(airport, teams, taken)
        context = build_airport_render_context(airport)
        ground = render_svg_page_png(
            render_airport_chart_svg(airport, context=context), options
        )
        images = [("AGC", ground)]
        pdfs = [("AGC", [ground])]
        parking = [
            (
                f"APC_RWY{chart.designator.upper()}",
                render_svg_page_png(
                    render_airport_parking_chart_svg(airport, chart, context=context),
                    options,
                ),
            )
            for chart in build_parking_charts(
                airport.layout,
                runways=context.runways,
                atc=airport.atc,
                magnetic_variation_degrees=airport.magnetic_variation_degrees,
                objective_heading_degrees=airport.placement.heading,
            )
        ]
        images += parking
        if parking:
            pdfs.append(("APC", [png for _, png in parking]))
        try:
            local = render_svg_page_png(
                render_topographic_chart_svg(airport, context=context), options
            )
            images.append(("LOC", local))
            pdfs.append(("LOC", [local]))
        except Exception as exc:
            print(f"{airport.name}: local chart skipped ({exc})")
        for suffix, png in images:
            if "png" in formats:
                print(_write_bytes(chart_path(arguments.output, target, suffix, "png"), png))
        if "pdf" in formats:
            for suffix, pages in pdfs:
                print(
                    _write_pdf(
                        chart_path(arguments.output, target, suffix, "pdf"),
                        (),
                        options,
                        png_pages=pages,
                    )
                )
    return 0


def _write_pdf(
    output: Path,
    svg_pages: list[bytes] | tuple[bytes, ...],
    options: PdfRenderOptions,
    *,
    png_pages: list[bytes] | tuple[bytes, ...] | None = None,
) -> Path:
    payload, _ = (
        render_svg_pages_pdf(svg_pages, options)
        if png_pages is None
        else render_png_pages_pdf(png_pages, options)
    )
    return _write_bytes(output, payload)


def _write_bytes(output: Path, payload: bytes) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    return output


def _pdf_filename(svg_filename: str) -> str:
    return Path(svg_filename).with_suffix(".pdf").name


def _png_filename(svg_filename: str) -> str:
    return Path(svg_filename).with_suffix(".png").name


if __name__ == "__main__":
    raise SystemExit(main())
