"""egen. Each function below is one that an open-list author's log shows (HNPXO1 doi:10.7910/DVN/HNPXO1 and 27102
doi:10.7910/DVN/27102, retrieved 2026-11-24). Each test pins a behaviour those logs show (which message line is
printed, which storage type results); the data, names and counts here are our own. The comparison with the authors'
output is the harness case dv-HNPXO1-09_final_data_management, which fetches their files. Functions no log shows must
raise Unsupported."""
import io
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "engine"))

from ose import commands  # noqa: E402,F401
from ose import missing as M  # noqa: E402
from ose.dataset import Dataset, Variable  # noqa: E402
from ose.errors import StataError, Unsupported  # noqa: E402
from ose.interp import Interp  # noqa: E402

MISS = M.SYSMISS


def mk(cols, types=None):
    out = io.StringIO()
    it = Interp(out=out)
    vs = []
    for name, vals in cols:
        if len(vals) and isinstance(vals[0], str):
            vs.append(Variable(name, "str8", np.array(vals, dtype=object)))
        else:
            vs.append(Variable(name, (types or {}).get(name, "double"), np.array(vals, dtype=np.float64)))
    it.ds = Dataset(vs)
    return it, out


def col(it, name):
    return list(it.ds.find(name).data)


def sortby(it, *names):
    it.ds.sort(list(names))


# --- mean, sd, total/sum, min, max ------------------------------------------------------

def test_mean_by_option_all_missing_group_is_missing_and_counted():
    # Witnessed in HNPXO1 06_citydev: mean() with by(), where whole groups are missing, prints the count line.
    it, out = mk([("g", [2, 1, 2, 3, 1, 3]), ("x", [4, 1, 6, MISS, 3, MISS])])
    it.dispatch("egen m = mean(x), by(g)")
    assert col(it, "m") == [5.0, 2.0, 5.0, MISS, 2.0, MISS]
    assert out.getvalue() == "(2 missing values generated)\n"
    assert it.ds.find("m").type == "float"
    assert it.ds.names() == ["g", "x", "m"]


def test_mean_by_prefix_and_by_option_agree():
    # Witnessed in HNPXO1 07_govreport: mean() under a bysort prefix.
    it, out = mk([("city", [1, 1, 2, 2, 2]), ("t", [1, 2, 3, 4, 8])])
    it.dispatch("bysort city: egen a = mean(t)")
    it.dispatch("egen b = mean(t), by(city)")
    assert col(it, "a") == col(it, "b") == [1.5, 1.5, 5.0, 5.0, 5.0]
    assert out.getvalue() == ""


def test_by_prefix_unsorted_is_error_5():
    it, _ = mk([("g", [2, 1]), ("x", [1, 2])])
    with pytest.raises(StataError) as e:
        it.dispatch("by g: egen m = mean(x)")
    assert e.value.rc == 5


def test_by_prefix_with_by_option_is_error_190():
    it, _ = mk([("g", [1, 1]), ("x", [1, 2])])
    with pytest.raises(StataError) as e:
        it.dispatch("by g: egen m = mean(x), by(g)")
    assert e.value.rc == 190


def test_mean_without_by_is_a_constant_and_float_storage_rounds():
    it, _ = mk([("x", [0.1, 0.2, 0.4])])
    it.dispatch("egen m = mean(x)")
    want = float(np.float32((0.1 + 0.2 + 0.4) / 3))
    assert col(it, "m") == [want] * 3
    it.dispatch("egen double d = mean(x)")
    assert col(it, "d") == [(0.1 + 0.2 + 0.4) / 3] * 3
    assert it.ds.find("d").type == "double"


def test_sd_sample_n_minus_1_and_single_obs_group_missing():
    # Witnessed in HNPXO1 07_govreport: sd() under a bysort prefix, later tested for zero and for missing.
    it, out = mk([("g", [1, 1, 1, 2, 3, 3]), ("x", [1, 2, 3, 5, 4, 4])])
    it.dispatch("bysort g: egen s = sd(x)")
    assert col(it, "s") == [1.0, 1.0, 1.0, MISS, 0.0, 0.0]
    assert out.getvalue() == "(1 missing value generated)\n"


