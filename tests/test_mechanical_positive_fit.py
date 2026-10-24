import math
from pathlib import Path
import random
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import mechanical_positive_fit as fit


class PositiveFitTests(unittest.TestCase):
    def test_known_synthetic_model_recovery(self):
        rng=random.Random(123)
        points=[]
        for _ in range(200):
            alpha=rng.uniform(-30,30);omega=rng.uniform(10,90)
            points.append(dict(alpha=alpha,omega=omega,direction=1,dt_s=.064,
                iq=.004*alpha+.002*omega+.08))
        model=fit.solve(points)
        for k,v in [('j_over_kt',.004),('b_over_kt',.002),('positive_friction_plus_bias_a',.08)]:
            self.assertAlmostEqual(model[k],v,places=10)
        self.assertAlmostEqual(model['r2'],1)

    def test_rank_and_direction_not_faked(self):
        points=[dict(alpha=1.,omega=20.,direction=1,dt_s=.064,iq=.2) for _ in range(100)]
        with self.assertRaisesRegex(ValueError,'RANK_DEFICIENT'):fit.solve(points)
        points[0]['direction']=-1
        with self.assertRaisesRegex(ValueError,'POSITIVE_ONLY_REQUIRED'):fit.solve(points)

    def test_empty_unqualified_no_absolute_parameters_or_writes(self):
        report=fit.report([])
        self.assertFalse(report['normalized_positive_qualified'])
        self.assertIsNone(report['absolute_parameters'])
        self.assertFalse(report['parameter_writes'])
        self.assertFalse(report['dob_control_enabled'])
        self.assertFalse(report['kt_independently_identified'])


if __name__=='__main__':unittest.main()
