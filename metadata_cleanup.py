import numpy as np
import pandas as pd
from datetime import date
import re

from molmass import Formula
from rdkit.Chem import Descriptors
from rdkit.Chem import AllChem as Chem
from rdkit.Chem.MolStandardize import rdMolStandardize
from pathlib import Path
import logging
import mol_identifiers as molid
import database_client as client
from database_client import pubchem_get_synonyms
import drugcentral_postgresql_query as drugcentral_query

from tqdm import tqdm

tqdm.pandas()
logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.DEBUG)

# CONSTANTS
unique_sample_id_header = "unique_sample_id"


def add_suffix(filename, suffix):
    p = Path(filename)
    return "{0}_{1}{2}".format(Path.joinpath(p.parent, p.stem), suffix, p.suffix)


def ensure_synonyms_column(df: pd.DataFrame) -> pd.DataFrame:
    df["synonyms"] = df.apply(lambda row: get_all_synonyms(row), axis=1)
    return df


def get_all_synonyms(row):
    synonyms = [
        get_or_else(row, "Product Name"),
        get_or_else(row, "CAS No."),
        get_or_else(row, "CAS"),
    ]

    old = row["synonyms"] if "synonyms" in row else None
    try:
        if isinstance(old, str):
            synonyms.append(old)
        elif old is not None:
            synonyms = synonyms + old
    except:
        logging.exception("Cannot concat synonyms")

    synonyms.extend([s.strip() for s in str(get_or_else(row, "Synonyms", "")).split(";")])

    synonyms = [x.strip() for x in synonyms if x]
    seen = set()
    unique = [x for x in synonyms if x.lower() not in seen and not seen.add(x.lower())]
    return unique


def get_or_else(row, key, default=None):
    return row[key] if key in row and pd.notnull(row[key]) else default


# query braod list
def map_clinical_phase_to_number(phase):
    match (str(phase)):
        case "" | "None" | "NaN" | "nan" | "np.nan" | "0" | "No Development Reported":
            return 0
        case "Preclinical":
            return 0.5
        case "1" | "1.0" | "Phase 1":
            return 1
        case "2" | "2.0" | "Phase 2":
            return 2
        case "3" | "3.0" | "Phase 3":
            return 3
        case "4" | "4.0" | "Phase 4" | "Launched":
            return 4
        case _:
            return phase


def get_clinical_phase_description(number):
    match (str(number)):
        case "" | "None" | "NaN" | "nan" | "np.nan" | "0" | "0.0":
            return ""
        case "0.5":
            return "Preclinical"
        case "1.0" | "1":
            return "Phase 1"
        case "2.0" | "2":
            return "Phase 2"
        case "3.0" | "3":
            return "Phase 3"
        case "4.0" | "4":
            return "Launched"
        case _:
            return number


def map_drugbank_approval(status):
    match (str(status)):
        case "approved" | "withdrawn":
            return 4
        case _:
            return None


def broad_list_search(df):
    # download from: https://clue.io/repurposing#download-data
    prefix = "broad_"
    broad_df = pd.read_csv("data/broad_institute_drug_list.csv")
    broad_df = broad_df.add_prefix(prefix)

    if "split_inchi_key" not in df and "inchi_key" in df:
        df["split_inchi_key"] = [str(inchikey).split("-")[0] if pd.notnull(inchikey) else None for inchikey in
                                 df['inchi_key']]
    broad_df["split_inchi_key"] = [str(inchikey).split("-")[0] if pd.notnull(inchikey) else None for inchikey in
                                   broad_df["{}InChIKey".format(prefix)]]

    merged_df = pd.merge(df, broad_df, on="split_inchi_key", how="left")
    # converting the clinical phases (from broad institute, chembl, provider, or else) to numbers (remove phase,
    # preclinic (as 0.5), or launched)
    merged_df["broad_clinical_phase"] = [map_clinical_phase_to_number(phase) for phase in
                                         merged_df["broad_clinical_phase"]]
    merged_df["clinical_phase"] = [map_clinical_phase_to_number(phase) for phase in merged_df["clinical_phase"]]
    if "Clinical Information" in df.columns:
        merged_df["Clinical Information"] = [map_clinical_phase_to_number(phase) for phase in
                                             merged_df["Clinical Information"]]
    else:
        merged_df["Clinical Information"] = None

    # Comparing the clinical phases, only store the highest number in clinical phase column
    merged_df["clinical_phase"] = merged_df[['broad_clinical_phase', 'clinical_phase', 'Clinical Information']].max(
        axis=1)
    return merged_df.drop(["broad_clinical_phase", "Clinical Information", "{}InChIKey".format(prefix)], axis=1)


