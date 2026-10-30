"""Tests for the voting flow. Face recognition is faked: the 'image' sent by the
test is a short name, and each name maps to a fixed embedding, so the tests run
without a camera or DeepFace models."""

import base64
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import faces
from .models import AuditLog, Candidate, Election, Participation, Position, Vote, Voter
from .roll import import_roll

FAKE_FACES = {
    "ada": [1.0, 0.0, 0.0, 0.0],
    "ada-again": [0.98, 0.1, 0.0, 0.0],  # same person, slightly different photo
    "ada-sibling": [0.67, 0.0, 0.0, 0.742],  # look-alike: distance 0.33 from ada
    "ada-twin": [0.8, 0.0, 0.0, 0.6],  # registered look-alike: distance 0.20 from ada
    "ada-twin-again": [0.85, 0.0, 0.0, 0.53],  # the twin on election day: 0.15 from ada, 0.004 from own face
    "ada-ambiguous": [0.95, 0.0, 0.0, 0.31],  # 0.049 from ada, 0.053 from ada-twin: too close to call
    "ada-blurred": [0.9, 0.0, 0.3, 0.0],  # a poor photo of ada: 0.051 from ada
    "ada-moved": [0.7, 0.0, 0.7, 0.0],  # half out of view: 0.29 from ada
    "bola": [0.0, 1.0, 0.0, 0.0],
    "chidi": [0.0, 0.0, 1.0, 0.0],
}


def photo(name):
    """A fake webcam data URL whose payload is just the person's name."""
    return "data:image/jpeg;base64," + base64.b64encode(name.encode()).decode()


def fake_embedding(data_url):
    name = base64.b64decode(data_url.split(",", 1)[1]).decode()
    if name == "no-face":
        raise faces.FaceError("No face was detected.")
    if name == "photo-of-ada":
        raise faces.SpoofError("Liveness check failed.")
    return FAKE_FACES[name]


def csv_file(text):
    return SimpleUploadedFile("roll.csv", text.encode("utf-8"), content_type="text/csv")


ROLL = (
    "full_name,reg_number,faculty,department,level\n"
    "Ada Obi,2021/111111,Physical Sciences,Computer Science,200\n"
    "Bola Ade,2021/222222,Physical Sciences,Computer Science,300\n"
    "Chidi Eze,2021/333333,Engineering,Electrical Engineering,400\n"
)


class RollImportTests(TestCase):
    def test_imports_rows(self):
        result = import_roll(csv_file(ROLL))
        self.assertTrue(result.ok)
        self.assertEqual(result.created, 3)
        self.assertEqual(Voter.objects.get(reg_number="2021/111111").department, "Computer Science")

    def test_headers_are_case_and_order_insensitive(self):
        text = "Reg Number,Full Name,Level,Department,Faculty\n2021/1, Ada  Obi ,200,CS,PS\n"
        result = import_roll(csv_file(text))
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(Voter.objects.get().full_name, "Ada Obi")

    def test_missing_header_rejected(self):
        result = import_roll(csv_file("full_name,reg_number,faculty\nA,1,F\n"))
        self.assertFalse(result.ok)
        self.assertIn("department", result.errors[0])
        self.assertEqual(Voter.objects.count(), 0)

    def test_bad_row_rejects_whole_file(self):
        text = ROLL + "Dupe,2021/111111,X,Y,100\n,2021/444444,X,Y,100\n"
        result = import_roll(csv_file(text))
        self.assertFalse(result.ok)
        self.assertEqual(len(result.errors), 2)
        self.assertEqual(Voter.objects.count(), 0)

    def test_reupload_updates_and_keeps_face(self):
        import_roll(csv_file(ROLL))
        Voter.objects.filter(reg_number="2021/111111").update(
            face_embedding=[1, 0, 0], registered_at=timezone.now()
        )
        result = import_roll(csv_file(ROLL.replace("Ada Obi,2021/111111,Physical Sciences,Computer Science,200",
                                                   "Ada Obi,2021/111111,Physical Sciences,Computer Science,300")))
        self.assertEqual((result.created, result.updated), (0, 3))
        ada = Voter.objects.get(reg_number="2021/111111")
        self.assertEqual(ada.level, "300")
        self.assertTrue(ada.is_registered)


