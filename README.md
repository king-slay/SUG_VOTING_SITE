# UNN SUG E-Voting

A web-based facial recognition e-voting system for Students' Union Government
elections at the University of Nigeria, Nsukka. Built with Django, MySQL,
OpenCV, InsightFace's ArcFace model and DeepFace.

## How it works

1. **Voter roll.** The electoral committee uploads a CSV or Excel (.xlsx)
   sheet of eligible students at `/staff/roll/upload/` with these headers
   (extra columns are ignored):
   `full_name, reg_number, faculty, department, level`
   (see `sample_voter_roll.csv`). Re-uploading updates existing students and
   keeps their face registration. If any row is invalid nothing is saved.
2. **Registration.** At `/register/` a student enters their details. They are
   cross-checked against the roll (case and extra spaces are ignored). The
   student adds email and phone and captures their face with the webcam. The
   camera takes three photos a moment apart; each is turned into an embedding
   (ArcFace, see *Face recognition* below), and if they agree, their average is stored. Every face scan
   first passes a liveness check (see below). A face that is
   already registered to another reg number is refused, so one person cannot
   register twice. Registration closes while an election is open.
3. **Election day.** At `/vote/` the student enters their reg number and scans
   their face (accreditation). The face must be close enough to the registered
   one *and* clearly closer to it than to any other registered student, so a
   look-alike (e.g. a sibling) is refused. If it matches, they get the ballot, choose one
   candidate per position, and their face is checked **again** when they
   submit. The ballot must be submitted within 10 minutes of accreditation.
4. **One vote per student** is enforced by a database constraint. The system
   stores *that* a student voted (`Participation`) separately from *what* was
   voted (`Vote`), and `Vote` has no link to the voter, so ballots are secret.
5. **Results.** Committee members see live results and turnout at
   `/staff/results/<id>/` (auto-refreshes every 10 seconds). After closing an
   election, tick *Results public* to publish them at `/results/<id>/`.
6. **Audit log.** Registrations, accreditations, failed face matches, votes
   cast (without choices, with the face-match distance), roll uploads and election open/close are logged at
   `/staff/audit/`. Five failed face scans in 15 minutes locks that reg number
   for 15 minutes.

## Running it locally

Python 3.10 to 3.12 is safest for TensorFlow.

```bash
python -m venv venv
venv\Scripts\activate            # Windows
# source venv/bin/activate       # macOS / Linux
pip install -r requirements.txt  # remove mysqlclient first if you only want SQLite
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open http://127.0.0.1:8000. The committee signs in at `/staff/login/` with
the account made by `createsuperuser`. Add more committee members in `/admin/`
(Users, tick *Staff status*).

The first time `runserver` starts it downloads the ArcFace recognition model
(InsightFace's 288 MB `buffalo_l.zip`, of which it keeps the 174 MB
`w600k_r50.onnx`) to `~/.unnvote/models`, and the liveness model (MiniFASNet) to
`~/.deepface`. After that, `runserver` loads the models in the background as it
starts (it prints "Face models loaded"), so the first voter after a restart does
not wait for them. If the download fails, download `buffalo_l.zip` from
https://github.com/deepinsight/insightface/releases/tag/v0.7 yourself and put
`w600k_r50.onnx` from it in `~/.unnvote/models`.

**Camera access only works on `localhost` or over `https`.** To test from a
phone, see *Practice election* below.

## Setting up an election

Everything is done from the committee pages at `/staff/`:

1. **Voter roll** tab: upload the roll, then search it, filter by faculty or
   registration, open a student to clear a bad face registration or remove
   them, and download the list as CSV.
2. Let students register.
3. **Elections** tab: create an election, add its positions (in ballot order)
   and candidates with photo, department and manifesto. The page lists what is
   still missing before voting can open.
4. On election day press **Open voting**. The ballot is locked from then on.
   Press **Close voting** when polls close, then **Publish results**.
5. The results page can be downloaded as CSV or printed.

## Practice election (phones over https)

A mock SUG election for a test run with a few students on their own phones.
Everyone uses a made-up identity from `practice/practice_roll.csv`.

```bash
python manage.py practice_election setup    # roll, election, 3 positions x 2 candidates (stays in draft)
python manage.py practice_election warmup   # download/load face models before testers arrive
python manage.py practice_election open     # after everyone has registered
python manage.py practice_election close    # stop voting and publish results
python manage.py practice_election report   # counts and face-match distances for the findings
python manage.py practice_election reset --faces   # wipe ballots (and face registrations) to run again
```

Phones need https for the camera. The simplest way is a free Cloudflare quick
tunnel (no account): install `cloudflared` (Windows: `winget install --id
Cloudflare.cloudflared`), then in two terminals:

```powershell
# terminal 1
python manage.py runserver 8000

# terminal 2
cloudflared tunnel --url http://localhost:8000
```

`cloudflared` prints an `https://<random-words>.trycloudflare.com` address.
Open that on the phones. The address changes each time `cloudflared` restarts.
While `DJANGO_DEBUG` is on (the default), the site accepts `*.trycloudflare.com`
addresses without extra settings.

## Hosting (Oracle Cloud Always Free)