def find_in_drugbank(drugbank_df, row):
    if pd.notnull(row["drugbank_id"]):
        return row["drugbank_id"]

    dbid = None
    # pubchem id first, then CHEMBL, then synonyms
    if pd.notnull(row["inchi_key"]):
        dbid = next((d for d in drugbank_df[drugbank_df["inchi_key"] == row["inchi_key"]]["drugbank_id"]), None)
    if isnull(dbid) and not isnull(row["pubchem_cid_parent"]):
        dbid = next((d for d in drugbank_df[drugbank_df["pubchem_cid"] == row["pubchem_cid_parent"]]["drugbank_id"]),
                    None)
    if isnull(dbid) and pd.notnull(row["chembl_id"]):
        dbid = next((d for d in drugbank_df[drugbank_df["chembl_id"] == row["chembl_id"]]["drugbank_id"]), None)
    if isnull(dbid) and pd.notnull(row["unii"]):
        dbid = next((d for d in drugbank_df[drugbank_df["unii"] == row["unii"]]["drugbank_id"]), None)
    if isnull(dbid) and "CAS No." in row and pd.notnull(row["CAS No."]):
        dbid = next((d for d in drugbank_df[drugbank_df["cas"] == row["CAS No."]]["drugbank_id"]), None)
    if isnull(dbid) and pd.notnull(row["split_inchi_key"]):
        dbid = next((d for d in drugbank_df[drugbank_df["split_inchi_key"] == row["split_inchi_key"]]["drugbank_id"]),
                    None)
    # if pd.isnull(dbid) and row["synonyms"]:
    #     dbid = next((d for d in drugbank_df[drugbank_df["name"] in row["synonyms"]]["drugbank_id"]), None)
    return dbid


def isnull(o):
    return str(o) == '<NA>' or o == "N/A" or o == "NA" or o == None or pd.isnull(o)


def notnull(o):
    return not isnull(o)


def drugbank_list_search(df):
    # download from: https://go.drugbank.com/releases/latest, approved access needed, xml extraction to tsv by
    # drugbank_extraction.py
    prefix = "drugbank_"
    drugbank_df = pd.read_csv("data/drugbank.tsv", sep="\t")
    drugbank_df["pubchem_cid"] = pd.array(drugbank_df["pubchem_cid"], dtype=pd.Int64Dtype())

    if "split_inchi_key" not in df and "inchi_key" in df:
        df["split_inchi_key"] = [str(inchikey).split("-")[0] if pd.notnull(inchikey) else None for inchikey in
                                 df['inchi_key']]
    drugbank_df["split_inchi_key"] = [str(inchikey).split("-")[0] if pd.notnull(inchikey) else None for inchikey in
                                      drugbank_df["inchi_key"]]

    df["drugbank_id"] = None
    # find drugbank IDs in drugbank table by PubChem, ChEMBL etc
    df["drugbank_id"] = df.progress_apply(lambda row: find_in_drugbank(drugbank_df, row), axis=1)

    drugbank_df = drugbank_df.add_prefix(prefix)
    merged_df = pd.merge(df, drugbank_df, left_on="drugbank_id", right_on="drugbank_drugbank_id", how="left")
    merged_df["unii"].fillna(merged_df["{}unii".format(prefix)])
    merged_df["chembl_id"].fillna(merged_df["{}chembl_id".format(prefix)], inplace=True)
    merged_df["compound_name"].fillna(merged_df["{}name".format(prefix)], inplace=True)
    return merged_df.drop(["drugbank_drugbank_id", "{}inchi_key".format(prefix), "{}smiles".format(prefix),
                           "{}split_inchi_key".format(prefix)], axis=1)


