import math
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
import pandas as pd

def safe_log2(x):
    return -math.log2(x) if x > 0 else 0

def neg_xlog2(x):
    out = np.zeros_like(x, dtype=float)
    mask = x > 0
    out[mask] = -x[mask] * np.log2(x[mask])
    return out

def compute_gain_generic(p_no, p_d):
    return p_no * p_d * safe_log2(p_d)

def generate_p_i_values(n, total_mass, shape_parameter):
    if shape_parameter <= 0:
        raise ValueError("For 'zipf', shape_parameter must be > 0.")
    ranks = np.arange(1, n + 1)
    values = 1 / np.power(ranks, shape_parameter)

    values = values / values.sum()
    values = values * total_mass
    return values

def simulate_one(row, outside_p, outside_concepts):
    n = int(row["n"])
    p_d = float(row["p_d"])
    p_g = float(row["p_g"])
    shape_parameter = float(row["shape_parameter"])
    p_no = float(row["p_no"])
    lexicon_size = int(row["lexicon_size"])

    if not (0 <= p_g <= p_d <= 1):
        raise ValueError("Require 0 <= p_g <= p_d <= 1.")
    if not (0 <= p_no <= 1):
        raise ValueError("Require 0 <= p_no <= 1.")
    if n < 1:
        raise ValueError("n must be at least 1.")
    if lexicon_size < 1:
        raise ValueError("lexicon_size must be at least 1.")

    # Focus-domain probabilities.
    sum_p_i = p_d - p_g
    p_i_values = generate_p_i_values(
        n=n,
        total_mass=sum_p_i,
        shape_parameter=shape_parameter
    )

    # Build arrays for all concepts.
    main_concepts = np.array([f"specific_{k}" for k in range(1, n + 1)] + ["generic"], dtype=object)
    main_types = np.array(["specific"] * n + ["generic"], dtype=object)
    main_p = np.concatenate([p_i_values, np.array([p_g], dtype=float)])

    scaled_outside_p = outside_p * (1 - p_d)
    outside_types = np.full(outside_concepts.shape[0], "other", dtype=object)

    concept = np.concatenate([main_concepts, outside_concepts])
    ctype = np.concatenate([main_types, outside_types])
    p = np.concatenate([main_p, scaled_outside_p])

    total_concepts = concept.shape[0]
    label_cutoff = min(lexicon_size, total_concepts)

    is_specific = ctype == "specific"
    is_generic = ctype == "generic"
    is_other = ctype == "other"

    specific_idx = np.flatnonzero(is_specific)
    generic_idx = np.flatnonzero(is_generic)[0]
    other_idx = np.flatnonzero(is_other)

    specific_p = p[specific_idx]
    if p_d > 0:
        ratio = specific_p / p_d
        neg_log_ratio = np.where(ratio > 0, -np.log2(ratio), 0.0)
        specific_gain_base = (
            p_no * neg_xlog2(specific_p)
            + (1 - p_no) * specific_p * neg_log_ratio
        )
        specific_gain_updated = specific_p * neg_log_ratio
    else:
        specific_gain_base = np.zeros_like(specific_p, dtype=float)
        specific_gain_updated = np.zeros_like(specific_p, dtype=float)

    other_gain = neg_xlog2(p[other_idx])
    generic_base_gain = compute_gain_generic(p_no=p_no, p_d=p_d)
    generic_log_factor = safe_log2(p_d)

    gain = np.full(total_concepts, np.nan, dtype=float)
    rank = np.zeros(total_concepts, dtype=int)
    selected = np.zeros(total_concepts, dtype=bool)
    labeled = np.zeros(total_concepts, dtype=bool)

    specific_updated = False
    generic_updated = False
    labeled_specific_mass = 0.0

    for step in range(1, total_concepts + 1):
        unselected = ~selected

        unselected_specific_idx = specific_idx[unselected[specific_idx]]
        if unselected_specific_idx.size > 0:
            if specific_updated:
                gain[unselected_specific_idx] = specific_gain_updated[unselected[specific_idx]]
            else:
                gain[unselected_specific_idx] = specific_gain_base[unselected[specific_idx]]

        unselected_other_idx = other_idx[unselected[other_idx]]
        if unselected_other_idx.size > 0:
            gain[unselected_other_idx] = other_gain[unselected[other_idx]]

        if unselected[generic_idx]:
            if generic_updated:
                gain[generic_idx] = p_no * (p_d - labeled_specific_mass) * generic_log_factor
            else:
                gain[generic_idx] = generic_base_gain

        candidates = np.flatnonzero(unselected)
        winner_idx = candidates[np.argmax(gain[candidates])]

        selected[winner_idx] = True
        rank[winner_idx] = step

        if step <= label_cutoff:
            labeled[winner_idx] = True
            if ctype[winner_idx] == "specific":
                labeled_specific_mass += p[winner_idx]

        if ctype[winner_idx] == "generic":
            specific_updated = True
        elif ctype[winner_idx] == "specific":
            generic_updated = True

    labeled_specific = labeled & is_specific
    labeled_focus = labeled & (is_specific | is_generic)
    generic_labeled = bool(labeled[generic_idx])
    m = int(labeled_specific.sum())
    generic_status = "present" if generic_labeled else "absent"

    if generic_labeled and m > 0:
        generic_rank = int(rank[generic_idx])
        labeled_specific_best_rank = int(rank[specific_idx[labeled[specific_idx]]].min())
        if generic_rank < labeled_specific_best_rank:
            generic_emergence = "early"
        elif generic_rank == labeled_specific_best_rank:
            generic_emergence = "equal"
        else:
            generic_emergence = "late"
    elif generic_labeled and m == 0:
        generic_emergence = "early"
    elif not generic_labeled and m > 0:
        generic_emergence = "late"
    else:
        generic_emergence = "none"

    if generic_status == "present":
        if m > 0:
            type_level = "two level"
        else:
            type_level = "generic only"
    else:
        if m > 0:
            type_level = "specific only"
        else:
            type_level = "none"

    return {
        "n": n,
        "p_d": p_d,
        "p_g": p_g,
        "shape_parameter": shape_parameter,
        "p_no": p_no,
        "lexicon_size": lexicon_size,
        "m": m,
        "generic": generic_status,
        "emergence": generic_emergence,
        "type": type_level,
    }