@mock.patch("voting.faces.get_embedding", side_effect=fake_embedding)
@override_settings(MEDIA_ROOT="/tmp/unnvote-test-media")
class RegistrationTests(TestCase):
    def setUp(self):
        import_roll(csv_file(ROLL))

    def post(self, **overrides):
        data = {
            "reg_number": "2021/111111", "full_name": "ada obi", "faculty": "Physical Sciences",
            "department": "computer science", "level": "200", "email": "ada@example.com",
            "phone": "08000000000", "face_image": photo("ada"),
        }
        data.update(overrides)
        return self.client.post(reverse("register"), data)

    def test_successful_registration(self, _):
        response = self.post()
        self.assertContains(response, "on the voting list")
        ada = Voter.objects.get(reg_number="2021/111111")
        self.assertTrue(ada.is_registered)
        self.assertEqual(ada.email, "ada@example.com")
        self.assertTrue(AuditLog.objects.filter(action="registered", reg_number="2021/111111").exists())

    def test_details_must_match_roll(self, _):
        response = self.post(department="Mathematics")
        self.assertContains(response, "do not match the voter roll")
        self.assertFalse(Voter.objects.get(reg_number="2021/111111").is_registered)

    def test_unknown_reg_number(self, _):
        self.assertContains(self.post(reg_number="2099/000000"), "do not match the voter roll")

    def test_cannot_register_twice(self, _):
        self.post()
        self.assertContains(self.post(), "already been registered")

    def test_same_face_cannot_register_two_reg_numbers(self, _):
        self.post()
        response = self.post(reg_number="2021/222222", full_name="Bola Ade", level="300", face_image=photo("ada-again"))
        self.assertContains(response, "already registered to another student")
        self.assertFalse(Voter.objects.get(reg_number="2021/222222").is_registered)
        entry = AuditLog.objects.get(action="register_duplicate_face")
        self.assertIn("face matches 2021/111111, distance 0.", entry.detail)

    def test_look_alike_who_would_not_pass_as_voter_can_register(self, _):
        # A sibling close to, but outside, the match threshold is a different person.
        self.post()
        response = self.post(reg_number="2021/222222", full_name="Bola Ade", level="300", face_image=photo("ada-sibling"))
        self.assertContains(response, "on the voting list")
        entry = AuditLog.objects.get(action="registered", reg_number="2021/222222")
        self.assertIn("nearest other face distance 0.330", entry.detail)

    def test_registration_stores_average_of_several_photos(self, _):
        response = self.client.post(reverse("register"), {
            "reg_number": "2021/111111", "full_name": "ada obi", "faculty": "Physical Sciences",
            "department": "computer science", "level": "200", "email": "ada@example.com",
            "phone": "08000000000", "face_image": photo("ada"),
            "face_image_extra": [photo("ada-again"), photo("ada-blurred")],
        })
        self.assertContains(response, "on the voting list")
        stored = Voter.objects.get(reg_number="2021/111111").face_embedding
        self.assertLess(faces.distance(stored, FAKE_FACES["ada"]), 0.03)
        self.assertNotEqual(stored, FAKE_FACES["ada"])
        entry = AuditLog.objects.get(action="registered", reg_number="2021/111111")
        self.assertIn("3 photo(s), spread 0.", entry.detail)

    def test_photos_that_disagree_are_refused(self, _):
        response = self.client.post(reverse("register"), {
            "reg_number": "2021/111111", "full_name": "ada obi", "faculty": "Physical Sciences",
            "department": "computer science", "level": "200", "email": "ada@example.com",
            "phone": "08000000000", "face_image": photo("ada"),
            "face_image_extra": [photo("ada-again"), photo("ada-moved")],
        })
        self.assertContains(response, "did not match each other")
        self.assertFalse(Voter.objects.get(reg_number="2021/111111").is_registered)

    def test_no_face_detected(self, _):
        self.assertContains(self.post(face_image=photo("no-face")), "No face was detected")

    def test_photo_rejected_by_liveness_check(self, _):
        self.assertContains(self.post(face_image=photo("photo-of-ada")), "Liveness check failed")
        self.assertFalse(Voter.objects.get(reg_number="2021/111111").is_registered)
        self.assertTrue(AuditLog.objects.filter(action="spoof_rejected", reg_number="2021/111111").exists())

    def test_closed_while_voting_open(self, _):
        Election.objects.create(title="SUG 2026", status=Election.OPEN)
        response = self.post()
        self.assertRedirects(response, reverse("home"))
        self.assertFalse(Voter.objects.get(reg_number="2021/111111").is_registered)