def drugcentral_search(df):
    prefix = "drugcentral_"
    if "split_inchi_key" not in df and "inchi_key" in df:
        df["split_inchi_key"] = [str(inchikey).split("-")[0] if pd.notnull(inchikey) else None for inchikey in
                                 df['inchi_key']]
    try:
        drugcentral_query.connect()
        logging.info("Searching in DrugCentral")
        results = df.progress_apply(lambda row: drugcentral_query.drugcentral_for_row(row), axis=1)
        # results = [drugcentral_query.drugcentral_for_row(row) for _,row in df.iterrows()]
        # results = [drugcentral_query.drugcentral_postgresql(inchikey, split_inchikey) for inchikey, split_inchikey in
        #          tqdm(zip(df["inchi_key"], df["split_inchi_key"]))]
        logging.info("DrugCentral search done")

        # row[1] is the data row[0] is the columns
        first_entry_columns = next((row[0] for row in results if pd.notnull(row[0])), [])
        columns = [col.name for col in first_entry_columns]
        elements = len(columns)
        data = [row[1] if pd.notnull(row[1]) else (None,) * elements for row in results]
        dc_df = pd.DataFrame(data=data, columns=columns, index=df.index)
        dc_df = dc_df.add_prefix(prefix)
        return pd.concat([df, dc_df], axis=1)

    finally:
        drugcentral_query.deconnect()


def cleanup_file(metadata_file, lib_id, id_columns=['Product Name', 'lib_plate_well', "inchi_key"],
                 plate_id_header="plate_id", well_header="well_location", query_pubchem: bool = True,
                 calc_identifiers: bool = True, pubchem_search: bool = True,
                 query_chembl: bool = True, query_broad_list=False, query_drugbank_list=False, query_drugcentral=False):
    logging.info("Will run on %s", metadata_file)
    out_file = add_suffix(metadata_file, "cleaned")

    # import df
    if metadata_file.endswith(".tsv"):
        df = pd.read_csv(metadata_file, sep="\t")
    else:
        df = pd.read_csv(metadata_file, sep=",")

    ensure_synonyms_column(df)

    # creat unique_id
    create_unique_sample_id_column(df, lib_id, plate_id_header, well_header)

    # Query pubchem by name and CAS
    if query_pubchem:
        logging.info("Search PubChem by name")
        df = pubchem_search_structure_by_name(df)

    # get mol from smiles or inchi
    # calculate all identifiers from mol - exact_mass, ...
    if calc_identifiers:
        logging.info("RDkit - predict properties")
        add_molid_columns(df)
        add_molid_columns(df)  ## second time for removing salts, especially adducts previous [Na], now .Na
    # drop duplicates
    try:
        df = df.drop_duplicates(id_columns, keep="first").sort_index()
    except:
        pass

    # get PubChem information based on inchikey, smiles, Inchi
    if pubchem_search:
        logging.info("Search PubChem by structure")
        df = pubchem_search_by_structure(df)

    # extract ids like the UNII, ...
    df = ensure_synonyms_column(df)
    df = extract_synonym_ids(df)

    # get ChEMBL information based on inchikey
    if query_chembl:
        logging.info("Search ChEMBL by chemblid or inchikey")
        df = chembl_search(df)

    # get broad institute information based on split inchikey
    if query_broad_list:
        logging.info("Search broad institute list of drugs by first block of inchikey")
        df = broad_list_search(df)

        # get drugbank information based on split inchikey
    if query_drugbank_list:
        logging.info("Search drugbank list by inchikey, pubchem_id, chembl_id, cas, split inchikey, etc.")
        df = drugbank_list_search(df)
        if "drugbank_approved" in df.columns:
            df["drugbank_approved_number"] = [map_drugbank_approval(status) for status in df["drugbank_approved"]]
        else:
            df["drugbank_approved_number"] = None
        df["clinical_phase"] = df[
            ['clinical_phase', 'drugbank_approved_number']].max(axis=1)
        df["any_phase"] = df["drugbank_approved"].notna() | (df["clinical_phase"] > 0)

    if query_drugcentral:
        logging.info("Search drugcentral by external identifier or inchikey")
        df = drugcentral_search(df)
        if "drugcentral_administration" in df.columns:
            df["drugcentral_administration_number"] = [4 if pd.notnull(status) else None for status in
                                                       df["drugcentral_administration"]]
        else:
            df["drugcentral_administration_number"] = None
        df["clinical_phase"] = df[['clinical_phase', 'drugcentral_administration_number']].max(axis=1)
        if "drugbank_approved" in df.columns:
            df["any_phase"] = df["drugbank_approved"].notna() | (df["clinical_phase"] > 0)
        else:
            df["any_phase"] = df["clinical_phase"] > 0

    # Converting numbers back to phase X, launched or preclinic
    df["clinical_phase_description"] = [get_clinical_phase_description(number) for number in
                                        df["clinical_phase"]]
    # drop mol
    df = df.drop(columns=['mol', 'pubchem'])
    df["none"] = df.isnull().sum(axis=1)
    try:
        df = df.sort_values(by="none", ascending=True).drop_duplicates(
            ["Product Name", unique_id_header, "exact_mass"], keep="first").sort_index()
    except:
        pass

    # export metadata file
    logging.info("Exporting to file %s", out_file)
    if metadata_file.endswith(".tsv"):
        df.to_csv(out_file, sep="\t", index=False)
    else:
        df.to_csv(out_file, sep=",", index=False)


