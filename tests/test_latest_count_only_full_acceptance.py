"""Host-only complete-acceptance evidence gates. No hardware access."""
import unittest
from latest_zero_count_only_acceptance import motion_observation


class FullAcceptanceTests(unittest.TestCase):
    def test_position_and_original_busy_phase_required(self):
        text = ('IN_MOTION T=0.1s 12 OK STATUS STAGE=2 BUSY=1 FLT=0\n'
                'Position change: +12.34 deg\n')
        r = motion_observation(text)
        self.assertEqual(r['delta_deg'], 12.34)
        self.assertEqual(r['observed_stages'], ['2'])
        self.assertFalse(r['torque_qualified'])
        self.assertFalse(r['steady_speed_qualified'])

    def test_no_false_pass_from_queued_ack_or_encoder_noise(self):
        for text in ('12 OK START QUEUED\nPosition change: +12.00 deg\n',
            'IN_MOTION T=0.1s 12 OK STATUS STAGE=0 BUSY=0\nPosition change: +12.00 deg\n',
            'IN_MOTION T=0.1s 12 OK STATUS STAGE=2 BUSY=1\nPosition change: +0.05 deg\n',
            'IN_MOTION T=0.1s 12 OK STATUS STAGE=2 BUSY=1\n'):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                motion_observation(text)


if __name__ == '__main__':
    unittest.main()
