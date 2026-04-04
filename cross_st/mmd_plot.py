import os
import sys
from dotenv import load_dotenv
from discourse import get_discourse_site, MmdDiscourseClient

# Define specific plots, in a single place
evaluator_v_target = "evaluator_v_target"
bar_score_evaluator = "bar_score_evaluator"
bar_score_target = "bar_score_target"

# Define plot types with descriptions
p_type = {
    "all": "All plots",
    "counts_v_score": "Correlation heatmap (Counts vs Score)",
    evaluator_v_target: "Heatmap of scores (Evaluator vs Target)",
    bar_score_evaluator: "Bar plot average scores by evaluator",
    bar_score_target: "Bar plot average scores by target",
    "outlier_detection": "Z-scores to detect outliers in scores",
    "pivot_table": "Pivot table of scores (Evaluator vs Target)",
}
p_choice = list(p_type.keys())


def get_plot_list():
    """
    Return plot list, list of keys and key: description.
    list [ 0 ] is 'all' to get all plots.
    :return: plot list, list of keys and key: description
    """
    return p_choice, p_type


def get_analysis_plot_types():
    return evaluator_v_target, bar_score_evaluator, bar_score_target


def tag_mapper(tag_kv, url_kv):
    """
    Return a mapping of markdown tags to plot URLs.

    Args:
        tag_kv (dict): Mapping of markdown_tag: plot_type
        url_kv (dict): Mapping of plot_type: plot_url

    Returns:
        dict: Mapping of markdown_tag: plot_url
    """
    tag_url = {}
    for tag, plot_type in tag_kv.items():
        tag_url[tag] = url_kv.get(plot_type, "key not found")
    return tag_url


def post_plot(site_slug, file_kv, verbose=True):
    """
    Post a collection of files to Discourse and return the list of upload urls
    in kv form.
    :param site_slug:
    :param file_kv:
    :return: upload_kv (k is the plot_type, v =s the url)
    """

    # Use realpath to get the actual path of the script
    _basedir  = os.path.dirname(os.path.realpath(__file__))
    _CROSSENV = os.path.expanduser("~/.crossenv")
    load_dotenv(_CROSSENV)                                    # 1. global ~/.crossenv
    load_dotenv(os.path.join(_basedir, ".env"))               # 2. repo-local .env (developer keys)
    load_dotenv(".env", override=True)                        # 3. CWD .env overrides both

    from discourse import get_discourse_slugs_sites
    _, sites = get_discourse_slugs_sites()

    # get the specific discourse site data
    site = get_discourse_site(site_slug, sites)

    # Initialize the client
    base_url = site["url"]
    client = MmdDiscourseClient(
        base_url,
        api_username=site["username"],
        api_key=site["api_key"],
    )

    upload_kv = {}
    for plot, file_path in file_kv.items():
        print(f"Uploading file: {file_path}", end=" ")
        upload_resp = client.upload_file(file_path)
        print(f"... complete")
        file_url = upload_resp["url"]
        upload_kv[plot] = file_url

    return upload_kv


def show_plot(fig=None):
    """Display a matplotlib figure with graceful keyboard/interrupt handling.

    - Prints a one-line hint telling the user how to close the window.
    - Escape or Q closes the chart window cleanly.
    - Ctrl+C is caught and handled without printing a traceback.

    Args:
        fig: matplotlib Figure to display.  If None, uses plt.gcf().
    """
    import matplotlib.pyplot as plt

    if fig is None:
        fig = plt.gcf()

    def _on_key(event):
        if event.key in ("escape", "q", "Q"):
            plt.close(fig)

    fig.canvas.mpl_connect("key_press_event", _on_key)
    print("  [Press Q or Esc to close the chart]", flush=True)
    try:
        plt.show()
    except KeyboardInterrupt:
        print()   # clean newline after ^C
        plt.close(fig)