def create_unique_sample_id_column(df, lib_id, plate_id_header, well_header):
    """
    generates a column with unique sample IDs if column with well locations and plate IDs (optional) is available.
    :param df: metadata
    :param lib_id: library id that defines the compound library
    :param plate_id_header: number or name of the plate
    :param well_header: well location of the injection
    :return: lib_id_plate_well_id
    """
    try:
        if well_header in df.columns:
            if plate_id_header in df.columns:
                df[unique_sample_id_header] = ["{}_{}_{}_id".format(lib_id, plate, well) for plate, well in
                                               zip(df[plate_id_header], df[well_header])]
            else:
                df[unique_sample_id_header] = ["{}_{}_id".format(lib_id, well) for well in df[well_header]]
    except:
        logging.info(
            "No well location and plate id found to construct unique ID which is needed for library generation")
        pass


def get_rdkit_mol(smiles, inchi):
    mol = None
    try:
        mol = Chem.MolFromSmiles(smiles)
    except:
        pass
    if mol is None:
        try:
            mol = Chem.MolFromInchi(inchi)
        except:
            pass
    return mol


def add_molid_columns(df):
    if "inchi" not in df.columns:
        df["inchi"] = None
    # first strip any salts
    df["Smiles"] = [molid.split_smiles_major_mol(smiles) if pd.notnull(smiles) else np.NAN for smiles in df["Smiles"]]
    df["mol"] = [get_rdkit_mol(smiles, inchi) for smiles, inchi in zip(df["Smiles"], df["inchi"])]
    df["mol"] = [molid.chembl_standardize_mol(mol) if pd.notnull(mol) else np.NAN for mol in df["mol"]]
    df["canonical_smiles"] = [molid.mol_to_canon_smiles(mol) for mol in df["mol"]]
    df["Smiles"] = [molid.mol_to_isomeric_smiles(mol) for mol in df["mol"]]
    df["exact_mass"] = [molid.exact_mass_from_mol(mol) for mol in df["mol"]]
    df["inchi"] = [molid.inchi_from_mol(mol) for mol in df["mol"]]
    df["inchi_key"] = [molid.inchikey_from_mol(mol) for mol in df["mol"]]
    df["split_inchi_key"] = [str(inchikey).split("-")[0] for inchikey in df['inchi_key']]
    df["formula"] = [molid.formula_from_mol(mol) for mol in df["mol"]]
    return df


def pubchem_search_by_names(row):
    if notnull(row["pubchem"]):
        return row["pubchem"]

    compound = None
    if "pubchem_cid_parent" in row:
        compound = client.pubchem_by_cid(row["pubchem_cid_parent"])
    if isnull(compound) and "pubchem_cid" in row:
        compound = client.pubchem_by_cid(row["pubchem_cid"])
    if isnull(compound):
        compound = client.search_pubchem_by_structure(inchikey=row["inchi_key"], smiles=row["Smiles"],
                                                      inchi=row["inchi"])
    if isnull(compound) and "compound_name" in row and notnull(row["compound_name"]):
        compound = client.search_pubchem_by_name(str(row["compound_name"]))
    if isnull(compound) and "CAS No." in row and notnull(row["CAS No."]):
        compound = client.search_pubchem_by_name(row["CAS No."])
    if isnull(compound) and "Product Name" in row:
        compound = client.search_pubchem_by_name(row["Product Name"])
    # only one compound was found as CAS-
    if isnull(compound) and "CAS No." in row:
        compound = client.search_pubchem_by_name("CAS-{}".format(row["Product Name"]))

    return compound


