from datetime import datetime
from functools import lru_cache

import pandas as pd
import panel as pn
import param
from components.select_picker import SelectPicker

pn.extension("echarts")

pd.options.display.max_columns = None


groups = {"year": "int"}

extraction_tools_params = {
    "RTransparent": {
        "metrics": [
            "is_data_pred",
            "is_code_pred",
        ],
        "splitting_vars": [
            "None",
            "journal",
            "affiliation_country",
            "fund_pmc_institute",
        ],
    }
}

dims_aggregations = {
    "is_data_pred": ["percent", "count_true"],
    "is_code_pred": ["percent", "count_true"],
    # "score": ["mean"],
    # "eigenfactor_score": ["mean"],
}

metrics_titles = {
    "percent_is_data_pred": "Data Sharing (%)",
    "percent_is_code_pred": "Code Sharing (%)",
    "count_true_is_data_pred": "Data Sharing",
    "count_true_is_code_pred": "Code Sharing",
    "mean_score": "Mean Score",
    "mean_eigenfactor_score": "Mean Eigenfactor Score",
}

metrics_by_title = {v: k for k, v in metrics_titles.items()}


aggregation_formulas = {
    "percent": lambda x: x.mean() * 100,
    "count_true": lambda x: (x == True).sum(),  # noqa
    "count": "count",
    "mean": "mean",
}