`deploy/setup.sh` installs the site on a fresh Ubuntu 24.04 server: MySQL,
the app under gunicorn (one worker, so one copy of the face models in memory),
and Caddy for HTTPS with an automatic certificate. The address is
`https://<public-ip-with-dashes>.sslip.io` unless `DOMAIN` is set.

1. Create an Ampere A1 instance (Ubuntu 24.04, 2 OCPU / 12 GB is plenty).
2. In its subnet's security list, add ingress rules for TCP ports 80 and 443
   from `0.0.0.0/0`.
3. SSH in and run:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/king-slay/SUG_VOTING_SITE/main/deploy/setup.sh -o setup.sh
   sudo bash setup.sh
   sudo unnvote-manage createsuperuser
   ```

Settings (database password, secret key) live in `/etc/unnvote.env`. Run
`sudo bash setup.sh` again to update to the latest code; `sudo unnvote-manage
<command>` runs any `manage.py` command, e.g. `practice_election setup`.
Logs: `journalctl -u unnvote -f`.

With `DJANGO_DEBUG=false` the site refuses to start without `DJANGO_SECRET_KEY`,
sends secure cookies and HSTS, and serves registered face photos only to
committee members (candidate photos stay public).

## Face recognition

Each snapshot goes through three steps (`voting/faces.py`):

1. **Find the face.** OpenCV's YuNet detector finds the face and five landmarks
   (eyes, nose, mouth corners). No face, more than one face, or a face too far
   from the camera is refused with a message telling the voter what to fix.
2. **Liveness.** DeepFace's MiniFASNet checks the face is live (below).
3. **Recognise.** The face is aligned on its landmarks and InsightFace's ArcFace
   model (`buffalo_l` / `w600k_r50`, run with ONNX Runtime, so no compiler is
   needed on Windows) turns it into 512 numbers. Two faces are compared by cosine
   distance.

ArcFace replaced DeepFace's Facenet512 in November 2026 because Facenet512 let a
sibling pass as his brother in the practice election. On DeepFace's 300 labelled
test photo pairs, the closest two different people scored 0.80 with ArcFace
against 0.48 with Facenet512, and a scan takes about 0.5 s against about 2 s.
Face records made with Facenet512 are cleared by migration `0002`, so those
students register again.

## Liveness check (anti-spoofing)

Every face scan (registration, accreditation and ballot submit) runs DeepFace's
MiniFASNet liveness model before matching. It looks at texture, glare, colour
and edges in a single snapshot and rejects a printed photo or a phone/laptop
screen held up to the camera. A rejected scan is logged as `spoof_rejected` in
the audit log and, on election day, counts towards the five-failures lockout.

Limits: it judges one still frame, so a very sharp, well-lit replay on a large
screen, a 3D mask, or a deepfake fed through a virtual webcam can still get
through. It can also wrongly reject a real face in very dark or backlit
conditions; the voter just tries again in better light. Turn it off with
`FACE_ANTI_SPOOFING=false` only for debugging.

## Configuration (environment variables)

| Variable | Default | Purpose |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | dev key | Set a long random value in production |
| `DJANGO_DEBUG` | `true` | Set `false` in production |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` (plus `.trycloudflare.com` while debugging) | Comma-separated host names |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://*.trycloudflare.com` while debugging, else empty | e.g. `https://vote.example.com` |
| `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST`, `MYSQL_PORT` | | Use MySQL when `MYSQL_DATABASE` is set, otherwise SQLite |
| `FACE_MODEL_DIR` | `~/.unnvote/models` | Where the ArcFace model is downloaded to |
| `FACE_MATCH_THRESHOLD` | `0.45` | Max cosine distance to accept a face match |
| `FACE_MATCH_MARGIN` | `0.10` | Refuse a scan when another registered face is within this distance of the claimed one (too close to call, e.g. siblings) |
| `FACE_ENROL_CONSISTENCY` | `0.25` | Registration takes 3 photos and stores their average; refused if any two differ by more than this |
| `FACE_DUPLICATE_THRESHOLD` | same as `FACE_MATCH_THRESHOLD` | Distance under which a new registration counts as an already-registered face |
| `FACE_ANTI_SPOOFING` | `true` | Liveness check that rejects photos and screens held up to the camera |
| `FACE_MIN_SIZE` | `80` | Smallest face (pixels) accepted; smaller means the voter is too far away |
| `VOTE_SESSION_MINUTES` | `10` | Time allowed between accreditation and submitting the ballot |

## Tests

```bash
python manage.py test voting
```

The tests fake the face recognition step, so they run without a camera.

## Project layout

```
unnvote/          Django settings and root URLs
voting/
  models.py       Voter, Election, Position, Candidate, Participation, Vote, AuditLog
  roll.py         CSV voter roll import
  faces.py        Face detection (YuNet), liveness (DeepFace), ArcFace embedding and matching
  face_models/    The YuNet detector model (230 KB)
  views.py        Registration, accreditation, ballot, public results
  staff_views.py  Committee dashboard, roll upload, live results, audit log
  management/commands/practice_election.py  Mock election setup, report, reset
  admin.py        Django admin (elections, candidates, open/close actions)
  tests.py
practice/         Made-up voter roll for the practice election
templates/        HTML templates
static/           CSS, camera.js (webcam capture and live positioning hints), fonts/ (Schibsted Grotesk, OFL)
```
