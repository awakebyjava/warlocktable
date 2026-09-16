"""Pixels dice input, tested without a radio.

    python -m unittest discover -s tests -v

The packet bytes here are real: captured from a d20 at the table on
2026-09-16 with `tools/dice_probe.py --raw`. If the firmware ever changes
the layout, these are the tests that should start failing.
"""

import struct
import unittest

from warlock.inputs.dice import (AdFields, RollTracker, decode_advert,
                                 face_value, parse_ad)

# One advert from Pixel03ef405d: flags, uuid list [180a], manufacturer
# 0xFFFF [led=20, design=0x73, state, face, batt=100], complete name.
ADV_ROLLED_14 = bytes.fromhex("02010603030a1808ffffff1473010d640e09506978656c3033656634303564")
ADV_ROLLING_20 = bytes.fromhex("02010603030a1808ffffff14730313640e09506978656c3033656634303564")
ADV_ROLLED_20 = bytes.fromhex("02010603030a1808ffffff14730113640e09506978656c3033656634303564")
ADV_ONFACE_2 = bytes.fromhex("02010603030a1808ffffff14730501640e09506978656c3033656634303564")
ADV_HANDLING = bytes.fromhex("02010603030a1808ffffff14730203640e09506978656c3033656634303564")

# The scan response the die sends occasionally: service data under 180a
# with pixel id and firmware build timestamp (2024-11-07).
SCAN_RSP = bytes([11, 0x16]) + struct.pack("<H", 0x180A) + struct.pack("<II", 0x03EF405D, 1730937600)

ADDR = "CA:D8:66:FC:05:74"


class ParseAdTests(unittest.TestCase):
    def test_real_advert(self):
        f = parse_ad(ADV_ROLLED_14)
        self.assertEqual(f.name, "Pixel03ef405d")
        self.assertEqual(f.uuids, ["0000180a-0000-1000-8000-00805f9b34fb"])
        self.assertEqual(f.manufacturer, {0xFFFF: bytes([20, 0x73, 1, 13, 100])})
        self.assertEqual(f.service_data, {})

    def test_merge_scan_response(self):
        f = parse_ad(ADV_ROLLED_14)
        parse_ad(SCAN_RSP, f)
        self.assertEqual(f.service_data[0x180A][:4], struct.pack("<I", 0x03EF405D))
        self.assertEqual(f.name, "Pixel03ef405d")   # kept

    def test_128bit_uuid_list(self):
        raw = bytes.fromhex("6e400001b5a3f393e0a9e50e24dcca9e")[::-1]
        f = parse_ad(bytes([17, 0x07]) + raw)
        self.assertEqual(f.uuids, ["6e400001-b5a3-f393-e0a9-e50e24dcca9e"])

    def test_garbage_is_harmless(self):
        parse_ad(b"")
        parse_ad(b"\x05")
        parse_ad(b"\xff\xff\xff")


class DecodeTests(unittest.TestCase):
    def test_advert_without_id(self):
        adv = decode_advert(parse_ad(ADV_ROLLED_14))
        self.assertIsNotNone(adv)
        self.assertEqual(adv.die_type, "d20")
        self.assertEqual(adv.led_count, 20)
        self.assertEqual(adv.colourway, 3)
        self.assertEqual(adv.state_name, "rolled")
        self.assertEqual(adv.face, 14)
        self.assertEqual(adv.battery, 100)
        self.assertFalse(adv.charging)
        self.assertIsNone(adv.pixel_id)

    def test_with_scan_response(self):
        f = parse_ad(ADV_ROLLING_20)
        parse_ad(SCAN_RSP, f)
        adv = decode_advert(f)
        self.assertEqual(adv.pixel_id, 0x03EF405D)
        self.assertEqual(adv.firmware.strftime("%Y-%m-%d"), "2024-11-07")
        self.assertEqual(adv.state_name, "rolling")
        self.assertEqual(adv.face, 20)

    def test_charging_bit(self):
        f = AdFields(name="Pixel", manufacturer={0xFFFF: bytes([20, 0x73, 5, 0, 0x80 | 40])})
        adv = decode_advert(f)
        self.assertTrue(adv.charging)
        self.assertEqual(adv.battery, 40)
        self.assertEqual(adv.state_name, "onFace")

    def test_not_a_pixel(self):
        govee = parse_ad(bytes([6, 0x09]) + b"Govee" + bytes([8, 0xFF, 0xFF, 0xFF, 1, 2, 3, 4, 5]))
        self.assertIsNone(decode_advert(govee))
        self.assertIsNone(decode_advert(AdFields(name="Pixel")))   # no data

    def test_face_values(self):
        self.assertEqual(face_value("d20", 19), 20)
        self.assertEqual(face_value("d6", 0), 1)
        self.assertEqual(face_value("d10", 0), 0)
        self.assertEqual(face_value("d10", 9), 9)
        self.assertEqual(face_value("d00", 9), 90)
        self.assertEqual(face_value("d00", 0), 0)


