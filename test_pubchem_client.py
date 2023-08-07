from unittest import TestCase

import pandas as pd
from pubchem_client import pubchem_search_structure_by_name, _get_pubchem_parent_cid


class Test(TestCase):
    def test_pubchem_search_structure_by_name(self):
        df = pd.DataFrame(
            {
                "smiles": [None, "lfjlajdfi", "dawd", "dawdawd"],
                "compound_name": ["aspirin", "piperine", None, ""]
            }
        )
        df = pubchem_search_structure_by_name(df)

        assert len(df) == 5

    def test_get_pubchem_parent_cid(self):
        cid = "46892186"
        parent_cid = _get_pubchem_parent_cid(cid, True, 1, 1)
        assert parent_cid == "11319217"
        assert _get_pubchem_parent_cid("11319217", max_tries=1) == "11319217"  # is parent
        assert _get_pubchem_parent_cid(None, max_tries=1) is None