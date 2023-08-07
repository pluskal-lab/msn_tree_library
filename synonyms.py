import logging
import re
import ast

import pandas as pd

import pandas_utils
from pandas_utils import get_or_else, get_unique_list, notnull, isnull


def ensure_synonyms_column(df: pd.DataFrame) -> pd.DataFrame:
    df["synonyms"] = df.apply(lambda row: get_all_synonyms(row), axis=1)
    return df


def get_all_synonyms(row):
    synonyms = [
        get_or_else(row, "cas"),
        get_or_else(row, "compound_name"),
        get_or_else(row, "input_name"),
    ]

    old = row["synonyms"] if "synonyms" in row else None
    try:
        if isinstance(old, str):
            try:
                list_from_str = ast.literal_eval(old)
                synonyms += list_from_str
            except:
                synonyms.append(old)
        elif notnull(old):
            synonyms = synonyms + old
    except:
        logging.exception("Cannot concat synonyms")

    synonyms = [x.strip() for x in synonyms if x]
    return get_unique_list(synonyms)


def add_synonyms(old_synonyms, new_synonyms, prepend: bool = True) -> list:
    if isnull(old_synonyms):
        old_synonyms = []
    if isnull(new_synonyms):
        new_synonyms = []
    all = new_synonyms + old_synonyms if prepend else old_synonyms + new_synonyms
    return get_unique_list(all)


def find_unii(synonyms):
    unii_generator = (re.sub('[ .;:\-]|UNII', '', name.upper()) for name in synonyms if "UNII" in name.upper())
    return next(unii_generator, None)


def find_schembl(synonyms):
    schembl_generator = (name.upper() for name in synonyms if name.upper().startswith("SCHEMBL"))
    return next(schembl_generator, None)


def find_chembl_id(synonyms):
    chembl_generator = (name.upper() for name in synonyms if name.upper().startswith("CHEMBL"))
    return next(chembl_generator, None)


def find_zinc(synonyms):
    zinc_generator = (name.upper() for name in synonyms if name.upper().startswith("ZINC"))
    return next(zinc_generator, None)


def find_drugbank(synonyms):
    for s in synonyms:
        drug = cleanup_drugbank_id(s)
        if drug:
            return drug
    return None
    # drugbank_generator = (cleanup_drugbank_id(name) for name in synonyms)
    # return next((db_id for db_id in drugbank_generator if db_id), None)


def cleanup_drugbank_id(input):
    pattern = "^DB.*\d"
    anti_pattern = "[ACE-Z]"
    input = input.upper()
    if re.search(pattern, input) and not re.search(anti_pattern, input):
        return re.sub("[^0-9DB]", "", input)
    else:
        return None


def extract_synonym_ids(df: pd.DataFrame) -> pd.DataFrame:
    source = pd.DataFrame()
    source["unii"] = [find_unii(synonyms) for synonyms in df["synonyms"]]
    source["schembl_id"] = [find_schembl(synonyms) for synonyms in df["synonyms"]]
    source["chembl_id"] = [find_chembl_id(synonyms) for synonyms in df["synonyms"]]
    source["zinc_id"] = [find_zinc(synonyms) for synonyms in df["synonyms"]]
    source["drugbank_id"] = [find_drugbank(synonyms) for synonyms in df["synonyms"]]

    return pandas_utils.combine_dfs_fill_missing_values(df, source)