def test_total_and_sum_missing_counted_as_zero():
    # Witnessed in 27102 (total() with by()) and HNPXO1 08_green_patent (sum() with a two-variable by()).
    it, out = mk([("g", [1, 1, 2, 2, 3]), ("x", [1, 2, MISS, MISS, 5])])
    it.dispatch("egen t = total(x), by(g)")
    it.dispatch("egen s = sum(x), by(g)")
    assert col(it, "t") == col(it, "s") == [3.0, 3.0, 0.0, 0.0, 5.0]
    assert out.getvalue() == ""


def test_total_of_an_expression_without_by():
    # Witnessed in 27102: total() of a logical expression, no by().
    it, out = mk([("u", [1, 1, 0, 1]), ("v", [0, 1, 0, 0])])
    it.dispatch("egen n_uv = total(u==1 & v==0)")
    assert col(it, "n_uv") == [2.0] * 4
    assert out.getvalue() == ""


def test_min_max_by_prefix_and_option_ignore_missing():
    # Witnessed in HNPXO1 09_final_data_management (min() under bysort) and 27102 (max() with a two-variable by()).
    it, out = mk([("a", [1, 1, 1, 2, 2]), ("b", [1, 1, 2, 1, 1]), ("x", [3, MISS, 7, MISS, MISS])])
    it.dispatch("egen hi = max(x), by(a b)")
    it.dispatch("egen lo = min(x), by(a b)")
    assert col(it, "hi") == [3.0, 3.0, 7.0, MISS, MISS]
    assert col(it, "lo") == col(it, "hi")
    assert out.getvalue() == "(2 missing values generated)\n(2 missing values generated)\n"
    it2, _ = mk([("id", [1, 1, 2]), ("cc", [4, 4, 9])])
    it2.dispatch("bysort id: egen mn = min(cc)")
    it2.dispatch("bysort id: egen mx = max(cc)")
    assert col(it2, "mn") == col(it2, "mx") == [4.0, 4.0, 9.0]


def test_if_and_in_limit_the_sample_and_leave_other_rows_missing():
    it, out = mk([("g", [1, 1, 1, 1]), ("x", [1, 2, 30, 40])])
    it.dispatch("egen m = mean(x) if x < 10, by(g)")
    assert col(it, "m") == [1.5, 1.5, MISS, MISS]
    assert out.getvalue() == "(2 missing values generated)\n"
    it.dispatch("egen n = max(x) in 2/3")
    assert col(it, "n") == [MISS, 30.0, 30.0, MISS]


# --- median and pctile ---------------------------------------------------------------------

def test_median_even_and_odd_counts():
    # Witnessed in 27102: median() with no by() and no message line.
    it, out = mk([("x", [10, 1, 9, 2, 8, 3, 7, 4, 6, 5])])
    it.dispatch("egen med = median(x)")
    assert col(it, "med") == [5.5] * 10
    it2, _ = mk([("x", [3, 1, MISS, 2])])
    it2.dispatch("egen med = median(x)")
    assert col(it2, "med") == [2.0] * 4
    assert out.getvalue() == ""


def test_pctile_rule_whole_and_fractional_positions():
    # x = 1..10: p10 -> P=1 (mean of x1,x2); p25 -> P=2.5 (x3); p50 -> 5.5; p90 -> P=9 (mean of x9,x10)
    it, _ = mk([("x", list(range(10, 0, -1)))])
    for p, want in ((10, 1.5), (25, 3.0), (50, 5.5), (90, 9.5), (99, 10.0)):
        it.dispatch(f"egen p{p} = pctile(x), p({p})")
        assert col(it, f"p{p}") == [want] * 10, p


