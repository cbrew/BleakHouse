import pandas as pd
from hamilton.io.materialization import from_, to
import logging
from hamilton import driver, base
import bleak_house.download
import bleak_house.metrics


def make_driver():
    data_path = "data"
    materializers = [
        to.json(
            id="chapters_json",  # name of the DataSaver node
            dependencies=[
                "chapters"
            ],  # name of the function whose output we want to save
            path=f"{data_path}/bleak_house.json",
        ),
    ]

    dr = (
        driver.Builder()
        .with_config({"input_choice": "plaintext"})
        .with_materializers(*materializers)
        .with_modules(bleak_house.download, bleak_house.metrics)
        .build()
    )
    return dr


def visualize_driver():
    dr = make_driver()
    dr.display_all_functions("graphs/bleak_house_download.png")


def run_driver():
    dr = make_driver()
    dr.execute(final_vars=["chapters_json"])


if __name__ == "__main__":
    run_driver()
