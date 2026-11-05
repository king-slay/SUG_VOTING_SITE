UNN SUG E-VOTING: GUIDE FOR THE DEFENCE TEAM
============================================
(c) 2026 KingSlay. All rights reserved.

The site runs on a Windows laptop. A free Cloudflare link puts it on the internet,
so anyone can open it on their phone by scanning a QR code. You do not need to
know programming to use it. Everything below is a double-click or a web page.

What the laptop needs: Windows 10 or 11, internet, a webcam, and about 4 GB free space.


1. FIRST TIME ON A LAPTOP (about 15-30 minutes, needs good internet)
--------------------------------------------------------------------
 1. Download the project:
    https://github.com/king-slay/SUG_VOTING_SITE/archive/refs/heads/main.zip
    Right-click the zip, choose "Extract All", and open the extracted folder.
    (Or copy the folder from another laptop; see section 5.)
 2. Open the "defence" folder and double-click  install.bat
    It installs Python, the Cloudflare tool, all packages and the face models.
    If Windows asks "Do you want to allow this app to make changes?", click Yes.
 3. Near the end it asks you to create the FIRST CHAIR ACCOUNT:
      Username: something like  chair
      Email:    just press Enter
      Password: type it twice (it does not show while you type; write it down)
 4. When it says "All set", a "Start UNN Voting" icon is on the desktop.

You can run install.bat again at any time. It skips anything already installed.


2. EVERY TIME YOU WANT THE SITE RUNNING
---------------------------------------
 1. Double-click "Start UNN Voting" on the desktop (or defence\start.bat).
 2. Wait. A browser page opens with a big QR code and the link. A second black
    window shows the site's log. Leave both windows open.
 3. Wait about one minute until the log window says "Face models loaded".
    Then people can scan the QR code with their phone camera and use the site.
 4. To stop: click the first window and press Enter.

The link is different every time you start, so show or print the QR code only
after starting. The laptop must stay on and connected for the link to work.


3. COMMITTEE (ADMIN) ACCOUNTS
-----------------------------
Every committee member gets their OWN username and password. Do not share one
account: the audit log records which account did what.

 - Sign in: open the link and add  /staff/login/  at the end, or click
   "Committee" at the top once signed in.
 - Add members (chair only): Committee tab > "Add a member". Make one account
   for each of the admins. Tick "Chair" for anyone who should also manage
   accounts. It is wise to have at least two chairs.
 - Members change their own password under "My password".
 - Forgotten password: a chair opens Committee > "New password" for that person.
 - Someone leaving: a chair clicks "Switch off" on their account.
 - Nobody can switch off or demote their own account, so a chair always remains.
 - If every chair is locked out: open the project folder, click the address bar,
   type  cmd  and press Enter, then run:
       venv\Scripts\python manage.py createsuperuser


4. RUNNING AN ELECTION (the order matters)
------------------------------------------
 1. Voter roll: Voter roll > "Upload roll". A CSV or Excel (.xlsx) file with the
    columns  full_name, reg_number, faculty, department, level
    ("Download a template CSV" gives a ready file.)
 2. Students register: on the home page, "Register". They enter their details
    exactly as on the roll and take 3 face photos. This only works while no
    election is open.
 3. Create the election: Dashboard > "New election", then add positions and the
    candidates for each position (photos optional).
 4. Open voting: on the election page, "Open voting". Registration closes and the
    ballot can no longer be changed.
 5. Students vote: "Vote", reg number, face scan, choose candidates, submit.
    Each student can vote once. 5 failed face scans lock a reg number for 15 minutes.
 6. Close voting, then "Publish results" to show them on the public site.
    Live results and a CSV download are on the committee results page.


NEW SESSION (students who finished leave the roll)
 - Voter roll > choose a Level (and/or Faculty) > Filter > "Remove these students".
   Type the number shown to confirm. Example: remove 500 level after they graduate.
 - Or, with no filter, "Clear whole roll", then upload the new list of students.
 - Removed students lose their face registration. Results and turnout of past
   elections are kept. Removing is not possible while voting is open.


5. MOVING TO ANOTHER LAPTOP
---------------------------
 1. Stop the site on the old laptop (press Enter in its window).
 2. Copy the WHOLE project folder to the new laptop (USB or Google Drive).
    The voter roll, registered faces, elections, votes and committee accounts
    are in the files  db.sqlite3  and the  media  folder, so they come along.
 3. On the new laptop, run defence\install.bat once (section 1, step 2).
    It notices the folder came from another computer and sets itself up again.
    It does not ask for a chair account if one already came with the folder.
 4. Start as usual.
Only run the site on ONE laptop at a time. Two laptops do not share data.


6. IF SOMETHING GOES WRONG
--------------------------
 - "No public link yet": the internet is down or slow. Check it, stop and start
   again. On the laptop itself the site still works at http://localhost:8000
 - The first face scan is slow or fails: wait for "Face models loaded" in the
   log window.
 - The phone camera does not open: use the https link from the QR code (phones
   only allow the camera on https), and allow camera access when asked.
 - A student's face keeps being refused: good front light, no cap,
   face filling the oval. If they registered badly, a committee member opens
   Voter roll > the student > "Clear face registration" so they can register again
   (only while voting is closed).
 - Something red in a black window: take a photo or screenshot of it and send
   it to the developer.