class RollTrackerTests(unittest.TestCase):
    def feed_all(self, tracker, packets, t0=0.0, step=0.2):
        events = []
        for i, pkt in enumerate(packets):
            e = tracker.feed(ADDR, pkt, -40, now=t0 + i * step)
            if e is not None:
                events.append(e)
        return events

    def test_one_roll_is_one_event(self):
        t = RollTracker()
        events = self.feed_all(t, [ADV_HANDLING, ADV_ROLLING_20, ADV_ROLLING_20,
                                   ADV_ROLLED_20, ADV_ROLLED_20, ADV_ROLLED_20])
        self.assertEqual([e.face for e in events], [20])
        self.assertEqual(events[0].die_type, "d20")
        self.assertEqual(events[0].name, "Pixel03ef405d")
        self.assertIsNone(events[0].pixel_id)
        self.assertEqual(events[0].die_key, ADDR)   # no id yet: address stands in

    def test_same_face_twice_is_two_rolls(self):
        t = RollTracker()
        events = self.feed_all(t, [ADV_ROLLED_14, ADV_ROLLING_20, ADV_ROLLED_14,
                                   ADV_ONFACE_2, ADV_ROLLING_20, ADV_ROLLED_14])
        self.assertEqual([e.face for e in events], [14, 14, 14])

    def test_on_face_is_not_a_roll(self):
        t = RollTracker()
        events = self.feed_all(t, [ADV_ONFACE_2, ADV_HANDLING, ADV_ONFACE_2])
        self.assertEqual(events, [])

    def test_first_packet_already_rolled_counts_once(self):
        # Scanner starts while the die is sitting on a rolled face: that is
        # the state it is in, reported once, not re-fired every packet.
        t = RollTracker()
        events = self.feed_all(t, [ADV_ROLLED_14] * 5)
        self.assertEqual(len(events), 1)

    def test_id_fills_in_from_scan_response(self):
        t = RollTracker()
        t.feed(ADDR, ADV_HANDLING, -40, now=0.0)
        t.feed(ADDR, SCAN_RSP, -40, now=0.2)          # no state change, no event
        e = t.feed(ADDR, ADV_ROLLED_20, -40, now=0.4)
        self.assertEqual(e.pixel_id, 0x03EF405D)
        self.assertEqual(e.die_key, "03ef405d")
        self.assertEqual(t.dice[ADDR].firmware.strftime("%Y-%m-%d"), "2024-11-07")

    def test_two_addresses_one_die_one_roll(self):
        # The same landing announced on both of a die's addresses within a
        # second is one roll -- but only once both are known to be the same id.
        t = RollTracker()
        other = "CA:D8:66:FC:05:75"
        for a in (ADDR, other):
            t.feed(a, ADV_HANDLING, -40, now=0.0)
            t.feed(a, SCAN_RSP, -40, now=0.1)
        e1 = t.feed(ADDR, ADV_ROLLED_20, -40, now=1.0)
        e2 = t.feed(other, ADV_ROLLED_20, -40, now=1.3)
        self.assertIsNotNone(e1)
        self.assertIsNone(e2)
        # ...and a genuinely new roll of the same face later is a new event.
        t.feed(ADDR, ADV_ROLLING_20, -40, now=3.0)
        e3 = t.feed(ADDR, ADV_ROLLED_20, -40, now=3.5)
        self.assertIsNotNone(e3)

    def test_snapshot_folds_addresses(self):
        t = RollTracker()
        other = "CA:D8:66:FC:05:75"
        for a in (ADDR, other):
            t.feed(a, ADV_HANDLING, -40, now=0.0)
            t.feed(a, SCAN_RSP, -40, now=0.1)
        t.feed(ADDR, ADV_ROLLED_20, -40, now=1.0)
        snap = t.snapshot(now=2.0)
        self.assertEqual(len(snap), 1)
        self.assertEqual(snap[0]["die"], "03ef405d")
        self.assertEqual(snap[0]["type"], "d20")
        self.assertEqual(snap[0]["rolls"], 1)
        self.assertEqual(snap[0]["battery"], 100)
        self.assertEqual(t.snapshot(now=1000.0), [])   # stale


if __name__ == "__main__":
    unittest.main()