def test_pctile_by_option_per_group_and_default_is_median():
    # Witnessed in 27102: pctile() with p() and a three-variable by() inside a loop.
    it, out = mk([("g", [1, 1, 1, 1, 2, 2, 2]), ("x", [4, 1, 3, 2, 9, MISS, 5])])
    it.dispatch("egen p50 = pctile(x), by(g)")
    assert col(it, "p50") == [2.5] * 4 + [7.0] * 3
    it.dispatch("egen p75 = pctile(x), p(75) by(g)")
    assert col(it, "p75") == [3.5] * 4 + [9.0] * 3
    assert out.getvalue() == ""


def test_pctile_all_missing_group_is_missing():
    it, out = mk([("g", [1, 2]), ("x", [1, MISS])])
    it.dispatch("egen p = pctile(x), p(50) by(g)")
    assert col(it, "p") == [1.0, MISS]
    assert out.getvalue() == "(1 missing value generated)\n"


def test_pctile_rejects_p_the_logs_do_not_show():
    it, _ = mk([("x", [1, 2, 3])])
    for bad in ("p(0)", "p(100)", "p(2.5)"):
        with pytest.raises(Unsupported):
            it.dispatch(f"egen q = pctile(x), {bad}")
    assert not it.ds.has("q")


# --- group and tag -------------------------------------------------------------------------

def test_group_numbers_combinations_in_sort_order_and_is_float():
    # Witnessed in HNPXO1 09_final_data_management: group() of two variables is stored as float, and a later
    # compress demotes it.
    it, out = mk([("a", [2, 1, 2, 1, 2]), ("y", [5, 7, 5, 5, 6])])
    it.dispatch("egen gy = group(a y)")
    assert col(it, "gy") == [3.0, 2.0, 3.0, 1.0, 4.0]
    assert it.ds.find("gy").type == "float"
    assert out.getvalue() == ""
    it.dispatch("compress")
    assert "variable gy was float now byte" in out.getvalue()


def test_group_missing_in_any_variable_is_missing_and_counted():
    # Witnessed in HNPXO1 09_final_data_management: group() with missing keys prints the count line.
    it, out = mk([("a", [1, MISS, 2, 2]), ("y", [1, 1, MISS, 1])])
    it.dispatch("egen g = group(a y)")
    assert col(it, "g") == [1.0, MISS, MISS, 2.0]
    assert out.getvalue() == "(2 missing values generated)\n"


def test_group_on_strings_sorts_by_code_point_and_blank_is_missing():
    it, out = mk([("s", ["b", "a", "", "b"]), ("y", [1, 1, 1, 1])])
    it.dispatch("egen g = group(s y)")
    assert col(it, "g") == [2.0, 1.0, MISS, 2.0]
    assert out.getvalue() == "(1 missing value generated)\n"


def test_group_with_if_leaves_others_missing_and_numbers_the_sample_only():
    it, out = mk([("a", [3, 1, 2, 1])])
    it.dispatch("egen g = group(a) if a != 1")
    assert col(it, "g") == [2.0, MISS, 1.0, MISS]


def test_tag_marks_first_per_group_and_if_rows_are_zero_not_missing():
    # Witnessed in HNPXO1 06_citydev: tag() with an if condition prints no count line, so the rows outside the
    # condition hold 0, not missing.
    it, out = mk([("c", [2, 2, 1, 1, 3]), ("ok", [1, 1, 1, 1, 0])])
    it.dispatch("egen t = tag(c) if ok == 1")
    assert col(it, "t") == [1.0, 0.0, 1.0, 0.0, 0.0]
    assert out.getvalue() == ""
    assert it.ds.find("t").type == "byte"


def test_tag_missing_key_is_zero():
    it, out = mk([("c", [1, MISS, MISS, 1])])
    it.dispatch("egen t = tag(c)")
    assert col(it, "t") == [1.0, 0.0, 0.0, 0.0]
    assert out.getvalue() == ""


def test_group_and_tag_with_by_are_unsupported():
    it, _ = mk([("c", [1, 1])])
    with pytest.raises(Unsupported):
        it.dispatch("egen t = tag(c), by(c)")
    with pytest.raises(Unsupported):
        it.dispatch("bysort c: egen t = group(c)")


