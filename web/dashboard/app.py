import os
from pathlib import Path

import panel as pn
import param
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import ui
from main_dashboard import MainDashboard
from pyarrow import compute as pc

from osm.schemas import schema_helpers as osh


def load_data():
    local_path = os.environ.get("LOCAL_DATA_PATH")
    if local_path is not None and Path(local_path).exists():
        dset = ds.dataset(local_path, format="parquet")
    else:
        dset = ds.dataset(osh.matches_to_table(osh.get_data_from_mongo()))
        pq.write_table(dset.to_table(), local_path, compression="snappy")

    tb = dset.to_table()
    split_col = pc.split_pattern(
        pc.if_else(
            pc.is_null(tb["affiliation_country"]),
            pa.scalar(""),
            tb["affiliation_country"],
        ),
        pattern=";",
    )
    tb = tb.set_column(
        tb.column_names.index("affiliation_country"),
        "affiliation_country",
        pa.array(split_col, type=pa.list_(pa.string())),
    )
    raw_data = tb.to_pandas()
    raw_data["metrics"] = "RTransparent"
    raw_data = raw_data[raw_data.year >= 2000]

    # necessary conversion to tuples, which is hashable type
    # needed for grouping.
    # Also removes duplicates and removes leading and trailing spaces in values.
    # Also replaces empty lists with ("None", ) to simplify the filtering and grouping in the dashboard
    for col in ["funder", "affiliation_country", "data_tags"]:
        raw_data[col] = raw_data[col].apply(
            lambda x: ("None",)
            if (len(x) == 0 or len(x) == 1 and x[0] == "")
            else tuple(set([v.strip() for v in x]))
        )

    # Filter out some distracting weird data
    raw_data = raw_data[
        raw_data["journal"]
        != "Acta Crystallographica Section E: Structure Reports Online"
    ]

    return raw_data


class OSMApp(param.Parameterized):
    def __init__(self):
        super().__init__()

        # Apply the design modifiers to the panel components
        # It returns all the CSS files of the modifiers
        self.css_filepaths = ui.apply_design_modifiers()

    def get_template(self):
        # A bit hacky, but works.
        # we need to preload the css files to avoid a flash of unstyled content, especially when switching between chats.
        # This is achieved by adding <link ref="preload" ...> tags in the head of the document.
        # But none of the panel templates allow to add custom link tags in the head.
        # the only way I found is to take advantage of the raw_css parameter, which allows to add custom css in the head.
        preload_css = "\n".join(
            [
                f"""<link rel="preload" href="{css_fp}" as="style" />"""
                for css_fp in self.css_filepaths
            ]
        )
        preload_css = f"""
                     </style>
                     {preload_css}
                     <style type="text/css">
                     """

        template = pn.template.FastListTemplate(
            site="OpenSciMetrics",
            title="Measuring Open Science",
            favicon="https://www.nih.gov/favicon.ico",
            sidebar=[],
            accent=ui.MAIN_COLOR,
            theme_toggle=False,
            raw_css=[ui.CSS_VARS, ui.CSS_GLOBAL, preload_css],
            css_files=[
                "https://rsms.me/inter/inter.css",
                "https://fonts.googleapis.com/css2?family=Roboto:ital,wght@0,100;0,300;0,400;0,500;0,700;0,900;1,100;1,300;1,400;1,500;1,700;1,900&display=swap",
                "css/global/vars.css",
                "css/global/flat.css",
                "css/global/intro.css",
                "css/global/vars.css",
            ],
        )
        # <link rel="preconnect" href="https://fonts.googleapis.com">
        # <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        # <link href="https://fonts.googleapis.com/css2?family=Roboto:ital,wght@0,100;0,300;0,400;0,500;0,700;0,900;1,100;1,300;1,400;1,500;1,700;1,900&display=swap" rel="stylesheet">
        template.header.append(
            ui.connection_monitor(),
        )

        return template

    def dashboard_page(self):
        template = self.get_template()
        dashboard = MainDashboard({"RTransparent": pn.state.cache["data"]})
        template.main.append(dashboard.get_dashboard())
        template.sidebar.append(dashboard.get_sidebar())

        return template

    def serve(self):
        pn.serve(
            {"/": self.dashboard_page},
            address="0.0.0.0",
            port=8501,
            start=True,
            location=True,
            show=False,
            keep_alive=30 * 1000,  # 30s
            autoreload=True,
            admin=True,
            profiler="pyinstrument",
            allow_websocket_origin=[
                "localhost:8501",
                "opensciencemetrics.org",
                "dev.opensciencemetrics.org",
            ],
            static_dirs={
                dir: str(Path(__file__).parent / dir)
                for dir in ["css"]  # add more directories if needed
            },
        )


def on_load():
    """
    Add resource intensive things that you only want to run once.
    """
    pn.config.browser_info = True
    pn.config.notifications = True
    raw_data = load_data()

    pn.state.cache["data"] = raw_data


if __name__ == "__main__":
    # Runs all the things necessary before the server actually starts.
    pn.state.onload(on_load)
    print("starting dashboard!")

    OSMApp().serve()
