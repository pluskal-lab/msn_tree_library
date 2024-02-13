from unittest import TestCase
import rdkit_functional_group as fg
import rdkit.Chem as Chem
from dataclasses import dataclass


def mol(smiles):
    return Chem.MolFromSmiles(smiles)


def count(group: fg.FunctionalGroup, smiles: str):
    return fg.count_functional_group(group, mol(smiles))


@dataclass
class Case:
    expected_matches: int
    smiles: str
    group: fg.FunctionalGroup


class Test(TestCase):
    def test_count(self):
        taurocholicacid = (
            "CC(CCC(=O)NCCS(=O)(=O)O)C1CCC2C1(C(CC3C2C(CC4C3(CCC(C4)O)C)O)O)C"
        )
        CH5132799 = "CS(=O)(=O)N1CCC2=C(N=C(N=C21)N3CCOCC3)C4=CN=C(N=C4)N"
        fostemsavir_trom = "CC1=NN(C=N1)C2=NC=C(C3=C2N(C=C3C(=O)C(=O)N4CCN(CC4)C(=O)C5=CC=CC=C5)COP(=O)(O)O)OC.C(C(CO)(CO)N)O"
        phenol = "C1=CC=C(C=C1)O"
        ascorbicacid = "C(C(C1C(=C(C(=O)O1)O)O)O)O"
        patulin = "C1C=C2C(=CC(=O)O2)C(O1)O"
        folic_acid = "C1=CC(=CC=C1C(=O)NC(CCC(=O)O)C(=O)O)NCC2=CN=C3C(=N2)C(=O)NC(=N3)N"
        folate = "C1=CC(=CC=C1C(=O)NC(CCC(=O)[O-])C(=O)O)NCC2=CN=C3C(=N2)C(=O)NC(=N3)N"
        lecitinpc = "CCCCCCCCCCCCCCCC(=O)OCC(COP(=O)([O-])OCC[N+](C)(C)C)OC(=O)CCCCCCCC=CCC=CCCCCC"

        cases = [
            Case(2, CH5132799, fg.guanidine),
            Case(0, CH5132799, fg.sulfonic_ester),
            Case(0, CH5132799, fg.sulfonic_acid),
            Case(1, CH5132799, fg.sulfone),
            Case(0, CH5132799, fg.sulfoxide),
            Case(0, CH5132799, fg.sulfate),
            Case(1, CH5132799, fg.prim_aromatic_amine),
            Case(1, phenol, fg.phenole),
            # taurocholic acid
            Case(0, taurocholicacid, fg.phenole),
            Case(4, taurocholicacid, fg.hydroxy),
            Case(3, taurocholicacid, fg.hydroxy_aliphatic),
            Case(1, taurocholicacid, fg.amide),
            Case(0, taurocholicacid, fg.sulfonic_ester),
            Case(1, taurocholicacid, fg.sulfonic_acid),
            Case(0, taurocholicacid, fg.lactone),
            Case(0, fostemsavir_trom, fg.sulfonic_acid),
            Case(0, fostemsavir_trom, fg.prim_aromatic_amine),
            Case(1, fostemsavir_trom, fg.prim_amine),
            Case(0, fostemsavir_trom, fg.second_amine),
            # Case(0, fostemsavir_trom, fg.tert_amine),
            Case(0, fostemsavir_trom, fg.quart_amine),
            Case(0, fostemsavir_trom, fg.enamine),
            Case(0, fostemsavir_trom, fg.enole),
            Case(5, fostemsavir_trom, fg.hydroxy),
            Case(3, fostemsavir_trom, fg.hydroxy_aliphatic),
            Case(1, fostemsavir_trom, fg.phosphoric_acid),
            Case(1, fostemsavir_trom, fg.phosphoric_ester),
            Case(0, fostemsavir_trom, fg.guanidine),
            Case(2, fostemsavir_trom, fg.amide),
            Case(2, fostemsavir_trom, fg.tert_amide),
            Case(0, fostemsavir_trom, fg.prim_amide),
            Case(0, fostemsavir_trom, fg.second_amide),
            Case(3, fostemsavir_trom, fg.azole),
            Case(1, fostemsavir_trom, fg.ketone),
            Case(0, fostemsavir_trom, fg.aldehyde),
            Case(3, fostemsavir_trom, fg.carbonyl),
            Case(0, fostemsavir_trom, fg.carboxylic_acid),
            Case(0, fostemsavir_trom, fg.lactone),
            Case(0, ascorbicacid, fg.carboxylic_acid),
            Case(0, ascorbicacid, fg.ketone),
            Case(1, ascorbicacid, fg.carbonyl),
            Case(1, ascorbicacid, fg.lactone),
            Case(4, ascorbicacid, fg.hydroxy),
            Case(1, patulin, fg.hydroxy),
            Case(1, patulin, fg.lactone),
            Case(1, patulin, fg.ester),
            Case(0, folic_acid, fg.lactone),
            Case(0, folic_acid, fg.ester),
            Case(2, folic_acid, fg.amide),
            Case(2, folic_acid, fg.second_amide),
            Case(1, folic_acid, fg.prim_amine),
            Case(1, folic_acid, fg.second_amine),
            Case(0, folic_acid, fg.tert_amine),
            Case(2, folic_acid, fg.carboxylic_acid),
            Case(0, folate, fg.lactone),
            Case(0, folate, fg.ester),
            Case(2, folate, fg.amide),
            Case(2, folate, fg.second_amide),
            Case(1, folate, fg.prim_amine),
            Case(1, folate, fg.second_amine),
            Case(0, folate, fg.tert_amine),
            Case(2, folate, fg.carboxylic_acid),
            Case(0, lecitinpc, fg.carboxylic_acid),
            Case(0, lecitinpc, fg.prim_amine),
            Case(0, lecitinpc, fg.second_amine),
            Case(0, lecitinpc, fg.tert_amine),
            Case(1, lecitinpc, fg.quart_amine),
            Case(1, lecitinpc, fg.phosphoric_acid),
            Case(1, lecitinpc, fg.phosphoric_ester),
            Case(0, lecitinpc, fg.lactone),
            Case(2, lecitinpc, fg.ester),
        ]

        for case in cases:
            group = case.group
            found = count(group, case.smiles)
            self.assertEqual(
                case.expected_matches,
                found,
                f"{group.name} smarts {group.smarts} failed count in {case.smiles}",
            )


if __name__ == "__main__":
    unittest.main()