def pubchem_search_structure_by_name(df) -> pd.DataFrame:
    df["pubchem"] = None
    df["pubchem"] = df.progress_apply(lambda row: pubchem_search_by_names(row), axis=1)

    df["pubchem_cid"] = pd.array([compound.cid if pd.notnull(compound) else np.NAN for compound in df["pubchem"]],
                                 dtype=pd.Int64Dtype())
    df["isomeric_smiles"] = [compound.isomeric_smiles if pd.notnull(compound) else np.NAN for compound in df["pubchem"]]
    df["canonical_smiles"] = [compound.canonical_smiles if pd.notnull(compound) else np.NAN for compound in
                              df["pubchem"]]

    df["pubchem_cid_parent"] = df["pubchem_cid"]
    df["compound_name"] = [get_first_synonym(compound) for compound in df["pubchem"]]
    df["iupac"] = [compound.iupac_name if pd.notnull(compound) else np.NAN for compound in df["pubchem"]]
    try:
        df["synonyms"] = df["synonyms"] + [pubchem_get_synonyms(compound) if pd.notnull(compound) else [] for compound
                                           in df["pubchem"]]
    except:
        logging.exception("No synonyms")
    df["pubchem_logp"] = [compound.xlogp if pd.notnull(compound) else np.NAN for compound in df["pubchem"]]

    # drop extra columns
    columns_to_keep = df.columns.isin(
        ["pubchem", "Cat. No.", "Product Name", "synonyms", "CAS No.", "Smiles", "pubchem_cid", "pubchem_cid_parent",
         "isomeric_smiles",
         "canonical_smiles", "mixed_location_plate1", "lib_plate_well", "URL", "Target", "Information", "Pathway",
         "Research Area", "Clinical Information", "gnps_libid", "compound_name", "iupac", "pubchem_logp", "entries"])

    df = df[df.columns[columns_to_keep]]
    # concat the new structures with the old ones
    if "Smiles" in df and len(df[df["Smiles"].notna()]) > 0:
        dfa = df.copy()

        dfa["Source"] = "MCE"
        dfb = df.copy()
        dfb["Smiles"] = [iso if notnull(iso) else smiles for iso, smiles in zip(df["isomeric_smiles"], df["Smiles"])]
        dfb["Source"] = "PubChem"

        dfb = dfb[dfb["Smiles"].notna()]

        df = pd.concat([dfb, dfa], ignore_index=True, sort=False)

    else:
        df["Smiles"] = [iso if notnull(iso) else smiles for iso, smiles in zip(df["isomeric_smiles"], df["Smiles"])]
        df["Source"] = "PubChem"
    return df


def get_first_synonym(compound):
    synonyms = pubchem_get_synonyms(compound)
    if synonyms is None or len(synonyms) <= 0:
        return None
    return synonyms[0]


def pubchem_search_by_structure(df) -> pd.DataFrame:
    df["pubchem"] = [client.search_pubchem_by_structure(smiles, inchi, inchikey) if isnull(compound) else compound for
                     compound, inchikey, smiles, inchi in
                     zip(df["pubchem"], df["inchi_key"], df["Smiles"], df["inchi"])]

    df["pubchem_cid_parent"] = pd.array(
        [compound.cid if pd.notnull(compound) else np.NAN for compound in df["pubchem"]],
        dtype=pd.Int64Dtype())
    df["compound_name"] = [get_first_synonym(compound) for compound in df["pubchem"]]
    df["iupac"] = [compound.iupac_name if pd.notnull(compound) else np.NAN for compound in df["pubchem"]]
    try:
        df["synonyms"] = df["synonyms"] + [pubchem_get_synonyms(compound) if pd.notnull(compound) else [] for compound
                                           in df["pubchem"]]
    except:
        logging.exception("No synonyms")
    df["pubchem_logp"] = [compound.xlogp if pd.notnull(compound) else np.NAN for compound in df["pubchem"]]

    return df


