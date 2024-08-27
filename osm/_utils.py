import argparse
import logging
import os
import shlex
import subprocess
import time
import types
from pathlib import Path

import pandas as pd
import requests

DEFAULT_OUTPUT_DIR = "./osm_output"
logger = logging.getLogger(__name__)

ERROR_CSV_PATH = Path("error_log.csv")
ERROR_LOG_PATH = Path("error.log")


def write_error_to_file(row: pd.Series, error: Exception):
    with ERROR_CSV_PATH.open("a") as csv_file, ERROR_LOG_PATH.open("a") as log_file:
        # Write the problematic row data to the CSV, add header if not yet populated.
        row.to_csv(
            csv_file,
            header=not ERROR_CSV_PATH.exists() or ERROR_CSV_PATH.stat().st_size == 0,
            index=False,
        )

        # Drop string values as they tend to be too long
        display_row = (
            row.apply(lambda x: x if not isinstance(x, str) else None)
            .dropna()
            .to_dict()
        )
        log_file.write(f"Error processing data:\n {display_row}\nError: {error}\n\n")


def _get_metrics_dir(output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
    metrics_dir = Path(output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    return metrics_dir


def _get_text_dir(output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
    text_dir = Path(output_dir) / "pdf_texts"
    text_dir.mkdir(parents=True, exist_ok=True)
    return text_dir


def _existing_file(path_string):
    path = Path(path_string)
    if not path.exists():
        raise argparse.ArgumentTypeError(f"The path {path} does not exist.")
    return path


def get_compute_context_id():
    return hash(f"{os.environ.get('HOSTNAME')}_{os.environ.get('USERNAME')}")


def wait_for_containers():
    while True:
        try:
            response = requests.get("http://localhost:8071/health")
            if response.status_code == 200:
                break
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)


def compose_up():
    cmd = shlex.split("docker compose up -d --build")
    subprocess.run(
        cmd,
        check=True,
    )


def compose_down():
    cmd = shlex.split("docker compose down")
    subprocess.run(
        cmd,
        check=True,
    )


def _setup(args):
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    xml_path = _get_text_dir() / f"{args.uid}.xml"
    if args.filepath.name.endswith(".pdf"):
        if xml_path.exists():
            raise FileExistsError(xml_path)
    elif args.filepath.name.endswith(".xml"):
        logger.warning(
            """
            The input file is an xml file. Skipping the pdf to text conversion
            and so ignoring requested parsers.
            """
        )
        args.parser = ["no-op"]
    metrics_path = _get_metrics_dir() / f"{args.uid}.json"
    if metrics_path.exists():
        raise FileExistsError(metrics_path)
    if not args.user_managed_compose:
        compose_up()

    logger.info("Waiting for containers to be ready...")
    print("Waiting for containers to be ready...")
    wait_for_containers()
    print("Containers ready!")
    return xml_path, metrics_path


def coerce_to_string(v):
    if isinstance(v, (int, float, bool)):
        return str(v)
    elif isinstance(v, types.NoneType):
        return None
    elif pd.isna(v):
        return None
    elif not isinstance(v, str):
        raise ValueError("string required or a type that can be coerced to a string")
    return v


def flatten_dict(d):
    """
    Recursively flattens a nested dictionary without prepending parent keys.

    :param d: Dictionary to flatten.
    :return: Flattened dictionary.
    """
    items = []
    for k, v in d.items():
        if isinstance(v, dict):
            # If the value is a dictionary, flatten it without the parent key
            items.extend(flatten_dict(v).items())
        else:
            items.append((k, v))
    return dict(items)