def generate_parameter_samples(num_samples, seed, n_range, p_d_range,
                               shape_parameter_range, p_no_range):
    rng = np.random.default_rng(seed)

    rows = []
    for _ in range(num_samples):
        n = int(rng.integers(n_range[0], n_range[1] + 1))
        p_d = float(rng.uniform(p_d_range[0], p_d_range[1]))
        p_g = float(rng.uniform(0.0, p_d))
        p_no = float(rng.uniform(p_no_range[0], p_no_range[1]))
        shape_parameter = float(rng.uniform(shape_parameter_range[0], shape_parameter_range[1]))
        lexicon_size = int(rng.integers(1, n + 854 + 1))

        rows.append(
            {
                "n": n,
                "p_d": p_d,
                "p_g": p_g,
                "shape_parameter": shape_parameter,
                "p_no": p_no,
                "lexicon_size": lexicon_size,
            }
        )

    return rows

def run_distribution(config, workers, d_full, project_folder):
    outside_p = d_full["p"].to_numpy(dtype=float)
    outside_concepts = d_full["concept"].to_numpy(dtype=object)

    rows = generate_parameter_samples(
        num_samples=config["num_samples"],
        seed=config["seed"],
        n_range=config["n_range"],
        p_d_range=config["p_d_range"],
        shape_parameter_range=config["shape_parameter_range"],
        p_no_range=config["p_no_range"],
    )

    results = []
    total = len(rows)
    print(f"Running {total} simulations with {workers} workers...")

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(simulate_one, row, outside_p, outside_concepts)
            for row in rows
        ]
        completed = 0
        for future in as_completed(futures):
            results.append(future.result())
            completed += 1
            if completed % 1000 == 0 or completed == total:
                print(f"Completed {completed}/{total}")

    result_df = pd.DataFrame(results)
    output_path = os.path.join(project_folder, "output", "results", config["output_filename"])
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    result_df.to_csv(output_path, index=False)
    print(f"Saved: {output_path}")


WORKERS = max(1, (os.cpu_count() or 2) - 1)

CONFIGS = [
    {
        "output_filename": "simulation_sequential.csv",
        "num_samples": 1000000,
        "seed": 123,
        "n_range": (1, 500),
        "p_d_range": (0.0, 0.30),
        "shape_parameter_range": (0.0, 10.0),
        "p_no_range": (0.0, 1.0),
    },
]


def main():
    project_folder = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(project_folder, "data", "d_full.csv")

    d_full = pd.read_csv(file_path, encoding="utf-8")
    d_full["freq"] = d_full[["wl_mean", "do_mean"]].mean(axis=1)
    d_full["p"] = d_full["freq"] / d_full["freq"].sum()
    d_full = d_full.rename(columns={"concepticon_gloss": "concept"})[["concept", "p"]]

    for config in CONFIGS:
        print(f"\n=== Running: {config['output_filename']} ===")
        run_distribution(
            config=config,
            workers=WORKERS,
            d_full=d_full,
            project_folder=project_folder,
        )


if __name__ == "__main__":
    main()