# --- rowtotal -----------------------------------------------------------------------------

def test_rowtotal_range_with_space_around_dash_and_missing_as_zero():
    # Witnessed in 27102: rowtotal() over a range written with a space after the dash; a later division by the
    # total reports only its own missing values, so rowtotal itself never returns missing.
    it, out = mk([("q_a", [1, MISS, 2]), ("q_b", [2, MISS, MISS]), ("q_g", [3, MISS, 4]), ("other", [9, 9, 9])])
    it.dispatch("egen w = rowtotal(q_a- q_g)")
    assert col(it, "w") == [6.0, 0.0, 6.0]
    assert out.getvalue() == ""


def test_rowtotal_wildcard_and_double_type():
    # Witnessed in HNPXO1 07_govreport (rowtotal() over a wildcard) and 00_main (an egen double result).
    it, _ = mk([("tf_1", [0.1, 1]), ("tf_2", [0.2, MISS]), ("zz", [5, 5])])
    it.dispatch("egen double w = rowtotal(tf_*)")
    assert col(it, "w") == [0.1 + 0.2, 1.0]
    assert it.ds.find("w").type == "double"


def test_rowtotal_string_variable_is_type_mismatch():
    it, _ = mk([("s", ["a", "b"]), ("x", [1, 2])])
    with pytest.raises(StataError) as e:
        it.dispatch("egen w = rowtotal(s x)")
    assert e.value.rc == 109


# --- errors and the unsupported surface ---------------------------------------------------

@pytest.mark.parametrize("fcn", ["count(x)", "rank(x)", "rowmean(x y)", "rowmax(x y)", "rowmin(x y)",
                                 "rownonmiss(x y)", "rowmiss(x y)", "concat(x y)", "seq()", "cut(x), at(1,2)",
                                 "std(x)", "mode(x)", "nvals(x)", "iqr(x)"])
def test_functions_no_log_shows_are_unsupported_and_create_nothing(fcn):
    it, out = mk([("x", [1, 2, 3]), ("y", [3, 2, 1])])
    with pytest.raises(Unsupported):
        it.dispatch(f"egen z = {fcn}")
    assert not it.ds.has("z") and out.getvalue() == ""


@pytest.mark.parametrize("line", ["egen z = group(x), missing", "egen z = group(x), label",
                                  "egen z = rowtotal(x y), missing", "egen z = total(x), missing",
                                  "egen z = mean(x), truncate(1)"])
def test_options_no_log_shows_are_refused(line):
    it, _ = mk([("x", [1, 2, 3]), ("y", [3, 2, 1])])
    with pytest.raises(Unsupported):
        it.dispatch(line)
    assert not it.ds.has("z")


def test_unbuilt_option_under_capture_still_stops_the_run():
    it, _ = mk([("x", [1, 2, 3])])
    with pytest.raises(Unsupported):
        it.dispatch("capture egen z = group(x), missing")


def test_existing_name_is_error_110_and_invalid_name_198():
    it, _ = mk([("x", [1, 2])])
    with pytest.raises(StataError) as e:
        it.dispatch("egen x = mean(x)")
    assert e.value.rc == 110
    with pytest.raises(StataError) as e:
        it.dispatch("egen 1x = mean(x)")
    assert e.value.rc == 198


def test_string_storage_type_is_unsupported():
    it, _ = mk([("x", [1, 2])])
    with pytest.raises(Unsupported):
        it.dispatch("egen str5 z = mean(x)")


def test_numeric_function_of_a_string_expression_is_type_mismatch():
    it, _ = mk([("s", ["a", "b"])])
    with pytest.raises(StataError) as e:
        it.dispatch("egen z = mean(s)")
    assert e.value.rc == 109


def test_integer_storage_type_out_of_range_is_refused():
    it, _ = mk([("x", [500.0, 700.0])])
    with pytest.raises(Unsupported):
        it.dispatch("egen byte z = mean(x)")
    assert not it.ds.has("z")
