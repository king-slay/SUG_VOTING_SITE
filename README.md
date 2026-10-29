# UNN SUG E-Voting

A web-based facial recognition e-voting system for Students' Union Government
elections at the University of Nigeria, Nsukka. Built with Django, MySQL,
OpenCV and DeepFace.

## How it works

1. **Voter roll.** The electoral committee uploads a CSV of eligible students
   at `/staff/roll/` with these headers:
   `full_name, reg_number, faculty, department, level`
   (see `sample_voter_roll.csv`). Re-uploading updates existing students and
   keeps their face registration. If any row is invalid nothing is saved.
2. **Registration.** At `/register/` a student enters their details. They are
   cross-checked against the roll (case and extra spaces are ignored). The
   student adds email and phone and captures their face with the webcam. The
   face is turned into an embedding (Facenet512) and stored. Every face scan
   first passes a liveness check (see below). A face that is
   already registered to another reg number is refused, so one person cannot
   register twice. Registration closes while an election is open.
3. **Election day.** At `/vote/` the student enters their reg number and scans
   their face (accreditation). If it matches, they get the ballot, choose one
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

Open http://127.0.0.1:8000. The committee logs in at `/admin/` and then uses
`/staff/`.

The first face scan downloads the Facenet512 (95 MB), RetinaFace and liveness
(MiniFASNet) models to `~/.deepface`, so it is slow once. After that,
`runserver` loads the models in the background as it starts (it prints
"Face models loaded"), so the first voter after a restart does not wait for them.

**Camera access only works on `localhost` or over `https`.** To test from a
phone, see *Practice election* below.

## Setting up an election

1. Upload the voter roll at `/staff/roll/`.
2. Let students register.
3. In `/admin/`, add an Election, its Positions, and Candidates for each
   position.
4. On election day select the election and run the **Open voting** action.
   Run **Close voting** when polls close.

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
# terminal 1 (PowerShell)
$env:DJANGO_ALLOWED_HOSTS = "localhost,127.0.0.1,.trycloudflare.com"
$env:DJANGO_CSRF_TRUSTED_ORIGINS = "https://*.trycloudflare.com"
python manage.py runserver 8000

# terminal 2
cloudflared tunnel --url http://localhost:8000
```

`cloudflared` prints an `https://<random-words>.trycloudflare.com` address.
Open that on the phones. The address changes each time `cloudflared` restarts.
On macOS/Linux use `export NAME=value` instead of `$env:NAME = "value"`.

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
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated host names |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | | e.g. `https://vote.example.com` |
| `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST`, `MYSQL_PORT` | | Use MySQL when `MYSQL_DATABASE` is set, otherwise SQLite |
| `FACE_MODEL` | `Facenet512` | DeepFace model |
| `FACE_DETECTOR` | `retinaface` | DeepFace face detector (`opencv` is faster but misses more faces) |
| `FACE_MATCH_THRESHOLD` | `0.30` | Max cosine distance to accept a face match |
| `FACE_DUPLICATE_THRESHOLD` | same as `FACE_MATCH_THRESHOLD` | Distance under which a new registration counts as an already-registered face |
| `FACE_ANTI_SPOOFING` | `true` | Liveness check that rejects photos and screens held up to the camera |
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
  faces.py        DeepFace embedding and matching
  views.py        Registration, accreditation, ballot, public results
  staff_views.py  Committee dashboard, roll upload, live results, audit log
  management/commands/practice_election.py  Mock election setup, report, reset
  admin.py        Django admin (elections, candidates, open/close actions)
  tests.py
practice/         Made-up voter roll for the practice election
templates/        HTML templates
static/           CSS, camera.js (webcam capture and live positioning hints), fonts/ (Schibsted Grotesk, OFL)
```