def chembl_search(df) -> pd.DataFrame:
    compounds = [client.get_chembl_mol(chembl_id, inchi_key) for chembl_id, inchi_key in
                 tqdm(zip(df["chembl_id"], df["inchi_key"]))]

    df["chembl_id"] = [compound["molecule_chembl_id"] if pd.notnull(compound) else np.NAN for compound in compounds]
    # df["compound_name"] = df["compound_name"] + [compound["pref_name"] if pd.notnull(compound) else np.NAN for
    # compound in compounds]
    df["molecular_species"] = [
        compound["molecule_properties"]["molecular_species"] if pd.notnull(compound) else np.NAN for compound in
        compounds]
    df["prodrug"] = [compound["prodrug"] if pd.notnull(compound) else np.NAN for compound in compounds]
    df["availability"] = [compound["availability_type"] if pd.notnull(compound) else np.NAN for compound in compounds]
    df["clinical_phase"] = [compound["max_phase"] if pd.notnull(compound) else np.NAN for compound in compounds]
    df["first_approval"] = pd.array(
        [compound["first_approval"] if pd.notnull(compound) else np.NAN for compound in compounds],
        dtype=pd.Int64Dtype())
    df["withdrawn"] = [compound["withdrawn_flag"] if pd.notnull(compound) else np.NAN for compound in compounds]
    # was changed by ChEMBL api
    # df["withdrawn_class"] = [compound["withdrawn_class"] if pd.notnull(compound) else np.NAN for compound in
    #                          compounds]
    # df["withdrawn_reason"] = [compound["withdrawn_reason"] if pd.notnull(compound) else np.NAN for compound in
    #                           compounds]
    # df["withdrawn_year"] = pd.array(
    #     [compound["withdrawn_year"] if pd.notnull(compound) else np.NAN for compound in compounds],
    #     dtype=pd.Int64Dtype())
    # df["withdrawn_country"] = [compound["withdrawn_country"] if pd.notnull(compound) else np.NAN for compound in
    #                            compounds]
    df["oral"] = [compound["oral"] if pd.notnull(compound) else np.NAN for compound in compounds]
    df["parenteral"] = [compound["parenteral"] if pd.notnull(compound) else np.NAN for compound in compounds]
    df["topical"] = [compound["topical"] if pd.notnull(compound) else np.NAN for compound in compounds]
    df["natural_product"] = [compound["natural_product"] if pd.notnull(compound) else np.NAN for compound in
                             compounds]
    df["usan_stem_definition"] = [compound["usan_stem_definition"] if pd.notnull(compound) else np.NAN for compound
                                  in compounds]
    df["chembl_alogp"] = [compound["molecule_properties"]["alogp"] if pd.notnull(compound) else np.NAN for compound
                          in compounds]
    df["chembl_clogp"] = [compound["molecule_properties"]["cx_logp"] if pd.notnull(compound) else np.NAN for compound
                          in compounds]

    ## dont overwrite
    # df["synonyms"] = df["synonyms"] + [compound["molecule_synonyms"] if pd.notnull(compound) else [] for
    # compound in compounds]
    df["indication"] = [compound["indication_class"] if pd.notnull(compound) else np.NAN for compound in compounds]

    return df


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
    df["unii"] = [find_unii(synonyms) for synonyms in df["synonyms"]]
    df["schembl_id"] = [find_schembl(synonyms) for synonyms in df["synonyms"]]
    df["chembl_id"] = [find_chembl_id(synonyms) for synonyms in df["synonyms"]]
    df["zinc_id"] = [find_zinc(synonyms) for synonyms in df["synonyms"]]
    df["drugbank_id"] = [find_drugbank(synonyms) for synonyms in df["synonyms"]]

    return df


if __name__ == "__main__":
    cleanup_file(r"data/library/test_metadata.tsv", lib_id="pluskal_nih",
                 id_columns=['Product Name', 'lib_plate_well', "inchi_key"],
                 query_pubchem=True, query_broad_list=True, query_drugbank_list=True,
                 query_drugcentral=True)
    # cleanup_file("data\mce_library.tsv", id_columns=['Product Name', 'lib_plate_well', "inchi_key"], query_pubchem=True, query_broad_list=True, query_drugbank_list=True,
    #                  query_drugcentral=True)
    # cleanup_file("data\gnpslib\gnps_library_small.csv", id_columns=['gnps_libid', "inchi_key"], query_pubchem=True,
    #              query_broad_list=True, query_drugbank_list=True, query_drugcentral=True)
    # cleanup_file("data\gnpslib\gnps_library.csv", id_columns=['gnps_libid', "inchi_key"], query_pubchem=True,
    #              query_broad_list=True, query_drugbank_list=True, query_drugcentral=True)
    # cleanup_file("data\mce_library_add_compounds.tsv", id_columns=['Product Name', 'lib_plate_well', "inchi_key"], query_pubchem=True, query_broad_list=True, query_drugbank_list=True,
    #                  query_drugcentral=True)
    # cleanup_file(r"data/nih/nih_library_test.tsv", id_columns=['Product Name', 'lib_plate_well', "Smiles"], query_pubchem=True,  pubchem_search=True, query_broad_list=True, query_drugbank_list=True,
    #                  query_drugcentral=True)