class MainDashboard(param.Parameterized):
    """
    Main dashboard for the application.
    """

    # High-level parameters.
    extraction_tool = param.Selector(default="", objects=[], label="Extraction tool")

    metrics = param.Selector(default=[], objects=[], label="Metrics")

    splitting_var = param.Selector(
        default="year",
        objects=["year", "fund_pmc_institute"],
        label="Splitting Variable",
    )

    # Filters
    filter_pubdate = param.Range(step=1, label="Publication date")

    filter_journal = param.ListSelector(default=[], objects=[], label="Journal")

    filter_affiliation_country = param.ListSelector(
        default=[], objects=[], label="Country"
    )

    # UI elements
    echarts_pane = pn.pane.ECharts(
        {}, height=640, width=840, renderer="svg", options={"replaceMerge": ["series"]}
    )

    def __init__(self, datasets, **params):
        super().__init__(**params)

        self.datasets = datasets

        # By default, take the first dataset.
        # Currently, there's only RTransparent
        self.param.extraction_tool.objects = list(self.datasets.keys())
        self.extraction_tool = self.param.extraction_tool.objects[0]

        self.journal_select_picker = SelectPicker.from_param(
            self.param.filter_journal,
            update_title_callback=lambda select_picker,
            values,
            options: self.new_picker_title("journals", select_picker, values, options),
        )

        self.affiliation_country_select_picker = SelectPicker.from_param(
            self.param.filter_affiliation_country,
            update_title_callback=lambda select_picker,
            values,
            options: self.new_picker_title(
                "affiliation countries", select_picker, values, options
            ),
        )

        self.build_pubdate_filter()

    @pn.depends("extraction_tool", watch=True)
    def did_change_extraction_tool(self):
        print("DID_CHANGE_EXTRACTION_TOOL")

        # Update the raw data
        self.raw_data = self.datasets[self.extraction_tool]

        # Updated the metrics param
        new_extraction_tools_metrics = extraction_tools_params[self.extraction_tool][
            "metrics"
        ]

        new_metrics = []
        for m in new_extraction_tools_metrics:
            for agg in dims_aggregations[m]:
                new_metrics.append(metrics_titles[f"{agg}_{m}"])

        self.param.metrics.objects = new_metrics
        self.metrics = self.param.metrics.objects[0]

        # Update the splitting_var param
        new_extraction_tools_splitting_vars = extraction_tools_params[
            self.extraction_tool
        ]["splitting_vars"]
        self.param.splitting_var.objects = new_extraction_tools_splitting_vars

        # Update the filters
        ## filter_pubdate
        self.param.filter_pubdate.bounds = (
            self.raw_data.year.min(),
            # self.raw_data.year.max(),
            # Use current year instead, so the "Past X years" buttons work
            datetime.now().year,
        )
        self.param.filter_pubdate.default = (
            self.raw_data.year.min(),
            self.raw_data.year.max(),
        )
        self.filter_pubdate = (self.raw_data.year.min(), self.raw_data.year.max())

        ## filter_journal
        self.param.filter_journal.objects = self.raw_data.journal.unique()

        ## affiliation country
        ## Keeping "None" as a string on purpose, to represent it in the SelectPicker
        countries_with_count = self.get_countries_with_count()

        def country_sorter(c):
            return countries_with_count[c]

        self.param.filter_affiliation_country.objects = sorted(
            countries_with_count.keys(), key=country_sorter, reverse=True
        )

        # This triggers function "did_change_splitting_var"
        # which updates the filter_journal and filter_affiliation_country
        self.splitting_var = self.param.splitting_var.objects[0]

    @lru_cache
    def get_countries_with_count(self):
        countries = {}
        for row in self.raw_data.affiliation_country.values:
            if row is None:
                countries["None"] = countries.get("None", 0) + 1
            else:
                for c in row:
                    countries[c] = countries.get(c, 0) + 1
        return countries

    @pn.depends("splitting_var", watch=True)
    def did_change_splitting_var(self):
        print("DID_CHANGE_SPLITTING_VAR", self.splitting_var)

        if self.splitting_var == "journal":
            # We want to show all journals, but pre-select only the top 10
            self.filter_journal = list(
                self.raw_data.journal.value_counts().iloc[:10].index
            )
            notif_msg = "Splitting by journal. Top 10 journals selected by default."
        else:
            self.filter_journal = self.param.filter_journal.objects

        if self.splitting_var == "affiliation_country":
            # We want to show all countries, but pre-select only the top 10
            countries_with_count = self.get_countries_with_count()
            countries_with_count = {
                country: count
                for country, count in countries_with_count.items()
                if count > 10
            }

            top_10_min = sorted(
                [count for _, count in countries_with_count.items()], reverse=True
            )[10]
            selected_countries = [
                country
                for country, count in countries_with_count.items()
                if count >= top_10_min
            ]
            self.filter_affiliation_country = selected_countries

            notif_msg = "Splitting by affiliation country. Top 10 countries selected by default."
        else:
            self.filter_affiliation_country = (
                self.param.filter_affiliation_country.objects
            )

        if self.splitting_var == "None":
            notif_msg = "No more splitting. Filters reset to default"

        pn.state.notifications.info(notif_msg, duration=5000)

    def filtered_grouped_data(self):
        print("FILTERED_GROUPED_DATA")

        filters = []

        if len(self.filter_journal) != self.param.filter_journal.objects:
            filters.append(f"journal in {self.filter_journal}")

        if self.filter_pubdate is not None:
            filters.append(f"year >= {self.filter_pubdate[0]}")
            filters.append(f"year <= {self.filter_pubdate[1]}")

        filtered_df = (
            self.raw_data.query(" and ".join(filters)) if filters else self.raw_data
        )

        if len(self.filter_affiliation_country) != len(
            self.param.filter_affiliation_country.objects
        ):
            # the filter on countries is a bit different as the rows
            # are list of countries
            def country_filter(cell):
                if cell is None:
                    return "None" in self.filter_affiliation_country
                return any(c in self.filter_affiliation_country for c in cell)

            filtered_df = filtered_df[
                filtered_df.affiliation_country.apply(country_filter)
            ]

        aggretations = {}
        for field, aggs in dims_aggregations.items():
            for agg in aggs:
                aggretations[f"{agg}_{field}"] = (field, aggregation_formulas[agg])

        groupers = ["year"]
        if self.splitting_var != "None":
            groupers.append(self.splitting_var)

        result = filtered_df.groupby(groupers).agg(**aggretations).reset_index()

        return result

    @pn.depends("splitting_var", "filter_pubdate", "metrics", watch=True)
    def updated_echart_plot(self):
        print("updateECHART_PLOT")

        if self.filter_pubdate is None:
            # The filters are not yet initialized
            # Let's return an empty plot
            return self.echarts_pane

        self.echarts_pane.loading = True

        df = self.filtered_grouped_data()

        raw_metric = metrics_by_title[self.metrics]

        xAxis = df["year"].unique().tolist()

        if self.splitting_var == "None":
            series = [
                {
                    "id": self.metrics,
                    "name": self.metrics,
                    "type": "line",
                    "data": df[raw_metric].tolist(),
                }
            ]
            legend_data = [
                {"name": self.metrics, "icon": "path://M 0 0 H 20 V 20 H 0 Z"},
            ]
        else:
            series = []
            legend_data = []

            if self.splitting_var == "affiliation_country":
                splitting_var_filter = self.filter_affiliation_country
                splitting_var_column = "affiliation_country"
                splitting_var_query = lambda cell, selected_item: selected_item in cell

            elif self.splitting_var == "fund_pmc_institute":
                splitting_var_filter = self.filter_fund_pmc_institute
                splitting_var_column = "fund_pmc_institute"
                splitting_var_query = lambda cell, selected_item: cell == selected_item
            else:
                print("Defaulting to splitting var 'journal' ")
                splitting_var_filter = self.filter_journal
                splitting_var_column = "journal"
                splitting_var_query = lambda cell, selected_item: cell == selected_item

            for selected_item in sorted(splitting_var_filter):
                # sub_df = df.query(f"{splitting_var_column} == '{selected_item}'")
                sub_df = (
                    df[
                        df[splitting_var_column].apply(
                            lambda x: splitting_var_query(x, selected_item)
                        )
                    ]
                    .groupby("year")
                    .agg({raw_metric: "mean"})  # todo fix this
                    .reset_index()
                )

                series.append(
                    {
                        "id": selected_item,
                        "name": selected_item,
                        "type": "line",
                        "data": sub_df[raw_metric].tolist(),
                    }
                )
                legend_data.append(
                    {"name": selected_item, "icon": "path://M 0 0 H 20 V 20 H 0 Z"}
                )

        title = f"{self.metrics} by {self.splitting_var} ({int(self.filter_pubdate[0])}-{int(self.filter_pubdate[1])})"

        echarts_config = {
            "title": {
                "text": title,
            },
            "tooltip": {
                "show": True,
                "trigger": "axis",
                # "formatter": f"""<b>{self.splitting_var}</b> : {{b0}} <br />
                #                 {{a0}} : {{c0}} <br />
                #                 {{a1}} : {{c1}} """,
            },
            "legend": {
                "data": legend_data,
                "orient": "vertical",
                "right": 10,
                "top": 20,
                "bottom": 20,
                "show": True,
            },
            "xAxis": {
                "data": xAxis,
                "name": "year",
                "nameLocation": "center",
                "nameGap": 30,
            },
            "yAxis": {
                "name": "percent",
                "nameLocation": "center",
                "nameGap": 30,
            },
            "series": series,
        }

        self.echarts_pane.object = echarts_config
        self.echarts_pane.loading = False

    # Below are all the functions returning the different parts of the dashboard :
    # Sidebar, Top Bar and the plot area (in function get_dashboard)

    def build_pubdate_filter(self):
        print("BUILD_PUBDATE_FILTER")

        # The text input only reflect and update the values of the slider bounds
        # self.pubdate_slider = pn.widgets.RangeSlider.from_param(self.param.filter_pubdate)
        self.pubdate_slider = pn.widgets.IntRangeSlider(
            start=int(self.param.filter_pubdate.bounds[0]),
            end=int(self.param.filter_pubdate.bounds[1]),
            step=1,
        )

        # It's the textInputs that controls the filter_pubdate param
        self.start_pubdate_input = pn.widgets.TextInput(
            value=str(int(self.param.filter_pubdate.bounds[0])),
            name="From",
            css_classes=["filters-text-input", "pubdate-input"],
        )
        self.end_pubdate_input = pn.widgets.TextInput(
            value=str(int(self.param.filter_pubdate.bounds[1])),
            name="To",
            css_classes=["filters-text-input", "pubdate-input"],
        )

        # When the slider's value change, update the TextInputs
        def update_pubdate_text_inputs(event):
            self.start_pubdate_input.value = str(self.pubdate_slider.value[0])
            self.end_pubdate_input.value = str(self.pubdate_slider.value[1])

        self.pubdate_slider.param.watch(update_pubdate_text_inputs, "value_throttled")

        # When the TextInputs' value change, update the slider,
        # and update filter_pubdate
        def update_pubdate_slider(event):
            self.pubdate_slider.value = (
                int(self.start_pubdate_input.value),
                int(self.end_pubdate_input.value),
            )
            self.filter_pubdate = self.pubdate_slider.value

        self.start_pubdate_input.param.watch(update_pubdate_slider, "value")
        self.end_pubdate_input.param.watch(update_pubdate_slider, "value")

        self.last_year_button = pn.widgets.Button(
            name="Last year", width=80, button_type="light", button_style="solid"
        )
        self.past_5years_button = pn.widgets.Button(
            name="Past 5 years", width=80, button_type="light", button_style="solid"
        )
        self.past_10years_button = pn.widgets.Button(
            name="Past 10 years", width=80, button_type="light", button_style="solid"
        )

        def did_click_shortcut_button(event):
            print(event)
            if event.obj.name == "Last year":
                self.pubdate_slider.value = (datetime.now().year, datetime.now().year)
            elif event.obj.name == "Past 5 years":
                self.pubdate_slider.value = (
                    datetime.now().year - 5,
                    datetime.now().year,
                )
            elif event.obj.name == "Past 10 years":
                self.pubdate_slider.value = (
                    datetime.now().year - 10,
                    datetime.now().year,
                )

        self.last_year_button.on_click(did_click_shortcut_button)
        self.past_5years_button.on_click(did_click_shortcut_button)
        self.past_10years_button.on_click(did_click_shortcut_button)

    def new_picker_title(self, entity, picker, values, options):
        value_count = len(picker.value)
        options_count = len(picker.options)

        if value_count == options_count:
            title = f"All {entity} ({ value_count })"

        elif value_count == 0:
            title = f"No {entity} (0 out of { options_count })"

        else:
            title = f"{ value_count } {entity} out of { options_count }"

        return title

    def get_sidebar(self):
        print("GET_SIDEBAR")

        items = [
            pn.pane.Markdown("## Filters"),
            pn.pane.Markdown("### Applied Filters"),
            pn.pane.Markdown("(todo)"),
            pn.layout.Divider(),
            pn.pane.Markdown(
                "### Publication Details", css_classes=["filters-section-header"]
            ),
            pn.Column(
                pn.Row(self.start_pubdate_input, self.end_pubdate_input),
                self.pubdate_slider,
                pn.Row(
                    self.last_year_button,
                    self.past_5years_button,
                    self.past_10years_button,
                ),
            ),
            pn.layout.Divider(),
            self.journal_select_picker,
            self.affiliation_country_select_picker,
        ]

        sidebar = pn.Column(*items)

        return sidebar

    def get_top_bar(self):
        print("GET_TOP_BAR")

        return pn.Row(
            pn.widgets.Select.from_param(self.param.extraction_tool),
            pn.widgets.Select.from_param(self.param.metrics),
            pn.widgets.Select.from_param(self.param.splitting_var),
        )

    def get_intro_block(self):
        explore_data_button = pn.widgets.Button(
            name="EXPLORE THE DATA", width=180, button_style="solid"
        )

        learn_more_button = pn.widgets.Button(
            name="LEARN MORE",
            width=180,
            button_style="solid",
            button_type="light",
        )
        github_button = pn.widgets.Button(
            name="GITHUB",
            width=180,
            button_style="solid",
            button_type="light",
        )

        return pn.Column(
            pn.pane.Markdown("#OpenSciMetrics Dashboard"),
            pn.pane.Markdown(
                "OpenSciMetrics is a tool designed to evaluate open science practices in biomedical publications, such as data sharing, code availability, and research transparency. Our goal is to provide insights into how these practices evolve over time and across different fields, journals, and countries. Use the dashboard below to explore key metrics and trends."
            ),
            pn.Row(explore_data_button, learn_more_button, github_button),
        )

    def get_dashboard(self):
        print("GET_DASHBOARD")

        # Layout the dashboard
        dashboard = pn.Column(
            "# Data and code transparency",
            pn.Column(
                self.get_top_bar(), self.echarts_pane, sizing_mode="stretch_width"
            ),
        )

        return dashboard