@mock.patch("voting.faces.get_embedding", side_effect=fake_embedding)
class VotingTests(TestCase):
    def setUp(self):
        import_roll(csv_file(ROLL))
        for reg, face in (("2021/111111", "ada"), ("2021/222222", "bola")):
            Voter.objects.filter(reg_number=reg).update(
                face_embedding=FAKE_FACES[face], registered_at=timezone.now()
            )
        self.election = Election.objects.create(title="SUG 2026", status=Election.OPEN)
        self.president = Position.objects.create(election=self.election, title="President", order=1)
        self.secgen = Position.objects.create(election=self.election, title="Secretary General", order=2)
        self.p1 = Candidate.objects.create(position=self.president, name="Candidate P1")
        self.p2 = Candidate.objects.create(position=self.president, name="Candidate P2")
        self.s1 = Candidate.objects.create(position=self.secgen, name="Candidate S1")

    def accredit(self, reg="2021/111111", face="ada"):
        return self.client.post(reverse("vote_start"), {"reg_number": reg, "face_image": photo(face)})

    def cast(self, face="ada", president=None):
        return self.client.post(reverse("ballot"), {
            f"position_{self.president.pk}": (president or self.p1).pk,
            f"position_{self.secgen.pk}": self.s1.pk,
            "face_image": photo(face),
        })

    def test_full_vote(self, _):
        self.assertRedirects(self.accredit(), reverse("ballot"))
        self.assertContains(self.client.get(reverse("ballot")), "Candidate P2")
        self.assertContains(self.cast(face="ada-again"), "Your vote has been recorded")
        self.assertEqual(Vote.objects.filter(candidate=self.p1).count(), 1)
        self.assertEqual(Participation.objects.count(), 1)

    def test_votes_are_not_linked_to_voters(self, _):
        field_names = {f.name for f in Vote._meta.get_fields()}
        self.assertNotIn("voter", field_names)

    def test_wrong_face_rejected_at_accreditation(self, _):
        response = self.accredit(face="bola")
        self.assertContains(response, "did not match")
        self.assertEqual(self.client.get(reverse("ballot")).status_code, 302)

    def test_look_alike_cannot_vote_as_someone_else(self, _):
        # Bola's sibling-like face passes Ada's threshold but is closer to Bola's own registration.
        Voter.objects.filter(reg_number="2021/222222").update(face_embedding=FAKE_FACES["ada-twin"])
        response = self.accredit(face="ada-twin-again")
        self.assertContains(response, "did not match")
        entry = AuditLog.objects.get(action="face_closer_to_other", reg_number="2021/111111")
        self.assertIn("to 2021/222222", entry.detail)
        # The real owner of each registration still gets through.
        self.assertRedirects(self.accredit(), reverse("ballot"))

    def test_face_too_close_to_another_student_is_refused(self, _):
        # Nearer to Ada (0.049) than to Bola's look-alike face (0.053), but not clearly.
        Voter.objects.filter(reg_number="2021/222222").update(face_embedding=FAKE_FACES["ada-twin"])
        self.assertContains(self.accredit(face="ada-ambiguous"), "did not match")
        self.assertTrue(AuditLog.objects.filter(action="face_closer_to_other", reg_number="2021/111111").exists())

    def test_unregistered_student_cannot_vote(self, _):
        self.assertContains(self.accredit(reg="2021/333333", face="chidi"), "not on the registered voters list")

    def test_face_rechecked_on_submit(self, _):
        self.accredit()
        response = self.cast(face="bola")
        self.assertContains(response, "did not match")
        self.assertEqual(Participation.objects.count(), 0)

    def test_cannot_vote_twice(self, _):
        self.accredit()
        self.cast()
        self.assertContains(self.accredit(), "already voted")
        self.assertEqual(Vote.objects.count(), 2)

    def test_must_choose_every_position(self, _):
        self.accredit()
        response = self.client.post(reverse("ballot"), {f"position_{self.president.pk}": self.p1.pk, "face_image": photo("ada")})
        self.assertContains(response, "Please choose a candidate for Secretary General")

    def test_candidate_from_other_position_rejected(self, _):
        self.accredit()
        response = self.client.post(reverse("ballot"), {
            f"position_{self.president.pk}": self.s1.pk,
            f"position_{self.secgen.pk}": self.s1.pk,
            "face_image": photo("ada"),
        })
        self.assertContains(response, "Please choose a candidate for President")
        self.assertEqual(Vote.objects.count(), 0)

    def test_session_expires(self, _):
        self.accredit()
        session = self.client.session
        session["vote_verified_at"] = (timezone.now() - timedelta(minutes=30)).isoformat()
        session.save()
        self.assertRedirects(self.cast(), reverse("vote_start"))
        self.assertEqual(Participation.objects.count(), 0)

    def test_lockout_after_repeated_mismatches(self, _):
        for _i in range(5):
            self.accredit(face="bola")
        self.assertContains(self.accredit(), "Too many failed face scans")

    def test_photo_rejected_at_accreditation(self, _):
        self.assertContains(self.accredit(face="photo-of-ada"), "Liveness check failed")
        self.assertEqual(self.client.get(reverse("ballot")).status_code, 302)
        self.assertTrue(AuditLog.objects.filter(action="spoof_rejected", reg_number="2021/111111").exists())

    def test_photo_rejected_at_submit(self, _):
        self.accredit()
        self.assertContains(self.cast(face="photo-of-ada"), "Liveness check failed")
        self.assertEqual(Participation.objects.count(), 0)

    def test_spoof_attempts_count_towards_lockout(self, _):
        for _i in range(5):
            self.accredit(face="photo-of-ada")
        self.assertContains(self.accredit(), "Too many failed face scans")

    def test_no_open_election(self, _):
        self.election.status = Election.CLOSED
        self.election.save()
        self.assertRedirects(self.accredit(), reverse("home"))


class StaffTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("committee", "c@example.com", "pass12345")

    def test_staff_pages_require_login(self):
        response = self.client.get(reverse("staff_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_roll_upload_view(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("staff_roll_upload"), {"file": csv_file(ROLL)}, follow=True)
        self.assertContains(response, "3 students added")
        self.assertTrue(AuditLog.objects.filter(action="roll_uploaded").exists())

    def test_results(self):
        self.client.force_login(self.admin)
        election = Election.objects.create(title="SUG 2026", status=Election.CLOSED)
        position = Position.objects.create(election=election, title="President")
        a = Candidate.objects.create(position=position, name="A")
        b = Candidate.objects.create(position=position, name="B")
        Vote.objects.bulk_create([Vote(election=election, position=position, candidate=a)] * 3
                                 + [Vote(election=election, position=position, candidate=b)])
        data = self.client.get(reverse("staff_results_json", args=[election.pk])).json()
        rows = data["positions"][0]["rows"]
        self.assertEqual([(r["id"], r["votes"], r["percent"]) for r in rows], [(a.pk, 3, 75.0), (b.pk, 1, 25.0)])
        self.assertContains(self.client.get(reverse("staff_results", args=[election.pk])), "75.0")

    def test_public_results_only_when_published(self):
        election = Election.objects.create(title="SUG 2026", status=Election.CLOSED)
        self.assertEqual(self.client.get(reverse("public_results", args=[election.pk])).status_code, 404)
        election.results_public = True
        election.save()
        self.assertEqual(self.client.get(reverse("public_results", args=[election.pk])).status_code, 200)


class FaceMathTests(TestCase):
    def test_distance(self):
        self.assertAlmostEqual(faces.distance([1, 0], [1, 0]), 0.0)
        self.assertAlmostEqual(faces.distance([1, 0], [0, 1]), 1.0)

    def test_decode_rejects_garbage(self):
        with self.assertRaises(faces.FaceError):
            faces.decode_data_url("data:image/jpeg;base64,not-an-image!!")

    @mock.patch("deepface.DeepFace.represent", side_effect=ValueError("Spoof detected in the given image."))
    def test_deepface_spoof_becomes_spoof_error(self, represent):
        import cv2
        import numpy as np

        ok, jpeg = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
        with self.assertRaises(faces.SpoofError):
            faces.get_embedding("data:image/jpeg;base64," + base64.b64encode(jpeg.tobytes()).decode())
        self.assertIs(represent.call_args.kwargs["anti_spoofing"], True)


@mock.patch("voting.faces.get_embedding", side_effect=fake_embedding)
class PracticeElectionTests(TestCase):
    def call(self, *args):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("practice_election", *args, stdout=out)
        return out.getvalue()

    def test_full_practice_run(self, _):
        self.call("setup")
        self.call("setup")  # running it twice changes nothing
        election = Election.objects.get(title="SUG Practice Election")
        self.assertEqual(Voter.objects.count(), 10)
        self.assertEqual(election.positions.count(), 3)
        self.assertEqual(Candidate.objects.filter(position__election=election).count(), 6)
        self.assertEqual(election.status, Election.DRAFT)

        Voter.objects.filter(reg_number="2021/245678").update(
            face_embedding=FAKE_FACES["ada"], registered_at=timezone.now()
        )
        self.call("open")
        self.client.post(reverse("vote_start"), {"reg_number": "2021/245678", "face_image": photo("bola")})
        self.client.post(reverse("vote_start"), {"reg_number": "2021/245678", "face_image": photo("ada")})
        ballot = {f"position_{p.pk}": p.candidates.first().pk for p in election.positions.all()}
        self.client.post(reverse("ballot"), {**ballot, "face_image": photo("ada-again")})
        self.assertEqual(Participation.objects.count(), 1)

        report = self.call("report")
        self.assertIn("   1  Accreditations (face matched)", report)
        self.assertIn("   1  Ballots cast", report)
        self.assertIn("Wrong-face rejections: 1 of 3 scans", report)

        self.call("close")
        election.refresh_from_db()
        self.assertTrue(election.results_public)

        self.call("reset", "--faces")
        election.refresh_from_db()
        self.assertEqual((Vote.objects.count(), Participation.objects.count()), (0, 0))
        self.assertEqual(election.status, Election.DRAFT)
        self.assertFalse(Voter.objects.exclude(registered_at=None).exists())
        self.assertIn("   0  Accreditations", self.call("report"))


@override_settings(
    ALLOWED_HOSTS=["localhost", ".trycloudflare.com"],
    CSRF_TRUSTED_ORIGINS=["https://*.trycloudflare.com"],
)
class TunnelTests(TestCase):
    """Phones reach the laptop through an https tunnel that forwards plain http."""

    def test_form_post_through_tunnel_passes_csrf(self):
        client = self.client_class(enforce_csrf_checks=True)
        host = "quiet-river-1234.trycloudflare.com"
        client.get(reverse("register"), HTTP_HOST=host)
        token = client.cookies["csrftoken"].value
        response = client.post(
            reverse("register"), {"csrfmiddlewaretoken": token},
            HTTP_HOST=host, HTTP_ORIGIN=f"https://{host}",
        )
        self.assertEqual(response.status_code, 200)  # form errors, not a 403
